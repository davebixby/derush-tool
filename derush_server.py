"""
DERUSH TOOL — Outil de dérushage multi-projet
Serveur HTTP avec gestion de projets, scan de médias, annotations, exports NLE.
"""
import http.server, json, os, sys, subprocess, csv, re, uuid, io, hashlib, secrets, shutil, socket, socketserver, base64, struct as _struct, sqlite3
import xml.etree.ElementTree as ET
import copy, threading, urllib.request, urllib.error, time as _time
from pathlib import Path
from datetime import datetime, timedelta
from urllib.parse import urlparse, unquote, parse_qs, quote as _urlquote
from collections import Counter
import mimetypes

# ─── Heartbeat / auto-shutdown ───
_last_heartbeat = _time.time()
_HEARTBEAT_TIMEOUT = 12  # seconds without heartbeat → exit

def _heartbeat_watcher():
    _time.sleep(20)  # grace period on startup (browser opening)
    while True:
        _time.sleep(3)
        if _time.time() - _last_heartbeat > _HEARTBEAT_TIMEOUT:
            os._exit(0)

threading.Thread(target=_heartbeat_watcher, daemon=True).start()

class ThreadedHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True

# Suppress console window for subprocess calls on Windows (PyInstaller no-console builds)
_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0

# ─── App dir (handles PyInstaller frozen bundles) ───
if getattr(sys, 'frozen', False):
    # Exe: data in %APPDATA%\DerushTool (persists across rebuilds/moves)
    APP_DIR = Path(os.environ.get('APPDATA', str(Path.home()))) / 'DerushTool'
    APP_DIR.mkdir(exist_ok=True, parents=True)
    BUNDLE_DIR = Path(sys._MEIPASS)  # bundled HTML/assets (read-only)
else:
    APP_DIR = Path(__file__).parent
    BUNDLE_DIR = APP_DIR

# ─── Config ───
CONFIG_FILE  = APP_DIR / "derush_config.json"
PROFILE_FILE = APP_DIR / "derush_profile.json"

def _load_config():
    if CONFIG_FILE.exists():
        try:
            return json.loads(CONFIG_FILE.read_text(encoding='utf-8'))
        except Exception:
            pass
    return {}

def save_config(data):
    CONFIG_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')

def load_profile():
    if PROFILE_FILE.exists():
        try:
            return json.loads(PROFILE_FILE.read_text(encoding='utf-8'))
        except Exception:
            pass
    return None

def save_profile(data):
    PROFILE_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')

CONFIG = _load_config()
IS_CONFIGURED = CONFIG.get('configured', False)

# ─── Crash logger ───────────────────────────────────────────────────────────
# Capture les exceptions Python (main + threads) ET les erreurs JS (via /api/crash).
# Toutes les entrées vont dans %APPDATA%\DerushTool\crashes.jsonl (1 JSON par ligne).
# Consultation via GET /api/crashes (les 100 derniers) ou /admin/crashes pour la page.
CRASH_LOG = APP_DIR / 'crashes.jsonl'
_CRASH_LOCK = threading.Lock()

def _log_crash(entry):
    """Append a crash entry as a single JSON line. Best-effort, never raises."""
    try:
        entry = dict(entry)
        entry.setdefault('ts', datetime.now().isoformat(timespec='seconds'))
        entry.setdefault('platform', sys.platform)
        with _CRASH_LOCK:
            with open(CRASH_LOG, 'a', encoding='utf-8') as f:
                f.write(json.dumps(entry, ensure_ascii=False) + '\n')
    except Exception:
        pass

def _read_crashes(limit=100):
    if not CRASH_LOG.exists():
        return []
    try:
        with open(CRASH_LOG, 'r', encoding='utf-8') as f:
            lines = f.readlines()[-limit:]
        out = []
        for ln in lines:
            ln = ln.strip()
            if not ln:
                continue
            try:
                out.append(json.loads(ln))
            except Exception:
                pass
        return out
    except Exception:
        return []

def _py_excepthook(exc_type, exc_value, exc_tb):
    """Intercepte les exceptions non-catchées du main thread."""
    import traceback
    _log_crash({
        'source': 'python',
        'thread': 'main',
        'type': exc_type.__name__ if exc_type else 'Unknown',
        'message': str(exc_value),
        'stack': ''.join(traceback.format_exception(exc_type, exc_value, exc_tb)),
    })
    # Conserve le comportement par défaut (print stderr)
    sys.__excepthook__(exc_type, exc_value, exc_tb)

def _py_thread_excepthook(args):
    """Intercepte les exceptions non-catchées des threads (Python 3.8+)."""
    import traceback
    _log_crash({
        'source': 'python',
        'thread': args.thread.name if args.thread else 'unknown',
        'type': args.exc_type.__name__ if args.exc_type else 'Unknown',
        'message': str(args.exc_value),
        'stack': ''.join(traceback.format_exception(args.exc_type, args.exc_value, args.exc_traceback)),
    })

sys.excepthook = _py_excepthook
try:
    threading.excepthook = _py_thread_excepthook
except AttributeError:
    pass  # Python < 3.8 — pas critique

# ─── Version + Changelog ────────────────────────────────────────────────────
def _read_version():
    """Lit la version depuis le fichier VERSION (bundled)."""
    try:
        p = BUNDLE_DIR / 'VERSION'
        return p.read_text(encoding='utf-8').strip()
    except Exception:
        return 'dev'

def _read_changelog():
    """Parse CHANGELOG.md → {current_version, entries: [{version, date, body}, ...]}"""
    try:
        p = BUNDLE_DIR / 'CHANGELOG.md'
        content = p.read_text(encoding='utf-8')
    except Exception:
        return {'current_version': _read_version(), 'entries': []}
    # Sections par version : "## [X.Y.Z] — date" ou "## [X.Y.Z] - date"
    import re as _re
    entries = []
    blocks = _re.split(r'(?m)^##\s+\[([^\]]+)\]\s*[—\-]\s*(\d{4}-\d{2}-\d{2})', content)
    # blocks = [pre_header, version1, date1, body1, version2, date2, body2, ...]
    for i in range(1, len(blocks), 3):
        v, d, body = blocks[i].strip(), blocks[i+1].strip(), blocks[i+2].strip()
        # Coupe le body au prochain header de niveau 2 (déjà fait par split mais clean)
        entries.append({'version': v, 'date': d, 'body': body})
    return {'current_version': _read_version(), 'entries': entries}

def _migrate_old_users():
    """Convert old per-project password_hash users to the new profile model."""
    if not PROFILE_FILE.exists():
        projects_dir = Path(CONFIG.get('projects_dir', str(APP_DIR / 'projects')))
        for pf in projects_dir.glob('*.derush.json'):
            try:
                data = json.loads(pf.read_text(encoding='utf-8'))
                for u in data.get('users', []):
                    if u.get('password_hash') and (u.get('is_admin') or True):
                        save_profile({'username': u.get('name', u.get('username', 'Admin')), 'password_hash': u['password_hash']})
                        break
            except Exception:
                pass
            if PROFILE_FILE.exists():
                break

_migrate_old_users()

PROJECTS_DIR = Path(CONFIG.get('projects_dir', str(APP_DIR / 'projects')))
PROJECTS_DIR.mkdir(exist_ok=True, parents=True)
WAVEFORMS_DIR = Path(CONFIG.get('waveforms_dir', str(APP_DIR / 'waveforms')))
WAVEFORMS_DIR.mkdir(exist_ok=True, parents=True)
THUMBNAILS_DIR = Path(CONFIG.get('thumbnails_dir', str(APP_DIR / 'thumbnails')))
THUMBNAILS_DIR.mkdir(exist_ok=True, parents=True)
BACKUPS_DIR = Path(CONFIG.get('backups_dir', str(PROJECTS_DIR / 'backups')))
BACKUPS_DIR.mkdir(exist_ok=True, parents=True)
PORT     = CONFIG.get('port', 8765)

def _default_binary(name):
    bundled = BUNDLE_DIR / (name + ('.exe' if sys.platform == 'win32' else ''))
    return str(bundled) if bundled.exists() else name

def _resolve_binary(name):
    cfg = CONFIG.get(name)
    # Honour an explicit absolute path from config (user override).
    # Ignore bare names like 'ffmpeg' — PATH is unreliable when launched from a
    # desktop app (Dock/Finder) and would silently break thumbnail generation.
    if cfg and os.path.isabs(cfg):
        return cfg
    return _default_binary(name)

FFMPEG   = _resolve_binary('ffmpeg')
FFPROBE  = _resolve_binary('ffprobe')

