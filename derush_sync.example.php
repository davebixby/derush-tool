<?php
/**
 * DERUSH TOOL — Sync endpoint + Share viewer
 * Déposez ce fichier sur votre hébergement web.
 * Configurez $SECRET_KEY avec une clé secrète de votre choix.
 *
 * SYNC (key required) :
 *   GET  ?key=SECRET&project=<pid>                  → télécharge le JSON du projet
 *   POST ?key=SECRET&project=<pid>  + body          → sauvegarde le JSON du projet
 *   GET  ?key=SECRET&action=list                    → liste les projets cloud
 *
 * SHARE — review externe (token-authed, no key):
 *   GET  ?view=share&token=<token>                  → page HTML viewer (public)
 *   GET  ?action=get_share&token=<token>            → package JSON
 *   POST ?action=add_comment&token=<token>  + body  → ajoute un commentaire
 *
 * SHARE — admin (key required):
 *   POST ?key=SECRET&action=create_share&token=<token> + body → stocke package
 *   POST ?key=SECRET&action=revoke_share&token=<token>        → supprime share
 *   GET  ?key=SECRET&action=poll_comments&token=<token>&since=<ts> → comments depuis ts
 */

$SECRET_KEY = 'CHANGEME_GENEREZ_UNE_CLE_ALEATOIRE_LONGUE';
$DATA_DIR   = __DIR__ . '/derush_data/';
$SHARE_DIR  = $DATA_DIR . 'shares/';

// --- Init ---
if (!is_dir($DATA_DIR))  mkdir($DATA_DIR, 0755, true);
if (!is_dir($SHARE_DIR)) mkdir($SHARE_DIR, 0755, true);
if (!file_exists($DATA_DIR . '.htaccess')) {
    file_put_contents($DATA_DIR . '.htaccess', "Options -Indexes\nDeny from all\n");
}

$action = $_GET['action'] ?? '';
$view   = $_GET['view']   ?? '';
$token  = preg_replace('/[^A-Za-z0-9_\-]/', '', $_GET['token'] ?? '');

// ─── PUBLIC : viewer HTML ────────────────────────────────────────────────────
if ($view === 'share') {
    if (!$token) { http_response_code(400); echo 'Token manquant'; exit; }
    header('Content-Type: text/html; charset=utf-8');
    serve_viewer_html($token);
    exit;
}

// ─── PUBLIC : récupérer le package (token = auth) ────────────────────────────
if ($action === 'get_share') {
    header('Content-Type: application/json; charset=utf-8');
    header('Access-Control-Allow-Origin: *');
    if (!$token) { http_response_code(400); echo '{"error":"Token manquant"}'; exit; }
    $f = $SHARE_DIR . $token . '.json';
    if (!file_exists($f)) { http_response_code(404); echo '{"error":"Lien expiré ou révoqué"}'; exit; }
    // Expiration du lien (audit 2.5) : le package embarque expires_at.
    $pkg = json_decode(file_get_contents($f), true) ?: [];
    if (!empty($pkg['expires_at']) && strtotime($pkg['expires_at']) < time()) {
        http_response_code(410); echo '{"error":"Ce lien de review a expiré."}'; exit;
    }
    readfile($f);
    exit;
}

// ─── PUBLIC : lire tous les commentaires (token = auth) ─────────────────────
if ($action === 'get_comments') {
    header('Content-Type: application/json; charset=utf-8');
    header('Access-Control-Allow-Origin: *');
    if (!$token) { http_response_code(400); echo '{"error":"Token manquant"}'; exit; }
    $f_share = $SHARE_DIR . $token . '.json';
    if (!file_exists($f_share)) { http_response_code(404); echo '{"error":"Lien expiré"}'; exit; }
    $f = $SHARE_DIR . $token . '_comments.jsonl';
    $comments = [];
    if (file_exists($f)) {
        foreach (file($f, FILE_IGNORE_NEW_LINES | FILE_SKIP_EMPTY_LINES) as $line) {
            $c = json_decode($line, true);
            if ($c) $comments[] = $c;
        }
    }
    echo json_encode(['comments' => $comments]);
    exit;
}

