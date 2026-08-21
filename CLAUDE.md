# DERUSH TOOL — Guide Claude

Outil de dérushage vidéo multi-utilisateurs. Serveur Python + UI HTML monofichier.

> **⚠️ Règle de documentation (à respecter à chaque changement)**
> À chaque modification du code ou d'une fonctionnalité, Claude **doit** mettre à jour les trois fichiers de documentation : `claude.md` (ce fichier — référence technique courante, pas de journal chronologique), `guide.html` (notice utilisateur) et `journal.html` (carnet de bord, ajouter une entrée datée). Ne jamais livrer un changement sans synchroniser ces trois fichiers.
> **Historique détaillé** : les sagas de debug et le récit chronologique complet vivent dans `HISTORY.md`, pas dans ce fichier — `claude.md` doit rester une référence technique de l'état courant. Une entrée dans `HISTORY.md` peut donner lieu à UNE ligne condensée dans la section « Pièges critiques à retenir » ci-dessous si la leçon reste applicable au code actuel ; ne pas y coller le récit complet.

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
- `HISTORY.md` — archive chronologique des sagas de debug/incidents/features (extrait de `CLAUDE.md` le 2026-08-01 pour garder ce dernier léger). Ne pas re-fusionner dedans ; y ajouter les nouvelles entrées datées à la place.

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

### Autocomplete tags (août 2026)
Pendant la frappe dans `#tagInput`, un menu déroulant (`#tagAutocomplete`) propose les tags déjà créés dans le projet (via `_allProjectTags()`, la même source que le filtre par tags) qui matchent en **sous-séquence** — les lettres tapées doivent apparaître dans le tag existant dans le même ordre, pas forcément contiguës (ex. `gh` matche `golden hour`) — pour rattraper une frappe partielle/fautée avant de créer un doublon.
- `_tagSubsequenceScore(needle, hay)` : retourne l'étendue du match (plus petit = plus pertinent) ou `-1` si pas de match. Tri par score puis alphabétique, limité aux 8 premiers, tags déjà posés sur le clip actif exclus.
- Navigation **↑/↓** dans `handleTagInput(e)` (déplace `_tagAcIndex`), **Entrée** valide l'item survolé s'il y en a un (sinon crée un nouveau tag comme avant), **Échap** ferme le menu sans vider le champ.
- Logique de validation d'un tag extraite dans `_commitTag(tag)` (partagée par la frappe manuelle et le clic/Entrée sur une suggestion).
- `#tagAutocomplete` en `position: fixed` avec coordonnées calculées en JS (`renderTagAutocomplete` → `input.getBoundingClientRect()`), **pas `position: absolute`** : `#tagInput` vit dans `.note-area` qui a `overflow-y: auto`, un dropdown absolute y serait rogné dès qu'il dépasse la zone visible/scrollée (même piège déjà résolu pour le panneau du mixeur BWF).
- **Flip vers le haut si pas de place en bas** : le champ Tags est tout en bas du panneau de notes, donc `window.innerHeight - r.bottom` est souvent petit. `renderTagAutocomplete` mesure `box.offsetHeight` (menu déjà rempli/affiché) et bascule `top` au-dessus du champ (`r.top - boxH - 2`) si l'espace restant sous le champ est inférieur à la hauteur du menu **et** qu'il y a la place au-dessus — sinon les suggestions rendaient hors de la fenêtre, invisibles sans scroller la page (retour terrain 18/08/2026).
- Fermé et réinitialisé (`closeTagAutocomplete()`) partout où `#tagInput` est déjà vidé au changement de clip (`selectClip`, `js/audio-bwf.js`).

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
- `currentSpeed` — vitesse de lecture courante (0.25, 0.5, 1, 1.25, 1.5, 2)
- `_flipHState` — miroir horizontal par clip (`{clip.id: bool}`), non persisté, reset au rechargement
- `_clipResumeTime` (déclaré dans `js/audio-bwf.js`) — `{clip.id: secondes}`, position de lecture à restaurer par clip. **Persisté** dans `localStorage['derush_resume_'+currentProjectId]` (contrairement à `_flipHState`) : survit à une fermeture/réouverture de l'app, voir `_persistClipResumeTime()`/`_loadClipResumeTime(pid)`
- `selectedMarkerId` — ID (string) du marker sélectionné sur la timeline, null si aucun
- `_activeHoverClipId` — clip_id du clip survolé pour éviter les race conditions du strip
- `_pregen` — `{q: [], n: 0, max: 3}` — queue de pré-génération des thumbnails
- `_bwfMixerSettings` (déclaré dans `js/bwf-mixer.js`) — `{pid: {bwfId: {gains:[...], mutes:[...], solos:[...]}}}`, **persisté** dans `localStorage['derush_bwf_mixer_'+pid]`
- `_bwfMixerPanelState` (`js/bwf-mixer.js`) — `{audio, bwfId, channels, trackNames}` du BWF affiché dans le panneau mixeur, `null` si fermé