# Throttle concurrent ffmpeg/ffprobe processes. ThreadedHTTPServer would otherwise
# fan out as many ffmpeg as there are inflight HTTP requests — a sidebar hover that
# triggers compute_strip (12 ffmpeg per clip) over 20 clips = 240 simultaneous
# processes saturating CPU + RAM. The semaphore caps it at a sane fraction of cores.
_FFMPEG_MAX_CONCURRENT = max(2, min(8, (os.cpu_count() or 4) // 2))
_ffmpeg_sem = threading.BoundedSemaphore(_FFMPEG_MAX_CONCURRENT)

def _ffmpeg_run(cmd, timeout=30, capture_output=True, text=False):
    """Bounded wrapper around subprocess.run for ffmpeg/ffprobe invocations."""
    with _ffmpeg_sem:
        return subprocess.run(cmd, capture_output=capture_output, text=text,
                              timeout=timeout, creationflags=_NO_WINDOW)

# Dedup running computations. Two HTTP requests asking for the same uncached
# thumbnail/strip/waveform must NOT both spawn the underlying ffmpeg work — the
# second one waits for the first instead. Keyed by an arbitrary string per artefact.
_compute_locks_lock = threading.Lock()
_compute_locks = {}  # key -> threading.Event (set when first worker finishes)

def _dedupe_compute(key, fn, wait_timeout=120):
    """Run fn() at most once per key concurrently. Concurrent callers wait."""
    with _compute_locks_lock:
        evt = _compute_locks.get(key)
        initiator = evt is None
        if initiator:
            evt = threading.Event()
            _compute_locks[key] = evt
    if not initiator:
        evt.wait(timeout=wait_timeout)
        return None
    try:
        return fn()
    finally:
        evt.set()
        with _compute_locks_lock:
            _compute_locks.pop(key, None)

# Sync credentials — hardcoded, overridable via config for developer use
SYNC_URL = CONFIG.get('sync_url', 'https://sebastiendelahaye.be/derush_sync.php')
SYNC_KEY = CONFIG.get('sync_key', 'drift2026')

# Sync runtime state — always configured since URL is hardcoded
_sync_status = {'configured': True, 'online': None, 'last_sync': None, 'error': None}
_sync_lock   = threading.Lock()

def get_lan_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return '127.0.0.1'

# In-memory sessions: token -> {user_id, project_id, root_path, name, color}
SESSIONS = {}

# WebSocket clients: {project_id: [[sock, token], ...]}
_ws_clients: dict = {}
_ws_clients_lock = threading.Lock()

# Session live : un seul leader par projet à la fois. Les actions du leader
# (select_clip, seek, play, pause) sont broadcasted aux autres clients via WS.
_session_leaders = {}        # pid → username (current leader)
_session_leaders_lock = threading.Lock()
_WS_MAGIC = '258EAFA5-E914-47DA-95CA-C5AB0DC85B11'

def _ws_accept(key):
    return base64.b64encode(hashlib.sha1((key + _WS_MAGIC).encode()).digest()).decode()

def _ws_send(sock, message):
    data = message.encode('utf-8') if isinstance(message, str) else message
    n = len(data)
    if n < 126:    header = bytes([0x81, n])
    elif n < 65536: header = bytes([0x81, 126]) + _struct.pack('>H', n)
    else:           header = bytes([0x81, 127]) + _struct.pack('>Q', n)
    try: sock.sendall(header + data); return True
    except Exception: return False

def _ws_recv(sock):
    try:
        raw = b''
        while len(raw) < 2:
            c = sock.recv(2 - len(raw))
            if not c: return None
            raw += c
        opcode = raw[0] & 0x0F
        masked = bool(raw[1] & 0x80)
        n = raw[1] & 0x7F
        if n == 126:
            b = b''
            while len(b) < 2: b += sock.recv(2 - len(b)) or b''
            n = _struct.unpack('>H', b)[0]
        elif n == 127:
            b = b''
            while len(b) < 8: b += sock.recv(8 - len(b)) or b''
            n = _struct.unpack('>Q', b)[0]
        mask = sock.recv(4) if masked else b'\x00\x00\x00\x00'
        payload = b''
        while len(payload) < n:
            chunk = sock.recv(min(4096, n - len(payload)))
            if not chunk: return None
            payload += chunk
        if masked: payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        return opcode, payload
    except Exception: return None

def _ws_broadcast(project_id, message, exclude_token=None):
    payload = json.dumps(message, ensure_ascii=False)
    dead = []
    with _ws_clients_lock:
        clients = list(_ws_clients.get(project_id, []))
    for entry in clients:
        if entry[1] == exclude_token: continue
        if not _ws_send(entry[0], payload): dead.append(entry)
    if dead:
        with _ws_clients_lock:
            for d in dead:
                try: _ws_clients.get(project_id, []).remove(d)
                except Exception: pass

_PBKDF2_ITERS = 200_000

def hash_password(pw, salt=None):
    """Hache un mot de passe en PBKDF2-HMAC-SHA256 (salé).
    Format stocké : 'pbkdf2$<iters>$<salt_hex>$<hash_hex>'."""
    if salt is None:
        salt = secrets.token_bytes(16)
    elif isinstance(salt, str):
        salt = bytes.fromhex(salt)
    dk = hashlib.pbkdf2_hmac('sha256', pw.encode('utf-8'), salt, _PBKDF2_ITERS)
    return f"pbkdf2${_PBKDF2_ITERS}${salt.hex()}${dk.hex()}"

def is_legacy_hash(stored):
    """True si le hash est dans l'ancien format SHA-256 nu (à re-hacher)."""
    return bool(stored) and not str(stored).startswith('pbkdf2$')

def verify_password(pw, stored):
    """Vérifie un mot de passe contre un hash stocké. Gère le nouveau format
    PBKDF2 et l'ancien SHA-256 nu (pour la migration transparente)."""
    if not stored:
        return False
    stored = str(stored)
    if stored.startswith('pbkdf2$'):
        try:
            _, iters, salt_hex, hash_hex = stored.split('$')
            dk = hashlib.pbkdf2_hmac('sha256', pw.encode('utf-8'),
                                     bytes.fromhex(salt_hex), int(iters))
            return secrets.compare_digest(dk.hex(), hash_hex)
        except Exception:
            return False
    # Ancien format : SHA-256 nu, non salé
    return secrets.compare_digest(hashlib.sha256(pw.encode('utf-8')).hexdigest(), stored)

# ─── Anti-brute-force login (audit 2.4) ──────────────────────────────────────
_login_fails = {}            # ip -> [timestamps des échecs récents]
_login_fails_lock = threading.Lock()
_LOGIN_MAX_FAILS = 8
_LOGIN_WINDOW = 300          # secondes

def _login_throttled(ip):
    now = _time.time()
    with _login_fails_lock:
        fails = [t for t in _login_fails.get(ip, []) if now - t < _LOGIN_WINDOW]
        _login_fails[ip] = fails
        return len(fails) >= _LOGIN_MAX_FAILS

def _login_record_fail(ip):
    with _login_fails_lock:
        _login_fails.setdefault(ip, []).append(_time.time())

def _login_clear(ip):
    with _login_fails_lock:
        _login_fails.pop(ip, None)

# Durée de vie par défaut d'un lien de review partagé (audit 2.5)
_SHARE_TTL_DAYS = 30

def get_session(handler):
    """Extract session from Authorization header or cookie."""
    auth = handler.headers.get('Authorization', '')
    if auth.startswith('Bearer '):
        token = auth[7:]
        return SESSIONS.get(token)
    return None

def require_auth(handler):
    """Return session or send 401. Usage: s = require_auth(self); if not s: return"""
    s = get_session(handler)
    if not s:
        handler.send_response(401)
        handler.send_header('Content-Type', 'application/json')
        handler.end_headers()
        handler.wfile.write(b'{"error":"Non authentifi\u00e9"}')
    return s

# ─── Timecode Helpers ───

def tc_to_seconds(tc_str, fps=25):
    if not tc_str: return None
    parts = tc_str.replace(';',':').split(':')
    if len(parts) == 4:
        h, m, s, f = [int(p) for p in parts]
        return h*3600 + m*60 + s + f/fps
    return None

def seconds_to_tc(sec, fps=25):
    if sec is None: return ''
    fps_int = round(fps)
    total_frames = int(round(sec * fps_int))
    f = total_frames % fps_int
    total_secs = total_frames // fps_int
    s = total_secs % 60
    total_mins = total_secs // 60
    m = total_mins % 60
    h = total_mins // 60
    return f"{h:02d}:{m:02d}:{s:02d}:{f:02d}"

def seconds_to_rational(sec, fps=25):
    fps_int = round(fps)
    frames = int(round(sec * fps_int))
    return f"{frames}/{fps_int}s"

# ─── Media Scanner ───

def ffprobe_metadata(filepath):
    try:
        cmd = [FFPROBE, '-i', str(filepath), '-show_entries',
               'format=duration,filename:format_tags:stream=width,height,codec_name,r_frame_rate,channels,sample_rate',
               '-v', 'quiet', '-print_format', 'json']
        r = _ffmpeg_run(cmd, timeout=30, text=True)
        return json.loads(r.stdout)
    except Exception:
        return {}

def _extract_tech_metadata(fmt_tags, streams, fps=25):
    """Extract ISO, aperture, shutter_angle, focal_length from ffprobe tags.
    Works with Blackmagic, Canon, Apple/QuickTime, DJI, and generic MP4/MOV."""
    # Merge format-level + all stream-level tags (format wins on conflict)
    merged = {}
    for s in streams:
        merged.update({k: str(v).strip() for k, v in s.get('tags', {}).items() if v})
    merged.update({k: str(v).strip() for k, v in fmt_tags.items() if v})

    result = {}

    # ISO
    for key in ('ISO', 'iso', 'ISOSpeedRatings', 'SensorGain',
                'com.apple.quicktime.camera.iso', 'capture_iso'):
        v = merged.get(key, '')
        if v and v.replace('.', '', 1).isdigit():
            result['iso'] = v.split('.')[0]
            break

    # Aperture / F-number
    for key in ('ApertureValue', 'FNumber', 'aperture', 'Aperture',
                'com.apple.quicktime.camera.aperture', 'f_number', 'iris'):
        v = merged.get(key, '')
        if not v: continue
        try:
            num = float(v)
            if num > 0:
                formatted = f"f/{num:.1f}".rstrip('0').rstrip('.')
                result['aperture'] = formatted if formatted != 'f/' else f"f/{num}"
        except Exception:
            if v.lower().startswith('f/') or '/' not in v:
                result['aperture'] = v
        if 'aperture' in result:
            break

    # Shutter angle (try named angle tags first, then compute from ExposureTime + fps)
    for key in ('shutter_angle', 'ShutterSpeedAngle',
                'com.apple.quicktime.camera.shutter_angle'):
        v = merged.get(key, '')
        if v:
            result['shutter_angle'] = v if '°' in v else f"{v}°"
            break
    if 'shutter_angle' not in result:
        for key in ('ExposureTime', 'shutter_speed', 'ShutterSpeed'):
            v = merged.get(key, '')
            if not v: continue
            try:
                if '/' in v:
                    n, d = v.split('/')
                    speed = float(n) / float(d)
                else:
                    speed = float(v)
                angle = speed * fps * 360
                if 1 <= angle <= 360:
                    result['shutter_angle'] = f"{angle:.1f}°".replace('.0°', '°')
            except Exception:
                pass
            if 'shutter_angle' in result:
                break

    # Focal length
    for key in ('focal_length', 'FocalLength',
                'com.apple.quicktime.camera.focal_length',
                'com.apple.quicktime.lens', 'lens_focal_length'):
        v = merged.get(key, '')
        if not v: continue
        try:
            result['focal_length'] = f"{float(v):.0f}mm"
        except Exception:
            result['focal_length'] = v
        break

    return result


def scan_media_folder(root_path, media_exts=None):
    if media_exts is None:
        media_exts = ['.mxf', '.mp4', '.mov', '.avi', '.r3d', '.braw', '.ari']
    root = Path(root_path)
    clips = []
    for f in sorted(root.rglob('*')):
        if not f.is_file(): continue
        if f.suffix.lower() not in media_exts: continue
        if 'sub' in str(f).lower().split(os.sep) or 'proxy' in str(f).lower().split(os.sep):
            continue
        if f.stem.startswith('._'): continue

        data = ffprobe_metadata(f)
        fmt = data.get('format', {})
        tags = fmt.get('tags', {})
        streams = data.get('streams', [])

        vstream = next((s for s in streams if s.get('width')), {})
        duration = float(fmt.get('duration', 0) or 0)

        # Timecode: try format tags first, then each stream's tags
        tc_in = tags.get('timecode', '')
        if not tc_in:
            for s in streams:
                tc_in = s.get('tags', {}).get('timecode', '')
                if tc_in: break

        # Determine day from path structure
        # day = first folder component; empty if file is directly at root level
        rel = f.relative_to(root)
        parts = rel.parts
        day = parts[0] if len(parts) > 1 else ''
        folder_camera = ''
        if 'IMAGE' in parts:
            idx = list(parts).index('IMAGE')
            if idx + 1 < len(parts): folder_camera = parts[idx + 1]

        # 1. Sony XML sidecar (authoritative for TC, duration, model, tech meta)
        xml_path = f.parent / (f.stem + 'M01.XML')
        camera = folder_camera
        tech_meta = {}
        if xml_path.exists():
            xml_data = parse_sony_xml(xml_path)
            if xml_data.get('tc_in'): tc_in = xml_data['tc_in']
            if xml_data.get('duration_sec'): duration = xml_data['duration_sec']
            if xml_data.get('model'): camera = xml_data['model']
            tech_meta = {k: xml_data[k] for k in ('iso', 'aperture', 'shutter_angle', 'focal_length') if xml_data.get(k)}

        # 2. Camera model from ffprobe tags (Canon, GoPro, DJI, iPhone, Blackmagic…)
        if not camera or camera == folder_camera:
            for tag_key in ('model', 'Model', 'com.apple.quicktime.model', 'com.apple.quicktime.make'):
                val = tags.get(tag_key, '').strip()
                if val:
                    camera = val
                    break

        # FPS (needed before tech_meta extraction for shutter angle computation)
        fps_str = vstream.get('r_frame_rate', '25/1')
        try:
            num, den = fps_str.split('/')
            fps = round(int(num) / int(den), 3)
        except Exception:
            fps = 25

        # 3. Tech meta from ffprobe tags for non-Sony cameras (Blackmagic, etc.)
        #    Only fill fields not already provided by the Sony XML sidecar
        if len(tech_meta) < 4:
            probe_tech = _extract_tech_metadata(tags, streams, fps)
            for field in ('iso', 'aperture', 'shutter_angle', 'focal_length'):
                if field not in tech_meta and field in probe_tech:
                    tech_meta[field] = probe_tech[field]

        # FIX: ffprobe reads FX6 MXF timecodes in reversed byte order
        if 'FX6' in camera.upper() and tc_in:
            tparts = tc_in.replace(';', ':').split(':')
            if len(tparts) == 4:
                tc_in = ':'.join(tparts[::-1])

        width = vstream.get('width', 0)
        height = vstream.get('height', 0)

        clip_id = f"{day}_{camera}_{f.stem}".replace(' ', '_').strip('_')
        proxy_url = find_proxy(root, f)

        clips.append({
            'id': clip_id,
            'filename': f.name,
            'stem': f.stem,
            'path': str(f),
            'rel_path': str(rel),
            'day': day,
            'camera': camera,
            'resolution': f"{width}x{height}" if width else '',
            'codec': vstream.get('codec_name', ''),
            'fps': fps,
            'tc_in': tc_in,
            'duration_sec': duration,
            'duration_tc': seconds_to_tc(duration, fps) if duration else '',
            'creation_date': tags.get('creation_time', ''),
            'size_mb': round(f.stat().st_size / 1e6, 1),
            'proxy_url': f"/proxy/{proxy_url.replace(os.sep, '/')}" if proxy_url else '',
            **tech_meta
        })
    return clips

def parse_sony_xml(xml_path):
    """Returns dict: tc_in, duration_sec, model, iso, aperture, shutter_angle, focal_length."""
    result = {}
    try:
        tree = ET.parse(xml_path)
        root = tree.getroot()
        ns = {'ns': 'urn:schemas-professionalDisc:nonRealTimeMeta:ver.2.20'}
        ltc = root.find('.//ns:LtcChangeTable/ns:LtcChange', ns)
        if ltc is not None:
            raw = ltc.get('value', '')
            if len(raw) == 8:
                result['tc_in'] = f"{raw[0:2]}:{raw[2:4]}:{raw[4:6]}:{raw[6:8]}"
        dur_el = root.find('.//ns:Duration', ns)
        if dur_el is not None:
            result['duration_sec'] = int(dur_el.get('value', '0')) / 25.0
        device_el = root.find('.//ns:Device', ns)
        if device_el is not None:
            result['model'] = device_el.get('modelName', '')
        for item in root.findall('.//ns:AcquisitionRecord/ns:Group/ns:Item', ns):
            name, val = item.get('name', ''), item.get('value', '')
            if not val: continue
            if name == 'ISOSensitivity':      result['iso'] = val
            elif name == 'IrisFNumber':        result['aperture'] = f"f/{val}"
            elif name == 'ShutterSpeedAngle':  result['shutter_angle'] = f"{val}°"
            elif name == 'FocalLength':        result['focal_length'] = f"{val}mm"
    except Exception: pass
    return result

def find_proxy(root, clip_path):
    """Find proxy file for a given clip. Looks in Sub/Proxy folders near the clip."""
    root = Path(root)
    clip_stem = clip_path.stem.lower()

    # Walk up from clip's parent and search all 'Sub'/'Proxy' dirs in the subtree
    # Start from the clip's parent dir and go up 3 levels to cover XDROOT/Clip -> XDROOT/Sub
    search_roots = [clip_path.parent]
    p = clip_path.parent
    for _ in range(3):
        p = p.parent
        if p == root or not str(p).startswith(str(root)):
            break
        search_roots.append(p)

    for search_root in search_roots:
        for sub_name in ['Sub', 'sub', 'Proxy', 'proxy']:
            sub_dir = search_root / sub_name
            if sub_dir.is_dir():
                for f in sorted(sub_dir.iterdir()):
                    if f.is_file() and f.suffix.lower() in ('.mp4', '.mov'):
                        # Proxy stem must START WITH clip stem (handles DRIFT_avril0001S03)
                        if f.stem.lower().startswith(clip_stem):
                            try:
                                return str(f.relative_to(root))
                            except ValueError:
                                return str(f)

    # Broader search: rglob any Sub folder under same camera dir
    cam_dir = clip_path.parent
    for _ in range(4):
        cam_dir = cam_dir.parent
        if cam_dir == root or not str(cam_dir).startswith(str(root)):
            break
    for sub_dir in cam_dir.rglob('Sub'):
        if not sub_dir.is_dir(): continue
        for f in sorted(sub_dir.iterdir()):
            if f.is_file() and f.suffix.lower() in ('.mp4', '.mov'):
                if f.stem.lower().startswith(clip_stem):
                    try:
                        return str(f.relative_to(root))
                    except ValueError:
                        return str(f)

    # GoPro fallback: pas de Sub/ → utiliser le .LRV (proxy natif GoPro à côté
    # du MP4 original, pattern GX0001.MP4 ↔ GL0001.LRV). Le LRV est en HEVC 432p,
    # quelques MB — Chromium peut le lire si l'OS a le codec HEVC.
    clip_name = clip_path.name
    if clip_name.startswith('GX') and clip_name.upper().endswith('.MP4'):
        lrv = clip_path.parent / ('GL' + clip_name[2:-4] + '.LRV')
        if lrv.exists():
            try:
                return str(lrv.relative_to(root))
            except ValueError:
                return str(lrv)
    return ''

# Resolution-cache pour _resolve_relpath_tolerant : evite de re-walker l'arbo a
# chaque requete /thumbnail/, /proxy/, /strip/ pour le meme clip. Cleared via SIGHUP
# si jamais (mais en pratique reset au prochain redemarrage).
_relpath_resolve_cache = {}
_relpath_cache_lock = threading.Lock()

def _resolve_relpath_tolerant(root, rel):
    """Resolve `<root>/<rel>` en etant tolerant aux differences de zero-padding sur les
    segments numeriques (cas typique : XDROOT/01 vs XDROOT/1, IMAGE/02 vs IMAGE/2).

    Cas tres frequent quand un disque source est copie/transfere entre PCs et que la
    copie a perdu le zero de tete (rsync, robocopy, drag&drop Explorer parfois).

    Strategie : essaie le chemin litteral d'abord (cas rapide). Si echec, walk segment
    par segment, pour chaque segment numerique essaie aussi les variantes avec/sans
    zero-padding (1↔01, 1↔001, 12↔012, etc.). Cache le resultat positif.

    Renvoie Path() si trouve, sinon None.
    """
    root = Path(root)
    cache_key = (str(root), rel)
    with _relpath_cache_lock:
        cached = _relpath_resolve_cache.get(cache_key)
    if cached is not None:
        if cached.exists(): return cached
        # Stale (fichier supprime depuis) → on retire et on retente
        with _relpath_cache_lock:
            _relpath_resolve_cache.pop(cache_key, None)

    # Fast path : chemin litteral
    literal = root / rel
    if literal.exists() and literal.is_file():
        with _relpath_cache_lock:
            _relpath_resolve_cache[cache_key] = literal
        return literal

    # Slow path : walk segment par segment avec tolerance numerique
    segments = [s for s in rel.replace('\\', '/').split('/') if s]
    current = root
    for seg in segments:
        if not current.is_dir():
            return None
        # Variantes a essayer pour ce segment, dans cet ordre :
        # 1. Le segment litteral
        # 2. Sans zero de tete (01 → 1, 002 → 2)
        # 3. Avec zero de tete (1 → 01) — moins frequent mais possible
        candidates = [seg]
        if seg.isdigit():
            stripped = seg.lstrip('0') or '0'
            if stripped != seg: candidates.append(stripped)
            for w in (2, 3):
                padded = seg.zfill(w)
                if padded != seg and padded not in candidates:
                    candidates.append(padded)
        matched = None
        for c in candidates:
            cand = current / c
            if cand.exists():
                matched = cand
                break
        if matched is None:
            # Dernier recours : match case-insensitive (Windows est insensitif mais
            # un disque externe en NTFS depuis Linux peut avoir d'autres casses)
            try:
                seg_lower = seg.lower()
                for entry in current.iterdir():
                    if entry.name.lower() == seg_lower:
                        matched = entry
                        break
            except (OSError, PermissionError):
                pass
        if matched is None:
            return None
        current = matched

    if current.exists() and current.is_file():
        with _relpath_cache_lock:
            _relpath_resolve_cache[cache_key] = current
        return current
    return None

# ─── Project Management ───

def list_projects():
    projects = []
    for f in PROJECTS_DIR.glob('*.derush.json'):
        try:
            data = json.loads(f.read_text(encoding='utf-8'))
            projects.append({
                'id': f.stem.replace('.derush', ''),
                'name': data.get('name', ''),
                'root_path': data.get('root_path', ''),
                'modified': data.get('modified', ''),
                'clip_count': len(data.get('clips', [])),
                'user_count': len(data.get('users', []))
            })
        except Exception: pass
    return sorted(projects, key=lambda p: p.get('modified', ''), reverse=True)

# ─── Concurrence, cache & indexation projet (audit 22 mai 2026) ──────────────
# Verrou ré-entrant par projet : sérialise les cycles load-modifie-save pour
# éviter qu'une écriture concurrente en écrase une autre (lost update).
_project_locks = {}
_project_locks_guard = threading.Lock()

def _project_lock(pid):
    with _project_locks_guard:
        lk = _project_locks.get(pid)
        if lk is None:
            lk = threading.RLock()
            _project_locks[pid] = lk
        return lk

_PID_PATH_RE = re.compile(r'^/api/project/([^/]+)/')

def _pid_from_path(rawpath):
    """Extrait le pid d'une URL /api/project/<pid>/... — None sinon."""
    m = _PID_PATH_RE.match(urlparse(rawpath).path)
    return m.group(1) if m else None

# Cache mémoire des projets, invalidé par (mtime, taille) du fichier — robuste
# aux écritures externes (sync). Évite de relire+reparser 400 Ko à chaque
# requête (polling notes, WebSocket…).
_project_cache = {}
_project_cache_lock = threading.Lock()

# Indexation FTS debouncée : une rafale de saves ne déclenche qu'un réindex.
_index_timers = {}
_index_pending = {}
_index_lock = threading.Lock()

def _schedule_index(pid, data, delay=2.0):
    with _index_lock:
        _index_pending[pid] = data
        t = _index_timers.get(pid)
        if t:
            try: t.cancel()
            except Exception: pass
        def _fire():
            with _index_lock:
                d = _index_pending.pop(pid, None)
                _index_timers.pop(pid, None)
            if d is not None:
                try: _index_project_db(pid, d)
                except Exception: pass
        t = threading.Timer(delay, _fire)
        t.daemon = True
        _index_timers[pid] = t
        t.start()

def load_project(project_id):
    f = PROJECTS_DIR / f"{project_id}.derush.json"
    try:
        st = f.stat()
    except (FileNotFoundError, NotADirectoryError):
        return None
    key = (st.st_mtime_ns, st.st_size)
    with _project_cache_lock:
        cached = _project_cache.get(project_id)
        if cached and cached[0] == key:
            return copy.deepcopy(cached[1])
    try:
        data = json.loads(f.read_text(encoding='utf-8'))
    except FileNotFoundError:
        return None
    with _project_cache_lock:
        _project_cache[project_id] = (key, data)
    return copy.deepcopy(data)

def save_project(project_id, data):
    data['modified'] = datetime.now().isoformat()
    f = PROJECTS_DIR / f"{project_id}.derush.json"
    if f.exists():
        backup_dir = BACKUPS_DIR / project_id
        backup_dir.mkdir(exist_ok=True)
        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        shutil.copy2(f, backup_dir / f"{project_id}_{ts}.json")
        old_backups = sorted(backup_dir.glob('*.json'))
        for old in old_backups[:-10]:
            old.unlink(missing_ok=True)
    # Écriture atomique : .tmp puis os.replace() — jamais de fichier projet
    # tronqué si le process meurt en plein write.
    tmp = f.parent / (f.name + '.tmp')
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(tmp, f)
    # Indexation FTS debouncée — ne bloque jamais le save.
    _schedule_index(project_id, data)

def create_project(name, root_path, admin_username, color='#a78bfa'):
    pid = re.sub(r'[^a-zA-Z0-9_]', '_', name.lower()).strip('_')
    if not pid: pid = 'project_' + str(uuid.uuid4())[:8]
    admin = {
        'username': admin_username,
        'color': color,
        'root_path': str(root_path),
        'is_admin': True
    }
    data = {
        'name': name,
        'root_path': str(root_path),
        'created': datetime.now().isoformat(),
        'modified': datetime.now().isoformat(),
        'users': [admin],
        'media_extensions': ['.mxf', '.mp4', '.mov'],
        'clips': [],
        'notes': {}
    }
    data['clips'] = scan_media_folder(root_path, [e.lower() for e in data['media_extensions']])
    save_project(pid, data)
    return pid, data

def find_project_user(proj, username):
    """Find user entry in project by username (case-insensitive). Also handles old 'name' field."""
    for u in proj.get('users', []):
        uname = u.get('username') or u.get('name', '')
        if uname.lower() == username.lower():
            return u
    return None

def user_note_key(u):
    """Return the key used to look up this user's notes (supports old id-based and new username-based models)."""
    return u.get('id') or u.get('username') or u.get('name', '')

# ─── Search index (SQLite FTS5) ───
# Hybrid model: .derush.json files remain the source of truth. This DB is a
# reconstructible full-text index over notes / markers / tags / discussions /
# clip metadata. Wiped and rebuilt at startup; updated incrementally on save_project.

INDEX_DB = APP_DIR / 'index.db'
_index_lock = threading.Lock()

def _index_db():
    """Return a per-thread connection (sqlite3 disallows sharing across threads)."""
    conn = sqlite3.connect(str(INDEX_DB), timeout=30)
    conn.row_factory = sqlite3.Row
    return conn

def _init_index_db():
    """Create the FTS5 virtual table if missing. Tokenizer handles French diacritics."""
    with _index_lock:
        conn = _index_db()
        try:
            conn.execute("""
                CREATE VIRTUAL TABLE IF NOT EXISTS notes_fts USING fts5(
                    project_id UNINDEXED,
                    clip_id UNINDEXED,
                    user_id UNINDEXED,
                    source UNINDEXED,
                    text,
                    tokenize='unicode61 remove_diacritics 1'
                )
            """)
            conn.commit()
        finally:
            conn.close()

def _index_project_db(pid, proj):
    """Replace all index rows for this project with a fresh dump from proj."""
    rows = []
    clips = proj.get('clips', [])
    notes = proj.get('notes', {})
    discussions = proj.get('discussions', {})
    clip_by_id = {c['id']: c for c in clips}

    # Per-clip metadata row (filename, camera, day, tc) — searchable filenames/cameras
    for c in clips:
        meta_text = ' '.join(filter(None, [
            c.get('stem', ''), c.get('filename', ''),
            c.get('camera', ''), c.get('day', ''), c.get('tc_in', ''),
        ]))
        if meta_text.strip():
            rows.append((pid, c['id'], '', 'clip_meta', meta_text))

    # Notes / markers / tags by user
    for uid, ucnotes in notes.items():
        if not isinstance(ucnotes, dict): continue
        for cid, cn in ucnotes.items():
            if not isinstance(cn, dict): continue
            note_text = (cn.get('notes') or '').strip()
            if note_text:
                rows.append((pid, cid, uid, 'note', note_text))
            tags = cn.get('tags') or []
            if tags:
                rows.append((pid, cid, uid, 'tag', ' '.join(str(t) for t in tags)))
            for m in (cn.get('markers') or []):
                desc = (m.get('desc') or '').strip()
                if desc and desc.lower() != 'marker':
                    rows.append((pid, cid, uid, 'marker', desc))

    # Reply discussions
    for cid, by_marker in discussions.items():
        if not isinstance(by_marker, dict): continue
        for mid, replies in by_marker.items():
            for r in (replies or []):
                txt = (r.get('text') or '').strip()
                if txt:
                    rows.append((pid, cid, r.get('user_id', ''), 'reply', txt))

    with _index_lock:
        conn = _index_db()
        try:
            conn.execute("DELETE FROM notes_fts WHERE project_id = ?", (pid,))
            if rows:
                conn.executemany(
                    "INSERT INTO notes_fts(project_id, clip_id, user_id, source, text) VALUES (?,?,?,?,?)",
                    rows
                )
            conn.commit()
        finally:
            conn.close()

def _rebuild_index_full():
    """Wipe and rebuild the FTS index from all .derush.json files. Run in background at startup."""
    try:
        _init_index_db()
        with _index_lock:
            conn = _index_db()
            try:
                conn.execute("DELETE FROM notes_fts")
                conn.commit()
            finally:
                conn.close()
        for f in PROJECTS_DIR.glob('*.derush.json'):
            pid = f.stem.replace('.derush', '')
            try:
                proj = json.loads(f.read_text(encoding='utf-8'))
                _index_project_db(pid, proj)
            except Exception:
                pass
    except Exception:
        pass

def _fts_escape(q):
    """Quote individual tokens for FTS5 MATCH and append prefix-match. Handles spaces, diacritics, hyphens."""
    parts = re.findall(r"[\w\-]+", q, flags=re.UNICODE)
    if not parts: return ''
    return ' '.join(f'"{p}"*' for p in parts if p)

def search_index(query, pid=None, limit=80):
    """Run FTS5 MATCH and return [{project_id, clip_id, source, snippet, score}, ...] grouped by clip."""
    fts_q = _fts_escape(query)
    if not fts_q: return []
    sql = """
        SELECT project_id, clip_id, source, user_id,
               snippet(notes_fts, 4, '<mark>', '</mark>', '…', 12) AS snip,
               bm25(notes_fts) AS score
        FROM notes_fts WHERE notes_fts MATCH ?
    """
    params = [fts_q]
    if pid:
        sql += " AND project_id = ?"
        params.append(pid)
    sql += " ORDER BY score LIMIT ?"
    params.append(limit * 4)  # over-fetch then dedup by clip

    conn = _index_db()
    try:
        cur = conn.execute(sql, params)
        rows = cur.fetchall()
    finally:
        conn.close()

    # Dedup by (project_id, clip_id), keep best score + best snippet
    by_clip = {}
    for r in rows:
        key = (r['project_id'], r['clip_id'])
        if key not in by_clip or r['score'] < by_clip[key]['score']:
            by_clip[key] = {
                'project_id': r['project_id'], 'clip_id': r['clip_id'],
                'source': r['source'], 'user_id': r['user_id'],
                'snippet': r['snip'], 'score': r['score'],
            }
    return sorted(by_clip.values(), key=lambda x: x['score'])[:limit]

# ─── Export Functions ───

def export_fcpxml(project, filter_config=None):
    clips = project.get('clips', [])
    notes = project.get('notes', {})
    users = project.get('users', [])
    fc_min_rating = int(filter_config['min_rating']) if filter_config and filter_config.get('min_rating') else None
    fc_cats = filter_config.get('cats') if filter_config else None
    fc_rejected_only = bool(filter_config.get('rejected_only')) if filter_config else False

    root = ET.Element('fcpxml', version='1.8')
    resources = ET.SubElement(root, 'resources')

    # Format entries keyed by (resolution, fps_int) to handle mixed fps projects
    formats = {}
    for clip in clips:
        res = clip.get('resolution') or '1920x1080'
        fps_int = round(clip.get('fps', 25))
        key = (res, fps_int)
        if key not in formats:
            parts = res.split('x')
            w, h = (parts[0], parts[1]) if len(parts) == 2 else ('1920', '1080')
            formats[key] = {'id': f'f{len(formats)+1}', 'w': w, 'h': h, 'fps': fps_int}

    if not formats:
        formats[('1920x1080', 25)] = {'id': 'f1', 'w': '1920', 'h': '1080', 'fps': 25}

    for (res, fps_int), data in formats.items():
        ET.SubElement(resources, 'format', id=data['id'],
                      name=f"Format_{data['w']}x{data['h']}_{fps_int}fps",
                      frameDuration=f'1/{fps_int}s',
                      width=str(data['w']), height=str(data['h']))

    seq_format_id = list(formats.values())[0]['id']
    
    library = ET.SubElement(root, 'library')
    event = ET.SubElement(library, 'event', name=f"{project['name']} - Dérushage")
    proj = ET.SubElement(event, 'project', name='Selects')
    seq = ET.SubElement(proj, 'sequence', format=seq_format_id, tcStart='0s', tcFormat='NDF')
    spine = ET.SubElement(seq, 'spine')

    record_offset = 0
    asset_idx = 0

    for clip in clips:
        include_clip = False
        is_rejected = False
        for u in users:
            uid = user_note_key(u)
            cnotes = (notes.get(uid) or {}).get(clip['id'])
            if not cnotes: continue
            rating = str(cnotes.get('rating', ''))
            if rating == 'X':
                is_rejected = True
            if fc_rejected_only:
                if rating == 'X': include_clip = True
            elif fc_min_rating is not None:
                if rating in ['1','2','3'] and int(rating) >= fc_min_rating:
                    include_clip = True
            elif fc_cats is not None:
                if any(m.get('cat') in fc_cats for m in cnotes.get('markers', []) if m.get('cat') != 'X'):
                    include_clip = True
            else:
                if cnotes.get('markers') or cnotes.get('notes', '').strip() or rating in ['1','2','3']:
                    include_clip = True

        if fc_rejected_only:
            if not include_clip: continue
        else:
            if is_rejected or not include_clip: continue

        asset_idx += 1
        asset_id = f"asset_{asset_idx}"
        clip_fps = round(clip.get('fps', 25))
        dur = clip.get('duration_sec', 0) or 1
        dur_rational = seconds_to_rational(dur, clip_fps)

        src_path = clip.get('path', '')
        src_uri = src_path.replace(chr(92), '/')
        if not src_uri.startswith('/'):
            src_uri = '/' + src_uri
        src_uri = 'file://localhost' + src_uri

        clip_res = clip.get('resolution') or '1920x1080'
        fmt_id = formats.get((clip_res, clip_fps), list(formats.values())[0])['id']

        # Use the actual source TC as start so DaVinci can validate it against
        # the embedded TC in the MXF file (they must match or DaVinci shows
        # "timecode extents" errors). tc_in is stored correctly after FX6 byte-reversal.
        tc_in_sec = tc_to_seconds(clip.get('tc_in', ''), clip_fps) or 0
        tc_in_frames = int(round(tc_in_sec * clip_fps))
        tc_in_rational = f'{tc_in_frames}/{clip_fps}s' if tc_in_frames > 0 else '0s'

        ET.SubElement(resources, 'asset', id=asset_id,
                      src=src_uri,
                      start=tc_in_rational, duration=dur_rational, format=fmt_id,
                      name=clip.get('filename', ''), hasVideo='1', hasAudio='1')

        # Collect global notes/rating as clip-level note (shown in DaVinci clip metadata, no timeline marker)
        clip_note_parts = []
        for u in users:
            uid = user_note_key(u)
            cnotes = (notes.get(uid) or {}).get(clip['id'])
            if not cnotes: continue
            rating = str(cnotes.get('rating', ''))
            global_note = cnotes.get('notes', '').strip()
            stars = {'3': '⭐⭐⭐', '2': '⭐⭐', '1': '⭐'}.get(rating, '')
            parts = [p for p in [stars, global_note] if p]
            if parts:
                clip_note_parts.append(f"[{u.get('name') or u.get('username', '?')}] " + ' — '.join(parts))

        # Collect X-marker cut points across all users
        x_times = sorted(set(
            m['time'] for u in users
            for m in ((notes.get(user_note_key(u)) or {}).get(clip['id']) or {}).get('markers', [])
            if m.get('cat') == 'X'
        ))

        # Build kept segments from X markers:
        # 1 X at T  → keep [0,T]
        # 2 X       → keep [0,T1] + [T2,end]
        # 3 X       → keep [0,T1] + [T2,T3]
        # etc.
        if not x_times:
            segments = [(0.0, dur)]
        else:
            segments = []
            prev = 0.0
            for i, t in enumerate(x_times):
                if i % 2 == 0:
                    if t > prev:
                        segments.append((prev, t))
                else:
                    prev = t
            if len(x_times) % 2 == 0 and x_times[-1] < dur:
                segments.append((x_times[-1], dur))

        # Collect content markers (non-X) from all users
        all_markers = []
        for u in users:
            uid = user_note_key(u)
            cnotes = (notes.get(uid) or {}).get(clip['id'])
            if not cnotes: continue
            cat_labels = {'3': '⭐⭐⭐', '2': '⭐⭐', '1': '⭐', 'T': '🎨', 'S': '🎵', 'D': '📌'}
            for m in cnotes.get('markers', []):
                if m.get('cat') == 'X':
                    continue
                cat = cat_labels.get(str(m.get('cat', '')), str(m.get('cat', '')))
                desc = m.get('desc', '')
                label = f"[{u.get('name') or u.get('username', '?')}] {cat}".strip()
                all_markers.append({'time': m.get('time', 0), 'val': label, 'note': desc})
        all_markers.sort(key=lambda x: x['time'])

        # Emit one asset-clip per kept segment
        for seg_start, seg_end in segments:
            seg_dur = seg_end - seg_start
            if seg_dur <= 0:
                continue
            seg_start_frames = int(round(seg_start * clip_fps))
            seg_dur_rational = seconds_to_rational(seg_dur, clip_fps)
            seg_tc_start_frames = tc_in_frames + seg_start_frames
            seg_tc_rational = f'{seg_tc_start_frames}/{clip_fps}s' if seg_tc_start_frames > 0 else '0s'

            ac_attrs = {
                'ref': asset_id,
                'offset': seconds_to_rational(record_offset, clip_fps),
                'duration': seg_dur_rational,
                'start': seg_tc_rational,
                'name': clip.get('filename', ''),
            }
            if clip_note_parts:
                ac_attrs['note'] = ' | '.join(clip_note_parts)
            ac = ET.SubElement(spine, 'asset-clip', **ac_attrs)

            # Add markers that fall within this segment
            seen_times = set()
            for m in all_markers:
                if m['time'] < seg_start or m['time'] >= seg_end:
                    continue
                offset_frames = int(round(m['time'] * clip_fps))
                frame_num = tc_in_frames + offset_frames
                while frame_num in seen_times:
                    frame_num += 1
                seen_times.add(frame_num)
                mk_attrs = {
                    'start': f'{frame_num}/{clip_fps}s',
                    'duration': f'1/{clip_fps}s',
                    'value': m['val'],
                }
                if m.get('note'):
                    mk_attrs['note'] = m['note']
                ET.SubElement(ac, 'marker', **mk_attrs)

            record_offset += seg_dur

    xml_str = '<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE fcpxml>\n'
    xml_str += ET.tostring(root, encoding='unicode', xml_declaration=False)
    return xml_str


def export_xml_fcp7(project, filter_config=None):
    """
    Export Adobe Premiere Pro XML (Final Cut Pro 7 XML Interchange Format, v5).
    Schéma : <xmeml><sequence><media><video><track><clipitem>…
    Compatible Premiere Pro CC 2017+ (et toute version qui sait lire l'XML FCP7).
    Mêmes règles de filtrage et coupes X que export_fcpxml.
    """
    clips = project.get('clips', [])
    notes = project.get('notes', {})
    users = project.get('users', [])
    fc_min_rating = int(filter_config['min_rating']) if filter_config and filter_config.get('min_rating') else None
    fc_cats = filter_config.get('cats') if filter_config else None
    fc_rejected_only = bool(filter_config.get('rejected_only')) if filter_config else False

    def _rate_elem(fps_int):
        """<rate><timebase>N</timebase><ntsc>FALSE</ntsc></rate>"""
        # NTSC fractional rates : 23.976, 29.97, 59.94 → ntsc=TRUE
        # Ici on traite des fps entiers depuis round(clip.fps), donc ntsc=FALSE
        e = ET.Element('rate')
        ET.SubElement(e, 'timebase').text = str(fps_int)
        ET.SubElement(e, 'ntsc').text = 'FALSE'
        return e

    def _tc_elem(tc_sec, fps_int):
        """<timecode><rate>…</rate><string>HH:MM:SS:FF</string><frame>N</frame>…"""
        frames = int(round(tc_sec * fps_int))
        tc_str = seconds_to_tc(tc_sec, fps_int)
        e = ET.Element('timecode')
        e.append(_rate_elem(fps_int))
        ET.SubElement(e, 'string').text = tc_str
        ET.SubElement(e, 'frame').text = str(frames)
        ET.SubElement(e, 'displayformat').text = 'NDF'
        return e

    # Détermine fps de séquence (majoritaire) + dims max
    seq_fps = 25
    seq_w, seq_h = 1920, 1080
    if clips:
        fps_count = {}
        for c in clips:
            fps_count[round(c.get('fps', 25))] = fps_count.get(round(c.get('fps', 25)), 0) + 1
        seq_fps = max(fps_count.items(), key=lambda x: x[1])[0]
        for c in clips:
            res = c.get('resolution') or '1920x1080'
            parts = res.split('x')
            if len(parts) == 2:
                try:
                    w, h = int(parts[0]), int(parts[1])
                    if w * h > seq_w * seq_h:
                        seq_w, seq_h = w, h
                except ValueError:
                    pass

    root = ET.Element('xmeml', version='5')
    seq = ET.SubElement(root, 'sequence', id='sequence-1')
    ET.SubElement(seq, 'name').text = f"{project.get('name', 'Projet')} - Selects"

    # La durée sera calculée à la fin (somme des segments en frames)
    seq_duration_el = ET.SubElement(seq, 'duration')
    seq.append(_rate_elem(seq_fps))
    seq.append(_tc_elem(0, seq_fps))

    media = ET.SubElement(seq, 'media')
    video = ET.SubElement(media, 'video')
    fmt = ET.SubElement(video, 'format')
    sc = ET.SubElement(fmt, 'samplecharacteristics')
    sc.append(_rate_elem(seq_fps))
    ET.SubElement(sc, 'width').text = str(seq_w)
    ET.SubElement(sc, 'height').text = str(seq_h)
    ET.SubElement(sc, 'pixelaspectratio').text = 'square'
    track = ET.SubElement(video, 'track')

    file_ids_emitted = set()  # pour réutiliser <file id> sans dupliquer le body
    record_frames = 0  # offset cumulé dans la timeline séquence
    clip_idx = 0

    for clip in clips:
        # ─── Filter : même logique que export_fcpxml ────────────────────────
        include_clip = False
        is_rejected = False
        for u in users:
            uid = user_note_key(u)
            cnotes = (notes.get(uid) or {}).get(clip['id'])
            if not cnotes:
                continue
            rating = str(cnotes.get('rating', ''))
            if rating == 'X':
                is_rejected = True
            if fc_rejected_only:
                if rating == 'X':
                    include_clip = True
            elif fc_min_rating is not None:
                if rating in ['1', '2', '3'] and int(rating) >= fc_min_rating:
                    include_clip = True
            elif fc_cats is not None:
                if any(m.get('cat') in fc_cats for m in cnotes.get('markers', []) if m.get('cat') != 'X'):
                    include_clip = True
            else:
                if cnotes.get('markers') or cnotes.get('notes', '').strip() or rating in ['1', '2', '3']:
                    include_clip = True
        if fc_rejected_only:
            if not include_clip:
                continue
        else:
            if is_rejected or not include_clip:
                continue

        clip_idx += 1
        clip_fps = round(clip.get('fps', 25))
        dur_sec = clip.get('duration_sec', 0) or 1
        dur_frames = int(round(dur_sec * clip_fps))
        tc_in_sec = tc_to_seconds(clip.get('tc_in', ''), clip_fps) or 0
        tc_in_frames = int(round(tc_in_sec * clip_fps))

        src_path = clip.get('path', '')
        src_uri = src_path.replace(chr(92), '/')
        if not src_uri.startswith('/'):
            src_uri = '/' + src_uri
        src_uri = 'file://localhost' + src_uri

        file_id = f"file-{clip['id']}"
        first_emit = file_id not in file_ids_emitted
        file_ids_emitted.add(file_id)

        # ─── Notes globales + segments X (même logique que FCPXML) ─────────
        clip_note_parts = []
        for u in users:
            uid = user_note_key(u)
            cnotes = (notes.get(uid) or {}).get(clip['id'])
            if not cnotes:
                continue
            rating = str(cnotes.get('rating', ''))
            global_note = cnotes.get('notes', '').strip()
            stars = {'3': '⭐⭐⭐', '2': '⭐⭐', '1': '⭐'}.get(rating, '')
            parts = [p for p in [stars, global_note] if p]
            if parts:
                clip_note_parts.append(f"[{u.get('name') or u.get('username', '?')}] " + ' — '.join(parts))

        x_times = sorted(set(
            m['time'] for u in users
            for m in ((notes.get(user_note_key(u)) or {}).get(clip['id']) or {}).get('markers', [])
            if m.get('cat') == 'X'
        ))
        if not x_times:
            segments = [(0.0, dur_sec)]
        else:
            segments = []
            prev = 0.0
            for i, t in enumerate(x_times):
                if i % 2 == 0:
                    if t > prev:
                        segments.append((prev, t))
                else:
                    prev = t
            if len(x_times) % 2 == 0 and x_times[-1] < dur_sec:
                segments.append((x_times[-1], dur_sec))

        # ─── Markers content (non-X) ───────────────────────────────────────
        all_markers = []
        cat_labels = {'3': '⭐⭐⭐', '2': '⭐⭐', '1': '⭐', 'T': '🎨', 'S': '🎵', 'D': '📌'}
        for u in users:
            uid = user_note_key(u)
            cnotes = (notes.get(uid) or {}).get(clip['id'])
            if not cnotes:
                continue
            for m in cnotes.get('markers', []):
                if m.get('cat') == 'X':
                    continue
                cat = cat_labels.get(str(m.get('cat', '')), str(m.get('cat', '')))
                desc = m.get('desc', '')
                label = f"[{u.get('name') or u.get('username', '?')}] {cat}".strip()
                all_markers.append({'time': m.get('time', 0), 'name': label, 'desc': desc})
        all_markers.sort(key=lambda x: x['time'])

        # ─── 1 <clipitem> par segment kept ─────────────────────────────────
        for seg_start, seg_end in segments:
            seg_dur_sec = seg_end - seg_start
            if seg_dur_sec <= 0:
                continue
            seg_in = int(round(seg_start * clip_fps))
            seg_out = int(round(seg_end * clip_fps))
            seg_dur_frames = seg_out - seg_in

            ci = ET.SubElement(track, 'clipitem', id=f"clipitem-{clip_idx}-{int(seg_start*1000)}")
            ET.SubElement(ci, 'name').text = clip.get('filename', clip.get('id', ''))
            ET.SubElement(ci, 'duration').text = str(dur_frames)
            ci.append(_rate_elem(clip_fps))
            ET.SubElement(ci, 'in').text = str(seg_in)
            ET.SubElement(ci, 'out').text = str(seg_out)
            ET.SubElement(ci, 'start').text = str(record_frames)
            ET.SubElement(ci, 'end').text = str(record_frames + seg_dur_frames)

            if first_emit:
                # Définition complète du fichier la 1ère fois
                f = ET.SubElement(ci, 'file', id=file_id)
                ET.SubElement(f, 'name').text = clip.get('filename', '')
                ET.SubElement(f, 'pathurl').text = src_uri
                f.append(_rate_elem(clip_fps))
                ET.SubElement(f, 'duration').text = str(dur_frames)
                # TC source : critique pour que Premiere matche le fichier original
                f.append(_tc_elem(tc_in_sec, clip_fps))
                fmedia = ET.SubElement(f, 'media')
                fvideo = ET.SubElement(fmedia, 'video')
                fsc = ET.SubElement(fvideo, 'samplecharacteristics')
                fsc.append(_rate_elem(clip_fps))
                cres = clip.get('resolution') or f'{seq_w}x{seq_h}'
                cparts = cres.split('x')
                cw, ch = (cparts[0], cparts[1]) if len(cparts) == 2 else (str(seq_w), str(seq_h))
                ET.SubElement(fsc, 'width').text = cw
                ET.SubElement(fsc, 'height').text = ch
                ET.SubElement(fmedia, 'audio')  # placeholder = pas de detail mais Premiere accepte
                first_emit = False
            else:
                # Réutilisation par ref
                ET.SubElement(ci, 'file', id=file_id)

            # Note globale dans le commentaire du clipitem (visible Métadonnées Premiere)
            if clip_note_parts:
                comments = ET.SubElement(ci, 'comments')
                mc = ET.SubElement(comments, 'mastercomment1')
                mc.text = ' | '.join(clip_note_parts)

            # Markers content dans le segment
            for m in all_markers:
                if m['time'] < seg_start or m['time'] >= seg_end:
                    continue
                # <marker><in> = offset depuis le début du SOURCE FILE (pas du clipitem)
                # Premiere place le marker à cette frame relative au fichier média
                m_in = int(round(m['time'] * clip_fps))
                mk = ET.SubElement(ci, 'marker')
                ET.SubElement(mk, 'name').text = m['name']
                if m.get('desc'):
                    ET.SubElement(mk, 'comment').text = m['desc']
                ET.SubElement(mk, 'in').text = str(m_in)
                ET.SubElement(mk, 'out').text = '-1'

            record_frames += seg_dur_frames

    seq_duration_el.text = str(record_frames)

    xml_str = '<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE xmeml>\n'
    xml_str += ET.tostring(root, encoding='unicode', xml_declaration=False)
    return xml_str


def export_subclips_fcpxml(project, pre_roll=3.0, post_roll=7.0, filter_config=None):
    """
    Export FCPXML avec un sous-clip par marker : [marker - pre_roll, marker + post_roll].
    Chaque segment est clampé aux bornes du clip source.
    """
    clips = project.get('clips', [])
    notes = project.get('notes', {})
    users = project.get('users', [])
    fc_cats = filter_config.get('cats') if filter_config else None
    fc_min_rating = int(filter_config['min_rating']) if filter_config and filter_config.get('min_rating') else None
    cat_labels_map = {'3':'⭐⭐⭐','2':'⭐⭐','1':'⭐','T':'🎨','S':'🎵','D':'📌'}

    root = ET.Element('fcpxml', version='1.8')
    resources = ET.SubElement(root, 'resources')

    formats = {}
    for clip in clips:
        res = clip.get('resolution') or '1920x1080'
        fps_int = round(clip.get('fps', 25))
        key = (res, fps_int)
        if key not in formats:
            parts = res.split('x')
            w, h = (parts[0], parts[1]) if len(parts) == 2 else ('1920', '1080')
            formats[key] = {'id': f'f{len(formats)+1}', 'w': w, 'h': h, 'fps': fps_int}
    if not formats:
        formats[('1920x1080', 25)] = {'id': 'f1', 'w': '1920', 'h': '1080', 'fps': 25}
    for (res, fps_int), data in formats.items():
        ET.SubElement(resources, 'format', id=data['id'],
                      name=f"Format_{data['w']}x{data['h']}_{fps_int}fps",
                      frameDuration=f'1/{fps_int}s',
                      width=str(data['w']), height=str(data['h']))

    seq_format_id = list(formats.values())[0]['id']
    library = ET.SubElement(root, 'library')
    event = ET.SubElement(library, 'event', name=f"{project['name']} - Subclips")
    proj_el = ET.SubElement(event, 'project',
                             name=f"Subclips -{int(pre_roll)}s/+{int(post_roll)}s")
    seq = ET.SubElement(proj_el, 'sequence', format=seq_format_id, tcStart='0s', tcFormat='NDF')
    spine = ET.SubElement(seq, 'spine')

    record_offset = 0.0
    asset_map = {}
    asset_idx = 0

    for clip in clips:
        clip_fps = round(clip.get('fps', 25))
        tc_in_sec = tc_to_seconds(clip.get('tc_in', ''), clip_fps) or 0
        tc_in_frames = int(round(tc_in_sec * clip_fps))
        clip_dur = clip.get('duration_sec', 0) or 0

        all_markers = []
        for u in users:
            uid = user_note_key(u)
            cnotes = (notes.get(uid) or {}).get(clip['id'])
            if not cnotes: continue
            if cnotes.get('rating') == 'X': continue
            # Rating-based markers
            rating = str(cnotes.get('rating', ''))
            if fc_cats is None and fc_min_rating is not None:
                if rating in ['1','2','3'] and int(rating) >= fc_min_rating:
                    label = f"[{u.get('name') or u.get('username', '?')}] {cat_labels_map.get(rating,'')}"
                    all_markers.append({'time': 0, 'label': label, 'note': cnotes.get('notes','').strip()})
            # Individual markers
            for m in cnotes.get('markers', []):
                if m.get('cat') == 'X': continue
                if fc_cats is not None and m.get('cat') not in fc_cats: continue
                if fc_min_rating is not None and fc_cats is None: continue
                cat = cat_labels_map.get(str(m.get('cat','')), '')
                desc = m.get('desc','').strip()
                label = f"[{u.get('name') or u.get('username', '?')}] {cat}"
                all_markers.append({'time': m.get('time', 0), 'label': label,
                                    'note': desc if desc.lower() not in ('marker','') else ''})

        if not all_markers: continue

        src_path = clip.get('path', '')
        if src_path not in asset_map:
            asset_idx += 1
            aid = f'asset_{asset_idx}'
            asset_map[src_path] = aid
            src_uri = src_path.replace(chr(92), '/')
            if not src_uri.startswith('/'): src_uri = '/' + src_uri
            src_uri = 'file://localhost' + src_uri
            clip_res = clip.get('resolution') or '1920x1080'
            fmt_id = formats.get((clip_res, clip_fps), list(formats.values())[0])['id']
            tc_r = f'{tc_in_frames}/{clip_fps}s' if tc_in_frames > 0 else '0s'
            ET.SubElement(resources, 'asset', id=aid, src=src_uri,
                          start=tc_r, duration=seconds_to_rational(clip_dur, clip_fps),
                          format=fmt_id, name=clip.get('filename',''), hasVideo='1', hasAudio='1')
        aid = asset_map[src_path]

        all_markers.sort(key=lambda x: x['time'])
        for m in all_markers:
            mtime = m['time']
            sub_start = max(tc_in_sec, tc_in_sec + mtime - pre_roll)
            sub_end   = min(tc_in_sec + clip_dur, tc_in_sec + mtime + post_roll)
            sub_dur   = sub_end - sub_start
            if sub_dur < 0.04: continue

            sub_start_frames = int(round(sub_start * clip_fps))
            ac = ET.SubElement(spine, 'asset-clip', ref=aid,
                               offset=seconds_to_rational(record_offset, clip_fps),
                               duration=seconds_to_rational(sub_dur, clip_fps),
                               start=f'{sub_start_frames}/{clip_fps}s',
                               name=f"{clip.get('stem','')} — {m['label']}")
            mk_frame = tc_in_frames + int(round(mtime * clip_fps))
            mk_attrs = {'start': f'{mk_frame}/{clip_fps}s',
                        'duration': f'1/{clip_fps}s', 'value': m['label']}
            if m.get('note'): mk_attrs['note'] = m['note']
            ET.SubElement(ac, 'marker', **mk_attrs)
            record_offset += sub_dur

    xml_str = '<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE fcpxml>\n'
    xml_str += ET.tostring(root, encoding='unicode', xml_declaration=False)
    return xml_str

def export_rough_cut_fcpxml(project, min_rating=2, user_filter=None):
    """
    Génère une rough cut : timeline FCPXML avec tous les clips ayant rating >= min_rating
    (pour user_filter spécifique ou n'importe quel user si None), dans l'ordre TC source.
    Chaque clip est inclus en entier (pas de subclip), prêt à monter dans Resolve.
    """
    clips = project.get('clips', [])
    notes = project.get('notes', {})
    users = project.get('users', [])
    min_rating = int(min_rating)

    def _matches(clip):
        for u in users:
            uid = user_note_key(u)
            if user_filter and uid != user_filter:
                continue
            cn = (notes.get(uid) or {}).get(clip['id'])
            if not cn: continue
            r = str(cn.get('rating', ''))
            if r in ('1', '2', '3') and int(r) >= min_rating:
                return True
        return False

    selected = [c for c in clips if _matches(c)]
    # Sort: by day then by source TC for natural editing order
    def _sortkey(c):
        fps = round(c.get('fps', 25))
        return (c.get('day', ''), tc_to_seconds(c.get('tc_in', ''), fps) or 0)
    selected.sort(key=_sortkey)

    root = ET.Element('fcpxml', version='1.8')
    resources = ET.SubElement(root, 'resources')

    # Build format pool
    formats = {}
    for c in selected:
        res = c.get('resolution') or '1920x1080'
        fps_int = round(c.get('fps', 25))
        key = (res, fps_int)
        if key not in formats:
            parts = res.split('x')
            w, h = (parts[0], parts[1]) if len(parts) == 2 else ('1920', '1080')
            formats[key] = {'id': f'f{len(formats)+1}', 'w': w, 'h': h, 'fps': fps_int}
    if not formats:
        formats[('1920x1080', 25)] = {'id': 'f1', 'w': '1920', 'h': '1080', 'fps': 25}
    for (res, fps_int), data in formats.items():
        ET.SubElement(resources, 'format', id=data['id'],
                      name=f"Format_{data['w']}x{data['h']}_{fps_int}fps",
                      frameDuration=f'1/{fps_int}s',
                      width=str(data['w']), height=str(data['h']))

    seq_format_id = list(formats.values())[0]['id']

    # Friendly project name
    rating_label = {1: 'OK+', 2: 'Bien+', 3: 'Top'}.get(min_rating, f'>={min_rating}')
    user_label = user_filter or 'équipe'

    library = ET.SubElement(root, 'library')
    event = ET.SubElement(library, 'event', name=f"{project['name']} - Rough cut")
    proj_el = ET.SubElement(event, 'project',
                            name=f"Rough cut {rating_label} ({user_label})")
    seq = ET.SubElement(proj_el, 'sequence', format=seq_format_id, tcStart='0s', tcFormat='NDF')
    spine = ET.SubElement(seq, 'spine')

    record_offset = 0.0
    for idx, clip in enumerate(selected, 1):
        clip_fps = round(clip.get('fps', 25))
        dur = clip.get('duration_sec', 0) or 1
        dur_rational = seconds_to_rational(dur, clip_fps)

        src_path = clip.get('path', '')
        src_uri = src_path.replace(chr(92), '/')
        if not src_uri.startswith('/'):
            src_uri = '/' + src_uri
        src_uri = 'file://localhost' + src_uri

        clip_res = clip.get('resolution') or '1920x1080'
        fmt_id = formats.get((clip_res, clip_fps), list(formats.values())[0])['id']

        tc_in_sec = tc_to_seconds(clip.get('tc_in', ''), clip_fps) or 0
        tc_in_frames = int(round(tc_in_sec * clip_fps))
        tc_in_rational = f'{tc_in_frames}/{clip_fps}s' if tc_in_frames > 0 else '0s'

        asset_id = f"asset_{idx}"
        ET.SubElement(resources, 'asset', id=asset_id,
                      src=src_uri,
                      start=tc_in_rational, duration=dur_rational, format=fmt_id,
                      name=clip.get('filename', ''), hasVideo='1', hasAudio='1')

        # Aggregate note: best rating + global notes from contributors
        note_parts = []
        for u in users:
            uid = user_note_key(u)
            if user_filter and uid != user_filter:
                continue
            cn = (notes.get(uid) or {}).get(clip['id'])
            if not cn: continue
            r = str(cn.get('rating', ''))
            stars = {'3': '⭐⭐⭐', '2': '⭐⭐', '1': '⭐'}.get(r, '')
            gn = (cn.get('notes') or '').strip()
            uname = u.get('username') or u.get('name', '?')
            bits = [b for b in [stars, gn] if b]
            if bits:
                note_parts.append(f'[{uname}] ' + ' — '.join(bits))

        ac_attrs = {
            'ref': asset_id,
            'offset': seconds_to_rational(record_offset, clip_fps),
            'duration': dur_rational,
            'start': tc_in_rational,
            'name': clip.get('filename', ''),
        }
        if note_parts:
            ac_attrs['note'] = ' | '.join(note_parts)
        ET.SubElement(spine, 'asset-clip', **ac_attrs)
        record_offset += dur

    xml_str = '<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE fcpxml>\n'
    xml_str += ET.tostring(root, encoding='unicode', xml_declaration=False)
    return xml_str

def export_report_html(project):
    clips = project.get('clips', [])
    notes = project.get('notes', {})
    users = project.get('users', [])
    proj_name = project.get('name', 'Projet')
    now = datetime.now().strftime('%d/%m/%Y à %H:%M')

    CAT_LABELS = {'3':'⭐⭐⭐ Top','2':'⭐⭐ Bien','1':'⭐ OK','X':'❌ Rejeté',
                  'T':'👁️ Image','S':'🎵 Son','D':'📌 Note'}
    CAT_COLORS = {'3':'#fcd34d','2':'#a78bfa','1':'#9ca3af','X':'#ef4444',
                  'T':'#3b82f6','S':'#10b981','D':'#f59e0b'}

    annotated, total_markers, total_rejected = [], 0, 0
    for clip in clips:
        included = False
        for u in users:
            cn = (notes.get(user_note_key(u)) or {}).get(clip['id'], {})
            if cn.get('rating') == 'X': total_rejected += 1
            if cn.get('rating') or cn.get('markers') or (cn.get('notes','').strip()):
                included = True
            total_markers += len([m for m in (cn.get('markers') or []) if m.get('cat') != 'X'])
        if included:
            annotated.append(clip)

    # Group by day
    days = {}
    for clip in annotated:
        day = clip.get('day', '—')
        days.setdefault(day, []).append(clip)

    def clip_card(clip):
        cid = clip['id']
        parts = []
        # Ratings
        rb = ''
        for u in users:
            cn = (notes.get(user_note_key(u)) or {}).get(cid, {})
            r = str(cn.get('rating', ''))
            if r:
                col = CAT_COLORS.get(r, '#888')
                lbl = CAT_LABELS.get(r, r)
                rb += (f'<span class="rbadge" style="color:{col};border-color:{col};background:{col}18;">'
                       f'<b style="color:{u.get("color","#888")}">{u["name"]}</b> {lbl}</span>')
        if rb:
            parts.append(f'<div class="ratings">{rb}</div>')

        # Markers
        mrows = ''
        for u in users:
            cn = (notes.get(user_note_key(u)) or {}).get(cid, {})
            for m in sorted(cn.get('markers') or [], key=lambda x: x.get('time', 0)):
                cat = str(m.get('cat', ''))
                if cat == 'X': continue
                col = CAT_COLORS.get(cat, '#888')
                lbl = CAT_LABELS.get(cat, cat)
                desc = (m.get('desc','') or '').strip() or '—'
                tc = m.get('tc', '')
                mrows += (f'<tr><td class="mono">{tc}</td>'
                          f'<td><span class="dot" style="background:{col}"></span>{lbl}</td>'
                          f'<td>{desc}</td>'
                          f'<td style="color:{u.get("color","#888")};font-weight:600">{u["name"]}</td></tr>')
        if mrows:
            parts.append(f'<table class="mtbl"><tr><th>TC</th><th>Catégorie</th><th>Description</th><th>Annotateur</th></tr>{mrows}</table>')

        # Global notes
        for u in users:
            cn = (notes.get(user_note_key(u)) or {}).get(cid, {})
            n = (cn.get('notes','') or '').strip()
            if n:
                parts.append(f'<div class="gnote"><b style="color:{u.get("color","#888")}">{u["name"]} :</b> {n}</div>')

        body = ''.join(parts) or '<span style="color:#aaa;font-size:0.85em;">—</span>'
        meta = ' · '.join(filter(None, [clip.get('camera',''), clip.get('tc_in',''),
                                         clip.get('duration_tc',''), clip.get('resolution','')]))
        return (f'<div class="card"><div class="card-head">'
                f'<span class="cname">{clip.get("stem","")}</span>'
                f'<span class="cmeta">{meta}</span></div>'
                f'<div class="card-body">{body}</div></div>\n')

    rows = ''
    for day, day_clips in days.items():
        rows += f'<div class="day">{day}</div>\n'
        for clip in day_clips:
            rows += clip_card(clip)

    css = """
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:'Helvetica Neue',Arial,sans-serif;background:#f4f4f8;color:#1a1a2e;font-size:13px}
.hdr{background:#1a1a2e;color:#fff;padding:20px 28px}
.hdr h1{font-size:1.3em;margin-bottom:4px}
.hdr .sub{color:rgba(255,255,255,.5);font-size:.82em;margin-bottom:10px}
.stats{display:flex;gap:12px;flex-wrap:wrap}
.stat{background:rgba(255,255,255,.12);padding:4px 12px;border-radius:20px;font-size:.82em}
.wrap{max-width:1080px;margin:0 auto;padding:20px 14px}
.day{font-size:.78em;font-weight:700;color:#888;text-transform:uppercase;letter-spacing:.08em;
     margin:18px 0 6px;border-bottom:1px solid #ddd;padding-bottom:3px}
.card{background:#fff;border-radius:8px;margin-bottom:7px;overflow:hidden;
      box-shadow:0 1px 3px rgba(0,0,0,.08)}
.card-head{display:flex;align-items:baseline;gap:12px;padding:8px 12px;background:#ebebf0;flex-wrap:wrap}
.cname{font-weight:700;font-size:.92em}
.cmeta{font-size:.75em;color:#888}
.card-body{padding:8px 12px}
.ratings{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:7px}
.rbadge{display:inline-flex;align-items:center;gap:4px;padding:2px 9px;
        border-radius:20px;font-size:.8em;border:1px solid}
.mtbl{width:100%;border-collapse:collapse;font-size:.8em;margin-bottom:6px}
.mtbl th{text-align:left;color:#888;padding:3px 7px;border-bottom:1px solid #eee;font-weight:600}
.mtbl td{padding:3px 7px;border-bottom:1px solid #f3f3f3;vertical-align:top}
.mtbl tr:last-child td{border-bottom:none}
.mono{font-family:monospace;color:#555;white-space:nowrap}
.dot{display:inline-block;width:7px;height:7px;border-radius:50%;margin-right:3px;vertical-align:middle}
.gnote{font-size:.8em;color:#555;font-style:italic;margin-top:4px;padding:3px 8px;
       background:#f8f8f8;border-left:3px solid #ddd;border-radius:2px}
@media print{body{background:#fff}.card{box-shadow:none;border:1px solid #ddd;break-inside:avoid}}
"""

    return f"""<!DOCTYPE html>
<html lang="fr"><head><meta charset="UTF-8">
<title>Rapport — {proj_name}</title>
<style>{css}</style></head><body>
<div class="hdr">
  <h1>📋 Rapport de dérushage — {proj_name}</h1>
  <div class="sub">Généré le {now}</div>
  <div class="stats">
    <span class="stat">🎬 {len(clips)} clips scannés</span>
    <span class="stat">✏️ {len(annotated)} annotés</span>
    <span class="stat">📌 {total_markers} markers</span>
    <span class="stat">❌ {total_rejected} rejetés</span>
    <span class="stat">👥 {len(users)} annotateur(s)</span>
  </div>
</div>
<div class="wrap">{rows}</div>
</body></html>"""

def export_edl(project):
    clips = project.get('clips', [])
    notes = project.get('notes', {})
    users = project.get('users', [])

    lines = [f"TITLE: {project['name']}_DERUSHAGE", "FCM: NON-DROP FRAME", ""]
    event_num = 0
    record_tc = 0  # destination timeline in seconds at 25fps

    for clip in clips:
        clip_fps = round(clip.get('fps', 25))
        tc_in_sec = tc_to_seconds(clip.get('tc_in', ''), clip_fps) or 0
        # CMX3600 : reel limité à 8 chars. DaVinci utilise * FROM CLIP NAME pour le vrai nom.
        reel = clip.get('stem', 'AX')[:8].ljust(8)
        cat_labels = {'3': '⭐⭐⭐', '2': '⭐⭐', '1': '⭐', 'T': '🎨', 'S': '🎵', 'D': '📌'}

        for u in users:
            uid = user_note_key(u)
            cnotes = (notes.get(uid) or {}).get(clip['id'])
            if not cnotes or not cnotes.get('markers'): continue
            seen_src = set()
            for m in cnotes['markers']:
                if m.get('cat') == 'X': continue
                mtime = m.get('time', 0)
                # Décaler les marqueurs au début du clip d'1 frame pour éviter les
                # erreurs "TC extents" quand la TC stockée diffère d'1 frame de celle de DaVinci
                if mtime == 0:
                    mtime = 1.0 / clip_fps
                # Dédupliquer les TC source identiques (décaler d'1 frame)
                src_frame = int(round((tc_in_sec + mtime) * clip_fps))
                while src_frame in seen_src:
                    src_frame += 1
                seen_src.add(src_frame)
                actual_src_sec = src_frame / clip_fps

                event_num += 1
                src_in = seconds_to_tc(actual_src_sec, clip_fps)
                src_out = seconds_to_tc(actual_src_sec + 1, clip_fps)
                rec_in = seconds_to_tc(record_tc, 25)
                rec_out = seconds_to_tc(record_tc + 1, 25)
                record_tc += 1

                lines.append(f"{event_num:03d}  {reel} V     C        {src_in} {src_out} {rec_in} {rec_out}")
                lines.append(f"* FROM CLIP NAME: {clip.get('filename', '')}")
                cat = cat_labels.get(str(m.get('cat', '')), '')
                desc = m.get('desc', '')
                lines.append(f"* LOC: {rec_in} RED [{u.get('name') or u.get('username', '?')}] {cat} {desc}".rstrip())
                lines.append("")

    return '\n'.join(lines)

def export_markers_edl(project):
    """
    EDL au format DaVinci Resolve 'Import Timeline Markers from EDL'.
    Workflow : importer d'abord le FCPXML comme timeline dans DaVinci,
    puis clic droit sur la timeline -> Timelines -> Import -> Timeline Markers from EDL.
    Les TCs de la piste timeline correspondent aux positions dans la sequence FCPXML.
    """
    clips = project.get('clips', [])
    notes = project.get('notes', {})
    users = project.get('users', [])

    SEQ_FPS = 25  # FPS de la séquence (doit correspondre au FCPXML)

    cat_colors = {
        '3': 'ResolveColorYellow',
        '2': 'ResolveColorPurple',
        '1': 'ResolveColorCream',
        'T': 'ResolveColorSky',
        'S': 'ResolveColorGreen',
        'D': 'ResolveColorSand',
    }
    cat_labels_en = {
        '3': '3 stars', '2': '2 stars', '1': '1 star',
        'T': 'treatment', 'S': 'sound', 'D': 'marker',
    }

    lines = [f"TITLE: {project['name']}_markers", "FCM: NON-DROP FRAME", ""]
    event_num = 0
    record_offset = 0  # position dans la timeline en secondes (même logique que FCPXML)

    for clip in clips:
        include_clip = False
        is_rejected = False
        for u in users:
            uid = user_note_key(u)
            cnotes = (notes.get(uid) or {}).get(clip['id'])
            if not cnotes: continue
            if cnotes.get('rating') == 'X':
                is_rejected = True
            if cnotes.get('markers') or cnotes.get('notes', '').strip() or str(cnotes.get('rating', '')) in ['1', '2', '3']:
                include_clip = True

        if is_rejected or not include_clip:
            continue

        dur = clip.get('duration_sec', 0) or 0

        # Collecter tous les marqueurs de tous les utilisateurs
        all_markers = []
        for u in users:
            uid = user_note_key(u)
            cnotes = (notes.get(uid) or {}).get(clip['id'])
            if not cnotes: continue

            rating = cnotes.get('rating', '')
            global_note = cnotes.get('notes', '').strip()

            if global_note or str(rating) in ['1', '2', '3']:
                r_cat = str(rating)
                color = cat_colors.get(r_cat, 'ResolveColorBlue')
                label = f"{u.get('name') or u.get('username', '?')} {cat_labels_en.get(r_cat, 'note')}"
                if global_note:
                    label += f" - {global_note}"
                all_markers.append({'time': 0, 'label': label, 'color': color})

            for m in cnotes.get('markers', []):
                if m.get('cat') == 'X': continue
                cat = str(m.get('cat', ''))
                color = cat_colors.get(cat, 'ResolveColorBlue')
                label = f"{u.get('name') or u.get('username', '?')} {cat_labels_en.get(cat, 'marker')}"
                desc = m.get('desc', '').strip()
                if desc and desc.lower() != 'marker':
                    label += f" - {desc}"
                all_markers.append({'time': m.get('time', 0), 'label': label, 'color': color})

        all_markers.sort(key=lambda x: x['time'])
        seen_frames = set()
        for m in all_markers:
            seq_time = record_offset + m['time']
            frame_num = int(round(seq_time * SEQ_FPS))
            while frame_num in seen_frames:
                frame_num += 1
            seen_frames.add(frame_num)

            tc_in = seconds_to_tc(frame_num / SEQ_FPS, SEQ_FPS)
            tc_out = seconds_to_tc((frame_num + 1) / SEQ_FPS, SEQ_FPS)

            event_num += 1
            lines.append(f"{event_num:03d}  001      V     C        {tc_in} {tc_out} {tc_in} {tc_out}")
            lines.append(f" |C:{m['color']} |M:{m['label']} |D:1")
            lines.append("")

        record_offset += dur

    return '\n'.join(lines)

def export_csv(project):
    clips = project.get('clips', [])
    notes = project.get('notes', {})
    users = project.get('users', [])
    
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Jour', 'Camera', 'Clip', 'TC_Source_In', 'Utilisateur', 'Rating',
                     'Marker_TC', 'Categorie', 'Description', 'Notes', 'Has_Drawing'])
    
    cat_labels = {3: '⭐⭐⭐', 2: '⭐⭐', 1: '⭐', 'T': '🎨', 'S': '🎵', 'X': '❌', 'D': '📌'}
    
    for clip in clips:
        for u in users:
            uid = user_note_key(u)
            cnotes = (notes.get(uid) or {}).get(clip['id'])
            if not cnotes: continue
            rating = cat_labels.get(cnotes.get('rating'), str(cnotes.get('rating', '')))
            if cnotes.get('markers'):
                for m in cnotes['markers']:
                    has_draw = '1' if m.get('drawing') else '0'
                    writer.writerow([clip.get('day', ''), clip.get('camera', ''),
                                     clip.get('stem', ''), clip.get('tc_in', ''),
                                     u.get('name') or u.get('username', '?'), rating, m.get('tc', ''),
                                     cat_labels.get(m.get('cat'), str(m.get('cat', ''))),
                                     m.get('desc', ''), cnotes.get('notes', ''), has_draw])
            elif cnotes.get('rating') or cnotes.get('notes'):
                writer.writerow([clip.get('day', ''), clip.get('camera', ''),
                                 clip.get('stem', ''), clip.get('tc_in', ''),
                                 u.get('name') or u.get('username', '?'), rating, '', '', '',
                                 cnotes.get('notes', ''), '0'])
    return output.getvalue()