// ─── PUBLIC : ajouter un commentaire (token = auth) ──────────────────────────
if ($action === 'add_comment' && $_SERVER['REQUEST_METHOD'] === 'POST') {
    header('Content-Type: application/json; charset=utf-8');
    header('Access-Control-Allow-Origin: *');
    if (!$token) { http_response_code(400); echo '{"error":"Token manquant"}'; exit; }
    $f_share = $SHARE_DIR . $token . '.json';
    if (!file_exists($f_share)) { http_response_code(404); echo '{"error":"Lien expiré"}'; exit; }
    $body = json_decode(file_get_contents('php://input'), true);
    if (!$body || empty($body['clip_id']) || empty($body['text'])) {
        http_response_code(400); echo '{"error":"clip_id et text requis"}'; exit;
    }
    $comment = [
        'clip_id' => (string)$body['clip_id'],
        'name'    => substr((string)($body['name'] ?? 'Anonyme'), 0, 80),
        'text'    => substr((string)$body['text'], 0, 2000),
        'ts'      => date('c'),
    ];
    $f_comments = $SHARE_DIR . $token . '_comments.jsonl';
    file_put_contents($f_comments, json_encode($comment, JSON_UNESCAPED_UNICODE) . "\n", FILE_APPEND | LOCK_EX);
    echo json_encode(['ok' => true]);
    exit;
}

// ─── Tout le reste demande la clé secrète ────────────────────────────────────
header('Content-Type: application/json; charset=utf-8');
header('Access-Control-Allow-Origin: *');
header('Access-Control-Allow-Methods: GET, POST, OPTIONS');
header('Access-Control-Allow-Headers: Content-Type');

if ($_SERVER['REQUEST_METHOD'] === 'OPTIONS') { http_response_code(200); exit; }

// Clé acceptée via l'en-tête X-Sync-Key (recommandé : n'apparaît pas dans les
// logs du serveur web) OU via ?key= (rétrocompatibilité). Comparaison à temps
// constant (hash_equals) pour ne pas fuiter la clé via une attaque temporelle.
$key = $_SERVER['HTTP_X_SYNC_KEY'] ?? ($_GET['key'] ?? '');
if (!hash_equals($SECRET_KEY, (string)$key)) {
    http_response_code(403);
    echo json_encode(['error' => 'Forbidden']);
    exit;
}

// ─── ADMIN : create / revoke / poll_comments ─────────────────────────────────
if ($action === 'create_share' && $_SERVER['REQUEST_METHOD'] === 'POST') {
    if (!$token) { http_response_code(400); echo '{"error":"Token requis"}'; exit; }
    $body = file_get_contents('php://input');
    if (!$body || !json_decode($body)) { http_response_code(400); echo '{"error":"Body JSON invalide"}'; exit; }
    file_put_contents($SHARE_DIR . $token . '.json', $body, LOCK_EX);
    echo json_encode(['ok' => true, 'token' => $token]);
    exit;
}

if ($action === 'revoke_share' && $_SERVER['REQUEST_METHOD'] === 'POST') {
    if (!$token) { http_response_code(400); echo '{"error":"Token requis"}'; exit; }
    @unlink($SHARE_DIR . $token . '.json');
    @unlink($SHARE_DIR . $token . '_comments.jsonl');
    echo json_encode(['ok' => true]);
    exit;
}

if ($action === 'poll_comments') {
    if (!$token) { http_response_code(400); echo '{"error":"Token requis"}'; exit; }
    $since = $_GET['since'] ?? '';
    $f = $SHARE_DIR . $token . '_comments.jsonl';
    $comments = [];
    if (file_exists($f)) {
        foreach (file($f, FILE_IGNORE_NEW_LINES | FILE_SKIP_EMPTY_LINES) as $line) {
            $c = json_decode($line, true);
            if (!$c) continue;
            if ($since !== '' && ($c['ts'] ?? '') <= $since) continue;
            $comments[] = $c;
        }
    }
    echo json_encode(['comments' => $comments]);
    exit;
}

