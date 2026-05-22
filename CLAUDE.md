# DERUSH TOOL — Guide Claude

Outil de dérushage vidéo multi-utilisateurs. Serveur Python + UI HTML monofichier.

## Fichiers
- `derush_server.py` — serveur HTTP Python (~1850 lignes)
- `derush_app.html` — UI web complète CSS+HTML+JS (~2000 lignes)
- `derush_launcher.py` — launcher avec tray icon (pystray) pour package installable
- `derush_setup.html` — wizard de configuration initiale (dark UI, 3 étapes + champs sync)
- `derush_sync.php` — script PHP à déposer sur hébergement web pour la sync cloud
- `derush.spec` — spec PyInstaller pour build Windows/macOS
- `build_windows.bat` / `build_mac.sh` — scripts de build
- `requirements.txt` — dépendances Python (pystray, Pillow, pyinstaller)
- `derush_config.json` — config (créé par setup wizard, à côté de l'exécutable)
- `projects/` — données projets JSON (`<id>.derush.json`)
- `projects/backups/<pid>/` — backups versionnés (10 derniers)
- `waveforms/` — cache JSON des formes d'onde (`<clip_id>.json`)
- `thumbnails/` — cache JPEG des miniatures + strips de scrubbing
- `GUIDE.html` — notice utilisateur complète

## Lancer le serveur
```
# Mode développement direct
python derush_server.py
# → http://localhost:8765

# Mode launcher (avec tray icon + ouverture navigateur auto)
python derush_launcher.py

# Build package installable
build_windows.bat    # Windows → dist/DerushTool/DerushTool.exe
bash build_mac.sh    # macOS   → dist/DerushTool.app
```

## Config système (derush_config.json)
Créé par le wizard `/setup` ou manuellement :
```json
{
  "configured": true,
  "projects_dir": "/path/to/projects",
  "waveforms_dir": "/path/to/waveforms",
  "thumbnails_dir": "/path/to/thumbnails",
  "backups_dir": "/path/to/projects/backups",
  "ffmpeg": "ffmpeg",
  "ffprobe": "ffprobe",
  "port": 8765,
  "sync_url": "https://example.com/derush_sync.php",
  "sync_key": "secret"
}
```
Variables globales : `APP_DIR`, `BUNDLE_DIR` (PyInstaller: `sys._MEIPASS`), `PROJECTS_DIR`, `WAVEFORMS_DIR`, `THUMBNAILS_DIR`, `BACKUPS_DIR`, `FFMPEG`, `FFPROBE`, `PORT`, `IS_CONFIGURED`, `SYNC_URL`, `SYNC_KEY`.

Sync runtime : `_sync_status` (dict: configured/online/last_sync/error), `_sync_lock` (threading.Lock).

## derush_server.py — Fonctions clés

| Fonction | Rôle |
|----------|------|
| `tc_to_seconds(tc_str, fps)` | TC "HH:MM:SS:FF" → secondes |
| `seconds_to_tc(sec, fps)` | secondes → TC string |
| `seconds_to_rational(sec, fps)` | secondes → "frames/fpsS" pour FCPXML |
| `get_lan_ip()` | IP LAN via socket (pour partage réseau) |
| `_load_config()` / `save_config(data)` | lecture/écriture `derush_config.json` |
| `ffprobe_metadata(filepath)` | metadata via ffprobe — retourne TOUS les format_tags |
| `scan_media_folder(root_path)` | scan récursif + TC + caméra depuis métadonnées + tech metadata |
| `parse_sony_xml(xml_path)` | retourne dict `{tc_in, duration_sec, model, iso, aperture, shutter_angle, focal_length}` |
| `find_proxy(root, clip_path)` | cherche proxy dans Sub/Proxy |
| `compute_thumbnail(file_path, clip_id, offset_sec)` | ffmpeg → JPEG 160px → cache `thumbnails/` |
| `compute_strip(file_path, clip_id, duration_sec, n=12)` | N frames en threads parallèles → PIL → JPEG horizontal 320×180px/frame → `<clip_id>_strip12.jpg` |
| `compute_waveform_peaks(file_path, num_buckets=800)` | ffmpeg → PCM s16le 4000Hz → RMS normalisé → liste floats |
| `export_fcpxml(project, filter_config)` | export FCPXML 1.8 pour DaVinci (supporte filtres) |
| `export_subclips_fcpxml(project, pre_roll, post_roll, filter_config)` | chaque marker → subclip court |
| `export_edl(project)` | export EDL classique (CMX3600) |
| `export_markers_edl(project)` | export EDL marqueurs DaVinci |
| `export_csv(project)` | export CSV |
| `export_report_html(project)` | rapport HTML auto-contenu |
| `import_edl(edl_text, user_id)` | import EDL → marqueurs |
| `project_health(proj, pid)` | rapport santé projet (médias, TC, annotations, export, infra) |
| `save_project(pid, data)` | sauvegarde + backup versionné (10 derniers dans `projects/backups/<pid>/`) |
| `merge_projects(local, remote)` | fusionne remote dans local — notes par user_id (sans conflit), discussions par timestamp |
| `sync_project(pid)` | pull remote → merge → push → save local → retourne `{ok, message}` |
| `sync_all_projects()` | appelle sync_project pour chaque `.derush.json` dans PROJECTS_DIR |
| `_sync_background_thread()` | thread daemon : détecte reconnexion (poll 90s), sync auto sur reconnexion + toutes les 10 min |
| `run(open_browser=False)` | lance ThreadedHTTPServer + _sync_background_thread (appelé par `__main__` et `derush_launcher`) |
| `DerushHandler` | handler HTTP (do_GET, do_POST) |

## Détection caméra — priorité
1. **Sidecar XML Sony** `<Device modelName="ILME-FX6"/>` — source la plus fiable
2. **Tags ffprobe** : `model`, `Model`, `com.apple.quicktime.model`, `com.apple.quicktime.make`
3. **Nom de dossier** (après `IMAGE/`) — fallback si aucune métadonnée

Fix byte-reversal FX6 : `'FX6' in camera.upper()` (couvre ILME-FX6, FX6V, etc.)

## Points techniques critiques

### PyInstaller — fichiers statiques
`APP_DIR = Path(sys.executable).parent` = dossier du .exe  
`BUNDLE_DIR = Path(sys._MEIPASS)` = `_internal/` où sont les fichiers data  
**`derush_app.html` doit être servi depuis `BUNDLE_DIR`, pas `APP_DIR`.** (fix ligne do_GET `/`)  
`derush_setup.html` est déjà servi depuis `BUNDLE_DIR` — ok.

### PyInstaller — UnboundLocalError threading dans run()
**Ne jamais faire `import threading` à l'intérieur d'une fonction qui utilise aussi `threading` hors du bloc.**  
Python traite alors `threading` comme variable locale dans toute la fonction, y compris avant l'import → `UnboundLocalError`.  
Fix appliqué dans `run()` : supprimer le `import threading` redondant dans le bloc `if open_browser:` (threading est déjà importé en haut du fichier).

### PyInstaller — fenêtres console subprocess
Tous les appels `subprocess.run()` utilisent `creationflags=_NO_WINDOW` pour éviter les flashs de fenêtre cmd.  
```python
_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
```

### FCPXML — TC source
`<asset start=tc_in_rational>` DOIT être la vraie TC source du fichier (pas `0s`).
DaVinci compare contre la TC embarquée MXF → mismatch = erreur "timecode extents".
Les marqueurs FCPXML sont en espace source-TC : `frame_num = tc_in_frames + offset_frames`.

### FCPXML — notes globales / rating (pas de marker au début du clip)
Les notes globales et étoiles ne génèrent **plus** de `<marker>` au début du clip (confusant dans DaVinci).  
À la place, elles sont placées dans l'attribut `note` de l'`<asset-clip>` : visibles dans l'inspecteur DaVinci sans polluer la timeline.  
Format : `"[Sébastien] ⭐⭐⭐ — texte de la note globale"`.

### FCPXML — marqueurs X (à couper)
Les marqueurs X définissent des zones à supprimer. L'export génère des sous-clips au lieu d'un clip entier :
- **0 X** → clip complet `[(0, dur)]`
- **1 X à T** → `[(0, T)]` — coupe jusqu'à la fin
- **2 X à T1, T2** → `[(0, T1), (T2, dur)]` — retire la section centrale
- **3 X à T1, T2, T3** → `[(0, T1), (T2, T3)]`
- **N X (pair)** → N/2 zones supprimées, section finale conservée
- **N X (impair)** → dernier X coupe jusqu'à la fin

Chaque segment devient un `<asset-clip>` séparé dans la spine FCPXML avec `start` et `duration` ajustés. Les markers de contenu ne sont inclus que s'ils tombent dans le segment conservé.

### EDL Marqueurs DaVinci (export_markers_edl)
Format spécifique pour : clic droit timeline → Timelines → Import → Timeline Markers from EDL
```
TITLE: nom_markers
FCM: NON-DROP FRAME

001  001      V     C        HH:MM:SS:FF HH:MM:SS:FF HH:MM:SS:FF HH:MM:SS:FF
 |C:ResolveColorYellow |M:texte label |D:1
```
- Reel toujours "001"
- Source TC = Record TC = position dans la timeline séquence (pas TC source clip)

### Couleurs marqueurs EDL
| Cat | Couleur app | ResolveColor |
|-----|-------------|--------------|
| 3 (⭐⭐⭐) | #fcd34d jaune | ResolveColorYellow |
| 2 (⭐⭐) | #a78bfa violet | ResolveColorPurple |
| 1 (⭐) | #9ca3af gris | ResolveColorCream |
| T (image) | #3b82f6 bleu | ResolveColorSky |
| S (son) | #10b981 vert | ResolveColorGreen |
| D (note) | #f59e0b ambre | ResolveColorSand |

### Waveform
- `compute_waveform_peaks()` : ffmpeg → raw PCM s16le @4000Hz → struct.unpack → RMS par bucket → normalisation
- Cache dans `waveforms/<clip_id>.json`
- Endpoint GET retourne `{"peaks": [...], "cached": bool}`

### Thumbnails & Contact Strip (scrub hover)
- `compute_thumbnail()` : ffmpeg `-ss offset -vframes 1 -vf scale=160:-1` — cache `<clip_id>.jpg`
- `compute_strip(n=12)` : N frames en threads parallèles à 320×180px → PIL assemble en JPEG horizontal → `<clip_id>_strip12.jpg`
- Survol de la sidebar : CSS `background-position: -${frameIdx * 260}px 0` sur le strip pour simuler la scrubbing sans requêtes réseau
- Race condition gérée par `_activeHoverClipId` (global JS) : `onload` du strip vérifie si la souris est encore sur ce clip
- Pre-génération au chargement du projet via `_pregen` (queue, max 3 concurrent)

### Markers timeline — interactions
- `selectedMarkerId` (string) : ID du marker sélectionné (stable après re-sort, contrairement à l'index)
- Clic sur un pin → sélection (anneau blanc CSS + highlight `.marker-row.selected`)
- Drag sur un pin → `mousedown` → `mousemove` (in-place DOM, pas de re-render) → `mouseup` met à jour `m.time`/`m.tc` + re-sort + `renderMarkers()`
- Seuil de déclenchement du drag : **8px** (évite les déplacements accidentels au clic)
- `Delete`/`Backspace` : supprime `selectedMarkerId` avec confirm
- `Escape` : désélectionne
- Clic sur la piste (hors pin) : désélectionne
- `timeToTC(t, fps)` : helper JS pour convertir secondes → "HH:MM:SS:FF"
- Pins avec dessin (`m.drawing`) → classe CSS `has-drawing` → forme **losange** (`::before` rotate 45°) au lieu du cercle
- Tooltip (`data-label`) tronqué à 48 caractères avec `…`
- Clic sur la zone vidéo (`.player-area` ou `#player`) → `togglePlay()`

### Rating toggle
`setRating(r)` : si `String(cur) === String(r)` → met à null (toggle off). Même comportement avec les touches 1/2/3/X.

### Tags — points techniques
- `tagsDisplay` div a `display:contents` → les chips sont enfants directs du flex-wrapper parent
- `onclick` des chips : **utiliser des guillemets simples** `onclick="removeTag('${t.replace(/'/g,"\\'")}')"` — `JSON.stringify()` génère des guillemets doubles qui cassent l'attribut HTML
- `undo()` doit appeler `renderTags()` pour rafraîchir l'affichage après annulation
- `.note-area` a `overflow-y: auto` pour que la section Tags reste accessible si les notes sont longues
- `#clipNotes` a `height: 72px` (pas `flex:1`) pour que les Tags soient toujours visibles sans scroll

### Sync cloud (derush_sync.php)
- PHP côté serveur, stocke JSON dans `derush_data/<pid>.derush.json`, backups dans `derush_data/backups/<pid>/`
- Auth par clé secrète `?key=SECRET` en query string
- GET → download, POST → upload (avec backup auto, 10 derniers)
- Merge strategy : `notes` = union par `user_id` (local gagne), `discussions` = union par `ts` (timestamps ISO), `users` = union par `id`
- Pas de conflit possible : chaque user_id n'écrit que ses propres notes

### Discussions (replies sur markers)
Stockées séparément des notes dans `proj['discussions']` pour éviter les conflits avec les sauvegardes locales.
```json
{
  "discussions": {
    "<clip_id>": {
      "<marker_id>": [{"user_id":"...","user_name":"...","color":"#...","text":"...","ts":"ISO"}]
    }
  }
}
```
Chaque marker a un champ `id` (hex aléatoire 8 chars) généré côté client à la création.

## Structure données projet (JSON)
```json
{
  "name": "DRIFT_CLUB",
  "root_path": "D:/...",
  "users": [{"id":"abc123","name":"Sébastien","password_hash":"...","color":"#a78bfa","root_path":"...","is_admin":true}],
  "clips": [{
    "id":"J02_ILME-FX6_DRIFT_avril0010",
    "filename":"DRIFT_avril0010.MXF",
    "camera":"ILME-FX6", "day":"J02",
    "tc_in":"12:28:15:17", "duration_sec":91.96, "fps":25,
    "iso":"800", "aperture":"f/2.8", "shutter_angle":"172.8°", "focal_length":"50mm",
    "proxy_url":"/proxy/..."
  }],
  "notes": {
    "<user_id>": {
      "<clip_id>": {
        "rating": "3",
        "notes": "texte global",
        "status": "valide",
        "tags": ["golden hour", "émotionnel"],
        "markers": [{"id":"a3f7b2c1","tc":"00:01:23:12","time":83.48,"cat":"3","desc":"SUPER PLAN","drawing":null}]
      }
    }
  },
  "discussions": {
    "<clip_id>": {
      "<marker_id>": [{"user_id":"...","user_name":"Léa","color":"#60a5fa","text":"Oui mais le son ?","ts":"2026-05-11T..."}]
    }
  }
}
```

## derush_app.html — Globals JS clés
- `currentProjectId`, `clips`, `allNotes`, `allDiscussions`, `activeClip`, `currentSession`, `currentProject`
- `activeFilter`, `activeSearch` — état des filtres sidebar
- `seenClipIds` — clips déjà ouverts
- `undoStack` — pile d'annulation (illimitée)
- `lastSavedHash` — hash JSON pour détecter les changements avant auto-save
- `waveformPeaks` — peaks audio du clip actif
- `pollingInterval` — ID du setInterval pour le sync local (60s)
- `_syncPollInterval` — ID du setInterval pour le statut de sync cloud (30s)
- `currentSpeed` — vitesse de lecture courante (1, 1.25, 1.5, 2)
- `selectedMarkerId` — ID (string) du marker sélectionné sur la timeline, null si aucun
- `_activeHoverClipId` — clip_id du clip survolé pour éviter les race conditions du strip
- `_pregen` — `{q: [], n: 0, max: 3}` — queue de pré-génération des thumbnails

## derush_app.html — Fonctions JS clés

| Fonction | Rôle |
|----------|------|
| `renderClipList()` | sidebar avec thumbnails+strip, en-têtes de jour, filtres, search texte, dots équipe |
| `selectClip(c)` | charge clip, affiche tech-meta, applique currentSpeed, appelle loadWaveform + renderTags |
| `setSpeed(rate)` | applique `video.playbackRate`, met à jour les boutons actifs |
| `setRating(r)` | toggle : si déjà actif → null, sinon → r |
| `addMarker(cat, desc, drawing)` | ajoute marker avec `id` unique |
| `renderMarkers()` | liste (avec selectedMarkerId) + pins timeline (drag via mousedown) + replies |
| `timeToTC(t, fps)` | secondes → "HH:MM:SS:FF" |
| `renderTags()` | affiche les tags du clip actif comme chips cliquables |
| `handleTagInput(e)` | Entrée ou virgule → ajoute tag dans allNotes + renderTags |
| `removeTag(tag)` | supprime tag avec pushUndo |
| `renderMultiUser()` | panneau "Avis des autres" : rating + note + markers + replies |
| `submitReply(btn, clipId, markerId)` | POST reply → refresh discussions |
| `loadWaveform(clip)` | fetch /waveform/, stocke peaks, appelle drawWaveform |
| `drawWaveform()` | dessine sur canvas dans timeline-bar |
| `startNotesPolling()` | sync local toutes les 60s — allNotes autres users + allDiscussions |
| `startSyncPolling()` | poll GET /api/sync/status toutes les 30s → met à jour le badge sync |
| `triggerSync()` | POST /api/sync/now → recharge notes si ok → met à jour badge |
| `pollSyncStatus()` | GET /api/sync/status → _updateSyncUI() |
| `_updateSyncUI(st)` | met à jour dot (vert/rouge/gris) + label du bouton Sync |
| `showUserMgmt()` | ouvre modal gestion utilisateurs |
| `renderUsersList()` | liste les users avec bouton ✏️ |
| `startEditUser(uid)` | pré-remplit le formulaire avec les données de l'utilisateur |
| `resetUserForm()` | remet le formulaire en mode "Ajouter" |
| `saveUser()` | add_user ou edit_user selon nuEditId |
| `rescanProject(btn)` | POST /scan, rafraîchit clips + dropdowns |
| `pushUndo()` / `undo()` | pile d'annulation illimitée |
| `saveNotes(silent)` | compare hash, POST si changement |
| `openExportModal()` | stats validateur + modal export |
| `openHealthModal()` | fetch /health, affiche rapport dans modal 🩺 |
| `renderHealth(h)` | construit HTML du rapport santé (5 sections) |
| `cycleStatus()` | null → arevoir → valide |
| `timelineSeek(e)` | seek + désélectionne marker si clic sur piste (hors pin) |

## Endpoints API
```
GET  /api/projects
GET  /api/me
GET  /api/browse                                   (tkinter folder picker)
GET  /api/project/<id>/clips
GET  /api/project/<id>/notes
GET  /api/project/<id>/discussions
GET  /api/project/<id>/config
GET  /api/project/<id>/health                      (rapport santé → 5 sections JSON)
GET  /api/project/<id>/export/fcpxml|edl|markers_edl|csv|subclips_fcpxml|report_html
GET  /api/project/<id>/thumbnail/<clip_id>         (cache thumbnails/)
GET  /api/project/<id>/thumbnail/<clip_id>?t=N     (thumbnail à offset N secondes)
GET  /api/project/<id>/strip/<clip_id>?n=12        (contact strip N frames)
GET  /api/project/<id>/waveform/<clip_id>          (cache waveforms/)
GET  /api/sync/status                              (configured/online/last_sync/error)
GET  /api/setup/status                             (état config : ffmpeg, LAN IP, dirs)
GET  /setup                                        (sert derush_setup.html)
GET  /proxy/<rel_path>                             (streaming vidéo)
POST /api/login
POST /api/logout
POST /api/setup                                    (sauvegarder derush_config.json + reload live, inclut sync_url/sync_key)
POST /api/project/open                             (créer projet + scan)
POST /api/project/<id>/add_user
POST /api/project/<id>/edit_user                   (admin: modifier nom/mdp/couleur/chemin d'un user)
POST /api/project/<id>/scan                        (rescan → retourne clips[])
POST /api/project/<id>/notes                       (sauvegarder annotations user)
POST /api/project/<id>/reply                       (ajouter reply sur marker)
POST /api/project/<id>/config
POST /api/project/<id>/import                      (importer EDL)
POST /api/sync/now                                 (sync immédiate tous les projets → {ok, results})
```

### Réponse /api/project/<id>/health
```json
{
  "media":    {"total":N, "with_proxy":N, "without_proxy":["stem",...], "missing_source":["stem",...], "zero_duration":["stem",...]},
  "timecode": {"with_tc":N, "without_tc":["stem",...], "fps_distribution":{"25":N}, "majority_fps":25, "wrong_fps":["stem",...]},
  "annotations": {"users":N, "clips_rated":N, "total_markers":N, "out_of_range":[{"clip":"stem","tc":"HH:MM:SS:FF"}]},
  "exports":  {"special_char_clips":["stem",...], "out_of_range_markers":[...], "clips_no_tc":["stem",...]},
  "infrastructure": {"last_save_mins_ago":N, "backup_count":N, "ffmpeg_ok":true, "ffprobe_ok":true}
}
```

### Réponse /api/sync/status
```json
{"configured": true, "online": true, "last_sync": "2026-05-12T10:30:00", "error": null}
```

## Workflow DaVinci Resolve
1. **📥 FCPXML** → DaVinci : File > Import > Timeline
2. **📥 Markers EDL** → clic droit sur la timeline → Timelines → Import → Timeline Markers from EDL

## Architecture multi-utilisateurs

### Mode réseau local (recommandé — tous les PCs allumés)
- 1 seul PC fait tourner DerushTool.exe (le serveur)
- Les autres PCs ouvrent un navigateur sur `http://<ip-lan>:8765`
- L'IP LAN s'affiche dans le wizard et en console au démarrage

### Mode autonome avec sync cloud
- Chaque PC a sa propre installation DerushTool + son propre DerushTool.exe
- `derush_sync.php` déposé sur un hébergement web commun (`sebastiendelahaye.be/derush_sync.php`)
- Clé sync : `drift2026` (hardcodée dans `SYNC_KEY` et dans le PHP déployé)
- Config dans `derush_config.json` : `sync_url` + `sync_key`
- Sync automatique au démarrage, à la reconnexion (détection 90s), et toutes les 10 min
- Merge sans conflit : chaque user_id n'écrit que ses propres notes
- Médias sur disques durs locaux — chaque user configure son propre `root_path`

## Système de profil global (depuis mai 2026)

Chaque machine a **un seul profil** stocké dans `%APPDATA%\DerushTool\derush_profile.json` :
```json
{"username": "Sébastien", "password_hash": "sha256hex"}
```

- Endpoint `GET /api/profile` → `{exists: bool, username: str}`
- Endpoint `POST /api/profile/create` → crée le profil (1 seul par machine)
- Login `/api/login` : vérifie username+password contre le profil local
- Si pas de profil → redirige vers `/setup`

### Session model
```python
SESSIONS[token] = {
    'username': 'Sébastien',
    'name': 'Sébastien',          # alias backward compat
    'user_id': 'Sébastien',       # alias backward compat
    'color': '#a78bfa',
    'root_path': '',
    'project_id': None,
    'is_admin': False,
}
```
`user_id` = alias de `username` pour compatibilité avec l'ancien code.

### user_note_key helper
```python
def user_note_key(u):
    return u.get('id') or u.get('username') or u.get('name', '')
```
Résout la divergence entre anciens users (`id`) et nouveaux (`username`).

## Système de clés d'invitation (authorize_user flow)

1. **Admin** → `POST /api/project/<pid>/authorize_user` avec `{username, color, is_admin}`
   - Ajoute l'user dans `proj['users']` avec un `invite_key` (8 chars uppercase aléatoire)
   - Retourne `{invite_key: "AB3X9KP2"}`
2. **Collaborateur** → `POST /api/sync/join_with_key` avec `{project_id, invite_key}`
   - Télécharge le projet depuis le cloud sync
   - Valide que `username` de session correspond à un user autorisé avec cette invite_key
   - Supprime `invite_key` (usage unique), sauvegarde localement, push sync
3. **Entrée workspace** → `POST /api/project/enter` avec `{project_id}`
   - Vérifie que l'user existe dans le projet ET que `invite_key` est absent (= déjà rejoint)
   - Met à jour SESSIONS avec `color`, `is_admin`, `root_path` du projet
   - Retourne `{ok: true, user: {...session...}}`

## Chemin local des rushs (root_path par user)
- Stocké dans `proj['users'][i]['root_path']` pour chaque user
- Endpoint `POST /api/project/<pid>/set_root_path` : met à jour user + session live
- Au premier accès au workspace : si `root_path` vide → modal de saisie du chemin
- Bouton dans la sidebar pour modifier le chemin (⚙️ ou dédié)

## Heartbeat / auto-shutdown
```python
_last_heartbeat = _time.time()
_HEARTBEAT_TIMEOUT = 12  # secondes

def _heartbeat_watcher():
    _time.sleep(20)   # grace period au démarrage
    while True:
        _time.sleep(3)
        if _time.time() - _last_heartbeat > _HEARTBEAT_TIMEOUT:
            os._exit(0)
```
- Frontend envoie `POST /api/heartbeat` toutes les 5s
- Si l'onglet est fermé → plus de heartbeat → server s'arrête après ~12s
- Bouton ⏻ dans l'UI → `POST /api/shutdown` → server s'arrête après 300ms

## PyInstaller — APP_DIR vs BUNDLE_DIR
```python
if getattr(sys, 'frozen', False):
    APP_DIR = Path(os.environ.get('APPDATA', str(Path.home()))) / 'DerushTool'
    APP_DIR.mkdir(exist_ok=True, parents=True)
    BUNDLE_DIR = Path(sys._MEIPASS)
else:
    APP_DIR = Path(__file__).parent
    BUNDLE_DIR = APP_DIR
```
- `APP_DIR` = données utilisateur (`config`, `profile`, `projects/`, etc.) → **persiste entre builds**
- `BUNDLE_DIR` = fichiers read-only bundlés (`derush_app.html`, `derush_setup.html`) → `_internal/`
- `derush_app.html` et `derush_setup.html` servis depuis `BUNDLE_DIR`, jamais `APP_DIR`

## Endpoints API (complet à jour)
```
GET  /api/projects
GET  /api/me
GET  /api/profile
GET  /api/browse                                   (tkinter folder picker)
GET  /api/project/<id>/clips
GET  /api/project/<id>/notes
GET  /api/project/<id>/discussions
GET  /api/project/<id>/config
GET  /api/project/<id>/health
GET  /api/project/<id>/export/fcpxml|edl|markers_edl|csv|subclips_fcpxml|report_html
GET  /api/project/<id>/thumbnail/<clip_id>
GET  /api/project/<id>/strip/<clip_id>?n=12
GET  /api/project/<id>/waveform/<clip_id>
GET  /api/project/<id>/invite_key/<username>       (admin: récupère la clé d'invitation)
GET  /api/sync/status
GET  /api/setup/status
GET  /setup
GET  /proxy/<rel_path>

POST /api/login
POST /api/logout
POST /api/heartbeat                                (reset auto-shutdown timer)
POST /api/shutdown                                 (arrêt propre du serveur)
POST /api/profile/create
POST /api/setup
POST /api/project/open                             (créer projet + scan)
POST /api/project/enter                            (entrer dans un projet)
POST /api/project/<id>/authorize_user              (admin: ajouter user + générer invite_key)
POST /api/project/<id>/set_root_path               (user: définir chemin local des rushs)
POST /api/project/<id>/scan
POST /api/project/<id>/notes
POST /api/project/<id>/reply
POST /api/project/<id>/config
POST /api/project/<id>/import
POST /api/sync/now
POST /api/sync/join_with_key                       (collaborateur: rejoindre via invite_key)
WS   /ws?token=<session_token>                     (WebSocket collaboration temps réel)
```

## Fonctionnalités avancées (ajoutées mai 2026)

### J/K/L Shuttle
Implémenté en JS pur (pas d'API browser). L réaccélère 1x→2x→4x (playbackRate), K stoppe, J joue en arrière (HTML5 ne supporte pas `playbackRate < 0`).

**Rétro lecture** : RAF loop qui seekBack à chaque frame :
```javascript
let _jklSpeed = 0, _jklRevRaf = null, _jklRevLast = null;
function _jklStartRev(rate) {
    // requestAnimationFrame → v.currentTime -= Math.abs(rate) * dt
}
```
Nettoyage dans `doLogout()` : `_jklStopRev(); _jklSpeed = 0;`

### WebSocket — Collaboration temps réel

**Côté serveur (derush_server.py)** :
- WebSocket RFC 6455 implémenté manuellement (pas de lib externe) dans `DerushHandler`
- Détection : `Upgrade: websocket` dans do_GET → `_handle_ws_upgrade(qs)`
- Auth : token en query param (`?token=xxx`) — impossible de setter des headers custom en browser
- Globals : `_ws_clients: dict[pid → [(sock, token)]]`, `_ws_clients_lock`
- `_ws_broadcast(pid, msg, exclude_token)` : envoie un JSON à tous les clients du projet sauf l'expéditeur
- Frames envoyées après : save notes (`notes_updated`) et après reply (`discussion_updated`)
- Opcode 8 (close) ou 9 (ping/pong) gérés proprement

**Côté client (derush_app.html)** :
```javascript
function startWebSocket() {
    const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
    _ws = new WebSocket(`${proto}//${location.host}/ws?token=${currentSession.token}`);
    _ws.onmessage = async (e) => { /* rechargement notes/discussions selon msg.type */ };
    _ws.onclose = () => { _ws = null; if(currentProjectId) setTimeout(startWebSocket, 6000); };
}
```
- Appelé dans `enterWorkspace()`, stoppé dans `doLogout()`
- Reconnexion automatique toutes les 6s en cas de drop

### Permissions granulaires (rôles)

3 rôles : `admin`, `annotator`, `viewer`
- Stocké dans `proj['users'][i]['role']` + `session['role']`
- Backward compat : si `role` absent, dérivé de `is_admin` (True → admin, False → annotator)
- Formulaire d'invitation : `<select id="nuRole">` (admin/annotator/viewer)
- Côté serveur dans `authorize_user` : `role = body.get('role', 'annotator')`

```javascript
function applyRoleUI(role) {
    // viewer : masque clipNotes, tagInput, popupConfirmBtn, ratingBtns (opacity 0.4)
    // !admin : masque gestion users, bouton rescan
}
```
Appelé dans `enterWorkspace()` avec `currentSession.role`.

### Comparaison multi-clips (Compare overlay)

Bouton "⚡ Comparer" → overlay plein écran fixe (`z-index: 150`) avec 2 slots côte à côte.

**Structure HTML** :
```
#compareOverlay > .compare-grid > [.compare-slot × 2]
  .compare-slot : header (select + TC + ⏯) | video-area | compare-timeline | compare-info
```

**Timeline compare** :
- `.compare-timeline` : 52px de haut, track positionné à 40px (laisse 26px au-dessus pour les markers)
- Markers 13×13px (tous les annotateurs du projet, pas seulement l'user courant)
- `cmpSeek(slot, e)` : utilise le rect du `cmpTrack` (pas du container) pour alignement pixel-perfect avec les pins
- Mise à jour de la tête : `updateCmpTc(slot)` → `cmpProg${slot}.style.width` + `cmpHead${slot}.style.left`
- `renderCmpMarkers(slot)` : parcourt `Object.values(allNotes)` et place un pin par marker

**Sync** : `_cmpSync` (bool) → quand un slot scrube, l'autre saute au même `currentTime`
- Info panel : hauteur fixe 90px (scroll) pour garder les deux vidéos à la même hauteur
- Markers dans info panel cliquables → seek vers `m.time`

**Globals JS** :
```javascript
let _cmpSync = false, _cmpClips = [null, null];
```
Nettoyage : `closeCompare()` appelé dans `doLogout()`

### Preview LUT (.cube) — Canvas 2D

**Implémentation** : Canvas 2D pur (abandonne WebGL — trop dépendant des drivers Windows/ANGLE).

**Algorithme** :
```javascript
_lutCtx.drawImage(v, 0, 0, w, h);          // vidéo → canvas (GPU)
const img = _lutCtx.getImageData(0,0,w,h); // readback CPU
// nearest-neighbour LUT lookup per pixel
for each pixel: idx = (bi*sz² + gi*sz + ri) * 3; → ld[idx]*255
_lutCtx.putImageData(img, 0, 0);            // CPU → canvas (GPU)
```
- Résolution max 480px de large pour les perfs (scalé par CSS sur l'affichage)
- RAF loop continue (pas de stop sur pause) — canvas recalculé en temps réel
- `_lutCtx = null` réinitialisé à chaque changement de fichier

**Parsing .cube** : `_parseCube(text)` lit ASCII `LUT_3D_SIZE N` puis les triplets float.

**Globals JS** :
```javascript
let _lut = null, _lutEnabled = false, _lutRaf = null, _lutCtx = null;
```

**Flow utilisateur** :
1. `📂 LUT` → `<input type="file" accept=".cube">` → `onLUTFileSelected`
2. `🎨 LUT` → `toggleLUT()` → `enableLUT(on)` — toggle on/off
3. Badge `LUT` affiché sur la vidéo quand actif

## CSS — compare-timeline layout

```css
.compare-timeline { height: 52px; }
.compare-timeline .cmp-tl-track { top: 40px; } /* laisse 26px au-dessus */
.compare-timeline .cmp-tl-head  { top: 40px; width: 13px; height: 13px; }
.compare-timeline .cmp-pin::before { top: 6px; width: 13px; height: 13px; }
/* hover: dot grossit 13→16px + anneau blanc */
.compare-info { height: 90px; overflow-y: auto; } /* fixe pour aligner les vidéos */
```

---

## Multicam — détection TC avec décodeur LTC (mis à jour 17-18 mai 2026)

**Évolution depuis le pivot du 17 mai** : on a gardé "pas de méthode audio xcorr/PHAT pour le matching" (ces approches étaient effectivement peu fiables). Mais on a ajouté un **décodeur LTC** (Linear Timecode audio) qui transforme le BZZZZ caractéristique encodé sur une piste audio en un vrai TC frame-accurate. Le matching reste TC, mais on a maintenant **deux sources de TC** :
- `clip['ltc_tc_in_sec']` : TC décodé depuis le LTC audio (préféré quand dispo, frame-accurate)
- `clip['tc_in']` : tag `format.timecode` de ffprobe (fiable pour FX6 jam-syncée via SDI, **faux pour FS5** dont l'horloge interne dérive)

`_clip_tc_seconds(clip)` choisit automatiquement le meilleur des deux. `_tc_pair_lag` et `_temporal_candidate` l'utilisent.

**Résultat sur DRIFT** : avant décodage LTC = 11 groupes détectés (FX6↔FX6 seulement). Après = nettement plus, paires FS5↔FX6 fiables (le LTC FS5 s'aligne avec le format.timecode FX6 si même multiprise).

### Constantes (`derush_server.py`)
```python
_MC_TC_GRACE = 5.0   # secondes de slack sur le test d'overlap TC
_FFMPEG_MAX_CONCURRENT = max(2, min(8, (os.cpu_count() or 4) // 2))
```
Plus de cache fingerprint, plus de seuils audio xcorr/GCC.

### Décodeur LTC (`derush_server.py`)
| Fonction | Rôle |
|----------|------|
| `_ltc_extract_pcm(file_path, channel=0, max_sec=8, sample_rate=48000)` | extrait 1 canal audio mono en int16 PCM via ffmpeg (`pan=mono\|c0=cX`) |
| `_ltc_decode_pcm(pcm, sample_rate=48000, fps=25, min_consecutive_frames=3)` | décode biphase mark LTC, sync word `0011111111111101`, 80 bits/frame. Retourne le TC au **début du PCM** en secondes, ou `None` |
| `_clip_tc_seconds(clip)` | helper : retourne `ltc_tc_in_sec` si dispo, sinon `tc_to_seconds(tc_in)` |
| `_ltc_proxy_path(clip, project)` | résout le path local du proxy MP4 (cherche dans `users[].root_path`) |
| `decode_project_ltc(project, pid, progress_cb, force)` | itère tous les clips, stocke `clip['ltc_tc_in_sec']` |
| `_decode_ltc_job(pid, force)` | wrapper background thread |

**Algorithme de décodage** (à connaître si on doit le modifier) :
1. ffmpeg → PCM int16 mono 48 kHz du canal L du proxy
2. Détection zero crossings → liste d'intervalles entre transitions (en samples)
3. Pour chaque intervalle : long (~bit_period) = '0', deux courts consécutifs (~bit_period/2) = '1'
4. **Validation de cohérence** : exiger `min_consecutive_frames=3` frames LTC consécutives où chaque `tc[k+1] = tc[k] + 1/fps` (mod 24h). Évite les faux sync words sur bruit ambiant.
5. **Correction d'offset** : le 1er sync valide peut être à 1-3s dans le PCM (LTC met du temps à locker). On calcule la position en samples du sync via `bit_to_iv` + `zc[]`, puis `TC_début_clip = TC_au_sync - offset_seconds`.

**Pièges du décodeur** :
- Avant le fix : retournait le 1er sync trouvé sans valider la cohérence → faux positifs sur bruit (chaise qui grince donnait un TC bidon). Bug observé sur Clip0037 J04 qui donnait 16:52:10 (faux) au lieu de 16:59:09 (réel), causant un mauvais appariement multicam.
- LTC sur la **piste 2** des MXF FS5 J02-J05 (pas piste 1 comme on aurait pu croire). Sur les FS5 J07-J11 par contre c'est piste 1. Détection auto par Crest factor < 2 dans `transcode_proxies.sh`.
- FX6 n'ont **pas de LTC dans l'audio** — elles reçoivent le TC via SDI/jam-sync et l'écrivent dans `format.timecode` (qui est fiable pour les FX6).
- Clips sans LTC : J02 Clip0001, J04 Clip0016/0029, J06 entier (multiprise jamais branchée). Renvoient `None`, fallback `format.timecode` (qui est souvent faux pour la FS5) → ces clips ne formeront pas de paires multicam, à caler à la main dans DaVinci.

### Fonctions BWF (lecture seule, pour le viewer)
| Fonction | Rôle |
|----------|------|
| `_read_bwf_bext_direct(file_path)` | parse RIFF/WAVE en Python, lit `fmt` + `bext` (TimeReference + OriginationDate) + `data` |
| `_read_bwf_tc_ffprobe(file_path)` | fallback via ffprobe (W64, formats exotiques) |
| `read_bwf_tc(file_path)` | dispatcher → dict `{tc_in_sec, duration_sec, sample_rate, channels, origination_date}` |
| `scan_son_dir(son_dir)` | récursif → liste `[{id, filename, path, tc_in_sec, duration_sec, origination_date, ...}]` |
| `_clip_origination_date(clip)` | extrait `YYYY-MM-DD` depuis `creation_date` ou regex sur `id`/`path` |
| `_bwf_origination_date(af)` | normalise depuis `audio_clips`, fallback lecture à la volée |
| `_bwf_candidates_for_clips(...)` | retourne BWF qui CONTIENNENT strictement les clips (grace ±2s) ET match la date, triés par compacité — utilisé seulement par `/group_bwf` pour le playback |

### Fonctions multicam (`derush_server.py`)
| Fonction | Rôle |
|----------|------|
| `_tc_pair_lag(clip_a, clip_b)` | utilise `_clip_tc_seconds` (LTC prioritaire). Retourne `tc_b - tc_a` si overlap, sinon `None` |
| `_temporal_candidate(a, b)` | True si overlap TC strict via `_clip_tc_seconds` |
| `detect_multicam_groups(project, pid, progress_cb)` | itère les paires par jour, garde celles avec overlap TC, propage les lags par BFS, retourne les groupes avec `sync_method: 'tc'` |
| `_detect_multicam_job(pid)` | wrapper background pour `/multicam/detect`. Callback à 1 phase : `'correlate'` |

### Endpoints multicam + LTC (`derush_server.py`)
| Méthode | Route | Rôle |
|---------|-------|------|
| GET | `/api/project/<pid>/son` | retourne `{son_dir, count, audio_clips}` |
| POST | `/api/project/<pid>/scan_son` | body `{son_dir}` → scan + sauvegarde projet |
| GET | `/api/project/<pid>/multicam` | groupes validés + propositions |
| POST | `/api/project/<pid>/multicam/detect` | lance la détection (background job, polled) |
| GET | `/api/project/<pid>/multicam/status` | progression du job (phase `correlate` uniquement) |
| POST | `/api/project/<pid>/multicam/accept` | propose → groupe validé |
| POST | `/api/project/<pid>/multicam/reject` | supprime un groupe (proposal ou validé) |
| POST | `/api/project/<pid>/multicam/nudge` | sauvegarde nouveaux `offsets` du groupe |
| GET | `/api/project/<pid>/bwf_audio/<ac_id>` | streame le BWF (Range support, MIME audio/wav) |
| GET | `/api/project/<pid>/multicam/group_bwf?group_id=...` | renvoie le 1er BWF candidat qui couvre le groupe (basé sur `_clip_tc_seconds` = LTC prioritaire) |
| **POST** | **`/api/project/<pid>/decode_ltc/start`** | body `{force: bool}`. Lance le décodage LTC pour tous les clips du projet |
| **GET** | **`/api/project/<pid>/decode_ltc/status`** | polling : `{status, done, total, current, n_with_ltc, n_without_ltc, elapsed}` |
| **GET** | **`/api/project/<pid>/decode_ltc/summary`** | `{total, decoded, with_ltc, without_ltc, pending}` pour le label UI |
| (handler) | `_serve_audio(file_path)` | helper Range (206) ou complet (200) avec MIME `audio/wav` |
| (handler) | `_serve_video(file_path)` | maintenant gère `.LRV` avec MIME `video/mp4` (Chromium peut lire HEVC LRV si OS supporte) |

**Supprimés au pivot précédent** : `/multicam/refine`, `/multicam/manual_pair`, `/multicam/group_bwf_analyze`, `/multicam/group_bwf_offset`.

### Pièges & subtilités
- **`_temporal_candidate` est strict** : pas de fallback `same-day-folder`, pas de fallback `creation_date`. Si une caméra a un TC aberrant, ses clips ne formeront aucune paire — c'est volontaire (l'utilisateur sait que c'est cassé sur ces jours et préfère un trou plutôt qu'un faux match).
- **`detect_multicam_groups` — skip déjà-groupés** : exclut tout clip présent dans `multicam_groups` OU `multicam_proposals`. Permet de re-run sans casser les offsets tunés manuellement.
- **`_detect_multicam_job` — APPEND, pas REPLACE** : `proj['multicam_proposals'] = existing + new_groups`. Conserve les propositions précédentes.
- **`_bwf_candidates_for_clips`** : reste utilisée par `/group_bwf` pour trouver le BWF de référence à jouer dans le viewer. Filtre par couverture TC stricte + match `origination_date`. Premier candidat = le plus compact (BWF qui démarre juste avant et finit juste après les clips).
- **`_mcCurrentGroupTime` — fix mini-loop fin de primary** : quand le primary atteint sa fin pendant la lecture, son `currentTime` plateau → `_mcDriftCorrect` rebobine les secondaires en boucle. Fix : si `pri.currentTime >= priDur - 0.1 && v.playing`, prendre la base de temps sur l'angle in-range le plus avancé. Sinon les secondaires plus longs que le primary bouclent visuellement sur quelques frames toutes les ~1s.

### Format groupe multicam stocké (`projects/<pid>.derush.json`)
```json
{
  "multicam_groups": [
    {
      "id": "mc_a1b2c3d4",
      "clip_ids": ["id_a", "id_b"],
      "offsets": {"id_a": 0, "id_b": 11.080},
      "score": 1.0,
      "sync_method": "tc",
      "detected_at": "2026-05-17T14:32:11"
    }
  ],
  "audio_clips": [
    {
      "id": "TECHCHECKT14",
      "filename": "TECHCHECKT14.WAV",
      "path": "/path/to/BWF/TECHCHECKT14.WAV",
      "tc_in_sec": 62051.0,
      "duration_sec": 1820.5,
      "sample_rate": 48000,
      "channels": 2,
      "origination_date": "2026-04-08"
    }
  ]
}
```

### UI viewer multicam (`derush_app.html`)
**Toolbar (id) :**
- `mcPlayBtn` · `mcViewerTime` · `mcViewerHint`
- `mcBwfBtn` (🔊 Son ingé / 🔇 Son ingé) — toggle playback BWF de référence
- `mcLayoutBtn` (⊞ Grille / ⊡ Primaire)
- `mcNudgeStep` (select : frame / 100ms / 500ms / 1s)
- Boutons `_mcNudgeStep(-1)` / `_mcNudgeStep(+1)` — nudge clips secondaires
- `mcNudgeDisplay` / `mcNudgeSaveBtn` (💾) — sauvegarde nouveaux `offsets`

**État JS (`_mcView`) :**
```js
{
  group, angles: [{cid, clip, normOff, duration, vidEl, wrapEl, _inRange}],
  groupDur, primaryIdx, playing, raf, drift, lastT, layoutMode, nudgeDelta,
  bwfAudio, bwfOffset, bwfEnabled, bwfFilename,
}
```

**Fonctions clés JS :**
- `openMcViewer()` — crée elements, charge BWF via `/group_bwf` (1 candidat, pas de sélecteur)
- `closeMcViewer()` — cleanup vidéos + audio BWF + masque le bouton BWF
- `_mcCurrentGroupTime()` — `primary.currentTime + primary.normOff`
- `_mcSeekGroup(T)` — seek tous les angles + BWF à `bwfOffset + T`
- `_mcStartRaf()` — RAF tick : update timeline, mute logic (`useBwf = bwfAudio && bwfEnabled`), gestion in-range secondaires
- `_mcDriftCorrect()` (interval 1s) — corrige drift video + BWF (resync si > 200ms d'écart)
- `_mcNudge(sign, unitSec)` — shift `normOff` des secondaires (sauf primary)
- `_mcNudgeStep(sign)` — wrapper, lit le sélecteur de pas
- `_mcToggleBwf()` — toggle `bwfEnabled` (mute/unmute caméras + play/pause BWF)

### Workflow utilisateur
1. **🎶 Décoder LTC** (1 fois par projet, ~quelques minutes en background) — récupère le vrai TC depuis l'audio des FS5/caméras LTC-équipées. Stocke `clip['ltc_tc_in_sec']`.
2. **🔍 Lancer la détection** → groupes TC (instantané, basé sur LTC+format.timecode via `_clip_tc_seconds`)
3. **Validation** → Accepter dans la modale (passe de proposal à validated, sélection multi avec shift+clic)
4. **Viewer** → 🔊 Son ingé pour entendre le BWF de référence pendant qu'on switch les angles
5. **Nudge clips si besoin** → ◄ / ► à droite du sélecteur de pas pour ajuster + 💾

### Audio FS5 mono R (LTC silencing)
Les proxys FS5 ont **L=LTC, R=micro** (mapping fait par `transcode_proxies.sh`). Lire le stereo brut fait entendre le BZZZZ. On utilise **WebAudio API** pour router R sur les deux canaux output, à la fois dans :
- Le **viewer multicam** : `_mcAttachAudio(a)` par angle FS5 (créé une fois par session viewer, disposed dans `closeMcViewer`)
- Le **player principal** : `_attachPlayerAudio()` + `_setPlayerMonoR(c.ltc_tc_in_sec != null)` dans `selectClip`

Détection FS5 = `clip.ltc_tc_in_sec != null` (proxy de "ce clip a un LTC, donc c'est une FS5 jam-syncée"). FX6 et GoPro restent en stereo natif.

`_attachPlayerAudio` crée un graph WebAudio une seule fois par video element (singleton via `video._audioAttached`). 2 routes via GainNodes : stereo natif (gain stéréo) + mono R dupliqué (gain monoR). `_setPlayerMonoR(true/false)` toggle les gains.

`openMcViewer()` met `mainPlayer.pause()` au début pour ne pas garder le son du clip principal qui continue en parallèle.

## Optimisations performance (17-18 mai 2026)

Le user a constaté des lags, plantages, "écran noir vidéo figée" après 6-7 ouvertures du viewer multicam ou hover rapide sur GoPro. Multiples coupables identifiés et corrigés :

### Sémaphore globale ffmpeg
```python
_FFMPEG_MAX_CONCURRENT = max(2, min(8, (os.cpu_count() or 4) // 2))
_ffmpeg_sem = threading.BoundedSemaphore(_FFMPEG_MAX_CONCURRENT)
def _ffmpeg_run(cmd, timeout=30, ...):
    with _ffmpeg_sem:
        return subprocess.run(cmd, ...)
```
**Tous les subprocess ffmpeg du serveur** passent par `_ffmpeg_run`. ThreadedHTTPServer fanout illimité auparavant → un hover sur 20 clips déclenchait 240 ffmpeg simultanés et saturait la RAM/CPU.

### Déduplication des calculs en cours
```python
_compute_locks = {}  # key → threading.Event
def _dedupe_compute(key, fn, wait_timeout=120):
    # initiator runs fn; concurrent callers wait on Event
```
Wrappers : `compute_thumbnail`, `compute_thumbnail_scrub`, `compute_strip`. Évite que 2 requêtes simultanées sur le même clip lancent N×2 ffmpeg.

### compute_strip throttle interne
ThreadPoolExecutor(max_workers=3) au lieu de 12 threads simultanés. 12 frames mais en 4 batchs de 3. Combiné avec la sémaphore globale, plus jamais d'explosion RAM.

### compute_waveform_peaks numpy-isé
Avant : `struct.unpack` + boucle Python pure → tuple Python de millions d'int (300 MB-1 GB pour clip 1h+). Maintenant : `np.frombuffer` (zero-copy) + `.reshape(N,B).mean(axis=1)` (vectorisé). ~10× moins de RAM, ~100× plus rapide.

### `-analyzeduration 1M -probesize 5M -an` sur tous les compute_*
Sans ça, ffmpeg peut allouer >1 GB pour probe les fichiers GoPro HEVC ou MXF Sony exotiques avant même de seek. Avec ces limites, max ~50-100 MB.

### `_lighter_decode_source(file_path)`
Détecte les GoPro `GX*.MP4` → utilise le `GL*.LRV` à côté (proxy natif GoPro, HEVC 432p ~5-10 MB) pour générer les thumbnails. Le décodeur HEVC alloue ~10× moins de RAM sur 432p que sur 5K. **Pas de transcode**, juste un fichier déjà présent par la caméra.

### `find_proxy` détecte les LRV GoPro comme proxy_url
Si pas de Sub/ trouvé pour un GX*.MP4 mais un GL*.LRV existe à côté → proxy_url = chemin du LRV. `_serve_video` envoie MIME `video/mp4` pour les .LRV (Chromium peut lire HEVC LRV si OS supporte le codec).

### Cleanup WebAudio + video elements dans `closeMcViewer`
Avant : MediaElementSource gardait référence aux `<video>` → leak mémoire massif à chaque close/open. Maintenant :
- `disconnect()` de tous les nodes (source, splitter, merger, gain)
- `vidEl.removeAttribute('src'); vidEl.load()` (force libération buffers décodeur browser)
- `window._mcAudioCtx.close()` (libère définitivement l'AudioContext, recréé au prochain open)

Idem dans `closeCompare()` pour le viewer de comparaison.

## Wrapper Electron (POC Phase A, 18 mai 2026)

**Pourquoi** : la dépendance au browser tiers (Firefox/Chrome/Safari) cause des problèmes de portabilité, codecs (Firefox ne lit pas HEVC), et fuites mémoire qu'on ne peut pas contrôler. Electron embarque Chromium → comportement uniforme, codecs OS, contrôle fin.

**Structure** :
```
derush_tool/
  electron/
    package.json     # deps: electron ^33, electron-builder ^25
    main.js          # spawn python backend + BrowserWindow Chromium
    preload.js       # vide pour POC (sécurité tight)
```

**Comment ça marche** :
1. `npm.cmd start` (mode dev) → Electron spawn `python derush_server.py --no-browser`, poll `localhost:8765`, ouvre `BrowserWindow` dessus
2. Fermeture window → `stopBackend()` qui kill le subprocess Python
3. F12 = DevTools

**Phase B (à faire)** : `npm run build` → bundle Chromium + le `dist/DerushTool.exe` PyInstaller en un seul `DerushTool-Portable.exe` (~280 MB). Configuré dans `package.json` via `extraResources`. Nécessite que `dist/DerushTool.exe` soit présent (build PyInstaller au préalable).

**Le serveur Python a un flag `--no-browser`** (ajouté dans `__main__`) pour ne pas ouvrir Firefox quand lancé par Electron.

**Limitations Electron à connaître** :
- Binaire ~280 MB (vs 150 MB actuel)
- RAM baseline ~300-400 MB
- HEVC sur Windows : nécessite extension MS "HEVC Video Extensions" (gratuite via lien direct OEM)
- Build Mac depuis Windows = impossible (faut un Mac ou CI), mais l'app TOURNE sur Mac
- SmartScreen warning au 1er lancement si exe non signé (clic "Plus d'infos → Exécuter")

## Scripts utilitaires (racine projet)

| Fichier | Rôle |
|---------|------|
| `transcode_proxies.sh` | batch transcode FS5 MXF→MP4 H.264 720p NVENC. Détecte LTC par Crest, mapping L=LTC R=micro. 1× par projet, écrit dans `Sub/` à côté |
| `watch_ffmpeg.ps1` | monitore les processus ffmpeg en cours, affiche RAM + ligne de commande, alerte au-dessus d'un seuil (debug perf) |
| `test_ltc_decoder.py` | test standalone du décodeur LTC sur 6 cas connus (validation) |
| `_patch_gopro_proxy.py` | one-shot : patche les proxy_url GoPro dans le JSON projet pour pointer sur les LRV (évite un rescan complet) |
| `validate_multichunk.py`, `refonte.py`, `recover_orphans.py` | scripts d'archive d'expérimentations audio multicam (session précédente, ne plus utiliser, ne pas supprimer) |

---

# État au 19 mai 2026 — Tournée majeure (Phase B Electron → refactor modules → auto-update → bonus features)

## Versions et release

- Version courante : **0.2.0** (fichier `VERSION` à la racine, bundlé dans le PyInstaller)
- Première release distribuée : `DerushTool-Portable-0.2.0.exe` (183 MB) sur GitHub Releases
- Repo public : https://github.com/davebixby/derush-tool

## Système changelog visible dans l'app

- `CHANGELOG.md` à la racine (format Keep a Changelog, parsé par regex `## [X.Y.Z] — date`)
- Backend : `GET /api/version`, `GET /api/changelog` (helpers `_read_version()`, `_read_changelog()` dans derush_server.py)
- Frontend : `js/changelog.js` — modal auto-affichée au 1er launch après bump de version (compare `localStorage.derush_last_seen_version` à la version courante)
- Lien manuel « 📜 Nouveautés » dans le footer de l'écran projets
- Render markdown léger (`##`, `**bold**`, `` `code` ``, listes `-`)

## Auto-update via electron-updater + GitHub Releases

- Provider : GitHub (owner=davebixby, repo=derush-tool, public)
- `electron-updater` ^6.8 en dependency d'`electron/`
- `package.json` build config : `portable.unpackDirName: 'DerushTool'` (extract dir stable pour update), `publish: [{provider: 'github', owner, repo}]`
- `main.js` : `setupAutoUpdater()` appelé dans `app.whenReady()`, seulement si `app.isPackaged`. Check 5s après boot, download silent, dialog au quitAndInstall(false, true) quand prêt
- Workflow release documenté dans `RELEASE.md` (bump VERSION + electron/package.json, update CHANGELOG.md, pyinstaller, npm run release)
- **Piège Windows critique** : `GH_TOKEN` au niveau User PAS propagé aux subprocess npm. Toujours injecter explicitement avant `npm run release` :
  ```powershell
  $env:GH_TOKEN = [Environment]::GetEnvironmentVariable('GH_TOKEN', 'User')
  npm run release
  ```
- **Piège GitHub** : refuse de publier une release sur un repo sans aucun commit (« Repository is empty »). Push au moins un README avant la 1ère release.
- **Mode Développeur Windows requis** sur la machine de build : `winCodeSign-2.6.0.7z` contient des symlinks Unix darwin/ qu'electron-builder doit extraire. Activé via `ms-settings:developers`.

## Refactor monolithe HTML → modules JS (19 mai)

`derush_app.html` passe de **5077 → 3109 lignes** (-39%). 10 modules JS dans `js/` :

| Module | Lignes | Contenu |
|--------|--------|---------|
| `audio-bwf.js` | 256+ | `_attachPlayerAudio`, `_setPlayerMonoR`, `_routeBwfMultiChannel`, BWF single player, `selectClip` |
| `multicam-viewer.js` | 643 | 4-up viewer overlay (`openMcViewer`, `_buildMcLayout`, `_mcSeekGroup`, etc.) |
| `multicam-modal.js` | 450 | Modal détection + groupes (propositions/validés) |
| `compare.js` | 175 | Compare 2-clips overlay |
| `lut.js` | 354 | WebGL2 LUT + scope + settings |
| `share.js` | 132 | Lien de review |
| `changelog.js` | 77 | Modal nouveautés |
| `crash.js` | 47 | Viewer journal erreurs |
| `auto-detect.js` | 200+ | Scene change candidats |
| `session-live.js` | 180+ | Leader/follower WS |

**Pattern d'extraction** :
- Pas d'ES modules (casseraient les `onclick=""` inline). Juste `<script src="js/X.js"></script>` classique
- Toutes les fonctions / `let` top-level partagent le global lexical scope → accessibles via inline `onclick` et entre modules
- Server route : `/js/*.js` servi depuis `BUNDLE_DIR/js/` (résolution PyInstaller-aware via la route ajoutée dans `do_GET`)
- PyInstaller spec : bundle tous les `js/*.js` via `glob` (datas)
- Chargement HTML : `<script src>` AVANT le bootstrap final `<script>init(); _loadVersionAndChangelog();</script>` à la fin du body

## Tests E2E Playwright (`tests/`)

- 14 tests sur 5 fichiers : `smoke`, `auth`, `changelog`, `markers` (regression bug textarea), `drawing`
- Setup : `cd tests && npm install && npx playwright install chromium` puis `npm test`
- Credentials via env vars : `DERUSH_TEST_USER` (défaut: 'Sebastien'), `DERUSH_TEST_PASS` (vide = skip auth tests), `DERUSH_TEST_PROJECT` (défaut: 'Drift_Club')
- Playwright config : `webServer` spawn `python derush_server.py --no-browser`, baseURL `http://localhost:8765`
- **Couvre le bug textarea** : test `markers.spec.js > BUG REGRESSION : add → delete → re-add → textarea focusable` — vérifie `popupDesc` est `toBeFocused` après le cycle
- 14/14 passent en ~30 s (incluse extraction modules JS → pattern validé)

## Bug textarea popup — saga + fix définitif

**5 tentatives échouées** : reset défensif, replaceChild, pointer-events:none overlay, blur après delete, double RAF.

**Vrai coupable** : `confirm()` natif. Chromium garde un état « focus stealer prevention » après un dialog natif qui empêche le rendu du caret sur les inputs focusés ensuite. **Comportement non documenté, reproductible**.

**Fix** : suppression de TOUS les `confirm()` natifs (10 occurrences). Remplacés par toast non-bloquant `showToast(msg, kind, duration)` — composant CSS custom avec slide-in animation. `prompt()` aussi désactivé (Electron le retourne `null` silencieusement) → `saveDrawing` utilise désormais le popup marker existant avec stash `_pendingDrawing`.

## LUT preview WebGL2 (rewrite complet)

- Canvas 2D nearest-neighbour 480px → WebGL2 + `sampler3D` + `gl.LINEAR` filtering (trilinéaire HW gratuite)
- Pleine résolution vidéo (jamais downsamplée), zéro readback CPU, format `RGB16F` upload
- `_lutInitGL(canvas)` crée le contexte + program + texture 3D
- Fragment shader : `expo → LUT lookup centre voxels → mix intensité → satu Rec.709 → dithering`
- Dithering anti-banding : noise sub-pixel ±0.5/255 décorrélé par canal, varie par frame via `u_time`
- Scope par caméra : `_lutScope = {mode:'cameras'|'clip', cameras:[], clip_id:''}` persisté en `localStorage`
- 3 sliders panel : intensité (0–1), exposition (-2/+2 EV), saturation (0–2). Uniforms re-pushés à chaque slide.
- `selectClip` re-évalue le scope → enable/disable canvas automatiquement
- Bouton 🎨 LUT 3 états visuels : `lut-on` (accent + glow), `lut-off` (barré dim), `lut-not-applicable` (dim + label « hors scope »)
- Canvas a `object-fit: contain` pour matcher l'aspect ratio du `<video>` (aussi en contain)

## BWF multi-track + Son ingé sur player single

- Endpoint nouveau : `GET /api/project/<pid>/clip_bwf/<clip_id>` — trouve le BWF couvrant le TC du clip (réutilise `_bwf_candidates_for_clips`)
- Frontend : bouton 🔊 Son ingé apparaît auto quand un BWF est dispo pour le clip actif
- WebAudio routing : `_routeBwfMultiChannel(audio, ctx)` crée `ChannelSplitter(8)` + 2 `GainNodes` qui mixent toutes les pistes (1/3 atténuation) → mergerStéréo → destination
- Marche pour les 2 contextes : player single (`_playerAudioCtx`) et multicam viewer (`window._mcAudioCtx`)
- Cleanup propre via `_unrouteBwf(audio)` au changement de clip / close viewer
- Bouton son ingé visuel cohérent partout : `bwf-on` (vert éclatant + glow), `bwf-off` (barré dim)

## Markers : shapes différenciées + stacking vertical

CSS par catégorie :
- `1/2/3` (rating) → cercle
- `T` (problème image) → carré (`border-radius: 2px`)
- `S` (problème son) → triangle (`clip-path: polygon(50% 0, 100% 100%, 0 100%)`)
- `D` (note) → losange (`border-radius: 2px; rotate(45deg)`)
- `X` (à couper) → croix (2 pseudos rotated 45°/-45°)

**Stacking vertical** : markers proches dans le temps (< 22 px horizontal) s'empilent sur 3 niveaux (`--pin-top` CSS var, offsets 4 / 17 / 30 px). Pre-calcul dans `renderMarkers` via algo greedy par level. Timeline-bar passée de 64 → 88 px pour l'espace.

Labels : « Image » → « Problème image », « Son » → « Problème son » (icône ⚠️ au lieu de 👁️/🎵).

## Export Adobe Premiere XML

- Nouvelle fonction `export_xml_fcp7(project, filter_config)` dans derush_server.py
- Schéma : Final Cut Pro 7 XML Interchange Format v5 (`<xmeml version="5"><sequence>…`)
- Endpoint : `/api/project/<pid>/export/xml_fcp7?label=…&min_rating=N&cats=...&rejected=1`
- Même logique de découpe par markers X (zones à couper) que `export_fcpxml` : 1 `<clipitem>` par segment kept
- Markers content placés avec `<in>` = offset depuis début SOURCE FILE (pas du clipitem)
- 5 boutons dans le modal export (complet + 4 filtres rating/son/image)
- Compatible Premiere Pro CC 2017+

## Lien de review partagé (Frame.io light)

**Architecture** :
1. `POST /api/project/<pid>/share/create` → backend construit un « share package » (annotations + thumbs + 4 previews HD 640×360 par clip via `compute_share_previews()`, cachés en `_share[0-3].jpg`)
2. Upload via `derush_sync.php?action=create_share&token=ABC` (token random url-safe 12 chars)
3. URL publique : `https://host/derush_sync.php?view=share&token=ABC` → PHP rend une page HTML embarquée (CSS+JS inline) qui fetch le package via `?action=get_share`
4. Viewer : sidebar clips + détails (4 thumbs HD + markers + notes équipe) + formulaire commentaire
5. `POST ?action=add_comment&token=ABC` (token = auth, pas de clé)
6. Pull commentaires : `_share_pull_locks` per-pid + dédoublonnage rétroactif par `(ts, text)` (fix bug doublons ×N causé par concurrent polling)
7. Affichage Derush : section verte « 🔗 Retours externes » sous chaque clip dans le panneau « Avis des autres »

**Bug fix** : `since=None` envoyé à PHP devenait `'None'` string, comparaison `'2026-...' <= 'None'` alphanumérique = True → tous filtrés. Fix : `since = proj['share'].get('comments_last_pulled') or ''`.

**Détails serveur PHP étendus** : voir `derush_sync.example.php` (template avec `SECRET_KEY = 'CHANGEME'` placeholder) — le vrai `derush_sync.php` contient la clé hardcodée et est exclu du repo via `.gitignore`.

## Sync cloud hardening

- **Pull-on-enter** : `POST /api/project/enter` déclenche `sync_project(pid)` en background (non-bloquant)
- **Push debounced** : après chaque save de notes, schedule un sync 3 s plus tard via `_sync_push_timers[pid]` (`threading.Timer`). Les saves rapprochées reset le timer = 1 seul push par rafale d'éditions.

## Crash reporter

- `%APPDATA%\DerushTool\crashes.jsonl` (1 JSON ligne par crash)
- Python : `sys.excepthook` + `threading.excepthook` (Python 3.8+) → `_log_crash(entry)`
- JS : `window.addEventListener('error')` + `unhandledrejection` → POST `/api/crash` (throttle 500ms)
- Endpoints : `GET /api/crashes?limit=N`, `GET /api/crashes/clear`
- UI : lien « 🐞 Journal des erreurs » sur écran projets → modal avec liste (badge JS/PY, timestamp, message, URL+line, stacktrace dépliable)
- Module : `js/crash.js`

## Auto-détection de plans (scene change)

- Backend : `detect_scenes_for_clip(file_path, threshold)` appelle ffmpeg avec `-filter:v "select=gt(scene\,X),showinfo" -loglevel verbose`
- Dédup à 0.5 s pour bursts d'I-frames
- Background job `_auto_detect_job(pid, threshold, clip_ids)` — stocke candidats dans `proj['auto_detected'][clip_id] = {candidates, scanned_at, threshold}`
- Skip candidats proches (< 1 s) de markers existants pour pas dupliquer
- 4 endpoints :
  - `POST /api/project/<pid>/auto_detect/start` (body: threshold, clip_ids?)
  - `GET /api/project/<pid>/auto_detect/status`
  - `GET /api/project/<pid>/auto_detect`
  - `POST /api/project/<pid>/auto_detect/decide` (body: clip_id, candidate_id, status='accepted'|'rejected')
- Accept → crée un vrai marker D côté serveur
- Module frontend : `js/auto-detect.js`, candidats rendus comme losanges jaunes (`.timeline-autodetect-pin`)

**Bugs fixés** (à retenir) :
- `-loglevel info` masque les `showinfo` lines → 0 candidats. Faut `verbose`.
- Regex `r'pts_time:([0-9.]+)'` matche aussi `[graph -1 input...] ... pts_time: 0` → faux positif à t=0. Faut regex stricte : `r'\[Parsed_showinfo[^\]]*\][^\n]*pts_time:([0-9.]+)'`.
- Default threshold 0.25 (pas 0.4) pour les longs takes FX6.

## Session live (leader/follower)

- Backend : `_session_leaders[pid] = username` dict + lock
- Endpoints : `GET /api/project/<pid>/session/state`, `POST .../session/start_leading|stop_leading|action`
- WS broadcast types nouveaux : `session_state` ({leader}), `session_action` ({action, data, from})
- Frontend : `js/session-live.js`
  - State : `_sessionIsLeading`, `_sessionFollowing`, `_sessionLeader`
  - Anti-loop : `_sessionApplyingRemote` flag bloque le re-broadcast d'une action reçue
  - Hooks : `selectClip` → broadcast `select_clip`, listeners `play/pause/seeked/ratechange` sur le `<video>` (attach one-shot via `attachSessionVideoListeners`)
- Cleanup au logout : libère leadership (broadcasted)
- Bouton 🎬 4 états : « Diriger la session », « 👁 Suivre [name] », « ✓ Suit [name] », « 🛑 Arrêter de diriger »

## Endpoints API (état au 19 mai 2026)

### Nouveaux endpoints :
```
GET  /api/version
GET  /api/changelog
GET  /api/crashes
GET  /api/crashes/clear
GET  /api/project/<pid>/share/info
POST /api/project/<pid>/share/create
POST /api/project/<pid>/share/revoke
POST /api/project/<pid>/share/pull_comments
GET  /api/project/<pid>/clip_bwf/<clip_id>           (BWF couvrant un seul clip)
GET  /api/project/<pid>/auto_detect
GET  /api/project/<pid>/auto_detect/status
POST /api/project/<pid>/auto_detect/start
POST /api/project/<pid>/auto_detect/decide
GET  /api/project/<pid>/session/state
POST /api/project/<pid>/session/start_leading
POST /api/project/<pid>/session/stop_leading
POST /api/project/<pid>/session/action
POST /api/project/<pid>/export/xml_fcp7              (Adobe Premiere)
POST /api/crash
GET  /js/*.js                                         (sert les modules JS bundlés)
```

## Pièges critiques à retenir

1. **`confirm()`, `alert()`, `prompt()` natifs** dans Electron : `prompt` retourne `null`, `confirm` casse le focus state. Toujours utiliser toast custom.
2. **`GH_TOKEN` au niveau User** : pas propagé aux subprocess npm sur Windows. Injecter en session avant `npm run release`.
3. **Mode Développeur Windows** : requis pour electron-builder (symlinks darwin/).
4. **PyInstaller onedir** : 5× plus rapide que onefile au démarrage. `derush.spec` utilise `EXE(exclude_binaries=True) + COLLECT(...)`. `console=IS_WIN` : sur Mac `console=True` → binaire POSIX pur (pas de `.app` bundle, pas de `NSApplicationLoad()` / fenêtre Dock quand Electron le spawne headlessly). Les deux plateformes produisent un dossier COLLECT plat → `extraResources` **commun** (top-level) `../dist/DerushTool` → `DerushTool`. `main.js` attend `Resources/DerushTool/DerushTool.exe` (Win) et `Resources/DerushTool/DerushTool` (Mac, chmod 755 au runtime).
5. **`derush_sync.php` jamais commité** : contient `SECRET_KEY` hardcodée. Utiliser `derush_sync.example.php` template.
6. **Bundle `js/` dans PyInstaller** : `*([(str(p), 'js') for p in (ROOT / 'js').glob('*.js')])` dans datas du derush.spec.
7. **ffmpeg `showinfo`** : invisible en `-loglevel info`. Faut `verbose`. Et regex parsing doit être préfixée à `\[Parsed_showinfo` pour éviter faux positifs sur lignes graph debug.
8. **Tests E2E** : faire tourner avant tout refactor risqué. `cd tests && DERUSH_TEST_PASS=... npm test`.
9. **tkinter sur Mac** : doit tourner sur le main thread, hangue silencieux en worker thread. → `/api/browse` détecte `sys.platform == 'darwin'` et utilise `osascript` (`choose folder with prompt …`) à la place. Windows garde tkinter.
10. **Path resolution cross-platform** : `_resolve_relpath_tolerant(root, rel)` walk segment par segment avec tolérance numérique (`01↔1↔001`) + case-insensitive fallback. Indispensable quand un disque source est copié entre PCs et que les noms de slot perdent leur zéro de tête (rsync, robocopy parfois). Cache positif pour ne pas re-walker à chaque requête.
11. **Clé de notes dédoublée (`user_note_key` vs save)** : l'endpoint `POST /api/project/<id>/notes` sauve sous `s.get('user_id') or s.get('username')`, mais l'export FCPXML et le reste lisent via `user_note_key(u) = u.get('id') or u.get('username') or u.get('name')`. Si une session perd son `user_id`, les notes du même humain partent sous une 2e clé (`username`/`name`) que `user_note_key` n'atteint jamais → notes orphelines invisibles à l'export, suppressions de marqueurs appliquées au mauvais jeu. La clé de save doit être résolue via le user trouvé dans `project['users']` (donc identique à `user_note_key`), pas via la session brute. **Et l'UI indexe les notes par `currentSession.user_id`** — donc `/api/project/enter` pose `session['user_id'] = user_note_key(user)` pour que UI, `/notes` et export partagent exactement la même clé (sinon l'UI ne retrouve pas ses notes et les écrase à vide).
12. **IDs de clip orphelins après ré-import** : les `notes` sont indexées par `clip['id']`. Un re-scan / ré-import qui régénère les IDs de clip laisse les anciennes notes pointer dans le vide → marqueurs/ratings perdus silencieusement (jamais lus par l'export). Re-mapper par nom de fichier si récupération nécessaire.
13. **Verrou par projet (`_project_lock`, audit 22 mai 2026)** : `do_POST` détient `_project_lock(pid)` (RLock) pendant tout le dispatch d'une requête `/api/project/<pid>/…` → les écritures d'endpoints sont déjà sérialisées, inutile de re-verrouiller dedans. En revanche **tout code qui écrit un projet hors d'une requête `do_POST`** (job de fond, `threading.Timer`, thread) DOIT recharger le projet avec `with _project_lock(pid):` juste avant `save_project`, sinon il écrase les écritures concurrentes (lost update). `save_project` écrit de façon atomique (`.tmp` + `os.replace`) ; `load_project` est caché par (mtime, taille). Voir `AUDIT.md` §1.

# État au 19 mai 2026 (suite, soirée) — Distribution zip + fixes cross-PC + support Mac

## Refonte distribution Windows : portable .exe → zip
Le `.exe` portable d'electron-builder dézippe dans `%LOCALAPPDATA%\Temp\<id>\` à chaque lancement (1 min sur premier run à cause de Defender qui scanne 176 Mo). Switché en `target: zip` → user dézippe manuellement dans un dossier fixe → démarrage 3–5s, zéro self-extract.

`electron/package.json` :
```json
"win": { "target": [{ "target": "zip", "arch": ["x64"] }], "artifactName": "DerushTool-${version}-win.${ext}" }
```
Perte : plus d'auto-update (electron-updater zip-target supporté mais nécessite write-access au dossier).

## Bug saga : utilisateur supprimé qui revient via sync (tombstone)
1. **Symptôme initial** : créer un user, fermer l'app, relancer → user disparu.
2. **Cause** : le tombstone qu'on avait ajouté pour fixer la suppression (`deleted_users[]`) restait actif. Au prochain sync, `merge_projects` filtrait le user re-créé parce que son nom était toujours dans `deleted_users` (côté remote).
3. **Fix 1** (`authorize_user`) : à la (ré)autorisation d'un user, retirer son nom de `deleted_users` local.
4. **Fix 2** (`merge_projects`) : un user présent dans `users[]` local lève automatiquement le tombstone (`all_dead -= local_alive`) → propagation correcte au remote au prochain push.

## URL encoding pour sync (espaces, accents)
`_sync_url_for(pid)` faisait `f"...?key={SYNC_KEY}&project={pid}"` sans encoding. Un `pid` avec espace (« drift club ») crashe urllib avec `URL can't contain control characters`. Fix :
- `_urlquote(SYNC_KEY, safe='')` + `_urlquote(pid, safe='')`
- Validation locale du `pid` : `re.match(r'^[a-zA-Z0-9_\-]+$', pid)` avant l'appel → message clair « ID invalide, pas d'espaces ni accents »
- Messages d'erreur explicites : « Clé sync incorrecte. Vérifie SYNC_KEY dans ⚙️ Configuration » au lieu de « Erreur serveur sync (403) »

## Refonte UX du setup wizard
- **Bouton 📁 Parcourir…** ajouté à côté du champ « Dossier Projets » dans `derush_setup.html`. Appelle `/api/browse` (qui utilise tkinter sur Win, osascript sur Mac).
- **« Rejoindre un projet »** retiré de la page de login (contre-intuitif : on demande de se loguer ET on propose de rejoindre, mais rejoindre nécessite d'être loggé). Reste visible uniquement sur l'écran « Mes projets » après connexion.

## Feedback visuel pour les thumbnails (génération ffmpeg sur fresh install)
Sur un PC qui rejoint un projet, `THUMBNAILS_DIR` côté serveur est vide → ffmpeg génère 428 vignettes à la demande (~1s/clip via `.LRV` GoPro, ~2s/MXF). Sans feedback, l'utilisateur voit 428 cases vides pendant 5+ minutes.

Ajouts dans `derush_app.html` :
- **Skeleton shimmer** animé sur `.clip-thumb-wrap:not(.thumb-ready)::before` pendant la requête
- **Barre flottante** en bas-droite : « Génération des aperçus… 47 / 428 » avec barre violette qui se remplit. Fade out à 100%.
- **Placeholder ⚠ rouge** sur les vignettes en 404 (au lieu de l'icône image cassée du browser)
- **Spinner sur le player** (cercle violet rotatif + « Chargement… ») wire sur `onloadstart`, `onwaiting`, `oncanplay`, `onplaying`
- **Écran d'erreur vidéo** : si 404, affiche le chemin demandé + code HTTP + rappel sur le dossier des rushs

Compteur dédoublonnage : `_thumbState.done = Set<clip_id>` pour ne pas double-compter sur rerender.

## Résolveur de chemins tolérant aux variantes (le gros morceau)
**Cas typique** : SSD copié de PC1 → PC2 avec rsync/robocopy/drag-drop Explorer. Folders perdent leur zéro de tête (`IMAGE\01` → `IMAGE\2`). Le serveur ne trouvait plus aucun fichier → 404 pour TOUS les proxies/thumbnails.

`_resolve_relpath_tolerant(root, rel)` dans `derush_server.py` :
1. Fast path : essaie le chemin littéral (cas pas-de-problème)
2. Slow path : walk segment par segment. Pour chaque segment numérique, essaie : valeur littérale, sans zéro de tête (01→1, 002→2), avec zéro (1→01, 1→001).
3. Dernier recours : `iterdir()` + match case-insensitive (pour APFS case-sensitive ou disques externes formatés ailleurs).
4. Cache positif `_relpath_resolve_cache[(root, rel)]` thread-safe pour ne pas re-walker à chaque hit.

Appliqué partout : `/proxy/`, `/thumbnail/`, `/strip/`, `_ltc_proxy_path`, `_resolve_clip_local_path`.

## Support Mac (Apple Silicon arm64) — Phase initiale
Cross-build depuis Windows impossible (PyInstaller pas de cross-compilation, electron-builder a besoin d'outils Mac). Workflow : build sur le Mac mini M1 directement, distribution vers MBP M2 via zip + AirDrop.

**Fichiers créés/modifiés** :
- `derush.spec` : détecte `sys.platform == 'darwin'`, désactive UPX (incompatible code signing), génère un `BUNDLE(...)` produisant `DerushTool.app` (Mac standard bundle) avec Info.plist incluant les permissions `NSDesktopFolderUsageDescription`, `NSDocumentsFolderUsageDescription`, `NSRemovableVolumesUsageDescription`. Icône `.icns` au lieu de `.ico` sur Mac.
- `electron/main.js` : `backendCommand()` détecte `process.platform === 'darwin'` → lance `DerushTool.app/Contents/MacOS/DerushTool` au lieu de `DerushTool.exe`. En dev : `python3` au lieu de `python`.
- `electron/package.json` : ajout `mac: { target: zip arm64, icon: ../derush_icon.icns, identity: null, hardenedRuntime: false }`. Nouveau script `build:mac`.
- `build_mac.sh` : script bash auto qui vérifie Xcode CLT + Homebrew + Python3 + Node + ffmpeg/ffprobe (messages d'erreur clairs si manquant), copie `which ffmpeg`+`which ffprobe` à la racine pour bundling PyInstaller, génère `.icns` depuis `.png` via `iconutil`, crée venv Python, lance pyinstaller puis electron-builder.
- `BUILD_MAC.md` : guide complet français — install prérequis, transfert sources Windows→Mac, lancement build, contournement Gatekeeper (clic droit → Ouvrir), distribution vers MBP, troubleshooting détaillé.

**Fix critique** : `/api/browse` (folder picker) — tkinter doit tourner sur main thread sur Mac (sinon hang silencieux). Sur Mac, utiliser `osascript -e 'POSIX path of (choose folder with prompt "...")'` (NSOpenPanel natif via AppleScript). Win garde tkinter en worker thread.

**Compatibilité données cross-platform vérifiée** :
- `proxy_url` stocké avec `/` séparateurs → marche tel quel sur Mac
- `rel_path` stocké avec `\\` Windows → résolveur convertit en `/` avant walk
- `clip.path` absolu Windows → ignoré sur Mac, fallback automatique vers `rel_path` + resolveur tolérant
- `_resolve_relpath_tolerant` couvre les diffs `IMAGE\01` Win ↔ `IMAGE/2` Mac SSD copié

## Versionnage de la session
- 0.3.1 → 0.3.2 : URL encoding sync
- 0.3.2 → 0.3.3 : skeleton shimmer + barre progression thumbnails
- 0.3.3 → 0.3.4 : placeholders ⚠ + écran erreur vidéo
- 0.3.4 → 0.3.5 : résolveur de chemins tolérant + support Mac (spec/main.js/package.json/build_mac.sh/BUILD_MAC.md/osascript)

# État au 20-21 mai 2026 — Build Mac (premier build réel) + bug export FCPXML

## Build Mac : premier build effectif sur le Mac mini M1
Jusqu'ici le support Mac était seulement préparé côté Windows. Premier build réel lancé sur le Mac mini → plusieurs bugs découverts et corrigés en conditions réelles.

### Nouvel outil : `zip_for_mac.ps1` (racine projet, Windows)
Script PowerShell qui prépare le `.zip` des sources à transférer sur le Mac. `robocopy` vers un staging temp en excluant les dossiers d'artefacts (`dist/ build/ node_modules/ projects/ .git/ __pycache__/ thumbnails/ waveforms/ sync_fingerprints/`) et les binaires Windows `ffmpeg.exe`/`ffprobe.exe` (~300 Mo, inutiles sur Mac — `build_mac.sh` recopie les versions Homebrew). Puis `Compress-Archive`. Lit `VERSION` pour nommer le zip, vérifie la présence des fichiers clés avant compression. `package-lock.json` est gardé (recette pour `npm install`), `node_modules/` non.

### Fix `build_mac.sh` #1 — `cp ffmpeg` « Permission denied »
Les binaires Homebrew sont en lecture seule ; `cp` (BSD) recopie ce mode → au 2e build, `cp` ne peut plus écraser le fichier non-inscriptible → `Permission denied`, et `set -e` stoppe tout. Fix : `rm -f "$ROOT/ffmpeg" "$ROOT/ffprobe"` avant les `cp`.

### Fix `build_mac.sh` #2 — `electron-builder: command not found`
Le test `if [ ! -d "node_modules" ]` sautait `npm install` dès que le dossier existait, même vide/incomplet (run précédent interrompu) → `electron-builder` jamais installé. Fix : tester `if [ ! -x "node_modules/.bin/electron-builder" ]`.

### Fix `package.json` — `extraResources` par plateforme (backend `ENOENT`)
`extraResources` commun pointait `../dist/DerushTool` (dossier COLLECT). Sur Mac `main.js` lance `Resources/DerushTool/DerushTool.app/Contents/MacOS/DerushTool` — il attend le `.app` BUNDLE → `spawn ... ENOENT`, le backend Python ne démarre jamais (« Le serveur Python n'a pas démarré »). Fix : `extraResources` déplacé dans les blocs `win`/`mac` — `win` → `../dist/DerushTool` → `DerushTool` ; `mac` → `../dist/DerushTool.app` → `DerushTool/DerushTool.app`. Voir piège #4.

### Réseau studio : `npm install` bloqué (`UNABLE_TO_GET_ISSUER_CERT_LOCALLY`)
Le réseau du studio intercepte le TLS (proxy / inspection HTTPS) → npm rejette les certificats. `NODE_TLS_REJECT_UNAUTHORIZED=0` ne suffit **pas** : npm a son propre `strict-ssl` (défaut `true`) qui écrase la variable. Contournement : `npm config set strict-ssl false` (registre npm) **+** `export NODE_TLS_REJECT_UNAUTHORIZED=0` (téléchargement du binaire Electron) dans le même terminal. Plus propre : builder sur un partage de connexion (hotspot), sans interception. Documenté dans `BUILD_MAC.md` § dépannage.

## Bug export FCPXML — timeline réduite à 2 clips + marqueur supprimé qui revient
Diagnostic sur `projects/drift_club.derush.json`.

**Symptômes** : (1) l'export FCPXML ne contient que `Clip0002` + `Clip0004` alors que beaucoup de clips sont notés ; (2) un marqueur 3★ « TRES BEBBEBE » supprimé dans l'UI réapparaît dans DaVinci.

**Cause unique — identité dédoublée** (piège #11) : les `notes` du projet ont 4 clés (`6714b070`, `Sebastien`, `Paola`, `davebixby`) pour 3 users déclarés. L'user « Sébastien » (`id=6714b070`, `name=Sebastien`) a ses notes éparpillées entre `6714b070` et `Sebastien`. L'export ne lit que `user_note_key(u)` = `6714b070` → toutes les notes sous la clé `Sebastien` sont invisibles ; et la suppression de « TRES BEBBEBE » (faite côté session `Sebastien`) n'a jamais touché le marqueur réel, stocké sous `6714b070`. S'ajoute le piège #12 : des notes sous IDs de clip `J02_*` orphelins (re-import).

**Règle de sélection d'un clip dans la timeline FCPXML** (`export_fcpxml`, export par défaut sans filtre) : un clip est inclus si **au moins un user reconnu** a sur ce clip un marqueur, une note écrite, ou un rating 1/2/3 — et **exclu** si un user l'a noté **X** (X = rejet du clip entier). Documenté aussi dans `GUIDE.html` § Export.

**Correctif appliqué (22 mai 2026)** :
- **Notes fusionnées** : merge *data-aware* de `Sebastien` dans `6714b070`. Sur le seul vrai conflit (`J02_…FS5_Clip0002`, le clip « TRES BEBBEBE ») le jeu `Sebastien` récent l'emporte ; partout ailleurs on garde le jeu qui porte des données → **aucune perte**. Les 2 notes à IDs de clip orphelins (`J02_*` ré-import) sont supprimées. Clé `Sebastien` supprimée → clés finales : `6714b070`, `Paola`, `davebixby` (une par personne ; `6714b070` = compte de Sébastien, nom affiché « Sebastien »). Backup : `projects/drift_club.derush.PREMERGE-BACKUP.json`. Export FCPXML : 2 → 8 clips.
- **Endpoint `/notes` corrigé** : la clé de save est résolue via `find_project_user(proj, …)` + `user_note_key()` — strictement identique à ce que lit l'export. Plus de dédoublement possible (piège #11).
- Canonique retenue = `6714b070` (l'`id` du user, ce que `user_note_key` rend) plutôt que le texte `Sebastien` : pas de modif de l'objet user (qui porte `password_hash` + `id` admin) — moins risqué, et la clé interne est invisible côté UI.