# ─── Waveform ───

def _lighter_decode_source(file_path):
    """Renvoie un chemin plus léger à décoder si dispo, sinon file_path original.

    Cas GoPro : à côté du MP4 4K/5K HEVC (lourd à décoder côté CPU — jusqu'à 1.5 GB
    de RAM par instance ffmpeg pour une seule frame), la caméra dépose un fichier
    .LRV en HEVC 432p (proxy natif GoPro, ~5-10 MB). Pour générer les thumbnails
    côté serveur on n'a pas besoin de la 5K — on utilise le LRV qui consomme ~10×
    moins de RAM. Pattern : GX0001.MP4 ↔ GL0001.LRV à côté."""
    try:
        p = Path(file_path)
        name = p.name
        if name.startswith('GX') and name.upper().endswith('.MP4'):
            lrv_name = 'GL' + name[2:-4] + '.LRV'
            lrv = p.with_name(lrv_name)
            if lrv.exists():
                return str(lrv)
    except Exception:
        pass
    return str(file_path)


def compute_thumbnail(file_path, clip_id, offset_sec=5.0):
    thumb = THUMBNAILS_DIR / f"{clip_id}.jpg"
    if thumb.exists():
        return thumb
    src = _lighter_decode_source(file_path)
    def _do():
        try:
            # -analyzeduration/-probesize : sans ça, ffmpeg peut allouer >1 GB pour
            # probe certains fichiers (GoPro HEVC, MXF Sony) avant même de seek.
            # -an : aucun besoin d'analyser l'audio pour faire un thumbnail.
            cmd = [FFMPEG, '-hide_banner', '-loglevel', 'error',
                   '-analyzeduration', '1M', '-probesize', '5M',
                   '-ss', str(offset_sec), '-i', src,
                   '-an', '-frames:v', '1',
                   '-vf', 'scale=160:-1:flags=fast_bilinear',
                   '-q:v', '5', '-y', str(thumb)]
            _ffmpeg_run(cmd, timeout=30)
        except Exception:
            pass
    _dedupe_compute(f"thumb:{clip_id}", _do)
    return thumb if thumb.exists() else None

