# DERUSH TOOL — Guide Claude

Outil de dérushage vidéo multi-utilisateurs. Serveur Python + UI HTML monofichier.

> **⚠️ Règle de documentation (à respecter à chaque changement)**
> À chaque modification du code ou d'une fonctionnalité, Claude **doit** mettre à jour les trois fichiers de documentation : `claude.md` (ce fichier — référence technique courante, pas de journal chronologique), `guide.html` (notice utilisateur) et `journal.html` (carnet de bord, ajouter une entrée datée). Ne jamais livrer un changement sans synchroniser ces trois fichiers.
> **Historique détaillé** : les sagas de debug, les citations de retour terrain et le récit chronologique complet vivent dans `HISTORY.md`, pas dans ce fichier. Ce fichier doit rester une référence technique **courte et à jour** de l'état actuel du code (fonctions, endpoints, schémas de données, contraintes non négociables) — pas un journal. Une entrée dans `HISTORY.md` peut donner lieu à UNE ligne condensée dans « Pièges critiques à retenir » si la leçon reste applicable au code actuel ; ne pas y coller le récit complet, ne pas dépasser 2-3 lignes par piège.
> **Discipline de taille** : ce fichier a dépassé 190k caractères le 15/09/2026 (au-delà d'une limite d'outillage de 150k) parce que des sagas de debug complètes s'y sont accumulées au fil des sessions au lieu d'être extraites vers `HISTORY.md` au fur et à mesure. Tout le contenu retiré ce jour-là a été archivé dans `HISTORY.md` (section « Archive du 15/09/2026 »), rien n'a été perdu. **Réflexe à appliquer désormais** : dès qu'une explication dépasse ~5 lignes ou cite un retour terrain/une enquête pas-à-pas, elle va dans `HISTORY.md` ; ce fichier ne garde que la conclusion actionnable.