// ─── List cloud projects ─────────────────────────────────────────────────────
if ($_SERVER['REQUEST_METHOD'] === 'GET' && $action === 'list') {
    $projects = [];
    foreach (glob($DATA_DIR . '*.derush.json') as $f) {
        $id   = basename($f, '.derush.json');
        $data = json_decode(file_get_contents($f), true) ?: [];
        $projects[] = [
            'id'         => $id,
            'name'       => $data['name'] ?? $id,
            'clip_count' => count($data['clips'] ?? []),
        ];
    }
    echo json_encode(['projects' => $projects]);
    exit;
}

// ─── Project sync (download/upload by ?project= name) ────────────────────────
$project = preg_replace('/[^a-zA-Z0-9_\-]/', '', $_GET['project'] ?? '');
if (!$project) { http_response_code(400); echo '{"error":"Missing project"}'; exit; }
$file = $DATA_DIR . $project . '.derush.json';

if ($_SERVER['REQUEST_METHOD'] === 'GET') {
    if (!file_exists($file)) { http_response_code(404); echo '{"error":"Not found"}'; exit; }
    readfile($file);
    exit;
}

if ($_SERVER['REQUEST_METHOD'] === 'POST') {
    $body = file_get_contents('php://input');
    if (!$body || !json_decode($body)) { http_response_code(400); echo '{"error":"Invalid JSON"}'; exit; }
    // Backup (10 derniers)
    if (file_exists($file)) {
        $bak_dir = $DATA_DIR . 'backups/' . $project . '/';
        if (!is_dir($bak_dir)) mkdir($bak_dir, 0755, true);
        $ts = date('YmdHis');
        copy($file, $bak_dir . $project . '_' . $ts . '.json');
        $baks = glob($bak_dir . '*.json');
        sort($baks);
        foreach (array_slice($baks, 0, max(0, count($baks) - 10)) as $old) unlink($old);
    }
    file_put_contents($file, $body, LOCK_EX);
    echo json_encode(['ok' => true, 'ts' => date('c')]);
    exit;
}

http_response_code(405);
echo json_encode(['error' => 'Method not allowed']);