def compute_thumbnail_scrub(file_path, clip_id, t_sec):
    """Génère un thumbnail à un offset précis pour le scrubbing hover, caché par seconde entière."""
    t_key = max(0, int(t_sec))
    thumb = THUMBNAILS_DIR / f"{clip_id}_t{t_key}.jpg"
    if thumb.exists():
        return thumb
    src = _lighter_decode_source(file_path)
    def _do():
        try:
            cmd = [FFMPEG, '-hide_banner', '-loglevel', 'error',
                   '-analyzeduration', '1M', '-probesize', '5M',
                   '-ss', str(float(t_key)), '-i', src,
                   '-an', '-frames:v', '1',
                   '-vf', 'scale=160:-1:flags=fast_bilinear',
                   '-q:v', '6', '-y', str(thumb)]
            _ffmpeg_run(cmd, timeout=30)
        except Exception:
            pass
    _dedupe_compute(f"thumb_scrub:{clip_id}:{t_key}", _do)
    return thumb if thumb.exists() else None

def compute_strip(file_path, clip_id, duration_sec, n=12):
    """Bande-contact : n frames équidistantes en parallèle → un seul JPEG horizontal caché.

    Le _dedupe_compute évite que 2 requêtes concurrentes pour la même strip lancent 2x
    n ffmpeg ; le _ffmpeg_run interne plafonne déjà le parallélisme global. Le résultat :
    un hover rapide sur 20 clips n'inonde plus le système — chaque strip est calculée
    une seule fois, dans la limite des slots ffmpeg disponibles."""
    strip = THUMBNAILS_DIR / f"{clip_id}_strip{n}.jpg"
    if strip.exists():
        return strip
    try:
        from PIL import Image as _PIL
    except ImportError:
        return None

    src = _lighter_decode_source(file_path)
    def _do():
        from concurrent.futures import ThreadPoolExecutor
        W, H = 320, 180
        frames = [None] * n

        def _gen(i):
            t = max(0.0, i * duration_sec / n)
            tmp = THUMBNAILS_DIR / f"{clip_id}_stmp{i}.jpg"
            try:
                cmd = [FFMPEG, '-hide_banner', '-loglevel', 'error',
                       '-analyzeduration', '1M', '-probesize', '5M',
                       '-ss', f'{t:.2f}', '-i', src,
                       '-an', '-frames:v', '1',
                       '-vf', f'scale={W}:{H}:flags=fast_bilinear',
                       '-q:v', '5', '-y', str(tmp)]
                _ffmpeg_run(cmd, timeout=30)
                if tmp.exists():
                    frames[i] = tmp.read_bytes()
            except Exception:
                pass
            finally:
                try: tmp.unlink(missing_ok=True)
                except Exception: pass

        # Throttle interne: 3 workers max (au lieu de n=12 threads simultanés).
        # Combiné avec _ffmpeg_sem (max 8 ffmpeg globaux), évite qu'un seul
        # compute_strip sature la RAM en lançant 12 décodeurs HEVC en parallèle.
        with ThreadPoolExecutor(max_workers=3) as pool:
            list(pool.map(_gen, range(n)))

        imgs = []
        for data in frames:
            try:
                img = _PIL.open(io.BytesIO(data)).convert('RGB').resize((W, H), _PIL.LANCZOS) if data else None
            except Exception:
                img = None
            imgs.append(img or _PIL.new('RGB', (W, H), (10, 10, 20)))

        out = _PIL.new('RGB', (W * n, H))
        for i, img in enumerate(imgs):
            out.paste(img, (i * W, 0))
        out.save(str(strip), 'JPEG', quality=82)

    _dedupe_compute(f"strip:{clip_id}:{n}", _do, wait_timeout=180)
    return strip if strip.exists() else None


