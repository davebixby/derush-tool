# DERUSH TOOL — Guide Claude

Outil de dérushage vidéo multi-utilisateurs. Serveur Python + UI HTML monofichier.

> **⚠️ Règle de documentation (à respecter à chaque changement)**
> À chaque modification du code ou d'une fonctionnalité, Claude **doit** mettre à jour les trois fichiers de documentation : `claude.md` (ce fichier — référence technique), `guide.html` (notice utilisateur) et `journal.html` (carnet de bord, ajouter une entrée datée). Ne jamais livrer un changement sans synchroniser ces trois fichiers.

## Fichiers
- `derush_server.py` — serveur HTTP Python (~1850 lignes)
- `derush_app.html` — UI web complète CSS+HTML+JS (~2000 lignes)
- `derush_launcher.py` — launcher avec tray icon (pystray) pour package installable
- `derush_setup.html` — wizard de configuration initiale (dark UI, 3 étapes + champs sync)
- `derush_sync.php` — script PHP à déposer sur hébergement web pour la sync cloud (gitignored, réel — `derush_sync.example.php` = template public)
- `derush_config.seed.json` — seed sync_url/sync_key (gitignored, réel — `derush_config.seed.example.json` = template public). Bundlé dans le build s'il existe sur la machine qui compile ; sert de valeur par défaut pour toute machine sans config existante (voir section dédiée plus bas)
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
- `pollingInterval` — ID du setInterval pour le sync local (15s)
- `_syncPollInterval` — ID du setInterval pour le statut de sync cloud (30s)
- `currentSpeed` — vitesse de lecture courante (1, 1.25, 1.5, 2)
- `selectedMarkerId` — ID (string) du marker sélectionné sur la timeline, null si aucun
- `_activeHoverClipId` — clip_id du clip survolé pour éviter les race conditions du strip
- `_pregen` — `{q: [], n: 0, max: 3}` — queue de pré-génération des thumbnails

## derush_app.html — Fonctions JS clés

| Fonction | Rôle |
|----------|------|
| `renderClipList()` | sidebar avec thumbnails+strip, en-têtes de jour, filtres, search texte, chips rating équipe |
| `selectClip(c)` | charge clip, affiche tech-meta, applique currentSpeed, appelle loadWaveform + renderTags |
| `setSpeed(rate)` | applique `video.playbackRate`, met à jour les boutons actifs |
| `setRating(r)` | toggle : si déjà actif → null, sinon → r |
| `addMarker(cat, desc, drawing)` | ajoute marker avec `id` unique |
| `renderMarkers()` | liste (avec selectedMarkerId) + pins timeline (drag via mousedown) + replies |
| `timeToTC(t, fps)` | secondes → "HH:MM:SS:FF" |
| `renderTags()` | affiche les tags du clip actif comme chips cliquables |
| `handleTagInput(e)` | Entrée ou virgule → ajoute tag dans allNotes + renderTags |
| `removeTag(tag)` | supprime tag avec pushUndo |
| `renderMultiUser()` | panneau "Avis des autres" : rating + note (+ fil de discussion forum) + markers (cliquables → seek, + replies) |
| `_muSeekMarker(time, e)` | clic sur un marker d'un collaborateur dans "Avis des autres" → `player.currentTime = time`. Ignore les clics dans `.mu-reply-form` imbriqué |
| `submitReply(btn, clipId, markerId)` | POST reply → refresh discussions |
| `loadWaveform(clip)` | fetch /waveform/, stocke peaks, appelle drawWaveform |
| `drawWaveform()` | dessine sur canvas dans timeline-bar |
| `startNotesPolling()` | sync local toutes les 15s — allNotes autres users + allDiscussions |
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
GET  /api/project/<id>/letterbox/<clip_id>         (bandes noires incrustées → {top,bottom,left,right})
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
POST /api/sync/pull                                (pull-only d'un projet, body {project_id} — poll auto)
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
GET  /api/project/<id>/letterbox/<clip_id>
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
POST /api/sync/pull                                (pull-only d'un projet, body {project_id})
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

### Disposition des contrôles du lecteur (refonte juin 2026, save déplacé juillet 2026)

Deux zones distinctes :
- **Barre du bas `.player-controls`** (sous la vidéo, au-dessus de la timeline) = transport + lecture : TC `#tcDisplay`, ◀5s/◀1s/⏯/1s▶/5s▶, 📌 Marker, 🖌 Dessin, ⤢ plein écran, 🔊 Son ingé (`#bwfBtn`), volume (`#volIcon`+`#volSlider`), spacer flex, groupe vitesses `1×/1.25×/1.5×/2×`, **💾 Sauver**, puis `#saveStatus` (flash de sauvegarde).
- **Barre flottante verticale `.player-toolbar`** (`#playerToolbar`) = tous les **outils/actions**, en colonne d'**icônes seules** (tooltips `title`), overlay en haut-droite de `.player-area` (`position:absolute; top:8px; right:8px; z-index:20`, fond translucide + blur) : ⚡ Comparer, 🎞 Cadre (+`#aspectMenu`), 🎨 LUT (`#lutBtn`), 📂 LUT, 🔄 Multi-cam, 🎬 Session (`#sessionBtn`), 📤 Exporter, 🔗 Partager, 🩺 Health, 📊 Stats, ⌨️ raccourcis, ☁️ Sync (`#syncBtn`, dot couleur uniquement — `#syncLabel` masqué).

**Points techniques** :
- Boutons à état dynamique passés en icône seule : `setAspectFrame` → `🎞` (format dans `title`/badge), `_updateSessionUI` (`js/session-live.js`) → `🛑`/`👁`/`🎬` (état via couleur + `title`), `_updateSyncUI` → dot coloré (label masqué, statut dans `title`).
- `#aspectMenu` s'ouvre vers la gauche (`right: calc(100% + 8px); top:0`) ; `#lutSettingsPanel` décalé à `right:56px` pour ne pas passer sous la barre.
- La barre est **masquée pendant le mode dessin** (`startDrawing`/`cancelDrawing` togglent `#playerToolbar`) pour ne pas intercepter les clics du canvas dans le coin.
- `applyRoleUI` cible `button[onclick="saveNotes()"]` (maintenant dans `.player-controls`, un seul exemplaire dans le DOM) → le bouton 💾 garde son `onclick` (rôle viewer le masque toujours).

### Plein écran englobe timeline + marqueurs (juillet 2026)

`toggleFullscreen()` mettait en fullscreen uniquement `#videoWrapper` (juste la vidéo + canvases) : la timeline et ses marqueurs, siblings en dehors de cet élément, disparaissaient complètement en plein écran. Fix : nouveau conteneur `.player-fs-wrap` (`#playerFsWrap`), englobant `.player-area` + `.player-controls` + `.timeline-bar` (mais pas `.notes-panel`, qui reste hors-champ). `toggleFullscreen()` cible désormais `#playerFsWrap`. CSS : `.player-fs-wrap { flex:1; display:flex; flex-direction:column; }`, `.player-fs-wrap:fullscreen { width/height:100%; background:#000; }` — `.player-area` garde son `flex:1` donc la vidéo remplit l'espace restant au-dessus de la barre de transport + timeline. Le comparateur (`js/compare.js`) a déjà ses marqueurs sur `.compare-timeline` de chaque slot via `renderCmpMarkers()`, câblé depuis longtemps — aucun changement nécessaire là.

### Cadrage / format d'image (overlay letterbox/pillarbox)

Overlay de prévisualisation des formats ciné les plus répandus. Affiche des masques semi-transparents (bandes noires) + une fine ligne de cadre + un label, par-dessus la vidéo, sans rien modifier au fichier ni à l'export.

**UI** : bouton `🎞` dans la **barre flottante** `.player-toolbar` (cf. section Disposition) → menu déroulant `#aspectMenu` qui s'ouvre **à gauche** du bouton (`right: calc(100% + 8px)`, z-index 60). Le bouton reste en icône seule ; le format actif est repris dans le `title` + le badge `#aspLabel` sur la vidéo + la classe `.asp-on` (fond accent).

**Formats** (`ASPECT_FORMATS`, ratio = largeur/hauteur) : Désactivé, 2.39:1 (Cinémascope), 2.35:1 (Scope), 2.40:1, 2:1 (Univisium), 1.85:1 (Flat ciné), 16:9 (1.78), 1.66:1 (Super 16), 4:3 (1.33), 9:16 (vertical).

**Markup** : `#aspectOverlay` dans `#videoWrapper` (z-index 2, `pointer-events:none`) contient 4 `.aspect-bar` (top/bottom/left/right), `#aspFrameLine` et `#aspLabel`.

| Fonction JS | Rôle |
|-------------|------|
| `initAspectMenu()` (IIFE) | construit le menu + restaure le format mémorisé (`localStorage` clé `derush_aspect`) |
| `toggleAspectMenu(e)` | ouvre/ferme le menu (fermeture au clic extérieur via listener document) |
| `setAspectFrame(ratio,label,el)` | applique le format, met à jour bouton/label/état actif, persiste dans `localStorage`, appelle `updateAspectOverlay()` |
| `_videoDisplayRect()` | rect de l'image RÉELLE dans le LECTEUR : rect `object-fit:contain` de la vidéo brute **amputé des insets** `_contentInsets` (la vidéo du lecteur n'est PAS recadrée, elle montre ses bandes → le cadre se cale sur le contenu à l'intérieur). PAS le ratio-du-contenu en contain (faux quand la vidéo affiche encore ses bandes) |
| `updateAspectOverlay()` | positionne le cadre sur le rect de `_videoDisplayRect()` : letterbox haut/bas si cible plus large que le contenu, pillarbox gauche/droite sinon |

### Bandes noires INCRUSTÉES — détection serveur + crop object-view-box (juin 2026)

Certains rushs ont des bandes noires *bakées* dans le fichier (matte cinéma au tournage — ex. FX6 J01 de DRIFT : matte 1.9:1, `1920×1012` dans du 1920×1080, ~34px de noir haut/bas). Deux conséquences corrigées : (1) le cadre 4:3 calait son haut/bas dans le noir ; (2) en comparaison/multicam, l'image bakée paraissait plus basse qu'un clip plein cadre (FS5).

**Détection : côté SERVEUR (fiable), pas client.** L'ancienne détection JS sur une frame isolée était trompée par les plans sombres (bug du comparateur). Désormais :
- `detect_letterbox(file_path)` (derush_server.py) : `ffmpeg cropdetect=24:2:0` sur 80 frames (`-ss 3`) → `{top,bottom,left,right}` (fractions) **+ `cw,ch`** (dims du contenu après filtrage). Ignore le bruit (<1.5%) et l'aberrant (>35%). Multi-frames = robuste au plan sombre.
- `get_letterbox(proj, clip)` : cache disque `letterbox_cache.json` (chargé au boot par `_load_letterbox_cache()`), détection à la demande.
- `GET /api/project/<pid>/letterbox/<clip_id>` → insets + cw/ch.

**Crop côté client : box 16:9 + ZOOM (transform:scale).** Tentatives ratées : `object-view-box` (non supporté Vivaldi → `false`, ignoré) ; `aspect-ratio` sur le `<video>` (non respecté → `object-fit:cover` sur-croppait) ; `aspect-ratio` = ratio contenu (dans une zone plus haute que 16:9, le contenu plus large devient plus court → mismatch).
Solution retenue (indépendante de la forme de la zone) : la vidéo compare est dans une box `.cmp-vbox` **16:9** (= ratio du fichier, identique pour les 2 clips → même taille/hauteur). Pour un clip baké on **zoome la vidéo** juste assez pour faire sortir les bandes, `overflow:hidden` les masque.
- `.cmp-vbox { aspect-ratio:16/9; max-width/max-height:100%; overflow:hidden; }` ; `.cmp-vbox video { width/height:100%; object-fit:contain; transform-origin:center; }`. Les deux `<video>` du comparateur sont enveloppées dans un `.cmp-vbox`.
- `_setVideoCrop(videoEl, ins)` : `z = max(1/(1-top-bottom), 1/(1-left-right))` ; `videoEl.style.transform = scale(z)` si `z>1.002`. Les boîtes restant 16:9 identiques → clips alignés en hauteur.
- `_applyLetterbox(videoEl, clipId, doCrop)` : fetch `/letterbox`, stocke `_letterbox` + `_contentInsets`. Si `doCrop` → `_setVideoCrop`.
- **Portée : COMPARATEUR seulement** (`doCrop=true`). Lecteur (`selectClip`) et multicam → `doCrop=false` (juste `_contentInsets` pour le cadre ; player = canvas dessin/LUT calés dessus, mc = cellules 16:9). À étendre.
- `_drawAspOn` (cadre) : en comparateur (`.cmp-vbox`) mesure la box (non transformée) → cadre 16:9 plein (vidéo zoomée = bandes hors cadre) ; en mc (non recadré) → rect contain de la vidéo amputé des insets (bandes visibles, cadre dans le contenu).
- Premier affichage d'un clip baké : ~1-2 s (cropdetect serveur) puis caché.

**Cohérence cadre ↔ crop** : `_contentInsets` est désormais alimenté UNIQUEMENT par le serveur (source unique). `updateAspectOverlay`/`_drawAspOn` calculent le cadre sur le **ratio du contenu** (contain), donc le cadre se pose exactement sur la vidéo recadrée. (Anciennes fonctions client `_detectContentInsets`/`_refreshContentInsets`/`_mergeContentInsets` conservées mais **plus appelées**.)

**Cadre appliqué partout** : le même `_aspectRatio` s'applique au player + comparateur + multicam.
- `_ensureAspOverlay(container, videoEl)` : crée (1×) un overlay (4 `.aspect-bar` + ligne) dans un conteneur `position:relative`, **inséré juste après la vidéo** (labels/badges restent au-dessus). Réf sur `container._aspOv`.
- `_drawAspOn(videoEl, container, clipId)` : contain du ratio contenu dans la box de l'élément (via `getBoundingClientRect`), insets depuis le cache serveur. Player / `.compare-video-area` / `a.wrapEl`.
- `refreshAllAspectOverlays()` : player + 2 slots compare (si `#compareOverlay` visible) + angles `_mcView.angles`. Appelé par `setAspectFrame`, `window resize`, et après `_applyLetterbox`.
- Hooks dessin : compare → `loadedmetadata` de `cmpVidN` ; multicam → `loadedmetadata` de chaque `mcVid_i` + fin de `_buildMcLayout` (rAF).

**Globals JS** : `let _aspectRatio = null;` · `let _contentInsets = {};` (insets bandes par clip.id, alimenté serveur) · `let _letterbox = {};` (cache fetch /letterbox).

**Hooks de recalcul du cadre** : `updateAspectOverlay()` en fin de `resizeCanvas()` (`window resize`, `loadedmetadata`, `player resize`) + `fullscreenchange`. Le cadre choisi persiste entre clips et sessions.

## CSS — compare-timeline layout

```css
.compare-timeline { height: 52px; }
.compare-timeline .cmp-tl-track { top: 40px; } /* laisse 26px au-dessus */
.compare-timeline .cmp-tl-head  { top: 40px; width: 13px; height: 13px; }
.compare-timeline .cmp-pin::before { top: 6px; width: 13px; height: 13px; }
/* hover: dot grossit 13→16px + anneau blanc */
.compare-info { height: 90px; overflow-y: auto; } /* fixe pour aligner les vidéos */
/* Vidéos compare : object-fit:contain (comme le lecteur principal). La vidéo remplit
   la zone en préservant son ratio. Deux clips de MÊME ratio (FS5 1280×720 et FX6
   1920×1080 = tous deux 16:9) s'affichent à l'identique → mêmes hauteurs, AUCUN
   rognage. La zone compare étant plus HAUTE que du 16:9, l'image est letterboxée
   (noir haut/bas) — normal.
   PIÈGES (essais ratés) : (1) max-width/max-height → identique pour du même ratio,
   ok ; (2) height:100%+width:auto → sur un flex item, les clips se résolvaient mal et
   disparaissaient ; (3) height:100% absolu → la zone étant plus haute que 16:9, ça
   forçait une largeur énorme → rognage massif des côtés. object-fit:contain est la
   bonne réponse. */
.compare-video-area { overflow: hidden; position: relative; }
.compare-video-area video { width: 100%; height: 100%; object-fit: contain; }

/* VRAIE cause du « hauteurs différentes » (FS5 vs FX6, pourtant tous deux 16:9, proxys
   1280×720 et 1920×1080 SAR 1:1 vérifiés à l'ffprobe) : la grille .compare-grid en
   `1fr 1fr` n'était PAS à colonnes égales. Les items grid ont min-width:auto par défaut
   → la colonne dont le <select> contient un nom de fichier long et insécable
   (DRIFT_avril0001S03.MP4) prenait plus de largeur → sa vidéo object-fit:contain (zone
   plus haute que 16:9 → limitée par la largeur) devenait plus haute. Fix : */
.compare-slot { min-width: 0; }
.compare-slot-header select { flex: 1; min-width: 0; }
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

**Suppression des commentaires reçus** : `revoke_share` supprime le lien (`proj['share']`) mais laissait `proj['share_comments']` intact — les commentaires restaient visibles même après révocation. `clear_share_comments(pid)` (endpoint `share/clear_comments`) vide `proj['share_comments']` sans toucher au lien. Bouton `🗑 Effacer les commentaires` dans `js/share.js`, confirmation par re-clic sous 8s (`confirm2Step`, même logique anti-`confirm()`-natif que le garde-fou de rescan).

**v0.3.29 — la suppression ne propageait pas aux autres machines** : le fix initial (ci-dessus) ne vidait que le cache local de la machine cliquée. Le fichier JSONL persistant côté `derush_sync.php` (un fichier par lien, alimenté par `add_comment`) n'était jamais purgé — seul `revoke_share` le faisait, en tuant le lien entier. Toute machine (y compris celle qui venait d'« effacer ») qui repullait ultérieurement retéléchargeait donc les mêmes commentaires depuis ce fichier intact. Aggravant : `pull_share_comments()` ne faisait qu'AJOUTER les nouveaux commentaires à `proj['share_comments']`, sans jamais rien retirer — une suppression ne pouvait donc structurellement jamais se propager, même le serveur purgé, tant que le cache local de chaque machine n'était pas lui aussi explicitement vidé.

Fix complet : nouvelle action `clear_comments` dans `derush_sync.php` (purge le JSONL du token, sans toucher au `.json` du package — contrairement à `revoke_share` qui supprime les deux). `clear_share_comments()` l'appelle en plus du nettoyage local. `pull_share_comments()` ne fait plus de fetch incrémental par `since` : il retélécharge l'intégralité des commentaires actuels à chaque appel et **remplace** `proj['share_comments']` plutôt que de le compléter — le seul moyen simple de rendre une suppression cohérente sur toutes les machines, sans tombstone. Volume attendu (une poignée de commentaires de review par petite équipe) rend le fetch complet négligeable en coût. Effet de bord positif : le reset de `comments_last_pulled = None` par `create_share`/`refreshShare()` (qui pouvait auparavant redéclencher un re-fetch complet involontaire) devient inoffensif, puisque le fetch est désormais toujours complet de toute façon.

**⚠️ Nécessite un redéploiement manuel** : `derush_sync.php` doit être réuploadé sur l'hébergement (`sebastiendelahaye.be`) pour que `clear_comments` soit reconnu — vérifié par `curl` direct contre le serveur en ligne au moment du fix : action pas encore reconnue tant que l'ancien fichier reste déployé. `derush_sync.example.php` (template public) mis à jour en parallèle.

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
POST /api/project/<pid>/share/clear_comments         (efface proj['share_comments'], garde le lien actif)
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

# État au 22 mai 2026 — Audit + corrections sécurité/stabilité + déploiement v0.3.6

## Audit technique (AUDIT.md créé)
Revue structurée du code (derush_server.py ~5160 lignes, UI ~3450 lignes). Tous les correctifs appliqués sauf §2.3 (HTTP clair sur LAN — assumé), §5 multi-device (1 user 2 machines en parallèle — non couvert), §6 features futures. Voir `AUDIT.md` pour le tableau de suivi complet.

### Correctifs appliqués (22 mai)
- **1.1 Verrou par projet** — `_project_lock(pid)` (RLock). `do_POST` détient le verrou pendant tout le dispatch → écritures d'endpoints sérialisées. Jobs de fond (LTC, multicam, auto-détect) + `sync_project` rechargent le projet sous verrou avant d'écrire.
- **1.2 Écriture atomique** — `save_project` écrit dans un `.tmp` puis `os.replace()`.
- **1.3 Handler 500** — `do_GET`/`do_POST` enveloppent le dispatch ; toute exception → réponse 500 JSON + trace stderr.
- **1.4 `except:` nus** — ~15 occurrences passées en `except Exception:`.
- **2.1 PBKDF2** — `hash_password` produit `pbkdf2$<iters>$<sel>$<hash>` (200 000 iter, sel par mdp). `verify_password` gère les deux formats ; migration transparente au prochain login.
- **2.2 Clé sync en header** — code prêt (`X-Sync-Key`) ; activation = redéployer `derush_sync.php`. Clé `drift2026` à remplacer par une clé aléatoire longue lors de l'activation.
- **2.4 Anti-brute-force login** — 8 échecs en 5 min depuis la même IP → 429.
- **2.5 Expiration liens de review** — `expires_at` = création + 30 jours. PHP refuse HTTP 410 si périmé.
- **3.1 Cache load_project** — invalidé par (mtime, taille) du fichier.
- **3.2 Debounce indexation FTS** — debouncée 2 s.
- **§5 Propagation des suppressions** — `merge_projects` ne publie que les notes du propre user (`_own_note_key` + `own_uid`), conserve la version cloud pour les autres.
- **§4 Tests unitaires Python** — `tests/test_server_units.py`, 20 cas : hachage, timecodes, `merge_projects`, résolveur de chemins, clés users.
- **§4 Découpage modules** — étapes 1-2/5 : `derush_core.py` (utilitaires purs) + `derush_exports.py` (~990 lignes FCPXML/Premiere/EDL/CSV/HTML). `derush_server.py` réduit de ~5320 à ~4330 lignes.

## Version et déploiement v0.3.6
- `VERSION` + `electron/package.json` montés à `0.3.6`. Commit `dee0dff`.
- Build Windows : PyInstaller + Electron → `DerushTool-0.3.6-win.zip` (248 Mo), embarquant les 3 modules Python.
- Build Mac : `git pull` sur le Mac mini + `./build_mac.sh` → `DerushTool-0.3.6-mac-arm64.zip`.
- Déploiement 3 machines : PC Sébastien (sources directes), PC Paola (zip), Mac davebixby (git pull + rebuild).
- Clés d'invitation drift_club v0.3.6 : davebixby = `IKO3LMZ2`, Paola = `W9J3ARXG`.

## Sync asymétrique — notes des autres rafraîchies en cours de session (RÉSOLU)
Constaté lors du test de sync à 3 : un commentaire posté pendant la session ne s'affichait pas chez les autres sans rouvrir le projet.

**Historique du fix** :
- **0.3.7** : le bouton manuel « Synchroniser » (`triggerSync`) recharge désormais `allNotes`/`allDiscussions` des autres users puis re-render (`renderMarkers`/`renderClipList`/`renderMultiUser`), indépendamment du succès du push.
- **0.3.9** : le **poll automatique** (`startNotesPolling`, 60 s) déclenche d'abord un **pull-only cloud** avant de relire `/notes`. Avant ça, le poll ne relisait que le fichier local, qui n'était rafraîchi que par le thread serveur (~10 min) → latence jusqu'à 10 min sans clic manuel. Maintenant les notes des autres apparaissent en ≤ 60 s sans aucune action.

**Implémentation 0.3.9** :
- `sync_project(pid, push=True)` : `push=False` → pull + merge + save local **sans** renvoi cloud (léger). N'écrit le fichier (et ne crée un backup versionné) **que si le merge change réellement quelque chose** (`merged != local_now`) → pas de rotation des backups locaux à chaque pull.
- Endpoint `POST /api/sync/pull` (body `{project_id}`) : pull-only du projet courant. Valide le `pid` (regex `^[a-zA-Z0-9_\-]+$`), renvoie `{ok, message}`. No-op si sync non configurée.
- Frontend `startNotesPolling` : `fetch('/api/sync/pull', {project_id})` best-effort en tête de chaque tick, puis logique de relecture `/notes` + `/discussions` existante.
- Les push locaux restent gérés par le timer debounced sur save (`_schedule_sync_push`) — le pull-only n'introduit aucun push supplémentaire.

# État au 26 juillet 2026 — v0.3.10 : timeline en plein écran, bouton save relocalisé

## Timeline + marqueurs visibles en plein écran
Voir section « Plein écran englobe timeline + marqueurs » plus haut. `#playerFsWrap` remplace `#videoWrapper` comme cible de `requestFullscreen()`.

## Bouton 💾 Sauver déplacé
Retiré de la barre flottante `.player-toolbar`, ajouté dans `.player-controls` (barre du bas), juste avant `#saveStatus`. Un seul exemplaire désormais dans le DOM (avant : dupliqué visuellement nulle part mais documenté à tort comme faisant partie de la barre flottante uniquement).

## FS5 son TC + flèches ◄/► qui ne bougent pas la timeline — build Mac obsolète, pas un bug de code
Signalé par l'utilisateur **spécifiquement sur la version Mac** : le son joué était la piste TC/LTC (BZZZZ) au lieu du micro, et ◄/► ne permettaient pas de se déplacer dans la timeline. Vérification du code source actuel (Windows, HEAD) :
- Le routage WebAudio mono-R (`_attachPlayerAudio`/`_setPlayerMonoR` dans `derush_app.html`, `_attachCmpSlotAudio`/`_setCmpMonoR` dans `js/compare.js`) est présent, correct et **sans branche spécifique à une plateforme** — Electron embarque Chromium sur Mac comme sur Windows, donc le même code WebAudio doit s'y comporter identiquement.
- Les raccourcis `ArrowLeft`/`ArrowRight` (seek frame-accurate, `Shift` = ±5s) sont câblés à la fois dans le handler clavier global (`derush_app.html`, section KEYBOARD SHORTCUTS) et dans `_cmpKeydown` (`js/compare.js`) pour le comparateur — également sans code spécifique à une plateforme.
- Aucune des deux fonctionnalités n'est un ajout récent : elles étaient déjà présentes bien avant le premier build Mac réel (session 20-21 mai, voir plus haut) et le dernier rebuild Mac documenté date de la **v0.3.6** (22 mai) — trois versions en retard sur le HEAD actuel (0.3.10).

**Conclusion : très probablement un exécutable Mac (`.app`) pas reconstruit depuis longtemps**, pas un bug de code à corriger. Pas de piste de correctif côté source à ce stade — recommandation : refaire `git pull` + `./build_mac.sh` sur le Mac mini (voir `BUILD_MAC.md`) et re-tester avant d'investiguer plus loin. Si le bug persiste après rebuild depuis ce commit, il faudrait alors reproduire en conditions réelles sur Mac (logs console, `_playerAudioCtx.state`, vérifier que `_attachPlayerAudio()` ne tombe pas dans son `catch` silencieux) — piste non explorée faute d'accès à une machine Mac depuis cet environnement.

## Sauvegarde automatique hors-ligne : oui, côté local
`setInterval(() => saveNotes(true), 30000)` (`derush_app.html`) sauvegarde les annotations toutes les 30 s via `POST /api/project/<id>/notes`, qui va vers le **serveur Python local** (`localhost:8765`) — ça marche que la machine soit connectée à Internet ou non, tant que le serveur Derush tourne. `save_project()` écrit sur disque de façon atomique (`.tmp` + `os.replace`) à chaque appel, avec backup versionné.
La **sync cloud** (push vers `derush_sync.php`) est un mécanisme séparé et additionnel : elle est debouncée (3 s après une sauvegarde) et retentée automatiquement à la reconnexion / toutes les 10 min (`_sync_background_thread`), mais son échec hors-ligne n'affecte pas la sauvegarde locale — les annotations ne sont jamais perdues faute de réseau, seule leur propagation aux autres collaborateurs est différée jusqu'au retour en ligne.

# État au 26 juillet 2026 (suite) — v0.3.11 : perte de clips au rescan (incident réel + fix)

## Incident : 428 clips perdus en un clic
Constaté en conditions réelles sur le projet `drift_club` : l'admin a mis à jour son chemin local des rushs (le disque externe s'était rebranché sous une nouvelle lettre, `D:` → `E:`), puis a lancé un rescan. Résultat : `proj['clips']` passé de 428 à 0 en ~3 secondes — bien trop rapide pour un vrai scan (un scan complet de ce dossier prend ~64s, mesuré). Preuve que le scan a tourné sur un chemin invalide qui échoue immédiatement, très probablement l'ancien `proj['root_path']` (`D:\DRIFT_CLUB`, champ resté périmé) utilisé en fallback parce que le `root_path` de la session n'était pas encore à jour au moment de ce scan précis.

**Bonne nouvelle constatée en investiguant** : les `notes`/`discussions`/`multicam_groups`/`audio_clips` référencent les clips par leur `id` mais vivent dans des dicts séparés de `clips[]` — un vidage de `clips[]` seul ne détruit aucune annotation, juste leur affichage (plus aucun clip dans la sidebar). Récupération : restauration de `proj['clips']` depuis le dernier backup versionné d'avant l'incident (`projects/backups/drift_club/drift_club_20260726_102931.json`, 428 clips) + correction de `proj['root_path']` sur la lettre de lecteur réelle actuelle.

## Root cause côté code
`POST /api/project/<pid>/scan` (derush_server.py) faisait `proj['clips'] = scan_media_folder(scan_root, ...)` sans **aucun garde-fou** — un résultat vide (chemin invalide, disque pas monté, mauvaise saisie) écrasait silencieusement une liste de clips existante partagée par toute l'équipe (le champ `clips` n'est pas per-user).