## derush_app.html — Fonctions JS clés

| Fonction | Rôle |
|----------|------|
| `renderClipList()` | sidebar avec thumbnails+strip, en-têtes de jour, filtres, search texte, chips rating équipe |
| `_scrollActiveClipIntoView()` | scrolle `#clip_<activeClip.id>` dans la vue — à appeler après un changement de filtre (tag/cam/jour/recherche) car `renderClipList()` vide `innerHTML` et retombe le scroll à 0, donnant l'impression que la sélection a sauté au premier clip |
| `selectClip(c)` | charge clip, affiche tech-meta, applique currentSpeed, appelle loadWaveform + renderTags. Persiste `localStorage['derush_last_clip_'+currentProjectId] = c.id` et la position de lecture du clip quitté (`_persistClipResumeTime()`) ; restaure `_clipResumeTime[c.id]` sur `loadedmetadata` du nouveau clip |
| `_persistClipResumeTime()` / `_loadClipResumeTime(pid)` (`js/audio-bwf.js`) | écrit/lit `_clipResumeTime` dans `localStorage['derush_resume_'+pid]`. `enterWorkspace()` appelle `_loadClipResumeTime(pid)` avant de restaurer le dernier clip consulté. Filet de sécurité `pagehide` (`js/audio-bwf.js`) : capture aussi la position courante si l'app est fermée sans changer de clip (sinon jamais écrite, `_clipResumeTime` n'étant mise à jour qu'au changement de clip) |
| `setSpeed(rate)` | applique `video.playbackRate`, met à jour les boutons actifs |
| `toggleFlipH()` | miroir horizontal **par clip** : toggle `_flipHState[activeClip.id]`, délègue à `_applyFlipH` |
| `_applyFlipH(on)` | flip `#player`+`#lutCanvas`+`#drawCanvas` via `scaleX(-1)`, appelée aussi par `selectClip` pour restaurer l'état du clip chargé |
| `setRating(r)` | toggle : si déjà actif → null, sinon → r |
| `addMarker(cat, desc, drawing)` | ajoute marker avec `id` unique |
| `renderMarkers()` | liste (avec selectedMarkerId) + pins timeline (drag via mousedown) + replies |
| `timeToTC(t, fps)` | secondes → "HH:MM:SS:FF" |
| `renderTags()` | affiche les tags du clip actif comme chips cliquables |
| `handleTagInput(e)` | ↑/↓ navigue l'autocomplete, Échap ferme, Entrée/virgule valide (item survolé ou saisie libre) → `_commitTag` |
| `updateTagAutocomplete()` / `renderTagAutocomplete()` / `closeTagAutocomplete()` | menu déroulant de suggestions par sous-séquence (`_tagSubsequenceScore`) sur `_allProjectTags()` pendant la frappe |
| `_commitTag(tag)` | ajoute le tag dans allNotes + renderTags + save immédiat (factorisé, utilisé par saisie libre et sélection d'une suggestion) |
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

### Preview LUT (.cube) — WebGL2 (`js/lut.js`)

**Implémentation** : texture 3D WebGL2 (`TEXTURE_3D`, filtrage `LINEAR` = trilinéaire gratuite en hardware), pleine résolution vidéo, zéro readback CPU. L'ancien pipeline Canvas 2D (`getImageData`/`putImageData`, nearest-neighbour manuel, capé à 480px) a été abandonné — sur Electron/Chromium le rendu ANGLE est fiable, le problème de drivers qui avait motivé Canvas 2D ne se pose plus.

**Pipeline du fragment shader** (`_lutInitGL`, un seul programme, tout en une passe) :
1. Exposition (`u_exposure`, EV, `pow(2, ev)`)
2. Balance des couleurs pré-LUT : température (`u_temperature`, gain différentiel R/B) + teinte (`u_tint`, gain sur G) — traitées comme une correction primaire, avant la LUT créative
3. Lookup LUT 3D (coordonnées centrées voxel, évite le biais ½-voxel)
4. Intensité (`u_intensity`) : mix source post-étapes 1-2 ↔ résultat LUT
5. Contraste (`u_contrast`) : pivot sur le gris moyen (0.5), pente `1+u_contrast`
6. Saturation (`u_saturation`) : mix vers le gris luma (coeffs Rec.709)
7. Dithering anti-banding : bruit sub-pixel ±0.5/255 décorrélé par canal, variant chaque frame (`u_time`) pour casser les patterns statiques dans les dégradés

**Réglages manuels** (`_lutSettings = {intensity, exposure, saturation, contrast, temperature, tint}`, tous neutres par défaut sauf intensity=1/saturation=1) — panneau `#lutSettingsPanel` (sliders). `setLutSetting(key, value)` met à jour + réapplique les uniforms (`_lutApplySettings`) + persiste. `resetLutSettings()` remet tout à neutre (toujours propre au plan courant, voir modèle d'assignation ci-dessous).

**Parsing .cube** : `_parseCube(text)` lit ASCII `LUT_3D_SIZE N` puis les triplets float.

#### Modèle d'assignation par plan (v0.3.5x)

Avant : une seule LUT globale + un seul scope + des réglages globaux partagés par tous les clips du scope — changer un slider sur un plan changeait donc le rendu de tous les autres clips de la même caméra, et recharger un nouveau `.cube` écrasait l'assignation précédente sans distinction.

Désormais, deux structures séparées :
- **Bibliothèque** `_lutLibrary = {lutName: {size, data}}` (cache mémoire, `lutName` = nom du fichier `.cube`) — le contenu brut est aussi persisté dans **IndexedDB** (`derush_luts` → store `files`, clé `${pid}::${lutName}`) pour survivre à un reload/relance sans devoir recharger le fichier (une LUT peut peser plusieurs Mo, hors budget raisonnable de `localStorage`).
- **Assignation** `_lutAssign = {cameras: {[camera]: {lutName, settings}}, clips: {[clipId]: {lutName, settings}}}`, persistée dans `localStorage['derush_lut_assign_' + pid]` (par projet). `clips[id]` est un override explicite propre à un plan, prioritaire sur `cameras[cam]` (défaut hérité par tous les plans de cette caméra sans override).

`_lutResolveFor(clip)` : override clip explicite > défaut caméra > rien (`null`).

- **Appliquer une LUT "à des caméras"** (`confirmLutScope`, mode `cameras`) n'écrit **jamais** dans `_lutAssign.clips` — seulement dans `_lutAssign.cameras`. Un plan qui a déjà son propre override n'est donc jamais écrasé par une application en masse malencontreuse ; la modale de scope liste en plus, pour chaque caméra, le nombre de plans déjà "protégés" par un override (`🔒 N plan(s) propre(s), non affecté(s)`) pour prévenir l'erreur avant qu'elle n'arrive.
- **Toucher un slider** (`setLutSetting`/`resetLutSettings`) sur un plan qui n'a encore qu'un défaut caméra hérité **fork** un override clip via `_lutEnsureEditableEntry()` (copie des réglages courants dans une nouvelle entrée `_lutAssign.clips[activeClip.id]`) sans jamais muter l'objet de réglages partagé par la caméra. C'est ce mécanisme qui garantit que chaque plan garde ses réglages manuels propres.
- **"Ce rush uniquement"** (mode `clip` dans la modale de scope) écrit directement un override explicite pour le plan actif.
- **Retirer une LUT d'un plan** : bouton `🗑 Retirer la LUT de ce plan` (`#lutRemoveWrap`, visible seulement si le plan a un override `clip` — pas pour un défaut `camera`) → `_lutRemoveForActiveClip()` supprime l'entrée `_lutAssign.clips[id]`, le plan retombe sur le défaut caméra s'il existe.
- Recharger un fichier `.cube` du **même nom** mutualise (met à jour partout où ce `lutName` est référencé) — comportement volontaire pour permettre de retoucher un export de grade et le repousser sans tout ré-assigner.

**Globals JS** :
```javascript
let _lutEnabled = false, _lutRaf = null, _lutGL = null, _lut = null, _lutCurrentLutName = null;
let _lutLibrary = {}, _lutAssign = {cameras: {}, clips: {}};
let _lutSettings = {intensity: 1.0, exposure: 0.0, saturation: 1.0, contrast: 0.0, temperature: 0.0, tint: 0.0};
```
`_lutGL = {gl, prog, vao, videoTex, lutTex, u_*, lutUploaded}` — un seul contexte/programme créé paresseusement (`_lutInitGL`), réutilisé ensuite (upload LUT via `_lutUploadLUT` seulement quand `_lutCurrentLutName` change, uniforms de réglage repoussés à chaque `_lutRefreshForActiveClip()`/changement de slider).

`_lutRefreshForActiveClip()` (async, protégée par `_lutRefreshToken` contre un changement de clip pendant l'attente IndexedDB) résout la LUT du plan actif, la charge si besoin (`_lutEnsureLoaded`, mémoire puis IndexedDB), met à jour canvas/badge/panneau/bouton. Appelée par : sélection de clip (`selectClip` → `js/audio-bwf.js`), `toggleLUT()`, `confirmLutScope()`, `_lutRemoveForActiveClip()`. `_lutLoadAssign(pid)` recharge `_lutAssign` depuis `localStorage` à l'entrée dans un projet (`enterWorkspace`).

**Flow utilisateur** :
1. `📂 LUT` → `<input type="file" accept=".cube">` → `onLUTFileSelected` → crée `_lutGL` si besoin (alerte si WebGL2 indisponible) → ajoute à `_lutLibrary` + IndexedDB → ouvre la modale de scope (caméras ou ce rush uniquement)
2. `🎨 LUT` → `toggleLUT()` — master preview on/off (session, pas persisté). Panneau réglages auto-affiché/masqué en même temps que le canvas (visible seulement si une LUT est résolue pour ce plan ET le master est actif)
3. Badge `LUT` affiché sur la vidéo quand actif

### Disposition des contrôles du lecteur (refonte juin 2026, save déplacé juillet 2026)

Deux zones distinctes :
- **Barre du bas `.player-controls`** (sous la vidéo, au-dessus de la timeline) = transport + lecture : TC `#tcDisplay`, ◀5s/◀1s/⏯/1s▶/5s▶, 📌 Marker, 🖌 Dessin, ⤢ plein écran, 🔊 Son ingé (`#bwfBtn`), volume (`#volIcon`+`#volSlider`), spacer flex, ⇋ Flip H (`#flipHBtn`), groupe vitesses `1×/1.25×/1.5×/2×`, **💾 Sauver**, puis `#saveStatus` (flash de sauvegarde).
- **Barre flottante verticale `.player-toolbar`** (`#playerToolbar`) = tous les **outils/actions**, en colonne d'**icônes seules** (tooltips `title`), overlay en haut-droite de `.player-area` (`position:absolute; top:8px; right:8px; z-index:20`, fond translucide + blur) : ⚡ Comparer, 🎞 Cadre (+`#aspectMenu`), 🎨 LUT (`#lutBtn`), 📂 LUT, 🔄 Multi-cam, 🎬 Session (`#sessionBtn`), 📤 Exporter, 🔗 Partager, 🩺 Health, 📊 Stats, ⌨️ raccourcis, ☁️ Sync (`#syncBtn`, dot couleur uniquement — `#syncLabel` masqué).

**Points techniques** :
- Boutons à état dynamique passés en icône seule : `setAspectFrame` → `🎞` (format dans `title`/badge), `_updateSessionUI` (`js/session-live.js`) → `🛑`/`👁`/`🎬` (état via couleur + `title`), `_updateSyncUI` → dot coloré (label masqué, statut dans `title`).
- `#aspectMenu` s'ouvre vers la gauche (`right: calc(100% + 8px); top:0`) ; `#lutSettingsPanel` décalé à `right:56px` pour ne pas passer sous la barre.
- La barre est **masquée pendant le mode dessin** (`startDrawing`/`cancelDrawing` togglent `#playerToolbar`) pour ne pas intercepter les clics du canvas dans le coin.
- `applyRoleUI` cible `button[onclick="saveNotes()"]` (maintenant dans `.player-controls`, un seul exemplaire dans le DOM) → le bouton 💾 garde son `onclick` (rôle viewer le masque toujours).

### Miroir horizontal (Flip H, août 2026 — passé en réglage par clip en v0.3.48)

Bouton `#flipHBtn` (`.player-controls`, juste avant le groupe de vitesses) → `toggleFlipH()` : toggle `_flipHState[activeClip.id]` (**par clip**, pas global — `{}` en mémoire, clip.id → bool, non persisté, reset au rechargement) et appelle `_applyFlipH(on)` qui applique `transform: scaleX(-1)` (ou `none`) directement sur `#player`, `#lutCanvas` et `#drawCanvas`. `selectClip()` (`js/audio-bwf.js`) appelle `_applyFlipH(!!_flipHState[c.id])` juste après avoir posé `activeClip = c` — sinon le flip du clip précédent resterait affiché sur le nouveau (l'élément `<video>` est réutilisé, son `style.transform` persiste tant que rien ne le réinitialise explicitement). Les trois éléments (`#player`, `#lutCanvas`, `#drawCanvas`) partagent exactement la même boîte dans `.video-wrapper` (règle CSS générique `video { width:100%; height:100%; }` / `canvas { position:absolute; inset:0; }`), donc un flip individuel de chacun reste visuellement cohérent en toute condition (LUT actif ou non, dessin en cours ou non). Nécessaire de flipper `#lutCanvas` séparément : quand la LUT est active ce canvas redessine le frame par-dessus la vidéo via `texImage2D`/`getImageData` (pixels bruts, pas affectés par le CSS transform de la vidéo source) — sans son propre flip CSS, il annulerait visuellement le miroir appliqué à `#player`. `#aspectOverlay` (cadre) n'a pas besoin d'être flippé : sa géométrie est calculée depuis le `getBoundingClientRect()` du player, inchangé par un `scaleX(-1)` en place (même boîte, juste mirroré visuellement).

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
- `detect_letterbox(file_path)` (derush_server.py) : `ffmpeg cropdetect=24:2:0` sur 80 frames (`-ss 3`) → `{top,bottom,left,right}` (fractions) **+ `cw,ch`** (dims du contenu après filtrage). Ignore le bruit (<1.5%) et l'aberrant (>35%). Multi-frames = robuste au plan sombre. **Filtre de symétrie (v0.3.49)** : une vraie bande incrustée est centrée sur le capteur (`top≈bottom` ou `left≈right`) — un inset détecté sur un seul côté d'un axe (l'autre à 0, ou très déséquilibré, tolérance 50%) est mis à zéro des deux côtés : c'est un vignettage/occlusion réel de l'image (pare-soleil, capuchon, micro dans le coin...), pas une bande à retirer.
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
| `_read_bwf_bext_direct(file_path)` | parse RIFF/WAVE en Python, lit `fmt` + `bext` (TimeReference + OriginationDate) + `iXML` (noms de piste) + `data` |
| `_parse_ixml_tracks(data)` | parse `TRACK_LIST` du chunk `iXML` → liste de noms de piste indexée sur l'ordre réel des canaux, ou `None` |
| `_read_bwf_tc_ffprobe(file_path)` | fallback via ffprobe (W64, formats exotiques) — pas de lecture iXML sur ce chemin |
| `read_bwf_tc(file_path)` | dispatcher → dict `{tc_in_sec, duration_sec, sample_rate, channels, origination_date, track_names}` |
| `scan_son_dir(son_dir)` | récursif → liste `[{id, filename, path, tc_in_sec, duration_sec, origination_date, track_names, ...}]` |
| `_clip_origination_date(clip)` | extrait `YYYY-MM-DD` depuis `creation_date` ou regex sur `id`/`path` |
| `_bwf_origination_date(af)` | normalise depuis `audio_clips`, fallback lecture à la volée |
| `_bwf_candidates_for_clips(...)` | retourne BWF qui CONTIENNENT strictement les clips (grace ±2s) ET match la date, triés par compacité — utilisé seulement par `/group_bwf` pour le playback |
| `_resolve_audio_clip_path(ac, proj)` | résout `ac['path']` (absolu, stocké tel quel au scan) sur le disque courant : match littéral d'abord, sinon retrouve le nom du dossier racine projet dans les segments du chemin stocké (résilient à un changement de lettre de lecteur) puis délègue à `_resolve_relpath_tolerant` — v0.3.46 |

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
| GET | `/api/project/<pid>/clip_bwf/<clip_id>` | BWF de référence pour UN clip (lecteur principal) → `{stream_url, filename, tc_in_sec, bwf_offset_sec, bwf_id, channels, track_names}` |
| GET | `/api/project/<pid>/multicam/group_bwf?group_id=...` | renvoie le 1er BWF candidat qui couvre le groupe (basé sur `_clip_tc_seconds` = LTC prioritaire) → mêmes champs + `earliest_id` |
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

### Mixeur multipiste du son ingé (août 2026)

Un BWF multipistes (boom + HF1 + HF2 + ambiance...) était sommé vers stéréo à **gain fixe 1/3 par piste** sans distinction. Remplacé par un mixeur : un `GainNode` indépendant par piste (mute/solo/fader 0–150%), avec les vrais noms de piste lus dans le chunk **iXML** du BWF quand l'enregistreur les écrit (Sound Devices, Zoom...).

**Serveur (`derush_server.py`)** :
- `_parse_ixml_tracks(data)` : parse `TRACK_LIST/TRACK` du chunk `iXML` (même pattern `ET.fromstring` que `parse_sony_xml`) → liste de noms indexée 0-based sur `INTERLEAVE_INDEX` (1-based dans le XML), ou `None`.
- `_read_bwf_bext_direct` : lit aussi le chunk `iXML` pendant son parcours RIFF existant. La sortie anticipée de la boucle est assouplie (`channels <= 2 or ixml_tracks is not None`) pour ne pas rater un iXML placé après `data` chez certains enregistreurs — coût quasi nul, le code ne fait que `seek` sur les gros chunks.
- `scan_son_dir` propage `track_names` dans chaque `audio_clips[]` — **nécessite un re-scan du dossier Son** sur un projet déjà scanné pour peupler ce champ.
- `GET /api/project/<pid>/clip_bwf/<clip_id>` et `GET /api/project/<pid>/multicam/group_bwf` renvoient en plus `bwf_id`, `channels`, `track_names`.

**Client (`js/bwf-mixer.js`, nouveau module)** :
- `_bwfBuildMixerGraph(audio, ctx, bwfId, channels, trackNames)` : `MediaElementSource → ChannelSplitter(8) → 1 GainNode par piste → ChannelMerger(2) → destination` (remplace l'ancien `_routeBwfMultiChannel` à gain fixe, supprimé). Stocke l'état sur `audio._bwfMixer`.
- `_bwfTeardownMixerGraph(audio)` : disconnect (remplace `_unrouteBwf`, supprimé).
- `_bwfMixerApplyGains(audio)` : relit gain/mute/solo persistés et les applique aux `GainNode`. Solo actif sur ≥1 piste → toutes les autres passent à 0 (solos cumulables).
- Persistance **localStorage par projet** (pas serveur — réglage personnel, même logique que `_lutAssign`) : `localStorage['derush_bwf_mixer_' + pid] = {<bwfId>: {gains:[...], mutes:[...], solos:[...]}}`. Clé = **id du fichier BWF** (pas du clip vidéo) : le mix reste valable sur tous les plans/groupes couverts par ce même son ingé. Gain par défaut `1/3` = comportement d'avant ce module, rien ne change tant qu'aucun fader n'est touché.
- `openBwfMixerPanel(anchorBtn)` / `closeBwfMixerPanel()` / `toggleBwfMixerPanel(e)` / `renderBwfMixerPanel()` / `_bwfMixerReset()` : panneau flottant unique `#bwfMixerPanel` (`position:fixed`, positionné dynamiquement via `getBoundingClientRect()` du bouton déclencheur — nécessaire car les deux boutons (`#bwfMixerBtn` en `.player-controls`, `#mcBwfMixerBtn` dans la toolbar `#mcViewerOverlay`) vivent dans deux zones DOM différentes, contrairement au panneau LUT qui reste toujours dans `#videoWrapper`). `z-index:500`, au-dessus de `#mcViewerOverlay` (300).

**Fix bundlé** : `openMcViewer()` créait `window._mcAudioCtx` **uniquement** via `_mcAttachAudio()` sur un angle FS5 (LTC) — un groupe multicam 100% FX6 n'avait donc jamais eu de routing multipiste correct pour le BWF (fallback downmix navigateur, 2 premières pistes seulement). Le contexte est désormais créé/pinné à la demande dans `openMcViewer()` si absent, avant d'appeler `_bwfBuildMixerGraph`.

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

**Menu clic droit / correction orthographique (v0.3.50)** : Electron n'affiche **aucun** menu contextuel par défaut (même pas Couper/Copier/Coller) — contrairement à un vrai navigateur qui gère ça nativement. `mainWindow.webContents.on('context-menu', (event, params) => …)` dans `electron/main.js` reconstruit le menu à la main : suggestions d'orthographe depuis `params.dictionarySuggestions` (clic → `webContents.replaceMisspelling(suggestion)`) quand `params.misspelledWord` est renseigné, entrée "Ajouter au dictionnaire" (`session.addWordToSpellCheckerDictionary`), puis Couper/Copier/Coller/Tout sélectionner si `params.isEditable`. Dictionnaire forcé en français via `session.setSpellCheckerLanguages(['fr'])` (Chromium ne le déduit pas toujours fiablement de la locale OS). Le soulignement rouge lui-même est natif Chromium (spellcheck des champs texte), aucune configuration requise côté `derush_app.html`.

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
10. **Path resolution cross-platform** : `_resolve_relpath_tolerant(root, rel)` walk segment par segment avec tolérance numérique (`01↔1↔001`) + case-insensitive fallback. Indispensable quand un disque source est copié entre PCs et que les noms de slot perdent leur zéro de tête (rsync, robocopy parfois). Cache positif pour ne pas re-walker à chaque requête. Pour les chemins **absolus stockés** (ex. `audio_clips[].path`) qui ne matchent plus aucune racine connue après un changement de lettre de lecteur : chercher le nom du dossier racine du projet n'importe où dans les segments du chemin stocké, puis déléguer à `_resolve_relpath_tolerant` sur ce qui suit (`_resolve_audio_clip_path`, v0.3.46 — même classe de bug déjà corrigée côté clips vidéo).
11. **Clé de notes dédoublée (`user_note_key` vs save)** : l'endpoint `POST /api/project/<id>/notes` sauve sous `s.get('user_id') or s.get('username')`, mais l'export FCPXML et le reste lisent via `user_note_key(u) = u.get('id') or u.get('username') or u.get('name')`. Si une session perd son `user_id`, les notes du même humain partent sous une 2e clé (`username`/`name`) que `user_note_key` n'atteint jamais → notes orphelines invisibles à l'export, suppressions de marqueurs appliquées au mauvais jeu. La clé de save doit être résolue via le user trouvé dans `project['users']` (donc identique à `user_note_key`), pas via la session brute. **Et l'UI indexe les notes par `currentSession.user_id`** — donc `/api/project/enter` pose `session['user_id'] = user_note_key(user)` pour que UI, `/notes` et export partagent exactement la même clé (sinon l'UI ne retrouve pas ses notes et les écrase à vide).
12. **IDs de clip orphelins après ré-import** : les `notes` sont indexées par `clip['id']`. Un re-scan / ré-import qui régénère les IDs de clip laisse les anciennes notes pointer dans le vide → marqueurs/ratings perdus silencieusement (jamais lus par l'export). Re-mapper par nom de fichier si récupération nécessaire.
13. **Verrou par projet (`_project_lock`, audit 22 mai 2026)** : `do_POST` détient `_project_lock(pid)` (RLock) pendant tout le dispatch d'une requête `/api/project/<pid>/…` → les écritures d'endpoints sont déjà sérialisées, inutile de re-verrouiller dedans. En revanche **tout code qui écrit un projet hors d'une requête `do_POST`** (job de fond, `threading.Timer`, thread) DOIT recharger le projet avec `with _project_lock(pid):` juste avant `save_project`, sinon il écrase les écritures concurrentes (lost update). `save_project` écrit de façon atomique (`.tmp` + `os.replace`) ; `load_project` est caché par (mtime, taille). Voir `AUDIT.md` §1.
14. **Jamais relire `self.rfile` deux fois** : `_dispatch_post()` lit déjà tout le corps POST une fois (`body = self._read_body()`) et le passe aux handlers. Un handler qui refait sa propre lecture (`self.rfile.read(length)`) bloque indéfiniment — le socket n'a plus rien à donner, aucun timeout configuré. Bug réel trouvé sur `/scan` (v0.3.16) et `/api/crash` : toujours réutiliser le `body` déjà fourni par le dispatcher, jamais relire.
15. **`_ffmpeg_run()` doit acquérir sa sémaphore avec un timeout** (`_ffmpeg_sem.acquire(timeout=timeout+5)`, jamais un `with` bloquant sans limite). Un `ffprobe`/`ffmpeg` peut zombie indéfiniment sur un fichier verrouillé en I/O (antivirus scannant une écriture toute fraîche, disque externe capricieux) — `TerminateProcess` ne revient parfois jamais dans ce cas. Sans timeout d'acquisition, chaque zombie fait fuiter un permis pour de bon jusqu'à épuisement total de la sémaphore, gelant tout appel ffmpeg/ffprobe de l'app entière (v0.3.17/18). `ffprobe_metadata()` (scan) passe en plus par `_ffprobe_metadata_bounded()` (thread daemon + `Event.wait(20s)`) pour ne jamais bloquer l'appelant même si le thread sous-jacent reste coincé, et utilise sa propre sémaphore dédiée `_ffprobe_meta_sem` (v0.3.19) pour ne pas faire la queue derrière la pré-génération de vignettes en tâche de fond.
16. **Heartbeat rafraîchi par toute requête HTTP entrante**, pas seulement `/api/heartbeat` (`_HEARTBEAT_TIMEOUT = 30`). Un scan/décodage long qui ne déclenche aucune requête réseau côté client peut sinon se faire tuer par le watchdog (`os._exit(0)`) sans laisser de trace dans `crashes.jsonl` — c'est un arrêt volontaire, pas une exception (v0.3.14/15).
17. **Garde-fou anti-écrasement au rescan** : `POST /scan` refuse (409) si le nouveau scan trouve moins de 50% des clips déjà présents dans `proj['clips']`, sauf `force:true` explicite. `clips[]` n'est pas per-user et un chemin racine invalide/pas encore monté écrasait silencieusement les clips de toute l'équipe (v0.3.11).
18. **`merge_projects` ne fusionne jamais `clips[]`** — chaque machine garde les siens ; seul `join_with_key` adopte le remote tel quel. Implication : la machine dont le fichier local a des clips sains s'auto-répare le cloud au prochain push, quel que soit l'état du cloud.
19. **`GET /api/project/<pid>/config` ne doit jamais retirer `id`** des objets user (seuls `password_hash` et la vraie valeur d'`invite_key` sont sensibles) — un `id` retiré casse la résolution de clé (`user.id || user.username`) pour tout compte hérité de l'ancien modèle par id, rendant ses notes/ratings invisibles aux autres collaborateurs (v0.3.28).
20. **Suppression de données synchronisées (ex. commentaires de review externe)** : purger le stockage serveur persistant (pas seulement le cache local) ET faire en sorte que le pull suivant **remplace** le cache local au lieu de fusionner par union — un pull incrémental/additif ne peut structurellement jamais faire disparaître une suppression (v0.3.29).
21. **SSL sur binaire PyInstaller (surtout macOS)** : `urlopen` peut échouer à trouver le trousseau de certs OS embarqué. Poser `os.environ.setdefault('SSL_CERT_FILE', certifi.where())` tout en haut de `derush_server.py`, avant tout appel réseau (v0.3.30).
22. **Config sync (`sync_url`/`sync_key`) jamais écrasée silencieusement** : `POST /api/setup` doit préserver les valeurs existantes si absentes du body (`body.get('sync_url') or CONFIG.get(...)`), sinon toute resoumission partielle de l'assistant efface la sync. Chaîne de priorité : config locale > seed gitignored bundlé au build (`derush_config.seed.json`) > placeholder public codé en dur (v0.3.23/24).
23. **Un champ de saisie qui porte du texte non validé doit être vidé au changement de contexte** (ex. `#tagInput` au changement de clip) — sinon il "colle" visuellement au nouvel élément sans jamais avoir été sauvegardé (v0.3.34).
24. **Mesurer avant de deviner sur un bug de géométrie/CSS** (`getBoundingClientRect`, `scrollHeight`) plutôt que de retoucher le CSS à l'aveugle — un mécanisme de scroll qui semble cassé peut fonctionner parfaitement, le vrai problème étant un contenu non borné ailleurs qui pousse l'élément visé hors de portée (v0.3.45). Voir aussi la mémoire persistante `measure-before-guessing-layout`.
25. **Face à un bug signalé qui contredit une lecture de code qui semble correcte, reproduire en conditions réelles (serveur + navigateur réel) plutôt que de continuer à relire le code** — sert aussi bien à confirmer un vrai bug qu'à disculper du code correct (v0.3.42, harnais réutilisable documenté dans `HISTORY.md`).
26. **`detect_letterbox` (cropdetect) peut halluciner une bande sur un seul côté** (vignettage/occlusion réel confondu avec une bande à retirer) — le cadre "cinéma" se cale alors sur un rectangle amputé d'un coin et paraît décalé dans la visionneuse sur ce clip précis, jamais sur ses voisins. Diagnostic : comparer les insets de `letterbox_cache.json` entre le clip cassé et un clip sain — une vraie bande est toujours symétrique (`top≈bottom` ou `left≈right`) ; un inset sur un seul côté est le signal du faux positif (v0.3.49, cas DRIFT_MAI0192).
27. **Un nouvel appel à une fonction déjà utilisée ailleurs doit être ajouté À TOUS les points d'appel équivalents, pas juste au premier qui vient à l'esprit** : `_scrollActiveClipIntoView()` avait été câblée sur les handlers de filtre (v0.3.52) mais oubliée sur le seul autre endroit qui sélectionne un clip sans clic utilisateur direct — la restauration du dernier clip au lancement (`enterWorkspace`). Résultat : le clip actif était bien sélectionné/lu, mais invisible tout en haut d'une sidebar retombée à `scrollTop:0`, exactement le même symptôme que le bug déjà corrigé pour les filtres (v0.3.53).
28. **Un pin de marker (`.timeline-marker-pin`, `renderMarkers()`) est un enfant de `#timelineTrack`** (la mini-piste de 4px collée en bas de la barre de 88px), donc `--pin-top` est relatif au **haut de la track**, pas au haut de la barre — un décalage positif pousse le pin SOUS la track (quasi invisible), un décalage négatif le pousse au-dessus. Toujours vérifier le référentiel de positionnement (quel est le vrai `offsetParent`) avant de calculer un offset CSS empilé, plutôt que de supposer que "top" se mesure depuis le conteneur visuellement englobant (v0.3.58, retour terrain « marqueurs proches, un à peine visible en-dessous »).
29. **Une map de "reprise de position" dédiée à un contexte (`_mcGroupResumeTime`, `_clipResumeTime`) devient périmée dès qu'on quitte ce contexte pour un autre puis qu'on y revient** — elle ne se met à jour qu'à la fermeture de CE contexte précis, jamais pendant qu'on est ailleurs (ex. lecteur principal). Toute ouverture d'un contexte B depuis un contexte A actif (comparateur depuis le lecteur, viewer multicam depuis le lecteur) doit écraser la map de B avec la position réelle de A au moment de l'ouverture, pas se fier à la dernière valeur laissée par une session précédente de B. Déjà corrigé une fois pour le comparateur (`openCompare()`, v0.3.13), le même oubli traînait sur `openMcViewer()` jusqu'à v0.3.59 — vérifier tout futur contexte de lecture synchronisée contre cette même classe de bug.

## Historique détaillé

Le détail chronologique des sagas de debug, incidents et livraisons de features (versions 0.2.0 → 0.3.46 et au-delà) est archivé dans **`HISTORY.md`**. Le consulter pour :
- comprendre *pourquoi* une décision de design a été prise (ex. panier personnel vs partagé, pas de tombstone pour les commentaires de review) ;
- retrouver le détail d'une reproduction de bug déjà résolue avant d'en enquêter une nouvelle qui y ressemble ;
- le contexte complet d'une version précise (numéros `v0.3.x`).

Les pièges listés ci-dessus sont un résumé condensé des leçons de `HISTORY.md` qui restent applicables au code actuel — ne pas dupliquer une nouvelle entrée ici sans la condenser en une règle générale.