def compute_waveform_peaks(file_path, num_buckets=800, pan_filter=None):
    """Extrait les pics RMS normalisés d'une piste audio via ffmpeg.

    Utilise numpy pour le bucketing — un struct.unpack + boucle Python pure
    construisait un tuple Python géant (~300 MB à 1 GB pour un clip d'1h+)
    qui pouvait saturer la RAM système. Avec numpy on garde un buffer compact
    et toute l'arithmétique est vectorisée en C : ~10x moins de RAM, ~100x plus
    rapide.

    pan_filter : filtre ffmpeg -af à appliquer avant le décodage (ex: 'pan=mono|c0=c1'
    pour extraire le canal droit uniquement — utile sur les proxies FS5 dont le
    canal gauche contient le signal LTC biphase à amplitude quasi-constante)."""
    try:
        import numpy as np
    except ImportError:
        # Fallback : moins efficace mais pas de dépendance
        import struct, math
        try:
            if pan_filter:
                cmd = [FFMPEG, '-i', str(file_path),
                       '-af', pan_filter, '-ar', '4000', '-f', 's16le', '-vn',
                       '-loglevel', 'error', 'pipe:1']
            else:
                cmd = [FFMPEG, '-i', str(file_path),
                       '-ac', '1', '-ar', '4000', '-f', 's16le', '-vn',
                       '-loglevel', 'error', 'pipe:1']
            r = _ffmpeg_run(cmd, timeout=120)
            if not r.stdout or len(r.stdout) < 4: return []
            samples = struct.unpack(f'<{len(r.stdout)//2}h', r.stdout)
            if not samples: return []
            bsize = max(1, len(samples) // num_buckets)
            peaks = []
            for i in range(num_buckets):
                chunk = samples[i * bsize: min((i + 1) * bsize, len(samples))]
                if not chunk: peaks.append(0.0); continue
                rms = math.sqrt(sum(s * s for s in chunk) / len(chunk)) / 32767.0
                peaks.append(rms)
            mx = max(peaks) if peaks else 1.0
            if mx > 0: peaks = [round(p / mx, 4) for p in peaks]
            return peaks
        except Exception:
            return []
    try:
        if pan_filter:
            cmd = [FFMPEG, '-hide_banner', '-loglevel', 'error',
                   '-analyzeduration', '1M', '-probesize', '5M',
                   '-i', str(file_path),
                   '-vn', '-af', pan_filter, '-ar', '4000', '-f', 's16le',
                   'pipe:1']
        else:
            cmd = [FFMPEG, '-hide_banner', '-loglevel', 'error',
                   '-analyzeduration', '1M', '-probesize', '5M',
                   '-i', str(file_path),
                   '-vn', '-ac', '1', '-ar', '4000', '-f', 's16le',
                   'pipe:1']
        r = _ffmpeg_run(cmd, timeout=120)
        if not r.stdout or len(r.stdout) < 4:
            return []
        samples = np.frombuffer(r.stdout, dtype=np.int16)
        if samples.size == 0:
            return []
        bsize = max(1, samples.size // num_buckets)
        usable = bsize * num_buckets
        s = samples[:usable].astype(np.float32).reshape(num_buckets, bsize)
        rms = np.sqrt((s * s).mean(axis=1)) / 32767.0
        mx = float(rms.max()) if rms.size else 1.0
        if mx <= 0:
            return [0.0] * num_buckets
        normalized = rms / mx
        return [round(float(p), 4) for p in normalized]
    except Exception:
        return []

# ─── Multi-cam sync (TC-only) ───
# Two clips are paired iff their source TC ranges overlap (with a small grace).
# The lag between them is simply tc_b - tc_a — frame-accurate when both cameras
# are jam-synced. No audio analysis, no BWF lookup: when the camera TC is wrong
# (cf. FS5 days J04/J07/J10/J11 on DRIFT) the pair just won't be detected.

_MC_TC_GRACE = 5.0           # seconds of slack on TC overlap (covers small drift between models)

# In-memory job registry: pid → {status, progress, total, result, error}
_mc_jobs = {}
_mc_jobs_lock = threading.Lock()

# ─── LTC decoder ───
# Decodes Linear Timecode (LTC) embedded in an audio channel of a clip's proxy.
# Used to recover the *real* source TC when the camera's internal clock (exposed
# via `format.timecode`) is wrong — typically on the Sony FS5 which routes LTC
# from the multiprise to audio input 1 or 2.

_ltc_jobs = {}
_ltc_jobs_lock = threading.Lock()


def _ltc_extract_pcm(file_path, channel=0, max_sec=10.0, sample_rate=48000):
    """Extract one audio channel of a proxy as int16 mono PCM array via ffmpeg."""
    try:
        import numpy as np
    except ImportError:
        return None
    cmd = [FFMPEG, '-hide_banner', '-loglevel', 'error',
           '-t', str(max_sec), '-i', str(file_path),
           '-af', f'pan=mono|c0=c{channel}',
           '-ac', '1', '-ar', str(sample_rate),
           '-f', 's16le', '-vn', 'pipe:1']
    try:
        r = _ffmpeg_run(cmd, timeout=30)
        if r.returncode != 0 or not r.stdout:
            return None
        return np.frombuffer(r.stdout, dtype=np.int16)
    except Exception:
        return None


def _ltc_decode_pcm(pcm, sample_rate=48000, fps=25, min_consecutive_frames=3):
    """Decode LTC from a mono PCM int16 array.

    Returns the TC at the START of the PCM buffer, as seconds since midnight, or None.

    Key correctness points:
    1. A sync-word match alone is not enough — random noise can produce a false sync
       with a plausible BCD TC. We require `min_consecutive_frames` consecutive frames
       where each TC = previous TC + 1/fps. This rejects fake signals (chair creaks,
       silence noise floor) that happen to look like LTC bits for 80 bits.
    2. The first valid sync word can be several frames into the buffer (LTC takes a few
       frames to lock at clip start). We compute the sample offset of the validated frame
       and subtract it from the decoded TC so the returned value is the TC at PCM[0].
    """
    try:
        import numpy as np
    except ImportError:
        return None
    if pcm is None or len(pcm) < sample_rate / fps:
        return None
    s = pcm.astype(np.float32)
    s = s - s.mean()
    if s.std() < 100:
        return None  # silent channel

    signs = np.sign(s)
    signs[signs == 0] = 1
    zc = np.where(np.diff(signs) != 0)[0]
    if len(zc) < 80:
        return None

    intervals = np.diff(zc).astype(np.float32)
    bit_period = sample_rate / (80.0 * fps)
    threshold = bit_period * 0.75

    # Decode bits AND remember the interval index at which each bit starts
    # (so we can map a bit position back to a sample position).
    bits = []
    bit_to_iv = []     # bit_to_iv[k] = index in `intervals` where bit k starts
    i = 0
    n = len(intervals)
    while i < n:
        if intervals[i] > threshold:
            bit_to_iv.append(i)
            bits.append(0)
            i += 1
        else:
            if i + 1 < n and intervals[i+1] < threshold:
                bit_to_iv.append(i)
                bits.append(1)
                i += 2
            else:
                i += 1  # glitch, skip
    if len(bits) < 80:
        return None

    SYNC = [0, 0, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 0, 1]
    frame_period = 1.0 / fps

    def _bcd(bs):
        return sum(b << k for k, b in enumerate(bs))

    def _decode_frame(fb):
        ff = _bcd(fb[8:10]) * 10 + _bcd(fb[0:4])
        ss = _bcd(fb[24:27]) * 10 + _bcd(fb[16:20])
        mm = _bcd(fb[40:43]) * 10 + _bcd(fb[32:36])
        hh = _bcd(fb[56:58]) * 10 + _bcd(fb[48:52])
        if hh >= 24 or mm >= 60 or ss >= 60 or ff >= fps:
            return None
        return hh * 3600 + mm * 60 + ss + ff / fps

    # Scan for runs of consecutive valid frames
    max_start = len(bits) - 80 * min_consecutive_frames
    for start in range(max_start):
        if bits[start+64:start+80] != SYNC:
            continue
        tc0 = _decode_frame(bits[start:start+80])
        if tc0 is None:
            continue
        # Verify min_consecutive_frames-1 follow-on frames
        ok = True
        for k in range(1, min_consecutive_frames):
            off = start + 80 * k
            if off + 80 > len(bits) or bits[off+64:off+80] != SYNC:
                ok = False; break
            tck = _decode_frame(bits[off:off+80])
            if tck is None:
                ok = False; break
            # Expect tck ≈ tc0 + k * frame_period (mod 24h wraparound)
            expected = (tc0 + k * frame_period) % (24 * 3600)
            if abs(tck - expected) > frame_period * 0.5:
                ok = False; break
        if not ok:
            continue
        # Validated stream. Compute sample position of the start of this frame
        # to derive the TC at PCM[0].
        iv_idx = bit_to_iv[start] if start < len(bit_to_iv) else 0
        sample_pos = int(zc[iv_idx]) if iv_idx < len(zc) else 0
        offset_sec = sample_pos / float(sample_rate)
        return round((tc0 - offset_sec) % (24 * 3600), 3)
    return None


def _ltc_proxy_path(clip, project):
    """Resolve the local filesystem path of a clip's proxy. Returns Path or None."""
    if clip.get('proxy_url'):
        rel = unquote(clip['proxy_url'][7:]).replace('\\', '/')
        for u in project.get('users', []):
            rp = u.get('root_path') or project.get('root_path', '')
            if not rp: continue
            resolved = _resolve_relpath_tolerant(rp, rel)
            if resolved is not None:
                return resolved
    p = Path(clip.get('path', ''))
    return p if p.exists() else None


def decode_project_ltc(project, pid, progress_cb=None, force=False):
    """Decode LTC for every clip of the project whose proxy contains an LTC signal.
    Stores result in clip['ltc_tc_in_sec'] (None if no LTC was found).
    Skips clips already decoded unless force=True.

    progress_cb(done, total, current_name) called after each clip.
    Returns (n_with_ltc, n_without_ltc, n_skipped, n_errors)."""
    clips = project.get('clips', [])
    total = len(clips)
    n_with = n_without = n_skip = n_err = 0
    for idx, c in enumerate(clips, 1):
        if not force and 'ltc_tc_in_sec' in c:
            # Already cached (even if None)
            if c.get('ltc_tc_in_sec') is not None:
                n_with += 1
            else:
                n_without += 1
            n_skip += 1
            if progress_cb: progress_cb(idx, total, c.get('stem') or c.get('id', '?'))
            continue
        path = _ltc_proxy_path(c, project)
        if not path:
            c['ltc_tc_in_sec'] = None
            n_err += 1
        else:
            fps = round(c.get('fps', 25)) or 25
            pcm = _ltc_extract_pcm(str(path), channel=0, max_sec=8.0, sample_rate=48000)
            tc = _ltc_decode_pcm(pcm, sample_rate=48000, fps=fps) if pcm is not None else None
            c['ltc_tc_in_sec'] = tc
            if tc is not None:
                n_with += 1
            else:
                n_without += 1
        if progress_cb: progress_cb(idx, total, c.get('stem') or c.get('id', '?'))
    return n_with, n_without, n_skip, n_err


def _decode_ltc_job(pid, force=False):
    """Background worker for /decode_ltc. Updates _ltc_jobs[pid] in place."""
    proj = load_project(pid)
    if not proj:
        with _ltc_jobs_lock:
            _ltc_jobs[pid] = {'status': 'error', 'error': 'Projet introuvable'}
        return
    started = _time.time()
    with _ltc_jobs_lock:
        _ltc_jobs[pid] = {'status': 'running', 'done': 0, 'total': len(proj.get('clips', [])),
                          'started_at': started, 'current': ''}

    def _cb(done, total, name):
        with _ltc_jobs_lock:
            j = _ltc_jobs.setdefault(pid, {})
            j['done'] = done
            j['total'] = total
            j['current'] = name

    try:
        n_with, n_without, n_skip, n_err = decode_project_ltc(proj, pid, _cb, force=force)
        # Re-charge sous verrou et ne réécrit que les clips — préserve les
        # annotations faites pendant le décodage (audit 1.1).
        with _project_lock(pid):
            _fresh = load_project(pid) or proj
            _fresh['clips'] = proj['clips']
            save_project(pid, _fresh)
        with _ltc_jobs_lock:
            _ltc_jobs[pid] = {'status': 'done',
                              'n_with_ltc': n_with, 'n_without_ltc': n_without,
                              'n_skipped': n_skip, 'n_errors': n_err,
                              'total': len(proj.get('clips', [])),
                              'elapsed': _time.time() - started}
    except Exception as e:
        with _ltc_jobs_lock:
            _ltc_jobs[pid] = {'status': 'error', 'error': str(e)}

# ─── BWF / Multiprise TC-sync ───

def _read_bwf_bext_direct(file_path):
    """Parse BEXT chunk directly from a WAV/BWF file (no subprocess). Returns dict or None."""
    try:
        with open(file_path, 'rb') as f:
            hdr = f.read(12)
            if len(hdr) < 12 or hdr[:4] != b'RIFF' or hdr[8:12] != b'WAVE':
                return None
            sr = channels = bits = time_ref = data_bytes = None
            while True:
                ch = f.read(8)
                if len(ch) < 8: break
                cid = ch[:4]
                csz = _struct.unpack_from('<I', ch, 4)[0]
                pos = f.tell()
                if cid == b'fmt ':
                    d = f.read(min(csz, 40))
                    if len(d) >= 16:
                        sr = _struct.unpack_from('<I', d, 4)[0]
                        channels = _struct.unpack_from('<H', d, 2)[0]
                        bits = _struct.unpack_from('<H', d, 14)[0]
                elif cid == b'bext':
                    d = f.read(min(csz, 350))
                    if len(d) >= 346:
                        trl = _struct.unpack_from('<I', d, 338)[0]
                        trh = _struct.unpack_from('<I', d, 342)[0]
                        time_ref = (trh << 32) | trl
                        # OriginationDate offset 320-329 (10 bytes "YYYY-MM-DD" ou "YYYY:MM:DD")
                        try:
                            raw_date = d[320:330].decode('ascii', errors='replace').strip('\x00 ').strip()
                            # Normaliser séparateur : "YYYY:MM:DD" → "YYYY-MM-DD"
                            origination_date = raw_date.replace(':', '-') if len(raw_date) == 10 else None
                        except Exception:
                            origination_date = None
                elif cid == b'data':
                    data_bytes = csz
                f.seek(pos + csz + (csz & 1), 0)
                if sr and time_ref is not None and data_bytes is not None:
                    break
        if not sr or sr <= 0 or time_ref is None:
            return None
        tc_in_sec = time_ref / sr
        duration_sec = None
        if data_bytes and channels and bits:
            bps = bits // 8
            if bps > 0 and channels > 0:
                duration_sec = data_bytes / (sr * channels * bps)
        return {'tc_in_sec': round(tc_in_sec, 3), 'sample_rate': sr,
                'channels': channels or 1, 'duration_sec': duration_sec,
                'origination_date': locals().get('origination_date')}
    except Exception:
        return None

def _read_bwf_tc_ffprobe(file_path):
    """ffprobe fallback: reads time_reference tag from BWF/WAV."""
    try:
        cmd = [FFPROBE, '-v', 'error', '-show_entries',
               'format_tags=time_reference:stream=sample_rate,channels,duration',
               '-of', 'json', str(file_path)]
        r = _ffmpeg_run(cmd, timeout=15)
        if r.returncode != 0: return None
        d = json.loads(r.stdout.decode('utf-8', errors='replace'))
        sr = channels = duration = None
        for st in d.get('streams', []):
            if st.get('sample_rate'):
                sr = int(st['sample_rate'])
                channels = int(st.get('channels', 1) or 1)
                try: duration = float(st.get('duration') or 0) or None
                except Exception: pass
                break
        time_ref_s = (d.get('format', {}).get('tags') or {}).get('time_reference')
        if sr and sr > 0 and time_ref_s:
            tc_in_sec = int(time_ref_s) / sr
            return {'tc_in_sec': round(tc_in_sec, 3), 'sample_rate': sr,
                    'channels': channels or 1, 'duration_sec': duration}
    except Exception:
        pass
    return None

def read_bwf_tc(file_path):
    """Read TC from a BWF/WAV file. Returns dict with tc_in_sec, duration_sec, etc. or None."""
    result = _read_bwf_bext_direct(file_path)
    if result: return result
    return _read_bwf_tc_ffprobe(file_path)

def _clip_origination_date(clip):
    """Extrait la date d'origine du clip (YYYY-MM-DD) depuis creation_date ou path."""
    cd = clip.get('creation_date', '') or ''
    if len(cd) >= 10 and cd[4] in '-:' and cd[7] in '-:':
        return cd[:10].replace(':', '-')
    # Fallback : chercher un pattern YYYY-MM-DD ou YYYY_MM_DD dans clip_id ou path
    for s in (clip.get('id', ''), clip.get('path', '')):
        m = re.search(r'(20\d{2})[_\-:](\d{2})[_\-:](\d{2})', s)
        if m: return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    return None

def _bwf_origination_date(af):
    """Date BWF normalisée YYYY-MM-DD (depuis scan ou lecture à la volée)."""
    d = af.get('origination_date')
    if d: return d.replace(':', '-')[:10]
    # Lecture à la volée si pas dans le scan (vieux scan sans date)
    p = af.get('path', '')
    if p and Path(p).exists():
        info = read_bwf_tc(p)
        if info and info.get('origination_date'):
            return info['origination_date'].replace(':', '-')[:10]
    return None

def _resolve_audio_clip_path(ac, proj):
    """Resolve an audio clip's path, handling cross-platform migration.
    Stored paths may be Windows absolute paths (D:\\DRIFT_CLUB\\...) that don't
    exist on macOS. Strips the stored root and retries with each user's root_path."""
    stored = ac.get('path', '')
    fp = Path(stored)
    if fp.exists():
        return fp
    stored_norm = stored.replace('\\', '/')
    # Collect all candidate roots to try stripping
    all_roots = []
    proj_root = proj.get('root_path', '')
    if proj_root:
        all_roots.append(proj_root.replace('\\', '/').rstrip('/'))
    for u in proj.get('users', []):
        rp = u.get('root_path', '')
        if rp:
            all_roots.append(rp.replace('\\', '/').rstrip('/'))
    for base in all_roots:
        if not base:
            continue
        if stored_norm.lower().startswith(base.lower() + '/'):
            rel = stored_norm[len(base) + 1:]
            for u in proj.get('users', []):
                rp = u.get('root_path', '')
                if not rp:
                    continue
                candidate = Path(rp) / rel
                if candidate.exists():
                    return candidate
    return None


def _bwf_candidates_for_clips(audio_clips, clip_ids, clip_map, grace=2):
    """Retourne la liste des BWF qui contiennent strictement TOUS les clips
    (grace ±2s seulement) ET qui matchent la date des clips.
    Triée du plus contenant au moins contenant (BWF qui démarre juste avant
    le premier clip et finit juste après le dernier = idéal)."""
    # Date attendue : celle du earliest clip
    clip_dates = set()
    for cid in clip_ids:
        c = clip_map.get(cid)
        if c:
            d = _clip_origination_date(c)
            if d: clip_dates.add(d)
    # Calcul des TC des clips (préfère LTC décodé, fallback format.timecode)
    clip_tcs = []
    for cid in clip_ids:
        c = clip_map.get(cid)
        if not c: continue
        tc_c = _clip_tc_seconds(c)
        dur_c = c.get('duration_sec') or 0
        if tc_c is None: continue
        clip_tcs.append((tc_c, tc_c + dur_c))
    if not clip_tcs: return []
    first_tc = min(t[0] for t in clip_tcs)
    last_tc  = max(t[1] for t in clip_tcs)
    candidates = []
    for af in audio_clips:
        tc_s = af.get('tc_in_sec'); dur_s = af.get('duration_sec') or 0
        if tc_s is None or dur_s <= 0: continue
        # Le BWF doit strictement contenir tous les clips (avec grace ±2s)
        if not (tc_s - grace <= first_tc and last_tc <= tc_s + dur_s + grace):
            continue
        # Filtre date : strict si on connaît les deux
        if clip_dates:
            bwf_date = _bwf_origination_date(af)
            if bwf_date and bwf_date not in clip_dates:
                continue
        # Score = à quel point le BWF "colle" aux clips (petit = bien)
        # Un BWF qui démarre 30s avant les clips est moins bon qu'un qui démarre 1s avant
        slack = (first_tc - tc_s) + (tc_s + dur_s - last_tc)
        candidates.append((slack, af))
    candidates.sort(key=lambda x: x[0])
    return [c[1] for c in candidates]

def scan_son_dir(son_dir):
    """Scan a directory for BWF/WAV files with BEXT timecode.
    Returns list of {id, filename, path, tc_in_sec, duration_sec, sample_rate, channels}."""
    root = Path(son_dir)
    if not root.exists(): return []
    audio_files = []
    for f in sorted(root.rglob('*')):
        if f.suffix.lower() not in ('.wav', '.bwf', '.w64') or not f.is_file():
            continue
        info = read_bwf_tc(str(f))
        if not info or info.get('tc_in_sec') is None:
            continue
        fid = re.sub(r'[^a-zA-Z0-9_]', '_', f.stem)
        audio_files.append({
            'id': fid,
            'filename': f.name,
            'path': str(f),
            'tc_in_sec': info['tc_in_sec'],
            'duration_sec': info.get('duration_sec'),
            'sample_rate': info.get('sample_rate'),
            'channels': info.get('channels', 1),
            'origination_date': info.get('origination_date'),
        })
    return audio_files

def _clip_tc_seconds(clip):
    """Return the most reliable TC (in seconds since midnight) for a clip.
    Prefers LTC decoded from audio (frame-accurate, wall-clock real time) over
    the camera's `format.timecode` tag (internal clock, often wrong on FS5).
    Returns None if neither source is available."""
    ltc = clip.get('ltc_tc_in_sec')
    if ltc is not None:
        return float(ltc)
    fps = round(clip.get('fps', 25)) or 25
    return tc_to_seconds(clip.get('tc_in', ''), fps)


def _tc_pair_lag(clip_a, clip_b):
    """If the two clips' source TC ranges overlap (with _MC_TC_GRACE slack), return
    lag = tc_b - tc_a (seconds, positive when b starts after a). Otherwise None.

    Uses LTC TC when available (frame-accurate), falls back to `format.timecode`
    (camera internal clock — only reliable for FX6 jam-synced via SDI).
    When the camera TC is wrong AND no LTC is available, the ranges won't
    overlap and no pair is produced, which is the intended behaviour."""
    tc_a = _clip_tc_seconds(clip_a)
    tc_b = _clip_tc_seconds(clip_b)
    if tc_a is None or tc_b is None: return None
    dur_a = clip_a.get('duration_sec', 0) or 0
    dur_b = clip_b.get('duration_sec', 0) or 0
    if not (tc_a < tc_b + dur_b + _MC_TC_GRACE and tc_b < tc_a + dur_a + _MC_TC_GRACE):
        return None
    return round(tc_b - tc_a, 3)

def _temporal_candidate(a, b):
    """True if two clips' source TCs overlap (with _MC_TC_GRACE slack).
    Uses LTC TC when available (via _clip_tc_seconds), else falls back to
    `format.timecode`. No other fallback: pair is rejected if neither TC works."""
    sa = _clip_tc_seconds(a)
    sb = _clip_tc_seconds(b)
    if sa is None or sb is None: return False
    da = a.get('duration_sec', 0) or 0
    db = b.get('duration_sec', 0) or 0
    return sa < sb + db + _MC_TC_GRACE and sb < sa + da + _MC_TC_GRACE

def detect_multicam_groups(project, pid, progress_cb=None):
    """Build multicam groups by pairing clips whose source TC ranges overlap.

    Lag between paired clips = tc_b - tc_a (frame-accurate when both cameras
    are jam-synced). No audio analysis: if a camera's TC is wrong, no pair forms
    — which is exactly what we want for the FS5 on days J04/J07/J10/J11.

    Preserves clips already in validated groups (multicam_groups) or proposals
    (multicam_proposals) — they're skipped so user-tuned offsets survive re-runs.

    progress_cb signature: (phase, done, total) where phase in {'pairs', 'correlate'}."""
    clips = project.get('clips', [])
    if len(clips) < 2:
        return []

    already_grouped = set()
    for coll in ('multicam_groups', 'multicam_proposals'):
        for g in project.get(coll, []):
            for cid in g.get('clip_ids', []):
                already_grouped.add(cid)

    if progress_cb: progress_cb('pairs', 0, 0)
    by_day = {}
    for c in clips:
        if c['id'] in already_grouped: continue
        by_day.setdefault(c.get('day', ''), []).append(c)

    pairs = []
    for day_clips in by_day.values():
        for i in range(len(day_clips)):
            for j in range(i + 1, len(day_clips)):
                a, b = day_clips[i], day_clips[j]
                if a.get('camera') and a.get('camera') == b.get('camera'):
                    continue
                if _temporal_candidate(a, b):
                    pairs.append((a, b))

    if not pairs:
        if progress_cb: progress_cb('correlate', 0, 0)
        return []

    # ── Collect edges: each TC-overlapping pair → (id_a, id_b, lag).
    # lag = tc_b - tc_a (positive when b starts after a). offsets[X] is the
    # group-time start of X (higher = later), so BFS does offsets[b] = offsets[a] + lag.
    edges = []
    corr_total = len(pairs)
    if progress_cb: progress_cb('correlate', 0, corr_total)
    for idx, (a, b) in enumerate(pairs, 1):
        lag = _tc_pair_lag(a, b)
        if lag is not None:
            edges.append((a['id'], b['id'], lag))
        if progress_cb: progress_cb('correlate', idx, corr_total)

    # ── Greedy camera-constrained grouping
    # One clip per camera per group. Tightest temporal matches (|lag| ASC) first
    # to prevent transitive chaining across far-apart consecutive shots.
    edges.sort(key=lambda e: abs(e[2]))

    clip_cam = {c['id']: (c.get('camera') or '') for c in clips}
    clip_to_grp = {}
    grp_cams   = []
    grp_clips  = []
    grp_edges  = []

    def _new_grp(a_id, b_id, edge):
        g = len(grp_clips)
        grp_clips.append([a_id, b_id])
        grp_cams.append({clip_cam[a_id], clip_cam[b_id]})
        grp_edges.append([edge])
        clip_to_grp[a_id] = g
        clip_to_grp[b_id] = g

    def _add_clip(g, cid, edge):
        clip_to_grp[cid] = g
        grp_clips[g].append(cid)
        grp_cams[g].add(clip_cam[cid])
        grp_edges[g].append(edge)

    for edge in edges:
        a_id, b_id = edge[0], edge[1]
        cam_a, cam_b = clip_cam.get(a_id, ''), clip_cam.get(b_id, '')
        ga = clip_to_grp.get(a_id)
        gb = clip_to_grp.get(b_id)

        if ga is None and gb is None:
            _new_grp(a_id, b_id, edge)
        elif ga is not None and gb is None:
            if not cam_b or cam_b not in grp_cams[ga]:
                _add_clip(ga, b_id, edge)
        elif ga is None and gb is not None:
            if not cam_a or cam_a not in grp_cams[gb]:
                _add_clip(gb, a_id, edge)
        elif ga != gb:
            if not (grp_cams[ga] & grp_cams[gb]):
                if len(grp_clips[ga]) < len(grp_clips[gb]):
                    ga, gb = gb, ga
                for cid in grp_clips[gb]:
                    clip_to_grp[cid] = ga
                grp_clips[ga].extend(grp_clips[gb])
                grp_cams[ga] |= grp_cams[gb]
                grp_edges[ga].extend(grp_edges[gb])
                grp_clips[gb] = []
                grp_cams[gb] = set()
                grp_edges[gb] = []

    # ── BFS over each group's edges to propagate offsets
    from collections import deque
    groups = []
    for g_idx, g_clip_ids in enumerate(grp_clips):
        if len(g_clip_ids) < 2: continue
        root = g_clip_ids[0]
        offsets = {root: 0.0}
        adj = {}
        for a_id, b_id, lag in grp_edges[g_idx]:
            adj.setdefault(a_id, []).append((b_id, lag))
            adj.setdefault(b_id, []).append((a_id, -lag))
        q = deque([root])
        while q:
            cur = q.popleft()
            for nb, lag in adj.get(cur, []):
                if nb not in offsets:
                    offsets[nb] = offsets[cur] + lag
                    q.append(nb)
        offsets = {k: round(v, 3) for k, v in offsets.items() if k in set(g_clip_ids)}
        if len(offsets) < 2: continue
        groups.append({
            'id': 'mc_' + secrets.token_hex(4),
            'clip_ids': sorted(offsets.keys(), key=lambda x: offsets[x]),
            'offsets': offsets,
            'score': 1.0,
            'sync_method': 'tc',
            'detected_at': datetime.utcnow().isoformat(),
        })
    return groups

def _detect_multicam_job(pid):
    """Background worker for /detect_multicam. Updates _mc_jobs[pid] in place.

    Tracks per-phase progress + the wall-clock timestamp of the last update so
    the frontend can compute ETA = remaining * elapsed/done."""
    proj = load_project(pid)
    if not proj:
        with _mc_jobs_lock:
            _mc_jobs[pid] = {'status': 'error', 'error': 'Projet introuvable'}
        return

    def _cb(phase, done, total):
        now = _time.time()
        with _mc_jobs_lock:
            job = _mc_jobs.setdefault(pid, {})
            job['phase'] = phase
            if phase == 'correlate':
                if 'corr_started_at' not in job: job['corr_started_at'] = now
                job['corr_done'] = done
                job['corr_total'] = total

    try:
        with _mc_jobs_lock:
            _mc_jobs[pid] = {'status': 'running', 'phase': 'pairs',
                              'corr_done': 0, 'corr_total': 0,
                              'started_at': _time.time()}
        groups = detect_multicam_groups(proj, pid, _cb)
        # Append to existing proposals (detect_multicam_groups already skips clips in
        # validated groups & proposals, so `groups` only contains new ones). This way
        # the user can iterate detection runs without losing previously found proposals.
        # Re-charge le projet sous verrou avant d'écrire (audit 1.1).
        with _project_lock(pid):
            proj = load_project(pid) or proj
            existing = proj.get('multicam_proposals', [])
            existing_ids = {g['id'] for g in existing}
            new_groups = [g for g in groups if g['id'] not in existing_ids]
            proj['multicam_proposals'] = existing + new_groups
            save_project(pid, proj)
        with _mc_jobs_lock:
            _mc_jobs[pid] = {'status': 'done', 'group_count': len(new_groups),
                             'total_proposals': len(proj['multicam_proposals']),
                             'groups': new_groups}
    except Exception as e:
        with _mc_jobs_lock:
            _mc_jobs[pid] = {'status': 'error', 'error': str(e)}

# ─── Auto-détection de plans (scene change via ffmpeg) ──────────────────────
# Scanne les clips et identifie les moments significatifs (cuts embarqués,
# transitions, etc.) via le filtre ffmpeg `select='gt(scene,X)'`. Stocke les
# candidats dans proj['auto_detected'][clip_id] — séparé des notes utilisateur
# pour permettre rescan sans pollution. Les candidats acceptés deviennent des
# vrais markers (cat='D'), les rejetés sont mémorisés pour ne pas re-suggérer.

_auto_detect_jobs = {}
_auto_detect_jobs_lock = threading.Lock()

def detect_scenes_for_clip(file_path, threshold=0.4, timeout=300):
    """Retourne une liste de timestamps (en secondes) où ffmpeg détecte un changement
    de scène. Threshold typique : 0.3 (agressif) à 0.7 (conservateur).

    Notes :
    - En mode argv (subprocess sans shell), les single-quotes shell-style ne sont
      pas interprétées par ffmpeg. On échappe donc la virgule de `scene,X` avec
      backslash pour éviter qu'ffmpeg la prenne comme un séparateur de filtres.
    - On utilise aussi -vsync vfr -an pour aller plus vite (skip audio, sync frames).
    """
    # Format correct argv-style : virgule échappée avec \\
    # IMPORTANT : showinfo n'imprime ses lignes qu'à partir de -loglevel verbose,
    # pas en `info` (qui est le défaut). Sans ça, on récupère 0 candidat.
    filter_str = f"select=gt(scene\\,{threshold}),showinfo"
    cmd = [FFMPEG, '-hide_banner', '-loglevel', 'verbose',
           '-analyzeduration', '5M', '-probesize', '10M',
           '-i', str(file_path),
           '-an',
           '-filter:v', filter_str,
           '-f', 'null', '-']
    try:
        r = _ffmpeg_run(cmd, timeout=timeout)
    except subprocess.TimeoutExpired:
        return []
    stderr = (r.stderr or b'').decode('utf-8', errors='replace')
    import re as _re
    times = []
    # IMPORTANT : regex stricte = uniquement les lignes showinfo, sinon on matche
    # aussi la ligne verbose "[graph -1 input ...] video frame properties congruent
    # with link at pts_time: 0" qui crée un faux positif à t=0.
    for m in _re.finditer(r'\[Parsed_showinfo[^\]]*\][^\n]*pts_time:([0-9.]+)', stderr):
        try:
            times.append(float(m.group(1)))
        except ValueError:
            pass
    # Filtre les doublons proches (< 0.5s) qui peuvent venir de bursts de I-frames
    deduped = []
    for t in times:
        if not deduped or t - deduped[-1] >= 0.5:
            deduped.append(t)
    return deduped

def _auto_detect_job(pid, threshold=0.4, clip_ids=None):
    """Background worker : scan tous (ou clip_ids) les clips du projet."""
    proj = load_project(pid)
    if not proj:
        with _auto_detect_jobs_lock:
            _auto_detect_jobs[pid] = {'status': 'error', 'error': 'Projet introuvable'}
        return
    clips = proj.get('clips', [])
    if clip_ids:
        clips = [c for c in clips if c['id'] in clip_ids]
    total = len(clips)
    with _auto_detect_jobs_lock:
        _auto_detect_jobs[pid] = {'status': 'running', 'done': 0, 'total': total, 'current': '', 'new_candidates': 0}
    proj.setdefault('auto_detected', {})
    new_count = 0
    for i, clip in enumerate(clips):
        with _auto_detect_jobs_lock:
            _auto_detect_jobs[pid].update({'done': i, 'current': clip.get('stem', clip['id'])})
        file_path = _resolve_clip_local_path(proj, clip)
        if not file_path:
            continue
        try:
            times = detect_scenes_for_clip(str(file_path), threshold)
        except Exception:
            continue
        # Existing markers (toutes équipes) pour ne pas suggérer en double
        existing_times = set()
        for u in proj.get('users', []):
            uid = user_note_key(u)
            cn = (proj.get('notes', {}).get(uid) or {}).get(clip['id'])
            if cn:
                for m in cn.get('markers', []):
                    existing_times.add(round(m.get('time', 0), 1))
        # Conserve les décisions précédentes (accepted/rejected) pour les mêmes timestamps
        prev_candidates = proj['auto_detected'].get(clip['id'], {}).get('candidates', [])
        prev_by_time = {round(c.get('time', 0), 1): c for c in prev_candidates}
        new_candidates = []
        for t in times:
            t_rounded = round(t, 1)
            if any(abs(t - et) < 1.0 for et in existing_times):
                continue
            if t_rounded in prev_by_time:
                new_candidates.append(prev_by_time[t_rounded])
            else:
                new_candidates.append({
                    'id': secrets.token_hex(4),
                    'time': t,
                    'type': 'scene',
                    'status': 'pending',
                })
                new_count += 1
        # Écrit le résultat de ce clip sous verrou, sur une copie fraîche du
        # projet — préserve les annotations concurrentes (audit 1.1).
        with _project_lock(pid):
            proj = load_project(pid) or proj
            proj.setdefault('auto_detected', {})[clip['id']] = {
                'candidates': new_candidates,
                'scanned_at': datetime.now().isoformat(timespec='seconds'),
                'threshold': threshold,
            }
            save_project(pid, proj)
    with _auto_detect_jobs_lock:
        _auto_detect_jobs[pid] = {'status': 'done', 'done': total, 'total': total, 'new_candidates': new_count}

# ─── Project stats (dashboard) ──────────────────────────────────────────────
def project_stats(proj):
    """Agrège les stats du projet pour le dashboard : totaux, distribution par
    user, par rating, par catégorie, par caméra, par jour, top tags."""
    clips = proj.get('clips', [])
    notes = proj.get('notes', {})
    users = proj.get('users', [])

    # Map username → user info (pour color/role)
    user_by_id = {user_note_key(u): {'name': u.get('username') or u.get('name', ''), 'color': u.get('color', '#888')} for u in users}

    total_clips = len(clips)
    clips_with_any_anno = set()
    clips_rated = set()       # clips avec au moins un rating (1/2/3)
    clips_rejected = set()    # clips avec rating X
    clips_validated = set()   # status='valide'
    clips_to_review = set()   # status='arevoir'

    total_markers = 0
    total_tags_set = set()    # tags uniques
    tag_counts = {}           # tag → count
    cat_counts = {'1':0, '2':0, '3':0, 'X':0, 'T':0, 'S':0, 'D':0}
    rating_dist = {'3':0, '2':0, '1':0, 'X':0, 'none':0}

    by_user = {}              # uid → {markers, ratings, tags, last_ts}
    for uid, user_notes in notes.items():
        u_stats = by_user.setdefault(uid, {
            'name': user_by_id.get(uid, {}).get('name', uid),
            'color': user_by_id.get(uid, {}).get('color', '#888'),
            'markers': 0, 'ratings': 0, 'tags': 0, 'clips_touched': 0,
        })
        for clip_id, cn in user_notes.items():
            if not cn: continue
            touched = False
            r = cn.get('rating')
            if r in ('1','2','3'):
                u_stats['ratings'] += 1
                clips_rated.add(clip_id); touched = True
            elif r == 'X':
                clips_rejected.add(clip_id); touched = True
            status = cn.get('status')
            if status == 'valide': clips_validated.add(clip_id); touched = True
            elif status == 'arevoir': clips_to_review.add(clip_id); touched = True
            mks = cn.get('markers', [])
            for m in mks:
                cat = str(m.get('cat', ''))
                if cat in cat_counts: cat_counts[cat] += 1
                total_markers += 1
                u_stats['markers'] += 1
                touched = True
            tg_list = cn.get('tags', [])
            for t in tg_list:
                if not t: continue
                tag_counts[t] = tag_counts.get(t, 0) + 1
                total_tags_set.add(t)
                u_stats['tags'] += 1
                touched = True
            if (cn.get('notes') or '').strip(): touched = True
            if touched:
                clips_with_any_anno.add(clip_id)
                u_stats['clips_touched'] = u_stats.get('clips_touched', 0) + 1

    # Rating distribution global (max rating across users per clip)
    for c in clips:
        max_r = 'none'
        rejected = False
        for u in users:
            uid = user_note_key(u)
            cn = (notes.get(uid) or {}).get(c['id'])
            if not cn: continue
            r = str(cn.get('rating', ''))
            if r == 'X': rejected = True
            elif r in ('3','2','1') and (max_r == 'none' or int(r) > int(max_r if max_r != 'none' else '0')):
                max_r = r
        if rejected: rating_dist['X'] += 1
        elif max_r != 'none': rating_dist[max_r] += 1
        else: rating_dist['none'] += 1

    # Distribution par caméra
    cam_counts = {}
    for c in clips:
        cam = c.get('camera') or '?'
        cam_counts[cam] = cam_counts.get(cam, 0) + 1

    # Distribution par jour
    day_counts = {}
    for c in clips:
        d = c.get('day') or '?'
        day_counts[d] = day_counts.get(d, 0) + 1

    # Top 10 tags
    top_tags = sorted(tag_counts.items(), key=lambda x: -x[1])[:10]

    return {
        'totals': {
            'clips': total_clips,
            'clips_touched': len(clips_with_any_anno),
            'clips_untouched': total_clips - len(clips_with_any_anno),
            'clips_rated': len(clips_rated),
            'clips_rejected': len(clips_rejected),
            'clips_validated': len(clips_validated),
            'clips_to_review': len(clips_to_review),
            'markers': total_markers,
            'unique_tags': len(total_tags_set),
            'users': len(users),
        },
        'by_user': list(by_user.values()),
        'cat_counts': cat_counts,
        'rating_dist': rating_dist,
        'cam_counts': cam_counts,
        'day_counts': day_counts,
        'top_tags': [{'tag': t, 'count': c} for t, c in top_tags],
    }

# ─── Import Functions ───

def project_health(proj, pid):
    clips = proj.get('clips', [])
    notes = proj.get('notes', {})

    # ─ Médias ─
    without_proxy = [c['stem'] for c in clips if not c.get('proxy_url')]
    missing_source = [c['stem'] for c in clips if c.get('path') and not Path(c['path']).exists()]
    zero_dur = [c['stem'] for c in clips if not c.get('duration_sec') or c['duration_sec'] < 0.1]

    # ─ Timecode ─
    without_tc = [c['stem'] for c in clips if not c.get('tc_in') or c['tc_in'] == '00:00:00:00']
    fps_count = Counter(round(c.get('fps', 25)) for c in clips)
    majority_fps = fps_count.most_common(1)[0][0] if fps_count else 25
    wrong_fps = [c['stem'] for c in clips if round(c.get('fps', 25)) != majority_fps]

    # ─ Annotations ─
    clips_rated = set()
    total_markers = 0
    out_of_range = []
    for uid, un in notes.items():
        for cid, cn in un.items():
            if cn.get('rating'): clips_rated.add(cid)
            clip = next((c for c in clips if c['id'] == cid), None)
            for m in cn.get('markers', []):
                total_markers += 1
                if clip and m.get('time', 0) > clip.get('duration_sec', 0) + 0.1:
                    out_of_range.append({'clip': clip.get('stem', cid), 'tc': m.get('tc', '?')})

    # ─ Exports ─
    special_chars = [c['stem'] for c in clips if any(ord(ch) > 127 for ch in c.get('stem', ''))]

    # ─ Infrastructure ─
    mins_ago = None
    modified = proj.get('modified', '')
    if modified:
        try:
            delta = datetime.now() - datetime.fromisoformat(modified)
            mins_ago = int(delta.total_seconds() / 60)
        except Exception:
            pass
    backup_dir = BACKUPS_DIR / pid
    backup_count = len(list(backup_dir.glob('*.json'))) if backup_dir.exists() else 0

    # ─ ffmpeg check ─
    def _check(cmd):
        try:
            r = subprocess.run([cmd, '-version'], capture_output=True, timeout=5, creationflags=_NO_WINDOW)
            return r.returncode == 0
        except Exception:
            return False

    return {
        'media': {
            'total': len(clips),
            'with_proxy': len(clips) - len(without_proxy),
            'without_proxy': without_proxy,
            'missing_source': missing_source,
            'zero_duration': zero_dur,
        },
        'timecode': {
            'with_tc': len(clips) - len(without_tc),
            'without_tc': without_tc,
            'fps_distribution': dict(fps_count),
            'majority_fps': majority_fps,
            'wrong_fps': wrong_fps,
        },
        'annotations': {
            'users': len(proj.get('users', [])),
            'clips_rated': len(clips_rated),
            'total_clips': len(clips),
            'total_markers': total_markers,
            'out_of_range': out_of_range,
        },
        'exports': {
            'special_char_clips': special_chars,
            'out_of_range_markers': out_of_range,
            'clips_no_tc': without_tc,
        },
        'infrastructure': {
            'last_save_mins_ago': mins_ago,
            'backup_count': backup_count,
            'ffmpeg_ok': _check(FFMPEG),
            'ffprobe_ok': _check(FFPROBE),
        },
    }

def import_edl(edl_text, user_id):
    markers_by_clip = {}
    lines = edl_text.strip().split('\n')
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        # Match event line
        match = re.match(r'(\d+)\s+(\S+)\s+', line)
        if match:
            clip_name = match.group(2).strip()
            parts = line.split()
            if len(parts) >= 9:
                tc = parts[5]  # source in
            else:
                tc = ''
            desc_parts = []
            i += 1
            while i < len(lines) and lines[i].strip().startswith('*'):
                desc_parts.append(lines[i].strip()[2:])
                i += 1
            desc = ' | '.join(desc_parts)
            if clip_name not in markers_by_clip:
                markers_by_clip[clip_name] = []
            markers_by_clip[clip_name].append({
                'tc': tc, 'time': tc_to_seconds(tc) or 0,
                'cat': 1, 'desc': desc
            })
        else:
            i += 1
    return markers_by_clip

# ─── HTTP Handler ───

class DerushHandler(http.server.BaseHTTPRequestHandler):
    def _handle_ws_upgrade(self, qs):
        ws_key = self.headers.get('Sec-WebSocket-Key', '')
        if not ws_key: self.send_error(400); return
        token = qs.get('token', [''])[0]
        s = SESSIONS.get(token)
        if not s: self.send_error(403); return
        pid = s.get('project_id')
        self.send_response(101)
        self.send_header('Upgrade', 'websocket')
        self.send_header('Connection', 'Upgrade')
        self.send_header('Sec-WebSocket-Accept', _ws_accept(ws_key))
        self.end_headers()
        sock = self.connection
        entry = [sock, token]
        with _ws_clients_lock:
            _ws_clients.setdefault(pid, []).append(entry)
        try:
            while True:
                frame = _ws_recv(sock)
                if frame is None: break
                opcode, _ = frame
                if opcode == 8: break  # close
                if opcode == 9:  # ping → pong
                    try: sock.sendall(bytes([0x8A, 0]))
                    except Exception: break
        finally:
            with _ws_clients_lock:
                try: _ws_clients.get(pid, []).remove(entry)
                except Exception: pass
            self.close_connection = True

    def do_GET(self):
        try:
            self._dispatch_get()
        except Exception:
            self._handle_exception()

    def do_POST(self):
        # Verrou par projet : sérialise les écritures concurrentes sur un même
        # projet (audit 1.1). + capture des exceptions → 500 propre (audit 1.3).
        pid = _pid_from_path(self.path)
        try:
            if pid:
                with _project_lock(pid):
                    self._dispatch_post()
            else:
                self._dispatch_post()
        except Exception:
            self._handle_exception()

    def _handle_exception(self):
        import traceback
        sys.stderr.write(f"[derush] Exception non gérée — {self.command} {self.path}\n"
                         + traceback.format_exc() + "\n")
        try:
            self.send_response(500)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(json.dumps({'error': 'Erreur interne du serveur'}).encode('utf-8'))
        except Exception:
            pass  # réponse déjà (partiellement) envoyée — rien à faire

    def _dispatch_get(self):
        parsed = urlparse(self.path)
        path = parsed.path
        qs = parse_qs(parsed.query)

        if self.headers.get('Upgrade', '').lower() == 'websocket':
            self._handle_ws_upgrade(qs)
            return

        if path == '/' or path == '/index.html':
            if not IS_CONFIGURED:
                self.send_response(302)
                self.send_header('Location', '/setup')
                self.end_headers()
                return
            self._serve_file(BUNDLE_DIR / 'derush_app.html', 'text/html')
            return

        # Servir les modules JS externalisés (js/*.js) depuis le bundle
        if path.startswith('/js/') and path.endswith('.js'):
            # Sécurité : pas de traversée de chemin
            fname = path[4:]  # remove '/js/'
            if '..' in fname or '/' in fname or '\\' in fname:
                self.send_error(403); return
            f = BUNDLE_DIR / 'js' / fname
            if f.exists():
                self._serve_file(f, 'application/javascript')
            else:
                self.send_error(404)
            return

        if path == '/api/projects':
            s = get_session(self)  # optional auth
            self._json_response(list_projects())
            return

        if path == '/api/me':
            s = require_auth(self)
            if not s: return
            self._json_response(s)
            return

        if path == '/api/profile':
            profile = load_profile()
            if profile:
                self._json_response({'exists': True, 'username': profile['username']})
            else:
                self._json_response({'exists': False, 'username': None})
            return

        if path == '/api/my_projects':
            s = require_auth(self)
            if not s: return
            username = s.get('username', s.get('name', ''))
            result = []
            for pf in sorted(PROJECTS_DIR.glob('*.derush.json')):
                try:
                    pid = pf.stem.replace('.derush', '')
                    proj = load_project(pid)
                    if not proj: continue
                    u = find_project_user(proj, username)
                    if u and not u.get('invite_key'):  # has access (not just pending)
                        result.append({'id': pid, 'name': proj['name'], 'clip_count': len(proj.get('clips', []))})
                except Exception:
                    continue
            self._json_response(result)
            return

        if path == '/api/browse':
            # Folder picker natif. Sur Mac, tkinter doit tourner sur le main thread
            # (sinon hang silencieux) → on utilise osascript a la place. Sur Windows
            # et Linux, on garde tkinter en worker thread (deja eprouve sur Win).
            try:
                folder_path = ''
                if sys.platform == 'darwin':
                    # NSOpenPanel via AppleScript : pas de dep externe, dialog natif macOS
                    apple_script = 'POSIX path of (choose folder with prompt "Choisir le dossier des rushs")'
                    try:
                        r = subprocess.run(['osascript', '-e', apple_script],
                                           capture_output=True, text=True, timeout=120)
                        if r.returncode == 0:
                            folder_path = r.stdout.strip()
                        # returncode != 0 = utilisateur a annule (-128) → silencieux
                    except Exception:
                        folder_path = ''
                else:
                    import queue as _queue
                    q = _queue.Queue()
                    def _pick():
                        try:
                            import tkinter as tk
                            from tkinter import filedialog
                            root = tk.Tk()
                            root.withdraw()
                            root.lift()
                            root.attributes('-topmost', True)
                            result = filedialog.askdirectory(parent=root)
                            root.destroy()
                            q.put(result or '')
                        except Exception:
                            q.put('')
                    t = threading.Thread(target=_pick, daemon=True)
                    t.start()
                    t.join(timeout=120)
                    folder_path = q.get_nowait() if not q.empty() else ''
                # Normalize separators : on Mac on garde POSIX, sur Win on convertit en backslash
                if folder_path and sys.platform == 'win32':
                    folder_path = folder_path.replace('/', os.sep)
                self._json_response({'path': folder_path or ''})
            except Exception as e:
                self._json_response({'error': str(e)}, 500)
            return

        if re.match(r'^/api/project/([^/]+)/clips$', path):
            pid = re.match(r'^/api/project/([^/]+)/clips$', path).group(1)
            proj = load_project(pid)
            if proj:
                self._json_response(proj.get('clips', []))
            else:
                self.send_error(404)
            return

        if re.match(r'^/api/project/([^/]+)/config$', path):
            pid = re.match(r'^/api/project/([^/]+)/config$', path).group(1)
            proj = load_project(pid)
            if proj:
                # Strip sensitive fields from user records
                safe_users = []
                for u in proj.get('users', []):
                    safe_users.append({
                        'username': u.get('username') or u.get('name', ''),
                        'color': u.get('color', '#a78bfa'),
                        'is_admin': u.get('is_admin', False),
                        'root_path': u.get('root_path', ''),
                        'pending': bool(u.get('invite_key')),
                    })
                self._json_response({
                    'name': proj['name'], 'root_path': proj['root_path'],
                    'users': safe_users, 'clip_count': len(proj.get('clips', []))
                })
            else:
                self.send_error(404)
            return

        if re.match(r'^/api/project/([^/]+)/notes$', path):
            pid = re.match(r'^/api/project/([^/]+)/notes$', path).group(1)
            proj = load_project(pid)
            if proj:
                self._json_response(proj.get('notes', {}))
            else:
                self.send_error(404)
            return

        if re.match(r'^/api/project/([^/]+)/discussions$', path):
            pid = re.match(r'^/api/project/([^/]+)/discussions$', path).group(1)
            proj = load_project(pid)
            if proj:
                self._json_response(proj.get('discussions', {}))
            else:
                self.send_error(404)
            return

        if re.match(r'^/api/project/([^/]+)/export/(fcpxml|edl|markers_edl|csv|subclips_fcpxml|rough_cut|report_html|xml_fcp7)$', path):
            m = re.match(r'^/api/project/([^/]+)/export/(fcpxml|edl|markers_edl|csv|subclips_fcpxml|rough_cut|report_html|xml_fcp7)$', path)
            pid, fmt = m.group(1), m.group(2)
            proj = load_project(pid)
            if not proj:
                self.send_error(404)
                return
            # Build filter_config from query params
            filter_config = None
            min_r = qs.get('min_rating', [None])[0]
            cats_p = qs.get('cats', [None])[0]
            rejected_p = qs.get('rejected', [None])[0]
            if min_r or cats_p or rejected_p:
                filter_config = {}
                if min_r: filter_config['min_rating'] = min_r
                if cats_p: filter_config['cats'] = cats_p.split(',')
                if rejected_p: filter_config['rejected_only'] = True
            if fmt == 'fcpxml':
                label = qs.get('label', [proj['name']])[0]
                content = export_fcpxml(proj, filter_config)
                self._text_response(content, f"{label}_selects.fcpxml", 'application/xml')
            elif fmt == 'xml_fcp7':
                label = qs.get('label', [proj['name']])[0]
                content = export_xml_fcp7(proj, filter_config)
                self._text_response(content, f"{label}_selects_premiere.xml", 'application/xml')
            elif fmt == 'subclips_fcpxml':
                label = qs.get('label', [proj['name']])[0]
                pre = float(qs.get('pre', ['3'])[0])
                post = float(qs.get('post', ['7'])[0])
                content = export_subclips_fcpxml(proj, pre_roll=pre, post_roll=post, filter_config=filter_config)
                self._text_response(content, f"{label}_subclips.fcpxml", 'application/xml')
            elif fmt == 'rough_cut':
                label = qs.get('label', [proj['name']])[0]
                min_r = int(qs.get('min_rating', ['2'])[0])
                user_filter = qs.get('user_id', [''])[0] or None
                content = export_rough_cut_fcpxml(proj, min_rating=min_r, user_filter=user_filter)
                tag = f"r{min_r}" + (f"_{user_filter}" if user_filter else "")
                self._text_response(content, f"{label}_rough_cut_{tag}.fcpxml", 'application/xml')
            elif fmt == 'edl':
                content = export_edl(proj)
                self._text_response(content, f"{proj['name']}_markers.edl", 'text/plain')
            elif fmt == 'markers_edl':
                content = export_markers_edl(proj)
                self._text_response(content, f"{proj['name']}_timeline_markers.edl", 'text/plain')
            elif fmt == 'csv':
                content = export_csv(proj)
                self._text_response(content, f"{proj['name']}_markers.csv", 'text/csv')
            elif fmt == 'report_html':
                content = export_report_html(proj)
                self.send_response(200)
                self.send_header('Content-Type', 'text/html; charset=utf-8')
                self.end_headers()
                self.wfile.write(content.encode('utf-8'))
            return

        if re.match(r'^/api/project/([^/]+)/health$', path):
            pid = re.match(r'^/api/project/([^/]+)/health$', path).group(1)
            proj = load_project(pid)
            if proj:
                self._json_response(project_health(proj, pid))
            else:
                self.send_error(404)
            return

        if re.match(r'^/api/project/([^/]+)/stats$', path):
            pid = re.match(r'^/api/project/([^/]+)/stats$', path).group(1)
            proj = load_project(pid)
            if proj:
                self._json_response(project_stats(proj))
            else:
                self.send_error(404)
            return

        m = re.match(r'^/api/project/([^/]+)/multicam$', path)
        if m:
            pid = m.group(1)
            proj = load_project(pid)
            if not proj: self.send_error(404); return
            self._json_response({
                'proposals': proj.get('multicam_proposals', []),
                'groups': proj.get('multicam_groups', []),
            })
            return

        m = re.match(r'^/api/project/([^/]+)/multicam/status$', path)
        if m:
            pid = m.group(1)
            with _mc_jobs_lock:
                self._json_response(_mc_jobs.get(pid, {'status': 'idle'}))
            return

        m = re.match(r'^/api/project/([^/]+)/auto_detect/status$', path)
        if m:
            pid = m.group(1)
            with _auto_detect_jobs_lock:
                self._json_response(_auto_detect_jobs.get(pid, {'status': 'idle'}))
            return

        m = re.match(r'^/api/project/([^/]+)/auto_detect$', path)
        if m:
            pid = m.group(1)
            proj = load_project(pid)
            if not proj: self.send_error(404); return
            self._json_response({'auto_detected': proj.get('auto_detected', {})})
            return

        m = re.match(r'^/api/project/([^/]+)/session/state$', path)
        if m:
            pid = m.group(1)
            with _session_leaders_lock:
                leader = _session_leaders.get(pid)
            self._json_response({'leader': leader})
            return

        m = re.match(r'^/api/project/([^/]+)/decode_ltc/status$', path)
        if m:
            pid = m.group(1)
            with _ltc_jobs_lock:
                self._json_response(_ltc_jobs.get(pid, {'status': 'idle'}))
            return

        m = re.match(r'^/api/project/([^/]+)/decode_ltc/summary$', path)
        if m:
            pid = m.group(1)
            proj = load_project(pid)
            if not proj: self.send_error(404); return
            clips = proj.get('clips', [])
            n_total = len(clips)
            n_done = sum(1 for c in clips if 'ltc_tc_in_sec' in c)
            n_with = sum(1 for c in clips if c.get('ltc_tc_in_sec') is not None)
            self._json_response({
                'total': n_total, 'decoded': n_done,
                'with_ltc': n_with, 'without_ltc': n_done - n_with,
                'pending': n_total - n_done,
            })
            return

        m = re.match(r'^/api/project/([^/]+)/son$', path)
        if m:
            pid = m.group(1)
            proj = load_project(pid)
            if not proj: self.send_error(404); return
            audio_clips = proj.get('audio_clips', [])
            self._json_response({
                'son_dir': proj.get('son_dir', ''),
                'count': len(audio_clips),
                'audio_clips': audio_clips,
            })
            return

        if path == '/api/search':
            q = (qs.get('q', [''])[0] or '').strip()
            scope_pid = (qs.get('pid', [''])[0] or '').strip() or None
            if len(q) < 2:
                self._json_response({'results': [], 'query': q})
                return
            try:
                results = search_index(q, pid=scope_pid, limit=120)
            except sqlite3.OperationalError as e:
                # Malformed FTS query (e.g. unbalanced quotes) — return empty rather than 500
                self._json_response({'results': [], 'query': q, 'error': str(e)})
                return
            self._json_response({'results': results, 'query': q})
            return

        if path == '/api/sync/status':
            with _sync_lock:
                self._json_response(dict(_sync_status))
            return

        if path == '/api/crashes':
            try:
                limit = int(qs.get('limit', ['100'])[0])
            except (TypeError, ValueError):
                limit = 100
            self._json_response({'crashes': _read_crashes(limit)})
            return

        if path == '/api/version':
            self._json_response({'version': _read_version()})
            return

        if path == '/api/icon':
            icon = BUNDLE_DIR / 'derush_icon.png'
            if icon.exists():
                self._serve_file(icon, 'image/png')
            else:
                self.send_error(404)
            return

        if path == '/api/changelog':
            self._json_response(_read_changelog())
            return

        m = re.match(r'^/api/project/([^/]+)/share/info$', path)
        if m:
            pid = m.group(1)
            proj = load_project(pid)
            if not proj: self.send_error(404); return
            share = proj.get('share')
            if share and SYNC_URL:
                base = SYNC_URL.rstrip('/').rsplit('?', 1)[0]
                share = {**share, 'url': f"{base}?view=share&token={share['token']}"}
            self._json_response({'share': share, 'share_comments': proj.get('share_comments', {})})
            return

        if path == '/api/crashes/clear':
            try:
                CRASH_LOG.unlink(missing_ok=True)
            except Exception:
                pass
            self._json_response({'ok': True})
            return

        if path == '/api/sync/cloud_projects':
            if not SYNC_URL or not SYNC_KEY:
                self._json_response({'error': 'Sync cloud non configurée. Va dans ⚙️ Configuration.'}, 400)
                return
            list_url = f"{SYNC_URL.rstrip('/')}?key={_urlquote(SYNC_KEY, safe='')}&action=list"
            try:
                req = urllib.request.Request(list_url, headers=_sync_headers())
                with urllib.request.urlopen(req, timeout=10) as resp:
                    data = json.loads(resp.read().decode('utf-8'))
            except urllib.error.HTTPError as e:
                if e.code == 403:
                    self._json_response({'error': 'Clé sync incorrecte. Vérifie la valeur de SYNC_KEY dans ⚙️ Configuration (elle doit correspondre exactement à $SECRET_KEY dans derush_sync.php).'}, 403)
                else:
                    self._json_response({'error': f'Erreur serveur sync (HTTP {e.code})'}, 500)
                return
            except urllib.error.URLError as e:
                self._json_response({'error': f'Serveur sync injoignable : {e.reason}. Vérifie l\'URL dans ⚙️ Configuration.'}, 500)
                return
            except json.JSONDecodeError:
                self._json_response({'error': 'Réponse invalide du serveur sync (pas du JSON).'}, 500)
                return
            except Exception as e:
                self._json_response({'error': f'Erreur inattendue : {e}'}, 500)
                return
            local_pids = {f.stem.replace('.derush', '') for f in PROJECTS_DIR.glob('*.derush.json')}
            available = [p for p in data.get('projects', []) if p['id'] not in local_pids]
            self._json_response(available)
            return

        if path == '/api/setup/status':
            def _check(cmd):
                try:
                    r = subprocess.run([cmd, '-version'], capture_output=True, timeout=5, creationflags=_NO_WINDOW)
                    return r.returncode == 0
                except Exception:
                    return False
            self._json_response({
                'configured': IS_CONFIGURED,
                'ffmpeg_ok': _check(FFMPEG),
                'ffprobe_ok': _check(FFPROBE),
                'lan_ip': get_lan_ip(),
                'port': PORT,
                'projects_dir': str(PROJECTS_DIR),
                'waveforms_dir': str(WAVEFORMS_DIR),
                'thumbnails_dir': str(THUMBNAILS_DIR),
                'ffmpeg': FFMPEG,
                'ffprobe': FFPROBE,
                'sync_url': SYNC_URL,
                'sync_key': SYNC_KEY,
            })
            return

        if path == '/setup':
            setup_html = (BUNDLE_DIR / 'derush_setup.html')
            if setup_html.exists():
                self.send_response(200)
                self.send_header('Content-Type', 'text/html; charset=utf-8')
                self.end_headers()
                self.wfile.write(setup_html.read_bytes())
            else:
                self.send_response(302)
                self.send_header('Location', '/')
                self.end_headers()
            return

        m = re.match(r'^/api/project/([^/]+)/thumbnail/(.+)$', path)
        if m:
            pid, clip_id = m.group(1), m.group(2)
            t_param = qs.get('t', [None])[0]
            scrub_mode = False
            t_sec = 0.0
            if t_param is not None:
                try:
                    t_sec = float(t_param)
                    scrub_mode = True
                except (ValueError, TypeError):
                    pass
            thumb = THUMBNAILS_DIR / (f"{clip_id}_t{max(0,int(t_sec))}.jpg" if scrub_mode else f"{clip_id}.jpg")
            if not thumb.exists():
                proj = load_project(pid)
                if not proj: self.send_error(404); return
                clip = next((c for c in proj.get('clips', []) if c['id'] == clip_id), None)
                if not clip: self.send_error(404); return
                file_path = None
                if clip.get('proxy_url'):
                    rel = unquote(clip['proxy_url'][7:]).replace('\\', '/')
                    for u in proj.get('users', []):
                        rp = u.get('root_path') or proj.get('root_path', '')
                        if not rp: continue
                        resolved = _resolve_relpath_tolerant(rp, rel)
                        if resolved is not None: file_path = resolved; break
                if not file_path:
                    cp = Path(clip.get('path', ''))
                    if cp.exists(): file_path = cp
                    elif clip.get('rel_path'):
                        # Fallback : pareil pour le fichier source (cas ou y'a pas de proxy)
                        for u in proj.get('users', []):
                            rp = u.get('root_path') or proj.get('root_path', '')
                            if not rp: continue
                            resolved = _resolve_relpath_tolerant(rp, clip['rel_path'])
                            if resolved is not None: file_path = resolved; break
                if not file_path: self.send_error(404); return
                if scrub_mode:
                    compute_thumbnail_scrub(str(file_path), clip_id, t_sec)
                else:
                    offset = max(1.0, clip.get('duration_sec', 10) * 0.15)
                    compute_thumbnail(str(file_path), clip_id, offset)
                if not thumb.exists(): self.send_error(404); return
            self.send_response(200)
            self.send_header('Content-Type', 'image/jpeg')
            self.send_header('Cache-Control', 'public, max-age=86400')
            self.end_headers()
            self.wfile.write(thumb.read_bytes())
            return

        m = re.match(r'^/api/project/([^/]+)/strip/(.+)$', path)
        if m:
            pid, clip_id = m.group(1), m.group(2)
            n_frames = int(qs.get('n', ['12'])[0]) if qs.get('n') else 12
            strip = THUMBNAILS_DIR / f"{clip_id}_strip{n_frames}.jpg"
            if not strip.exists():
                proj = load_project(pid)
                if not proj: self.send_error(404); return
                clip = next((c for c in proj.get('clips', []) if c['id'] == clip_id), None)
                if not clip: self.send_error(404); return
                file_path = None
                if clip.get('proxy_url'):
                    rel = unquote(clip['proxy_url'][7:]).replace('\\', '/')
                    for u in proj.get('users', []):
                        rp = u.get('root_path') or proj.get('root_path', '')
                        if not rp: continue
                        resolved = _resolve_relpath_tolerant(rp, rel)
                        if resolved is not None: file_path = resolved; break
                if not file_path:
                    cp = Path(clip.get('path', ''))
                    if cp.exists(): file_path = cp
                    elif clip.get('rel_path'):
                        # Fallback : pareil pour le fichier source (cas ou y'a pas de proxy)
                        for u in proj.get('users', []):
                            rp = u.get('root_path') or proj.get('root_path', '')
                            if not rp: continue
                            resolved = _resolve_relpath_tolerant(rp, clip['rel_path'])
                            if resolved is not None: file_path = resolved; break
                if not file_path: self.send_error(404); return
                compute_strip(str(file_path), clip_id, clip.get('duration_sec', 10), n=n_frames)
                if not strip.exists(): self.send_error(404); return
            self.send_response(200)
            self.send_header('Content-Type', 'image/jpeg')
            self.send_header('Cache-Control', 'public, max-age=86400')
            self.end_headers()
            self.wfile.write(strip.read_bytes())
            return

        m = re.match(r'^/api/project/([^/]+)/waveform/(.+)$', path)
        if m:
            pid, clip_id = m.group(1), m.group(2)
            proj = load_project(pid)
            if not proj:
                self.send_error(404); return
            # Check cache
            cache_file = WAVEFORMS_DIR / f"{clip_id}.json"
            if cache_file.exists():
                self._json_response(json.loads(cache_file.read_text(encoding='utf-8')))
                return
            # Find clip file path
            clip = next((c for c in proj.get('clips', []) if c['id'] == clip_id), None)
            if not clip:
                self.send_error(404); return
            file_path = None
            # Try proxy path first
            if clip.get('proxy_url'):
                rel = unquote(clip['proxy_url'][7:]).replace('\\', '/')
                for u in proj.get('users', []):
                    rp = Path(u.get('root_path', proj.get('root_path', '')))
                    candidate = rp / rel
                    if candidate.exists():
                        file_path = candidate; break
            # Fall back to original clip path
            if not file_path:
                cp = Path(clip.get('path', ''))
                if cp.exists():
                    file_path = cp
            if not file_path:
                self._json_response({'peaks': [], 'cached': False}); return
            # FS5 proxies: L=LTC biphase (quasi-constant max amplitude), R=mic.
            # Extract only the right channel to avoid LTC contaminating the waveform.
            pan_filter = 'pan=mono|c0=c1' if clip.get('ltc_tc_in_sec') is not None else None
            peaks = compute_waveform_peaks(str(file_path), pan_filter=pan_filter)
            result = {'peaks': peaks, 'cached': False}
            try:
                cache_file.write_text(json.dumps(result), encoding='utf-8')
            except Exception:
                pass
            self._json_response(result)
            return

        if path.startswith('/proxy/'):
            rel = unquote(path[7:]).replace('\\', '/')
            # Use logged-in user's root_path if available, else try all projects
            s = get_session(self)
            roots_to_try = []
            if s and s.get('root_path'):
                roots_to_try.append(Path(s['root_path']))
            for pf in PROJECTS_DIR.glob('*.derush.json'):
                try:
                    pdata = json.loads(pf.read_text(encoding='utf-8'))
                    for u in pdata.get('users', []):
                        rp = Path(u.get('root_path', pdata.get('root_path', '')))
                        if rp not in roots_to_try:
                            roots_to_try.append(rp)
                except Exception: pass
            for root in roots_to_try:
                resolved = _resolve_relpath_tolerant(root, rel)
                if resolved is not None:
                    self._serve_video(resolved)
                    return
            self.send_error(404)
            return

        m = re.match(r'^/api/project/([^/]+)/invite_key/([^/]+)$', path)
        if m:
            pid, target_username = m.group(1), unquote(m.group(2))
            s = require_auth(self)
            if not s: return
            if not s.get('is_admin'):
                self._json_response({'error': 'Admin requis'}, 403)
                return
            proj = load_project(pid)
            if not proj:
                self.send_error(404); return
            user = find_project_user(proj, target_username)
            if not user:
                self._json_response({'error': 'Utilisateur introuvable'}, 404)
                return
            if not user.get('invite_key'):
                self._json_response({'error': 'Cet utilisateur a déjà rejoint le projet'}, 400)
                return
            self._json_response({'invite_key': user.get('invite_key', '')})
            return

        m = re.match(r'^/api/project/([^/]+)/bwf_audio/([^/]+)$', path)
        if m:
            pid, ac_id = m.group(1), m.group(2)
            proj = load_project(pid)
            if not proj: self.send_error(404); return
            ac = next((a for a in proj.get('audio_clips', []) if a.get('id') == ac_id), None)
            if not ac: self.send_error(404); return
            fp = _resolve_audio_clip_path(ac, proj)
            if not fp: self.send_error(404); return
            self._serve_audio(fp)
            return

        m = re.match(r'^/api/project/([^/]+)/clip_bwf/(.+)$', path)
        if m:
            pid, clip_id = m.group(1), m.group(2)
            proj = load_project(pid)
            if not proj: self._json_response({'ok': False}); return
            clip = next((c for c in proj.get('clips', []) if c['id'] == clip_id), None)
            if not clip: self._json_response({'ok': False}); return
            audio_clips = proj.get('audio_clips', [])
            if not audio_clips: self._json_response({'ok': False}); return
            tc_clip = _clip_tc_seconds(clip)
            if tc_clip is None: self._json_response({'ok': False}); return
            clip_map = {c['id']: c for c in proj.get('clips', [])}
            candidates = _bwf_candidates_for_clips(audio_clips, [clip_id], clip_map)
            if not candidates:
                self._json_response({'ok': False}); return
            chosen = candidates[0]
            self._json_response({
                'ok': True,
                'stream_url': f'/api/project/{pid}/bwf_audio/{chosen["id"]}',
                'filename': chosen['filename'],
                'tc_in_sec': chosen['tc_in_sec'],
                'bwf_offset_sec': round(tc_clip - chosen['tc_in_sec'], 3),
            })
            return

        m = re.match(r'^/api/project/([^/]+)/multicam/group_bwf$', path)
        if m:
            pid = m.group(1)
            gid = (qs.get('group_id') or [''])[0]
            proj = load_project(pid)
            if not proj: self._json_response({'ok': False}); return
            all_grps = proj.get('multicam_proposals', []) + proj.get('multicam_groups', [])
            grp = next((g for g in all_grps if g['id'] == gid), None)
            if not grp: self._json_response({'ok': False}); return
            clip_ids = grp.get('clip_ids', [])
            clip_map = {c['id']: c for c in proj.get('clips', [])}
            audio_clips = proj.get('audio_clips', [])
            offsets = grp.get('offsets', {})
            if not clip_ids or not audio_clips:
                self._json_response({'ok': False}); return
            earliest_id = min(offsets.keys(), key=lambda k: offsets[k]) if offsets else clip_ids[0]
            earliest_clip = clip_map.get(earliest_id)
            if not earliest_clip: self._json_response({'ok': False}); return
            tc_earliest = _clip_tc_seconds(earliest_clip)
            if tc_earliest is None: self._json_response({'ok': False}); return
            candidates = _bwf_candidates_for_clips(audio_clips, clip_ids, clip_map)
            if not candidates:
                self._json_response({'ok': False}); return
            chosen_af = candidates[0]
            self._json_response({
                'ok': True,
                'stream_url': f'/api/project/{pid}/bwf_audio/{chosen_af["id"]}',
                'filename': chosen_af['filename'],
                'tc_in_sec': chosen_af['tc_in_sec'],
                'bwf_offset_sec': round(tc_earliest - chosen_af['tc_in_sec'], 3),
                'earliest_id': earliest_id,
            })
            return

        self.send_error(404)

    def _dispatch_post(self):
        global CONFIG, IS_CONFIGURED, PROJECTS_DIR, WAVEFORMS_DIR, THUMBNAILS_DIR, BACKUPS_DIR, PORT, FFMPEG, FFPROBE, SYNC_URL, SYNC_KEY
        parsed = urlparse(self.path)
        path = parsed.path
        body = self._read_body()

        if path == '/api/profile/create':
            username = body.get('username', '').strip()
            password = body.get('password', '')
            if not username or len(password) < 4:
                self._json_response({'error': 'Identifiant requis et mot de passe min. 4 caractères'}, 400)
                return
            if load_profile():
                self._json_response({'error': 'Un profil existe déjà sur cet appareil'}, 409)
                return
            save_profile({'username': username, 'password_hash': hash_password(password)})
            self._json_response({'ok': True, 'username': username})
            return

        if path == '/api/login':
            username = body.get('username', '').strip()
            password = body.get('password', '')
            if not username:
                self._json_response({'error': 'Identifiant requis'}, 400)
                return
            _ip = self.client_address[0]
            if _login_throttled(_ip):
                self._json_response({'error': 'Trop de tentatives de connexion. Réessaie dans quelques minutes.'}, 429)
                return
            profile = load_profile()
            if not profile:
                self._json_response({'error': 'Aucun profil créé sur cet appareil. Relancez la configuration.'}, 403)
                return
            profile_ok = (profile['username'].lower() == username.lower()
                          and verify_password(password, profile.get('password_hash', '')))
            if profile_ok and is_legacy_hash(profile.get('password_hash', '')):
                # Migration transparente : re-hache en PBKDF2 au login réussi.
                profile['password_hash'] = hash_password(password)
                save_profile(profile)
            if not profile_ok:
                # Fallback: old-style project-based auth (backward compat)
                matched_pid = matched_user = matched_proj = None
                for pf in sorted(PROJECTS_DIR.glob('*.derush.json')):
                    pid = pf.stem.replace('.derush', '')
                    try:
                        proj = load_project(pid)
                        if not proj: continue
                        u = find_project_user(proj, username)
                        if u and verify_password(password, u.get('password_hash', '')):
                            matched_pid, matched_user, matched_proj = pid, u, proj
                            break
                    except Exception:
                        continue
                if not matched_user:
                    _login_record_fail(_ip)
                    self._json_response({'error': 'Identifiants incorrects'}, 401)
                    return
                # Migrate: create profile from old admin user
                if not load_profile():
                    save_profile({'username': matched_user.get('name', username), 'password_hash': hash_password(password)})
                profile = load_profile()
            _login_clear(_ip)
            token = secrets.token_hex(32)
            SESSIONS[token] = {
                'username': profile['username'],
                'name': profile['username'],
                'user_id': profile['username'],
                'color': '#a78bfa',
                'root_path': '',
                'project_id': None,
                'is_admin': False,
            }
            self._json_response({'token': token, 'user': SESSIONS[token]})
            return

        if path == '/api/logout':
            auth = self.headers.get('Authorization', '')
            if auth.startswith('Bearer '):
                tok = auth[7:]
                sess = SESSIONS.pop(tok, None)
                # Si l'utilisateur dirigeait une session, libère le leader status
                if sess:
                    uname = sess.get('username', '') or sess.get('user_id', '')
                    with _session_leaders_lock:
                        for pid, leader in list(_session_leaders.items()):
                            if leader == uname:
                                _session_leaders.pop(pid, None)
                                _ws_broadcast(pid, {'type': 'session_state', 'leader': None})
            self._json_response({'ok': True})
            return

        if path == '/api/heartbeat':
            global _last_heartbeat
            _last_heartbeat = _time.time()
            self._json_response({'ok': True})
            return

        m = re.match(r'^/api/project/([^/]+)/share/(create|revoke|pull_comments)$', path)
        if m:
            pid, action = m.group(1), m.group(2)
            s = require_auth(self)
            if not s: return
            if action == 'create':
                res = create_share(pid)
                self._json_response(res, 200 if res.get('ok') else 400)
            elif action == 'revoke':
                res = revoke_share(pid)
                self._json_response(res, 200 if res.get('ok') else 400)
            elif action == 'pull_comments':
                res = pull_share_comments(pid)
                self._json_response(res, 200 if res.get('ok') else 400)
            return

        if path == '/api/crash':
            # Frontend errors (window.onerror, unhandledrejection, etc.)
            try:
                body = json.loads(self.rfile.read(int(self.headers.get('Content-Length', 0))) or b'{}')
            except Exception:
                body = {}
            entry = {
                'source': 'js',
                'type': str(body.get('type', 'Error'))[:80],
                'message': str(body.get('message', ''))[:2000],
                'stack': str(body.get('stack', ''))[:6000],
                'url': str(body.get('url', ''))[:500],
                'line': body.get('line'),
                'col': body.get('col'),
                'user_agent': self.headers.get('User-Agent', '')[:300],
            }
            _log_crash(entry)
            self._json_response({'ok': True})
            return

        if path == '/api/shutdown':
            self._json_response({'ok': True})
            def _kill():
                _time.sleep(0.3)
                os._exit(0)
            threading.Thread(target=_kill, daemon=True).start()
            return

        if path == '/api/project/open':
            s = require_auth(self)
            if not s: return
            name = body.get('name', 'Nouveau Projet')
            root_path = body.get('root_path', '')
            color = body.get('color', '#a78bfa')
            if not root_path or not Path(root_path).is_dir():
                self._json_response({'error': 'Chemin invalide'}, 400)
                return
            pid, data = create_project(name, root_path, s['username'], color)
            # Update session with project context
            SESSIONS[self.headers.get('Authorization', '')[7:]] = {
                **s, 'project_id': pid, 'is_admin': True,
                'color': color, 'root_path': root_path,
            }
            # Sync to cloud in background
            threading.Thread(target=sync_project, args=(pid,), daemon=True).start()
            self._json_response({'id': pid, 'name': data['name'], 'clip_count': len(data['clips'])})
            return

        if re.match(r'^/api/project/([^/]+)/authorize_user$', path):
            pid = re.match(r'^/api/project/([^/]+)/authorize_user$', path).group(1)
            s = require_auth(self)
            if not s: return
            if not s.get('is_admin'):
                self._json_response({'error': 'Admin requis'}, 403)
                return
            proj = load_project(pid)
            if not proj:
                self.send_error(404); return
            target_username = body.get('username', '').strip()
            if not target_username:
                self._json_response({'error': 'Identifiant requis'}, 400)
                return
            existing = find_project_user(proj, target_username)
            if existing and not existing.get('invite_key'):
                self._json_response({'error': f'{target_username} a déjà accès à ce projet'}, 400)
                return
            import string as _string
            invite_key = ''.join(secrets.choice(_string.ascii_uppercase + _string.digits) for _ in range(8))
            role = body.get('role', 'annotator')  # admin | annotator | viewer
            is_admin = role == 'admin' or body.get('is_admin', False)
            if existing:
                existing['invite_key'] = invite_key
                existing['color'] = body.get('color', existing.get('color', '#60a5fa'))
                existing['is_admin'] = is_admin
                existing['role'] = role
            else:
                proj.setdefault('users', []).append({
                    'username': target_username,
                    'color': body.get('color', '#60a5fa'),
                    'is_admin': is_admin,
                    'role': role,
                    'root_path': '',
                    'invite_key': invite_key,
                })
            # IMPORTANT : si l'user était dans la tombstone (re-création après suppression),
            # on le retire — sinon merge_projects le re-filtrera au prochain sync.
            tomb = [t for t in proj.get('deleted_users', []) if t.lower() != target_username.lower()]
            proj['deleted_users'] = tomb
            save_project(pid, proj)
            threading.Thread(target=sync_project, args=(pid,), daemon=True).start()
            self._json_response({'ok': True, 'invite_key': invite_key, 'username': target_username})
            return

        if re.match(r'^/api/project/([^/]+)/edit_user$', path):
            pid = re.match(r'^/api/project/([^/]+)/edit_user$', path).group(1)
            s = require_auth(self)
            if not s: return
            if not s.get('is_admin'):
                self._json_response({'error': 'Admin requis'}, 403)
                return
            proj = load_project(pid)
            if not proj:
                self.send_error(404); return
            target_username = body.get('username', '').strip()
            user = find_project_user(proj, target_username)
            if not user:
                self._json_response({'error': 'Utilisateur introuvable'}, 404)
                return
            if 'color' in body: user['color'] = body['color']
            if 'is_admin' in body: user['is_admin'] = body['is_admin']
            if 'role' in body:
                user['role'] = body['role']
                user['is_admin'] = body['role'] == 'admin'  # garde la cohérence avec is_admin
            if body.get('reset_key'):
                import string as _string
                user['invite_key'] = ''.join(secrets.choice(_string.ascii_uppercase + _string.digits) for _ in range(8))
            save_project(pid, proj)
            new_key = user.get('invite_key') if body.get('reset_key') else None
            self._json_response({'ok': True, 'invite_key': new_key})
            return

        if re.match(r'^/api/project/([^/]+)/delete_user$', path):
            pid = re.match(r'^/api/project/([^/]+)/delete_user$', path).group(1)
            s = require_auth(self)
            if not s: return
            if not s.get('is_admin'):
                self._json_response({'error': 'Admin requis'}, 403)
                return
            target_username = body.get('username', '').strip()
            if target_username.lower() == s.get('username', '').lower():
                self._json_response({'error': 'Impossible de se supprimer soi-même'}, 400)
                return
            proj = load_project(pid)
            if not proj:
                self.send_error(404); return
            before = len(proj.get('users', []))
            proj['users'] = [u for u in proj.get('users', [])
                             if (u.get('username') or u.get('name', '')).lower() != target_username.lower()]
            if len(proj['users']) == before:
                self._json_response({'error': 'Utilisateur introuvable'}, 404)
                return
            # Tombstone : marque cet user comme supprimé pour que merge_projects ne
            # le re-pompe pas depuis le cloud (qui peut encore l'avoir).
            tombstones = set(proj.get('deleted_users', []))
            tombstones.add(target_username.lower())
            proj['deleted_users'] = sorted(tombstones)
            save_project(pid, proj)
            # Push immédiat pour propager la suppression au cloud
            _schedule_sync_push(pid, delay=0.5)
            self._json_response({'ok': True})
            return

        if re.match(r'^/api/project/([^/]+)/set_root_path$', path):
            pid = re.match(r'^/api/project/([^/]+)/set_root_path$', path).group(1)
            s = require_auth(self)
            if not s: return
            root_path = body.get('root_path', '').strip()
            proj = load_project(pid)
            if not proj:
                self.send_error(404); return
            user = find_project_user(proj, s['username'])
            if not user:
                # Diagnostic : on dit explicitement pourquoi
                in_tomb = s['username'].lower() in [t.lower() for t in proj.get('deleted_users', [])]
                user_list = [u.get('username') or u.get('name', '') for u in proj.get('users', [])]
                msg = f"L'utilisateur '{s['username']}' n'est pas inscrit sur ce projet."
                if in_tomb:
                    msg += " (Il a été supprimé du projet — demande à l'admin de te réinviter.)"
                else:
                    msg += f" Users actuels : {', '.join(user_list) if user_list else '(aucun)'}."
                self._json_response({'error': msg}, 403); return
            user['root_path'] = root_path
            save_project(pid, proj)
            auth = self.headers.get('Authorization', '')[7:]
            if auth in SESSIONS:
                SESSIONS[auth]['root_path'] = root_path
            self._json_response({'ok': True})
            return

        if re.match(r'^/api/project/([^/]+)/scan$', path):
            pid = re.match(r'^/api/project/([^/]+)/scan$', path).group(1)
            s = require_auth(self)
            if not s: return
            proj = load_project(pid)
            if not proj:
                self.send_error(404)
                return
            # Use authenticated user's root_path if set, else project default
            scan_root = s.get('root_path') or proj.get('root_path', '')
            proj['clips'] = scan_media_folder(scan_root,
                [e.lower() for e in proj.get('media_extensions', ['.mxf', '.mp4', '.mov'])])
            save_project(pid, proj)
            self._json_response({'clip_count': len(proj['clips']), 'clips': proj['clips']})
            return

        if re.match(r'^/api/project/([^/]+)/notes$', path):
            pid = re.match(r'^/api/project/([^/]+)/notes$', path).group(1)
            s = require_auth(self)
            if not s: return
            proj = load_project(pid)
            if not proj:
                self.send_error(404)
                return
            # Résout la clé de notes via le user du projet — donc identique à ce
            # que user_note_key() et l'export utilisent. Sauver via la session brute
            # (`user_id or username`) dédoublait les notes d'un même humain sous 2
            # clés (ex. `6714b070` vs `Sebastien`) → notes invisibles à l'export.
            _pu = find_project_user(proj, s.get('username') or s.get('name') or s.get('user_id') or '')
            user_key = user_note_key(_pu) if _pu else (s.get('user_id') or s.get('username', ''))
            notes = body.get('notes', {})
            if not proj.get('notes'):
                proj['notes'] = {}
            proj['notes'][user_key] = notes
            save_project(pid, proj)
            _ws_broadcast(pid, {'type': 'notes_updated', 'user': user_key},
                          exclude_token=self.headers.get('Authorization', '')[7:])
            # Push cloud debounced : ~3s après la dernière save, un sync part en bg.
            _schedule_sync_push(pid)
            self._json_response({'ok': True})
            return

        if re.match(r'^/api/project/([^/]+)/config$', path):
            pid = re.match(r'^/api/project/([^/]+)/config$', path).group(1)
            proj = load_project(pid)
            if not proj:
                self.send_error(404)
                return
            if 'users' in body: proj['users'] = body['users']
            if 'name' in body: proj['name'] = body['name']
            if 'media_extensions' in body: proj['media_extensions'] = body['media_extensions']
            save_project(pid, proj)
            self._json_response({'ok': True})
            return

        if re.match(r'^/api/project/([^/]+)/reply$', path):
            pid = re.match(r'^/api/project/([^/]+)/reply$', path).group(1)
            s = require_auth(self)
            if not s: return
            proj = load_project(pid)
            if not proj: self.send_error(404); return
            clip_id = body.get('clip_id', '')
            marker_id = body.get('marker_id', '')
            text = (body.get('text') or '').strip()
            if not clip_id or not marker_id or not text:
                self.send_error(400); return
            suid = s.get('user_id') or s.get('username', '')
            user = find_project_user(proj, s.get('username', suid)) or {}
            if 'discussions' not in proj: proj['discussions'] = {}
            if clip_id not in proj['discussions']: proj['discussions'][clip_id] = {}
            if marker_id not in proj['discussions'][clip_id]: proj['discussions'][clip_id][marker_id] = []
            proj['discussions'][clip_id][marker_id].append({
                'user_id': suid,
                'user_name': user.get('username') or user.get('name', s.get('name', '?')),
                'color': user.get('color', '#888'),
                'text': text,
                'ts': datetime.utcnow().isoformat()
            })
            save_project(pid, proj)
            _ws_broadcast(pid, {'type': 'discussion_updated', 'clip_id': clip_id, 'marker_id': marker_id},
                          exclude_token=self.headers.get('Authorization', '')[7:])
            self._json_response({'ok': True})
            return

        if re.match(r'^/api/project/([^/]+)/import$', path):
            pid = re.match(r'^/api/project/([^/]+)/import$', path).group(1)
            proj = load_project(pid)
            if not proj:
                self.send_error(404)
                return
            fmt = body.get('format', 'edl')
            content = body.get('content', '')
            user_id = body.get('user', 'import')
            if fmt == 'edl':
                markers = import_edl(content, user_id)
                if not proj.get('notes'): proj['notes'] = {}
                if not proj['notes'].get(user_id): proj['notes'][user_id] = {}
                for clip_name, mlist in markers.items():
                    for clip in proj['clips']:
                        if clip_name.strip() in clip.get('stem', ''):
                            cid = clip['id']
                            if cid not in proj['notes'][user_id]:
                                proj['notes'][user_id][cid] = {}
                            if 'markers' not in proj['notes'][user_id][cid]:
                                proj['notes'][user_id][cid]['markers'] = []
                            proj['notes'][user_id][cid]['markers'].extend(mlist)
                save_project(pid, proj)
            self._json_response({'ok': True})
            return

        if path == '/api/sync/join_with_key':
            # Download project + validate invite_key against local profile username
            s = require_auth(self)
            if not s: return
            pid = body.get('project_id', '').strip()
            invite_key = body.get('invite_key', '').strip().upper()
            if not pid or not invite_key:
                self._json_response({'error': 'ID de projet et clé d\'invitation requis'}, 400)
                return
            # Validation pid : doit matcher ce que la PHP accepte (a-zA-Z0-9_-).
            # Sans ça, espaces et accents font soit crasher urllib, soit silently miss.
            if not re.match(r'^[a-zA-Z0-9_\-]+$', pid):
                self._json_response({'error': 'ID de projet invalide. Utilisez uniquement lettres, chiffres, tirets et underscores (pas d\'espaces ni d\'accents).'}, 400)
                return
            if not SYNC_URL or not SYNC_KEY:
                self._json_response({'error': 'Sync cloud non configurée. Va dans ⚙️ Configuration pour définir l\'URL et la clé sync.'}, 400)
                return
            url = _sync_url_for(pid)
            try:
                req = urllib.request.Request(url, headers=_sync_headers())
                with urllib.request.urlopen(req, timeout=15) as resp:
                    project_data = json.loads(resp.read().decode('utf-8'))
            except urllib.error.HTTPError as e:
                if e.code == 404:
                    self._json_response({'error': f'Aucun projet "{pid}" trouvé sur le serveur sync. Vérifie l\'ID exact (admin → ⚙️ → Configuration).'}, 404)
                elif e.code == 403:
                    self._json_response({'error': 'Clé sync incorrecte. Vérifie la valeur de SYNC_KEY dans ⚙️ Configuration (elle doit correspondre exactement à $SECRET_KEY dans derush_sync.php).'}, 403)
                else:
                    self._json_response({'error': f'Erreur serveur sync (HTTP {e.code})'}, 500)
                return
            except urllib.error.URLError as e:
                self._json_response({'error': f'Serveur sync injoignable : {e.reason}. Vérifie l\'URL dans ⚙️ Configuration et ta connexion internet.'}, 500)
                return
            except json.JSONDecodeError:
                self._json_response({'error': 'Réponse du serveur sync invalide (pas du JSON). derush_sync.php est-il bien à jour et accessible ?'}, 500)
                return
            except Exception as e:
                self._json_response({'error': f'Erreur inattendue : {e}'}, 500)
                return
            username = s['username']
            user_entry = find_project_user(project_data, username)
            if not user_entry:
                self._json_response({'error': f'Aucun accès autorisé pour "{username}" sur ce projet. Demandez à l\'admin de vous autoriser.'}, 403)
                return
            if user_entry.get('invite_key', '').upper() != invite_key:
                self._json_response({'error': 'Clé d\'invitation incorrecte'}, 403)
                return
            # Key validated — remove it and save project locally
            user_entry.pop('invite_key', None)
            save_project(pid, project_data)
            # Push updated project back to cloud
            threading.Thread(target=sync_project, args=(pid,), daemon=True).start()
            self._json_response({'ok': True, 'project_id': pid, 'name': project_data.get('name', pid)})
            return

        if path == '/api/project/enter':
            # Enter a project workspace — loads project-specific session info
            s = require_auth(self)
            if not s: return
            pid = body.get('project_id', '').strip()
            # Pull immédiat depuis le cloud avant d'entrer (background, non bloquant).
            # Le polling notes 60s + WebSocket attrapent la fraîcheur si pas encore arrivée
            # quand l'UI charge.
            threading.Thread(target=sync_project, args=(pid,), daemon=True).start()
            proj = load_project(pid)
            if not proj:
                self._json_response({'error': 'Projet introuvable'}, 404); return
            user = find_project_user(proj, s['username'])
            if not user or user.get('invite_key'):
                self._json_response({'error': 'Accès refusé. Utilisez votre clé d\'invitation pour rejoindre ce projet.'}, 403)
                return
            auth_token = self.headers.get('Authorization', '')[7:]
            is_admin = user.get('is_admin', False)
            role = user.get('role', 'admin' if is_admin else 'annotator')
            SESSIONS[auth_token] = {
                **s,
                'project_id': pid,
                'color': user.get('color', '#a78bfa'),
                'is_admin': is_admin,
                'role': role,
                'root_path': user.get('root_path', proj.get('root_path', '')),
            }
            self._json_response({'ok': True, 'user': SESSIONS[auth_token]})
            return

        m = re.match(r'^/api/project/([^/]+)/multicam/detect$', path)
        if m:
            pid = m.group(1)
            s = require_auth(self)
            if not s: return
            with _mc_jobs_lock:
                cur = _mc_jobs.get(pid, {})
                if cur.get('status') == 'running':
                    self._json_response({'ok': False, 'error': 'Détection déjà en cours'}, 409)
                    return
            # _detect_multicam_job initialises _mc_jobs[pid] itself on entry
            threading.Thread(target=_detect_multicam_job, args=(pid,), daemon=True).start()
            self._json_response({'ok': True, 'status': 'running'})
            return

        m = re.match(r'^/api/project/([^/]+)/session/(start_leading|stop_leading|action)$', path)
        if m:
            pid, kind = m.group(1), m.group(2)
            s = require_auth(self)
            if not s: return
            user = s.get('username', '') or s.get('user_id', '')
            if kind == 'start_leading':
                with _session_leaders_lock:
                    _session_leaders[pid] = user
                _ws_broadcast(pid, {'type': 'session_state', 'leader': user})
                self._json_response({'ok': True, 'leader': user})
                return
            if kind == 'stop_leading':
                with _session_leaders_lock:
                    if _session_leaders.get(pid) == user:
                        _session_leaders.pop(pid, None)
                _ws_broadcast(pid, {'type': 'session_state', 'leader': None})
                self._json_response({'ok': True})
                return
            if kind == 'action':
                with _session_leaders_lock:
                    cur = _session_leaders.get(pid)
                if cur != user:
                    self._json_response({'ok': False, 'error': 'Pas leader'}, 403); return
                action = body.get('action', '')
                data = body.get('data', {})
                # Broadcast à tous les clients du projet (y compris l'expéditeur — son client
                # ignore les actions venant de lui-même)
                _ws_broadcast(pid, {'type': 'session_action', 'action': action, 'data': data, 'from': user})
                self._json_response({'ok': True})
                return
            return

        m = re.match(r'^/api/project/([^/]+)/auto_detect/(start|decide)$', path)
        if m:
            pid, action = m.group(1), m.group(2)
            s = require_auth(self)
            if not s: return
            if action == 'start':
                threshold = float(body.get('threshold', 0.4))
                threshold = max(0.05, min(0.95, threshold))
                clip_ids = body.get('clip_ids')  # None = tous les clips
                with _auto_detect_jobs_lock:
                    cur = _auto_detect_jobs.get(pid, {})
                    if cur.get('status') == 'running':
                        self._json_response({'ok': False, 'error': 'Détection déjà en cours'}, 409)
                        return
                threading.Thread(target=_auto_detect_job, args=(pid, threshold, clip_ids), daemon=True).start()
                self._json_response({'ok': True, 'status': 'running'})
                return
            elif action == 'decide':
                # body: {clip_id, candidate_id, status: 'accepted'|'rejected'}
                clip_id = body.get('clip_id', '')
                cand_id = body.get('candidate_id', '')
                new_status = body.get('status', 'pending')
                if new_status not in ('accepted', 'rejected', 'pending'):
                    self._json_response({'ok': False, 'error': 'status invalide'}, 400); return
                proj = load_project(pid)
                if not proj:
                    self._json_response({'ok': False}, 404); return
                ad = proj.setdefault('auto_detected', {})
                clip_data = ad.get(clip_id)
                if not clip_data:
                    self._json_response({'ok': False, 'error': 'Clip non scanné'}, 404); return
                cand = next((c for c in clip_data['candidates'] if c.get('id') == cand_id), None)
                if not cand:
                    self._json_response({'ok': False, 'error': 'Candidat introuvable'}, 404); return
                cand['status'] = new_status
                # Si accepté : crée un vrai marker D dans les notes de l'utilisateur
                if new_status == 'accepted':
                    user_key = s.get('user_id') or s.get('username', '')
                    proj.setdefault('notes', {}).setdefault(user_key, {}).setdefault(clip_id, {}).setdefault('markers', [])
                    markers = proj['notes'][user_key][clip_id]['markers']
                    # Trouve fps + clip pour calculer le TC
                    clip = next((c for c in proj.get('clips', []) if c['id'] == clip_id), None)
                    fps = (clip or {}).get('fps', 25) or 25
                    t = cand.get('time', 0)
                    tc = seconds_to_tc(t, fps)
                    markers.append({
                        'id': secrets.token_hex(4),
                        'tc': tc,
                        'time': t,
                        'cat': 'D',
                        'desc': '[Auto] Plan détecté',
                    })
                    markers.sort(key=lambda m: m.get('time', 0))
                save_project(pid, proj)
                self._json_response({'ok': True})
                return
            return

        m = re.match(r'^/api/project/([^/]+)/decode_ltc/start$', path)
        if m:
            pid = m.group(1)
            s = require_auth(self)
            if not s: return
            force = bool(body.get('force', False))
            with _ltc_jobs_lock:
                cur = _ltc_jobs.get(pid, {})
                if cur.get('status') == 'running':
                    self._json_response({'ok': False, 'error': 'Décodage LTC déjà en cours'}, 409)
                    return
            threading.Thread(target=_decode_ltc_job, args=(pid, force), daemon=True).start()
            self._json_response({'ok': True, 'status': 'running'})
            return

        m = re.match(r'^/api/project/([^/]+)/multicam/accept$', path)
        if m:
            pid = m.group(1)
            s = require_auth(self)
            if not s: return
            gid = body.get('group_id', '')
            proj = load_project(pid)
            if not proj: self.send_error(404); return
            proposals = proj.get('multicam_proposals', [])
            grp = next((g for g in proposals if g['id'] == gid), None)
            if not grp:
                self._json_response({'ok': False, 'error': 'Groupe introuvable'}, 404)
                return
            proj['multicam_groups'] = proj.get('multicam_groups', []) + [grp]
            proj['multicam_proposals'] = [g for g in proposals if g['id'] != gid]
            save_project(pid, proj)
            self._json_response({'ok': True})
            return

        m = re.match(r'^/api/project/([^/]+)/multicam/reject$', path)
        if m:
            pid = m.group(1)
            s = require_auth(self)
            if not s: return
            gid = body.get('group_id', '')
            proj = load_project(pid)
            if not proj: self.send_error(404); return
            # Remove from both lists (user can reject either an unresolved proposal or an accepted group)
            proj['multicam_proposals'] = [g for g in proj.get('multicam_proposals', []) if g['id'] != gid]
            proj['multicam_groups']    = [g for g in proj.get('multicam_groups', [])    if g['id'] != gid]
            save_project(pid, proj)
            self._json_response({'ok': True})
            return

        m = re.match(r'^/api/project/([^/]+)/multicam/nudge$', path)
        if m:
            pid = m.group(1)
            s = require_auth(self)
            if not s: return
            gid = body.get('group_id', '')
            new_offsets = body.get('offsets', {})
            if not gid or not new_offsets:
                self._json_response({'ok': False, 'error': 'group_id et offsets requis'}, 400)
                return
            proj = load_project(pid)
            if not proj: self.send_error(404); return
            grp = next((g for g in proj.get('multicam_groups', []) if g['id'] == gid), None)
            if not grp:
                self._json_response({'ok': False, 'error': 'Groupe introuvable'}, 404)
                return
            grp['offsets'] = new_offsets
            save_project(pid, proj)
            self._json_response({'ok': True})
            return

        m = re.match(r'^/api/project/([^/]+)/scan_son$', path)
        if m:
            pid = m.group(1)
            s = require_auth(self)
            if not s: return
            son_dir = (body.get('son_dir', '') or '').strip()
            if not son_dir:
                self._json_response({'ok': False, 'error': 'son_dir requis'}, 400); return
            proj = load_project(pid)
            if not proj: self.send_error(404); return
            try:
                audio_clips = scan_son_dir(son_dir)
            except Exception as e:
                self._json_response({'ok': False, 'error': str(e)}, 500); return
            proj['son_dir'] = son_dir
            proj['audio_clips'] = audio_clips
            save_project(pid, proj)
            self._json_response({'ok': True, 'count': len(audio_clips), 'audio_clips': audio_clips})
            return

        if path == '/api/sync/now':
            results = sync_all_projects()
            all_ok  = all(v['ok'] for v in results.values())
            msgs    = [f"{pid}: {v['message']}" for pid, v in results.items()]
            self._json_response({'ok': all_ok, 'results': results, 'message': ' | '.join(msgs)})
            return

        if path == '/api/setup':
            projects_dir = body.get('projects_dir', str(APP_DIR / 'projects'))
            waveforms_dir = body.get('waveforms_dir', str(APP_DIR / 'waveforms'))
            thumbnails_dir = body.get('thumbnails_dir', str(APP_DIR / 'thumbnails'))
            ffmpeg = body.get('ffmpeg', 'ffmpeg')
            ffprobe = body.get('ffprobe', 'ffprobe')
            port = int(body.get('port', 8765))
            # Validate dirs exist or can be created
            try:
                Path(projects_dir).mkdir(exist_ok=True, parents=True)
                Path(waveforms_dir).mkdir(exist_ok=True, parents=True)
                Path(thumbnails_dir).mkdir(exist_ok=True, parents=True)
                Path(projects_dir, 'backups').mkdir(exist_ok=True, parents=True)
            except Exception as e:
                self._json_response({'error': str(e)}, 400)
                return
            new_config = {
                'configured': True,
                'projects_dir': projects_dir,
                'waveforms_dir': waveforms_dir,
                'thumbnails_dir': thumbnails_dir,
                'backups_dir': str(Path(projects_dir) / 'backups'),
                'ffmpeg': ffmpeg,
                'ffprobe': ffprobe,
                'port': port,
            }
            save_config(new_config)
            # Apply config live
            CONFIG = new_config
            IS_CONFIGURED = True
            PROJECTS_DIR = Path(projects_dir)
            WAVEFORMS_DIR = Path(waveforms_dir)
            THUMBNAILS_DIR = Path(thumbnails_dir)
            BACKUPS_DIR = Path(projects_dir) / 'backups'
            PORT = port
            FFMPEG = ffmpeg
            FFPROBE = ffprobe
            self._json_response({'ok': True, 'lan_ip': get_lan_ip(), 'port': port})
            return

        self.send_error(404)

    def _read_body(self):
        length = int(self.headers.get('Content-Length', 0))
        if length:
            return json.loads(self.rfile.read(length))
        return {}

    def _json_response(self, data, code=200):
        self.send_response(code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode('utf-8'))

    def _text_response(self, content, filename, mime):
        self.send_response(200)
        self.send_header('Content-Type', f'{mime}; charset=utf-8')
        self.send_header('Content-Disposition', f'attachment; filename="{filename}"')
        self.end_headers()
        self.wfile.write(content.encode('utf-8'))

    def _serve_file(self, filepath, mime):
        if filepath.exists():
            self.send_response(200)
            self.send_header('Content-Type', f'{mime}; charset=utf-8')
            self.end_headers()
            self.wfile.write(filepath.read_bytes())
        else:
            self.send_error(404)

    def _serve_video(self, file_path):
        size = file_path.stat().st_size
        # .LRV est un conteneur MP4 (HEVC GoPro). Sans MIME video/mp4 explicite
        # Chromium peut refuser de le lire via <video>.
        ext = file_path.suffix.lower()
        if ext in ('.mp4', '.lrv'):
            mime = 'video/mp4'
        else:
            mime = 'video/quicktime'
        range_header = self.headers.get('Range')
        if range_header:
            ranges = range_header.replace('bytes=', '').split('-')
            start = int(ranges[0]) if ranges[0] else 0
            end = int(ranges[1]) if len(ranges) > 1 and ranges[1] else size - 1
            length = end - start + 1
            self.send_response(206)
            self.send_header('Content-Type', mime)
            self.send_header('Content-Range', f'bytes {start}-{end}/{size}')
            self.send_header('Content-Length', str(length))
            self.send_header('Accept-Ranges', 'bytes')
            self.end_headers()
            with open(file_path, 'rb') as f:
                f.seek(start)
                remaining = length
                while remaining > 0:
                    chunk = f.read(min(65536, remaining))
                    if not chunk: break
                    self.wfile.write(chunk)
                    remaining -= len(chunk)
        else:
            self.send_response(200)
            self.send_header('Content-Type', mime)
            self.send_header('Content-Length', str(size))
            self.send_header('Accept-Ranges', 'bytes')
            self.end_headers()
            with open(file_path, 'rb') as f:
                while True:
                    chunk = f.read(65536)
                    if not chunk: break
                    self.wfile.write(chunk)

    def _serve_audio(self, file_path):
        size = file_path.stat().st_size
        range_header = self.headers.get('Range')
        if range_header:
            ranges = range_header.replace('bytes=', '').split('-')
            start = int(ranges[0]) if ranges[0] else 0
            end = int(ranges[1]) if len(ranges) > 1 and ranges[1] else size - 1
            length = end - start + 1
            self.send_response(206)
            self.send_header('Content-Type', 'audio/wav')
            self.send_header('Content-Range', f'bytes {start}-{end}/{size}')
            self.send_header('Content-Length', str(length))
            self.send_header('Accept-Ranges', 'bytes')
            self.end_headers()
            with open(file_path, 'rb') as f:
                f.seek(start)
                remaining = length
                while remaining > 0:
                    chunk = f.read(min(65536, remaining))
                    if not chunk: break
                    self.wfile.write(chunk)
                    remaining -= len(chunk)
        else:
            self.send_response(200)
            self.send_header('Content-Type', 'audio/wav')
            self.send_header('Content-Length', str(size))
            self.send_header('Accept-Ranges', 'bytes')
            self.end_headers()
            with open(file_path, 'rb') as f:
                while True:
                    chunk = f.read(65536)
                    if not chunk: break
                    self.wfile.write(chunk)

    def log_message(self, format, *args):
        pass

def _sync_headers(extra=None):
    """En-têtes des requêtes vers le serveur de sync. La clé passe en en-tête
    X-Sync-Key (audit 2.2) — une fois derush_sync.php redéployé, elle n'a plus
    besoin d'être dans le query string et n'apparaît plus dans les logs Apache.
    Le ?key= reste pour l'instant (rétrocompatibilité)."""
    h = {'User-Agent': 'DerushTool', 'X-Sync-Key': SYNC_KEY}
    if extra:
        h.update(extra)
    return h

def _sync_url_for(pid):
    # URL-encode pour gérer les espaces et caractères spéciaux (sinon urllib râle).
    # NB : la PHP filtre déjà via preg_replace([^a-zA-Z0-9_\-]) côté serveur, donc
    # un pid avec espaces ne matchera jamais — mais ici on évite au moins le crash.
    return f"{SYNC_URL.rstrip('/')}?key={_urlquote(SYNC_KEY, safe='')}&project={_urlquote(pid, safe='')}"

def _own_note_key(proj):
    """Clé de notes de l'utilisateur de CETTE machine (son profil local).
    Sert au merge sync : une machine ne publie que ses propres notes (audit §5)."""
    prof = load_profile()
    if not prof:
        return None
    u = find_project_user(proj, prof.get('username', ''))
    return user_note_key(u) if u else None

def merge_projects(local, remote, own_uid=None):
    """Fusionne remote dans local.

    Notes (audit §5) : on part de la version distante et cette machine ne
    réimpose QUE les notes de son propre utilisateur (`own_uid`). Sinon une
    machine réécrirait les notes des autres users avec sa copie périmée → une
    suppression de marqueur faite ailleurs « reviendrait » au sync suivant.
    Si `own_uid` est inconnu, on retombe sur l'ancien comportement (toutes les
    clés locales) pour ne risquer aucune perte.
    """
    result = copy.deepcopy(local)
    merged_notes = copy.deepcopy(remote.get('notes', {}))
    local_notes = local.get('notes', {})
    if own_uid is not None:
        if own_uid in local_notes:
            merged_notes[own_uid] = local_notes[own_uid]
        # own_uid connu mais pas de notes locales pour lui → on ne touche à rien
    else:
        for uid, unotes in local_notes.items():
            merged_notes[uid] = unotes
    result['notes'] = merged_notes

    # Discussions : ajoute les replies du remote absentes en local (clé = timestamp)
    remote_disc = remote.get('discussions', {})
    local_disc  = copy.deepcopy(local.get('discussions', {}))
    for clip_id, markers in remote_disc.items():
        local_disc.setdefault(clip_id, {})
        for marker_id, replies in markers.items():
            if marker_id not in local_disc[clip_id]:
                local_disc[clip_id][marker_id] = list(replies)
            else:
                known_ts = {r['ts'] for r in local_disc[clip_id][marker_id]}
                for r in replies:
                    if r.get('ts') not in known_ts:
                        local_disc[clip_id][marker_id].append(r)
                local_disc[clip_id][marker_id].sort(key=lambda x: x.get('ts', ''))
    result['discussions'] = local_disc

    # Tombstones : union des suppressions local + remote, MAIS un user qui est
    # actuellement présent dans les users[] locaux est considéré comme "lift" du
    # tombstone (re-création après suppression). Sinon impossible de re-créer
    # un user supprimé : le tombstone remote le re-filtre à chaque sync.
    local_dead = set(t.lower() for t in local.get('deleted_users', []))
    remote_dead = set(t.lower() for t in (remote.get('deleted_users', []) or []))
    all_dead = local_dead | remote_dead
    local_alive = {(u.get('username') or u.get('name', '')).lower() for u in local.get('users', [])}
    all_dead -= local_alive  # un user "vivant" en local lève le tombstone
    result['deleted_users'] = sorted(all_dead)

    # Filtre les users locaux : retire ceux qui sont dans les tombstones (cas où
    # le remote a supprimé un user que le local avait encore)
    result['users'] = [u for u in result.get('users', [])
                       if (u.get('username') or u.get('name', '')).lower() not in all_dead]

    # Utilisateurs : ajoute les users du remote absents en local ET pas tombstoned
    local_ids = {user_note_key(u) for u in result.get('users', [])}
    for u in remote.get('users', []):
        uname = (u.get('username') or u.get('name', '')).lower()
        if uname in all_dead: continue  # supprimé → ne pas re-pomper
        if user_note_key(u) not in local_ids:
            result['users'].append(u)

    return result

# Debounced push : chaque save planifie un sync 3s plus tard. Sauves rapprochées
# remplacent le timer précédent → un seul sync_project() pour une rafale d'éditions.
_sync_push_timers = {}
_sync_push_lock = threading.Lock()

def _schedule_sync_push(pid, delay=3.0):
    """Push debounced — annule le timer en cours et en re-arme un."""
    if not SYNC_URL or not SYNC_KEY:
        return
    with _sync_push_lock:
        t = _sync_push_timers.get(pid)
        if t:
            try: t.cancel()
            except Exception: pass
        def _fire():
            try: sync_project(pid)
            except Exception: pass
        t = threading.Timer(delay, _fire)
        t.daemon = True
        _sync_push_timers[pid] = t
        t.start()

def sync_project(pid):
    """Pull remote, merge, push. Retourne {'ok': bool, 'message': str}"""
    global _sync_status
    url = _sync_url_for(pid)

    proj = load_project(pid)
    if not proj:
        return {'ok': False, 'message': 'Projet introuvable'}

    # Pull
    try:
        req = urllib.request.Request(url, headers=_sync_headers())
        with urllib.request.urlopen(req, timeout=10) as resp:
            remote = json.loads(resp.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            remote = None   # Premier push
        else:
            msg = f'Erreur serveur {e.code}'
            with _sync_lock:
                _sync_status.update({'online': False, 'error': msg})
            return {'ok': False, 'message': msg}
    except Exception as e:
        msg = f'Connexion impossible : {e}'
        with _sync_lock:
            _sync_status.update({'online': False, 'error': msg})
        return {'ok': False, 'message': msg}

    # Merge + save sous verrou projet : on recharge le projet à l'instant T pour
    # ne pas écraser une écriture concurrente survenue pendant le pull réseau
    # (audit 1.1).
    with _project_lock(pid):
        local_now = load_project(pid) or proj
        own = _own_note_key(local_now)
        merged = merge_projects(local_now, remote, own_uid=own) if remote else local_now
        save_project(pid, merged)

    # Push du résultat fusionné vers le cloud
    try:
        data = json.dumps(merged, ensure_ascii=False).encode('utf-8')
        req  = urllib.request.Request(url, data=data, method='POST',
                                      headers=_sync_headers({'Content-Type': 'application/json'}))
        with urllib.request.urlopen(req, timeout=10) as resp:
            resp.read()
    except Exception as e:
        msg = f'Erreur push : {e}'
        with _sync_lock:
            _sync_status.update({'online': False, 'error': msg})
        return {'ok': False, 'message': msg}

    ts = datetime.now().strftime('%H:%M')
    with _sync_lock:
        _sync_status.update({'online': True, 'last_sync': datetime.now().isoformat(), 'error': None})
    return {'ok': True, 'message': f'Synchronisé à {ts}'}

# ─── Share link (review externe) ────────────────────────────────────────────
def _b64_file(path):
    """Lit un fichier binaire et retourne sa base64 (ou None si absent)."""
    try:
        with open(path, 'rb') as f:
            return base64.b64encode(f.read()).decode('ascii')
    except Exception:
        return None

def _resolve_clip_local_path(proj, clip):
    """Trouve le chemin local d'un clip : essaie proxy_url + chaque user root_path,
    fallback sur clip['path']. Utilisé pour générer les previews share côté serveur."""
    if clip.get('proxy_url'):
        rel = unquote(clip['proxy_url'][7:]).replace('\\', '/')
        for u in proj.get('users', []):
            rp = u.get('root_path') or proj.get('root_path', '')
            if not rp: continue
            resolved = _resolve_relpath_tolerant(rp, rel)
            if resolved is not None:
                return resolved
    cp = Path(clip.get('path', ''))
    if cp.exists():
        return cp
    return None

def compute_share_previews(file_path, clip_id, duration_sec, n=4, W=640, H=360):
    """Génère n previews HD pour le viewer share. Frames répartis équitablement,
    qualité supérieure au strip habituel (lanczos + q=3 vs fast_bilinear + q=5).
    Cache : <clip_id>_share<i>.jpg dans THUMBNAILS_DIR."""
    out_paths = [THUMBNAILS_DIR / f"{clip_id}_share{i}.jpg" for i in range(n)]
    missing = [i for i, p in enumerate(out_paths) if not p.exists()]
    if not missing:
        return out_paths
    src = _lighter_decode_source(file_path)
    def _do():
        from concurrent.futures import ThreadPoolExecutor
        def _gen(i):
            # (i+0.5)/n centre chaque frame dans son segment de temps (évite t=0
            # souvent noir et t=duration souvent out of bounds).
            t = max(0.3, (i + 0.5) * duration_sec / n)
            try:
                cmd = [FFMPEG, '-hide_banner', '-loglevel', 'error',
                       '-analyzeduration', '1M', '-probesize', '5M',
                       '-ss', f'{t:.2f}', '-i', src,
                       '-an', '-frames:v', '1',
                       '-vf', f'scale={W}:{H}:flags=lanczos',
                       '-q:v', '3', '-y', str(out_paths[i])]
                _ffmpeg_run(cmd, timeout=30)
            except Exception:
                pass
        with ThreadPoolExecutor(max_workers=3) as ex:
            list(ex.map(_gen, missing))
    _dedupe_compute(f"share_prev:{clip_id}", _do)
    return out_paths

def build_share_package(pid):
    """Construit le payload à uploader sur le sync.php pour la review externe.
    Inclut annotations + thumbnails + strips (b64), pas de vidéo."""
    proj = load_project(pid)
    if not proj:
        return None
    package = {
        'project_id': pid,
        'name': proj.get('name', pid),
        'created_at': datetime.now().isoformat(timespec='seconds'),
        'users': [{'id': user_note_key(u), 'name': u.get('name') or u.get('username', ''), 'color': u.get('color', '#a78bfa')}
                  for u in proj.get('users', [])],
        'clips': [],
        'notes': proj.get('notes', {}),
        'discussions': proj.get('discussions', {}),
    }
    for clip in proj.get('clips', []):
        cid = clip['id']
        thumb_b64 = _b64_file(THUMBNAILS_DIR / f"{cid}.jpg")
        # Génère + embed 4 previews HD pour le viewer share (cache permanent)
        previews_b64 = []
        file_path = _resolve_clip_local_path(proj, clip)
        if file_path:
            try:
                preview_paths = compute_share_previews(str(file_path), cid, clip.get('duration_sec', 10))
                previews_b64 = [_b64_file(p) for p in preview_paths]
                previews_b64 = [b for b in previews_b64 if b]  # drop les frames qui ont raté
            except Exception:
                previews_b64 = []
        package['clips'].append({
            'id': cid,
            'stem': clip.get('stem', ''),
            'filename': clip.get('filename', ''),
            'camera': clip.get('camera', ''),
            'day': clip.get('day', ''),
            'tc_in': clip.get('tc_in', ''),
            'duration_sec': clip.get('duration_sec', 0),
            'fps': clip.get('fps', 25),
            'resolution': clip.get('resolution', ''),
            'thumb_b64': thumb_b64,
            'previews_b64': previews_b64,  # 4 frames HD 640×360 pour le viewer
        })
    return package

def create_share(pid):
    """Génère un token + push le package vers sync.php. Stocke le token dans proj['share']."""
    if not SYNC_URL or not SYNC_KEY:
        return {'ok': False, 'error': 'Sync cloud non configurée (⚙️ Configuration)'}
    proj = load_project(pid)
    if not proj:
        return {'ok': False, 'error': 'Projet introuvable'}
    # Réutilise un token existant si déjà partagé (sinon on génère)
    token = (proj.get('share') or {}).get('token') or secrets.token_urlsafe(12)
    package = build_share_package(pid)
    if not package:
        return {'ok': False, 'error': 'Impossible de construire le package'}
    # Expiration du lien (audit 2.5) — embarquée dans le package : c'est la PHP
    # qui refusera de servir un lien périmé.
    expires_at = (datetime.now() + timedelta(days=_SHARE_TTL_DAYS)).isoformat(timespec='seconds')
    package['expires_at'] = expires_at
    try:
        url = f"{SYNC_URL.rstrip('/')}?key={SYNC_KEY}&action=create_share&token={token}"
        data = json.dumps(package, ensure_ascii=False).encode('utf-8')
        req = urllib.request.Request(url, data=data, method='POST',
                                     headers=_sync_headers({'Content-Type': 'application/json'}))
        with urllib.request.urlopen(req, timeout=30) as resp:
            resp.read()
    except Exception as e:
        return {'ok': False, 'error': f'Push share échoué : {e}'}
    with _project_lock(pid):
        proj = load_project(pid) or proj
        proj['share'] = {
            'token': token,
            'created_at': datetime.now().isoformat(timespec='seconds'),
            'expires_at': expires_at,
            'comments_last_pulled': None,
        }
        save_project(pid, proj)
    # URL viewer (sans key) basée sur sync_url
    base = SYNC_URL.rstrip('/').rsplit('?', 1)[0]
    viewer_url = f"{base}?view=share&token={token}"
    return {'ok': True, 'token': token, 'url': viewer_url, 'expires_at': expires_at}

def revoke_share(pid):
    """Révoque le partage : supprime le token côté projet et envoie un delete au cloud."""
    proj = load_project(pid)
    if not proj:
        return {'ok': False, 'error': 'Projet introuvable'}
    token = (proj.get('share') or {}).get('token')
    if token and SYNC_URL and SYNC_KEY:
        try:
            url = f"{SYNC_URL.rstrip('/')}?key={SYNC_KEY}&action=revoke_share&token={token}"
            req = urllib.request.Request(url, method='POST', headers=_sync_headers())
            with urllib.request.urlopen(req, timeout=10) as resp:
                resp.read()
        except Exception:
            pass  # On supprime localement même si le cloud refuse
    with _project_lock(pid):
        proj = load_project(pid) or proj
        proj.pop('share', None)
        save_project(pid, proj)
    return {'ok': True}

# Locks par projet pour empêcher pull_share_comments concurrents (cause de
# duplication : chaque appel lit le même `since`, récupère les mêmes commentaires,
# les append → N copies si N appels en parallèle).
_share_pull_locks = {}
_share_pull_locks_lock = threading.Lock()
def _get_share_lock(pid):
    with _share_pull_locks_lock:
        if pid not in _share_pull_locks:
            _share_pull_locks[pid] = threading.Lock()
        return _share_pull_locks[pid]

def pull_share_comments(pid):
    """Récupère les nouveaux commentaires externes depuis le cloud, les stocke dans
    proj['share_comments'][clip_id] = [{name, text, ts}].
    Lock per-pid + dédoublonnage rétroactif pour absorber les copies déjà accumulées."""
    with _get_share_lock(pid):
        proj = load_project(pid)
        if not proj or not proj.get('share') or not SYNC_URL or not SYNC_KEY:
            return {'ok': False, 'count': 0}
        token = proj['share']['token']
        # IMPORTANT: si comments_last_pulled est None (jamais pullé), on doit envoyer
        # chaîne vide, sinon PHP reçoit "None" et la comparaison '2026-...' <= 'None'
        # est True alphanumériquement → tous les commentaires sont filtrés.
        since = proj['share'].get('comments_last_pulled') or ''
        try:
            url = f"{SYNC_URL.rstrip('/')}?key={SYNC_KEY}&action=poll_comments&token={token}&since={since}"
            req = urllib.request.Request(url, headers=_sync_headers())
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode('utf-8'))
        except Exception as e:
            return {'ok': False, 'error': str(e), 'count': 0}

        sc = proj.setdefault('share_comments', {})
        # Dédup rétroactif : nettoie les copies déjà accumulées avant le fix.
        for cid in list(sc.keys()):
            seen = set()
            deduped = []
            for c in sc[cid]:
                key = (c.get('ts', ''), c.get('text', ''))
                if key in seen: continue
                seen.add(key)
                deduped.append(c)
            sc[cid] = deduped

        new_comments = data.get('comments', [])
        added = 0
        max_ts = since
        for c in new_comments:
            cid = c.get('clip_id', '')
            if not cid: continue
            sc.setdefault(cid, [])
            existing_keys = {(x.get('ts', ''), x.get('text', '')) for x in sc[cid]}
            key = (c.get('ts', ''), c.get('text', ''))
            if key not in existing_keys:
                sc[cid].append({
                    'name': c.get('name', 'Anonyme')[:80],
                    'text': c.get('text', '')[:2000],
                    'ts': c.get('ts', datetime.now().isoformat(timespec='seconds')),
                })
                added += 1
            if c.get('ts', '') > max_ts:
                max_ts = c['ts']
        proj['share']['comments_last_pulled'] = max_ts
        with _project_lock(pid):
            save_project(pid, proj)
        return {'ok': True, 'count': added}

def sync_all_projects():
    """Synchronise tous les projets connus + pull les commentaires share externes."""
    results = {}
    for f in PROJECTS_DIR.glob('*.derush.json'):
        pid = f.stem.replace('.derush', '')
        results[pid] = sync_project(pid)
        # Pull share comments si projet partagé (best-effort, n'échoue jamais)
        try:
            proj = load_project(pid)
            if proj and proj.get('share'):
                pull_share_comments(pid)
        except Exception:
            pass
    return results

def _sync_background_thread():
    """Thread de fond : détecte la reconnexion et sync automatiquement."""
    global _sync_status
    was_online      = None
    last_full_sync  = None
    POLL_INTERVAL   = 90       # secondes entre chaque vérification
    FORCE_SYNC_SECS = 10 * 60  # sync forcée toutes les 10 minutes

    while True:
        threading.Event().wait(POLL_INTERVAL)

        if not SYNC_URL or not SYNC_KEY:
            with _sync_lock:
                _sync_status['configured'] = False
            continue

        with _sync_lock:
            _sync_status['configured'] = True

        # Test de connectivité léger
        pid_list = [f.stem for f in PROJECTS_DIR.glob('*.derush.json')]
        if not pid_list:
            continue

        test_url = f"{SYNC_URL.rstrip('/')}?key={SYNC_KEY}&project={pid_list[0]}"
        now_online = False
        try:
            req = urllib.request.Request(test_url, headers={'User-Agent': 'DerushTool'})
            with urllib.request.urlopen(req, timeout=8) as r:
                r.read()
            now_online = True
        except Exception:
            try:  # 404 = serveur joignable mais projet pas encore uploadé = online
                urllib.request.urlopen(test_url, timeout=8)
                now_online = True
            except urllib.error.HTTPError as he:
                now_online = he.code in (403, 404)
            except Exception:
                now_online = False

        reconnected = (was_online is False and now_online)
        force_due   = (last_full_sync is None or
                       (datetime.now() - datetime.fromisoformat(last_full_sync)).total_seconds() > FORCE_SYNC_SECS)

        if now_online and (reconnected or force_due):
            for pid in pid_list:
                sync_project(pid)
            last_full_sync = datetime.now().isoformat()

        was_online = now_online
        with _sync_lock:
            _sync_status['online'] = now_online

def run(open_browser=False):
    lan_ip = get_lan_ip()
    print("=========================================")
    print("      DERUSH TOOL -- Serveur             ")
    print("=========================================")
    print(f"  Local : http://localhost:{PORT}")
    print(f"  LAN   : http://{lan_ip}:{PORT}")
    print(f"  Projets : {PROJECTS_DIR}")
    print("=========================================")
    server = ThreadedHTTPServer(('0.0.0.0', PORT), DerushHandler)
    threading.Thread(target=_sync_background_thread, daemon=True).start()
    threading.Thread(target=_rebuild_index_full, daemon=True).start()
    if open_browser:
        import webbrowser, time
        def _open():
            time.sleep(1.5)
            webbrowser.open(f'http://localhost:{PORT}')
        threading.Thread(target=_open, daemon=True).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nArrêt du serveur.")

if __name__ == '__main__':
    # --no-browser : démarrer le serveur sans ouvrir automatiquement un onglet.
    # Utilisé par le wrapper Electron qui gère sa propre fenêtre Chromium.
    no_browser = '--no-browser' in sys.argv
    run(open_browser=not no_browser)
