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
- `projects/backups/<pid>/` — backups versionnés : rolling horodatés (`<pid>_AAAAMMJJ_HHMMSS.json`, 40 derniers) + quotidiens (`<pid>_daily_AAAAMMJJ.json`, 90 jours, hors cycle rolling)
- `waveforms/` — cache JSON des formes d'onde (`<clip_id>.json`)
- `thumbnails/` — cache JPEG des miniatures + strips de scrubbing
- `projects/luts/` — fichiers `.cube` PARTAGÉS entre collaborateurs, adressés par hash sha256 (`<hash>.cube`), dédupliqués — voir § LUT partagée
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

## derush_server.py — Fonctions clés

| Fonction | Rôle |
|----------|------|
| `tc_to_seconds(tc_str, fps)` | TC "HH:MM:SS:FF" → secondes |
| `seconds_to_tc(sec, fps)` | secondes → TC string |
| `seconds_to_rational(sec, fps)` | secondes → "frames/fpsS" pour FCPXML |
| `get_lan_ip()` | IP LAN via socket (pour partage réseau) |
| `_load_config()` / `save_config(data)` | lecture/écriture `derush_config.json` |
| `ffprobe_metadata(filepath)` | metadata via ffprobe — retourne TOUS les format_tags **+** le tag `timecode` de chaque stream (`-show_entries ...:stream_tags=timecode`, indispensable pour les caméras — GoPro entre autres — qui n'écrivent leur TC qu'au niveau stream, jamais format ; voir piège #35) |
| `scan_media_folder(root_path)` | scan récursif + TC + caméra depuis métadonnées + tech metadata |
| `parse_sony_xml(xml_path)` | retourne dict `{tc_in, duration_sec, model, iso, aperture, shutter_angle, focal_length}` |
| `find_proxy(root, clip_path)` | cherche proxy dans Sub/Proxy |
| `_resolve_clip_src_path(proj, clip, prefer_root=None)` / `_proj_with_resolved_export_paths(proj, prefer_root=None)` | résout `clip['path']` au chemin RÉEL courant (tolérant lettre de lecteur/zero-padding, via `_resolve_relpath_tolerant`) — utilisé juste avant les exports FCPXML/XML Premiere pour ne jamais embarquer un chemin figé au scan initial et périmé depuis (piège #36). **Priorité** : `prefer_root` (query param `?root=` = root_path de l'utilisateur qui exporte, passé par le front car l'export part sans header Auth) > chemin littéral `clip['path']` s'il existe encore > `root_path` des autres users (tolérant) > chemin stocké. `prefer_root` DOIT primer même si l'ancien disque est encore branché avec une copie |
| `compute_thumbnail(file_path, clip_id, offset_sec)` | ffmpeg → JPEG 160px → cache `thumbnails/` |
| `compute_strip(file_path, clip_id, duration_sec, n=12)` | N frames en threads parallèles → PIL → JPEG horizontal 320×180px/frame → `<clip_id>_strip12.jpg` |
| `compute_waveform_peaks(file_path, num_buckets=800)` | ffmpeg → PCM s16le 4000Hz → RMS normalisé → liste floats |
| `export_fcpxml(project, filter_config)` | export FCPXML 1.8 pour DaVinci (supporte filtres) |
| `export_subclips_fcpxml(project, pre_roll, post_roll, filter_config)` | chaque marker → subclip court |
| `export_edl(project)` | export EDL classique (CMX3600) |
| `export_markers_edl(project, filter_config=None)` | export EDL marqueurs DaVinci. `filter_config` = MÊME contrat que `export_fcpxml` (`min_rating`/`cats`/`rejected_only`) : inclusion de clips, FPS de séquence (= `round(clips[0].fps)`) et découpage des zones X répliqués à l'identique depuis `export_fcpxml` pour que l'EDL tombe pile sur la timeline générée avec le même filtre. À passer identique au FCPXML importé |
| `export_csv(project)` | export CSV |
| `export_report_html(project)` | rapport HTML auto-contenu |
| `import_edl(edl_text, user_id)` | import EDL → marqueurs |
| `project_health(proj, pid)` | rapport santé projet (médias, TC, annotations, export, infra) |
| `save_project(pid, data)` | sauvegarde atomique + double backup dans `projects/backups/<pid>/` : rolling horodaté (`BACKUP_KEEP_ROLLING`=40) + 1 copie `_daily_AAAAMMJJ` par jour calendaire (`BACKUP_KEEP_DAILY`=90, jamais purgée par le cycle rolling). Purges par globs séparés (`_daily_` exclu du rolling) |
| `merge_projects(local, remote)` | fusionne remote dans local — notes par user_id (sans conflit), discussions par timestamp |
| `sync_project(pid)` | pull remote → merge → push → save local → retourne `{ok, message}` |
| `sync_all_projects()` | appelle sync_project pour chaque `.derush.json` dans PROJECTS_DIR |
| `_lut_fetch_from_cloud(hash)` / `_lut_push_to_cloud(hash, content)` | LUT partagée : va chercher/pousse un `.cube` sur `derush_sync.php` (`action=lut_get`/`lut_upload`) quand le hash référencé par un collaborateur n'est pas encore en local — voir § LUT partagée |
| `_sync_background_thread()` | thread daemon : détecte reconnexion (poll 90s), sync auto sur reconnexion + toutes les 10 min |
| `run(open_browser=False)` | lance ThreadedHTTPServer + _sync_background_thread (appelé par `__main__` et `derush_launcher`) |
| `DerushHandler` | handler HTTP (do_GET, do_POST) |

## Détection caméra — priorité
1. **Sidecar XML Sony** `<Device modelName="ILME-FX6"/>` — source la plus fiable
2. **Tags ffprobe** : `model`, `Model`, `com.apple.quicktime.model`, `com.apple.quicktime.make`
3. **Nom de dossier** (après `IMAGE/`) — fallback si aucune métadonnée

Fix byte-reversal FX6 : `'FX6' in camera.upper()` (couvre ILME-FX6, FX6V, etc.)

## Détection TC (timecode) — priorité
1. **Sidecar XML Sony** — comme pour la caméra
2. **`format.tags.timecode`** (ffprobe) — présent pour certaines caméras (Sony FX6 MXF notamment)
3. **`streams[i].tags.timecode`** (ffprobe, premier stream qui en a un — vidéo en général) — **seule source pour GoPro** et d'autres caméras qui n'écrivent le TC qu'au niveau stream (voir piège #35 : nécessite `stream_tags=timecode` dans `-show_entries`, sans quoi cette source renvoie toujours vide silencieusement)

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

Tous les exports (FCPXML, XML Premiere, EDL classique) passent par `_clip_asset_tc_sec(clip, fps)` (`derush_exports.py`) : priorise `clip['ltc_tc_in_sec']` (décodé depuis la piste audio LTC) quand disponible, sinon repli sur `tc_to_seconds(clip['tc_in'])` (tag brut ffprobe/MXF). Concerne en pratique seulement les FS5 (GoPro/FX6 n'ont jamais de `ltc_tc_in_sec`).

⚠️ **Précondition non négociable** : le Start TC du Media Pool DaVinci DOIT avoir été corrigé à la même valeur LTC (`Update Timecode from Audio Track` / `fs5_fix_timecode_resolve.py`) **ET le Media Pool doit contenir TOUS les médias référencés** (toutes journées, toutes caméras) **avant** l'import de cet export — voir § Workflow FS5. Deux tentatives précédentes (v0.3.85, v0.3.87) semblaient échouer sur la précision du TC, mais l'investigation du 11/09/2026 (logs DaVinci, `davinci_resolve.log`) a montré qu'un Media Pool **incomplet** était au moins en partie responsable des échecs observés en v0.3.87 (un clip GoPro jamais touché par le LTC échouait identiquement) — le vrai taux d'échec dû à la précision du décodage TC seul, dans des conditions propres, n'est pas encore établi (piège #37).

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
- **Alignement avec le FCPXML** : `export_markers_edl` porte `filter_config` (mêmes params que `export_fcpxml`) et réplique à l'identique (a) l'inclusion des clips (branches `fc_rejected_only`/`fc_min_rating`/`fc_cats`/défaut), (b) le FPS de séquence (`round(clips[0].fps)`, pas 25 en dur), (c) le découpage des zones X en segments conservés — un marqueur dans une zone coupée est retiré, les autres sont replacés via `_src_to_seq()` (temps source → temps séquence à travers les segments), `record_offset += kept_dur`. Avant v0.3.83 l'EDL avançait de `dur` complet → tout décalé après le 1er clip avec des X, même en workflow « timeline complète ». **Toute modif de la logique d'inclusion/segments dans `export_fcpxml` doit être répercutée ici.**
- UI : modale d'export, sous « Timelines de selects », une ligne « Markers EDL correspondant » avec un bouton `exportDataWithParams('markers_edl', {...même params que le FCPXML au-dessus...})` par filtre. Le bouton « 📥 Markers EDL » du workflow complet reste sans params (= inclusion par défaut).

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

**Même mécanisme pour le champ tag de la fenêtre de sélection** (`#selectPopupTagInput`, popup ✂️ Nouvelle sélection / pré-montage, `js/selects.js`, sept. 2026) : réutilise `_tagSubsequenceScore` telle quelle, mais reste un menu **inline** (`#selectPopupTagSuggest`, pas de `position:fixed`) — la fenêtre de sélection n'est pas dans un conteneur à `overflow` restreint, donc pas besoin du repositionnement dynamique. Source de tags dédiée `_allProjectTagsForSuggest()` (union tags clip + tags déjà posés sur d'autres sélections, toute l'équipe) au lieu de `_allProjectTags()`. Champ vide → liste complète (parcours libre) ; frappe → filtrage + tri identiques (`_spCurrentMatches`). Navigation ↑/↓/Entrée/Échap = mêmes rôles (`_spTagInputKeydown`, `_spTagAcIndex`), `oninput="_spOnTagInput()"`.
`.sp-tag-suggest` est en **`height` fixe** (74px, pas `max-height`) + `align-content:flex-start` : le nombre de pills affichées varie à chaque frappe (filtrage), un `max-height` aurait laissé la boîte se redimensionner verticalement à chaque lettre tapée. Hauteur fixe = zone toujours réservée, y compris quand 0 suggestion ne matche (boîte présente mais vide, jamais retirée du DOM/masquée).
La hauteur fixe seule ne suffisait **pas** (retour terrain persistant : « la fenêtre change de taille et de forme ») — la vraie 2e cause était la **largeur** : `.marker-popup` n'avait qu'un `min-width` (360px), jamais de `width`. Un conteneur `flex-wrap` sans largeur définie sur son ancêtre se dimensionne en *shrink-to-fit* : le calcul essaie d'abord de caser tout le contenu (ici les pills de suggestion) sur une seule ligne (candidat max-content) avant de considérer le wrap — donc plus il y avait de suggestions filtrées large-content, plus la popup entière s'élargissait pour les accueillir sans retour à la ligne, puis se recentrait (`transform:translate(-50%,-50%)` sur `top/left:50%`) → l'impression de fenêtre qui « change de taille et de forme » à chaque lettre. Fix définitif : `.marker-popup { width: 520px; }` (remplace `min-width`, taille demandée en retour terrain une fois le tremblement corrigé) — largeur désormais fixe, le flex-wrap des suggestions comme des chips de tags déjà posés est contraint à l'intérieur, plus aucune variation de largeur possible. Aucun enfant de `#markerPopup`/`#selectPopup` n'a de largeur pixel fixe (tout est `width:100%` ou wrap naturel), donc sans risque de débordement.

### Sync cloud (derush_sync.php)
- PHP côté serveur, stocke JSON dans `derush_data/<pid>.derush.json`, backups dans `derush_data/backups/<pid>/`
- Auth par clé secrète `?key=SECRET` en query string
- GET → download, POST → upload. Backup à chaque POST : rolling horodaté (`$BACKUP_KEEP_ROLLING`=40) + 1 `_daily_AAAAMMJJ` par jour (`$BACKUP_KEEP_DAILY`=90, hors cycle rolling) — **mêmes seuils/logique que `save_project` côté Python ; toute modif doit rester synchro entre les deux, et le PHP doit être ré-uploadé sur l'hébergement pour prendre effet**
- Merge strategy : `notes`/`baskets`/`lut_assign` = own-uid-wins (chaque machine ne republie que sa propre clé, garde le remote pour les autres — voir `merge_projects()`), `discussions` = union par `ts` (timestamps ISO), `users` = union par `id`
- Pas de conflit possible : chaque user_id n'écrit que ses propres notes
- **⚠️ Le sync propage aussi les régressions** : `merge_projects()` repart du remote puis réimpose les notes de `own_uid` depuis le LOCAL. Un local rétrogradé (restauration système, rollback) écrase donc la version cloud de cet user au redémarrage. Les backups (local 40 rolling + 90 daily, serveur idem) sont le vrai filet — voir piège #30.

### LUT partagée (sept. 2026)

Retour terrain : « est-ce possible, lorsque je vois le prémontage d'un autre utilisateur, de voir son prémontage avec les LUTs et les réglages de LUT qu'elle a faits ? ». Avant cette feature, `_lutAssign`/`_lutLibrary` (js/lut.js) étaient **strictement locaux** (localStorage + IndexedDB du navigateur) — le pré-montage d'un collaborateur s'affichait donc toujours sans grade, quels que soient ses réglages. Portée volontairement **restreinte** (confirmé explicitement par l'utilisateur) : seule la consultation du pré-montage D'UN AUTRE user affiche sa LUT publiée ; partout ailleurs (lecteur principal, VOTRE pré-montage, comparateur, multicam) c'est **toujours** `_lutAssign` local qui gouverne.

**Deux canaux séparés**, pour ne jamais alourdir le sync cloud fréquent (push/pull debounced 3s des notes/paniers) :
1. **Métadonnées** (petit JSON : `lutName` + `hash` + `settings`, jamais le contenu) : `proj['lut_assign'][uid] = {cameras:{}, clips:{}}`, même forme que `_lutAssign` client + un `hash`. Publié/lu exactement comme `baskets` — mêmes endpoints REST (`GET`/`POST /api/project/<pid>/lut_assign`), même merge own-uid-wins dans `merge_projects()`, même WS (`lut_assign_updated`) et poll 15s. Voyage donc "gratuitement" dans le JSON projet déjà synchronisé.
2. **Contenu binaire** (le `.cube`, potentiellement plusieurs Mo) : HORS du JSON projet, adressé par hash sha256, dédupliqué. Stockage local `LUTS_DIR` (`projects/luts/<hash>.cube`) + endpoints `GET /api/project/<pid>/lut/<hash>` (texte brut, 404 si absent — tente alors `_lut_fetch_from_cloud(hash)`, cache le résultat localement) et `POST /api/project/<pid>/lut/upload` (`{content}` → écrit si hash absent, republie en tâche de fond vers le cloud via `_lut_push_to_cloud`). Ces deux fonctions parlent à `derush_sync.php?action=lut_get`/`lut_upload` (stockage cloud séparé `derush_data/luts/<hash>.cube`, dédupliqué pareil côté PHP) — **indispensable en mode sync cloud multi-PC** : chaque machine a son propre serveur local, le hash d'un collaborateur n'existe pas forcément localement.

**Client (`js/lut.js`)** :
- `allLutAssign` (chargé dans `enterWorkspace()`, rafraîchi par poll 15s + WS comme `allBaskets`) : `{uid: {cameras, clips}}` publié par toute l'équipe.
- `_lutPersistAssign()` (déjà appelée par `confirmLutScope`/`setLutSetting`/`resetLutSettings`/`_lutRemoveForActiveClip`) déclenche en plus `_lutSchedulePublish()` — debounced **1.5s** (un slider glissé déclenche `oninput` en rafale, republier à chaque frappe serait absurde).
- `_lutPublishAssign()` republie un **instantané complet** de `_lutAssign` (pas un diff) : une entrée retirée localement disparaît donc aussi de la version publiée au tick suivant, sans logique de suppression séparée. Pour chaque entrée, `_lutEnsureUploaded(lutName)` upload le contenu (lu depuis l'IndexedDB locale, déjà posé par `onLUTFileSelected`) si pas déjà fait (`_lutUploadedHash`, cache client) et récupère son `hash` — une entrée dont l'upload échoue est simplement omise de CE tick de publication (retentée au prochain réglage/publish).
- `_lutResolveForRemote(uid, clip)` : équivalent de `_lutResolveFor` mais lit `allLutAssign[uid]` au lieu de `_lutAssign` local — jamais appelée pour l'utilisateur courant.
- `_lutEnsureLoadedByHash(hash)` : équivalent de `_lutEnsureLoaded` mais indexé par **hash de contenu**, pas par nom de fichier — deux collaborateurs peuvent chacun avoir une LUT différente sous le même nom (`look1.cube`), indexer par nom collisionnerait. Cache mémoire `_lutLibrary['hash:'+hash]` (préfixe dédié, jamais en collision avec l'espace `lutName` local) + cache disque IndexedDB dédié (`_lutDbGetHash`/`_lutDbPutHash`, clé `hash::<h>`, même store `derush_luts`/`files`).

**Basculement dans le pré-montage** (`_basketLutRefresh()`, `js/selects.js`) : un seul `if(viewingOther)` (= `_basketViewUser !== currentSession.user_id`) choisit entre les deux chemins de résolution ci-dessus — le chemin "propre panier" (le cas courant) est **strictement inchangé** ligne pour ligne par rapport à avant cette feature. Clé de cache GL (`_basketLutCurrentLutName`) préfixée `hash:` en mode remote pour ne jamais réutiliser à tort la texture d'une LUT locale. `c.title` (tooltip sur `#basketLutCanvas`) indique `"LUT de <uid> — <lutName>"` en mode remote, vide sinon — seule indication visuelle que ce grade n'est pas le vôtre.

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
- `activeFilter`, `activeSearch` — état des filtres sidebar. Valeurs `activeFilter` : `all`/`3`/`2+`/`markers`/`hasselect`/`unseen`/`rejected`/`disagree` — chaque nouvelle valeur nécessite juste un chip `.fchip[data-filter=...]` (`.filter-chips`) + une condition `if(activeFilter === '...' && !cond) return;` dans la boucle de filtrage de `renderClipList()` ; `hasselect` (sept. 2026, retour terrain : ne montrer que les clips ayant déjà au moins une sélection ✂️) réutilise `hasSelect` (`(n.selects||[]).length > 0`), déjà calculé pour le point `.clip-select-dot` sur la vignette
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
- `_clipSortMode` — ordre d'affichage intra-journée dans la sidebar : `'camera'` (défaut, ordre du scan) ou `'time'` (retrie par heure de tournage réelle, caméras mélangées). **Persisté** par projet dans `localStorage['derush_clip_sort_'+pid]`

## derush_app.html — Fonctions JS clés

| Fonction | Rôle |
|----------|------|
| `renderClipList()` | sidebar avec thumbnails+strip, en-têtes de jour, filtres, search texte, chips rating équipe. Construit `orderedClips` à partir de `clips` selon `_clipSortMode` avant de boucler dessus |
| `_clipTimeOfDay(c)` / `_tcStrToSeconds(tc, fps)` | heure de tournage d'un clip en secondes (`ltc_tc_in_sec` si dispo, sinon `tc_in` converti via `fps`), `Infinity` si TC inexploitable — utilisé pour le tri `_clipSortMode==='time'` |
| `_setClipSortMode(mode)` / `_loadClipSortMode(pid)` / `_updateSortModeButtons()` | change/persiste/restaure `_clipSortMode`, boutons `#sortModeCamBtn`/`#sortModeTimeBtn` dans la filter-bar |
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
0. Timeline DaVinci en **25 fps** (les positions de l'EDL sont à `round(clips[0].fps)`, = 25 sur tous les projets réels à ce jour) et démarrant à `00:00:00:00`.
1. **📥 FCPXML** → DaVinci : File > Import > Timeline
2. **📥 Markers EDL** → clic droit sur la timeline → Timelines → Import → Timeline Markers from EDL
- Pour une **timeline de selects filtrée**, prendre le FCPXML ET le Markers EDL du **même** filtre (boutons appariés dans la modale). Un EDL et une timeline de filtres différents = tous les marqueurs décalés.

### Workflow FS5 — sync du son ingé dans DaVinci

Le Start TC interne des MXF FS5 est faux (horloge qui dérive / se remet à zéro en cours de journée). Le vrai TC est en **LTC sur une piste audio**, décodé par Derush (`ltc_tc_in_sec`, 🎶 Décoder LTC). L'objectif final est *Auto Sync Audio → Based on Timecode* pour lier le son ingé, frame-accurate — *Based on Waveform* est un repli, pas un substitut : mauvais résultats sur les scènes à bruit répétitif (moteur/pneus de roulage), retour terrain confirmé.

⚠️ **Sur un projet où du LTC a été décodé avant sept. 2026 (v0.3.90)** : relancer 🎶 Décoder LTC avec **↻ Re-décoder tout** (force) avant de suivre cette méthode — le décodeur avait un décalage systématique de +1 frame, corrigé depuis (voir § Décodeur LTC, piège #37). Des valeurs `ltc_tc_in_sec` non re-décodées reproduiront le taux d'échec d'avant le fix.

**Méthode (l'ordre et l'exhaustivité comptent) :**
1. Importer **TOUS les médias, de TOUTES les caméras, de TOUS les jours** dans le Media Pool — pas un sous-ensemble de test. ⚠️ Un Media Pool incomplet a été une cause d'échecs à l'import précédemment identifiés à tort comme un problème de précision de TC (voir piège #37) : si un jour/une caméra manque, n'importe quel clip de ce lot échoue à l'import FCPXML, sans rapport avec le LTC.
2. Clic droit sur les FS5 → *Timecode → Update Timecode from Audio Track* (Resolve **Studio**). `Frame Rate = 25`, canal LTC : **Channel 2** pour J02–J05, **Channel 1** pour J07–J11, par lot de journée. *(Repli Resolve gratuit / décodage récalcitrant : `fs5_fix_timecode_resolve.py`.)*
3. Importer tous les sons ingé (WAV/BWF).
4. Sélection tout (vidéo + WAV) → *Auto Sync Audio → Based on Timecode*.
5. **Puis seulement** importer le FCPXML de selects (régénéré côté Derush **après** l'étape 2 et après un re-décodage LTC si besoin) → *Import Timeline*, **décocher "Automatically import source clips into media pool bins"** pour forcer le matching contre le Media Pool existant plutôt qu'un réimport silencieux en double.

**Si des clips restent *Media Offline* après ça** (Media Pool complet + TC corrigé + LTC re-décodé confirmés) : relink manuel. Dans le Media Pool, sélectionner (clic simple) le bon clip → clic droit sur le plan offline dans la timeline → **Replace Selected Clip**. Si l'option n'apparaît pas, charger le clip en double-clic dans le **Source Viewer** puis utiliser le bouton d'édition **Replace** de la timeline sur le plan sélectionné.

**Diagnostic** : deux outils, à utiliser ensemble plutôt que de deviner depuis l'extérieur —
- `%APPDATA%\Blackmagic Design\DaVinci Resolve\Support\Logs\davinci_resolve.log` — chercher `failed to link` : une ligne par clip qui échoue à l'import (`The clip "X.MXF" failed to link because the timecode extents do not match any clip in the Media Pool`). Ne précise pas le jour (les noms de fichiers FS5 se répètent sur plusieurs journées) ni si la cause est "absent du Media Pool" ou "présent mais TC désaccordé".
- **API de scripting DaVinci** (§ ci-dessous) pour lever précisément ces deux ambiguïtés : lister les items timeline réellement offline (`GetMediaPoolItem() is None`), les recouper avec le FCPXML importé (désambiguïse le jour) et avec le Start TC réel du Media Pool (détecte un vrai désaccord de précision vs une absence pure et simple).

**Timeline déjà conformée** : ne PAS relancer une correction de TC en masse dessus (piège : *Media Offline* + reconform lent, risque de freeze/crash). Pour un clip FS5 isolé ajouté après coup, traiter individuellement.

**Repli sans TC** : *Auto Sync Audio Based on Waveform* reste l'option pour les clips sans LTC exploitable ou en cas d'échec résiduel après relink — moins précis mais toujours disponible.

**Doc utilisateur autonome** : `D:\METHODOLOGIE_IMPORT_RUSHS_DAVINCI.md` (procédure + tableau canaux LTC par journée) — insister sur l'exhaustivité du Media Pool avant tout import FCPXML.

### API de scripting DaVinci Resolve (diagnostic, sept. 2026)

Resolve expose une API Python officielle pour interroger/manipuler un projet **actuellement ouvert** dans l'appli — précieux pour diagnostiquer des écarts entre ce que Derush exporte et ce que DaVinci a réellement en base, sans dépendre de l'utilisateur pour copier des valeurs à la main.

**Connexion** (Windows, PowerShell) :
```powershell
$env:RESOLVE_SCRIPT_API = "C:\ProgramData\Blackmagic Design\DaVinci Resolve\Support\Developer\Scripting"
$env:RESOLVE_SCRIPT_LIB  = "C:\Program Files\Blackmagic Design\DaVinci Resolve\fusionscript.dll"
$env:PYTHONPATH = "$env:RESOLVE_SCRIPT_API\Modules\;$env:PYTHONPATH"
python -c "
import DaVinciResolveScript as dvr
resolve = dvr.scriptapp('Resolve')
proj = resolve.GetProjectManager().GetCurrentProject()
print(proj.GetName())
"
```
Nécessite Resolve **lancé** avec un projet ouvert (`GetCurrentProject()` échoue sinon). Vérifier d'abord `Test-Path` sur les deux chemins ci-dessus (versions/installs différentes possibles) et `Get-Process -Name Resolve`.

**Objets utiles** :
- `proj.GetMediaPool().GetRootFolder()` → `Folder`, avec `.GetClipList()` (clips de ce bin) et `.GetSubFolderList()` (récursion manuelle nécessaire, pas de walk récursif fourni).
- `MediaPoolItem.GetClipProperty()` (sans argument) → dict complet (`Start TC`, `End TC`, `File Path`, `Online Status`, `FPS`, `Duration`, `Synced Audio`, etc.) — bien plus riche et fiable que de demander à l'utilisateur de lire l'UI.
- `proj.GetCurrentTimeline()` → `Timeline`, avec `.GetTrackCount('video')` et `.GetItemListInTrack('video', n)` → liste de `TimelineItem`.
- `TimelineItem.GetMediaPoolItem()` retourne `None` pour un item **offline/non lié** — c'est LE test fiable pour détecter un plan qui a échoué à se relier à l'import (`GetClipProperty` n'existe pas sur un `TimelineItem` offline puisqu'il n'a justement aucun Media Pool item associé). `GetName()`, `GetStart()`/`GetEnd()` (position frame dans la timeline), `GetDuration()` restent lisibles même offline.
- Un `TimelineItem` offline n'expose PAS son TC source déclaré (`GetSourceStartFrame()` renvoie `None`) → pour le retrouver, croiser `(GetName(), GetDuration(), GetStart())` avec le FCPXML réellement importé (parsé en Python, `<asset-clip offset/duration/start>` + `<asset ref/src>`) — ce triplet désambiguïse de façon fiable même quand plusieurs jours partagent le même nom de fichier (cas FS5 : `ClipNNNN.MXF` réutilisé chaque journée).

**Limite** : pas d'outil de contrôle souris/clavier dans cette session (pas d'automation de l'UI Resolve, pas de clic sur les menus) — uniquement lecture/écriture de données via l'API scripting. Suffisant pour tout le diagnostic TC de la saga FS5 (piège #37).

### Modale d'export (📤, `derush_app.html` `#exportModal`)
Section « Timelines de selects » (FCPXML et XML Premiere) : boutons rapides `exportDataWithParams(fmt, {min_rating:N, label})` — `N=3` (⭐⭐⭐ uniquement), `N=2` (⭐⭐ et plus), `N=1` (⭐ et plus, retour terrain sept. 2026 : « un filtre pour exporter que les clips qui ont au moins une étoile »). Le filtre `min_rating` était déjà générique côté serveur (`derush_exports.py`, `fc_min_rating` — inclut un clip dès qu'**un seul membre de l'équipe**, tous confondus, lui a mis au moins cette note) : ajouter le bouton `min_rating:1` suffit, aucun changement serveur nécessaire. Même ladder 3/2/1 déjà utilisée par le sélecteur "Rating min." du rough cut (`#rcRating`).

Sous les boutons FCPXML de « Timelines de selects », une ligne « Markers EDL correspondant » : un `exportDataWithParams('markers_edl', {...})` par filtre, MÊMES params (`min_rating`/`cats`/`rejected`/`label`) que le bouton FCPXML au-dessus. L'endpoint passe `filter_config` à `export_markers_edl` (v0.3.83) et nomme le fichier avec `label`. Prendre timeline + EDL du même filtre — voir § EDL Marqueurs DaVinci pour le détail de l'alignement.

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
- Endpoint `POST /api/project/<pid>/set_root_path` : met à jour user + session live — **ne touche jamais `clip['path']`** (figé au scan), seulement le `root_path` utilisé pour résoudre les fichiers dynamiquement (streaming/vignettes déjà tolérants, exports depuis sept. 2026 — voir piège #36). Le front passe ce `root_path` en query param `?root=` sur les exports FCPXML/Premiere (`_exportRootParam(fmt)` dans `derush_app.html`, + `_basketExport` dans `js/selects.js`) : sans ça, si l'ancien disque (E:) est toujours branché, l'export garde ses chemins car `clip['path']` littéral existe encore — l'utilisateur a beau avoir pointé F:, DaVinci ouvre E: (piège #36, 2e passe)
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
GET  /api/project/<id>/basket                       (paniers de toute l'équipe)
GET  /api/project/<id>/lut_assign                    (LUT publiées de toute l'équipe — hash + réglages, pas le contenu)
GET  /api/project/<id>/lut/<hash>                    (contenu .cube par hash — fallback cloud si absent localement)
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
POST /api/project/<id>/basket                        (sauvegarder son panier)
POST /api/project/<id>/lut_assign                     (publier son assignation LUT — hash + réglages)
POST /api/project/<id>/lut/upload                     (uploader un .cube, body {content} → {hash}, dédupliqué)
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
- Frames envoyées après : save notes (`notes_updated`), reply (`discussion_updated`), save panier (`basket_updated`), publication LUT (`lut_assign_updated`)
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

### Pré-montage (Basket overlay, `js/selects.js`)

Bouton 📽️ → overlay plein écran (`#basketOverlay`) : liste réordonnable des sélections de l'user (`#basketBody`, 1/3 gauche) + visionneuse dédiée (`#basketViewer`, reste). Identifiants internes restés `basket`/panier (`allBaskets[uid]`, endpoints `/api/.../basket`) — voir en-tête du fichier pour le choix de vocabulaire affiché vs interne.

**Dupliquer une sélection** (`⧉` dans `.basket-item-actions`, `_basketDuplicateItem(idx)`) — retour terrain : « pouvoir copier coller une sélection plusieurs fois dans le prémontage » (répéter un même plan à plusieurs endroits du montage, ex. un plan de coupe/réaction). Un clic = une copie insérée juste après l'original dans `allBaskets[uid]` ; re-cliquer (sur l'original ou une copie) ajoute une copie de plus — "coller plusieurs fois" sans presse-papier/état de sélection à gérer, combiné au glisser-déposer déjà existant pour repositionner une copie ailleurs dans la bobine. Crée une **sélection indépendante** (nouvel id aléatoire dans `n.selects`, mêmes `in`/`out`/`tags`/`desc` au départ, nom suffixé `" (copie N)"` via `_basketNextSuffixedName` — voir plus bas) plutôt que de réutiliser `select_id` — sinon retrimmer une copie depuis la timeline de séquence (qui mute `sel.in`/`out` en place) changerait aussi silencieusement toutes les autres occurrences de la même sélection dans le pré-montage. Deux poussées d'annulation distinctes (`pushUndo(clip.id)` pour `allNotes`, `_pushBasketUndo()` pour `allBaskets`), même pattern déjà utilisé par `confirmSelect()` pour une nouvelle sélection auto-ajoutée au pré-montage — Ctrl+Z peut donc nécessiter deux appuis pour tout annuler.

**Double lecteur crossfade** (`#basketVid`/`#basketVidB`, `_basketActiveVid()`/`_basketInactiveVid()`) : quand le segment suivant est sur un clip **différent** de celui en lecture, il est préchargé en arrière-plan dans le lecteur inactif (`_basketPreloadNextSegment`, identité clip **+** sélection via `dataset.clipId`/`dataset.selectId`) pour basculer instantanément sans flash noir ni gel. Quand il est sur le **même** clip que l'actif, `_basketPreloadNextSegment` s'abstient explicitement — recharger un fichier déjà en cours de décodage dans l'autre élément juste pour y basculer ensuite est coûteux et, répété sur toute une série de sélections découpées dans le même rush (le cas le plus courant du pré-montage), a fini par ne plus jamais finir à temps → flash noir à chaque transition → crash du renderer Electron après une ou deux lectures (retour terrain, build packagée, sept. 2026). Cette transition reste fluide via le chemin de repli de `_basketGoto` (pause → seek → attend `seeked` → reprend, sur l'élément déjà chargé, sans rien recharger) — voir piège CLAUDE.md #31 et `HISTORY.md` v0.3.42/v0.3.65 pour le détail des sagas de fluidité (y compris cette dernière correction).

**Timeline de séquence** (`#basketSeqTimeline`, sous la visionneuse) : toutes les sélections « collées » bout à bout, largeur proportionnelle à la durée retenue (`_basketSeqSegments`/`_basketRenderSeqTimeline`). Molette = zoom ancré sous le curseur (`_basketSeqWheel`, `_basketSeqZoom` 1–25). Clic/glisser sur la piste = scrub dans toute la séquence (`_basketSeqMouseDown`/`_basketSeekSeqRatio`, appelle `_basketGoto(..., scrubbing=true)` — voir piège #31 sur pourquoi le scrub garde un chemin dédié sans attente `seeked`).

**Réordonner directement sur la timeline de séquence** (façon DaVinci, `_wireBasketSeqSegDrag`, `isMine` seulement) — retour terrain : « clic gauche sur un clip dans la timeline pour le déplacer et l'intercaler entre deux clips ou au début/fin de la séquence ». Drag-and-drop natif HTML5 sur le **corps** du segment (`el.draggable = true`), distinct du drag mousedown/mousemove custom des poignées de trim (`handleIn.draggable = handleOut.draggable = false` + leur `preventDefault`/`stopPropagation` sur `mousedown` empêchent le drag natif de démarrer quand on saisit précisément une poignée). La **moitié survolée** du segment cible (`dragover`, comparaison à `rect.width/2`) détermine si le clip glissé s'insère avant (`.drop-before`, liseré vert à gauche) ou après (`.drop-after`, à droite) — permet de viser précisément l'intercalation entre deux clips, ou le tout début/toute la fin en lâchant sur la moitié extérieure du premier/dernier segment. `_basketSeqReorder(fromIdx, toIdx, before)` fait le même travail sur `allBaskets[uid]` que `_wireBasketDrag` (réordonnancement depuis la LISTE à gauche) — deux implémentations séparées, même sous-jacent (`splice`+`_pushBasketUndo`+`saveBasket`). Le clic initial sur le segment déclenche aussi le scrub existant (`_basketSeqMouseDown` reste attaché à l'ancêtre `#basketSeqTimeline`, non court-circuité) : effet de bord accepté (la tête de lecture saute au point cliqué avant que le drag natif ne prenne la main), pas gênant en pratique.

**Précision de trim façon DaVinci (sept. 2026)** — retour terrain : glisser une poignée `.bseq-handle-in`/`-out` perdait facilement le point d'atterrissage précis. Trois briques dans `js/selects.js`, juste avant `_wireBasketSeqHandle` :
- `_basketSnapClamp(edge, rawT, otherBound, fps, clipDur, minDur)` — arrondit **toujours** à la frame exacte (`Math.round(t*fps)/fps`) puis clampe ; utilisée à la fois par le glisser souris et le nudge clavier, donc les deux méthodes convergent vers la même grille.
- `_basketFmtDelta(deltaSec, fps)` → `{text:"+1s04f"/"−12f"/"±0f", cls:"pos"/"neg"/"zero"}`.
- `_basketShowTrimHud(handleEl, tcText, deltaSec, fps, hint)`/`_basketHideTrimHud()` — bulle `#basketTrimHud` (`position:fixed`, repositionnée en JS au-dessus de la poignée) affichant TC exact + delta depuis le point de départ + rappel des raccourcis, visible en continu pendant tout le geste (glisser ou nudge clavier) — la vraie réponse à « je ne sais plus où j'atterris ».

**Trim armé au clavier** (`_basketArmedTrim`, état global) : cliquer une poignée **sans glisser** l'« arme » (`_basketArmTrimHandle`) au lieu de ne rien faire — façon DaVinci, sélectionner un point de montage puis `←`/`→` (1 frame) ou `Maj+←`/`→` (1s) l'ajuste précisément (`_basketNudgeArmedTrim`, géré dans `_basketKeydown`). `Entrée` valide (`_basketCommitArmedTrim`), `Échap` annule (`_basketCancelArmedTrim`, `sel.in`/`out` jamais mutés tant que non validé — même principe que le glisser, un seul `pushUndo`/`saveNotes` par session de trim, pas un par frappe).
- **Piège DOM évité** : valider un trim armé rappelle `renderBasketOverlay()` → `_basketRenderSeqTimeline()` **détruit et recrée toutes** les poignées (`track.querySelectorAll('.basket-seq-seg').forEach(el=>el.remove())`), y compris celle qu'on vient potentiellement de cliquer dans le même geste. `_wireBasketSeqHandle` flush donc un trim armé en tête de `mousedown` puis **s'arrête là** (`return`) plutôt que de continuer avec une référence `handleEl` désormais détachée (un `getBoundingClientRect()` sur un nœud hors document renvoie des zéros → HUD mal positionné) — un second clic engage la nouvelle poignée sur un DOM frais.
- **Garde anti-référence-obsolète générale** : `renderBasketOverlay()` commence par `if(_basketArmedTrim) { _basketCommitArmedTrim(); return; }` — tout re-rendu déclenché ailleurs (ajout/retrait/réorganisation d'item, switch d'utilisateur affiché) valide d'abord le trim en attente ; `_basketCommitArmedTrim()` vide `_basketArmedTrim` **avant** son propre appel à `renderBasketOverlay()`, donc pas de récursion infinie. `_basketGoto()` et `closeBasket()` flushent aussi explicitement (navigation ou fermeture = validation implicite).
- **Flèches à double rôle** dans `_basketKeydown` : nudge du point armé s'il y en a un, sinon nudge classique de la tête de lecture (`1/fps` / `Maj` = 1s) — mêmes conventions que le lecteur principal (`derush_app.html`, `ArrowLeft`/`ArrowRight`).

**Repères de séquence + magnétisme (sept. 2026)** — retour terrain suivant : « des petits marqueurs, pas ceux avec des commentaires, juste des repères pour faire coulisser les poignées à cet endroit précis avec un peu de magnétisme ». Distincts des marqueurs annotés (`addMarker`, catégorie/description/discussion, posés sur UN clip) : ce sont de simples points d'accroche, **personnels**, en **secondes-séquence** (position dans la bobine assemblée, pas dans un clip source) :
- État : `_basketSeqMarkers` (array de floats triés), persisté en `localStorage['derush_basket_seq_markers_' + pid]` (`_loadBasketSeqMarkers`/`_saveBasketSeqMarkers`) — même logique que `_lutAssign`/`_bwfMixerSettings`, pas dans `allNotes`/le projet partagé. Chargés à `openBasket()`.
- UI : lane dédiée `#basketSeqMarkers` (12px, au-dessus de `#basketSeqTimeline`, largeur synchronisée en JS à chaque zoom — `_basketSeqWheel`). **Clic simple** sur la lane = ajoute un repère à cette position ; **clic maintenu + glisser** = scrube la séquence à la place (retour terrain : « plutôt que de placer un repère quand je clique au-dessus de la timeline, que je puisse me déplacer dans la sélection quand je maintiens le clic gauche »). `_basketMarkerLaneMouseDown(e)` : même distinction seuil-de-3px clic/glisser que les poignées de trim et le réordonnancement des segments — si le mouvement dépasse le seuil, appelle en boucle `_basketSeekSeqRatio(ratio)` (même mécanisme que le scrub de `_basketSeqMouseDown` sur la piste juste en-dessous) ; sinon, au relâchement, pose un repère (`_basketDeselectSeqMarker()` + `_basketAddSeqMarkerAt`). Les pins de repère (`.basket-seq-marker-pin`, enfants de la lane) stoppent la propagation dès leur PROPRE `mousedown` (pas seulement leur `click`) pour ne jamais déclencher aussi la logique de la lane parente. Bouton `Repère` (`#basketAddMarkerBtn`, `.basket-seq-toolbar` alignée à **gauche** au-dessus de la timeline) et touche **`M`** = ajout direct à la position de lecture courante (`_basketAddSeqMarkerAtPlayhead`, même formule de position-séquence que `_basketUpdateSeqHead`) — chemins qui ne passent pas par la lane, donc pas concernés par la distinction clic/glisser. Icône du bouton = même losange ambre que les repères sur la timeline (`.bseq-marker-diamond`, classe de base partagée avec `.basket-seq-marker-pin` — celle-ci surcharge juste `width`/`height` à 9px via l'ordre du CSS, le bouton reste à 8px).
- **Clic sur un repère existant = sélection + seek, PAS suppression** (retour terrain explicite : « je ne veux pas que le clic l'efface, je veux avancer le clip à cet endroit et voir l'image ; la suppression doit être un geste à part »). `_basketSelectSeqMarker(t)` : marque `_basketSelectedSeqMarker = t` (valeur en secondes, pas un index — un index se périmerait au moindre ajout/retrait puisque le tableau est retrié), ré-affiche le repère en surbrillance (`.basket-seq-marker-pin.selected`), puis traduit `t` en `{idx, offset}` via `_basketSeqTimeToSegmentOffset(t)` et appelle `_basketGoto(idx, offset, false)` — la visionneuse affiche l'image exacte à cet endroit, en pause. `Suppr`/`Backspace` (dans `_basketKeydown`, uniquement si un repère est sélectionné) → `_basketDeleteSelectedSeqMarker()`. `Échap` : cascade de priorité — annule d'abord un trim armé s'il y en a un (`_basketArmedTrim`), sinon désélectionne le repère s'il y en a un (`_basketDeselectSeqMarker()`, retourne `false` si rien n'était sélectionné), sinon ferme l'overlay (`closeBasket()`).
- **Magnétisme** (dans `onMove` de `_wireBasketSeqHandle`, drag souris uniquement — le trim clavier armé reste volontairement exact/non magnétique, il a déjà sa propre précision) : rayon d'accroche en **pixels écran** (10px, indépendant du zoom) converti en secondes via `pxPerSec` courant. Ne compare JAMAIS la position brute du point dragué à un repère — compare la **frontière qui bouge réellement dans la séquence** pour ce segment, qui est TOUJOURS sa frontière avec le segment SUIVANT (`seg.start + dur`), quelle que soit la poignée tenue : `_basketSeqSegments()` positionne chaque bloc en cumulant les durées des précédents, donc la frontière d'un segment avec son PRÉCÉDENT ne bouge jamais quand on trimme CE segment — seule sa frontière avec le suivant se déplace (piège potentiel si on modélise ça autrement : le point qu'on croit intuitivement "ancré à la poignée in" ne l'est pas visuellement, cf. la poignée `bseq-handle-in` en `left:0` d'une boîte dont c'est justement le bord DROIT qui bouge). Si un repère est dans le rayon, `_basketNearestSeqMarker` le retourne, la durée cible est recalculée puis repassée dans `_basketSnapClamp` (donc re-alignée sur la grille de frames — l'accroche peut être à moins d'une frame du repère exact, jamais pile dessus si ça tombe entre deux frames). HUD (`_basketShowTrimHud`) affiche un 🧲 suffixé au TC quand accroché.
- **Limite assumée, pas un bug** : un repère est un nombre en secondes-séquence figé — si on retrime largement un segment plus tôt dans la bobine (ou qu'on réordonne), la position "logique" que visait le repère peut ne plus correspondre au même instant qu'à sa création (pas de ripple automatique des repères, comme dans la plupart des NLE hors mode ripple-marker dédié). Comportement volontaire, pas dans le scope demandé.

**Couper (façon DaVinci, sept. 2026)** — retour terrain : « ajouter un outil cut dans le prémontage à côté de repère mais aussi en appuyant sur C qui me permet de couper un clip dans la timeline ». Bouton `#basketCutBtn` (à côté de `#basketAddMarkerBtn` dans `.basket-seq-toolbar`) et touche **`C`** (`_basketKeydown`) → `_basketCutAtPlayhead()` (`js/selects.js`, juste après `_basketCancelArmedTrim`) : scinde en deux la sélection chargée dans la visionneuse, à la position de lecture courante (`vid.currentTime`, snap frame-exact comme le trim). Même schéma que `_basketDuplicateItem` (auquel il emprunte le pattern de save) : la 1ère moitié réutilise `sel`/`select_id` (mute `sel.out = cutT` en place), la 2e moitié est un **nouvel enregistrement** dans `n.selects` (nouvel id, `in:cutT, out:origOut`, nom suffixé `" (cut N)"` via `_basketNextSuffixedName`) avec un nouvel item inséré juste après dans `allBaskets[uid]` — jamais de mutation partagée entre les deux moitiés, retrimmer l'une n'affecte pas l'autre. Refuse la coupe (toast warn) si `sel.out - sel.in < _BASKET_TRIM_MIN_DUR * 2` (pas de marge suffisante) ou si le point clampé tomberait à moins de `_BASKET_TRIM_MIN_DUR` (~2 frames) d'un bord — réutilise la même constante que le trim, pas de moitié de durée quasi nulle. `isMine` seulement (bouton masqué via `renderBasketOverlay()` sinon, même toggle que `#basketClearBtn`) ; flush un trim armé en attente (`_basketCommitArmedTrim()`) avant de couper, comme les autres gestes qui déclenchent un re-rendu de la timeline de séquence.

**Nommage numéroté des sélections générées** (`_basketNextSuffixedName(selects, name, suffix)`, `js/selects.js`, juste avant `_basketDuplicateItem`) — retour terrain : « tu peux la nommer avec le suffixe cut et un numéro [...] quand je copie un même clip tu peux la nommer avec le suffixe copie et un numéro » (avant : suffixe fixe `" (copie)"` / `" (2)"` identique à chaque nouvelle occurrence, aucun moyen de distinguer copie 1 de copie 2 par le nom seul). Partagée par `_basketDuplicateItem` (`suffix='copie'`) et `_basketCutAtPlayhead` (`suffix='cut'`) : `_basketBaseSelectName(name)` retire d'abord un éventuel suffixe `" (copie N)"`/`" (cut N)"` déjà présent (regex) pour retomber sur le nom de base, puis balaie **toutes** les sélections du même clip (`n.selects`, avant l'ajout du nouvel enregistrement) cherchant `"<base> (<suffix> N)"` pour prendre le N max + 1 — numérote donc à plat même si on duplique une copie ou coupe un segment déjà issu d'une coupe, jamais d'empilement `" (copie 1) (copie 1)"`. Les deux suffixes (`copie`/`cut`) ont leur propre compteur indépendant sur un même clip.

**Renommer une sélection** (`✏️` dans `.basket-item-actions`, à côté de `⧉` et `🗑`) — retour terrain : « je voudrais pouvoir aussi renommer les sélections dans le prémontage à côté de copie et supprimer ». Petite modale dédiée `#basketRenameOverlay`/`#basketRenameInput` (`derush_app.html`, juste après `#basketOverlay`) plutôt qu'un `prompt()` natif (piège #1 : casse le focus state sous Electron) ou une édition inline dans `.basket-item-name` — le `body.innerHTML` entier de la liste est reconstruit à chaque `renderBasketOverlay()` (poll 15s, WS `basket_updated`), ce qui détruirait un champ en cours d'édition inline. `_basketRenameItem(idx)` (`js/selects.js`, juste après `_basketDuplicateItem`) stocke `_basketRenameItemRef = r.item` (référence par **identité** de l'item du panier, pas par index — même raison que `_basketCurrentItemRef` : l'index dans `_basketLastResolved` peut se périmer si un re-rendu externe survient pendant que la modale reste ouverte). `_basketConfirmRename()` retrouve l'item via `_basketLastResolved.find(x => x.item === _basketRenameItemRef)`, refuse un nom vide (toast warn), mute `r.sel.name` en place (même objet que dans `n.selects`, pas de nouvel enregistrement — contrairement à dupliquer/couper), `pushUndo(r.clip.id)` + `saveNotes(true)`. `Entrée` valide, `Échap` annule (`_basketRenameKeydown` sur l'input) ; `closeBasket()` annule aussi la modale si elle était restée ouverte.

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
- **"Ce rush uniquement"** (mode `clip` dans la modale de scope) écrit directement un override explicite pour le plan actif. `confirmLutScope()` ne lit les checkboxes `.lutScopeCam` que si `mode === 'cameras'` — en mode `clip` elles sont ignorées. `_lutScopeModeChanged()` (déclenché au `onchange` des radios + à l'ouverture de la modale) grise/désactive visuellement la liste des caméras quand `clip` est sélectionné, pour ne pas laisser croire qu'une caméra restée cochée (ex. FS5 pré-cochée par défaut) sera aussi affectée (v0.3.60).
- **Retirer une LUT d'un plan** : bouton `🗑 Retirer la LUT de ce plan` (`#lutRemoveWrap`, visible seulement si le plan a un override `clip` — pas pour un défaut `camera`) → `_lutRemoveForActiveClip()` supprime l'entrée `_lutAssign.clips[id]`, le plan retombe sur le défaut caméra s'il existe.
- Recharger un fichier `.cube` du **même nom** mutualise (met à jour partout où ce `lutName` est référencé) — comportement volontaire pour permettre de retoucher un export de grade et le repousser sans tout ré-assigner.

**Globals JS** :
```javascript
let _lutEnabled = false, _lutRaf = null, _lutGL = null, _lut = null, _lutCurrentLutName = null;
let _lutLibrary = {}, _lutAssign = {cameras: {}, clips: {}};
let _lutSettings = {intensity: 1.0, exposure: 0.0, saturation: 1.0, contrast: 0.0, temperature: 0.0, tint: 0.0};
```
`_lutGL = {gl, prog, vao, videoTex, lutTex, u_*, lutUploaded}` — un seul contexte/programme créé paresseusement (`_lutInitGL`), réutilisé ensuite (upload LUT via `_lutUploadLUT` seulement quand `_lutCurrentLutName` change, uniforms de réglage repoussés à chaque `_lutRefreshForActiveClip()`/changement de slider).

`_lutRefreshForActiveClip()` (async, protégée par `_lutRefreshToken` contre un changement de clip pendant l'attente IndexedDB) résout la LUT du plan actif, la charge si besoin (`_lutEnsureLoaded`, mémoire puis IndexedDB), met à jour canvas/badge/panneau/bouton. Appelée par : sélection de clip (`selectClip` → `js/audio-bwf.js`), `toggleLUT()`, `confirmLutScope()`, `_lutRemoveForActiveClip()`. `_lutLoadAssign(pid)` recharge `_lutAssign` **et `_lutEnabled`** depuis `localStorage` à l'entrée dans un projet (`enterWorkspace`) — voir « Persistance au redémarrage » ci-dessous.

**Flow utilisateur** :
1. `📂 LUT` → `<input type="file" accept=".cube">` → `onLUTFileSelected` → crée `_lutGL` si besoin (alerte si WebGL2 indisponible) → ajoute à `_lutLibrary` + IndexedDB → ouvre la modale de scope (caméras ou ce rush uniquement)
2. `🎨 LUT` → `toggleLUT()` — master preview on/off, persisté par projet (voir ci-dessous). Panneau réglages auto-affiché/masqué en même temps que le canvas (visible seulement si une LUT est résolue pour ce plan ET le master est actif)
3. Badge `LUT` affiché sur la vidéo quand actif

**Persistance au redémarrage** (sept. 2026, retour terrain : « garder en mémoire pour chaque clip le fait qu'on a appliqué des réglages au LUT... qu'au relancement la LUT apparaisse bien sur les clips où je l'ai appliquée, avec ses réglages propres ») — les assignations elles-mêmes (`_lutAssign`, quelle LUT + quels réglages par clip/caméra) étaient déjà persistées dans `localStorage` depuis l'origine du modèle d'assignation par plan. Ce qui manquait : `_lutEnabled` (l'interrupteur maître 🎨) repartait TOUJOURS à `false` au démarrage (`session, pas persisté` dans le commentaire d'origine) — donc rien ne s'affichait tant qu'on n'avait pas re-cliqué sur 🎨, même avec toutes les données déjà là. Fix :
- `_lutPersistEnabled()` (nouvelle fonction, symétrique de `_lutPersistAssign()`) écrit `_lutEnabled` dans `localStorage['derush_lut_enabled_' + pid]` — appelée depuis `toggleLUT()` et `confirmLutScope()` (les deux seuls points qui mutent `_lutEnabled` directement).
- `_lutLoadAssign(pid)` relit cette clé en plus de `_lutAssign` — donc au relancement, `enterWorkspace(pid)` → `_lutLoadAssign(pid)` restaure `_lutEnabled` AVANT que la restauration du dernier clip consulté (`_loadClipResumeTime` → `selectClip` → `_lutRefreshForActiveClip`) ne décide d'afficher ou non le rendu — aucun autre changement nécessaire, le mécanisme de résolution/rendu existant fonctionnait déjà correctement une fois `_lutEnabled` correctement restauré.
- Persisté **par projet** (comme `_lutAssign`) — activer la preview LUT sur un projet n'affecte pas les autres.

**Panneau réduit → languette collée à la toolbar** (sept. 2026) — retour terrain en trois temps : (1) « pouvoir la diminuer pour que ça ne prenne pas trop de place » (1er jet : ne cachait que les sliders, titre+Reset restaient visibles) ; (2) « je veux que Réglages LUT et Reset ne soit plus visible, juste un petit bout qui dépasse, comme Photoshop » (2e jet : panneau réduit à une languette interne à `#lutSettingsPanel`) ; (3) « je veux juste une petite languette collée à la barre latérale au niveau de la sélection des LUTs, comme un marque-page qui sortirait légèrement d'un livre » — design final :
- Réduit = `#lutSettingsPanel` **entièrement caché** (`display:none`, comme fermé) ; une languette **séparée** `#lutPanelTab` (bouton vide, 12×30px, coins arrondis à gauche seulement, `box-shadow` vers la gauche pour l'effet "dépasse du bord") prend le relais, positionnée en `position:absolute` dans `#videoWrapper`.
- `_lutPositionPanelTab()` aligne la languette sur le bouton `#lutBtn` (🎨, dans `.player-toolbar`) via `getBoundingClientRect()` des deux éléments + de `#videoWrapper` (conversion en coordonnées relatives à l'ancêtre positionné du panneau) — recalculé à CHAQUE affichage plutôt que mémorisé, pour rester juste après un redimensionnement de fenêtre. Même technique que le panneau du mixeur BWF (`js/bwf-mixer.js`) pour un problème similaire (deux boutons déclencheurs dans des zones DOM différentes).
- **Piège d'ordre trouvé et corrigé avant livraison** : `_lutPositionPanelTab()` lit la position de `#lutBtn`, qui doit donc déjà être visible (`display:''`) au moment du calcul — `_lutUpdateBtnVisual(resolved)` doit impérativement s'exécuter **avant** `_lutSettingsUpdateUI()`/`_lutApplyPanelCollapsed()` dans `_lutRefreshForActiveClip()`, pas après (l'ordre "naturel" du code aurait mis à jour le bouton en dernier).
- `_lutPanelShouldShow` (bool) reflète si un panneau — sous une forme ou une autre — doit être visible EN CE MOMENT (LUT résolue + preview active) ; piloté uniquement par `_lutRefreshForActiveClip()`, lu par `_lutApplyPanelCollapsed()` pour choisir entre tout cacher (rien à régler), afficher le panneau complet, ou afficher la languette — sans quoi la languette pourrait apparaître collée à la toolbar même sans LUT active, un onglet qui ne mène nulle part.
- `_lutTogglePanelCollapsed()` bascule `_lutPanelCollapsed` (bool, persisté `localStorage['derush_lut_panel_collapsed']`) puis rappelle `_lutApplyPanelCollapsed()`. Le panneau (sous une forme ou une autre) reste toujours affiché tant qu'une LUT est active — replié, il ne se referme pas tout seul, distinct du show/hide global lié à `_lutEnabled`+LUT résolue.

**LUT dans le pré-montage** (sept. 2026, retour terrain : « quand j'applique une LUT sur un clip, ça affecte aussi les sélections de ce clip dans le pré-montage ») — pipeline WebGL **indépendant** du lecteur principal, dans `js/selects.js` (dépend de l'état du panier) plutôt que `js/lut.js` : `_basketLutGL`/`_basketLutRaf`/`_basketLutCurrentLutName`, canvas `#basketLutCanvas` (dans `#basketViewerVideoWrap`, `z-index:0` — sous l'overlay de cadre dynamique `z-index:1`, au-dessus des `<video>` en `z-index:auto`/ordre DOM). Un seul canvas pour les **deux** lecteurs du crossfade (`#basketVid`/`#basketVidB`) : `_basketRenderLUT()` relit `_basketActiveVid()` à chaque frame plutôt que d'avoir sa propre notion de "lequel afficher" — le swap crossfade est donc suivi automatiquement.
- `_lutInitGL`/`_lutUploadLUT`/`_lutApplySettings` (déjà génériques ou rendues génériques pour ce besoin — `_lutUploadLUT(glCtx, lutData)`/`_lutApplySettings(glCtx, settings)` acceptent maintenant un contexte GL + des données en paramètres, défaut sur les globals `_lutGL`/`_lut`/`_lutSettings` du lecteur principal si omis, donc **aucun** appelant existant à modifier) sont réutilisées telles quelles — pas de duplication du shader/pipeline d'upload.
- `_basketLutRefresh()` (async) résout la LUT du clip **affiché dans le pré-montage** (`_basketLastResolved[_basketPlayIdx].clip`, indépendant de `activeClip` le lecteur principal). Sur SON PROPRE panier (`_basketViewUser === currentSession.user_id`, le cas courant) : même `_lutResolveFor(clip)`/`_lutEnsureLoaded(lutName)` génériques qu'avant. Sur le panier D'UN AUTRE collaborateur : bascule sur `_lutResolveForRemote(uid, clip)`/`_lutEnsureLoadedByHash(hash)` pour afficher SA LUT publiée — voir § LUT partagée pour le détail complet de ce second chemin. Se garde elle-même : si `#basketOverlay` n'a pas la classe `.active`, coupe la boucle RAF et masque le canvas sans rien faire d'autre — permet de l'appeler sans condition depuis n'importe où (elle est appelée après CHAQUE sortie de `_lutRefreshForActiveClip()` — toggle maître, changement de scope, retrait de LUT — ainsi que par `setLutSetting`/`resetLutSettings` directement, et par `_basketGoto`/`_basketSwapActiveVideo`/`openBasket()`) sans que l'appelant ait besoin de savoir si le pré-montage est ouvert.
- Respecte le même toggle maître `_lutEnabled` que le lecteur principal — pas de bouton 🎨 séparé pour le pré-montage, l'activer une fois l'active partout.

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

**Popups marker/select oubliés du périmètre (v0.3.63)** : `#popupOverlay`+`#markerPopup` (nouveau marqueur) et `#selectPopupOverlay`+`#selectPopup` (sélection in/out) étaient restés siblings de `.player-fs-wrap`, pas descendants — la Fullscreen API ne peint que le sous-arbre de l'élément fullscreen, donc ces popups `position:fixed` continuaient d'exister (remplis, `display:block`) mais n'étaient tout simplement plus rendus à l'écran tant qu'on ne quittait pas le plein écran (retour terrain : « je mets un marqueur en fullscreen, la fenêtre ne s'affiche pas, elle est visible dès que je sors »). Fix : les deux blocs déplacés à l'intérieur de `.player-fs-wrap`, juste avant sa fermeture. Comme `position:fixed` a pour containing block le viewport tant qu'aucun ancêtre n'a de `transform`/`filter`/`contain` (`.player-fs-wrap` n'en a pas), le déplacement est neutre hors plein écran — même position, même z-index, seule la visibilité en plein écran change.

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
6. **Calibration -1 frame (sept. 2026)** : le calcul de l'étape 5 seul est systématiquement en avance d'exactement 1 frame par rapport au décodeur natif DaVinci (*Update Timecode from Audio Track*) — validé empiriquement sur 22 clips FS5 réels, 6 journées, toujours le même écart dans le même sens (jamais 0 ni 2 frames). Cause racine (probablement un détail de la correspondance bit/sample dans les étapes 2-5) non isolée avec certitude ; `-frame_period` appliqué en calibration empirique en attendant mieux. Voir piège #37 pour le détail de l'investigation.

**Pièges du décodeur** :
- Avant le fix (v0.3.x, ancien) : retournait le 1er sync trouvé sans valider la cohérence → faux positifs sur bruit (chaise qui grince donnait un TC bidon). Bug observé sur Clip0037 J04 qui donnait 16:52:10 (faux) au lieu de 16:59:09 (réel), causant un mauvais appariement multicam.
- **Décalage systématique de +1 frame (corrigé sept. 2026)** : voir étape 6 ci-dessus. ⚠️ Les valeurs `ltc_tc_in_sec` déjà décodées et cachées dans un projet AVANT ce fix restent fausses d'1 frame — **relancer 🎶 Décoder LTC avec `↻ Re-décoder tout` (force)** pour les recalculer sur les projets existants (ex. DRIFT_CLUB, 127 clips concernés).
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
| `_patch_fx6_proxy.py` | one-shot DRIFT_CLUB : les proxys caméra FX6 (`Sub/`) ont été re-transcodés sans le suffixe Sony `S03` → tous les FX6 affichaient « vidéo introuvable ». Réécrit `proxy_url` `Sub/<stem>S03.MP4` → `Sub/<stem>.MP4` pour les 225 clips FX6, uniquement si le fichier cible existe. Ne touche qu'à `proxy_url` — pas aux IDs, aux `notes`, ni à `ltc_tc_in_sec` (contrairement à un rescan qui régénère `clips[]` et efface le LTC décodé). Sept. 2026 |
| `fs5_fix_timecode_resolve.py` | one-shot DRIFT_CLUB : script à coller dans la Console DaVinci Resolve — réécrit le Start TC des 127 rushes FS5 (clés `<dossier jour>/<fichier>`) avec le vrai timecode décodé du LTC audio par Derush (`ltc_tc_in_sec`), le TC interne FS5 étant faux. Démarre en `DRY_RUN=True`. **Se lance sur les clips du Media Pool DaVinci** (pas via Derush — le FCPXML garde le TC MXF depuis v0.3.86), avant l'*Auto Sync Audio → Based on Timecode*. **Piège vécu** : sur un projet où la timeline picture est DÉJÀ montée/conformée sur l'ancien TC, changer le Start TC fait passer les clips *Media Offline* + reconform lent → Resolve peut freezer/crasher. Dans ce cas, synchro **waveform** ou set du Start TC clip par clip. `fs5_revert_timecode_resolve.py` répare le cas offline |
| `fs5_revert_timecode_resolve.py` | retour arrière du précédent : remet le Start TC des FS5 à la valeur du fichier MXF (= `clip['tc_in']` Derush) pour ré-online la timeline picture. Puis synchro son par waveform |
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
30. **Le sync cloud n'est pas un historique versionné — il propage les régressions**. `merge_projects()` repart du remote mais réimpose les notes de `own_uid` depuis le fichier local ; un local rétrogradé (restauration système Windows, rollback disque, mauvais recovery) écrase donc la version cloud de cet utilisateur au premier sync du redémarrage, et un push suivant la grave définitivement côté serveur. Seule protection réelle : les sauvegardes. Depuis v0.3.61 → `save_project` **et** `derush_sync.php` gardent 40 rolling horodatées + 90 quotidiennes (`_daily_AAAAMMJJ.json`, hors cycle rolling) ; les deux implémentations doivent rester identiques et le PHP ré-uploadé pour que le serveur en profite. En récupération après ce type d'incident : NE PAS relancer l'app (chaque démarrage peut re-pusher et faire tourner les backups serveur), récupérer d'abord `derush_data/backups/<pid>/` par FTP, réinjecter les `notes[own_uid]` de la bonne version dans le projet courant sans toucher aux autres users. Incident fondateur : 01/09/2026 (détail dans `HISTORY.md`).
31. **Un seek sur un flux vidéo long-GOP EN COURS DE LECTURE n'est jamais "déjà instantané"**, même sur le même fichier déjà en cache — il doit retrouver la keyframe la plus proche et redécoder depuis là, ce qui peut geler l'image une fraction de seconde. Ne jamais coder cette hypothèse en dur pour justifier de sauter un préchargement (piège rencontré dans le double-lecteur crossfade du pré-montage, `_basketPreloadNextSegment`/`js/selects.js` : « même clip que l'actif → pas besoin de swap, le seek suffit » était faux). Corollaire pour tout swap entre deux éléments `<video>` : `readyState>=2` (HAVE_CURRENT_DATA) garantit juste l'image du point de seek, pas la capacité à enchaîner sans re-bufferiser — exiger `readyState>=3` + une vraie marge dans `buffered()` avant de considérer un élément "prêt" (v0.3.65, retour terrain « la transition entre deux sélections freeze »).
32. **Un re-rendu déclenché EN PLEIN MILIEU d'un geste (mousedown/drag) peut détruire la référence DOM que ce geste tient encore en main.** `_basketRenderSeqTimeline()` (pré-montage) détruit et recrée toutes les poignées de trim à chaque appel ; committer un trim armé au clavier depuis le `mousedown` d'une AUTRE poignée déclenche ce re-rendu, rendant la poignée qu'on vient de presser détachée du document (`getBoundingClientRect()` y renvoie des zéros → tout élément positionné dessus, ex. un HUD flottant, atterrit en haut à gauche de l'écran). Le fix générique n'est pas de "réparer" la référence après coup mais de **s'arrêter net** après un flush qui a effectivement déclenché un rendu : traiter le clic comme une simple validation, pas comme le début d'un nouveau geste — un second clic engage la nouvelle poignée sur un DOM frais (v0.3.66, `js/selects.js`).
33. **Corriger un seek qui gèle en préchargeant systématiquement — y compris quand c'est LE MÊME fichier déjà en cours de décodage ailleurs — peut être pire que le mal.** Piège #31 avait raison sur le diagnostic (un seek à vif n'est pas instantané) mais le remède choisi (`_basketPreloadNextSegment` préchargeant même les segments du clip déjà actif) créait un cycle de rechargements complets à chaque transition sur une série de sélections du même rush — le cas le plus courant du pré-montage. Résultat mesuré sur la build Electron packagée : flash noir à **chaque** transition (le rechargement n'avait jamais le temps de finir) puis **crash du renderer** après une ou deux lectures complètes (épuisement des décodeurs vidéo ouverts/fermés en boucle). Le fix suffisant était déjà en place et n'avait pas besoin de préchargement : le chemin de repli pause→seek→attend `seeked`→reprend de `_basketGoto`, appliqué à l'élément DÉJÀ chargé, sans jamais recharger de fichier. Leçon : avant de préchager "pour être sûr", vérifier si la cible du préchargement est déjà disponible ailleurs sous une forme utilisable — dupliquer un décodeur d'un fichier déjà ouvert n'est presque jamais la bonne réponse à un problème de fluidité (v0.3.65 corrigé le jour même, `js/selects.js`, retour terrain sur build packagée).
34. **Un contenu binaire potentiellement volumineux ne doit JAMAIS rejoindre le JSON projet synchronisé** (`notes`/`baskets`/etc.), même si c'est le chemin le plus simple à coder — `sync_project()` re-sérialise et repousse l'INTÉGRALITÉ du projet fusionné à chaque push (debounced 3s après chaque save), donc tout ce qui vit dans ce dict est retransmis en boucle, y compris quand ce contenu précis n'a pas changé. La LUT partagée (§ LUT partagée) illustre le bon réflexe : les métadonnées légères (hash + réglages) voyagent dans le JSON projet comme `baskets`, mais le contenu réel du `.cube` (plusieurs Mo possibles) est adressé par hash et stocké/synchronisé sur un canal totalement séparé (`LUTS_DIR` local + `derush_sync.php?action=lut_get/lut_upload` dédié), jamais embarqué dans `proj[...]`. Réflexe à appliquer à toute future feature qui voudrait partager un fichier/asset entre collaborateurs (sept. 2026).
35. **`ffprobe -show_entries stream=champ1,champ2,...` NE renvoie PAS `streams[i].tags` du tout**, même si le code appelant s'attend à pouvoir y lire un tag (ex. `s.get('tags', {}).get('timecode')`) — il faut explicitement ajouter une clause séparée `stream_tags=<nom_du_tag>` (ou `stream_tags` seul pour tout récupérer) à la chaîne `-show_entries`. Bug réel : `ffprobe_metadata()` ne demandait que `format_tags` + une liste de champs stream techniques (width/height/codec/…), jamais `stream_tags` — le fallback "TC au niveau stream" de `scan_media_folder()` (nécessaire pour GoPro, qui n'écrit JAMAIS son TC au niveau `format`, seulement sur chaque piste vidéo/audio/tmcd) tombait donc systématiquement sur un dict vide, silencieusement, et `tc_in` restait `""` pour toute caméra dans ce cas — pas seulement GoPro, n'importe quelle caméra sans `format.tags.timecode`. Conséquence concrète en aval : `export_fcpxml` pose `<asset start="0s">` au lieu de la vraie TC source → DaVinci refuse l'import avec "Mismatch between specified target timecodes [00:00:00:00 ...] and located file timecodes [17:13:59:15 ...]" (TC réellement embarquée dans le fichier, lue correctement PAR DAVINCI LUI-MÊME — la preuve que la donnée existe bel et bien dans le fichier, juste jamais lue côté Derush). Fix + détail dans § Détection TC ci-dessus (sept. 2026, retour terrain avec le message d'erreur DaVinci complet). **Après ce fix, les clips déjà scannés AVANT le patch gardent leur `tc_in` vide en cache — un rescan (🔄) est nécessaire pour les corriger rétroactivement.**
36. **`clip['path']` (chemin absolu) est figé au moment du SCAN — changer le `root_path` (lettre de lecteur, disque remonté ailleurs) ne le met PAS à jour tout seul.** Le streaming/les vignettes/waveforms étaient déjà résilients à ce cas (résolution dynamique via `_resolve_relpath_tolerant` contre le `root_path` courant, à chaque requête) — mais les exports FCPXML/XML Premiere (`export_fcpxml` et les 5 autres qui embarquent des chemins) lisaient `clip['path']` tel quel, sans repasser par cette résolution. Retour terrain réel : « j'ai mis à jour le dossier drift_club [...] remplaçant le chemin vers le disque E par le disque F [...] pourtant quand j'exporte le FCPXML [...] il prend les rush sur le disque E au lieu du disque F » — changer le chemin local des rushs (`set_root_path`) sans re-scanner laissait les exports pointer vers l'ancien disque, alors que la lecture dans l'app elle-même fonctionnait déjà correctement (d'où la confusion : "j'ai bien mis à jour le chemin, pourquoi l'export ignore ça ?"). Fix : `_proj_with_resolved_export_paths()` (sept. 2026) réévalue `clip['path']` juste avant l'export, exactement comme le fait déjà la génération de vignettes — même mécanisme, appliqué là où il manquait. Une leçon plus générale : **un mécanisme de résolution tolérante ajouté à UN SEUL endpoint ne protège que cet endpoint** — vérifier systématiquement si d'autres lecteurs du même champ figé (ici `clip['path']`) ont besoin de la même protection plutôt que de supposer qu'un fix "central" couvre tout le code qui touche à cette donnée. **2e passe (sept. 2026, v0.3.84)** : le 1er fix ne suffisait pas quand **l'ancien disque est toujours branché**. `_resolve_clip_src_path` faisait `if Path(clip['path']).exists(): return` en premier — donc tant que E: contient encore une copie, l'export garde E: quel que soit le `root_path` que l'utilisateur a pointé. Corrigé en inversant la priorité : le `root_path` explicite de l'utilisateur qui exporte (passé en query param `?root=` par le front — l'export part en `window.location` donc SANS header `Authorization`, la session est introuvable côté serveur) est essayé AVANT le chemin littéral figé. Leçon : un `root_path` configuré par l'utilisateur est une **déclaration d'intention** ("les rushs sont ICI maintenant") qui doit primer sur un chemin de scan qui se trouve encore valide par accident.
37. **Avant de conclure qu'un mécanisme externe (ici : la reconnaissance d'asset de DaVinci) est intrinsèquement imprévisible, épuiser les facteurs confondants qu'on contrôle soi-même — et utiliser TOUS les outils d'investigation disponibles, pas seulement le raisonnement depuis l'extérieur.** Saga TC LTC des FS5 dans l'export (`_clip_asset_tc_sec`, `derush_exports.py` + décodeur `_ltc_decode_pcm`, `derush_server.py`), en 3 temps :
    1. **v0.3.85 → 0.3.86** : LTC embarqué sans Media Pool corrigé en parallèle → rejet massif → revert (TC brut partout).
    2. **v0.3.87 → 0.3.88** : LTC ré-embarqué avec Media Pool corrigé → une partie des FS5 quand même hors ligne, périmètre en apparence dispersé/imprévisible → conclusion hâtive « le mécanisme interne de DaVinci est trop opaque, abandon définitif ». **Prématuré** : en creusant `davinci_resolve.log` (`%APPDATA%\Blackmagic Design\DaVinci Resolve\Support\Logs\`, accessible directement sur disque sans permission spéciale — Claude tourne déjà en local), un clip **GoPro** jamais concerné par le LTC échouait à l'identique → Media Pool **incomplet** (médias de certains jours jamais importés), pas une question de précision. Restauré en v0.3.89.
    3. **v0.3.90 — résolution** : Media Pool complété + testé proprement, 23 clips FS5 encore hors ligne sur 228. Plutôt que deviner depuis l'extérieur, connexion directe à l'**API de scripting DaVinci** (`DaVinciResolveScript`, module Python bundlé avec Resolve — `RESOLVE_SCRIPT_API`/`RESOLVE_SCRIPT_LIB`/`PYTHONPATH`, voir § API Resolve) pendant que le projet était ouvert : liste exhaustive des items timeline sans `GetMediaPoolItem()` lié (= offline), croisée avec le FCPXML importé (pour lever l'ambiguïté des noms de fichiers répétés sur plusieurs jours) et avec le Start TC réel de chaque clip dans le Media Pool. Résultat : **22 des 23 clips montraient un écart IDENTIQUE d'exactement +1 frame**, toujours dans le même sens — un bug systématique et déterministe dans `_ltc_decode_pcm`, pas un problème de matching DaVinci. Corrigé par calibration (`-frame_period` sur la valeur retournée). Le seul vrai outlier (+118 frames) était un échec du décodage LTC de Resolve lui-même sur CE clip précis (retombé sur le TC brut), cas distinct et sans rapport.

    **Leçons** : (a) un log applicatif tiers accessible sur disque peut trancher en minutes ce que des heures de déduction (calculs de frames, comparaisons manuelles clip par clip, hypothèses sur des motifs jour/caméra/canal) ne résolvaient pas — chercher les logs de l'appli concernée est un réflexe à avoir tôt, pas en dernier recours. (b) Une API de scripting officielle de l'appli tierce (ici Resolve) permet d'obtenir des données exactes et exhaustives (tous les clips, tous les TC réels) là où on ne pouvait avant que demander à l'utilisateur de copier 2-3 valeurs à la main — un changement d'échelle qui a permis de voir un pattern invisible sur un petit échantillon. (c) Un écart mesuré comme "aléatoire"/"imprévisible" sur 2-3 exemples peut se révéler parfaitement déterministe une fois mesuré sur un échantillon assez large — ne jamais généraliser une conclusion de non-fiabilité depuis 2 points de données. Voir aussi piège #35 pour le cas orthogonal où `tc_in` est carrément vide (`start="0s"`).

## Historique détaillé

Le détail chronologique des sagas de debug, incidents et livraisons de features (versions 0.2.0 → 0.3.46 et au-delà) est archivé dans **`HISTORY.md`**. Le consulter pour :
- comprendre *pourquoi* une décision de design a été prise (ex. panier personnel vs partagé, pas de tombstone pour les commentaires de review) ;
- retrouver le détail d'une reproduction de bug déjà résolue avant d'en enquêter une nouvelle qui y ressemble ;
- le contexte complet d'une version précise (numéros `v0.3.x`).

Les pièges listés ci-dessus sont un résumé condensé des leçons de `HISTORY.md` qui restent applicables au code actuel — ne pas dupliquer une nouvelle entrée ici sans la condenser en une règle générale.