## Fichiers
- `derush_server.py` — serveur HTTP Python (~1850 lignes)
- `derush_app.html` — UI web complète CSS+HTML+JS (~2000 lignes)
- `derush_exports.py` — exports FCPXML/XML Premiere/EDL/AAF, tri chronologique, résolution de chemins
- `derush_drt.py` — export DRT natif DaVinci (multipiste son ingé, voir § Export DRT)
- `derush_launcher.py` — launcher avec tray icon (pystray) pour package installable
- `derush_setup.html` — wizard de configuration initiale (dark UI, 3 étapes + champs sync)
- `derush_sync.php` — script PHP à déposer sur hébergement web pour la sync cloud (gitignored, réel — `derush_sync.example.php` = template public)
- `derush_config.seed.json` — seed sync_url/sync_key (gitignored, réel — `derush_config.seed.example.json` = template public). Bundlé dans le build s'il existe sur la machine qui compile ; sert de valeur par défaut pour toute machine sans config existante
- `derush.spec` — spec PyInstaller pour build Windows/macOS
- `build_windows.bat` / `build_mac.sh` — scripts de build
- `requirements.txt` — dépendances Python (pystray, Pillow, pyinstaller)
- `derush_config.json` — config (créé par setup wizard, à côté de l'exécutable)
- `projects/` — données projets JSON (`<id>.derush.json`)
- `projects/backups/<pid>/` — backups versionnés : rolling horodatés (`<pid>_AAAAMMJJ_HHMMSS.json`, 40 derniers) + quotidiens (`<pid>_daily_AAAAMMJJ.json`, 90 jours, hors cycle rolling)
- `waveforms/` — cache JSON des formes d'onde (`<clip_id>.json`)
- `thumbnails/` — cache JPEG des miniatures + strips de scrubbing
- `projects/luts/` — fichiers `.cube` PARTAGÉS entre collaborateurs, adressés par hash sha256 (`<hash>.cube`), dédupliqués — voir § LUT partagée
- `GUIDE.html` — notice utilisateur complète
- `HISTORY.md` — archive chronologique des sagas de debug/incidents/features. Ne pas re-fusionner dans `CLAUDE.md` ; y ajouter les nouvelles entrées datées à la place.

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
```json
{
  "configured": true,
  "projects_dir": "/path/to/projects",
  "waveforms_dir": "/path/to/waveforms",
  "thumbnails_dir": "/path/to/thumbnails",
  "backups_dir": "/path/to/projects/backups",
  "luts_dir": "/path/to/projects/luts",
  "ffmpeg": "ffmpeg",
  "ffprobe": "ffprobe",
  "port": 8765,
  "sync_url": "https://example.com/derush_sync.php",
  "sync_key": "secret",
  "backup_keep_rolling": 40,
  "backup_keep_daily": 90
}
```
`backup_keep_rolling` / `backup_keep_daily` optionnels (défauts 40 / 90).

Variables globales : `APP_DIR`, `BUNDLE_DIR` (PyInstaller: `sys._MEIPASS`), `PROJECTS_DIR`, `WAVEFORMS_DIR`, `THUMBNAILS_DIR`, `BACKUPS_DIR`, `LUTS_DIR`, `BACKUP_KEEP_ROLLING`, `BACKUP_KEEP_DAILY`, `FFMPEG`, `FFPROBE`, `PORT`, `IS_CONFIGURED`, `SYNC_URL`, `SYNC_KEY`.

Sync runtime : `_sync_status` (dict: configured/online/last_sync/error), `_sync_lock` (threading.Lock).

**PyInstaller — APP_DIR vs BUNDLE_DIR** :
```python
if getattr(sys, 'frozen', False):
    APP_DIR = Path(os.environ.get('APPDATA', str(Path.home()))) / 'DerushTool'
    BUNDLE_DIR = Path(sys._MEIPASS)
else:
    APP_DIR = Path(__file__).parent
    BUNDLE_DIR = APP_DIR
```
`APP_DIR` = données utilisateur (config, profile, projects/…, persiste entre builds). `BUNDLE_DIR` = fichiers read-only bundlés (`derush_app.html`, `derush_setup.html`, `_internal/`). `derush_app.html`/`derush_setup.html` servis depuis `BUNDLE_DIR`, jamais `APP_DIR`.

## derush_server.py — Fonctions clés

| Fonction | Rôle |
|----------|------|
| `tc_to_seconds(tc_str, fps)` | TC "HH:MM:SS:FF" → secondes |
| `seconds_to_tc(sec, fps)` | secondes → TC string |
| `seconds_to_rational(sec, fps)` | secondes → "frames/fpsS" pour FCPXML |
| `get_lan_ip()` | IP LAN via socket (pour partage réseau) |
| `_load_config()` / `save_config(data)` | lecture/écriture `derush_config.json` |
| `ffprobe_metadata(filepath)` | metadata via ffprobe — TOUS les `format_tags` **+** `stream_tags=timecode` de chaque stream (indispensable pour GoPro, qui n'écrit son TC qu'au niveau stream — piège #35) |
| `scan_media_folder(root_path)` | scan récursif + TC + caméra depuis métadonnées + tech metadata |
| `parse_sony_xml(xml_path)` | `{tc_in, duration_sec, model, iso, aperture, shutter_angle, focal_length}` |
| `find_proxy(root, clip_path)` | cherche proxy dans Sub/Proxy, ou LRV GoPro à défaut |
| `_resolve_clip_src_path(proj, clip, prefer_root=None)` / `_proj_with_resolved_export_paths(proj, prefer_root=None)` | résout `clip['path']` au chemin RÉEL courant avant export (piège #36). Priorité : `prefer_root` (query `?root=`, root_path de l'utilisateur qui exporte) > chemin littéral existant > `root_path` des autres users (tolérant) > chemin stocké |
| `_resolve_relpath_tolerant(root, rel)` | walk segment par segment, tolère lettre de lecteur/zero-padding (`01↔1↔001`), case-insensitive, avec cache positif |
| `compute_thumbnail(file_path, clip_id, offset_sec)` | ffmpeg → JPEG 160px → cache `thumbnails/` |
| `compute_strip(file_path, clip_id, duration_sec, n=12)` | N frames en threads parallèles (max 3, ThreadPoolExecutor) → JPEG horizontal 320×180px/frame |
| `compute_waveform_peaks(file_path, num_buckets=800)` | ffmpeg → PCM s16le 4000Hz → `np.frombuffer`+`reshape().mean()` (vectorisé, pas de boucle Python) → peaks normalisés |
| `_chrono_sort_clips(clips)` (`derush_exports.py`) | trie par (jour, heure réelle — LTC si décodé sinon TC brut), mélange les caméras au sein d'un jour multicam. Utilisée par tous les exports timeline (FCPXML, XML Premiere, subclips, markers EDL) |
| `export_fcpxml(project, filter_config)` | export FCPXML 1.8 pour DaVinci, tri chrono. Une seule piste son par clip — **insuffisant pour le multipiste son ingé** |
| `export_drt(project, filter_config)` (`derush_drt.py`) | **export recommandé pour les timelines de selects** — voir § Export DRT multipiste. Nécessite DaVinci Resolve lancé en direct (`MediaPool.CreateTimelineFromClips` + export natif `.drt`). Lève `DrtExportError` si Resolve injoignable ou clip ambigu |
| `export_aaf(project, filter_config)` (`derush_exports.py`) | repli historique (image + son caméra + 1 piste/BWF via `pyaaf2`), plus la voie recommandée — l'audio AAF se rattache par TC seul chez DaVinci, sensible aux collisions inter-jours (piège #41) |
| `export_subclips_fcpxml(project, pre_roll, post_roll, filter_config)` | chaque marker → subclip court, même tri chrono |
| `export_edl(project)` | EDL classique (CMX3600) |
| `export_markers_edl(project, filter_config=None)` | EDL marqueurs DaVinci, même contrat de filtre que `export_fcpxml` (voir § EDL Marqueurs) |
| `export_csv(project)` / `export_report_html(project)` | export CSV / rapport HTML auto-contenu |
| `import_edl(edl_text, user_id)` | import EDL → marqueurs |
| `project_health(proj, pid)` | rapport santé projet (médias, TC, annotations, export, infra) |
| `save_project(pid, data)` | sauvegarde atomique (`.tmp`+`os.replace`) + backup rolling (40) + quotidien (90, jamais purgé par le rolling) |
| `merge_projects(local, remote)` | fusionne remote dans local — `notes`/`baskets`/`lut_assign` own-uid-wins, `discussions` union par ts, `users` union par id. Ne fusionne **jamais** `clips[]` |
| `sync_project(pid)` | pull remote → merge → push → save local → `{ok, message}` |
| `sync_all_projects()` | `sync_project` pour chaque `.derush.json` dans PROJECTS_DIR |
| `_lut_fetch_from_cloud(hash)` / `_lut_push_to_cloud(hash, content)` | LUT partagée — va chercher/pousse un `.cube` sur `derush_sync.php` quand le hash référencé n'est pas encore local |
| `_sync_background_thread()` | thread daemon : détecte reconnexion (poll 90s), sync auto sur reconnexion + toutes les 10 min |
| `run(open_browser=False)` | lance ThreadedHTTPServer + `_sync_background_thread` |
| `DerushHandler` | handler HTTP (do_GET, do_POST) |

### Concurrence & robustesse serveur
- `_project_lock(pid)` (RLock) : détenu par `do_POST` pendant tout le dispatch `/api/project/<pid>/…`. Tout code qui écrit un projet HORS d'une requête `do_POST` (job de fond, thread, Timer) doit recharger sous `with _project_lock(pid):` juste avant `save_project`, sinon lost update.
- `_dispatch_post()` lit le corps une fois (`body = self._read_body()`) et le passe aux handlers — un handler qui relit `self.rfile` bloque indéfiniment (pas de timeout socket).
- `_ffmpeg_run(cmd, timeout, ...)` : sémaphore globale `_ffmpeg_sem` (`BoundedSemaphore(_FFMPEG_MAX_CONCURRENT)`, `_FFMPEG_MAX_CONCURRENT = max(2, min(8, cpu_count//2))`), acquise avec `timeout=timeout+5` (jamais bloquant sans limite — un process zombie sur I/O verrouillé épuiserait la sémaphore pour de bon). `ffprobe_metadata()` passe par `_ffprobe_metadata_bounded()` (thread daemon + `Event.wait(20s)`) et sa propre sémaphore `_ffprobe_meta_sem`.
- `_compute_locks` (dict clé→`threading.Event`) : `_dedupe_compute(key, fn)` — un seul calcul en cours par clé, les appels concurrents attendent l'Event. Wrappe `compute_thumbnail`/`compute_thumbnail_scrub`/`compute_strip`.
- `-analyzeduration 1M -probesize 5M -an` sur tous les `compute_*` ffmpeg (évite les allocations >1GB sur fichiers GoPro HEVC/MXF exotiques).
- `_lighter_decode_source(file_path)` : GoPro `GX*.MP4` → utilise le `GL*.LRV` voisin (proxy natif HEVC 432p) pour les thumbnails, pas de transcode.
- Heartbeat rafraîchi par **toute** requête HTTP entrante, pas seulement `/api/heartbeat` (`_HEARTBEAT_TIMEOUT`) — un job long sans requête réseau ne doit pas déclencher le watchdog `os._exit(0)`.
- Garde-fou rescan : `POST /scan` refuse (409) si le nouveau scan trouve moins de 50% des clips déjà présents, sauf `force:true`.

## Détection caméra — priorité
1. **Sidecar XML Sony** `<Device modelName="ILME-FX6"/>` — source la plus fiable
2. **Tags ffprobe** : `model`, `Model`, `com.apple.quicktime.model`, `com.apple.quicktime.make`
3. **Nom de dossier** (après `IMAGE/`) — fallback si aucune métadonnée

Fix byte-reversal FX6 : `'FX6' in camera.upper()` (couvre ILME-FX6, FX6V, etc.)

## Détection TC (timecode) — priorité
1. **Sidecar XML Sony** — comme pour la caméra
2. **`format.tags.timecode`** (ffprobe) — fiable pour Sony FX6 MXF
3. **`streams[i].tags.timecode`** (ffprobe, premier stream qui en a un) — **seule source pour GoPro** (nécessite `stream_tags=timecode` dans `-show_entries`, piège #35)

## Points techniques critiques

### PyInstaller
- Ne jamais faire `import threading` à l'intérieur d'une fonction qui utilise aussi `threading` hors du bloc (→ `UnboundLocalError`, `threading` traité comme variable locale).
- Tous les `subprocess.run()` utilisent `creationflags=_NO_WINDOW` (`subprocess.CREATE_NO_WINDOW` si Windows, sinon 0) pour éviter les flashs de fenêtre cmd.

### FCPXML — TC source
`<asset start=tc_in_rational>` DOIT être la vraie TC source du fichier (pas `0s`) — DaVinci compare contre la TC embarquée MXF, mismatch = erreur "timecode extents". Marqueurs en espace source-TC : `frame_num = tc_in_frames + offset_frames`.

Tous les exports passent par `_clip_asset_tc_sec(clip, fps)` (`derush_exports.py`) : priorise `clip['ltc_tc_in_sec']` (LTC décodé) sinon `tc_to_seconds(clip['tc_in'])`. Concerne en pratique les FS5 seulement.

⚠️ **Précondition non négociable pour l'import DaVinci** : le Start TC du Media Pool doit être corrigé à la valeur LTC (*Update Timecode from Audio Track* / `fs5_fix_timecode_resolve.py`) **ET** le Media Pool doit contenir TOUS les médias référencés (tous jours, toutes caméras) **avant** l'import — sinon des clips échouent à l'import pour une raison sans rapport avec la précision du TC (Media Pool incomplet, piège #37 — saga complète dans `HISTORY.md`).

### Mute automatique du canal LTC des FS5 — voie fermée
Le bruit LTC (BZZZZ) ne peut être coupé automatiquement ni via FCPXML (`<audio-channel-source>` : DaVinci ignore cet élément à l'import, bug connu et documenté du logiciel — sources externes dans `HISTORY.md`) ni via l'API de scripting (aucune méthode d'écriture exposée pour l'assignation de canal audio dans cette version). **Seule option fiable** : couper le canal 1 (LTC) à la main dans Clip Attributes → Audio sur tous les FS5 du Media Pool (une fois, s'applique aussi aux instances déjà découpées dans une timeline). Ne pas retenter sans nouvelle piste concrète côté API Resolve.

### FCPXML — notes globales / rating
Pas de `<marker>` au début du clip (confusant dans DaVinci). Notes/étoiles globales → attribut `note` de l'`<asset-clip>`, format `"[Sébastien] ⭐⭐⭐ — texte"`.

### FCPXML — marqueurs X (zones à couper)
- **0 X** → clip complet `[(0, dur)]`
- **1 X à T** → `[(0, T)]`
- **2 X à T1,T2** → `[(0,T1),(T2,dur)]`
- **3 X à T1,T2,T3** → `[(0,T1),(T2,T3)]`
- **N pair** → N/2 zones supprimées, fin conservée ; **N impair** → dernier X coupe jusqu'à la fin

Chaque segment conservé = un `<asset-clip>` séparé, markers de contenu inclus seulement s'ils tombent dans un segment conservé.

### EDL Marqueurs DaVinci (`export_markers_edl`)
Import : clic droit timeline → Timelines → Import → Timeline Markers from EDL.
```
TITLE: nom_markers
FCM: NON-DROP FRAME

001  001      V     C        HH:MM:SS:FF HH:MM:SS:FF HH:MM:SS:FF HH:MM:SS:FF
 |C:ResolveColorYellow |M:texte label |D:1
```
Reel toujours "001". Source TC = Record TC = position séquence. **Doit répliquer exactement** `export_fcpxml` : inclusion clips (mêmes branches de filtre), FPS séquence (`round(clips[0].fps)`), découpage des zones X (marqueurs dans une zone coupée retirés, autres replacés via `_src_to_seq()`). Toute modif de la logique d'inclusion/segments dans `export_fcpxml` doit être répercutée ici. UI : bouton apparié par filtre dans la modale d'export, sous chaque bouton timeline.

Couleurs marqueurs :
| Cat | Couleur app | ResolveColor |
|-----|-------------|--------------|
| 3 (⭐⭐⭐) | #fcd34d jaune | ResolveColorYellow |
| 2 (⭐⭐) | #a78bfa violet | ResolveColorPurple |
| 1 (⭐) | #9ca3af gris | ResolveColorCream |
| T (image) | #3b82f6 bleu | ResolveColorSky |
| S (son) | #10b981 vert | ResolveColorGreen |
| D (note) | #f59e0b ambre | ResolveColorSand |

### Waveform / Thumbnails / Strip
- `compute_waveform_peaks()` : cache `waveforms/<clip_id>.json`, `GET .../waveform/<id>` → `{"peaks":[...], "cached":bool}`.
- `compute_thumbnail()` : `ffmpeg -ss offset -vframes 1 -vf scale=160:-1` → `<clip_id>.jpg`.
- `compute_strip(n=12)` : assemble N frames 320×180px en JPEG horizontal `<clip_id>_strip12.jpg`. Survol sidebar : `background-position: -${frameIdx*260}px 0` (scrubbing sans requête réseau). Race condition gérée par `_activeHoverClipId`. Pré-génération au chargement (`_pregen`, queue max 3 concurrent).

### Markers timeline — interactions
`selectedMarkerId` (string, stable après re-sort). Clic pin → sélection ; drag (seuil 8px) → `mousedown`/`mousemove` in-place puis `mouseup` met à jour `m.time`/`m.tc` + re-sort. `Delete`/`Backspace` supprime avec confirm, `Escape` désélectionne. Pins avec dessin → losange (`.has-drawing`) au lieu de cercle. Tooltip tronqué à 48 caractères.

### Rating toggle
`setRating(r)` : si déjà actif → null (toggle off). Même comportement touches 1/2/3/X.

### Tags
- `tagsDisplay` en `display:contents` (chips enfants directs du flex-wrapper parent).
- `onclick` des chips en guillemets simples (`JSON.stringify` casserait l'attribut HTML).
- `#clipNotes` en `height:72px` fixe (pas `flex:1`) pour garder les Tags visibles sans scroll.
- **Autocomplete tags** (`#tagAutocomplete`) : suggestions par sous-séquence (`_tagSubsequenceScore`, lettres dans l'ordre pas forcément contiguës) sur `_allProjectTags()`, triées par score puis alpha, 8 max. Navigation ↑/↓/Entrée/Échap (`handleTagInput`). `position:fixed` (pas `absolute` — `#tagInput` est dans un conteneur `overflow-y:auto`), coordonnées calculées via `getBoundingClientRect()`, flip vers le haut si pas de place en bas. Logique de validation extraite dans `_commitTag(tag)`. Même mécanisme pour `#selectPopupTagInput` (popup de sélection, `js/selects.js`) mais menu **inline** (`#selectPopupTagSuggest`, pas de conteneur à overflow restreint), source `_allProjectTagsForSuggest()` (tags de toute l'équipe sur ce clip).
- `.marker-popup` a une **`width` fixe** (520px, pas `min-width`) : un flex-wrap sans largeur d'ancêtre définie se dimensionne en shrink-to-fit et grandit à chaque lettre tapée selon le nombre de suggestions filtrées.

### Sync cloud (derush_sync.php)
PHP côté serveur : `derush_data/<pid>.derush.json` + backups `derush_data/backups/<pid>/`. Auth `?key=SECRET`. GET=download, POST=upload+backup (mêmes seuils rolling/daily que `save_project` — **toute modif doit rester synchro entre les deux fichiers, et le PHP doit être ré-uploadé pour prendre effet**). Merge : `notes`/`baskets`/`lut_assign` own-uid-wins, `discussions` union par ts, `users` union par id. **Le sync propage aussi les régressions** : un local rétrogradé (restauration système, rollback) écrase la version cloud de cet user au redémarrage — les backups (40 rolling + 90 daily, local ET serveur) sont le seul vrai filet (piège #30).

### LUT partagée (sept. 2026)
Consultation du pré-montage d'un AUTRE collaborateur affiche SA LUT publiée (avec ses réglages) ; partout ailleurs (lecteur, votre pré-montage, comparateur, multicam) c'est toujours votre `_lutAssign` local qui gouverne. Deux canaux séparés pour ne jamais alourdir le sync JSON fréquent :
1. **Métadonnées** (`lutName`+`hash`+`settings`, jamais le contenu) : `proj['lut_assign'][uid] = {cameras:{}, clips:{}}`, mêmes endpoints/merge/WS que `baskets`.
2. **Contenu binaire** (`.cube`, plusieurs Mo possible) : adressé par hash sha256, dédupliqué. Local `LUTS_DIR`, endpoints `GET/POST /api/project/<pid>/lut/<hash>` et `/lut/upload`, fallback cloud via `derush_sync.php?action=lut_get/lut_upload`.

Client (`js/lut.js`) : `allLutAssign` (poll 15s + WS, publié par toute l'équipe). `_lutPersistAssign()` déclenche `_lutSchedulePublish()` (debounced 1.5s). `_lutPublishAssign()` republie un instantané complet (pas un diff). `_lutResolveForRemote(uid, clip)` / `_lutEnsureLoadedByHash(hash)` = équivalents remote de `_lutResolveFor`/`_lutEnsureLoaded`, indexés par hash de contenu (pas par nom — deux users peuvent avoir des `.cube` différents sous le même nom). Bascule dans `_basketLutRefresh()` (`js/selects.js`) : un seul `if(viewingOther)`.

### Discussions (replies sur markers)
Stockées séparément des notes dans `proj['discussions']` (évite les conflits avec les sauvegardes locales) :
```json
{"discussions": {"<clip_id>": {"<marker_id>": [{"user_id":"...","user_name":"...","color":"#...","text":"...","ts":"ISO"}]}}}
```
Chaque marker a un `id` (hex aléatoire 8 chars) généré côté client à la création.

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
        "rating": "3", "notes": "texte global", "status": "valide",
        "tags": ["golden hour", "émotionnel"],
        "markers": [{"id":"a3f7b2c1","tc":"00:01:23:12","time":83.48,"cat":"3","desc":"SUPER PLAN","drawing":null}],
        "selects": [{"id":"...","name":"...","in":10.2,"out":25.4,"tags":[...]}]
      }
    }
  },
  "discussions": {"<clip_id>": {"<marker_id>": [{"user_id":"...","user_name":"Léa","color":"#60a5fa","text":"Oui mais le son ?","ts":"2026-05-11T..."}]}},
  "multicam_groups": [{"id":"mc_a1b2c3d4","clip_ids":["id_a","id_b"],"offsets":{"id_a":0,"id_b":11.08},"score":1.0,"sync_method":"tc","detected_at":"..."}],
  "audio_clips": [{"id":"TECHCHECKT14","filename":"TECHCHECKT14.WAV","path":"...","tc_in_sec":62051.0,"duration_sec":1820.5,"sample_rate":48000,"channels":2,"origination_date":"2026-04-08","track_names":[...]}],
  "lut_assign": {"<uid>": {"cameras":{}, "clips":{}}}
}
```

## derush_app.html — Globals JS clés
- `currentProjectId`, `clips`, `allNotes`, `allDiscussions`, `activeClip`, `currentSession`, `currentProject`
- `activeFilter` (`all`/`3`/`2+`/`markers`/`hasselect`/`unseen`/`rejected`/`disagree`), `activeSearch` — chaque nouvelle valeur = un chip `.fchip[data-filter=...]` + une condition dans `renderClipList()`
- `seenClipIds`, `undoStack` (illimité), `lastSavedHash`, `waveformPeaks`
- `pollingInterval` (notes, 15s), `_syncPollInterval` (statut sync, 30s)
- `currentSpeed` (0.25–2), `_flipHState` (`{clip.id:bool}`, non persisté)
- `_clipResumeTime` (`js/audio-bwf.js`) — `{clip.id:sec}`, **persisté** `localStorage['derush_resume_'+pid]`
- `selectedMarkerId`, `_activeHoverClipId`, `_pregen` (`{q:[], n:0, max:3}`)
- `_bwfMixerSettings` (`js/bwf-mixer.js`) — `{pid:{bwfId:{gains,mutes,solos}}}`, persisté `localStorage['derush_bwf_mixer_'+pid]`
- `_bwfMixerPanelState` — `{audio, bwfId, channels, trackNames}` du BWF affiché, `null` si fermé
- `_clipSortMode` — `'camera'`|`'time'`, persisté `localStorage['derush_clip_sort_'+pid]`

## derush_app.html — Fonctions JS clés

| Fonction | Rôle |
|----------|------|
| `renderClipList()` | sidebar (thumbnails+strip, en-têtes jour, filtres, search, chips rating équipe). `orderedClips` selon `_clipSortMode` |
| `_clipTimeOfDay(c)` / `_tcStrToSeconds(tc, fps)` | heure de tournage en secondes (LTC prioritaire), `Infinity` si TC inexploitable |
| `_setClipSortMode(mode)` / `_loadClipSortMode(pid)` / `_updateSortModeButtons()` | change/persiste/restaure le tri sidebar |
| `_scrollActiveClipIntoView()` | à appeler après tout changement de filtre (le re-render vide `innerHTML`, `scrollTop` retombe à 0) |
| `selectClip(c)` | charge clip, tech-meta, currentSpeed, waveform, tags. Persiste dernier clip + position de reprise du clip quitté |
| `_persistClipResumeTime()` / `_loadClipResumeTime(pid)` (`js/audio-bwf.js`) | I/O `_clipResumeTime` ↔ localStorage. Filet `pagehide` en plus du changement de clip |
| `setSpeed(rate)` | `video.playbackRate` + boutons actifs |
| `toggleFlipH()` / `_applyFlipH(on)` | miroir horizontal par clip (`scaleX(-1)` sur `#player`+`#lutCanvas`+`#drawCanvas`) |
| `setRating(r)` / `addMarker(cat, desc, drawing)` / `renderMarkers()` / `timeToTC(t, fps)` | rating, markers, rendu timeline |
| `renderTags()` / `handleTagInput(e)` / `updateTagAutocomplete()` / `_commitTag(tag)` / `removeTag(tag)` | gestion tags + autocomplete |
| `renderMultiUser()` / `_muSeekMarker(time, e)` / `submitReply(btn, clipId, markerId)` | panneau "Avis des autres" (rating/note/discussion/markers d'équipe) |
| `loadWaveform(clip)` / `drawWaveform()` | fetch + rendu canvas |
| `startNotesPolling()` (15s) / `startSyncPolling()` (30s) / `triggerSync()` / `pollSyncStatus()` / `_updateSyncUI(st)` | polling notes/discussions + statut sync cloud |
| `showUserMgmt()` / `renderUsersList()` / `startEditUser(uid)` / `resetUserForm()` / `saveUser()` | gestion utilisateurs |
| `rescanProject(btn)` | POST /scan, rafraîchit clips + dropdowns |
| `pushUndo()` / `undo()` | pile d'annulation illimitée |
| `saveNotes(silent)` | compare hash, POST si changement |
| `openExportModal()` / `openHealthModal()` / `renderHealth(h)` | modales export/santé |
| `cycleStatus()` | null → arevoir → valide |
| `timelineSeek(e)` | seek + désélectionne marker si clic hors pin |

## Endpoints API
```
GET  /api/projects
GET  /api/me
GET  /api/profile
GET  /api/browse                                   (tkinter folder picker Windows, osascript sur Mac — piège #9)
GET  /api/project/<id>/clips
GET  /api/project/<id>/notes
GET  /api/project/<id>/discussions
GET  /api/project/<id>/basket                       (paniers de toute l'équipe)
GET  /api/project/<id>/lut_assign                    (LUT publiées de l'équipe — hash+réglages, pas le contenu)
GET  /api/project/<id>/lut/<hash>                    (contenu .cube par hash, fallback cloud)
GET  /api/project/<id>/config
GET  /api/project/<id>/health
GET  /api/project/<id>/export/drt|aaf|fcpxml|edl|markers_edl|csv|subclips_fcpxml|report_html
GET  /api/project/<id>/export/basket_fcpxml|basket_xml_fcp7|basket_drt  (?items=id1,id2 optionnel, ?user=, ?root=)
GET  /api/project/<id>/thumbnail/<clip_id>[?t=N]
GET  /api/project/<id>/strip/<clip_id>?n=12
GET  /api/project/<id>/waveform/<clip_id>
GET  /api/project/<id>/letterbox/<clip_id>         ({top,bottom,left,right,cw,ch})
GET  /api/project/<id>/invite_key/<username>       (admin)
GET  /api/project/<id>/son                         ({son_dir, count, audio_clips})
GET  /api/project/<id>/multicam                    (groupes validés + propositions)
GET  /api/project/<id>/multicam/status
GET  /api/project/<id>/bwf_audio/<ac_id>           (streaming BWF, Range)
GET  /api/project/<id>/clip_bwf/<clip_id>
GET  /api/project/<id>/multicam/group_bwf?group_id=
GET  /api/project/<id>/decode_ltc/status | /summary
GET  /api/sync/status
GET  /api/setup/status
GET  /setup
GET  /proxy/<rel_path>                             (streaming vidéo)

POST /api/login | /api/logout
POST /api/heartbeat | /api/shutdown
POST /api/profile/create
POST /api/setup
POST /api/project/open                             (créer projet + scan)
POST /api/project/enter
POST /api/project/<id>/authorize_user              (admin: ajoute user + invite_key)
POST /api/project/<id>/set_root_path
POST /api/project/<id>/add_user | /edit_user
POST /api/project/<id>/scan
POST /api/project/<id>/notes
POST /api/project/<id>/basket
POST /api/project/<id>/lut_assign
POST /api/project/<id>/lut/upload                   ({content} → {hash}, dédupliqué)
POST /api/project/<id>/reply
POST /api/project/<id>/config
POST /api/project/<id>/import                       (import EDL)
POST /api/project/<id>/scan_son                     ({son_dir})
POST /api/project/<id>/multicam/detect | /accept | /reject | /nudge
POST /api/project/<id>/decode_ltc/start             ({force})
POST /api/sync/now | /api/sync/pull                 ({project_id})
POST /api/sync/join_with_key                        ({project_id, invite_key})
WS   /ws?token=<session_token>                       (collaboration temps réel)
```

### Réponse `/health`
```json
{
  "media":    {"total":N, "with_proxy":N, "without_proxy":["stem"], "missing_source":["stem"], "zero_duration":["stem"]},
  "timecode": {"with_tc":N, "without_tc":["stem"], "fps_distribution":{"25":N}, "majority_fps":25, "wrong_fps":["stem"]},
  "annotations": {"users":N, "clips_rated":N, "total_markers":N, "out_of_range":[{"clip":"stem","tc":"HH:MM:SS:FF"}]},
  "exports":  {"special_char_clips":["stem"], "out_of_range_markers":[...], "clips_no_tc":["stem"]},
  "infrastructure": {"last_save_mins_ago":N, "backup_count":N, "ffmpeg_ok":true, "ffprobe_ok":true}
}
```

### Réponse `/api/sync/status`
```json
{"configured": true, "online": true, "last_sync": "2026-05-12T10:30:00", "error": null}
```

## Système de profil global
Un profil par machine (`%APPDATA%\DerushTool\derush_profile.json`, `{username, password_hash}`). `GET /api/profile` → `{exists, username}`. Pas de profil → redirige `/setup`.

**Session model** :
```python
SESSIONS[token] = {'username':'Sébastien','name':'Sébastien','user_id':'Sébastien','color':'#a78bfa','root_path':'','project_id':None,'is_admin':False}
```
`user_id` = alias de `username` (compat ancien code).

**`user_note_key(u)`** = `u.get('id') or u.get('username') or u.get('name','')` — résout la divergence anciens (`id`) vs nouveaux (`username`) users. **Piège #11** : l'endpoint `/notes` doit sauver sous cette MÊME clé résolue via le user trouvé dans `project['users']`, jamais via la session brute — sinon notes orphelines invisibles à l'export. `/api/project/enter` pose `session['user_id'] = user_note_key(user)` pour que UI/notes/export partagent la même clé.

## Système de clés d'invitation
1. Admin → `POST .../authorize_user {username, color, is_admin}` → ajoute user + `invite_key` (8 chars) → `{invite_key}`
2. Collaborateur → `POST /api/sync/join_with_key {project_id, invite_key}` : télécharge depuis le cloud, valide le username contre l'invite_key, supprime la clé (usage unique), sauvegarde + push
3. `POST /api/project/enter {project_id}` : vérifie user existant + `invite_key` absent (déjà rejoint), met à jour SESSIONS

## Chemin local des rushs (root_path)
`proj['users'][i]['root_path']`. `POST .../set_root_path` met à jour user + session live, **ne touche jamais `clip['path']`** (figé au scan) — seulement la résolution dynamique. Le front passe `?root=` sur les exports (`_exportRootParam(fmt)`, + `_basketExport`) : sans ça, si l'ancien disque est toujours branché, l'export garde ses chemins (piège #36). Premier accès workspace sans `root_path` → modal de saisie.

## Heartbeat / auto-shutdown
```python
_HEARTBEAT_TIMEOUT = 12  # secondes, grace period 20s au démarrage puis check toutes les 3s
```
Frontend `POST /api/heartbeat` toutes les 5s. Onglet fermé → plus de heartbeat → `os._exit(0)` après ~12s. Bouton ⏻ → `POST /api/shutdown` (arrêt après 300ms).

## Workflow DaVinci Resolve
0. Timeline DaVinci en **25 fps** (positions EDL à `round(clips[0].fps)`), démarrant à `00:00:00:00`.
1. **📥 FCPXML** → File > Import > Timeline. 2. **📥 Markers EDL** → clic droit timeline → Timelines → Import → Timeline Markers from EDL. Pour une timeline filtrée, prendre FCPXML + EDL du **même** filtre (boutons appariés).

### Workflow FS5 — sync du son ingé
Le Start TC interne des MXF FS5 dérive/se remet à zéro ; le vrai TC est en LTC sur une piste audio, décodé par Derush (`ltc_tc_in_sec`, 🎶 Décoder LTC). Objectif : *Auto Sync Audio → Based on Timecode* (frame-accurate) — *Based on Waveform* est un repli, pas un substitut (mauvais sur bruit répétitif moteur/pneus).

⚠️ Sur un projet où du LTC a été décodé avant v0.3.90 : relancer 🎶 Décoder LTC avec **↻ Re-décoder tout** (ancien décodeur en avance d'1 frame, corrigé depuis — piège #37).

**Méthode (ordre + exhaustivité comptent) :**
1. Importer TOUS les médias, toutes caméras, tous jours dans le Media Pool — pas un sous-ensemble.
2. Clic droit FS5 → *Timecode → Update Timecode from Audio Track* (Resolve Studio). FPS=25, canal LTC **Channel 2** pour J02–J05, **Channel 1** pour J07–J11, par lot de journée. Repli : `fs5_fix_timecode_resolve.py`.
3. Importer tous les sons ingé (WAV/BWF).
4. Sélection tout (vidéo+WAV) → *Auto Sync Audio → Based on Timecode* — **organiser le Media Pool en bins PAR JOUR et faire cette étape un jour à la fois** (le TC ne code pas la date, un bin mélangeant plusieurs jours peut associer le WAV du mauvais jour à heure coïncidente — piège #39).
5. **Puis seulement** générer la timeline de selects (📤 Exporter → DRT, § Export DRT) : rattachement par identité live du `MediaPoolItem`, pas d'import à gérer.

**Si Media Offline persiste** (Media Pool complet + TC corrigé + LTC re-décodé confirmés) : relink manuel (Media Pool → sélectionner le bon clip → clic droit sur le plan offline → Replace Selected Clip, ou Source Viewer + bouton Replace).

**Diagnostic** : `%APPDATA%\Blackmagic Design\DaVinci Resolve\Support\Logs\davinci_resolve.log` (chercher `failed to link`) + API de scripting (§ ci-dessous) pour lister précisément les items offline et croiser avec le FCPXML importé.

**Timeline déjà conformée** : ne PAS relancer de correction TC en masse dessus (risque Media Offline + reconform lent + freeze/crash). **Couper le LTC (BZZZZ) dans DaVinci** : Media Pool → tous les FS5 → clic droit → Clip Attributes → Audio → désactiver canal 1 (L), garder canal 2 (R). Repli : page Fairlight, couper au niveau du patch de piste.

Doc utilisateur autonome : `D:\METHODOLOGIE_IMPORT_RUSHS_DAVINCI.md`.

### API de scripting DaVinci Resolve (diagnostic)
Connexion (PowerShell, Resolve doit être lancé projet ouvert) :
```powershell
$env:RESOLVE_SCRIPT_API = "C:\ProgramData\Blackmagic Design\DaVinci Resolve\Support\Developer\Scripting"
$env:RESOLVE_SCRIPT_LIB  = "C:\Program Files\Blackmagic Design\DaVinci Resolve\fusionscript.dll"
$env:PYTHONPATH = "$env:RESOLVE_SCRIPT_API\Modules\;$env:PYTHONPATH"
python -c "import DaVinciResolveScript as dvr; resolve = dvr.scriptapp('Resolve'); print(resolve.GetProjectManager().GetCurrentProject().GetName())"
```
Objets utiles : `proj.GetMediaPool().GetRootFolder()` → `Folder` (`.GetClipList()`, `.GetSubFolderList()` — récursion manuelle). `MediaPoolItem.GetClipProperty()` (sans argument) → dict complet (Start TC, End TC, File Path, Online Status, FPS, Duration…). `proj.GetCurrentTimeline().GetItemListInTrack('video', n)` → `TimelineItem`s. `TimelineItem.GetMediaPoolItem() is None` = test fiable d'offline (mais `GetSourceStartFrame()` renvoie aussi `None` dans ce cas — croiser `(GetName(), GetDuration(), GetStart())` avec le FCPXML importé pour désambiguïser). Pas de contrôle souris/clavier UI, lecture/écriture de données seulement. **Piège** : `hasattr(item, 'NomInventé')` renvoie toujours `True` sur ces objets `PyRemoteObject` — jamais fiable pour tester l'existence réelle d'une méthode, seul un appel réel le confirme.

### Modale d'export (📤, `#exportModal`)
« Timelines de selects » : boutons `exportDataWithParams('drt', {min_rating:N, label})` pour N=3/2/1 (ladder partagé avec `#rcRating` du rough cut). `min_rating` inclut un clip dès qu'un seul membre de l'équipe lui a mis au moins cette note. Sous chaque bouton DRT, un bouton « Markers EDL correspondant » avec les MÊMES params — prendre timeline + EDL du même filtre. XML Premiere (`xml_fcp7`), Subclips, Rough cut et l'export du pré-montage restent en FCPXML/XML.

**Nom de fichier personnalisé** : `_promptExportName(defaultName)` → modale `#exportNameOverlay` (jamais `prompt()` natif, piège #1) retournant une Promise, pré-remplie avec le nom automatique. `_sanitizeFilenamePart(s)` neutralise `\/:*?"<>|`. Annuler la modale annule tout l'export (pas de fallback silencieux). Déclenché pour `fmt==='fcpxml'` **et** `fmt==='drt'` — `xml_fcp7` garde un nom automatique.

**Emplacement personnalisé (DRT uniquement, sept. 2026)** : en plus du nom, les exports DRT (workflow complet, filtres « Timelines de selects », pré-montage tout/sélection) passent par `_downloadWithPicker(url, suggestedName)` (`derush_app.html`) au lieu d'une navigation directe — `apiFetch(url)` (garde l'en-tête Authorization, possible ici car ce n'est plus une navigation) puis `window.showSaveFilePicker` (File System Access API, Chromium — Electron/Chrome/Edge) ouvre la vraie boîte "Enregistrer sous" de l'OS. Fallback sur `window.location.href` (dossier de téléchargements par défaut) si l'API est absente (Firefox/Safari). Bénéfice secondaire : une erreur serveur (`DrtExportError`, 503) est lue via `res.text()` et affichée en toast plutôt que de naviguer vers une page d'erreur brute.

### Export DRT multipiste — remplace le FCPXML pour les timelines de selects
Le FCPXML ne porte qu'une piste son par clip ; l'AAF se rattache par TC seul chez DaVinci (sensible aux collisions inter-jours, piège #41) ; `MediaPool.AppendToTimeline` ne pose jamais plus d'un canal. **Solution : `export_drt()` (`derush_drt.py`)** via `MediaPool.CreateTimelineFromClips` — seule méthode qui restitue toutes les pistes ingé son, rattachement par identité live du `MediaPoolItem` (jamais par fichier échangé ni résolution de TC). Contrainte : DaVinci Resolve doit tourner en direct, Media Pool complet et déjà synchronisé (Auto Sync Audio fait), au moment de l'export — pas un fichier portable hors-ligne. Validé sur un export réel de 53 plans.

Sujet séparé non résolu par cet export : silence du son caméra sur certains clips J11 (`Clip0008.MXF`/`DRIFT_MAI0217`/`DRIFT_MAI0237`) — problème du Media Pool/projet DaVinci lui-même, indépendant de tout mécanisme d'export testé (pièges #40/#41).

**Liaison vidéo/son — RÉSOLU par correction du `FieldsBlob` (sept. 2026, piège #44)** : la vraie cause n'était ni `CreateTimelineFromClips` ni `SetClipsLinked` — le mécanisme qui pilote l'icône de liaison DaVinci est un champ `FieldsBlob` (par item vidéo/audio) contenant une trame **ZSTD compressée** (en-tête 9 octets `00 00 00 02` + longueur big-endian + `81`, puis signature ZSTD `28 B5 2F FD`) qui décompresse en une liste de `DbId` — ceux des AUTRES items du même **groupe de liaison**, le groupe étant défini par `(MediaRef, Start)` (tous les items démarrant exactement à la même frame ET venant du même plan — **pas** tous les items partageant seulement le même `MediaRef` : plusieurs coupes d'un même plan partagent légitimement leur `MediaRef`, chacune garde son propre groupe limité à sa position).

Rétro-ingénié et vérifié par comparaison automatisée entre un `.drt` de référence généré nativement par DaVinci (groupes déjà corrects) et nos propres exports : la timeline de BASE (une seule occurrence par plan, construite par `CreateTimelineFromClips`) a déjà un `FieldsBlob` correct — mais un item CLONÉ par `_splice_repeated_clips` (§ ci-dessous) hérite du `FieldsBlob` de son gabarit tel quel, qui référence encore les `DbId` du groupe D'ORIGINE du gabarit (une autre position sur la timeline), jamais ceux de sa propre position. D'où l'absence de liaison observée uniquement sur les plans coupés plusieurs fois.

**Fix** (`derush_drt.py`) : `_fix_clip_linking(root)` regroupe tous les items par `(MediaRef, Start)`, décode le `FieldsBlob` de chaque membre, remplace les UUID qu'il contient par les vrais `DbId` des autres membres du groupe (en conservant l'encodage UTF-16 BE/LE déjà présent pour chaque UUID trouvé), recompresse et réécrit l'en-tête. Appelée à la fin de `_splice_repeated_clips` et via `_apply_linking_fix` sur le chemin sans coupe répétée (filet de sécurité, coût négligeable sur un groupe déjà correct). **Confirmé fonctionnel par réimport réel dans DaVinci** par l'utilisateur : icône de liaison présente sur chaque coupe, y compris les plans coupés plusieurs fois. `zstandard` ajouté à `requirements.txt`.

**`Timeline.SetClipsLinked`** (piste explorée avant de trouver la vraie cause) fonctionne bien en direct dans Resolve mais n'a aucun effet sur le fichier exporté (le vrai mécanisme vit dans `FieldsBlob`, pas dans un état que cette méthode modifierait) — retiré de `derush_drt.py`. `link_timeline_clips_resolve.py`/`check_clip_link_resolve.py` (racine du projet) restent comme scripts de diagnostic ayant servi à explorer puis écarter cette piste ; plus nécessaires en usage normal depuis ce fix.

**Piège DaVinci resté valable, indépendant de ce fix** : même avec la liaison correctement posée, un déplacement solidaire vidéo/son ne se produit que si le mode **« Linked Selection »** de la timeline (icône maillon de chaîne dans la barre d'outils, à côté du magnétisme) est activé. Réglage de session DaVinci (comme le magnétisme), à activer à chaque montage — aucun moyen de l'embarquer dans l'export.

**Coupes multiples du même plan** (sept. 2026, piège #42 — RÉSOLU pour le rattachement audio, confirmé en conditions réelles) : `_build_and_export_drt` (`derush_drt.py`) construit la timeline de base avec UNE SEULE occurrence par plan distinct via `CreateTimelineFromClips` (son intact), l'exporte en DRT, puis — si des plans étaient repris plusieurs fois — reconstruit la timeline finale en Python pur : `_collect_clip_templates` retrouve, pour chaque `MediaRef`, tous les blocs `(piste, item)` déjà câblés par Resolve pour ce plan (vidéo + chaque piste son ingé) ; `_splice_repeated_clips` vide toutes les pistes et les reconstruit dans l'ordre réel voulu par l'utilisateur, en clonant (nouveau DbId, `Start`/`Duration`/`In` mis à jour, tout le reste — `MediaRef`, `MediaStartTime`, `FieldsBlob`, etc. — recopié tel quel) le bloc du plan concerné pour chaque occurrence. `_discover_media_refs` retrouve le `MediaRef` DaVinci de chaque plan par position (l'ordre de la piste vidéo de la timeline de base correspond à l'ordre des `infos` passés à `CreateTimelineFromClips`). Validé hors-ligne par comparaison automatisée contre un `.drt` de référence généré nativement par DaVinci (4 coupes d'un même plan) : `Duration`/`In`/`MediaRef` identiques à 100 % — **et confirmé par réimport réel** : panier de 6 sélections (dont des coupes multiples du même plan) réimporté dans DaVinci avec les bonnes pistes son ingé sur toutes les coupes. `FieldsBlob` copié tel quel depuis le gabarit (jamais recalculé) ne pose donc pas de problème à l'import — hypothèse de cache UI non-critique confirmée dans les faits.

### Mode réseau local (recommandé)
1 PC fait tourner DerushTool.exe (serveur), les autres ouvrent un navigateur sur `http://<ip-lan>:8765` (IP affichée dans le wizard + console).

### Mode autonome avec sync cloud
Chaque PC a sa propre install DerushTool. `derush_sync.php` sur un hébergement commun (`sebastiendelahaye.be/derush_sync.php`), clé `drift2026` (`SYNC_KEY`). Config dans `derush_config.json` (`sync_url`+`sync_key`). Sync auto au démarrage, à la reconnexion (poll 90s) et toutes les 10 min. Médias sur disques locaux, chaque user configure son `root_path`.

## Fonctionnalités avancées

### J/K/L Shuttle
JS pur. L réaccélère 1x→2x→4x (`playbackRate`), K stoppe, J joue en arrière via RAF loop (`v.currentTime -= rate*dt`, HTML5 ne supporte pas `playbackRate<0`). Cleanup dans `doLogout()`.

### WebSocket — collaboration temps réel
Implémenté manuellement (RFC 6455, pas de lib). Détection `Upgrade: websocket` dans `do_GET` → `_handle_ws_upgrade(qs)`. Auth par token en query param (`?token=`, pas de headers custom possibles en browser). Globals `_ws_clients: dict[pid→[(sock,token)]]`, `_ws_broadcast(pid, msg, exclude_token)`. Frames après save notes (`notes_updated`), reply (`discussion_updated`), save panier (`basket_updated`), publication LUT (`lut_assign_updated`). Client : reconnexion auto toutes les 6s.

### Permissions granulaires (rôles)
`admin`/`annotator`/`viewer` dans `proj['users'][i]['role']` + `session['role']` (backward compat depuis `is_admin` si absent). `applyRoleUI(role)` : viewer masque édition (notes/tags/rating), non-admin masque gestion users + rescan.

### Pré-montage (Basket overlay, `js/selects.js`)
Bouton 📽️ → overlay plein écran : liste réordonnable des sélections (`#basketBody`) + visionneuse (`#basketViewer`). Identifiants internes `basket`/panier, endpoints `/api/.../basket`.

- **Double lecteur crossfade** (`#basketVid`/`#basketVidB`) : préchargement dans le lecteur inactif SEULEMENT quand le segment suivant est sur un clip différent (`_basketPreloadNextSegment`) — sur le MÊME clip, transition via pause→seek→attend `seeked`→reprend sur l'élément déjà chargé, jamais de rechargement (précharger même le même clip a provoqué flash noir + crash renderer, piège #33). `readyState>=3` + marge dans `buffered()` requis pour considérer un lecteur "prêt" (piège #31).
- **Dupliquer** (`⧉`, `_basketDuplicateItem`) : copie indépendante (nouvel id dans `n.selects`, pas de partage de `select_id`) suffixée `" (copie N)"` via `_basketNextSuffixedName`.
- **Couper** (`C` ou `#basketCutBtn`, `_basketCutAtPlayhead`) : scinde la sélection en deux au point de lecture (snap frame-exact), 1ère moitié mute `sel.out` en place, 2e = nouvel enregistrement `" (cut N)"`. Refuse si marge < `_BASKET_TRIM_MIN_DUR*2`.
- **Renommer** (`✏️`, `_basketRenameItem`) : modale dédiée `#basketRenameOverlay` (jamais `prompt()`), référence par identité d'objet (pas index, périmable).
- **Timeline de séquence** (`#basketSeqTimeline`) : segments proportionnels à la durée (`_basketSeqSegments`), zoom molette ancré (`_basketSeqZoom` 1–25), scrub par clic/glisser. **Réordonner directement sur la timeline** (drag HTML5 natif sur le corps du segment, poignées de trim en `draggable=false` pour ne pas interférer) — moitié survolée du segment cible détermine insertion avant/après.
- **Trim précis façon DaVinci** : `_basketSnapClamp` arrondit toujours à la frame exacte. HUD `#basketTrimHud` affiche TC + delta en continu pendant le geste. **Trim armé au clavier** : clic sans glisser arme la poignée (`_basketArmedTrim`), `←`/`→` (1 frame) ou `Maj+←/→` (1s) ajuste, `Entrée` valide, `Échap` annule. Piège corrigé : `renderBasketOverlay()` détruit/recrée toutes les poignées à chaque appel — `_wireBasketSeqHandle` flush un trim armé en tête de `mousedown` puis `return` (ne pas continuer sur une référence DOM détachée, piège #32). `renderBasketOverlay()` commence par flush tout trim armé en attente.
- **Repères de séquence + magnétisme** : `_basketSeqMarkers` (array de floats, personnel, `localStorage`), lane dédiée au-dessus de la timeline. Clic simple = pose un repère, clic+glisser = scrub (seuil 3px). Clic sur repère existant = sélection+seek (pas suppression) ; `Suppr` supprime le sélectionné. Magnétisme (drag souris uniquement, pas le trim clavier) : rayon 10px écran, compare toujours la frontière du segment avec le SUIVANT (celle qui bouge réellement), snap sur repère si dans le rayon puis re-passe par `_basketSnapClamp`.
- **Export FCPXML/Premiere/DRT du panier — sélection partielle** : case à cocher par ligne (`_basketExportSelIds`, Set d'`item.id`, non persisté, vidé au changement d'utilisateur consulté ET à `closeBasket()`). Maj+clic = plage (`_basketApplyRangeSelect`), ancre stockée par **id stable** (`_basketExportAnchorItemId`, pas un index — un index se périme après un réordonnancement, piège corrigé). `_basket_entries(project, user_key, item_ids=None)` conserve l'ORDRE DU PANIER, jamais l'ordre de cochage.
- **Export DRT du panier** (`export_basket_drt`, `derush_drt.py`) : réutilise `_basket_entries` + le cœur commun `_build_and_export_drt` partagé avec `export_drt`.

### Comparaison multi-clips (Compare overlay)
Overlay plein écran (`z-index:150`), 2 slots `.compare-slot` (header+video+timeline+info). `cmpSeek(slot,e)` aligné sur le rect de `cmpTrack`. `_cmpSync` (bool) : un slot scrube → l'autre saute au même `currentTime`. `renderCmpMarkers(slot)` : pins de tous les annotateurs. `.compare-slot { min-width:0 }` — sans ça, la grid `1fr 1fr` laisse le slot au nom de fichier long pousser sa colonne plus large, donnant des hauteurs vidéo différentes en `object-fit:contain`.

### Preview LUT (.cube) — WebGL2 (`js/lut.js`)
Texture 3D WebGL2 (`TEXTURE_3D`, `LINEAR`=trilinéaire hardware), pleine résolution, zéro readback CPU. Un seul programme fragment shader : exposition → balance couleur (température/teinte) → lookup LUT 3D (coords centrées voxel) → intensité (mix source/LUT) → contraste (pivot 0.5) → saturation (mix vers gris Rec.709) → dithering anti-banding.

**Modèle d'assignation par plan** : `_lutLibrary={lutName:{size,data}}` (cache mémoire + IndexedDB), `_lutAssign={cameras:{[cam]:{lutName,settings}}, clips:{[id]:{lutName,settings}}}` (localStorage par projet). `_lutResolveFor(clip)` = override clip > défaut caméra > rien. Appliquer "à des caméras" n'écrit jamais dans `clips` (override jamais écrasé) ; toucher un slider fork un override clip (`_lutEnsureEditableEntry`) sans jamais muter l'objet caméra partagé. Bouton retrait d'override clip (`_lutRemoveForActiveClip`) fait retomber sur le défaut caméra.

**Persistance** : `_lutEnabled` (interrupteur maître) persisté par projet (`_lutPersistEnabled`, `localStorage['derush_lut_enabled_'+pid]`) — restauré par `_lutLoadAssign(pid)` AVANT la restauration du dernier clip consulté.

**Panneau réduit → languette** : `#lutSettingsPanel` caché (`display:none`) quand réduit, languette séparée `#lutPanelTab` (12×30px) positionnée dynamiquement (`getBoundingClientRect` de `#lutBtn` + `#videoWrapper`) à chaque affichage. `_lutUpdateBtnVisual` doit s'exécuter AVANT `_lutApplyPanelCollapsed` (le bouton doit être visible pour mesurer sa position).

**LUT dans le pré-montage** : pipeline WebGL indépendant (`_basketLutGL` etc., `js/selects.js`), un seul canvas `#basketLutCanvas` pour les deux lecteurs crossfade (relit `_basketActiveVid()` à chaque frame). Fonctions génériques (`_lutInitGL`/`_lutUploadLUT`/`_lutApplySettings`) acceptent un contexte GL en paramètre, défaut sur les globals du lecteur principal.

### Disposition des contrôles du lecteur
`.player-controls` (bas, sous vidéo) = transport : TC, seek ±5s/±1s, ⏯, 📌 Marker, 🖌 Dessin, ⤢ plein écran, 🔊 Son ingé, volume, ⇋ Flip H, vitesses, 💾 Sauver. `.player-toolbar` (`#playerToolbar`, overlay flottant haut-droite de `.player-area`) = outils en icônes seules : ⚡ Comparer, 🎞 Cadre, 🎨/📂 LUT, 🔄 Multi-cam, 🎬 Session, 📤 Exporter, 🔗 Partager, 🩺 Health, 📊 Stats, ⌨️ raccourcis, ☁️ Sync. Masquée pendant le mode dessin.

### Miroir horizontal (Flip H)
Par clip (`_flipHState[activeClip.id]`, non persisté). `_applyFlipH(on)` flip `#player`+`#lutCanvas`+`#drawCanvas` (le canvas LUT redessine des pixels bruts, doit être flippé séparément). `selectClip()` réapplique l'état du nouveau clip.

### Plein écran
`.player-fs-wrap` (`#playerFsWrap`) englobe `.player-area`+`.player-controls`+`.timeline-bar` (pas `.notes-panel`). `#popupOverlay`/`#markerPopup` et `#selectPopupOverlay`/`#selectPopup` sont descendants de ce wrapper (sinon invisibles en plein écran, la Fullscreen API ne peint que le sous-arbre de l'élément fullscreen).

### Cadrage / format d'image (letterbox/pillarbox)
Bouton 🎞 → `#aspectMenu` (formats ciné courants, `ASPECT_FORMATS`). `#aspectOverlay` (4 `.aspect-bar` + ligne de cadre) dans `#videoWrapper`. `_videoDisplayRect()` = rect `object-fit:contain` amputé des insets détectés serveur. Persisté par `localStorage['derush_aspect']`.

**Bandes noires incrustées** (matte cinéma bakée au tournage) : détection **côté serveur** (`detect_letterbox`, `ffmpeg cropdetect` sur 80 frames, plus robuste qu'une frame isolée côté client) → cache `letterbox_cache.json`. Filtre de symétrie : un inset sur un seul côté d'un axe = vignettage/occlusion réelle (pare-soleil, capuchon), pas une bande — mis à zéro (piège #26). Crop côté client via zoom `transform:scale()` dans une box `.cmp-vbox` 16:9 fixe (`object-view-box` et `aspect-ratio` CSS non fiables cross-navigateur) — **portée : comparateur seulement**, le lecteur principal et le multicam n'appliquent que le cadre (`_contentInsets`), pas le crop.

### Multicam — détection TC via décodeur LTC
Matching par TC uniquement (pas de xcorr/GCC audio, peu fiable). Deux sources : `clip['ltc_tc_in_sec']` (LTC décodé, préféré) et `clip['tc_in']` (ffprobe, faux pour FS5). `_clip_tc_seconds(clip)` choisit le meilleur.

**Constantes** : `_MC_TC_GRACE = 5.0` (slack overlap TC), `_FFMPEG_MAX_CONCURRENT`.

**Décodeur LTC** (`derush_server.py`) :
| Fonction | Rôle |
|----------|------|
| `_ltc_extract_pcm(file_path, channel, max_sec=8, sample_rate=48000)` | 1 canal mono int16 via ffmpeg |
| `_ltc_decode_pcm(pcm, sample_rate, fps=25, min_consecutive_frames=3)` | biphase mark LTC, sync word 16 bits, 80 bits/frame → TC début PCM ou `None` |
| `_clip_tc_seconds(clip)` | `ltc_tc_in_sec` si dispo sinon `tc_to_seconds(tc_in)` |
| `decode_project_ltc(project, pid, progress_cb, force)` | itère tous les clips, stocke `ltc_tc_in_sec` |

Algorithme : PCM canal L 48kHz → zero crossings → long=bit'0', 2 courts='1' → validation 3 frames consécutives cohérentes (`tc[k+1]=tc[k]+1/fps`) contre faux positifs sur bruit ambiant → correction d'offset (1er sync peut être à 1-3s dans le PCM) → **calibration -1 frame** (le calcul brut est systématiquement en avance d'1 frame vs le décodeur DaVinci natif, `-frame_period` appliqué en attendant une cause racine isolée — piège #37).

LTC piste 2 des MXF FS5 J02-J05, piste 1 pour J07-J11 (détection auto crest factor < 2). FX6 n'ont pas de LTC (TC via SDI/jam-sync dans `format.timecode`). Clips sans LTC (multiprise jamais branchée un jour donné) : fallback `format.timecode` (souvent faux pour FS5) → pas de paire multicam, à caler à la main.

**Fonctions multicam** : `_tc_pair_lag(a,b)` / `_temporal_candidate(a,b)` (overlap TC strict, pas de fallback same-day/creation_date — volontaire) / `detect_multicam_groups(project, pid, progress_cb)` (skip déjà-groupés, BFS propage les lags) / `_detect_multicam_job(pid)` (append aux propositions, ne remplace jamais).

**Endpoints** : `GET/POST /multicam/detect|accept|reject|nudge`, `GET /multicam/status`, `GET /clip_bwf/<id>`, `GET /multicam/group_bwf?group_id=`, `POST /decode_ltc/start {force}`, `GET /decode_ltc/status|summary`.

**BWF (lecture seule)** : `_read_bwf_bext_direct` (RIFF/WAVE, `fmt`+`bext`+`iXML`+`data`), `_parse_ixml_tracks` (noms de piste), `read_bwf_tc` (dispatcher), `scan_son_dir`, `_bwf_candidates_for_clips` (BWF qui contiennent strictement les clips ±2s, triés par compacité — utilisé par `/group_bwf`).

**Audio FS5 mono R** : proxys FS5 = L=LTC, R=micro. WebAudio route R sur les 2 canaux output (`_attachPlayerAudio`+`_setPlayerMonoR`, `_mcAttachAudio` pour le viewer multicam). Détection FS5 = `clip.ltc_tc_in_sec != null`.

**Mixeur multipiste BWF** (`js/bwf-mixer.js`) : `GainNode` indépendant par piste (mute/solo/fader 0-150%), noms de piste depuis iXML. `_bwfBuildMixerGraph` : `MediaElementSource→ChannelSplitter(8)→GainNode×N→ChannelMerger(2)→destination`. Persisté par **BWF id** (pas clip) dans `localStorage['derush_bwf_mixer_'+pid]`. Panneau `#bwfMixerPanel` positionné dynamiquement (2 boutons déclencheurs dans des zones DOM différentes).

**Workflow** : 🎶 Décoder LTC (1×/projet) → 🔍 Détection (instantané, TC only) → Validation modale → Viewer (🔊 Son ingé + nudge ◄/► + 💾) → export.

### Optimisations performance
- Sémaphore ffmpeg globale (voir § Concurrence ci-dessus) — évite le fanout illimité de ThreadedHTTPServer.
- `_dedupe_compute` — évite les calculs dupliqués sur requêtes concurrentes.
- `compute_strip` : ThreadPoolExecutor(3) au lieu de 12 threads simultanés.
- `compute_waveform_peaks` numpy-isé (`np.frombuffer`+`reshape().mean()`) — ~10× moins de RAM, ~100× plus rapide que `struct.unpack` en boucle Python.
- `-analyzeduration 1M -probesize 5M -an` sur tous les `compute_*`.
- `_lighter_decode_source` : GoPro utilise le LRV voisin pour les thumbnails (HEVC 432p au lieu de 5K).
- `find_proxy` détecte les `.LRV` GoPro comme proxy si pas de `Sub/` — `_serve_video` leur donne MIME `video/mp4`.
- Cleanup WebAudio + `<video>` dans `closeMcViewer()`/`closeCompare()` : `disconnect()` de tous les nodes, `removeAttribute('src')`+`load()`, `AudioContext.close()` — sans ça, fuite mémoire massive à chaque open/close répété.

### Wrapper Electron
`electron/` (`main.js`, `preload.js`) spawn le backend Python (`python derush_server.py --no-browser`), poll `localhost:8765`, ouvre un `BrowserWindow` Chromium dessus. Fermeture window → kill subprocess. F12=DevTools. Build : `dist/DerushTool.exe` (PyInstaller) bundlé en `extraResources` dans un exe Electron portable (~280 MB). `console=IS_WIN` dans `derush.spec` (Mac : binaire POSIX pur headless, pas de bundle `.app`). Menu clic droit reconstruit à la main (`context-menu` event) : suggestions orthographe (`dictionarySuggestions`/`replaceMisspelling`), Couper/Copier/Coller. Dictionnaire forcé français (`setSpellCheckerLanguages(['fr'])`).

**Limitations** : binaire ~280MB, RAM baseline ~300-400MB, HEVC Windows nécessite l'extension MS gratuite, build Mac impossible depuis Windows (mais l'app tourne sur Mac), SmartScreen au 1er lancement (exe non signé).

## Scripts utilitaires (racine projet)
| Fichier | Rôle |
|---------|------|
| `transcode_proxies.sh` | batch transcode FS5 MXF→MP4 H.264 720p NVENC, détecte LTC par crest factor |
| `watch_ffmpeg.ps1` | monitore les process ffmpeg (RAM + cmdline), alerte au-dessus d'un seuil |
| `test_ltc_decoder.py` | test standalone du décodeur LTC (6 cas connus) |
| `fs5_fix_timecode_resolve.py` | script Console DaVinci : réécrit le Start TC des rushes FS5 avec `ltc_tc_in_sec`. `DRY_RUN=True` par défaut. À lancer AVANT Auto Sync Audio, jamais sur une timeline déjà conformée (risque Media Offline + freeze) |
| `fs5_revert_timecode_resolve.py` | retour arrière du précédent (Start TC → valeur MXF) |
| `check_proxy_links_resolve.py` | diagnostic lecture seule : liste les clips dont `Proxy Media Path` ne correspond pas au clip lui-même (voir piège #38) |
| `link_timeline_clips_resolve.py` | **à lancer après CHAQUE import d'une timeline DRT Derush** (Console DaVinci ou externe) : lie tous les plans de la timeline courante à leurs pistes son ingé en une passe (`SetClipsLinked`) — l'export ne peut pas le faire, voir § Liaison vidéo/son et piège #44 |
| `check_clip_link_resolve.py` | diagnostic (modifie la timeline courante, annulable Ctrl+Z) : teste `Timeline.SetClipsLinked` sur le 1er clip vidéo + ses pistes audio à la même position — a servi à isoler le problème du piège #44 |
| `check_tc_collisions_resolve.py` | diagnostic permanent lecture seule : collisions de TC entre WAV de jours différents, noms de fichiers dupliqués, clips couvrant un TC cible (voir piège #39). Utilise `End TC` (pas `Frames`, vide pour l'audio dans cette version de l'API) |
| `_patch_gopro_proxy.py` / `_patch_fx6_proxy.py` | one-shot patch de `proxy_url` sans rescan complet (préserve `ltc_tc_in_sec`) |
| `validate_multichunk.py`, `refonte.py`, `recover_orphans.py` | archive d'expérimentations audio multicam (session antérieure, ne plus utiliser, ne pas supprimer) |

## Pièges critiques à retenir

1. **`confirm()`/`alert()`/`prompt()` natifs** dans Electron cassent le focus state ou renvoient `null` — toujours un toast/modale custom.
2. **`GH_TOKEN` niveau User** : pas propagé aux subprocess npm sur Windows. Injecter en session avant `npm run release`.
3. **Mode Développeur Windows requis** pour electron-builder (symlinks darwin/).
4. **PyInstaller onedir** (5× plus rapide que onefile). `console=IS_WIN` dans `derush.spec`. `extraResources` commun (`../dist/DerushTool` → `DerushTool`), `main.js` attend `DerushTool.exe` (Win) / `DerushTool` chmod 755 (Mac).
5. **`derush_sync.php` jamais commité** (SECRET_KEY hardcodée) — utiliser `derush_sync.example.php`.
6. **Bundle `js/`** dans `derush.spec` : glob `*.js` en datas.
7. **ffmpeg `showinfo`** invisible en `-loglevel info` (faut `verbose`), regex préfixée `\[Parsed_showinfo` (faux positifs sinon).
8. **Tests E2E** avant tout refactor risqué : `cd tests && DERUSH_TEST_PASS=... npm test`.
9. **tkinter sur Mac** hangue en worker thread → `/api/browse` utilise `osascript` sur `darwin`, tkinter sur Windows.
10. **`_resolve_relpath_tolerant`** : tolérance zero-padding/case pour chemins relatifs. Pour chemins absolus stockés (`audio_clips[].path`) qui ne matchent plus après changement de lettre de lecteur : chercher le nom du dossier racine projet dans les segments, déléguer le reste (`_resolve_audio_clip_path`).
11. **Clé de notes dédoublée** : la clé de save doit être résolue via `user_note_key()` sur le user trouvé dans `project['users']`, jamais via la session brute — sinon notes orphelines invisibles à l'export (voir § user_note_key).
12. **IDs de clip orphelins après ré-import** : un rescan qui régénère les IDs laisse les anciennes notes pointer dans le vide. Re-mapper par nom de fichier si récupération nécessaire.
13. **`_project_lock(pid)`** : voir § Concurrence & robustesse serveur ci-dessus.
14. **Jamais relire `self.rfile` deux fois** : voir § Concurrence & robustesse serveur.
15. **`_ffmpeg_run()` timeout d'acquisition sémaphore obligatoire** : voir § Concurrence & robustesse serveur.
16. **Heartbeat rafraîchi par toute requête HTTP**, pas seulement `/api/heartbeat` — sinon un job long sans requête réseau se fait tuer par le watchdog.
17. **Garde-fou rescan** : `POST /scan` refuse (409) si <50% des clips connus retrouvés, sauf `force:true`.
18. **`merge_projects` ne fusionne jamais `clips[]`** — chaque machine garde les siens ; seul `join_with_key` adopte le remote tel quel.
19. **`GET .../config` ne doit jamais retirer `id`** des users (seuls `password_hash` et `invite_key` sont sensibles) — sinon casse la résolution de clé pour les comptes hérités.
20. **Suppression de données synchronisées** : purger le stockage serveur ET faire en sorte que le pull suivant REMPLACE le cache local (pas union) — un pull additif ne peut jamais faire disparaître une suppression.
21. **SSL sur binaire PyInstaller (macOS)** : `os.environ.setdefault('SSL_CERT_FILE', certifi.where())` tout en haut du fichier, avant tout appel réseau.
22. **Config sync jamais écrasée silencieusement** : `POST /api/setup` préserve `sync_url`/`sync_key` existants si absents du body. Priorité : config locale > seed gitignored bundlé > placeholder public.
23. **Champ de saisie non validé** doit être vidé au changement de contexte (ex. `#tagInput` au changement de clip) — sinon il "colle" visuellement sans avoir été sauvegardé.
24. **Mesurer avant de deviner sur un bug de géométrie/CSS** (`getBoundingClientRect`, `scrollHeight`) — voir mémoire persistante `measure-before-guessing-layout`.
25. **Reproduire en conditions réelles** (serveur + navigateur) plutôt que de continuer à relire du code qui semble correct face à un bug signalé qui le contredit.
26. **`detect_letterbox` peut halluciner une bande sur un seul côté** (vignettage/occlusion réel) — une vraie bande est toujours symétrique (top≈bottom ou left≈right).
27. **Un nouvel appel à une fonction partagée doit être ajouté À TOUS les points d'appel équivalents** — pas seulement au premier qui vient à l'esprit (ex. `_scrollActiveClipIntoView()` oublié sur la restauration au lancement).
28. **Un pin de marker est enfant de `#timelineTrack`** (mini-piste 4px), pas de la barre 88px — vérifier le vrai `offsetParent` avant de calculer un offset CSS empilé.
29. **Une map de "reprise de position" dédiée à un contexte devient périmée dès qu'on quitte ce contexte** — toute ouverture d'un contexte B depuis A actif doit écraser la map de B avec la position réelle de A, pas se fier à une session précédente de B.
30. **Le sync cloud n'est pas un historique versionné** — il propage les régressions (voir § Sync cloud ci-dessus et mémoire persistante `sync-not-a-versioned-backup`).
31. **Un seek sur un flux long-GOP en cours de lecture n'est jamais "déjà instantané"**, même sur un fichier déjà en cache — il doit retrouver la keyframe et redécoder. `readyState>=3`+marge dans `buffered()` requis avant de considérer un élément "prêt" pour un swap.
32. **Un re-rendu déclenché EN PLEIN MILIEU d'un geste (mousedown/drag) peut détruire la référence DOM que ce geste tient encore en main** — s'arrêter net après un flush qui a déclenché un rendu, ne pas continuer sur une référence potentiellement détachée.
33. **Précharger systématiquement "pour être sûr" peut être pire que le mal** — vérifier si la cible du préchargement est déjà disponible ailleurs sous une forme utilisable avant de dupliquer un décodeur.
34. **Un contenu binaire potentiellement volumineux ne doit JAMAIS rejoindre le JSON projet synchronisé** — l'adresser par hash sur un canal séparé (voir § LUT partagée pour le modèle à suivre).
35. **`ffprobe -show_entries stream=...` ne renvoie PAS `streams[i].tags`** sans clause séparée `stream_tags=<nom>` — silencieusement vide sinon, TC absent pour toute caméra sans `format.tags.timecode` (pas seulement GoPro). Rescanner après un fix de ce type pour corriger les clips déjà en cache.
36. **`clip['path']` est figé au scan** — changer `root_path` ne le met pas à jour. Un `root_path` explicite de l'utilisateur qui exporte doit primer sur un chemin de scan encore valide par accident (même si l'ancien disque est encore branché) — voir `_resolve_clip_src_path`.
37. **Décodeur LTC en avance systématique de +1 frame** (trouvé via l'API de scripting DaVinci après deux tentatives ratées qui blâmaient à tort un Media Pool incomplet) — corrigé par calibration `-frame_period`. Un log applicatif tiers accessible sur disque, ou une API de scripting officielle, peuvent trancher en minutes ce que des heures de déduction manuelle ne résolvaient pas. Saga complète dans `HISTORY.md`.
38. **`Link Proxy Media` en recherche "comprehensive" sur plusieurs jours peut lier le mauvais proxy** (jusqu'au MXF d'un autre jour) — toujours scoper `Relink Proxy Media` à un seul dossier/jour, recherche exacte. `LinkProxyMedia()` API échoue silencieusement si on tente de changer un lien existant vers une cible différente (ne réussit qu'en no-op).
39. **`Auto Sync Audio Based on Timecode` ne code pas la date, seulement l'heure** — un bin son mélangeant plusieurs jours associe parfois le WAV du mauvais jour à heure coïncidente. Organiser le Media Pool en bins par jour, Link Proxy + fix TC + Auto Sync **un jour à la fois**. `UnlinkClips()` API met offline au lieu de délier juste l'audio (Ctrl+Z pour annuler).
40. **Silence audio résiduel sur certains clips FX6 malgré mapping/lien 100% corrects** — piste ouverte non confirmée : piste Adaptive 36 canaux dont seuls les canaux 1-2 sont patchés vers Main par défaut, le son peut être sur un canal 9-15 jamais routé. À tester : réassigner le canal dans Clip Attributes, ou Fairlight → Patch.
42. **RÉSOLU — `CreateTimelineFromClips` ne place qu'une instance par `MediaPoolItem` par appel, et échoue si le nom de timeline existe déjà dans le projet.** Un même clip source repris plusieurs fois dans les picks (plusieurs coupes du même plan) voit ses occurrences suivantes silencieusement ignorées si on ne s'en prémunit pas. Duplication via `MediaPool.ImportMedia` **essayée et abandonnée** : la synchro son ingé est un état du `MediaPoolItem` d'origine, pas du fichier — un clip réimporté joue le mauvais son. **Solution retenue** (voir § Export DRT — coupes multiples du même plan) : construire la timeline de base avec un seul appel API (une occurrence par plan distinct, son intact), puis **cloner nous-mêmes en Python les blocs XML du `.drt` exporté** pour les coupes supplémentaires — le format `.drt` (zip + XML) supporte nativement plusieurs `<Sm2Ti*Clip>` (DbId unique chacun) partageant le même `<MediaRef>` ; seuls `Start`/`Duration`/`In` varient réellement entre coupes d'un même plan (vérifié sur un `.drt` de référence généré nativement par DaVinci, `MediaStartTime`/`PreConformMediaExtents`/`MediaTimemapBA` restent constants). Plus besoin d'appel API supplémentaire ni de duplication de média — élimine le problème par construction. Collision de nom : `timeline_name` reçoit systématiquement un suffixe horodaté.
43. **Pour l'audio (pas l'image), DaVinci résout un AAF importé par TC seul, jamais par nom de fichier** — une collision de TC entre jours fait jouer le mauvais son quel que soit le nom affiché (prouvé par suppression en cascade de candidats concurrents, y compris sur un AAF natif Resolve). Solution : export DRT natif (`export_drt`, `MediaPool.CreateTimelineFromClips`) qui élimine ce mécanisme de résolution par construction — voir § Export DRT multipiste.
44. **RÉSOLU — l'icône de liaison DaVinci est pilotée par une liste de `DbId` compressée en ZSTD dans `FieldsBlob`, groupée par `(MediaRef, Start)`, pas par un état d'API.** Un item cloné (coupes multiples d'un même plan) hérite du `FieldsBlob` de son gabarit tel quel, qui référence encore le groupe D'ORIGINE du gabarit — jamais sa propre position. `Timeline.SetClipsLinked` (API documentée, fonctionne bien en direct) n'a aucun effet sur ce mécanisme et a été retiré. Fix réel : `_fix_clip_linking` (`derush_drt.py`) réécrit le `FieldsBlob` de chaque item avec les vrais `DbId` de son groupe `(MediaRef, Start)`. Un piège méthodologique a précédé cette découverte : un premier diagnostic externe groupait par `MediaRef` seul (sans le `Start`), concluant à tort que le contenu de `FieldsBlob` était aléatoire/faux partout — toujours revérifier le critère de regroupement avant de conclure qu'un champ est corrompu. Piège DaVinci additionnel, indépendant : même liaison correcte, le mode « Linked Selection » (icône maillon dans la barre d'outils) doit être activé pour que ça bouge ensemble — réglage de session, à réactiver à chaque montage.

## Historique détaillé
Le détail chronologique complet (sagas de debug, citations de retour terrain, enquêtes pas-à-pas, décisions de design) vit dans **`HISTORY.md`**, y compris l'archive du contenu retiré de ce fichier le 15/09/2026. Le consulter pour :
- comprendre *pourquoi* une décision de design a été prise ;
- retrouver le détail d'une reproduction de bug déjà résolue avant d'en enquêter une nouvelle qui y ressemble ;
- le contexte complet d'une version précise (`v0.3.x`) ou d'un piège listé ci-dessus en une ligne.

Les pièges ci-dessus sont un résumé condensé des leçons de `HISTORY.md` qui restent applicables au code actuel — ne pas dupliquer une nouvelle entrée ici sans la condenser en une règle générale de 2-3 lignes max.