// ─── HTML Viewer page ────────────────────────────────────────────────────────
function serve_viewer_html($token) {
    $safe_token = htmlspecialchars($token, ENT_QUOTES);
    echo <<<HTML
<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>Derush — Review</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
:root { --bg:#0a0a0f; --surface:#12121a; --border:rgba(255,255,255,.08); --text:#e0e0e8; --dim:#6b6b80; --accent:#a78bfa; --green:#34d399; --red:#ef4444; }
* { box-sizing:border-box; margin:0; padding:0; }
::-webkit-scrollbar { width:8px; height:8px; }
::-webkit-scrollbar-thumb { background:rgba(167,139,250,.25); border-radius:4px; }
::-webkit-scrollbar-thumb:hover { background:rgba(167,139,250,.5); }
html,body { background:var(--bg); color:var(--text); font-family:'Inter',sans-serif; height:100vh; overflow:hidden; }
body { display:flex; flex-direction:column; }
#root { flex:1; display:flex; flex-direction:column; min-height:0; }
header { background:var(--surface); border-bottom:1px solid var(--border); padding:12px 18px; display:flex; align-items:center; gap:12px; flex-shrink:0; }
header h1 { color:var(--accent); font-size:1em; font-weight:700; }
header .meta { color:var(--dim); font-size:0.78em; }
.layout { flex:1; display:flex; min-height:0; }
aside { width:320px; border-right:1px solid var(--border); overflow-y:auto; background:var(--surface); flex-shrink:0; }
.day-header { padding:6px 14px; font-size:0.68em; font-weight:700; letter-spacing:.08em; text-transform:uppercase; color:var(--accent); background:var(--bg); border-bottom:1px solid var(--border); position:sticky; top:0; z-index:1; }
.clip-row { display:flex; gap:8px; padding:10px 14px; border-bottom:1px solid var(--border); cursor:pointer; align-items:flex-start; }
.clip-row:hover { background:rgba(167,139,250,.06); }
.clip-row.active { background:rgba(167,139,250,.14); border-left:3px solid var(--accent); padding-left:11px; }
.clip-row .thumb { width:60px; height:34px; border-radius:3px; object-fit:cover; background:#000; flex-shrink:0; margin-top:2px; }
.clip-row .info { flex:1; min-width:0; }
.clip-row .name { font-size:0.85em; font-weight:600; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.clip-row .sub { font-size:0.7em; color:var(--dim); margin-top:2px; }
.clip-row .rating { font-size:0.72em; margin-top:2px; }
main { flex:1; overflow-y:auto; padding:24px 32px; min-width:0; }
main .placeholder { color:var(--dim); padding:40px; text-align:center; }
.clip-header { display:flex; gap:16px; align-items:flex-start; margin-bottom:18px; flex-wrap:wrap; }
.clip-header .strip { width:100%; max-width:640px; aspect-ratio:16/9; background:#000; border-radius:6px; object-fit:cover; }
.strips4 { display:grid; grid-template-columns:repeat(4,1fr); gap:6px; margin-top:12px; }
.strip4-frame { aspect-ratio:16/9; border-radius:4px; background:#000; overflow:hidden; }
.strip4-frame img { width:100%; height:100%; object-fit:cover; display:block; }
.clip-header .title { font-size:1.2em; font-weight:700; margin-bottom:4px; }
.clip-header .technical { font-size:0.82em; color:var(--dim); }
.section { margin-top:24px; }
.section h3 { font-size:0.78em; font-weight:700; text-transform:uppercase; letter-spacing:.08em; color:var(--accent); margin-bottom:10px; }
.markers-list { display:flex; flex-direction:column; gap:6px; }
.marker-item { background:var(--surface); border:1px solid var(--border); border-radius:6px; padding:10px 12px; display:flex; gap:10px; align-items:flex-start; }
.marker-item .tc { font-family:monospace; font-size:0.82em; color:var(--accent); flex-shrink:0; min-width:90px; }
.marker-item .cat { font-size:1em; flex-shrink:0; }
.marker-item .body { flex:1; min-width:0; }
.marker-item .who { font-size:0.72em; color:var(--dim); }
.marker-item .desc { font-size:0.9em; margin-top:2px; }
.notes-list { display:flex; flex-direction:column; gap:10px; }
.note-card { background:var(--surface); border-left:3px solid var(--accent); border-radius:0 6px 6px 0; padding:10px 14px; }
.note-card .author { font-size:0.78em; font-weight:600; }
.note-card .rating { display:inline; color:var(--accent); margin-left:6px; }
.note-card .tags { margin-top:4px; }
.tag { display:inline-block; background:rgba(167,139,250,.15); color:#c4b5fd; border:1px solid rgba(167,139,250,.3); border-radius:10px; padding:1px 7px; font-size:0.72em; margin-right:4px; }
.note-card .text { font-size:0.88em; margin-top:6px; color:var(--text); white-space:pre-wrap; }
.comments-list { display:flex; flex-direction:column; gap:8px; margin-bottom:14px; }
.comment-item { background:rgba(52,211,153,.06); border:1px solid rgba(52,211,153,.2); border-radius:6px; padding:10px 12px; }
.comment-item .head { display:flex; gap:8px; align-items:baseline; }
.comment-item .name { font-size:0.85em; font-weight:600; color:var(--green); }
.comment-item .ts { font-size:0.7em; color:var(--dim); font-family:monospace; }
.comment-item .text { font-size:0.88em; margin-top:4px; white-space:pre-wrap; }
.comment-form { background:var(--surface); border:1px solid var(--border); border-radius:8px; padding:12px 14px; }
.comment-form input, .comment-form textarea { width:100%; background:var(--bg); color:var(--text); border:1px solid var(--border); border-radius:4px; padding:8px 10px; font-family:inherit; font-size:0.88em; margin-bottom:8px; }
.comment-form textarea { min-height:70px; resize:vertical; }
.comment-form button { background:var(--accent); color:#000; border:none; border-radius:4px; padding:8px 16px; font-weight:600; cursor:pointer; }
.comment-form button:hover { background:#b8a2fb; }
.comment-form .ok { color:var(--green); font-size:0.82em; }
.comment-form .err { color:var(--red); font-size:0.82em; }
.error-page { display:flex; height:100vh; align-items:center; justify-content:center; color:var(--dim); font-size:1.1em; flex-direction:column; gap:8px; }
@media (max-width:720px) {
    aside { width:200px; }
    main { padding:16px; }
    .clip-row .thumb { width:48px; height:27px; }
}
</style>
</head>
<body>
<div id="root"></div>
<script>
const TOKEN = "{$safe_token}";
let pkg = null;
let comments = [];          // [{clip_id, name, text, ts}]
let activeClipId = null;
const STORED_NAME_KEY = 'derush_share_name_' + TOKEN;

function escapeHtml(s) {
    return String(s||'').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}
function tcStr(sec, fps) {
    fps = fps || 25;
    if (sec < 0) sec = 0;
    const h = Math.floor(sec/3600), m = Math.floor((sec%3600)/60), s = Math.floor(sec%60), f = Math.floor((sec%1)*fps);
    const pad = n => String(n).padStart(2,'0');
    return `\${pad(h)}:\${pad(m)}:\${pad(s)}:\${pad(f)}`;
}
function userById(uid) {
    return (pkg.users || []).find(u => u.id === uid) || {name: uid, color: '#999'};
}
const CAT_ICON = {'3':'⭐⭐⭐','2':'⭐⭐','1':'⭐','T':'🎨','S':'🎵','D':'📌','X':'❌'};

async function load() {
    try {
        const r = await fetch(`?action=get_share&token=\${TOKEN}`);
        if (!r.ok) {
            const e = await r.json().catch(()=>({}));
            document.getElementById('root').innerHTML = `<div class="error-page">😕 \${escapeHtml(e.error || 'Lien invalide ou expiré')}</div>`;
            return;
        }
        pkg = await r.json();
        await loadComments();
        render();
        // Auto-refresh des commentaires toutes les 30s pour voir les retours en quasi-temps réel
        setInterval(refreshComments, 30000);
    } catch(e) {
        document.getElementById('root').innerHTML = `<div class="error-page">⚠️ Erreur de chargement : \${escapeHtml(e.message)}</div>`;
    }
}

async function loadComments() {
    try {
        const r = await fetch(`?action=get_comments&token=\${TOKEN}`);
        if (r.ok) {
            const d = await r.json();
            comments = d.comments || [];
        } else if (r.status === 403) {
            // PHP pas à jour : action get_comments tombe dans le check de clé.
            // Affiche un warning discret pour aider au diagnostic.
            console.warn('get_comments → 403 : derush_sync.php probablement pas à jour sur le serveur');
        }
    } catch(e) { console.warn('loadComments failed', e); }
}

async function refreshComments() {
    const prevLen = comments.length;
    await loadComments();
    if (comments.length !== prevLen && activeClipId) {
        renderCommentsForClip(activeClipId);
    }
}

function commentsForClip(clipId) {
    return comments.filter(c => c.clip_id === clipId).sort((a,b) => (a.ts||'').localeCompare(b.ts||''));
}

function renderCommentsForClip(clipId) {
    const list = document.getElementById('clipCommentsList');
    if (!list) return;
    const cs = commentsForClip(clipId);
    if (!cs.length) {
        list.innerHTML = '<div style="color:var(--dim);font-size:0.82em;font-style:italic;">Aucun commentaire pour le moment.</div>';
        return;
    }
    list.innerHTML = cs.map(c =>
        `<div class="comment-item"><div class="head"><span class="name">\${escapeHtml(c.name||'Anonyme')}</span><span class="ts">\${escapeHtml((c.ts||'').replace('T',' ').slice(0,16))}</span></div><div class="text">\${escapeHtml(c.text||'')}</div></div>`
    ).join('');
}

function render() {
    const clipsByDay = {};
    pkg.clips.forEach(c => {
        const d = c.day || 'Sans jour';
        (clipsByDay[d] = clipsByDay[d] || []).push(c);
    });
    const dayKeys = Object.keys(clipsByDay).sort();
    let sidebarHTML = '';
    for (const d of dayKeys) {
        sidebarHTML += `<div class="day-header">\${escapeHtml(d)}</div>`;
        for (const c of clipsByDay[d]) {
            const thumb = c.thumb_b64 ? `<img class="thumb" src="data:image/jpeg;base64,\${c.thumb_b64}">` : `<div class="thumb"></div>`;
            const ratings = topRating(c.id);
            sidebarHTML += `<div class="clip-row" data-id="\${escapeHtml(c.id)}" onclick="select('\${escapeHtml(c.id)}')">
                \${thumb}
                <div class="info">
                    <div class="name">\${escapeHtml(c.stem || c.filename || c.id)}</div>
                    <div class="sub">\${escapeHtml(c.camera || '')} · \${tcStr(c.duration_sec, c.fps)}</div>
                    \${ratings ? `<div class="rating">\${ratings}</div>` : ''}
                </div>
            </div>`;
        }
    }
    document.getElementById('root').innerHTML = `
        <header>
            <h1>🎬 \${escapeHtml(pkg.name)}</h1>
            <span class="meta">Review externe · \${pkg.clips.length} clips</span>
        </header>
        <div class="layout">
            <aside>\${sidebarHTML}</aside>
            <main id="clipPanel"><div class="placeholder">Sélectionnez un clip à gauche pour voir les annotations.</div></main>
        </div>`;
}

function topRating(clipId) {
    const stars = new Set();
    for (const uid in pkg.notes) {
        const r = (pkg.notes[uid]?.[clipId] || {}).rating;
        if (r === '3' || r === '2' || r === '1') stars.add(r);
    }
    if (stars.has('3')) return '⭐⭐⭐';
    if (stars.has('2')) return '⭐⭐';
    if (stars.has('1')) return '⭐';
    return '';
}

function select(clipId) {
    activeClipId = clipId;
    document.querySelectorAll('.clip-row').forEach(el => el.classList.toggle('active', el.dataset.id === clipId));
    renderPanel();
}

function renderPanel() {
    const c = pkg.clips.find(x => x.id === activeClipId);
    if (!c) return;
    // 4 previews HD 640×360 dédiés (générés côté serveur avec lanczos + q=3),
    // fallback sur le strip 12-frames si previews indisponibles (anciens packages).
    let strip = '';
    if (Array.isArray(c.previews_b64) && c.previews_b64.length) {
        strip = `<div class="strips4">` + c.previews_b64.map(b64 =>
            `<div class="strip4-frame"><img src="data:image/jpeg;base64,\${b64}" loading="lazy"></div>`
        ).join('') + `</div>`;
    } else if (c.strip_b64) {
        // Compat ancien package : extrait 4 frames via CSS background-position
        const stripUrl = `data:image/jpeg;base64,\${c.strip_b64}`;
        const srcFrames = [0, 4, 8, 11];
        strip = `<div class="strips4">` + srcFrames.map(i => {
            const pct = (i * 100 / 11).toFixed(2);
            return `<div class="strip4-frame" style="background-image:url(\${stripUrl});background-size:1200% 100%;background-position:\${pct}% 0;"></div>`;
        }).join('') + `</div>`;
    } else {
        strip = `<div class="strip"></div>`;
    }
    // Markers + notes par user
    let markersHTML = '', notesHTML = '';
    const allMarkers = [];
    for (const uid in (pkg.notes || {})) {
        const cn = pkg.notes[uid]?.[c.id]; if (!cn) continue;
        const u = userById(uid);
        // Note globale + tags + rating
        const rating = cn.rating, stars = CAT_ICON[String(rating)] || '';
        const tags = (cn.tags || []).map(t => `<span class="tag">\${escapeHtml(t)}</span>`).join('');
        const noteText = (cn.notes || '').trim();
        if (rating || tags || noteText) {
            notesHTML += `<div class="note-card" style="border-left-color:\${u.color}">
                <div class="author">\${escapeHtml(u.name)} \${stars ? `<span class="rating">\${stars}</span>` : ''}</div>
                \${tags ? `<div class="tags">\${tags}</div>` : ''}
                \${noteText ? `<div class="text">\${escapeHtml(noteText)}</div>` : ''}
            </div>`;
        }
        for (const m of (cn.markers || [])) {
            allMarkers.push({...m, _user: u});
        }
    }
    allMarkers.sort((a,b) => (a.time||0) - (b.time||0));
    for (const m of allMarkers) {
        const icon = CAT_ICON[String(m.cat)] || '·';
        markersHTML += `<div class="marker-item">
            <span class="tc">\${escapeHtml(m.tc || tcStr(m.time, c.fps))}</span>
            <span class="cat">\${icon}</span>
            <div class="body">
                <div class="who" style="color:\${m._user.color}">\${escapeHtml(m._user.name)}</div>
                \${m.desc ? `<div class="desc">\${escapeHtml(m.desc)}</div>` : ''}
            </div>
        </div>`;
    }
    const panel = document.getElementById('clipPanel');
    const storedName = localStorage.getItem(STORED_NAME_KEY) || '';
    panel.innerHTML = `
        <div class="clip-header">
            <div style="flex:1;min-width:300px;">
                <div class="title">\${escapeHtml(c.stem || c.filename || c.id)}</div>
                <div class="technical">\${escapeHtml(c.camera || '')} · TC \${escapeHtml(c.tc_in||'')} · \${tcStr(c.duration_sec, c.fps)} · \${escapeHtml(c.resolution||'')}</div>
            </div>
        </div>
        \${strip}
        \${notesHTML ? `<div class="section"><h3>📝 Notes de l'équipe</h3><div class="notes-list">\${notesHTML}</div></div>` : ''}
        \${markersHTML ? `<div class="section"><h3>📍 Markers</h3><div class="markers-list">\${markersHTML}</div></div>` : ''}
        <div class="section">
            <h3>💬 Commentaires</h3>
            <div class="comments-list" id="clipCommentsList"></div>
            <div class="comment-form">
                <input type="text" id="commentName" placeholder="Votre nom" maxlength="80" value="\${escapeHtml(storedName)}">
                <textarea id="commentText" placeholder="Votre commentaire sur ce clip…" maxlength="2000"></textarea>
                <button onclick="submitComment()">Envoyer</button>
                <span id="commentStatus" style="margin-left:10px;"></span>
            </div>
        </div>`;
    renderCommentsForClip(c.id);
}

async function submitComment() {
    const name = document.getElementById('commentName').value.trim();
    const text = document.getElementById('commentText').value.trim();
    const status = document.getElementById('commentStatus');
    status.textContent = '';
    if (!text) { status.className = 'err'; status.textContent = 'Texte requis.'; return; }
    if (!activeClipId) return;
    // Mémorise le nom localement pour ne pas le retaper à chaque commentaire
    if (name) localStorage.setItem(STORED_NAME_KEY, name);
    try {
        const r = await fetch(`?action=add_comment&token=\${TOKEN}`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({clip_id: activeClipId, name: name || 'Anonyme', text}),
        });
        const d = await r.json();
        if (d.ok) {
            status.className = 'ok'; status.textContent = '✓ Envoyé';
            document.getElementById('commentText').value = '';
            // Refresh la liste immédiatement pour voir son propre commentaire
            await loadComments();
            renderCommentsForClip(activeClipId);
            setTimeout(() => { status.textContent = ''; }, 3000);
        } else {
            status.className = 'err'; status.textContent = d.error || 'Erreur';
        }
    } catch(e) {
        status.className = 'err'; status.textContent = 'Erreur réseau';
    }
}

load();
</script>
</body>
</html>
HTML;
}