## Fix : garde-fou anti-écrasement
- Si `proj['clips']` a déjà des entrées et que le nouveau scan en trouve **moins de 50%**, la requête est refusée (HTTP 409, rien n'est sauvegardé) avec un message explicite (chemin scanné, ancien/nouveau compte).
- Un flag `force:true` dans le body POST bypass le garde-fou pour un vidage volontaire assumé (dossier réellement déplacé/vidé).
- Frontend (`rescanProject()`) : **pas de `confirm()` natif** (cf. piège Electron déjà documenté — le focus state casse après un dialog natif). À la place : toast d'avertissement + fenêtre de 15s pendant laquelle recliquer 🔄 revient à confirmer (`_rescanForceUntil`, comparé à `Date.now()` au clic suivant). Remplace aussi un `alert()` préexistant sur le chemin d'erreur générique (même règle no-native-dialog).

## Ce que ça ne couvre PAS
Le vrai bug de fond (pourquoi `s.get('root_path')` n'était pas à jour au moment du scan qui a déclenché l'incident) n'a pas été identifié avec certitude — plusieurs chemins de mise à jour du `root_path` existent (`set_root_path`, édition admin `edit_user`) et ne mettent pas forcément à jour `SESSIONS[token]['root_path']` de façon uniforme. Le garde-fou ci-dessus protège contre la conséquence (perte de données) quelle que soit la cause exacte ; investiguer la cause précise si l'avertissement 409 se déclenche à nouveau sans raison apparente.

## Question : sync auto après travail hors-ligne sur une autre machine
Confirmé (pas de changement de code nécessaire, comportement déjà correct) : un collaborateur qui annote hors-ligne (ex. Mac portable sans connexion) voit ses notes sauvegardées localement en continu (`saveNotes` toutes les 30s, sur le serveur local — indépendant du réseau). Dès que sa machine retrouve une connexion, `_sync_background_thread` détecte la reconnexion (poll 90s) et déclenche un sync automatiquement, sans action utilisateur. Ses notes sont indexées sous son propre `user_id` (merge sans conflit — voir `merge_projects`), donc aucun risque d'écraser le travail des autres à ce push.

**Nuance importante découverte en creusant `merge_projects`** : le champ `clips` n'est **jamais fusionné** — `result = copy.deepcopy(local)` garde toujours SES PROPRES clips, ceux du remote ne sont jamais adoptés lors d'un merge normal (seul le flow `join_with_key`, qui télécharge le projet à neuf sans merge, adopte directement le remote). Implication pratique de l'incident ci-dessus : tant que le fichier local d'une machine a des clips corrects, un push depuis cette machine réécrase le cloud avec les bons clips, quel que soit l'état du cloud — la machine avec les données saines est donc auto-réparatrice pour ce champ au prochain sync.

## Badge « En attente » (invite_key)
`'pending': bool(u.get('invite_key'))` (endpoint liste users, derush_server.py ~L2445) — un user reste « En attente » tant que son `invite_key` n'a pas été consommé via `POST /api/sync/join_with_key` **et que cette consommation n'a pas encore été synchronisée** vers la copie du projet qu'on regarde. Cas vécu : collaborateur qui a déjà rejoint et annoté sur sa machine (hors-ligne), mais dont la machine qu'on consulte n'a pas encore reçu son push — le badge reste affiché à tort jusqu'au prochain sync réussi de sa machine, qui effacera `invite_key` partout.

# État au 26 juillet 2026 (suite) — v0.3.12 : reprise de la position de lecture par clip

## Fonctionnalité
Quitter un clip en cours de lecture (le sélectionner ailleurs dans la sidebar, changer de slot dans le comparateur, ou fermer le viewer multicam) puis y revenir replace la tête de lecture à l'endroit laissé, au lieu de repartir de 0. Demandé pour les 3 contextes : lecteur principal, comparateur 2-clips, et clips synchronisés (groupe multicam).

## Implémentation
- **Global partagé** `let _clipResumeTime = {}` (déclaré en tête de `js/audio-bwf.js`, avant les autres modules dans l'ordre de chargement `<script>` — donc visible de `compare.js` et `multicam-viewer.js` via le scope lexical global partagé, cf. section Refactor modules JS) : `clip.id → secondes`.
- **Lecteur principal** (`selectClip`, `js/audio-bwf.js`) : au tout début de la fonction, avant de réassigner `activeClip`, sauvegarde `player.currentTime` sous l'ancien `activeClip.id`. Au `loadedmetadata` du nouveau clip (même listener `once` qui pose déjà `playbackRate`), restaure `player.currentTime` si une valeur > 0.1s existe pour ce `clip.id`.
- **Comparateur** (`loadCmpClip(slot)`, `js/compare.js`) : sauvegarde la position du clip quitté dans ce slot (`_cmpClips[slot]` avant réassignation) ; restaure au `loadedmetadata` du nouveau clip, **avant** l'appel à `_detectCmpMulticam()` — si les 2 clips du comparateur forment une paire multicam validée, l'alignement automatique du slot 1 sur le slot 0 prend la main après coup (comportement voulu : la synchro multicam est prioritaire sur la reprise générique). `closeCompare()` sauvegarde aussi la position des 2 slots avant de vider les `<video>`.
- **Viewer multicam / clips synchronisés** (`js/multicam-viewer.js`) : `_mcGroupResumeTime = {}` (`group.id → secondes de temps-groupe`, distinct de `_clipResumeTime` car un groupe multicam n'a pas d'identité de clip unique). `closeMcViewer()` sauvegarde `_mcCurrentGroupTime()` sous `v.group.id`. `_buildMcLayout(isInitial)` : au premier build, la position de démarrage devient `_mcGroupResumeTime[group.id]` si elle existe (sinon comportement inchangé : démarre au `normOff` du clip primaire).
- **`swapToAngle`** (bascule d'angle dans un groupe, existant) n'est pas affecté : il appelle `selectClip()` (qui pose son propre listener `loadedmetadata` de reprise) puis attache un second listener `loadedmetadata` `{once:true}` qui écrase la position avec le calcul par offset — l'ordre d'attache des listeners fait que ce recalcul explicite gagne toujours sur la reprise générique, ce qui est le comportement voulu (swap d'angle = suivre le même instant, pas la dernière position vue sur cet angle).
- Pas de persistance disque/localStorage — mémoire vive, reset à chaque rechargement de page (comportement jugé suffisant : la demande porte sur la navigation en cours de session, pas sur une reprise après fermeture de l'app).

# État au 26 juillet 2026 (suite) — v0.3.13 : correctifs comparateur + miniatures dans le sélecteur

## Bug 1 — le slot 0 du comparateur reprenait une position obsolète
Retour terrain sur la v0.3.12 : ouvrir ⚡ Comparer chargeait le slot gauche avec l'ancienne valeur de `_clipResumeTime[activeClip.id]`, laissée par une session comparateur *précédente* sur ce même clip (ex. 3/4 de la timeline) — pas la position réelle du lecteur principal, qui peut avoir bougé entre-temps sans jamais déclencher `selectClip()` (donc sans jamais rafraîchir l'entrée de la map). Fix (`openCompare()`, `js/compare.js`) : juste avant `loadCmpClip(0)`, on écrase explicitement `_clipResumeTime[activeClip.id] = mainPlayer.currentTime` — le comparateur reflète alors toujours l'instant courant du lecteur principal à l'ouverture, la reprise « historique comparateur » restant valable seulement pour les changements de clip *pendant* qu'on est dans le comparateur.

## Bug 2 — barre de progression figée sur l'ancien clip
Charger un nouveau clip dans un slot (`loadCmpClip`) ne réinitialisait ni la barre `#cmpProgN`/`#cmpHeadN` ni le TC `#cmpTcN` : ces éléments ne sont mis à jour que par `updateCmpTc(slot)`, câblé sur l'event `ontimeupdate` de la `<video>` — qui ne refire pas forcément tout de suite si le nouveau clip démarre à 0 et reste en pause (pas de seek → pas de `timeupdate` immédiat dans certains navigateurs/Electron). Fix : reset explicite de la barre/TC à `loadCmpClip()` (avant le chargement) + appel direct à `updateCmpTc(slot)` dans le listener `loadedmetadata` (après l'éventuel seek de reprise), au lieu de compter uniquement sur l'event natif.

## Feature — miniatures dans le sélecteur de clips du comparateur
Demande : pouvoir repérer les clips plus facilement dans les menus déroulants du comparateur. Un `<select>` natif ne peut pas afficher d'image dans ses `<option>` (limitation Chromium/tous navigateurs) → remplacé visuellement par un combo custom :
- Le `<select id="cmpSelN">` d'origine est **gardé dans le DOM, caché** (`display:none`) — reste la source de vérité pour `.value`, lu ailleurs dans le code (`loadCmpClip`, `refreshAllAspectOverlays`). Toute sélection passe par `_cmpPickClip(slot, clipId)` qui pose `sel.value = clipId` puis appelle `loadCmpClip(slot)` normalement — zéro changement requis dans le reste du code.
- Nouveau markup par slot : `.cmp-combo` (bouton `#cmpComboBtnN` avec miniature `#cmpComboThumbN` + label `#cmpComboLabelN`, liste déroulante `#cmpComboListN`).
- `_cmpBuildComboList(slot)` (appelée dans `openCompare()`) construit la liste avec un `<img>` par clip (`/api/project/<pid>/thumbnail/<clip_id>`, même endpoint que le panneau Angles) + le label existant (`day · filename`).
- `_cmpToggleCombo(slot)` / `_cmpComboOutsideClick` : ouverture/fermeture façon menu, un seul combo ouvert à la fois, fermeture au clic extérieur (`document.addEventListener('click', ..., {capture:true, once:true})`).
- `_cmpUpdateComboLabel(slot, clip)` : synchronise miniature + label du bouton + surbrillance de l'item sélectionné dans la liste — appelée dans `loadCmpClip()` (après changement) et `closeCompare()` (reset à l'état vide).
- CSS `.cmp-combo*` dans le bloc de styles principal, à côté de `.compare-slot-header` ; `z-index:60` cohérent avec les autres popups de la page (`#aspectMenu`, `#lutSettingsPanel`).

# État au 26 juillet 2026 (suite) — v0.3.14 : rescan qui fermait l'app (heartbeat trop court)

## Contexte
102 proxys FS5 régénérés sur un nouveau disque (`E:\DRIFT_CLUB`, disque précédent `D:` remonté sous une nouvelle lettre — cf. `transcode_proxies.sh`). Après rescan pour les prendre en compte : le bouton reste en ⏳ puis **l'application entière se ferme**, sans rien dans `crashes.jsonl`. Signalé en même temps qu'un second symptôme distinct (voir plus bas) : le son des clips FS5 joue le bruit du TC (LTC) au lieu du micro.

## Root cause confirmée par mesure directe
`scan_media_folder()` appelé en isolation sur `E:\DRIFT_CLUB` (428 clips, ffprobe par fichier) prend **65 secondes**, sans aucune erreur. Le watchdog `_heartbeat_watcher()` (`_HEARTBEAT_TIMEOUT = 12`) tue le process via `os._exit(0)` — un arrêt volontaire, pas une exception, d'où l'absence totale de trace dans le crash reporter. `do_POST` tient `_project_lock(pid)` pendant tout `scan_media_folder()`, donc la requête `/scan` reste bloquante côté serveur pendant ces 65s ; le heartbeat `/api/heartbeat` du frontend est censé être indépendant (connexion HTTP séparée, `ThreadingMixIn`), mais la marge de 12s ne laisse aucune place au moindre à-coup de charge — d'autant plus juste après 40+ minutes d'encodage NVENC et sur un scan CPU/IO-intensif touchant un disque externe.

**Reproduit en conditions contrôlées** : importer `derush_server` (démarre le watchdog) et appeler `scan_media_folder()` sans jamais simuler de heartbeat → le process meurt silencieusement avant d'avoir rien affiché (~23s : grâce de 20s + première vérification à +3s), bien avant la fin réelle du scan à 65s. En simulant un heartbeat toutes les 2s depuis un thread du script de test, le même scan va jusqu'au bout sans problème — preuve directe que c'est le watchdog, pas `scan_media_folder()`, qui est en cause.

## Fix appliqué
`scan_media_folder()` (derush_server.py) rafraîchit désormais `_last_heartbeat` (global) à chaque fichier itéré dans sa boucle principale. Le scan prouve sa propre vivacité pendant qu'il tourne, indépendamment de la livraison effective des heartbeats client. Re-testé dans les mêmes conditions qu'à l'origine du bug (aucun heartbeat simulé) : le scan va maintenant jusqu'au bout (428 clips, ~53s), le process ne s'arrête plus prématurément.

Portée volontairement limitée à `scan_media_folder()` : c'est la seule opération synchrone-dans-la-requête qui peut légitimement dépasser 12s. Les autres jobs longs (décodage LTC, détection multicam, auto-détection de plans) tournent déjà en thread de fond avec polling (`/status` endpoints) — ils ne bloquent jamais le dispatch `do_POST` et n'ont donc jamais pu déclencher ce bug.

## Second symptôme (même incident) — bruit TC sur les clips FS5 : pas un bug
Vérifié dans `drift_club.derush.json` : les 147 clips FS5 du projet ont `ltc_tc_in_sec = null` — normal, ce sont des proxys tout juste régénérés et l'étape **🎶 Décoder LTC** (voir section Multicam plus haut) n'a pas encore tourné dessus. Le silencing automatique de la piste TC (`_setPlayerMonoR`, section « Audio FS5 mono R ») se déclenche sur `clip.ltc_tc_in_sec != null` — tant que cette valeur n'est pas peuplée, le lecteur joue le stéréo brut du proxy (L=LTC, R=micro) sans filtrage. Aucun correctif de code nécessaire : lancer le décodage LTC une fois sur le projet résout le symptôme.

# État au 26 juillet 2026 (suite) — v0.3.15 : le fix du scan ne couvrait pas tous les cas

## Correction sur l'affirmation de la section précédente
La v0.3.14 affirmait que les jobs de fond (décodage LTC, détection multicam, auto-détection) « ne bloquent jamais le dispatch `do_POST` et n'ont donc jamais pu déclencher ce bug ». **Ce raisonnement était incomplet.** Ne pas bloquer la requête HTTP du client n'empêche pas une activité serveur intense de créer des à-coups de charge (CPU, I/O disque) suffisants pour qu'un `/api/heartbeat` légitime, envoyé sur une connexion pourtant indépendante, rate quand même la fenêtre de tolérance.

## Nouvel incident confirmant le problème plus large
Après le build 0.3.14, l'app s'est refermée à nouveau — cette fois **sans rescan ni décodage LTC en cours** (confirmé explicitement par l'utilisateur), juste après une navigation normale sur le lot d'environ 100 clips FS5 jamais ouverts (chaque premier affichage déclenche vignette + strip de scrubbing + waveform via ffmpeg). Même mécanisme de fond (watchdog trop strict), déclenché par un chemin différent du rescan.

## Fix généralisé (derush_server.py)
Plutôt que de patcher chaque boucle serveur longue une par une (approche fragile, toujours en retard d'un cas non couvert) :
- `do_GET` et `do_POST` rafraîchissent désormais `_last_heartbeat` pour **toute requête entrante**, pas seulement `/api/heartbeat` — une requête vignette/proxy/waveform prouve tout autant que le navigateur est actif.
- `_HEARTBEAT_TIMEOUT` porté de 12 à **30 secondes**, marge de sécurité supplémentaire sans dégrader significativement la détection d'un onglet réellement fermé (grâce de démarrage 20s + 30s ≈ 50s pire cas).

Le fix ciblé de la 0.3.14 (heartbeat rafraîchi dans la boucle `scan_media_folder`) reste en place — redondant avec le fix général pour ce cas précis, mais reste une défense en profondeur utile si un futur job long ne génère aucune requête HTTP entrante pendant son exécution (pas d'image, pas de heartbeat client, rien).

# État au 26 juillet 2026 (suite) — v0.3.16 : la vraie cause du hang, trouvée par reproduction directe

## Symptôme précis rapporté
« Le sablier reste même si le scan est fini » — le bouton 🔄 ne se réinitialise jamais. Vérification demandée à l'utilisateur (F12 → Réseau) : la requête `/scan` reste **« pending » indéfiniment**, jamais de statut 200. Ce n'était donc pas un problème de timing heartbeat mais un vrai hang réseau — les fix 0.3.14/0.3.15 (bien que corrects) ne pouvaient pas résoudre ce symptôme précis.

## Root cause (trouvée par test HTTP réel contre le serveur réel, pas par lecture de code seule)
Un script de test a importé `derush_server`, injecté une session valide directement dans `SESSIONS`, démarré le vrai `ThreadedHTTPServer`, et envoyé une vraie requête `POST /api/project/drift_club/scan` via `urllib`. Avec `scan_media_folder`/`save_project` monkey-patchés pour logger leur entrée : **`scan_media_folder` n'est jamais appelée**. Le hang se produit avant.

En lisant le handler `/scan` ligne par ligne (`derush_server.py`) : `_dispatch_post()` lit déjà le corps POST une fois tout en haut (`body = self._read_body()`, partagé par tous les endpoints). Le handler `/scan` refaisait **une deuxième lecture** (`body = self._read_body() or {}`) juste après `require_auth`. `_read_body()` fait `self.rfile.read(length)` avec `length` = `Content-Length` — la première lecture consomme déjà tous les octets du corps ; la seconde relit le même nombre d'octets sur un socket qui n'a plus rien à donner → **`rfile.read()` bloque indéfiniment** (aucun timeout configuré sur ce socket), en attendant des données que le client ne renverra jamais (il attend la réponse).

`grep` confirme que `/scan` est le **seul** endpoint avec cette double lecture dans tout `derush_server.py`. Le bug ne se déclenche que si le corps POST est non-vide (`{"force": false}` envoyé par `rescanProject()`) — un corps vide fait retourner `{}` immédiatement aux deux lectures sans toucher le socket, ce qui explique pourquoi ce code a pu rester non détecté depuis l'ajout du flag `force` (v0.3.11).

## Fix
Suppression de la lecture redondante — le handler `/scan` utilise désormais le `body` déjà lu par `_dispatch_post()` (même portée de fonction, aucune ré-lecture nécessaire). Revérifié avec le **même** test de reproduction : statut 200, 428 clips, 51,9 secondes, aucun hang.

## Implication rétroactive sur les plantages 0.3.14/0.3.15
`do_POST` tient `_project_lock(pid)` pendant tout le dispatch — un `/scan` qui hang indéfiniment dessus tient donc *aussi* ce verrou indéfiniment, bloquant en cascade toute autre écriture sur ce projet (sauvegarde de notes, etc.) tant que la requête reste pendante. C'est très probablement la vraie cause directe des plantages précédemment attribués au seul timing du heartbeat. Les fix heartbeat (généralisation à toute requête + marge 30s) restent corrects et utiles en défense en profondeur — une opération légitimement longue ne doit jamais pouvoir se faire tuer par le watchdog — mais ce bug de lecture double était la cause directe et suffisante du symptôme exact rapporté par l'utilisateur, indépendamment de tout timing.

# État au 26 juillet 2026 (suite) — v0.3.17 : le fix 0.3.16 ne suffisait toujours pas — ffprobe.exe zombie

## Le fix de la lecture double était correct mais insuffisant
Après avoir livré 0.3.16, l'utilisateur retente avec un zip fraîchement extrait dans un nouveau dossier (version confirmée sans ambiguïté) — `/scan` reste bloqué en pending indéfiniment. Ma reproduction isolée (même script de test HTTP réel) réussit pourtant deux fois de suite sur cette même machine (51,9s puis 52,4s) : le code est correct, l'environnement est stable. La divergence vient donc d'un facteur présent uniquement dans la vraie session utilisateur.

## Diagnostic décisif : Gestionnaire des tâches pendant le blocage
Demandé à l'utilisateur d'observer le Gestionnaire des tâches (onglet Détails, trié CPU) pendant que `/scan` reste bloqué. Résultat : **un processus `ffprobe.exe` présent mais à 0% CPU** (pas de `ffmpeg.exe`). Un processus qui existe sans consommer de CPU n'est pas en train de travailler lentement — il est bloqué en attente sur une ressource (I/O), pas en calcul.

## Root cause
`_ffmpeg_run()` lance `subprocess.run(cmd, timeout=30, ...)` — en théorie Python tue le process après 30s. Mais un processus bloqué dans une **attente I/O noyau ininterruptible** (disque externe qui répond mal, ou antivirus Windows retenant en lecture un fichier tout juste écrit — exactement le cas des 102 proxys FS5 générés par NVENC quelques minutes plus tôt) peut être **impossible à tuer** depuis l'espace utilisateur : `TerminateProcess()` ne revient pas tant que l'I/O sous-jacente ne se termine pas côté pilote/OS, ce qui peut prendre très longtemps ou ne jamais se produire dans la fenêtre d'observation.

`scan_media_folder()` appelle `ffprobe_metadata()` **séquentiellement** par fichier — un seul fichier dans cet état gèle la boucle entière, et via `_project_lock(pid)` tenu pendant toute la requête `/scan` (fix 0.3.16 compris), gèle en cascade toute autre écriture sur le projet. Confirmé : `/notes` et `pull_comments` étaient également bloqués pendant l'incident, `/api/heartbeat` (hors verrou projet) répondait normalement — cohérent avec un verrou projet tenu indéfiniment par la requête `/scan`.

## Fix
Nouvelle fonction `_ffprobe_metadata_bounded(filepath, wall_timeout=20)` (`derush_server.py`, juste avant `ffprobe_metadata`) : exécute `ffprobe_metadata()` dans un thread daemon, attend le résultat via `threading.Event.wait(timeout=20)` — indépendamment de ce qui se passe réellement dans le thread. Si le fichier ne répond pas à temps, le scan continue avec des métadonnées vides pour ce clip (durée 0, pas de TC — clip présent mais dégradé, plutôt qu'absent) au lieu d'attendre indéfiniment un sous-processus potentiellement immortel. `scan_media_folder()` appelle désormais `_ffprobe_metadata_bounded(f)` au lieu de `ffprobe_metadata(f)` directement.

Coût dans le pire cas (rare) : un thread et un slot de `_ffmpeg_sem` restent occupés jusqu'à ce que l'OS libère enfin le processus zombie — accepté comme compromis, car l'alternative (attendre indéfiniment) gèle tout le projet pour tous les collaborateurs.

## Fix additionnel trouvé en creusant (même classe de bug que 0.3.16)
`/api/crash` avait la même double-lecture du corps de requête (`self.rfile.read(...)` une deuxième fois après le `_read_body()` du dispatcher partagé) — corrigée par la même occasion, bien que non mise en cause dans cet incident précis (payloads de crash généralement petits, risque plus théorique qu'observé).

## Pourquoi ça n'apparaît que sur ce lot de clips précis
Les 102 proxys FS5 venaient d'être écrits par un encodage NVENC de 43 minutes juste avant le scan. Un antivirus scannant les fichiers neufs en temps réel, ou un cache d'écriture pas encore flush sur le disque externe, sont des explications plausibles pour un verrou I/O transitoire sur un ou plusieurs fichiers précis — sans garantie de reproductibilité (mon test isolé, lancé à un instant où ces conditions transitoires n'étaient plus présentes, n'a jamais rencontré le problème).

# État au 26 juillet 2026 (suite) — v0.3.18 : le fix 0.3.17 ne suffisait toujours pas — fuite de la sémaphore ffmpeg partagée

## Le fix 0.3.17 était incomplet
Retest de l'utilisateur sur 0.3.17 : « après plus de 5 minutes ffprobe à 0%, scan/notes/pull_comments en pending, toujours pareil ». `_ffprobe_metadata_bounded` (0.3.17) borne correctement l'attente de l'**appelant** à 20s par fichier, mais le thread daemon qu'elle lance pour ce fichier continue de tourner indéfiniment en arrière-plan (c'est le principe du fix : abandonner l'attente, pas le thread). Ce thread reste bloqué à l'intérieur de `_ffmpeg_run()`, qui faisait `with _ffmpeg_sem:` — un `with` ne libère la sémaphore qu'au retour de `subprocess.run()`, qui ne revient jamais pour un processus réellement zombie. Le permis de sémaphore est donc perdu pour de bon, silencieusement, à chaque fichier dans cet état.

## Root cause : la sémaphore `_ffmpeg_sem` n'a que 8 permis et est partagée par TOUTE l'app
`_ffmpeg_sem` (8 permis sur cette machine 24 cœurs, `_FFMPEG_MAX_CONCURRENT`) throttle absolument tous les appels ffmpeg/ffprobe de l'application — vignettes, strips, waveform, décodage LTC, détection de plans, scan. Si plusieurs fichiers du lot de 102 proxys se retrouvent bloqués pendant le scan (plausible si l'antivirus scanne plusieurs fichiers à la suite), les 8 permis finissent tous par fuiter un par un. Une fois épuisés, **tout nouvel appel ffmpeg/ffprobe de l'app entière** — pas seulement les fichiers restants du scan, n'importe quelle vignette ou waveform demandée ailleurs — bloque indéfiniment sur le `with _ffmpeg_sem:` lui-même, en attente d'un permis qui ne se libérera jamais. D'où la persistance du symptôme malgré le fix 0.3.17 : celui-ci réglait le cas du premier fichier bloqué, pas la fuite de fond qui s'accumule ensuite jusqu'à épuisement total.

## Confirmé par simulation directe
Script qui acquiert les 8 permis de `_ffmpeg_sem` à la main sans jamais les libérer (simule des zombies accumulés), puis appelle `_ffmpeg_run(['ffprobe', '-version'], timeout=5)`. Avec l'ancien code (`with _ffmpeg_sem:` sans délai) : blocage indéfini confirmé. Avec le fix : échec propre après 10s (`timeout + 5`) avec un `TimeoutError` clair.

## Fix
`_ffmpeg_run()` acquiert désormais la sémaphore via `_ffmpeg_sem.acquire(timeout=timeout + 5)` au lieu du `with` bloquant sans limite ; libération explicite dans un `finally`. Si aucun permis ne se libère à temps, `TimeoutError` est levée — absorbée par le même `except Exception` qui gérait déjà les autres échecs ffprobe (retour `{}`, clip dégradé mais pas de gel). Compromis identique à la 0.3.17 : un permis peut rester perdu pour de bon si son détenteur est un vrai zombie (capacité effective réduite d'autant, jusqu'au redémarrage de l'app), mais plus aucun appelant, nulle part dans l'app, ne peut désormais rester bloqué indéfiniment à cause de ça.

# État au 26 juillet 2026 (suite) — v0.3.19 : diagnostic en direct (py-spy) — ce n'était plus un hang, juste trop lent

## Méthode : inspection live du process réel plutôt que reproduction isolée
Après la 0.3.18, retest utilisateur : « toujours pareil ». Plutôt que continuer à écrire des scripts de reproduction isolés (qui n'avaient jamais révélé le vrai comportement en conditions réelles), demande faite de laisser le rescan bloqué **en direct** — l'utilisateur travaillant sur la même machine que celle utilisée pour tout ce diagnostic. Installation de `py-spy` (`pip install py-spy`) et dump direct des stacks Python du process réel en cours d'exécution : `py-spy dump --pid <pid>` (trouvé via `tasklist`/`netstat -ano` sur le port 8765).

## Ce que ça a montré
Le thread gérant `/scan` était dans `_ffprobe_metadata_bounded` (fix 0.3.17), sur `Event.wait(20)` — attente normale sur le fichier courant, pas un blocage. Un second dump quelques instants après : le thread avait progressé vers un fichier suivant (nouveau thread daemon interne). Un troisième dump plus tard : le thread avait disparu — requête terminée normalement, fichier projet sauvegardé (428 clips, horodatage concordant). **Les fix 0.3.16/0.3.17/0.3.18 fonctionnent tous correctement** — il ne s'agissait plus d'un hang infini. Confirmé par l'utilisateur : le scan a fini par se terminer après ~15 minutes (contre ~52s en test isolé).

## Root cause de la lenteur (elle-même, pas le hang)
Un `ffprobe` direct en ligne de commande sur un des fichiers concernés, lancé PENDANT que l'app était censée être « bloquée », répond en 0,1s — ni le disque ni le fichier ne sont intrinsèquement lents. La différence : `scan_media_folder()` sonde chaque fichier via `_ffmpeg_sem`, la **même sémaphore à 8 emplacements** utilisée par vignettes/strips/waveform. Juste après avoir généré 102 nouveaux proxys FS5, l'app pré-génère leurs aperçus en tâche de fond (décodage vidéo réel, bien plus lourd qu'un `ffprobe -show_entries`) — ces opérations occupent les 8 emplacements en continu pendant plusieurs minutes. Les sondages du scan, individuellement quasi instantanés, doivent faire la queue derrière ce travail de fond jusqu'à épuiser leur délai d'attente (20s du wrapper, ou 35s de la sémaphore) avant même d'avoir pu démarrer — d'où l'accumulation jusqu'à ~15 minutes sur 428 fichiers.

## Fix
Nouvelle sémaphore dédiée `_ffprobe_meta_sem` (`_FFPROBE_META_MAX_CONCURRENT = max(4, min(16, cpu_count))`, 16 sur cette machine), réservée aux sondages `ffprobe` de métadonnées seules. `_ffmpeg_run()` accepte désormais un paramètre `sem` optionnel (défaut : `_ffmpeg_sem`) ; `ffprobe_metadata()` (utilisée uniquement par `scan_media_folder`) passe `sem=_ffprobe_meta_sem`. Un rescan actif ne peut plus se faire distancer par de la pré-génération d'aperçus en arrière-plan, qui continue de tourner sur son propre quota.

Sanity check post-fix (conditions isolées) : ~52s, aucune régression. L'amélioration réelle (plus de queue derrière la pré-génération) ne se mesure qu'en conditions réelles de contention.

# État au 26 juillet 2026 (suite) — v0.3.20 : plus besoin de redémarrer après Décoder LTC

## Bug signalé
Après un décodage LTC réussi (corrige le bruit de TC sur les clips FS5), le son restait faux tant que l'app n'était pas redémarrée.

## Root cause
Le décodage LTC met à jour `clip.ltc_tc_in_sec` côté serveur, mais le tableau `clips` côté client n'est chargé qu'une fois, à `enterWorkspace()`. À la fin du décodage, `js/multicam-modal.js` n'appelait que `refreshLtcSummary()` (rafraîchit un texte de compteur via `GET /decode_ltc/summary`, jamais la vraie liste de clips). `_setPlayerMonoR` (basé sur `c.ltc_tc_in_sec != null`, section « Audio FS5 mono R » plus haut) continuait donc de lire des valeurs `null` périmées jusqu'à un rechargement complet forcé par un redémarrage.

## Fix
Nouvelle fonction `_refreshClipsAfterLtcDecode()` (`js/multicam-modal.js`), appelée dès que le statut de polling passe à `done` (dans `_startLtcPolling`) : recharge `clips` depuis `GET /api/project/<pid>/clips`, et si `activeClip` est défini, retrouve sa version à jour dans le tableau rechargé, la réassigne à `activeClip`, et appelle `_setPlayerMonoR(updated.ltc_tc_in_sec != null)` immédiatement. Le son bascule sur le micro dès la fin du décodage, y compris pour le clip en cours de lecture — plus besoin de redémarrer.

# État au 27 juillet 2026 — v0.3.21 : réponses aux marqueurs pas rafraîchies en direct + ratings équipe visibles sur la vignette

## Question posée : les commentaires (réponses) sur un marqueur d'un collaborateur sont-ils bien visibles ?
Vérification du code de bout en bout. La visibilité elle-même est déjà correcte des deux côtés :
- **Sur vos propres marqueurs** : `renderMarkers()` (`derush_app.html` ~L2202) affiche les réponses de `allDiscussions[activeClip.id][m.id]` sous chaque marqueur de la liste.
- **Sur les marqueurs des autres** : `renderMultiUser()` (~L3441-3448) fait la même chose dans le panneau « Avis des autres », avec en plus un formulaire pour répondre directement (`submitReply`).

**Vrai gap trouvé, pas dans l'affichage mais dans le rafraîchissement temps réel** : le handler WebSocket `discussion_updated` (`startWebSocket()`, ~L2533) ne rappelait que `renderMultiUser()`, jamais `renderMarkers()`. Si un collaborateur répond à un marqueur que VOUS avez créé pendant que vous êtes sur ce clip, la réponse apparaissait dans son panneau à lui immédiatement, mais chez vous elle n'apparaissait dans votre propre liste de marqueurs qu'au poll suivant (`startNotesPolling`, jusqu'à 60s) — pas via le WebSocket qui est censé être temps réel.

## Fix
`discussion_updated` appelle désormais `renderMultiUser()` **et** `renderMarkers()` quand un clip est actif. Une ligne de correctif, cohérence rétablie entre les deux panneaux.

## Feature — ratings de l'équipe visibles directement sur la vignette (pas seulement au survol)
Demande : pouvoir repérer d'un coup d'œil, sans survoler, si un collaborateur a mis 1 à 3 étoiles ou rejeté (❌) un clip entier.

Avant : `renderClipList()` (~L1942, ancien nom `teamDots`) affichait un simple point de couleur de 7px par collaborateur ayant noté le clip, avec le nom et la note uniquement dans l'attribut `title` (donc invisible sans survol).

Fix : le point est remplacé par une chip texte toujours visible — `<nom> <étoiles ou ❌>` — sous la ligne méta de chaque clip (`.team-ratings-row`, une chip `.team-rating-chip` par collaborateur ayant noté). Les rejets (`rating === 'X'`) reçoivent un fond rouge distinct (`.team-rating-chip.rejected`) pour ressortir immédiatement dans la liste. Couvre à la fois les ratings 1/2/3 étoiles et le rejet X, comme demandé — c'est le même champ `un.rating` qui portait déjà les deux cas, seul l'affichage change.

# État au 27 juillet 2026 (suite) — v0.3.22 : suppression des commentaires externes de test

## Demande
Sébastien avait testé le lien de review externe (retours équipe hors-Derush) pour vérifier que ça marchait, et veut maintenant supprimer ces commentaires de test du projet.

## Constat
Aucun moyen existant de le faire : `revoke_share` (bouton 🗑 Révoquer existant) supprime le **lien** (`proj['share']`, token) mais ne touchait jamais à `proj['share_comments']` — les commentaires reçus restaient stockés et affichés indéfiniment dans le panneau « Avis des autres » (section verte « 🔗 Retours externes »), y compris après révocation du lien.

## Fix
- Nouvelle fonction serveur `clear_share_comments(pid)` (`derush_server.py`, juste avant `revoke_share`) : vide `proj['share_comments']` sous verrou projet. Ne touche pas `comments_last_pulled` — comme ce curseur reste avancé, un pull automatique ultérieur ne re-télécharge pas les commentaires effacés (ils ont déjà un `ts` antérieur au curseur).
- Nouvel endpoint `POST /api/project/<pid>/share/clear_comments` (ajouté à la regex existante `share/(create|revoke|pull_comments|clear_comments)`).
- `js/share.js` : nouveau bouton « 🗑 Effacer les commentaires (N) » dans la modale de partage, visible seulement s'il y a au moins un commentaire (`commentsCount > 0`). Confirmation par re-clic sous 8s via `confirm2Step()` — même logique que le garde-fou anti-écrasement du rescan (v0.3.11) : pas de `confirm()` natif, qui casse le focus des textarea dans Electron (bug documenté plus haut). Après suppression : rafraîchit `_shareState` + `renderMultiUser()` si un clip est ouvert.

# État au 27 juillet 2026 (suite) — v0.3.23 : sync cloud en 403 sur toutes les machines — clé jamais reconfigurable

## Symptôme signalé
« Erreur 403 niveau serveur sur le petit rond rouge, sur ce PC et sur le Mac. Rien ne synchronise. »

## Diagnostic (test direct contre le serveur réel, pas de suppositions)
`curl` contre `derush_sync.php` déployé, avec l'ancienne clé codée en dur (`drift2026`) → **403**. Avec la clé longue présente dans le `derush_sync.php` local (`quFQZQC2gUr4uzNijEui6Z0tR3NyORzGtYZNShMj6Mw`) → **200**. La clé a donc été régénérée côté hébergement à un moment donné (cf. audit 2.2/2.4, "clé à remplacer par une clé aléatoire longue lors de l'activation").

Root cause plus profonde que "une machine a une vieille clé" : **il n'existe et n'a jamais existé de champ dans `derush_setup.html` pour saisir `sync_url`/`sync_key`** — malgré la doc de ce fichier ("3 étapes + champs sync") et malgré `GET /api/setup/status` qui renvoyait déjà ces valeurs (pensé pour préremplir un formulaire qui n'a jamais été câblé). Pire : `POST /api/setup` reconstruisait `new_config` à partir de zéro sans jamais reporter `sync_url`/`sync_key` — donc **toute resoumission de l'assistant (juste le dossier ou le port) effaçait silencieusement la sync**, qui retombait sur les valeurs par défaut codées en dur dans `SYNC_URL`/`SYNC_KEY` (`.get('sync_url', 'https://...')`, `.get('sync_key', 'drift2026')`). Confirmé sur cette machine : `%APPDATA%\DerushTool\derush_config.json` (le vrai fichier utilisé par l'exe packagé, pas celui du dossier source) ne contenait ni `sync_url` ni `sync_key` du tout.

## Fix
- `POST /api/setup` (`derush_server.py`) accepte désormais `sync_url`/`sync_key` dans le body, et les **préserve** si absents/vides plutôt que de les effacer (`body.get('sync_url') or CONFIG.get('sync_url', SYNC_URL)`). S'applique en live (`SYNC_URL`/`SYNC_KEY` réassignés, déjà dans le `global` de `_dispatch_post`).
- `derush_setup.html` : 2 nouveaux champs optionnels dans l'étape 0 — "URL de sync cloud" et "Clé de sync cloud" — préremplis depuis `/api/setup/status`, envoyés dans `saveFolder()`.
- `sync_project()` : message générique `Erreur serveur {code}` remplacé par le message explicite (clé incorrecte, cf. audit 2.2) sur 403 — jusqu'ici seuls `/api/projects` et `join_with_key` avaient ce message, pas le sync principal qui alimente le dot ☁️.
- `_sync_url_for()` avait perdu son `?key=` en query string lors d'un refactor précédent (migration vers l'en-tête `X-Sync-Key` seul) — remis en plus de l'en-tête, par cohérence avec tous les autres appels sync du fichier (défense en profondeur si jamais le PHP déployé ne supporte pas encore l'en-tête).
- Réparation immédiate de cette machine : `sync_url`/`sync_key` ajoutés à la main dans `%APPDATA%\DerushTool\derush_config.json` (valeur correspondant au `derush_sync.php` réellement déployé, vérifiée par test direct). Nécessite un redémarrage de l'app pour prendre effet (le process qui tournait avait chargé l'ancienne config vide en mémoire).

## Pour le Mac (pas de correctif possible à distance)
Le chemin équivalent sur Mac est `~/DerushTool/derush_config.json` (PAS `~/Library/Application Support/` : `APP_DIR` retombe sur `Path.home() / 'DerushTool'` faute de variable d'environnement `APPDATA` sur cette plateforme). Tant qu'un nouveau build Mac avec les champs sync n'est pas installé, il faut soit éditer ce fichier à la main (ajouter `sync_url`/`sync_key`), soit attendre un rebuild Mac puis passer par `/setup` → nouveaux champs.

# État au 27 juillet 2026 (suite) — v0.3.24 : build "prêt à l'emploi" pour la sync — plus besoin de saisir la clé à la main

## Demande
Après le fix 0.3.23 (champs sync dans l'assistant), Sébastien doit quand même corriger la clé à la main sur chaque machine. Demande : un build Mac qui embarque directement la bonne clé, pour que Paola n'ait rien à saisir.

## Contrainte de sécurité à respecter
Le repo GitHub est **public** (`davebixby/derush-tool`). Il est hors de question de coder la vraie `sync_key` en dur dans `derush_server.py` — ça la publierait dans l'historique git pour toujours (exactement le risque que le projet évite déjà pour `derush_sync.php`, gitignored depuis le début avec un template `.example.php`).

## Solution : seed gitignored, même pattern que `derush_sync.php`
Nouveau fichier `derush_config.seed.json` (racine du projet, **gitignored**), contenant la vraie `sync_url`/`sync_key`. Template public `derush_config.seed.example.json` commité à sa place pour la doc (mêmes placeholders que `derush_sync.example.php`).

`derush_server.py` : nouvelle fonction `_load_sync_seed()` qui lit `BUNDLE_DIR / 'derush_config.seed.json'` s'il existe (silencieux sinon). Chaîne de priorité pour `SYNC_URL`/`SYNC_KEY` :
1. `derush_config.json` de la machine (si déjà configuré — prime toujours, jamais écrasé)
2. Seed bundlé (la vraie clé, seulement présente sur les machines qui buildent avec le fichier local)
3. Placeholder public codé en dur (dernier recours pour un tiers qui clone le repo public et build sans avoir le seed)

`derush.spec` : bundle `derush_config.seed.json` dans les datas **seulement s'il existe** sur la machine de build (`*( [...] if (ROOT / 'derush_config.seed.json').exists() else [] )`, même pattern que le bundling conditionnel de `ffmpeg.exe`/`ffprobe.exe`).

## Validé par test direct
Config locale temporairement retirée (`derush_config.json` renommé), réimport du module → `SYNC_KEY` récupéré correctement depuis le seed (pas depuis le placeholder). Confirme le fallback avant de livrer.

## Pour builder le Mac avec le seed
`zip_for_mac.ps1` n'exclut aucun fichier par nom générique (seulement `dist/build/node_modules/projects/.git/__pycache__/thumbnails/waveforms/sync_fingerprints` + les binaires ffmpeg Windows) — `derush_config.seed.json`, présent à la racine sur cette machine, est donc automatiquement inclus dans le zip transféré. Sur le Mac : `./build_mac.sh` bundle le fichier tel quel (même logique conditionnelle dans `derush.spec`, cross-plateforme). Résultat : l'app Mac de Paola aura la sync déjà configurée dès la première installation, sans passer par ⚙️ Configuration.

**Transfert allégé** : pas besoin de repasser par `zip_for_mac.ps1` juste pour propager une mise à jour du seed — copier uniquement `derush_config.seed.json` à la racine du projet sur le Mac (à côté de `derush_config.seed.example.json`) avant `./build_mac.sh` suffit, le fichier n'a besoin d'exister nulle part ailleurs que sur le disque de la machine qui build.

# État au 27 juillet 2026 (suite) — v0.3.25 : ajout de la target `.dmg` pour le build Mac

## Demande
En plus du `.zip`, pouvoir distribuer le build Mac en `.dmg` (format d'installation standard macOS, glisser-déposer dans `/Applications`) pour un collaborateur.

## Fix
`electron/package.json` : `mac.target` passe de `[{target: 'zip', arch: ['arm64']}]` à `[{target: 'zip', ...}, {target: 'dmg', arch: ['arm64']}]` — les deux formats sont produits par le même `npm run build:mac` / `./build_mac.sh`, aucun script séparé. Nouveau bloc `dmg: {sign: false}` (pas de signature de code disponible, comme `identity: null` déjà en place pour l'app elle-même — `sign: false` évite que `dmg-builder` tente quand même de signer l'image disque).

Le mécanisme de seed (`derush_config.seed.json`, v0.3.24) est **indépendant du format de sortie** — un `.dmg` construit sur une machine où le seed est présent contient la sync déjà configurée exactement comme le `.zip`.

`build_mac.sh` : le récapitulatif de fin de build détecte maintenant zip ET dmg séparément (`ls -t electron/dist/*.zip` / `*.dmg`), affiche les deux avec leurs instructions d'installation respectives (dézipper vs glisser dans Applications). Même avertissement Gatekeeper dans les deux cas (app non signée, clic droit → Ouvrir) — un `.dmg` ne dispense pas de ça, seule une vraie signature Apple Developer ID le ferait.

# État au 27 juillet 2026 (suite) — v0.3.26 : poll de sync local accéléré (60s → 15s)

## Demande
Discussion sur la fréquence de synchro : est-ce que descendre à 15s serait gênant à l'usage ? Réponse donnée avant modification : non pour une petite équipe — poll silencieux (pas de flicker tant que rien n'a changé), `derush_sync.php` n'a aucune limitation de fréquence, le seul coût réel est la bande passante (4× plus de requêtes vers l'hébergement partagé), trivial pour 2-3 personnes.

## Fix
`derush_app.html`, `startNotesPolling()` (~L2648) : `setInterval(..., 60000)` → `setInterval(..., 15000)`. Seul ce poll est concerné (pull-only cloud + relecture `/notes`/`/discussions`, cf. section « Sync asymétrique » plus haut). Intervalles inchangés : sauvegarde auto locale (30s), push debounced après save (3s), thread serveur de fond (vérif 90s / sync forcée 10 min), badge ☁️ (30s).

# État au 27 juillet 2026 (suite) — v0.3.27 : vignette cassée sur un clip GoPro < 1s

## Symptôme
Vignette ⚠ cassée pour `J05_2026_04_11_GOPRO_GX010141`, avec une erreur 401 en console sur `/thumbnail/...` — alors que le endpoint `/thumbnail/` (`derush_server.py` ~L2835) ne fait aucune vérification d'auth et ne peut renvoyer que 200 ou 404. Longue investigation en cul-de-sac (hypothèse clip-id divergent entre machines, hypothèse process serveur parasite sur le port 8765 — écartées : un seul process écoute sur 8765, et le fichier existe bien à l'endroit attendu par le projet, `E:\DRIFT_CLUB\J05_2026_04_11\IMAGE\GOPRO\DCIM\100GOPRO\GX010141.MP4`, confirmé par `find` direct sur le disque).

## Root cause
`clip.duration_sec = 0.96` (0,96 seconde — très probablement un déclenchement accidentel de la caméra GoPro). Le calcul de l'offset pour la vignette (~L2875) : `offset = max(1.0, duration_sec * 0.15)` → pour ce clip, `max(1.0, 0.144) = 1.0` — **au-delà de la durée réelle du fichier**. ffmpeg ne trouve aucune frame à `-ss 1.0` sur un fichier de 0,96s, le `.jpg` n'est jamais créé, `if not thumb.exists(): self.send_error(404)` renvoie 404 (le « 401 » en console était probablement un mauvais étiquetage du navigateur sur cette requête, jamais élucidé précisément — mais le vrai problème, la vignette cassée, est bien expliqué et corrigé indépendamment de ce détail).

## Fix
```python
dur = clip.get('duration_sec') or 10
offset = min(max(1.0, dur * 0.15), max(0.0, dur - 0.05))
```
Plafonne l'offset sous la durée réelle du clip, quel que soit le calcul initial. `compute_strip()` (bande de scrubbing) n'était pas concernée : sa formule (`i * duration_sec / n` pour `i` allant jusqu'à `n-1`) reste structurellement toujours sous la durée totale, aucun fix nécessaire là.

Vérifié par appel direct de `compute_thumbnail()` contre le vrai fichier (`E:\DRIFT_CLUB\J05_2026_04_11\IMAGE\GOPRO\DCIM\100GOPRO\GX010141.MP4`, offset recalculé à 0.91s) : le `.jpg` se génère correctement.

# État au 27 juillet 2026 (suite) — v0.3.28 : la vraie cause de « davebixby ne voit pas les étoiles de Sébastien »

## Résolution du fil ouvert plus haut
Cette session a exploré plusieurs pistes pour le symptôme « les 3 étoiles de Sébastien sur `DRIFT_avril0001` sont invisibles pour davebixby, même après sync manuel » : sync 403 (écarté — clé correcte, statut vert), merge_projects (écarté — simulation directe avec les vraies données du cloud confirme que le merge préserve bien `6714b070`), IDs de clip divergents entre scans (écarté — davebixby a vérifié le bon clip précisément). Toutes ces vérifications étaient correctes mais s'arrêtaient avant la vraie cause, jamais dans le code qui alimente le panneau d'affichage lui-même.

**Résolu par une session Claude Code tournant en parallèle sur la machine de davebixby**, qui a trouvé la cause réelle en lisant `GET /api/project/<pid>/config` (`derush_server.py`, la seule source de `currentProject.users` côté frontend — confirmé ici en cherchant tous les call sites de `/config` dans `derush_app.html` : 4 occurrences, toutes alimentent `currentProject`).

## Root cause
Ce endpoint retirait le champ `id` de chaque objet user avant de l'envoyer au client, avec le commentaire « Strip sensitive fields from user records » — une erreur de catégorisation : `id` n'a rien de sensible (seuls `password_hash` et la vraie valeur d'`invite_key` le sont, et cette dernière était déjà correctement remplacée par un simple booléen `pending`). Le compte de Sébastien (`{'id': '6714b070', 'name': 'Sebastien', ...}`, le seul compte de ce projet issu de l'ancien modèle par id plutôt que par username — cf. section « Système de profil global ») perdait donc son seul identifiant utilisable côté client. `renderMultiUser()`/le chip de rating (`ukey = u.id || u.username || u.name`) retombait alors sur `u.name = 'Sebastien'`, une clé **différente** de `'6714b070'` — celle où `user_note_key()` range réellement ses notes côté serveur. `allNotes['Sebastien']` n'a jamais existé → « pas encore annoté » affiché indéfiniment, pour absolument tous les autres collaborateurs, sur n'importe quelle machine (Sébastien lui-même ne pouvait jamais le remarquer : sa propre session résout sa clé côté serveur à la connexion, indépendamment de ce payload `/config`).

Confirme aussi rétroactivement pourquoi Paola et davebixby n'étaient jamais affectés en tant que « vus par les autres » : leurs comptes (créés via le système d'invitation plus récent) n'ont pas de champ `id` du tout, seulement `username` — `u.id || u.username` retombe alors correctement sur `u.username` de toute façon, aucune perte d'information dans leur cas.

## Fix
`id` n'est plus retiré de la réponse. Un seul point de code concerné dans tout `derush_server.py` (vérifié par recherche du commentaire « Strip sensitive fields »), corrigé et validé en simulant la réponse `/config` avec le vrai fichier projet : `Sebastien` a maintenant `"id": "6714b070"` dans la réponse, `Paola`/`davebixby` gardent `"id": null` (sans régression, leur résolution de clé passe déjà par `username`).

# État au 27 juillet 2026 (suite) — v0.3.29 : « Effacer les commentaires » ne supprimait vraiment rien nulle part

## Symptôme
Sébastien : « en cliquant sur Effacer, ça laisse toujours "Ok mais des lunettes c'est bizarre non", et ça ne les supprime pas sur les autres machines. »

## Root cause (deux bugs cumulés dans le fix de la v0.3.22)
1. Le fichier persistant côté `derush_sync.php` (un `.jsonl` par lien de partage, alimenté par chaque `add_comment` externe) n'était **jamais purgé** par « Effacer » — seule `revoke_share` le faisait, en tuant le lien entier au passage. Toute machine qui repullait (y compris celle qui venait de cliquer Effacer, via le poll automatique) retéléchargeait donc les mêmes commentaires depuis ce fichier resté intact.
2. `pull_share_comments()` ne faisait qu'**ajouter** les commentaires reçus au cache local, sans jamais rien retirer. Même en supposant le point 1 réglé, un cache local déjà peuplé sur une AUTRE machine ne pouvait jamais perdre un commentaire supprimé ailleurs — rien ne le lui redemandait.

Ces deux bugs cumulés expliquent exactement les deux symptômes rapportés : le commentaire revient toujours (bug 1, sur la machine qui clique Effacer elle-même, via le pull automatique suivant), et il ne disparaît jamais ailleurs (bug 2, structurellement, quelle que soit la machine).

## Fix
- Nouvelle action `clear_comments` dans `derush_sync.php` (et son template public `derush_sync.example.php`) : supprime le `.jsonl` du token sans toucher au package JSON du lien lui-même.
- `clear_share_comments()` (Python) appelle cette action en plus de vider le cache local.
- `pull_share_comments()` retélécharge désormais l'intégralité des commentaires à chaque appel (plus de fetch incrémental par `since`) et **remplace** `proj['share_comments']` au lieu de le compléter — un commentaire supprimé côté serveur disparaît donc de toutes les machines dès leur prochain pull, automatique ou manuel. Volume attendu (une poignée de commentaires pour une petite équipe) rend le coût du fetch complet négligeable.

## ⚠️ Action requise, hors code
Vérifié par `curl` direct contre le serveur en ligne : `clear_comments` n'est pas reconnu tant que le nouveau `derush_sync.php` n'est pas réuploadé sur `sebastiendelahaye.be` (le fichier déployé est gitignored, jamais mis à jour automatiquement par un git pull). Le fix Python fonctionne déjà en local (vide le cache) même sans le redéploiement, mais la propagation cross-machine reste incomplète tant que ce n'est pas fait.

# État au 27 juillet 2026 (suite) — v0.3.30 : sync systématiquement hors ligne sur macOS (certificat SSL)

## Symptôme
Sur le MacBook Pro M2 de Paola, à jour en 0.3.29 : dot ☁️ rouge, message au survol `Connexion impossible : urlopen error [SSL: CERTIFICATE_VERIFY_FAILED] ...`. Ni la clé ni l'URL de sync n'étaient en cause (ce n'est pas le bug 403 déjà connu) — sa connexion internet fonctionne par ailleurs.

## Root cause
Aucune requête réseau du fichier (`urllib.request.urlopen`, ~12 sites d'appel — sync projet, share, invite, etc.) ne spécifie de contexte SSL explicite. Sur un Python **installé normalement**, `ssl.create_default_context()` (utilisé implicitement par `urlopen`) trouve le trousseau de certificats racine via les chemins par défaut de l'OS. Sur un Python **embarqué par PyInstaller** (le cas de ce build), cet accès au trousseau système peut échouer selon la plateforme — observé ici spécifiquement sur macOS (jamais reproduit sur Windows dans cette session, malgré des dizaines de syncs testées).

## Fix
Ajout de `certifi` (déjà une dépendance transitive de pip, mais jamais importée explicitement) à `requirements.txt`. Tout en haut de `derush_server.py`, avant tout code réseau :
```python
try:
    import certifi
    os.environ.setdefault('SSL_CERT_FILE', certifi.where())
except ImportError:
    pass
```
`SSL_CERT_FILE` est lu par `ssl.get_default_verify_paths()` (donc par tout `create_default_context()` implicite derrière `urlopen`) — poser la variable avant la première requête suffit à couvrir tous les sites d'appel sans toucher à chacun individuellement. PyInstaller bundle automatiquement `certifi/cacert.pem` dès que le module est importé (hook natif, pas de configuration `derush.spec` nécessaire) — vérifié dans `dist/DerushTool/_internal/certifi/cacert.pem` après rebuild.

Sans risque de régression Windows : `SSL_CERT_FILE` pointant vers un bundle de certs valide et à jour (certifi) fonctionne aussi bien qu'un magasin de certs OS, juste une source différente pour les mêmes autorités de confiance.

# État au 28 juillet 2026 — v0.3.31 : markers des collaborateurs cliquables (seek)

## Demande
Les markers des collaborateurs apparaissaient déjà (avec réponses) dans le panneau « Avis des autres ». Demande : pouvoir cliquer dessus pour amener directement la lecture au bon endroit de la timeline — comme c'est déjà le cas pour ses propres markers (liste de gauche + pins timeline, `renderMarkers()`).

## Fix
`renderMultiUser()` (`derush_app.html`) : chaque bloc `.mu-marker` reçoit `onclick="_muSeekMarker(m.time, event)"`. Nouvelle fonction `_muSeekMarker(time, e)` (juste avant `submitReply`) : pose `player.currentTime = time`, sauf si le clic vient du formulaire de réponse imbriqué (`e.target.closest('.mu-reply-form')`) — pour ne pas voler le focus de l'input quand on répond à un marker. CSS `.mu-marker` : `cursor:pointer` + surbrillance au survol (clair/sombre).

Portée volontairement limitée au panneau « Avis des autres » : les markers de l'utilisateur courant (`renderMarkers()`) avaient déjà ce comportement (`div.onclick` sur `.marker-row` et `mousedown` sur les pins timeline), aucun changement nécessaire là.

# État au 28 juillet 2026 (suite) — v0.3.32 : fil de discussion forum sous l'avis général

## Demande + clarification
« Je trouverais ça bien aussi qu'on puisse répondre sous les avis des autres, un peu en mode forum. » Ambigu — clarifié par question à choix : pas un fil général par clip, pas des réponses imbriquées sur les markers existants, mais un formulaire de réponse rattaché à l'**avis global** (rating + note) de chaque collaborateur, en plus des réponses déjà possibles sur ses markers.

## Implémentation — zéro changement serveur
Le mécanisme de réponse (`proj['discussions'][clip_id][marker_id]`, endpoint `POST /reply`, merge par union de timestamps dans `merge_projects`) est déjà générique : rien ne valide qu'un marker de cet id existe réellement dans les notes du clip. Réutilisé tel quel avec un id synthétique **`'note_' + ukey`** (`ukey` = même clé d'identité que `user_note_key()` côté serveur — `id`/`username`/`name`) pour porter le fil « avis général » d'un collaborateur sur un clip.

`renderMultiUser()` (`derush_app.html`) : chaque bloc `.mu-block` reçoit un `.mu-note-thread` (réponses existantes + `<input>`/bouton ↩, même markup que `.mu-reply-form` des markers) après la note et les markers — y compris dans le cas « pas encore annoté » (permet de relancer un collaborateur avant même qu'il ait noté le clip). CSS : `.mu-note-thread .mu-replies` a une bordure gauche en pointillés pour se distinguer visuellement des réponses de marker (bordure pleine).

Le rafraîchissement temps réel (`discussion_updated` WebSocket → `renderMultiUser()` + `renderMarkers()`, déjà en place depuis la v0.3.21) couvre ce nouveau fil sans modification : `renderMultiUser()` reconstruit tout son HTML depuis `allDiscussions` à chaque appel, qu'il s'agisse d'un `marker_id` réel ou synthétique.

# État au 28 juillet 2026 (suite) — v0.3.33 : son uniquement à droite sur Mac (hypothèse, non vérifiée)

## Symptôme
« Sur mac je n'entends que le son à droite, avec ou sans écouteurs. » YouTube sur la même machine joue les deux canaux normalement, jamais reproduit sur Windows dans cette session — donc probablement isolé au graphe WebAudio de Derush, pas à un réglage système.

## Root cause (hypothèse la plus solide trouvée, pas confirmée sur machine réelle)
Trois endroits construisent un graphe WebAudio pour le son des clips — `_attachPlayerAudio()` (`derush_app.html`, lecteur principal, **actif sur tous les clips**), `_attachCmpSlotAudio()` (`js/compare.js`, comparateur, **actif sur tous les clips**), `_mcAttachAudio()` (`js/multicam-viewer.js`, viewer multicam, actif seulement sur les clips avec LTC) — tous avec le même pattern `createMediaElementSource` → `ChannelSplitter`/`ChannelMerger` → `ctx.destination`, sans jamais fixer le nombre de canaux de la destination.

Indice trouvé en comparant au code voisin : `_routeBwfMultiChannel()` (`js/audio-bwf.js`, pour le "Son ingé" BWF multipistes) force déjà `src.channelInterpretation = 'discrete'` — preuve que ce fichier a déjà eu affaire à un problème de mixage de canaux par le passé, mais ce traitement n'a jamais été étendu au chemin audio ordinaire des clips. Sur un Mac dont la sortie audio expose plus de 2 canaux au navigateur (haut-parleurs "spatial audio" des MacBook Pro récents type M1 Pro/Max/M2 Pro/Max, ou une sortie agrégée), Chromium up-mixe un signal stéréo brut connecté à une destination >2 canaux selon un layout de haut-parleurs ("speakers") qui ne correspond pas forcément au signal réel — classe de bug Web Audio documentée pouvant faire atterrir tout le son sur un seul canal physique.

## Fix
Nouvelle fonction `_pinStereoDestination(ctx)` (`derush_app.html`, définie dans le script inline principal donc visible de tous les modules `js/*.js` chargés après) :
```javascript
function _pinStereoDestination(ctx) {
    try {
        const dest = ctx.destination;
        const maxCh = dest.maxChannelCount || 2;
        dest.channelCount = Math.min(2, maxCh);
        dest.channelCountMode = 'explicit';
        dest.channelInterpretation = 'speakers';
    } catch(e) {}
}
```
Appelée juste après `new AudioContext()` dans les 3 sites de création de contexte (`_attachPlayerAudio`, `_attachCmpSlotAudio`, `_mcAttachAudio`). `_routeBwfMultiChannel()` réutilise un contexte déjà créé par l'un de ces 3 sites — pas besoin d'y toucher séparément, il en bénéficie automatiquement.

Sans effet sur une sortie 2 canaux standard (le cas normal — `maxChannelCount` vaut alors déjà 2, aucun changement de comportement, donc aucun risque de régression Windows).

## ⚠️ Non vérifié
Pas de machine Mac disponible dans cet environnement pour reproduire/confirmer directement. Nécessite un rebuild Mac (`build_mac.sh`) + retest par Paola avant de considérer le bug clos. Si le symptôme persiste après ce fix, il faudra investiguer en conditions réelles (`ctx.destination.maxChannelCount`/`channelCount` dans la console DevTools Mac, lister les périphériques audio via `navigator.mediaDevices.enumerateDevices()`).

# État au 28 juillet 2026 (suite) — v0.3.34 : un tag non validé "colle" au clip suivant

## Symptôme rapporté
« Quand Paola met "sanglier" comme tag sous un clip, si elle clique un autre clip, "sanglier" s'affiche comme tag [dessus]. Quand elle recherche "sanglier" dans la barre de recherche ça n'affiche aucun clip. »

## Pistes écartées
Hypothèse d'IDs de clip dupliqués (`clip_id = f"{day}_{camera}_{f.stem}"`, un vrai risque en théorie si deux fichiers du même jour/caméra partagent un nom — ex. compteur de fichier remis à zéro entre cartes SD) vérifiée sur `projects/drift_club.derush.json` : aucun doublon. Écartée aussi car les `clips[]` ne sont scannés qu'une fois (généralement par l'admin) et partagés via sync — Paola ne rescanne pas sur sa propre machine, donc pas de divergence d'ID possible entre elle et les autres.

## Root cause réelle
`#tagInput` (le `<input>` de saisie des tags, `derush_app.html`) n'était **jamais vidé** dans `selectClip()` au changement de clip — seul `#clipNotes` (textarea des notes) l'était. Un tag tapé sans être validé (`Entrée` ou `,` — le seul indice pour l'utilisateur est le placeholder discret `+ tag (Entrée)…`) restait donc affiché tel quel dans le champ en changeant de clip, donnant l'illusion qu'il "appartenait" au nouveau clip. Comme il n'a jamais été validé par `handleTagInput()`, il n'a jamais existé dans `allNotes` ni été envoyé au serveur — d'où l'absence totale de résultat en recherche. Une seule cause explique les deux symptômes ; aucune corruption de données réelle.

## Fix
`selectClip()` (`js/audio-bwf.js`) vide `#tagInput.value` juste après avoir rempli `#clipNotes`, au même endroit dans le flux.

En creusant le chemin de recherche pendant ce diagnostic, gap trouvé en plus : un tag *validé* n'était poussé au serveur (donc indexé en FTS, donc trouvable en recherche) qu'à la prochaine sauvegarde périodique (`setInterval(saveNotes, 30000)`), jusqu'à 30s de latence + les 2s de debounce d'indexation côté serveur (`_schedule_index`). `handleTagInput()` et `removeTag()` (`derush_app.html`) appellent désormais `saveNotes(true)` immédiatement après modification — un tag est maintenant cherchable en quelques secondes au lieu de jusqu'à 32s.

# État au 28 juillet 2026 (suite) — v0.3.35 : tags collaboratifs (visibles pour l'équipe, colorés, filtrables)

## Constat en creusant le bug ci-dessus
« Au-delà [du bug], je me rends compte qu'elle ne peut pas voir mes tags. » Vérifié : les tags étaient strictement privés côté rendu (comme les ratings/notes), alors que `allNotes` (chargé intégralement avec le projet via `GET /api/project/<pid>/notes` → `proj.get('notes', {})`, **toutes les clés utilisateur, pas seulement la sienne**) contient déjà les tags de tout le monde en mémoire côté client. Confirmé aussi que `search_index()`/`GET /api/search` (`derush_server.py`) n'a **jamais** filtré par `user_id` — seulement par `project_id` — donc chercher un tag d'un collaborateur fonctionnait déjà côté recherche ; seul l'affichage manquait. **Aucun changement serveur nécessaire pour cette feature.**

## Demande
« Ça serait bien pour chaque utilisateur de voir les tags des autres (…) ils peuvent apparaître de la couleur de l'utilisateur ainsi on sait qui a écrit quoi. À côté du tri par caméra ou jour, ça serait super d'avoir un tri par tag cochable qui se met à jour à chaque qu'un utilisateur crée un tag. »

## Implémentation

### Tags visibles + colorés par auteur
`_clipTagEntries(clipId)` (`derush_app.html`) : parcourt `currentProject.users`, retourne `[{tag, uid, color, label}]` — un objet par (utilisateur, tag) présent sur ce clip.
- **Sous le clip actif** : nouveau bloc `#teamTagsDisplay` (juste sous `#tagInput`, dans le panneau Notes), rempli par `renderTeamTags()` — reprend `_clipTagEntries()` en excluant l'utilisateur courant, chips en lecture seule teintées `border-color`/`color`/`background` de la couleur du collaborateur (`e.color + '22'` pour un fond très léger).
- **Dans la liste des clips** (`renderClipList()`) : nouvelle variable `teamTags` = `_clipTagEntries(c.id)` (soi-même **inclus** cette fois, pour une vue complète sans ouvrir le clip), rendue dans une `<div class="team-ratings-row">` supplémentaire sous celle des ratings d'équipe (classe déjà existante, réutilisée telle quelle — même style que les chips de rating par couleur).

### Filtre par tags cochable
Nouveau bouton `#tagFilterBtn` ("🏷 Tags") à côté de `#filterCam`/`#filterDay` dans `.filter-selects`, ouvrant `#tagFilterMenu` (liste à cocher, position absolue, `z-index:60` cohérent avec les autres popups de la page).
- `_allProjectTags()` : vocabulaire complet des tags du projet, calculé en parcourant `Object.values(allNotes)` (toute l'équipe) — pas d'appel serveur dédié.
- `_rebuildTagFilterMenu()` : reconstruit la liste de checkboxes depuis `_allProjectTags()`, préserve les cases cochées (`_tagFilterSelected`, un `Set`), retire silencieusement de la sélection un tag qui n'existe plus nulle part (dernier clip démarqué), met à jour le libellé du bouton (`🏷 Tags (N)`) et sa classe `.active-filter`.
- Filtrage OR dans `renderClipList()` : un clip passe le filtre s'il porte **au moins un** des tags cochés, toute l'équipe confondue (agrège `Object.values(allNotes)` par clip).
- **Live update** : `_rebuildTagFilterMenu()` appelée à chaque rafraîchissement de `allNotes` — chargement initial du projet, poll 15s (`startNotesPolling`), WebSocket `notes_updated` — ainsi qu'immédiatement après un ajout/suppression de tag local (`handleTagInput`/`removeTag`). Un nouveau tag créé par un collaborateur apparaît donc dans le menu sans avoir à rouvrir le projet.
- **Pattern d'ouverture/fermeture** : inspiré du combo du comparateur (`_cmpToggleCombo`/`_cmpComboOutsideClick`, v0.3.13 — écouteur `click` en phase de capture, `{once:true}`, ajouté *pendant* le dispatch du clic d'ouverture donc jamais déclenché rétroactivement par ce même clic). Adapté ici car le menu à cases à cocher doit rester ouvert tant qu'on coche plusieurs tags (contrairement à une sélection unique) : `_tagFilterOutsideClick(ev)` ignore les clics dont la cible est à l'intérieur du menu (`menu.contains(ev.target)`) ou sur le bouton toggle lui-même, et ne se retire (`removeEventListener`) qu'au moment où il ferme réellement le menu.

# État au 28 juillet 2026 (suite) — v0.3.36 : la recherche ne matche plus le nom de fichier des clips

## Demande
Retour immédiat après le fix de tags (v0.3.34/35) : « si je veux utiliser le tag drift, il va m'afficher tous les clips avec le nom drift, or je veux une recherche par tag. » Le projet s'appelle DRIFT_CLUB, clips nommés `DRIFT_avril0010` etc. — chercher le tag « drift » remontait donc aussi tous les clips juste à cause de leur nom de fichier (source `clip_meta` dans l'index FTS, qui indexait `stem`/`filename`/`camera`/`day`/`tc_in`), noyant le vrai résultat recherché.

## Fix
- **Serveur** (`_index_project_db()`, `derush_server.py`) : suppression complète du bloc qui insérait la ligne `clip_meta` (stem/filename/camera/day/tc_in) dans `notes_fts`. La table `clip_by_id`/`clips` locale à la fonction n'était utilisée que par ce bloc — supprimée avec lui (code mort sinon). La recherche ne porte plus que sur `note`/`tag`/`marker`/`reply` — ce que l'équipe a réellement écrit. Aucune migration nécessaire : `_index_project_db` fait `DELETE FROM notes_fts WHERE project_id = ?` puis réinsère à chaque appel (déclenché par tout save via `_schedule_index`, ou par `_rebuild_index_full()` au démarrage du serveur, lancé en thread de fond) — les anciennes lignes `clip_meta` disparaissent au premier reindex qui suit le déploiement.
- **Client, repli local** (`renderClipList()`, `derush_app.html`, chemin utilisé pour une recherche <2 caractères ou si le fetch FTS échoue) : ne teste plus `c.stem + c.camera + c.day`, uniquement les tags — mais élargi au passage pour agréger les tags de **toute l'équipe** sur ce clip (`Object.values(allNotes)`), pas seulement ceux de l'utilisateur courant, pour rester cohérent avec le comportement serveur (qui n'a jamais filtré par `user_id`).

## Vérifié en conditions réelles (pas juste en lecture de code)
Serveur relancé (déclenche `_rebuild_index_full()`) puis requêtes directes contre `/api/search` sur le vrai projet `drift_club` : `?q=poulet` (tag réel du projet) → 1 résultat, le bon clip. `?q=drift` → 0 résultat (aucun clip n'a "drift" en tag/note/marker/réponse, malgré des dizaines de clips nommés `DRIFT_avril00xx`) — avant le fix, cette même requête aurait remonté toute la liste.

## Ce qui reste inchangé
Les filtres caméra/jour (`#filterCam`/`#filterDay`) restent le bon outil pour retrouver un clip par son nom — volontairement pas remplacés, la recherche texte devient un outil dédié au contenu écrit par l'équipe plutôt qu'aux métadonnées de fichier.

# État au 30 juillet 2026 — v0.3.37 : sélections in/out + panier (pré-montage)

## Pourquoi
Jusqu'ici l'unité d'annotation était le marqueur ponctuel (+ les X pour couper) : l'outil sert à *rapporter* ce qui est bon, pas à *assembler* une sélection jouable. Nouvelle brique : une « sélection » est un segment in/out nommé/taggué sur un clip ; un « panier » est une bobine personnelle réordonnable de sélections, jouable bout-à-bout et exportable en séquence NLE — le dérushage produit un embryon de montage, pas seulement un rapport.

## Décision de design : panier personnel, visible par l'équipe
Comme les markers/tags, chaque user a **son propre panier** — aucun risque de conflit de fusion sur l'ordre (deux personnes qui réordonnent en même temps). Mais contrairement à un panier strictement privé, **tout le monde peut voir le panier de tout le monde** (menu déroulant dans l'overlay, lecture/export possibles) — seul l'auteur peut le modifier. Décision explicite de l'utilisateur (pas la recommandation initiale « panier partagé équipe »), cohérente avec le principe déjà en place pour les notes/tags : `allNotes`/`allBaskets` sont chargés intégralement côté client (toutes les clés user), l'édition est juste bornée à sa propre clé.

## Modèle de données
Les sélections vivent **dans le même objet que les markers** (`notes[uid][clip_id]`) — undo/redo (`pushUndo`/`undo`) et sauvegarde (`POST /notes`) les couvrent gratuitement, aucun changement serveur requis pour ce côté-là :
```json
"notes": {
  "<user_id>": {
    "<clip_id>": {
      "markers": [...],
      "selects": [{"id":"a1b2c3d4","in":12.4,"out":18.9,"name":"Beau plan drift","desc":"","tags":["golden hour"]}]
    }
  }
}
```
Le panier est un nouveau champ top-level `proj['baskets'][user_id]`, liste ordonnée de références (pas de duplication des données de la sélection) :
```json
"baskets": {
  "<user_id>": [{"id":"b1","clip_id":"<clip_id>","select_id":"a1b2c3d4"}]
}
```
Une entrée de panier orpheline (clip ou select supprimé depuis l'ajout) est ignorée silencieusement partout (rendu, export) — `_basket_entries()` côté serveur, `.filter(r => r.clip && r.sel)` côté client.

## Endpoints (`derush_server.py`)
```
GET  /api/project/<pid>/basket                        (tous les paniers, comme /notes — pas d'auth requise, cohérent avec le reste des GET)
POST /api/project/<pid>/basket                         body {basket:[...]} — sauve sous la clé résolue via user_note_key(session), même pattern que POST /notes
GET  /api/project/<pid>/export/basket_fcpxml?user=<uid>&label=...
GET  /api/project/<pid>/export/basket_xml_fcp7?user=<uid>&label=...   (Premiere)
```
`merge_projects` fusionne `baskets` exactement comme `notes` (§5 de l'audit) : chaque machine ne republie que le panier de son propre `own_uid`, garde la version cloud pour les autres — sinon une réorganisation locale périmée écraserait un retrait fait ailleurs. WS : nouveau type `basket_updated` (broadcast après chaque `POST /basket`, sur le même modèle que `notes_updated`).

## Exports (`derush_exports.py`)
`export_basket_fcpxml(project, user_key)` / `export_basket_xml_fcp7(project, user_key)` — **pas de filtre rating/X** ici contrairement à `export_fcpxml`/`export_rough_cut_fcpxml` : le contenu et l'ordre sont la décision explicite de l'utilisateur (ce qu'il a mis dans son panier, dans l'ordre où il l'a rangé), pas une inférence depuis les notes d'équipe. `_basket_entries(project, user_key)` résout `[(clip, select)]` en filtrant les orphelins. `_fcp7_rate_elem`/`_fcp7_tc_elem` : les deux fonctions imbriquées qu'utilisait `export_xml_fcp7` ont été promues au niveau module (mêmes noms via alias locaux dans `export_xml_fcp7`, zéro changement de comportement) pour être réutilisées par `export_basket_xml_fcp7`.

## Frontend — création (`js/selects.js`, nouveau module)
- **Raccourcis `[` / `]`** (clavier non pris par ailleurs — `I` était déjà pris pour le marker « problème image ») : `[` pose `_pendingSelectIn` (ligne orange sur la timeline, `#pendingSelectInMarker`, créée dynamiquement) ; `]` ouvre le popup de nommage (`#selectPopup`, calqué sur `#markerPopup`). `Échap` annule un point d'entrée en attente (prioritaire sur la désélection de marker existante). Bouton `✂️ Sélection` dans `.player-controls` = équivalent clic, toggle son propre libellé (`✂️ Sélection` → `✂️ Fin →`) via `_updateSelectMarkBtn()`.
- **Changement de clip** (`selectClip`, `js/audio-bwf.js`) annule silencieusement un point d'entrée en attente — un in-point du clip qu'on quitte n'a aucun sens sur le suivant.
- **Sauvegarde immédiate** : `confirmSelect`/`deleteSelect` appellent `saveNotes(true)` directement (même raison que le fix tags 0.3.34 — pas attendre le cycle de 30s).
- **Panneau `#selectsPanel`** (sous `#markersList`, dans un nouveau conteneur flex `.annotations-col` qui remplace l'ancienne largeur fixe 50% de `.markers-list` — nécessaire pour caser les deux panneaux dans la même colonne sans casser le 50/50 avec `.note-area`). Liste (`renderSelects()`, appelée en fin de `renderMarkers()` — donc automatiquement à jour partout où `renderMarkers()` l'est déjà : `selectClip`, `undo()`, WS `notes_updated`, poll 15s) + rangées translucides sur la timeline (`.timeline-select-range`, sous les pins de marker).

## Frontend — panier (`js/selects.js`)
- **Bouton `📽️ Panier`** dans `.player-toolbar`, badge `#basketBadge` = taille du panier de l'utilisateur courant.
- **Overlay `#basketOverlay`** (plein écran, même famille que `#compareOverlay`) : sélecteur d'utilisateur (`#basketUserSel` — soi-même toujours en premier, « 📽️ Mon panier » vs « 👁 <nom> » pour les autres), liste glisser-déposer (HTML5 DnD natif, pas de lib), bouton Lire tout / Exporter (menu FCPXML/Premiere) / Vider (confirmation par re-clic sous 8s, `_basketClearConfirmUntil` — même garde-fou anti-`confirm()`-natif que le rescan 0.3.11 et le clear share comments 0.3.22) / Fermer.
- **`_basketLastResolved`** : cache du dernier rendu résolu `[{item, clip, sel}]`, indispensable pour que drag/suppression/lecture retrouvent la bonne entrée réelle dans `allBaskets[uid]` par **identité d'objet** (`arr.indexOf(r.item)`) plutôt que par index brut — un panier contenant une entrée orpheline (filtrée à l'affichage) ferait sinon diverger l'index affiché de l'index réel.
- **Lecture bout-à-bout** (`_basketPlayFrom`/`_basketPlayCurrent`/`_basketAdvance`) : réutilise `selectClip()` pour changer de clip, puis un listener `loadedmetadata` posé **après** celui de `selectClip()` force `currentTime = sel.in` — même pattern déjà établi et documenté pour `swapToAngle` (le listener posé en second gagne sur la reprise de position générique `_clipResumeTime`). Un seul listener `timeupdate` persistant vérifie `currentTime >= sel.out` pour avancer à l'item suivant.
- **Visibilité vs édition** : `renderBasketOverlay()` calcule `isMine = _basketViewUser === currentSession.user_id` — drag, suppression et bouton Vider masqués/désactivés si on regarde le panier d'un collaborateur ; lecture et export restent possibles dans les deux cas (lecture seule, sans risque).

## Sync temps réel
WS `basket_updated` → refetch `/basket` + `_updateBasketBadge()` + `renderBasketOverlay()` si l'overlay est ouvert (même branche `onmessage` que `notes_updated`/`discussion_updated`). Poll 15s (`startNotesPolling`) refait aussi un `GET /basket` et fusionne les clés des autres users (préserve la sienne, pas encore sauvée) — même logique que la fusion des notes dans ce même poll.

## Vérification effectuée
Backend : import propre, `export_basket_fcpxml`/`export_basket_xml_fcp7` testés directement (XML bien formé, `ET.fromstring` sans erreur), `merge_projects` avec `baskets` testé (own_uid préservé, autres users hérités du remote). Puis un vrai serveur HTTP lancé sur un projet jetable (PROJECTS_DIR redirigé vers un dossier temporaire, session injectée dans `SESSIONS`) avec de vraies requêtes `urllib` : GET/POST `/basket` (y compris une entrée orpheline volontaire, silencieusement ignorée à l'export), export FCPXML/XML Premiere, 400 si `?user=` manquant — tout passe. Frontend : `node --check` sur les 12 modules `js/*.js` + le script inline principal (aucune erreur de syntaxe) ; vérification croisée automatisée de tous les `getElementById(...)`/`onclick="fn(...)"`/classes CSS introduits — aucun identifiant ni fonction manquants. **Pas de clic-through dans un vrai navigateur** : aucun outil d'automatisation navigateur disponible dans cet environnement pour cette session — à faire manuellement avant de considérer le point clos (créer une sélection avec `[`/`]`, vérifier le popup, ajouter au panier, glisser-déposer pour réordonner, lire bout-à-bout, exporter).

## v0.3.38 — retour terrain immédiat (premier vrai test utilisateur)

**« J'ai bien sélectionné une portion de clip (vert dans la timeline) mais je ne le vois pas dans panier. »** Cause : `confirmSelect()` créait la sélection dans `notes[uid][clip_id].selects` mais ne la poussait jamais dans `baskets[uid]` — il fallait cliquer un bouton 📽️ séparé sur la ligne du panneau ✂️ Sélections, visible seulement au survol (`.select-actions { opacity:0 } :hover { opacity:1 }`, même pattern que `.marker-actions`). Une étape supplémentaire non découverte, vécue comme un bug plutôt qu'une action volontaire.

**Fix** : nouvelle fonction `_pushToBasket(clipId, selectId)` (`js/selects.js`) qui pousse dans `allBaskets[uid]` sans notifier — réutilisée par `addSelectToBasket()` (clic manuel 📽️, avec toast) et désormais aussi appelée automatiquement dans `confirmSelect()` juste après la création d'une **nouvelle** sélection (pas sur une édition). Toast combiné « ✂️ Sélection créée et ajoutée au panier 📽️ ». Le bouton 📽️ manuel reste utile pour re-ajouter une sélection retirée du panier depuis l'overlay.

**« Ça serait bien aussi d'avoir une prévisualisation »** : le panier affichait `/thumbnail/<clip_id>` — la vignette générique du clip (offset fixe ~15% de la durée), **identique pour toutes les sélections d'un même clip**, donc inutile pour les distinguer visuellement (cas fréquent : plusieurs sélections sur le même long plan). Fix : vignette par sélection via l'endpoint scrub déjà existant, `?t=<offset entier en secondes>` (`compute_thumbnail_scrub`, caché par seconde, zéro changement serveur) — `/thumbnail/<clip_id>?t=${Math.floor(sel.in)}`. Appliqué à la fois dans le panneau ✂️ Sélections (nouveau `<img class="select-thumb">` 42×24px par ligne) et dans l'overlay 📽️ Panier (remplace la vignette générique).

## v0.3.39 — deuxième retour terrain : vignette plus grande, scrub au survol, visionneuse, tags suggérés, renommage

Quatre demandes distinctes dans un seul retour, toutes sur le panier :

**1. Renommage « Panier » → « Pré-montage »** — texte affiché uniquement (boutons, titre de l'overlay, toasts, `GUIDE.html`). **Aucun identifiant interne renommé** : `allBaskets`, `openBasket`/`closeBasket`/`saveBasket`, `#basketOverlay`/`#basketBtn`/`#basketBadge`, l'endpoint `/api/project/<pid>/basket`, le champ JSON `baskets[uid]` — tout reste « basket »/« panier » en interne. Renommer l'UI sans toucher au modèle de données évite une migration et garde la cohérence avec tout le code déjà écrit (0.3.37/0.3.38) et la doc technique existante.

**2. Vignette plus grande** : `.basket-item-thumb-wrap` passe de 64×36 à 128×72px, avec badge ▶ semi-transparent au survol (clic = lecture depuis cette entrée).

**3. Défiler les images au survol** : les 128×72 sont statiques (vignette au point d'entrée, comme avant) — le défilement se fait dans le popup flottant `#scrub-preview` déjà utilisé par le survol de la sidebar (même élément DOM réutilisé, pas de duplication). Nouveau générateur serveur `compute_select_strip(file_path, clip_id, select_id, in_sec, out_sec, n=8)` : contrairement à `compute_strip` (12 frames équidistantes sur **tout le clip**, 0→duration — inutile pour une sélection de quelques secondes dans un plan de 20 minutes, presque toutes les frames tomberaient hors plage), échantillonne uniquement entre `in_sec` et `out_sec`. Les deux fonctions partagent maintenant un cœur commun `_compute_strip_generic(file_path, cache_path, dedupe_key, t_start, t_end, n)` — refactor minimal-diff de `compute_strip`, comportement inchangé pour tous les appelants existants (sidebar). Cache : `<clip_id>_sel<select_id>_strip<n>.jpg`. Nouvel endpoint `GET /api/project/<pid>/select_strip/<clip_id>?select_id=&in=&out=&n=` (400 si params manquants/invalides, sinon même contrat que `/strip/`). Garde de course dédiée côté client (`_activeHoverSelectKey`, clé `clip.id:select.id`) — distincte de `_activeHoverClipId` (sidebar) car **deux entrées du panier peuvent référencer le même clip avec des sélections différentes** ; réutiliser la garde clip-only aurait laissé la mauvaise frame s'afficher si la souris passe rapidement d'une entrée à l'autre du même clip.

**4. Visionneuse dans le panier** — en creusant cette demande, découverte d'un vrai bug fonctionnel dans le 0.3.37 initial : `#basketOverlay` est `position:fixed; inset:0` **opaque**, il masque entièrement `#player` derrière lui. Les fonctions `_basketPlayFrom`/`_basketPlayCurrent` de la 0.3.37 pilotaient pourtant le lecteur principal cachdé — cliquer « ▶ Lire tout » lançait bien la lecture, mais **invisible** tant qu'on ne fermait pas l'overlay. Personne n'avait pu s'en rendre compte avant ce test réel (aucun navigateur disponible pour le clic-through en 0.3.37, documenté comme limite connue à l'époque). Fix : nouveau `<video id="basketVid">` dédié dans une zone `.basket-viewer` en haut de l'overlay (nom + TC affichés), le moteur de lecture retravaillé pour piloter directement `src`/`currentTime`/`play()` sur cet élément — **découplé de `selectClip()`/`_clipResumeTime`**, plus besoin du pattern « listener `loadedmetadata` posé après celui de `selectClip` » utilisé en 0.3.37 (qui n'a plus lieu d'être puisqu'on ne partage plus le lecteur principal). `_basketReleaseViewer()` (appelée par `closeBasket()`) libère le décodeur vidéo à la fermeture, même raison que `closeMcViewer`/`closeCompare` : un `<video>` avec `src` posé garde son buffer décodé en mémoire tant qu'on ne fait pas `removeAttribute('src') + load()`.

**5. Tags suggérés dans le popup de sélection** : remplace le simple `<input>` texte par un système chips + suggestions — `_selectPopupTags` (état de session du popup), `_spRenderTagChips()`/`_spAddTag()`/`_spRemoveTag()` (chips existantes, ×  pour retirer), `_spRenderTagSuggestions()` (pastilles cliquables sous le champ, tags du projet pas encore ajoutés). Nouvelle fonction `_allProjectTagsForSuggest()` — **volontairement distincte** de `_allProjectTags()` (existante depuis 0.3.35, alimente le filtre par tags de la sidebar) : elle unionne les tags de clip **et** les tags déjà posés sur d'autres sélections (`cn.selects[].tags`), alors que `_allProjectTags()` reste clip-only pour ne pas faire apparaître dans le filtre sidebar un tag qui ne matcherait jamais aucun clip. `confirmSelect()` absorbe aussi un tag tapé dans le champ mais jamais validé par Entrée/virgule (`_spAddTag(pendingTagInput)` avant de finaliser) — évite de reproduire le bug 0.3.34 (tag perdu silencieusement) dans ce nouveau contexte.

## v0.3.40 — refonte de l'overlay pré-montage : disposition 1/3+2/3, timeline de séquence, cadre, scrub en place

Cinq demandes précises sur l'overlay du pré-montage :

**1. Disposition 1/3 liste + 2/3 visionneuse** — `.basket-main` (nouveau conteneur flex-row sous `.basket-toolbar`) contient `.basket-body` (`width: 33.333%`, la liste réordonnable, inchangée fonctionnellement) et `.basket-viewer` (`flex:1`, la visionneuse). La visionneuse n'est plus un bandeau conditionnellement affiché (`.active` togglée par JS comme en 0.3.39) : elle fait maintenant partie du layout en permanence, avec un placeholder texte (`#basketViewerPlaceholder`) tant que rien n'est chargé.

**2. Timeline de séquence navigable ("clips collés")** — nouvelle piste `#basketSeqTimeline` sous la visionneuse : une div par sélection du pré-montage, largeur proportionnelle à sa durée retenue (`_basketSeqSegments()` calcule les offsets cumulés), vignette + nom en fond. Une tête blanche (`#basketSeqHead`) indique la position courante dans la séquence ENTIÈRE (pas juste le segment). `_basketSeqMouseDown(e)` (clic + glisser, même pattern que `cmpSeek`/`timelineSeek`) → `_basketSeekSeqRatio(ratio)` convertit une position 0-1 sur toute la piste en `(segment, offset dans le clip)`, et route vers `_basketGoto()`.

**3. Moteur de lecture unifié** — tout (clic vignette, "Lire tout", avance auto en fin de segment, clic/glisser sur la timeline de séquence) passe maintenant par une seule fonction `_basketGoto(idx, withinOffset, autoplay)` : charge le clip si besoin (`vid.src`), seek à `withinOffset`, joue ou reste en pause selon `autoplay`. Remplace `_basketPlayCurrent()` (0.3.39, dupliquait cette logique) — simplification, pas un ajout de fonctionnalité en soi, mais nécessaire pour que "Lire tout" et le scrub de la timeline de séquence partagent exactement le même comportement (notamment le changement de clip).

**4. Réordonner influence la visionneuse en direct** — l'ancien design (0.3.39) suivait la position lue par **index** (`_basketPlayIdx`), qui devient invalide dès qu'un glisser-déposer réordonne la liste pendant la lecture. Nouveau : `_basketCurrentItemRef` retient l'**identité** de l'item chargé (référence d'objet, comme `_basketLastResolved` le fait déjà pour drag/remove depuis 0.3.37). À chaque `renderBasketOverlay()` (donc après tout drag-drop, ajout, suppression), l'index réel est retrouvé par `resolved.findIndex(r => r.item === _basketCurrentItemRef)` — si l'item a été retiré entre-temps, la lecture s'arrête proprement (`_basketStop()`) au lieu de sauter vers un autre clip par accident.

**5. Cadre appliqué à la visionneuse** — `_basketGoto()` appelle `_applyLetterbox(vid, clip.id, false)` au changement de clip (même appel que `selectClip()`/multicam, `doCrop=false` — pas de recadrage, juste les insets pour le cadre). `refreshAllAspectOverlays()` (fonction centrale existante, `derush_app.html`) étendue avec un bloc `#basketVid`/`#basketViewerVideoWrap`, gardé par `#basketOverlay.classList.contains('active')` — même pattern que les blocs compare/multicam déjà présents dans cette fonction. Hook `loadedmetadata` sur `#basketVid` (attaché une seule fois via `_ensureBasketVidHandlers()`, l'élément étant statique dans le DOM contrairement aux `<video>` de comparaison recréées par slot).

**6. Survol : toute la carte déclenche, scrub en place sur la vignette** — deux retours distincts sur le 0.3.39 : (a) le survol ne marchait que sur la petite vignette, pas toute la ligne ; (b) le défilement utilisait le popup flottant `#scrub-preview` partagé avec la sidebar, alors que la demande était explicite de scruber **sur la vignette elle-même**, sans rien recréer à côté. Fix : `_wireBasketRowHover` (renommée depuis `_wireBasketThumbHover`) attache les listeners sur **toute la `.basket-item`** (la carte), mais calcule le ratio de scrub sur le `getBoundingClientRect()` de la vignette (clampé 0-1) — survoler n'importe où sur la carte déclenche, la position défilée reste ancrée visuellement sur la vignette. La vignette elle-même passe d'un `<img>` à un `background-image` manipulé en `background-position` (technique déjà utilisée par le popup flottant, maintenant appliquée directement sur l'élément en place au lieu d'un élément séparé) — au repos elle affiche la vignette statique (`?t=in`), au survol elle bascule sur la bande-contact de la sélection (`select_strip`) et défile.

## v0.3.41 — audio FS5 dans la visionneuse, espace, redimensionnement de la sélection

**1. Son de TC entendu dans la visionneuse du pré-montage (clips FS5)** — `#basketVid` (nouveau en 0.3.39) est un `<video>` brut, jamais raccordé au routage WebAudio mono-R que le lecteur principal (`_attachPlayerAudio`/`_setPlayerMonoR`, `derush_app.html`) et le comparateur (`_attachCmpSlotAudio`/`_setCmpMonoR`, `js/compare.js`) appliquent déjà — oubli lors de l'ajout de la visionneuse. Fix : `_attachBasketVidAudio()`/`_setBasketMonoR(on)` dans `js/selects.js`, calqué exactement sur la version comparateur (single élément au lieu d'un tableau par slot) — `MediaElementSource` → `ChannelSplitter` → deux routes (stéréo native / mono R dupliqué sur L+R) → deux `GainNode`, activé selon `clip.ltc_tc_in_sec != null` (même heuristique "FS5 jam-syncée" que partout ailleurs). Appelé dans `_basketGoto()` à chaque changement de clip, juste avant le hook cadre déjà en place (`_applyLetterbox`).

**2. Espace pilotait le mauvais lecteur** — le handler clavier global (`derush_app.html`) appelle `togglePlay()` sur `#player`, invisible derrière l'overlay plein écran du pré-montage (même défaut de conception que la visionneuse manquante en 0.3.37, cette fois sur le clavier plutôt que le clic). Fix : nouveau `_basketKeydown(e)` (`js/selects.js`), enregistré en phase de capture dans `openBasket()`/retiré dans `closeBasket()` — exactement le pattern déjà établi par `_cmpKeydown` (comparateur). Espace → `_basketTogglePlay()`, Échap → `closeBasket()` (cohérence avec les autres overlays plein écran de l'app). Garde ajoutée dans le handler global (`if (document.getElementById('basketOverlay').classList.contains('active')) return;`), même ligne que la garde compareOverlay déjà présente.

**3. Redimensionner une sélection depuis la timeline** — deux poignées (`.tsr-handle-in`/`.tsr-handle-out`, 8px, `cursor:ew-resize`) ajoutées aux extrémités de chaque `.timeline-select-range` dans `renderSelects()`. `_wireSelectRangeHandle(handle, bar, sel, edge, track, v, dur)` reproduit exactement le pattern déjà utilisé pour le drag des pins de marker dans `renderMarkers()` : pendant le glisser, seuls le style CSS de la bande et `v.currentTime` bougent (variables locales `liveIn`/`liveOut`) — **`sel.in`/`sel.out` ne sont mutés qu'au relâchement**, après `pushUndo()`, pour que Ctrl+Z restaure l'état exact d'avant le drag (pas un état intermédiaire du glisser). `MIN_DUR = 0.08s` (~2 frames) empêche une sélection de durée nulle ou négative. Sauvegarde immédiate (`saveNotes(true)`), même raison que la création/suppression de sélection (0.3.37) : pas attendre le cycle de 30s.

# État au 31 juillet 2026 — investigation « redimensionner ne met pas à jour le pré-montage » (fausse alerte) + v0.3.42 : poignées agrandies, transition fluide, trim de séquence, zoom molette

## Investigation — le bug signalé n'en était pas un

Signalement ferme de l'utilisateur sur le build Electron 0.3.41 : redimensionner une sélection déjà présente dans le pré-montage (via les poignées `.tsr-handle`) n'y répercutait pas le changement. Lecture du code : par conception le pré-montage ne stocke qu'une **référence** (`{clip_id, select_id}`), jamais les valeurs `in`/`out` elles-mêmes — `renderBasketOverlay()` les relit en direct depuis `allNotes` à chaque affichage, donc un redimensionnement devrait déjà se répercuter automatiquement, sans même fermer/rouvrir l'overlay. Le zip 0.3.41 déployé a été comparé octet pour octet à la source (`diff` sur `js/selects.js` bundlé vs source) : identique, pas de build périmée.

**Comme le raisonnement statique ne suffisait pas face à un signalement ferme et contradictoire**, reproduction en conditions réelles plutôt que suppositions supplémentaires : `derush_server` importé et démarré en process (pas subprocess) dans un script Python, `SESSIONS` peuplé directement avec un token de test (évite d'avoir à connaître le mot de passe du vrai profil), `SYNC_URL`/`SYNC_KEY` neutralisés (`sync_project` remplacée par un no-op) pour ne jamais toucher le vrai serveur de sync cloud pendant le test, `_HEARTBEAT_TIMEOUT` mis à une valeur énorme (sinon le watchdog tue le process pendant qu'on orchestre le test à la main — piège déjà documenté plus haut, section heartbeat). Projet jetable créé via `create_project()` directement (pas de passage par l'UI), pointant sur un dossier avec un clip `.mp4` synthétique généré à la volée par ffmpeg (`color=` + `sine=`) et sa copie dans un sous-dossier `Sub/` (nécessaire pour que `find_proxy()` lui attribue un `proxy_url` — sans ça `selectClip()` n'assigne jamais de `src` à la vidéo).

Piloté par Playwright (Chromium réel, pas juste `fetch`) : session restaurée via `localStorage.setItem('derush_session', ...)` avant navigation (le flow `init()` de `derush_app.html` gère déjà la restauration + `POST /api/project/enter` automatiquement si `project_id` est présent). Sélection créée par appel direct à `markSelectIn()`/`markSelectOut()`/`confirmSelect()`, puis glisser RÉEL de `.tsr-handle-out` (`page.mouse.move/down/move/up`, pas juste une mutation JS directe — sinon le test ne couvrirait pas le vrai chemin utilisateur). **Résultat : ça fonctionne** — `sel.out` change bien, et le pré-montage réaffiche la nouvelle durée à la réouverture, sans doublon créé.

**Vraie cause, trouvée en 2 allers-retours de commandes console DevTools données à l'utilisateur** (`JSON.stringify(allNotes[...].selects)` puis `JSON.stringify(allBaskets[...])`) : la sélection que l'utilisateur redimensionnait (« regard_miroir ») **n'était pas référencée dans son pré-montage du tout** — ni par `select_id`, ni même par `clip_id`, parmi les 3 entrées présentes. Ce qu'il observait en rouvrant le pré-montage n'était donc pas une version périmée de sa sélection, mais simplement les 3 autres entrées sans rapport, inchangées parce que rien ne les concernait. Confirmé résolu après un nettoyage du pré-montage côté utilisateur (vider puis re-tester en ajoutant explicitement la sélection).

**Leçon pour la suite** : le pattern « le code semble correct sur le papier → construire un harness serveur+navigateur réel plutôt que persister à relire le code » est déjà bien établi dans ce projet (sagas heartbeat/scan/ffprobe zombie/sémaphore) ; il s'applique tout aussi bien pour DISCULPER du code que pour trouver un vrai bug. Voir le harness réutilisable ci-dessous (section suivante), le même a servi à vérifier le vrai bug trouvé pendant le développement des 4 features demandées ensuite.

## v0.3.42 — poignées agrandies, transition fluide sans flash noir, trim de séquence (façon DaVinci), zoom molette

Quatre demandes suite à l'investigation ci-dessus, toutes sur `js/selects.js` + CSS `derush_app.html` :

**1. Poignées du lecteur principal agrandies** — `.tsr-handle` : zone de clic passée de 8px à 14px (`top/bottom:-7px`, `width:14px`), sans épaissir le repère visuel : un `::after` de 3px centré reste affiché, `background` plein au survol. Zéro changement JS, uniquement CSS.

**2. Transition fluide entre deux sélections lues (plus de flash noir)** — le noir au changement de plan est inhérent à tout changement de `.src` sur un `<video>` unique (le décodeur redémarre à zéro, même avec le fichier déjà en cache réseau) : aucune quantité de préchargement réseau seul ne peut l'éviter tant qu'il n'y a qu'un seul élément vidéo. Solution : **double lecteur** dans `.basket-viewer-videowrap` (`#basketVid` + nouveau `#basketVidB`), un seul « actif » à la fois (`_basketVidActiveId`, `'basketVid'|'basketVidB'`) :
- `_basketActiveVid()` / `_basketInactiveVid()` — résolvent l'élément DOM actif/inactif.
- `_basketPreloadNextSegment()` — appelée à chaque fois qu'un segment démarre (fin de `_basketGoto`), précharge le clip du **segment suivant** dans le lecteur inactif (`src` + `loadedmetadata` → `currentTime = next.sel.in`), sauf s'il s'agit déjà du même clip que l'actif (segments consécutifs sur le même plan → pas besoin de swap, le seek en place suffit et reste instantané).
- `_basketGoto(idx, ...)` — nouveau chemin rapide en tête de fonction : si le lecteur inactif a déjà ce `clip.id` en `dataset.clipId` ET `readyState >= 2`, appelle `_basketSwapActiveVideo()` (bascule laquelle des deux vidéos est visible via la classe CSS `.bv-active`, `opacity` transitionnée en 150ms) au lieu de réassigner `.src` — c'est CE rechargement de source qui causait le flash noir, pas contournable autrement.
- Routage audio WebAudio (mono-R pour les FS5) généralisé **par élément** plutôt que par un seul lecteur global : `_attachBasketVidAudio(vid)`/`_setBasketMonoR(vid, on)` stockent désormais les `GainNode` sur l'élément lui-même (`vid._gainStereo`/`vid._gainMonoR`), un seul `AudioContext` partagé entre les deux `<video>`.
- `_ensureBasketVidHandlers()` attache maintenant les listeners `timeupdate`/`loadedmetadata` aux **deux** éléments (statiques dans le DOM, jamais recréés), en ne réagissant que si l'élément qui a fireé l'event est bien celui actuellement actif (`vid === _basketActiveVid()`) — l'autre peut être en train de précharger silencieusement en arrière-plan sans déclencher d'avance de segment ou de rafraîchissement de cadre prématuré.
- `_basketReleaseViewer()` (fermeture de l'overlay) libère les DEUX décodeurs et réinitialise `_basketVidActiveId` à `'basketVid'` pour la prochaine ouverture.
- CSS : `.basket-viewer-videowrap video { position:absolute; opacity:0; pointer-events:none; transition:opacity .15s linear; }` + `.bv-active { opacity:1; pointer-events:auto; }` — remplace l'ancienne règle `video[src=""] { display:none }` qui ne gérait qu'un seul élément.

**3. Poignées de trim directement sur la timeline de séquence du pré-montage (façon DaVinci)** — chaque `.basket-seq-seg` (créé dans `_basketRenderSeqTimeline()`) reçoit deux enfants `.bseq-handle-in`/`.bseq-handle-out`, révélés au survol du segment (`.basket-seq-seg:hover .bseq-handle::after`), **seulement si `isMine`** (lecture seule sur le pré-montage d'un collaborateur, cohérent avec le reste de l'overlay). `_wireBasketSeqHandle(handleEl, seg, edge)` :
- Pendant le glisser : **aucune mutation de données**, seulement `_basketPreviewSeqWidths(idx, previewIn, previewOut)` qui recalcule les largeurs `%` de TOUS les segments (le total change avec la durée du segment en cours d'ajustement) et les applique directement via `el.style.width` sur les nœuds DOM déjà en place — pas de refetch de vignette, pas de recréation DOM, coût minimal même à haute fréquence de `mousemove`.
- **Au relâchement seulement** : `pushUndo(seg.r.clip.id)` puis `sel.in = liveIn; sel.out = liveOut;` — même principe que `_wireSelectRangeHandle` (lecteur principal) : la donnée réelle n'est écrite qu'à la fin du drag, pour un undo propre qui restaure l'état exact d'avant le glisser (pas un état intermédiaire).
- **Aucune logique de "ripple" à coder explicitement** pour ne pas écraser le voisin : les segments de la timeline de séquence ne sont jamais qu'un enchaînement de blocs, chacun avec une largeur `%` proportionnelle à SA PROPRE durée relative au total — agrandir un segment repousse mécaniquement tous les suivants (recalcul du total → nouveaux `%`), sans jamais toucher aux bornes `in`/`out` du voisin lui-même. « Raccorde automatiquement » par construction du layout, pas par une règle spéciale.
- `pushUndo(clipId)` (`derush_app.html`) généralisée pour accepter un `clipId` optionnel (par défaut `activeClip.id`, comme avant) — nécessaire ici car le clip dont on modifie la sélection depuis la timeline de séquence n'est pas forcément celui affiché dans le lecteur principal. `undo()` restaurait déjà génériquement `allNotes[uid][clipId]` quel qu'il soit ; seul le snapshot au moment du `pushUndo()` devait pouvoir cibler un clip arbitraire.

**Bug trouvé par test réel, pas par lecture de code** : première version des handles avec `left:-5px`/`right:-5px` (zone de clic débordant de 5px sur le segment voisin, pour faciliter la préhension pile à la jointure). Un test Playwright automatisé (glisser réel sur `.bseq-handle-out` du segment 0) montrait systématiquement AUCUN changement sur la sélection du segment 0, mais un `undoStack` qui grossissait quand même — signe qu'un mousedown avait bien été intercepté par UN handle, juste pas le bon. `document.elementFromPoint(hBox.x + hBox.width/2, hBox.y + hBox.height/2)` a confirmé : à cet endroit, c'est en réalité `.bseq-handle-in` du segment **suivant** qui reçoit le clic (peint après dans le DOM, donc au-dessus, à l'endroit exact où les deux zones de 5px se chevauchent). Fix : chaque poignée reste **entièrement à l'intérieur** de la boîte de son propre segment (`left:0`/`right:0`, plus de débordement négatif) — aucun chevauchement possible entre segments adjacents. Revérifié après fix : `elementFromPoint` retourne bien `.bseq-handle-out`, et la sélection ciblée change effectivement (`out: 2 → 2.34`), avec `undo()` qui la restaure exactement à `2`.

**4. Zoom molette sur la timeline de séquence** — nouveau conteneur `#basketSeqTimelineScroll` (`overflow-x:auto`) enveloppant `#basketSeqTimeline`, qui devient large de `_basketSeqZoom * 100%` au lieu de `100%` fixe. `_basketSeqWheel(e)` (attaché en `onwheel` sur le conteneur de scroll) : `preventDefault()`, facteur `×1.2`/`÷1.2` par cran (borné `[1, 25]`), zoom **ancré sous le curseur** (calcule le ratio horizontal du curseur dans la track avant redimension, puis règle `scrollEl.scrollLeft` après pour que ce même point reste sous le curseur — comportement DaVinci/Premiere). Les largeurs `%` des `.basket-seq-seg` restent relatives à leur parent direct (la track), donc se recalculent automatiquement au changement de largeur du parent sans toucher au reste du code de rendu — aucune modification nécessaire dans `_basketRenderSeqTimeline()`/`_basketPreviewSeqWidths()` pour que le zoom fonctionne avec les poignées de trim. `_basketSeqZoom` réinitialisé à `1` dans `_basketReleaseViewer()` (fermeture de l'overlay) pour repartir propre à la prochaine ouverture.

## Harness de test réel réutilisable (serveur + navigateur, projet jetable)

Pattern qui a servi à la fois pour disculper le bug signalé plus haut ET pour trouver le vrai bug de chevauchement des handles pendant le développement des 4 features — à réutiliser pour tout futur signalement « ça ne marche pas » qui contredit une lecture de code qui semble correcte :

1. **Serveur en process** (pas subprocess) : `import derush_server as ds` puis manipulation directe des globals avant `ds.run(open_browser=False)` — `ds.SYNC_URL = ''`, `ds.SYNC_KEY = ''`, `ds.sync_project = lambda pid, push=True: {'ok': True}` (JAMAIS toucher le vrai serveur de sync cloud pendant un test), `ds._HEARTBEAT_TIMEOUT = 10**9` (sinon le watchdog tue le process pendant qu'on orchestre le test à la main). Session injectée directement dans `ds.SESSIONS[token] = {...}` (évite d'avoir besoin du vrai mot de passe du profil local). Projet jetable via `ds.create_project(name, media_root, username, color)` avec un préfixe reconnaissable (nettoyé — `pf.unlink()` sur `PROJECTS_DIR.glob('<préfixe>*.derush.json')` — au début ET après chaque run).
2. **Média synthétique** : `ffmpeg -f lavfi -i color=c=...:s=320x180:d=Ns:r=25 -f lavfi -i sine=f=...:d=Ns -c:v libx264 -c:a aac -pix_fmt yuv420p out.mp4`. Placé dans `<root>/J01/CLIP.mp4` **et copié dans `<root>/J01/Sub/CLIP.mp4`** (`find_proxy()` exige un dossier `Sub`/`Proxy` sibling ou ancêtre — sans ça `proxy_url` reste vide et `selectClip()` n'assigne jamais de `src`, la vidéo ne charge jamais, `v.duration` reste `NaN`).
3. **Playwright** (`tests/node_modules/playwright`, déjà installé pour les specs `tests/*.spec.js`) : session restaurée via `page.addInitScript(() => localStorage.setItem('derush_session', JSON.stringify({token, project_id})))` **avant** `page.goto()` — le flow `init()` de `derush_app.html` gère seul la validation (`GET /api/me`) et l'entrée dans le workspace (`POST /api/project/enter`) si `project_id` est présent, aucun besoin de simuler le clic sur la liste de projets.
4. **Piège JS** : `window.activeClip` est `undefined` même quand `activeClip` (déclaré `let` en haut niveau d'un script non-module) est bien défini — les `let`/`const` de top-level n'attachent PAS de propriété sur `window`, contrairement à `var`. Dans `page.evaluate()`, référencer la variable nue (`activeClip`, pas `window.activeClip`) puisque `evaluate()` s'exécute dans le contexte global lexical de la page.
5. **Toujours simuler le VRAI geste utilisateur**, pas un raccourci JS qui court-circuite le chemin réel : `page.mouse.move/down/move({steps:N})/up` plutôt que d'appeler directement une fonction interne — c'est ce qui a permis de détecter le bug de chevauchement des handles (une mutation JS directe de test n'aurait jamais pu révéler un problème de hit-testing DOM).

# État au 31 juillet 2026 (suite) — v0.3.43 : image en direct dans la visionneuse pendant le trim de séquence

## Demande
Suite immédiate à la v0.3.42 : en glissant une poignée de trim sur la timeline de séquence du pré-montage, voir l'image du clip se mettre à jour en direct dans la visionneuse, en fonction de là où en est le glisser — même principe que les poignées de sélection du lecteur principal (`_wireSelectRangeHandle`, qui fait déjà `v.currentTime = liveIn/liveOut` pendant le drag).

## Implémentation (`js/selects.js`)

`_wireBasketSeqHandle(handleEl, seg, edge)` — au `mousedown`, **avant même le premier mouvement** :
- Une lecture en cours (`_basketPlaying`) est stoppée (`_basketTogglePlay()`) — on prend la main manuellement sur la tête de lecture, pas de conflit avec l'avance auto de segment.
- Le segment visé devient le « courant » du pré-montage (`_basketPlayIdx = seg.idx`, `_basketCurrentItemRef = seg.r.item`, `_highlightBasketPlaying()`, `_updateBasketViewerInfo(seg.r)`) — cohérent avec le mécanisme de suivi par identité déjà en place (v0.3.40), donc `renderBasketOverlay()` au `mouseup` retrouve le bon index sans effort supplémentaire.
- `_basketPreviewLoadClip(seg.r.clip, edge === 'in' ? sel.in : sel.out)` (nouvelle fonction) charge le clip du segment dans le lecteur **actif** si ce n'est pas déjà lui, puis seek immédiatement au point de départ de la poignée — **un seul chargement par début de drag**, jamais répété pendant le glisser.

Pendant `onMove` (après le premier mouvement au-delà du seuil de 3px) : en plus de l'ajustement des largeurs déjà en place (`_basketPreviewSeqWidths`), une ligne supplémentaire `vid.currentTime = edge === 'in' ? liveIn : liveOut` sur `_basketActiveVid()` — coût quasi nul puisque le clip est déjà chargé (juste un seek, pas de rechargement de source).

## `_basketPreviewLoadClip(clip, thenSeekTo)` — réutilise le double lecteur

Ne recharge PAS bêtement une source à chaque fois : mêmes 3 chemins que `_basketGoto()` (v0.3.42) —
1. Le lecteur actif a déjà ce `clip.id` → seek direct, retour immédiat.
2. Le lecteur INACTIF a déjà ce clip préchargé (`dataset.clipId` correspond, `readyState >= 2`) → `_basketSwapActiveVideo()` (bascule crossfade déjà en place), puis seek sur le nouveau lecteur actif.
3. Sinon → chargement classique (`vid.src = clip.proxy_url`, `_applyLetterbox`, `_attachBasketVidAudio`/`_setBasketMonoR`, seek au `loadedmetadata`).

Cette réutilisation signifie que si l'utilisateur trimme un segment sur un clip qui vient d'être préchargé en tâche de fond (parce qu'il jouait juste avant le segment courant), la bascule est instantanée — sinon un vrai chargement de source a lieu, avec le flash noir habituel inhérent à un premier chargement (inévitable, mais un seul par début de drag, pas par frame).

## Vérifié en conditions réelles (même harness que la section précédente)

Scénario Playwright avec 2 clips synthétiques et 3 sélections (2 sur le clip 0, 1 sur le clip 1) :
- **Trim sur le clip déjà affiché** (segment 0, clip 0) : `_basketActiveVid().currentTime` suit le glisser en direct (2.0s → 2.25s pendant le drag), `dataset.clipId` reste `clip0` (pas de rechargement).
- **Trim sur un clip DIFFÉRENT** (segment 2, clip 1, alors que le lecteur affichait encore le clip 0) : dès le `mousedown` (avant tout mouvement), la visionneuse bascule sur `clip1` et affiche `t=3.0` (le point de départ de la poignée) — confirme que `_basketPreviewLoadClip` charge/seek immédiatement, pas seulement au premier `mousemove`. Puis `t` suit le glisser jusqu'à 3.26s.
- Zéro erreur JS sur l'ensemble du scénario.

# État au 31 juillet 2026 (suite) — v0.3.44 : Ctrl+Z dans le pré-montage

## Demande
Pouvoir annuler les actions faites dans le pré-montage (📽️) avec Ctrl+Z, comme partout ailleurs dans l'app.

## Constat de départ : le trim était déjà TECHNIQUEMENT annulable, juste invisible
`_wireBasketSeqHandle` (v0.3.42) appelle déjà `pushUndo(seg.r.clip.id)` avant de committer `sel.in`/`sel.out`. Et le raccourci global Ctrl+Z (`derush_app.html`, handler `keydown` sur `document`) n'est **jamais bloqué** par l'overlay du pré-montage — contrairement à Espace/Échap qui ont leur propre handler dédié en phase de capture (`_basketKeydown`, `js/selects.js`), le check `if (document.getElementById('basketOverlay')...active) return;` (ligne ~4060) arrive dans le handler global APRÈS le bloc Ctrl+Z (ligne ~4046), donc Ctrl+Z atteint toujours `undo()` quel que soit l'overlay actif. Le vrai manque : `undo()` ne rafraîchissait jamais `renderBasketOverlay()` après avoir restauré `allNotes` — l'annulation avait bien lieu dans les données (le pré-montage les relit en direct depuis `allNotes`, sans copie), mais restait invisible à l'écran tant qu'on ne fermait/rouvrait pas l'overlay.

## Fix 1 — `undo()` rafraîchit le pré-montage s'il est ouvert
Une ligne ajoutée en fin de la branche « notes » de `undo()` (`derush_app.html`) : `if (#basketOverlay actif) renderBasketOverlay();`.

## Fix 2 — aucune mutation de `allBaskets` n'était annulable
Ajouter une sélection au panier, la retirer, réordonner par glisser-déposer, vider le pré-montage : **aucune de ces 4 actions ne poussait quoi que ce soit sur `undoStack`**, contrairement au trim (qui passe par les notes, déjà couvert). Nouvelle fonction `_pushBasketUndo()` (`derush_app.html`, à côté de `pushUndo()`) :
```javascript
function _pushBasketUndo() {
    if(!currentSession) return;
    const uid = currentSession.user_id;
    const state = JSON.parse(JSON.stringify(allBaskets[uid] || []));
    undoStack.push({ type: 'basket', uid, state });
}
```
Appelée juste avant la mutation dans les 4 sites concernés (`js/selects.js`) : `_pushToBasket()` (couvre à la fois l'auto-ajout de `confirmSelect()` et le bouton manuel `addSelectToBasket()`, un seul point d'entrée), le handler `drop` de `_wireBasketDrag()`, `_basketRemoveAt()`, et `_basketClear()` (juste avant le `allBaskets[uid] = []` du re-clic de confirmation).

`undo()` étendu avec une branche dédiée en tête : si `last.type === 'basket'`, restaure `allBaskets[last.uid] = last.state`, rafraîchit badge (`_updateBasketBadge`) + panneau ✂️ Sélections (`renderSelects`, pour le badge 📽️✓/+) + overlay pré-montage si ouvert (`renderBasketOverlay`), puis persiste (`saveBasket()`) — et `return` avant d'atteindre la logique « notes » historique (les deux branches sont mutuellement exclusives).

## Pourquoi une seule pile plutôt que deux
`_pushBasketUndo()` pousse sur la **même** `undoStack` globale que `pushUndo()` (notes/markers/sélections), simplement discriminée par un champ `type`. Alternative envisagée et rejetée : une pile séparée dédiée au panier. Avec une pile unique, Ctrl+Z annule les actions dans leur ordre chronologique réel, y compris entrelacées (ex. : créer une sélection → ça l'ajoute au panier → la retirer manuellement du panier → Ctrl+Z, Ctrl+Z, Ctrl+Z annule les trois dans le bon ordre, peu importe où on se trouve dans l'app à chaque pression).

## Vérifié en conditions réelles (même harness que les sections précédentes)

Scénario Playwright couvrant les 4 chemins, sur un projet jetable à 2 clips synthétiques :
- **Ajout auto** (création d'une sélection via `[`/`]`) : panier passe de 1 à 2 entrées, Ctrl+Z revient à 1 — la sélection elle-même (dans `allNotes`) reste intacte, seule son entrée dans le panier disparaît.
- **Retrait** (`_basketRemoveAt`) : `["A","B"]` → `["B"]` après retrait, Ctrl+Z restaure exactement `["A","B"]` (ordre inclus), et le nombre de `.basket-item` dans le DOM repasse bien à 2 (confirme le rafraîchissement de l'overlay).
- **Réorganisation par VRAI glisser-déposer natif** : `page.mouse.move/down/move/up` sur un élément `draggable="true"` déclenche bien nativement `dragstart`/`dragover`/`drop` dans Chromium (pas besoin de simuler l'API HTML5 DnD séparément — enseignement à retenir pour de futurs tests sur `.basket-item`/`_wireBasketDrag`) : `["A","B"]` → `["B","A"]` après glisser, Ctrl+Z restaure `["A","B"]`, noms de sélection dans le DOM revérifiés dans le bon ordre.
- **Trim d'un segment** (poignée de la timeline de séquence) : `sel.out` passe de `5` à `5.145`, texte affiché dans le panier passe de `2.0s` à `2.1s` ; Ctrl+Z restaure `sel.out = 5` **et** le texte affiché repasse à `2.0s` (confirme le Fix 1).
- Zéro erreur JS sur l'ensemble des 4 scénarios.

**Piège de test rencontré (pas un bug applicatif)** : une première version du test combinait un glisser-déposer réel ET une mutation manuelle redondante via `page.evaluate()` pour « simuler » le même réordonnancement — comme le glisser réel avait déjà suffi (cf. point ci-dessus), les deux mutations s'annulaient visuellement l'une l'autre, donnant l'illusion trompeuse qu'aucun changement n'avait eu lieu. Corrigé en ne gardant que le glisser réel — leçon générale : quand un test combine une interaction UI réelle et un raccourci JS censé produire le même effet, vérifier d'abord que l'un des deux n'est pas déjà suffisant à lui seul avant d'empiler les deux.

# État au 31 juillet 2026 (suite) — v0.3.45 : champ de tag inatteignable en scrollant dans la fenêtre principale

## Signalement
« Sur la fenêtre principale quand je scrolle en bas je n'ai plus accès au champ de saisie manuelle de tag, elle dépasse de la fenêtre. »

## [[measure-before-guessing-layout]] : mesurer avant de deviner
Plutôt que de retoucher du CSS à l'aveugle sur un bug de géométrie (leçon déjà établie ailleurs, cf. mémoire persistante), même harnais serveur+navigateur réel que les investigations précédentes de cette session : clip peuplé artificiellement avec 25 tags, 15 markers, ET l'avis complet d'un second collaborateur simulé (`allNotes['collab2']` avec rating + note longue + 3 markers, `currentProject.users` étendu en conséquence) — puis mesure directe de la géométrie (`getBoundingClientRect`, `scrollHeight`/`clientHeight` de `.note-area` et `#multiUserPanel`, position de `#tagInput`) à plusieurs hauteurs de fenêtre (700px, puis 500px pour un cas extrême).

## Résultat : le scroll de `.note-area` fonctionnait déjà correctement
`.note-area { overflow-y: auto; }` (pas de `min-height:0` explicite, mais la spec flexbox résout déjà le minimum automatique à 0 pour un item avec overflow non-`visible` — pas le bug soupçonné au départ). Dans **tous** les scénarios testés, y compris à 500px de hauteur de fenêtre avec le clip densément peuplé, régler `noteArea.scrollTop = noteArea.scrollHeight` révélait bien systématiquement `#tagInput` dans les limites du viewport. Le mécanisme de scroll lui-même n'était donc pas cassé.

## Vraie cause : `#multiUserPanel` sans limite de hauteur
Le panneau « Avis des autres » (`#multiUserPanel`, dans `#multiUserPanelWrap`, tout en haut de `.note-area` — avant les Notes globales et les Tags dans l'ordre du DOM) n'avait **aucun `max-height`** : il grandit avec le nombre de collaborateurs × (rating + note + markers + fil de discussion) de chacun. Mesure directe : l'ajout d'un seul collaborateur avec un avis complet fait passer `noteArea.scrollHeight` de 434px à 786px — soit **+352px** pour une seule personne. Sur un vrai projet à plusieurs collaborateurs actifs, cet empilement peut facilement dépasser l'écran entier, obligeant à un défilement disproportionné juste pour accéder à ses propres outils d'annotation (Notes, Tags) — c'est ce que l'utilisateur vivait comme « ça dépasse de la fenêtre », même si techniquement, en scrollant assez loin, le champ restait mathématiquement atteignable.

## Fix
`#multiUserPanel` (`derush_app.html`, ligne ~1220) : `style="margin-top:4px;max-height:180px;overflow-y:auto;"` — un mini-scroll dédié pour parcourir les avis de l'équipe, indépendant et plafonné, qui ne peut plus repousser Notes/Tags en dehors de portée. Revérifié après fix, même scénario de test : `noteArea.scrollHeight` passe de 786px à 677px (économie de 109px = exactement 289 − 180, la différence entre le contenu réel de `#multiUserPanel` et son nouveau plafond), réduisant d'autant le `scrollTop` nécessaire pour atteindre `#tagInput`.

## Enseignement général
Face à un signalement de géométrie/overflow, ne pas supposer que le mécanisme de scroll lui-même est cassé sans le mesurer — ici il fonctionnait parfaitement, y compris dans des conditions extrêmes. Le vrai problème était un contenu non borné poussant un élément important loin de sa position naturelle. La mesure directe (au lieu de la simple lecture de CSS) a permis d'identifier PRÉCISÉMENT quel bloc était responsable et de combien, plutôt que d'appliquer un correctif générique (par exemple réduire `.notes-panel` ou changer sa position) qui aurait pu ne pas cibler la vraie cause.
