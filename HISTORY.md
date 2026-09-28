# DERUSH TOOL — Historique de développement (journal technique Claude)

> Ce fichier contient le détail chronologique des sagas de debug, incidents et features livrées, extrait de `CLAUDE.md` le 2026-08-01 pour garder ce dernier sous la limite de taille. `CLAUDE.md` reste la référence technique courante (architecture, endpoints, fonctions, pièges encore valides aujourd'hui) ; ce fichier est l'archive narrative — utile pour retrouver *pourquoi* une décision a été prise ou le détail d'une reproduction de bug, mais pas nécessaire à charger pour du développement courant. Nouvelles entrées datées : continuer à les ajouter ici plutôt que dans `CLAUDE.md`.

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

# État au 31 juillet 2026 (suite) — v0.3.46 : Son ingé (BWF) en 404 après changement de lettre de lecteur

## Signalement
Erreurs console : `GET /api/project/drift_club/bwf_audio/MIROIRT01` (et `MIROIRT02`, `REC_B_003`) → 404. « Le son ingé ne se lit plus quand je le sélectionne, alors que le chemin d'accès est celui-ci : `E:\DRIFT_CLUB\J01_2026_04_07\SON\26Y04M07\MIROIRT01.WAV` » (fichier confirmé présent sur disque à cet endroit). Accompagné d'un `401` sur `/api/me`.

## Le 401 : pas un bug
`SESSIONS` est un dict en mémoire, vidé à chaque redémarrage du serveur. Après les rebuilds/relances successifs de cette session, l'ancien token en `localStorage` du navigateur n'était plus reconnu → `init()` (`derush_app.html`) détecte le 401, nettoie le storage et redirige vers l'écran de connexion — comportement normal, aucun correctif nécessaire.

## Le 404 : même classe de bug que l'incident "v0.3.11" (clips vidéo), jamais corrigée côté BWF
`_resolve_audio_clip_path(ac, proj)` (`derush_server.py`) ne gérait qu'un match **littéral** : le chemin stocké (`ac['path']`, absolu, capturé tel quel par `scan_son_dir` au moment du scan initial du dossier Son) devait commencer par une des racines connues (`proj['root_path']` ou un `user['root_path']`) pour en déduire un chemin relatif à réappliquer sur le disque courant. Si le disque de rushs a changé de lettre depuis ce scan (`D:` → `E:`, exactement le scénario déjà documenté pour les clips vidéo), le chemin stocké (`D:\DRIFT_CLUB\...`) ne matche plus AUCUNE racine connue (toutes en `E:\...` désormais) → résolution abandonnée → 404, alors que le fichier existe à l'identique sous la nouvelle lettre.

**Pourquoi les clips vidéo n'ont jamais ce problème** : `_resolve_relpath_tolerant()` prend un chemin déjà **relatif** (`clip['rel_path']`, stocké séparément dès le scan), jamais un absolu à décomposer — la question de la lettre de lecteur ne se pose donc pas pour eux. Les `audio_clips`, eux, n'ont jamais stocké de `rel_path` du tout, seulement le chemin absolu complet.

## Fix
`_resolve_audio_clip_path()` étendu avec un repli : si le match littéral échoue, recherche le **nom du dossier racine du projet** (dernier segment de `root_path`, ex. `DRIFT_CLUB`) n'importe où dans les segments du chemin stocké — peu importe ce qui précède (lettre de lecteur, structure de disque totalement différente). Tout ce qui suit ce segment devient le chemin relatif, résolu ensuite via `_resolve_relpath_tolerant()` (même fonction que pour les clips — offre gratuitement la tolérance au zero-padding en prime).

## Vérification en conditions réelles

**Attention à ne pas toucher l'instance live de l'utilisateur** : au moment du diagnostic, une vraie session `DerushTool.exe` de l'utilisateur tournait déjà sur le port 8765 (confirmé via `Get-Process` sur le PID qui écoutait ce port avant de lancer quoi que ce soit) — le harness de test a été démarré sur le **port 8766** (`ds.PORT = 8766` avant `ds.run()`) pour ne jamais risquer d'interférer avec elle.

1. **Premier test en isolation, trompeur** : `root_path` de test fixé directement à `D:\DRIFT_CLUB` (la même lettre que le chemin stocké) — passait, mais n'exerçait que le match littéral déjà existant, pas le nouveau repli. Corrigé en nommant le dossier de test racine `DRIFT_CLUB` mais sous un chemin totalement différent de celui stocké (ex. `...\scratch\...\DRIFT_CLUB`) — seul moyen de vraiment exercer la recherche par nom de dossier plutôt que par préfixe littéral.
2. **Vraie requête HTTP** (pas juste la fonction en isolation) : projet jetable avec un `audio_clip` au chemin stocké pointant vers un `D:` inexistant, fichier réel placé sous la structure relative attendue au nouveau `root_path`. Avant fix : `GET /bwf_audio/MIROIRT01` → 404. Après fix : → 200, `Content-Type: audio/wav`.

## Portée non couverte
Seul `_resolve_audio_clip_path()` (utilisé par `/bwf_audio/<id>` et indirectement par `/clip_bwf/<clip_id>`) a été corrigé. Si d'autres endpoints résolvent un jour des chemins BWF absolus par une autre voie, appliquer le même repli.

# État au 20 août 2026 — v0.3.58 : marqueur presque invisible quand 2 marqueurs sont très proches

## Signalement
« quand deux marqueurs sont très proches sur la timeline, le logiciel en place un au-dessus et un en-dessous de la timeline. Je vois à peine celui en-dessous. » Le mécanisme anti-chevauchement (empilement vertical sur 3 niveaux, cf. section « Markers : shapes différenciées + stacking vertical » plus haut dans ce fichier) existait déjà et était censé toujours pousser les marqueurs proches **au-dessus** de la piste, jamais en-dessous.

## Reproduction hors app (sans logiciel de test navigateur connecté)
Pas d'extension Chrome disponible dans cette session pour piloter un vrai navigateur sur l'app. Plutôt que de retoucher le CSS à l'aveugle sur un pur bug de géométrie (cf. mémoire persistante `measure-before-guessing-layout`), reproduction dans une page HTML autonome (`tests/_repro_markers.html`, jetable) qui rejoue **exactement** le bloc CSS (`.timeline-bar`, `.timeline-track`, `.timeline-marker-pin` + `::before` pour le "stem") et l'algorithme JS de `renderMarkers()` (calcul du stack level + `--pin-top`/`--pin-stem`) copiés tels quels depuis `derush_app.html`, avec 3 cas : marqueurs éloignés (pas de stacking), 2 marqueurs à 0.3s d'écart (stack 0/1), 3 marqueurs à 0.2s d'écart (stack 0/1/2). Capture via un script Playwright `page.screenshot()` (le module `@playwright/test` déjà installé dans `tests/node_modules` pour les tests E2E, lancé directement en `node` hors du runner de test).

## Cause : mauvais référentiel pour `--pin-top`
Les pins sont ajoutés comme enfants de `#timelineTrack` (`track.appendChild(pin)`), qui est `.timeline-track` : une mini-piste de seulement **4px de haut**, positionnée `bottom:14px` à l'intérieur de la barre de 88px (`.timeline-bar`). `position:absolute` sur le pin le place donc relativement au **haut de cette mini-piste** (proche du bas de la barre), pas au haut de la barre entière. Le calcul original (`pinTop = 4 + stack*13`, valeurs positives 4/17/30px) avait été écrit en supposant implicitement l'inverse — un commentaire de code calculait même une `trackTopY = 88 - 14 - 4 = 70` comme si `--pin-top` était mesuré depuis le haut de la barre, alors qu'il ne l'a jamais été.

Résultat visuel confirmé par la capture Playwright (avant fix) : avec 2 marqueurs proches, le premier (stack 0, `top:4px`) atterrit à cheval sur la piste (son propre haut dépasse à peine au-dessus de la piste, l'essentiel du pin la recouvre) — perçu comme « au-dessus » par l'utilisateur. Le second (stack 1, `top:17px`) est poussé 17px **sous le haut de la mini-piste**, donc en réalité sous la piste et proche du bord inférieur de la barre de 88px (voire au-delà) — exactement le marqueur « à peine visible en-dessous » signalé.

## Fix
`derush_app.html`, dans `renderMarkers()` (bloc de rendu du pin timeline) : le `gap` (4 + stack×13, inchangé) sert désormais de distance entre le **haut de la piste** et le **bas du pin**, avec `--pin-top` rendu **négatif** (`-(gap + 12)`, 12 = hauteur du pin) pour empiler réellement vers le haut ; `--pin-stem` = `gap` directement (plus besoin de la constante `trackTopY`, qui n'avait jamais le bon sens).

## Vérification
Même harnais de repro, après fix : capture Playwright confirme que les 2 (puis 3) marqueurs proches restent tous nettement visibles **au-dessus** de la piste, avec un fil de rattachement (stem) de longueur croissante vers le marqueur le plus empilé — plus aucun pin ne descend sous la piste. Fichiers de repro jetables (`tests/_repro_markers.html`, `tests/_screenshot_repro.js`, `tests/_repro_markers.png`) supprimés après vérification, aucun test E2E permanent ajouté pour ce fix ponctuel de géométrie CSS.

# État au 21 août 2026 — v0.3.59 : « Voir le groupe » repartait du début du clip au lieu de suivre la position du lecteur principal

## Signalement
« quand je suis un clip contenu dans un groupe et que je clique sur voir le groupe, j'aimerais arriver au même endroit que là où j'étais dans la vision du clip seul. Car à chaque fois que je clique sur voir le groupe, il me met au début du clip. »

## Cause : même bug que le comparateur (v0.3.13, « Bug 1 »), jamais corrigé côté viewer multicam
`openMcViewer()` (`js/multicam-viewer.js`) sélectionne bien l'angle du clip actif comme primary, mais `_buildMcLayout(isInitial)` calcule la position de départ à partir de `_mcGroupResumeTime[group.id]` en priorité — une map dédiée à la reprise de position **interne au viewer multicam** (posée par `closeMcViewer()` à sa dernière fermeture, feature v0.3.12), pas à la position courante du lecteur principal. Rejouer un groupe une fois, le fermer, puis continuer à naviguer/lire le clip seul avant de rouvrir "Voir le groupe" laisse `_mcGroupResumeTime` sur une valeur périmée — l'utilisateur atterrit sur l'ancienne position du viewer (souvent proche de 0 si jamais ouvert cette session) au lieu de celle du lecteur principal qu'il vient de quitter.

C'est exactement le même bug déjà rencontré et corrigé sur le comparateur : `openCompare()` écrasait déjà `_clipResumeTime[activeClip.id]` avec `mainPlayer.currentTime` juste avant de charger le slot 0, précisément pour cette raison (« le comparateur reflète alors toujours l'instant courant du lecteur principal à l'ouverture, la reprise historique restant valable seulement pour les changements de clip pendant qu'on est dans le comparateur »). Le viewer multicam n'avait jamais reçu le même traitement.

## Fix
`openMcViewer()` : juste avant `_buildMcLayout(true)`, écrase explicitement `_mcGroupResumeTime[g.id]` avec `mainPlayer.currentTime + normOff` de l'angle primary (conversion position-clip → position-groupe, même formule que `_mcSeekGroup`/`_mcCurrentGroupTime`). `_buildMcLayout()` lui-même n'a pas changé — sa logique de lecture de `_mcGroupResumeTime` reste correcte et continue de servir pour la navigation interne au viewer (bascule grille/primaire). Seule la fraîcheur de la valeur au moment de l'ouverture depuis un clip était en cause.

# État au 1 septembre 2026 — v0.3.61 : restauration Windows → annotations perdues, sync qui propage la régression

## Signalement
« J'ai dû faire un recovery de Windows le 1er septembre à 12h05, j'ai relancé Derush Tool et j'ai perdu toutes les annotations que j'avais faites. Je croyais qu'elles étaient sauvées en ligne. »

## Diagnostic (forensique)
- Une restauration système Windows (point « Avant Optimisation-Boot », ~11:14 heure locale, appliquée à 12:05) a ramené le fichier projet local `projects/drift_club.derush.json` à son état du **31 août 18:48**. Confirmé via une Volume Shadow Copy post-restauration lisible proprement (`modified: 2026-08-31T18:48:42`, notes Sébastien 525 marqueurs / 248 ratings / 200 textes / 668 tags).
- Les Shadow Copies **d'avant** la restauration (10:35, 10:38, 11:14 heure locale) existaient mais leurs blocs de données pour ce fichier étaient inexploitables : `save_project` fait une réécriture atomique complète (`.tmp` + `os.replace`) à chaque sauvegarde → VSS ne conservait pas les clusters, on y lisait des zéros et même un en-tête `MZ` d'un exécutable ayant réutilisé les clusters. Piste morte.
- Au redémarrage, le sync a **propagé la perte jusqu'au cloud** : `merge_projects(local, remote, own_uid)` repart de `remote.notes` puis fait `merged_notes[own_uid] = local_notes[own_uid]`. Le local rétrogradé a donc écrasé les notes cloud de Sébastien, et le push suivant l'a gravé côté serveur. Notes de Paola intactes (écrites par sa machine, jamais réimposées par celle de Sébastien).
- Diff : Sébastien avait perdu ~un lot de plans **J04 (10 avril) FS5 Clip0009–0021** annotés le matin du 1er sept (ratings, notes, marqueurs, tags `axeldanse`/`plandecoupe`/…). Seul Clip0009 avait une modif locale plus récente (note retapée à la main après la perte, inachevée).

## Récupération
Les sauvegardes horodatées côté hébergement PHP (`derush_data/backups/drift_club/`) tenaient encore **6 versions** du matin même (horodatage serveur UTC = ~2h avant l'heure locale belge, donc pushs de ~11:35 à ~11:42 locale, ~20 min avant la restauration). Récupérées par FTP. La plus récente (`drift_club_20260901094306.json`, Sébastien 537/259/209/677) a servi de source : ses `notes['6714b070']` réinjectées dans le projet live courant, Clip0009 conservant les deux versions de note séparées par `---`, Paola / discussions / clips / paniers inchangés. Sauvegarde de l'état d'avant l'opération : `projects/_recovery_20260901/live_BEFORE_restore.json`.

**C'était limite** : les backups (serveur ET local) ne gardaient que les 10 derniers. Une session de travail suffit à tous les faire tourner ; quelques sync post-incident de plus et la dernière piste disparaissait.

## Correctif (v0.3.61)
Deux niveaux de rétention distincts, **implémentés à l'identique** dans `derush_server.py` (`save_project`) et `derush_sync.php` (bloc POST) + `derush_sync.example.php` :
- **Rolling** : copies `<pid>_AAAAMMJJ_HHMMSS.json` à chaque sauvegarde, plafond 10 → **40** (`BACKUP_KEEP_ROLLING` / `$BACKUP_KEEP_ROLLING`).
- **Quotidiennes** : à la 1re sauvegarde de chaque jour calendaire, une copie `<pid>_daily_AAAAMMJJ.json` figée, **jamais purgée par le cycle rolling**, conservée **90 jours** (`BACKUP_KEEP_DAILY` / `$BACKUP_KEEP_DAILY`).

Purges par globs séparés : le rolling exclut explicitement `_daily_` du décompte, les quotidiennes sont purgées à part. Seuils réglables via `derush_config.json` (`backup_keep_rolling` / `backup_keep_daily`) côté serveur, variables en tête de fichier côté PHP. **Le côté cloud ne prend effet qu'après ré-upload de `derush_sync.php` sur l'hébergement.** Test unitaire de la logic Python : 5 jours × 60 saves/jour → 40 rolling (les plus récents) + 5 quotidiennes conservés, aucune quotidienne emportée par le flot.

## Leçon (condensée dans `CLAUDE.md` piège #30)
Le sync est une réconciliation last-writer-wins par utilisateur, pas un historique : il propage aussi bien les ajouts que les régressions. Les sauvegardes sont le vrai filet. En récupération après un rollback/restauration : ne pas relancer l'app avant d'avoir récupéré `derush_data/backups/<pid>/` par FTP (chaque démarrage peut re-pusher et faire tourner les backups serveur).

# État au 9 septembre 2026 — v0.3.65 : gel vidéo entre deux sélections du pré-montage

## Signalement
« Dans prémontage la transition entre deux sélections n'est pas très fluide, parfois ça freeze un peu la vidéo qui vient. »

## Diagnostic
Le double-lecteur crossfade de `js/selects.js` (v0.3.42, voir plus haut) reposait sur une hypothèse fausse dans `_basketPreloadNextSegment()` : « si le prochain segment est sur le MÊME clip que celui en cours de lecture, un swap de source est inutile — le seek direct dans `_basketGoto` suffit et est déjà instantané ». Ce n'est vrai que pour un fichier entièrement décodé/en cache. Sur un flux H.264/H.265 long-GOP **en cours de lecture**, un seek vers un point quelconque doit retrouver la keyframe la plus proche puis redécoder jusqu'à la cible — ce qui gèle visiblement l'image une fraction de seconde, surtout sur un proxy volumineux ou un disque/réseau lent. Le pré-montage contient très souvent plusieurs sélections découpées dans le **même** rush (plusieurs bons moments sur un même plan long) — c'était donc le cas le plus fréquent qui ne bénéficiait d'aucun préchargement.

Deuxième faiblesse, plus fine : le "chemin rapide" de `_basketGoto()` acceptait un lecteur inactif dès `readyState >= 2` (`HAVE_CURRENT_DATA` — l'image du point de seek est là, mais rien ne garantit de pouvoir continuer à jouer sans re-bufferiser aussitôt). Un swap pouvait donc se déclencher vers un segment "préchargé" mais pas réellement prêt à jouer en continu, déplaçant le gel juste après la bascule au lieu de l'éviter.

## Fix (premier jet)
- `_basketPreloadNextSegment()` préchargeait **systématiquement** le segment suivant dans le lecteur inactif, même quand c'est le même fichier source que l'actif — identité de préchargement suivie par clip **et** par sélection (`dataset.selectId` en plus de `dataset.clipId`, car un même clip peut apparaître plusieurs fois dans le pré-montage avec des in/out différents). **Revu quelques heures plus tard, voir addendum ci-dessous — ce point précis s'est révélé être une régression, pas un fix.**
- Nouvelle garde `_basketSegmentReady(video, atTime)` : exige `readyState >= 3` (`HAVE_FUTURE_DATA`) **et** une vraie marge tampon (`buffered`) autour du point de reprise, remplace le `readyState >= 2` trop permissif du chemin rapide de `_basketGoto()`.
- Chemin de repli (préchargement pas encore prêt — segment précédent trop court) revu : au lieu de seeker à vif sur l'élément qui joue, on `pause()`, on seek, puis on attend l'évènement `seeked` avant de relancer la lecture — évite un sursaut de frames pendant que le navigateur retrouve la keyframe. Filet de sécurité (`setTimeout` 700ms) au cas où `currentTime` vaudrait déjà la cible et où `seeked` ne se déclencherait jamais (seek no-op, dépend du navigateur).
- Ce chemin de repli "attend `seeked`" est **désactivé** pendant un scrub actif sur la timeline de séquence (nouveau paramètre `scrubbing` de `_basketGoto`, utilisé par `_basketSeekSeqRatio` pendant le `mousemove` du drag) — sinon la réactivité du glisser en aurait pâti (des dizaines d'appels/s, chacun attendant potentiellement 700ms). Le scrub garde le seek instantané d'origine.

## Non couvert (constaté à l'époque)
Si le segment précédent est trop court pour laisser le temps au préchargement de se terminer (quelques centaines de ms), le chemin de repli reste utilisé et un léger gel résiduel reste possible — inhérent à toute lecture bout-à-bout de segments très courts sans buffer d'avance illimité.

## Addendum même jour : régression découverte sur la build Electron packagée → crash

### Signalement
« La build electron a crashé lorsque j'ai lu les clips dans prémontage, notamment au niveau des transitions. J'ai constaté qu'il y avait comme un noir entre chaque clip alors que je veux une transition fluide entre deux clips (comme DaVinci). Après deux lectures, il a crashé. »

### Diagnostic
Le préchargement "systématique même sur le même clip" (premier jet ci-dessus) semblait correct pour UNE transition isolée entre deux sélections du même rush, mais le pré-montage contient très souvent une SUITE de plusieurs sélections découpées dans le **même** long rush (le cas le plus courant, pas l'exception) — exactement le scénario testé par l'utilisateur. Pour chaque transition dans cette suite, `_basketPreloadNextSegment()` déclenchait un rechargement **complet** (nouveau décodeur, éventuellement un nouveau fetch réseau) d'un fichier qui était déjà, à ce moment précis, en train d'être décodé dans l'AUTRE élément `<video>` — juste pour y rebasculer l'instant d'après. Ce rechargement n'avait quasiment jamais le temps de finir avant la transition suivante → `_basketSegmentReady` refusait le swap rapide à chaque fois → chemin de repli déclenché en boucle → flash noir à **chaque** transition (pas seulement occasionnellement). Répété sur toute une lecture bout-à-bout, ce cycle d'ouverture/fermeture de décodeurs vidéo sur le même fichier a fini par épuiser les ressources du renderer Electron → crash après une ou deux lectures complètes.

### Fix définitif
`_basketPreloadNextSegment()` **s'abstient désormais explicitement** de précharger quand le segment suivant est sur le MÊME clip que celui actuellement dans l'élément **actif** (`if(next.clip.id === active.dataset.clipId) return;` — littéralement le garde-fou d'origine d'avant ce fix, réintroduit). Le "chemin de repli" pause→seek→attend `seeked`→reprend de `_basketGoto` (ajouté dans le fix ci-dessus et resté inchangé) suffit à lui seul à rendre cette transition fluide, PARCE QU'IL RÉUTILISE L'ÉLÉMENT DÉJÀ CHARGÉ au lieu d'en recréer un — aucun rechargement, donc aucun flash noir, et aucune pression sur les décodeurs. Le préchargement dans le lecteur inactif reste utilisé, inchangé, pour les transitions vers un clip **différent** (le cas d'usage d'origine du double-lecteur crossfade, v0.3.42, qui fonctionnait déjà bien).

### Leçon (condensée dans `CLAUDE.md` piège #33)
Corriger un problème de fluidité en préchargeant "pour être sûr" — y compris quand la cible est déjà ouverte ailleurs sous une forme réutilisable — peut être pire que le problème d'origine. Le bon réflexe était déjà présent dans le même correctif (le chemin de repli gentil) ; il n'y avait pas besoin du préchargement redondant en plus.

# État au 9 septembre 2026 — v0.3.66 : précision de trim façon DaVinci dans le pré-montage

## Signalement
« Je trouve l'outil de pré-montage très pratique à utiliser, notamment quand on veut raccourcir ou étendre un clip. [Mais] on perd vite l'endroit précis où l'on voulait atterrir. Pourrais-tu t'inspirer fortement de DaVinci Resolve pour faire en sorte qu'il soit très pratique de faire un mini montage dans cette section ? »

## Diagnostic
Glisser une poignée `.bseq-handle-in`/`-out` sur la timeline de séquence du pré-montage (`_wireBasketSeqHandle`, `js/selects.js`) produisait un `sel.in`/`sel.out` en secondes flottantes arbitraires — résolution pixel de l'écran, pas résolution frame. Aucun repère visuel du point exact visé pendant le geste (pas de TC affiché, pas de delta par rapport au point de départ) : impossible de savoir, en glissant, si on venait de dépasser ou pas le point voulu, ni de revenir dessus avec précision une fois raté. Aucune façon de corriger frame par frame après coup — seule option : recommencer le glisser à l'aveugle.

## Fix — trois briques inspirées de DaVinci Resolve
1. **Snap sur la grille de frames** (`_basketSnapClamp`) : le point trimmé est désormais TOUJOURS arrondi à la frame exacte la plus proche (`Math.round(t*fps)/fps`), que ce soit pendant un glisser souris ou un nudge clavier — élimine le flou sous-frame par construction.
2. **HUD flottant TC + delta pendant le geste** (`_basketShowTrimHud`/`_basketHideTrimHud`, `#basketTrimHud`) : bulle positionnée au-dessus de la poignée, affichant le timecode exact du point courant ET l'écart depuis le point de départ (`+1s04f`/`−12f`/`±0f`, coloré vert/rouge/gris) — visible en continu pendant tout le geste (glisser OU nudge clavier), directement pensé pour répondre à « on perd l'endroit précis où l'on voulait atterrir ».
3. **Trim armé au clavier** (`_basketArmedTrim`, `_basketArmTrimHandle`/`_basketNudgeArmedTrim`/`_basketCommitArmedTrim`/`_basketCancelArmedTrim`) : cliquer une poignée SANS glisser ne fait plus rien de spécial → l'« arme » pour un ajustement clavier frame-exact, exactement le geste de précision de référence dans DaVinci (sélectionner un point de montage, puis `←`/`→` pour le trimmer). `←`/`→` = 1 frame, `Maj+←`/`→` = 1 seconde, `Entrée` valide, `Échap` annule sans rien modifier. Comme le glisser, `sel.in`/`out` ne sont mutés qu'à la validation — un seul `pushUndo`/`saveNotes` par session de trim, pas un par frappe.
4. **Flèches à double rôle hors trim armé** : `←`/`→` (et `Maj+←`/`→`) nudgent maintenant la tête de lecture de la visionneuse pré-montage (1 frame / 1s), pour retrouver la frame exacte visée AVANT même de lancer un trim — mêmes conventions que le lecteur principal.

## Piège rencontré et corrigé en cours de route
Valider un trim armé au clavier reconstruit toute la timeline de séquence (`_basketRenderSeqTimeline` détruit/recrée chaque poignée). Committer ce trim depuis le `mousedown` d'une AUTRE poignée détruisait donc la poignée qu'on venait de presser dans le même geste — la référence DOM devenait détachée, un `getBoundingClientRect()` dessus renvoyant des zéros aurait affiché le HUD en haut à gauche de l'écran. Fix : `_wireBasketSeqHandle` flush un trim en attente puis `return` immédiatement plutôt que de continuer sur une référence potentiellement obsolète — un second clic engage la nouvelle poignée sur un DOM frais. Condensé en piège CLAUDE.md #32 (leçon générale : un re-rendu déclenché en plein milieu d'un geste peut invalider les références DOM que ce geste tient encore).

## Portée
Snap-frame, HUD et trim armé s'appliquent uniquement aux poignées de la **timeline de séquence du pré-montage** (`.bseq-handle`, `#basketSeqTimeline`) — pas aux poignées de sélection in/out du lecteur principal (`.tsr-handle`, `_wireSelectRangeHandle`), qui restent sur leur comportement existant (non demandé par le retour terrain, périmètre volontairement resserré sur le pré-montage).

# État au 9 septembre 2026 — v0.3.67 : repères de séquence + magnétisme dans le pré-montage

## Signalement
« Ça serait pas mal aussi de pouvoir mettre des petits marqueurs (comme dans DaVinci) qui ne sont pas les marqueurs que l'on mettait sur la vidéo avec des commentaires etc, juste des repères qui nous permettent de faire coulisser les poignées à cet endroit précis avec un peu de magnétisme. » — suite directe de la précision de trim v0.3.66.

## Design : où vivent les repères ?
Question centrale avant d'écrire du code : un repère est-il défini en temps CLIP-LOCAL (une frame précise d'un clip source donné) ou en temps SÉQUENCE (une position dans la bobine assemblée) ? DaVinci place ses marqueurs de timeline sur la SÉQUENCE, pas sur un clip — et c'est aussi la seule interprétation cohérente avec le fonctionnement réel de `_basketSeqSegments()` : chaque segment est positionné en cumulant les durées de TOUS les segments qui le précèdent (`acc += dur`, jamais l'inverse) — sa frontière avec le PRÉCÉDENT ne bouge donc JAMAIS quand on trimme ce segment lui-même, seule sa frontière avec le SUIVANT se déplace. Un repère en position-séquence est le seul modèle qui reste cohérent avec cette mécanique bout-à-bout.

Conséquence directe pour le calcul de magnétisme (voir plus bas) : peu importe la poignée tenue (in ou out), c'est TOUJOURS `seg.start + dur_live` — la frontière avec le segment suivant — qu'il faut comparer aux repères, jamais `seg.start` seul (invariant) ni une lecture naïve "poignée in = bord gauche qui bouge".

## Implémentation (`js/selects.js`)
- **Données** : `_basketSeqMarkers` (array de secondes-séquence, triées), persisté en `localStorage['derush_basket_seq_markers_' + pid]` — personnel, jamais dans `allNotes`/le projet partagé (ce n'est pas une annotation à faire remonter à l'équipe, juste un outil d'aide au montage). Chargé à `openBasket()`.
- **UI** : nouvelle lane `#basketSeqMarkers` (12px, au-dessus de `#basketSeqTimeline`, largeur resynchronisée à chaque zoom dans `_basketSeqWheel` pour rester alignée). Clic sur la lane = ajoute (`_basketMarkerLaneClick` → `_basketAddSeqMarkerAt`, désélectionne d'abord tout repère sélectionné). Bouton `Repère` (`#basketAddMarkerBtn`, `.basket-seq-toolbar` alignée à gauche, icône = même losange ambre que les repères sur la timeline via la classe partagée `.bseq-marker-diamond`) + touche `M` = ajoute à la position de lecture courante (`_basketAddSeqMarkerAtPlayhead`, même formule de position-séquence que `_basketUpdateSeqHead`).
- **Magnétisme** (`onMove` de `_wireBasketSeqHandle`, drag souris uniquement) : rayon d'accroche fixé en PIXELS ÉCRAN (10px), converti en secondes via `pxPerSec` du zoom courant — reste "collant" pareil quel que soit le niveau de zoom, comme le magnétisme DaVinci. `_basketNearestSeqMarker(pos, tol)` trouve le repère le plus proche sous le seuil ; si trouvé, la durée cible du segment est recalculée pour que `seg.start + dur === repère`, puis repassée dans `_basketSnapClamp` existant (donc re-alignée sur la grille de frames — l'accroche peut être à moins d'une frame pile du repère si celui-ci ne tombait pas sur une frame exacte). HUD : petit 🧲 ajouté au TC affiché quand l'accroche est active.
- **Volontairement PAS de magnétisme sur le trim clavier armé** (v0.3.66) : ce geste est déjà exact par construction (nudge frame par frame) ; superposer un magnétisme aurait juste réintroduit de l'imprévisibilité sur un geste déjà précis. Reste un moyen fiable de bypasser le magnétisme quand on veut viser à côté d'un repère.

## Itération immédiate : clic = suppression rejeté par le retour terrain
Premier jet : cliquer un repère le retirait directement (`_basketRemoveSeqMarker`). Retour terrain quasi immédiat : « je ne veux pas que ça s'efface, je veux que ça avance le clip à ce niveau-là et qu'on voit l'image dans la preview. Par contre si le marqueur est sélectionné (en cliquant dessus) et que j'appuie sur Suppr, je le supprime. » Revu :
- `_basketSelectedSeqMarker` (la VALEUR du repère sélectionné, pas un index — un index se périmerait au moindre ajout/retrait puisque le tableau est retrié à chaque insertion).
- Cliquer un repère → `_basketSelectSeqMarker(t)` : sélectionne (classe CSS `.selected`, anneau vert) **et** traduit la position-séquence en `{idx, offset}` (`_basketSeqTimeToSegmentOffset`, cherche le premier segment dont `t` tombe avant la fin, sinon le dernier) pour appeler `_basketGoto(idx, offset, false)` — la visionneuse affiche l'image exacte, en pause.
- `Suppr`/`Backspace` dans `_basketKeydown` (seulement si un repère est sélectionné) → `_basketDeleteSelectedSeqMarker()`.
- `Échap` : cascade — annule d'abord un trim clavier armé s'il y en a un, sinon désélectionne le repère (`_basketDeselectSeqMarker()`, retourne `false` si rien n'était sélectionné), sinon ferme l'overlay.
- Bouton `Repère` ajouté au passage (juste au-dessus de la timeline) — la touche `M` seule n'était pas assez découvrable pour un geste destiné à être posé souvent. Retour terrain suivant : aligné à **gauche** (pas à droite) et icône remplacée par le même losange ambre CSS que les repères sur la timeline (`.bseq-marker-diamond`, classe de base extraite et réutilisée par `.basket-seq-marker-pin`) plutôt que l'émoji 📍 initial — pour que le bouton affiche visuellement le symbole qu'il pose.

## Limite assumée
Un repère est un nombre figé en secondes-séquence — retrimmer fortement un segment plus tôt dans la bobine (ou réordonner) ne fait PAS "ripple" les repères qui suivent : leur position logique visée à la création peut ne plus correspondre au même instant après coup. Comportement standard de la plupart des NLE hors mode ripple-marker dédié (non demandé, hors scope).

# État au 9 septembre 2026 — v0.3.68 : dupliquer une sélection dans le pré-montage

## Signalement
« J'aimerais aussi que l'on puisse copier coller une sélection plusieurs fois dans le prémontage. »

## Design
Deux options envisagées : (a) un vrai copier/coller avec presse-papier — sélectionner une ligne (Ctrl+C), coller (Ctrl+V) à la position du curseur/de la ligne active, répétable ; (b) un bouton "dupliquer" par ligne — insère immédiatement une copie juste après, re-cliquable pour en ajouter d'autres. Choix : **(b)**, pour plusieurs raisons — le pré-montage n'a pas de concept de "ligne sélectionnée" indépendant du clic-pour-lire déjà en place (cliquer une ligne = `_basketPlayFrom`, pas une sélection au sens UI) ; en introduire un aurait demandé un nouvel état + une nouvelle affordance de clic (ex. Ctrl+clic) pour ne pas entrer en collision avec l'existant. Le glisser-déposer, lui, existe déjà et permet de replacer une copie n'importe où dans la bobine après duplication — donc "dupliquer ici puis glisser où on veut" couvre le même besoin que "copier puis coller ailleurs", en réutilisant une brique déjà là plutôt qu'en construisant un état de presse-papier séparé.

## Implémentation (`_basketDuplicateItem(idx)`, `js/selects.js`)
- Bouton `⧉` ajouté dans `.basket-item-actions` de chaque ligne (à côté de ▶ et 🗑), visible seulement `isMine` (cohérent avec le reste des contrôles d'édition du pré-montage).
- Crée une **sélection indépendante** dans `n.selects` (nouvel id aléatoire, mêmes `in`/`out`/`tags`/`desc` que la source, nom suffixé `" (copie)"`) — PAS une simple deuxième entrée `allBaskets` pointant vers le même `select_id`. Raison : la timeline de séquence du pré-montage (`_wireBasketSeqHandle`) mute `sel.in`/`sel.out` **en place** sur l'objet sélection partagé — si deux items du pré-montage pointaient vers le même `select_id`, retrimmer l'un aurait aussi silencieusement changé l'autre. Chaque copie doit rester ajustable indépendamment, comme dupliquer un clip sur une timeline DaVinci (qui référence le même média mais reste un point de montage distinct).
- Nouvel item `allBaskets[uid]` inséré à `realIdx + 1` (juste après l'original, pas en fin de liste) — facile à repérer visuellement pour le glisser ensuite si besoin.
- Deux poussées d'annulation distinctes sur `undoStack` : `pushUndo(clip.id)` pour la nouvelle entrée dans `allNotes[uid][clip.id].selects`, `_pushBasketUndo()` pour la nouvelle entrée dans `allBaskets[uid]` — même pattern déjà utilisé par `confirmSelect()` quand une sélection nouvellement créée est auto-ajoutée au pré-montage. Ctrl+Z peut donc demander deux appuis pour tout annuler d'un coup ; comportement existant, pas une régression introduite ici.
- `saveNotes(true)` + `saveBasket()` appelés l'un après l'autre pour persister les deux moitiés du changement côté serveur.

# État au 9 septembre 2026 — v0.3.69 : réordonner les clips directement sur la timeline de séquence

## Signalement
« Ça serait aussi bien de pouvoir, lorsqu'on clique gauche sur un clip dans la timeline, le déplacer sur celle-ci pour l'intercaler entre deux clips ou au début/fin de la séquence. Comme DaVinci. »

## Design
Le réordonnancement existait déjà (glisser une ligne de la LISTE, `_wireBasketDrag`), mais pas depuis la timeline de séquence elle-même — celle-ci ne servait qu'à naviguer (`_basketSeqMouseDown`, clic/glisser = scrub) et trimmer (`_wireBasketSeqHandle`, glisser un bord). Ajouter le réordonnancement DIRECT sur cette même timeline demandait de faire coexister trois interactions sur les mêmes éléments DOM sans qu'elles ne se marchent dessus :
- **Scrub** : mousedown n'importe où sur `#basketSeqTimeline` (ancêtre).
- **Trim** : mousedown sur une poignée (`.bseq-handle-in`/`-out`, enfant positionné aux bords, `stopPropagation`+`preventDefault`).
- **Réordonner** (nouveau) : glisser le CORPS d'un segment (`.basket-seq-seg`).

## Implémentation (`_wireBasketSeqSegDrag`, `_basketSeqReorder`, `js/selects.js`)
Choix : drag-and-drop **natif HTML5** (`draggable="true"` + `dragstart`/`dragover`/`drop`) sur le corps du segment, plutôt qu'un pattern mousedown/mousemove custom (celui déjà utilisé par les poignées de trim, qui a besoin d'aperçu live et de contrôle fin — pas nécessaire ici, un simple réordonnancement n'a besoin que d'un point de dépôt).
- **Coexistence avec les poignées** : `handleIn.draggable = handleOut.draggable = false` (override explicite de l'attribut `draggable` hérité du parent) + leur `mousedown` existant fait déjà `preventDefault()`/`stopPropagation()` — les deux couches empêchent le drag natif du segment parent de démarrer quand on saisit précisément une poignée.
- **Coexistence avec le scrub** : `_basketSeqMouseDown` reste attaché à l'ancêtre `#basketSeqTimeline`, non court-circuité — un clic sur un segment déclenche donc TOUJOURS le scrub existant (la tête de lecture saute au point cliqué) avant qu'un éventuel drag natif ne prenne la main sur les évènements mousemove suivants. Effet de bord accepté sciemment (pas invasif, plutôt cohérent : on voit où on a "attrapé" le clip) plutôt que de complexifier l'interaction pour le supprimer.
- **Insertion avant/après** : `dragover` compare `e.clientX` à la moitié de la largeur du segment cible (`rect.width/2`) et bascule les classes `.drop-before`/`.drop-after` (liseré vert CSS `box-shadow: inset`) en conséquence. `_basketSeqReorder(fromIdx, toIdx, before)` traduit ça en `splice` sur `allBaskets[uid]` — même sous-jacent que `_wireBasketDrag` (liste), logique d'index légèrement différente pour gérer le avant/après (`if(fromRealIdx < toRealIdx) toRealIdx--` après le retrait, puis insertion à `toRealIdx` ou `toRealIdx+1`) : vérifié à la main sur les 4 cas limites (déplacer vers l'avant/l'arrière, avant/après la cible, y compris tout au début ou toute la fin de la bobine) avant implémentation.
- `_pushBasketUndo()` avant la mutation, `saveBasket()` après — mêmes conventions que le reste des mutations `allBaskets`.

# État au 9 septembre 2026 — v0.3.70–0.3.73 : panneau LUT réductible, LUT dans le pré-montage, filtre "sélection faite", scrub sur la lane des repères

Quatre retours terrain traités dans la même session, chacun assez contenu pour ne pas mériter sa propre entrée détaillée séparée — condensés ici.

## v0.3.70 — Panneau de réglages LUT réductible
Signalement (premier jet) : « pouvoir la diminuer pour que ça ne prenne pas trop de place. » `#lutSettingsPanel` séparé en deux : l'en-tête (titre + boutons Reset/▾) reste toujours visible, les sliders passent dans `#lutSettingsBody` que `_lutTogglePanelCollapsed()` cache/montre.

**Corrigé dans la foulée (2e jet)** — retour terrain immédiat sur le premier jet : « je veux que Réglages LUT et Reset ne soit plus visible, juste un petit bout qui dépasse, comme les fenêtres de réglages de Photoshop. » Cacher seulement les sliders ne suffisait pas : le titre et Reset prenaient encore de la place. Restructuré une première fois : `#lutSettingsExpanded` englobant TOUT le contenu normal + `#lutPanelExpandBtn` (icône 🎚️ seule, à l'intérieur du panneau) comme languette.

**Corrigé une seconde fois (3e jet, design final)** — ce 2e jet réduisait le panneau à sa propre languette INTERNE (toujours au même endroit que le panneau normal), mais la demande était différente : « je veux juste une petite languette collée à la barre latérale au niveau de la sélection des LUTs, comme un marque-page qui sortirait légèrement d'un livre. Quand on clique dessus, la fenêtre de réglages réapparaît. » Repensé : `#lutSettingsPanel` redevient un bloc simple qui se cache **entièrement** (`display:none`, comme fermé) quand réduit — plus de sous-structure interne. Une languette **séparée** `#lutPanelTab` (bouton vide 12×30px, coins arrondis à gauche, `box-shadow` pour l'effet "dépasse du bord") est positionnée dynamiquement via `_lutPositionPanelTab()`, collée contre le bouton `#lutBtn` (🎨) de `.player-toolbar` — recalculée à chaque affichage (pas mémorisée) pour rester juste après un redimensionnement, même technique que le panneau du mixeur BWF pour un problème similaire.

Nouvel état `_lutPanelShouldShow` (bool, piloté uniquement par `_lutRefreshForActiveClip()`) répond à "faut-il montrer QUOI QUE CE SOIT en ce moment" (LUT résolue + preview active) — sans lui, la languette pourrait apparaître collée à la toolbar même sans LUT active sur le plan courant, un onglet qui ne mènerait nulle part au clic. `_lutApplyPanelCollapsed()` compose `_lutPanelShouldShow` et `_lutPanelCollapsed` pour choisir entre : rien, panneau complet, ou languette.

**Piège d'ordre trouvé et corrigé avant livraison** : `_lutPositionPanelTab()` lit la position réelle de `#lutBtn` — qui doit donc déjà être visible (`display:''`, mis à jour par `_lutUpdateBtnVisual`) au moment du calcul, sinon `getBoundingClientRect()` renvoie des zéros. L'ordre "naturel" du code (mettre à jour visuellement panneau/badge/canvas d'abord, bouton en dernier) aurait positionné la languette AVANT que le bouton ne soit visible. Fix : `_lutUpdateBtnVisual(resolved)` déplacé explicitement avant `_lutSettingsUpdateUI()`/`_lutApplyPanelCollapsed()` dans `_lutRefreshForActiveClip()`.

État `_lutPanelCollapsed` toujours persisté `localStorage['derush_lut_panel_collapsed']`. Distinct du show/hide global existant du panneau (lié à `_lutEnabled` + LUT résolue) : replié, un panneau (sous une forme ou une autre) reste toujours affiché tant qu'une LUT est active, il ne se referme pas tout seul.

## v0.3.71 — LUT appliquée aussi dans le pré-montage
Signalement : « quand j'applique une LUT sur un clip, ça affecte aussi les sélections de ce clip dans le prémontage. »

**Diagnostic** : le pipeline LUT (`js/lut.js`) était entièrement câblé sur le lecteur principal — `_lutGL`/`#lutCanvas` liés à `document.getElementById('player')` en dur dans `_renderLUT()`. Le pré-montage (double lecteur crossfade `#basketVid`/`#basketVidB`) n'avait aucun rendu LUT.

**Design** : plutôt que de rendre le pipeline existant multi-instance de façon générique (risque de régression sur un système déjà sensible, cf. sagas v0.3.42/v0.3.65 sur la fluidité du crossfade), un **second pipeline WebGL indépendant** dans `js/selects.js` (dépend de l'état du panier, pas de `js/lut.js`) : `_basketLutGL`, canvas `#basketLutCanvas` (dans `#basketViewerVideoWrap`), boucle `_basketRenderLUT()`. Seules deux fonctions de `js/lut.js` ont eu besoin d'être touchées — `_lutApplySettings`/`_lutUploadLUT` acceptent maintenant un contexte GL + des données en paramètres optionnels (défaut sur les globals du lecteur principal si omis, donc **zéro** changement de comportement pour les appelants existants) — le reste (`_lutInitGL`, `_lutResolveFor`, `_lutEnsureLoaded`, le shader lui-même) était déjà assez générique pour être réutilisé tel quel.

**Suivi du crossfade sans synchronisation dédiée** : `_basketRenderLUT()` relit `_basketActiveVid()` à CHAQUE frame plutôt que de mémoriser "quel lecteur regarder" — quand `_basketSwapActiveVideo()` bascule laquelle des deux vidéos est visible (crossfade), le rendu LUT suit automatiquement dès la frame suivante, sans code de synchronisation supplémentaire.

**Déclenchement** : `_basketLutRefresh()` (async, résout la LUT du clip *affiché dans le pré-montage*, indépendant de `activeClip` le lecteur principal) est appelée sans condition depuis de nombreux points (`_basketGoto`, `_basketSwapActiveVideo`, `openBasket()`, et — côté `js/lut.js` — en sortie de `_lutRefreshForActiveClip()` ainsi que directement dans `setLutSetting`/`resetLutSettings`) : elle se garde elle-même (si `#basketOverlay` n'a pas `.active`, coupe la boucle RAF et masque le canvas) plutôt que de demander à chaque appelant de vérifier si le pré-montage est ouvert — bien plus sûr qu'une liste de conditions dispersées à maintenir.

**Piège d'ordonnancement trouvé et corrigé avant livraison** : `openBasket()` appelle `renderBasketOverlay()` (qui charge le 1er item via `_basketGoto`, donc déclenche un premier `_basketLutRefresh()`) **avant** d'ajouter la classe `.active` à l'overlay — la garde interne aurait donc annulé ce tout premier appel. Fix : rappel explicite de `_basketLutRefresh()` en toute fin de `openBasket()`, après l'ajout de `.active`.

**Z-index** : `#basketLutCanvas` en `z-index:0` — sous l'overlay de cadre dynamique (`_ensureAspOverlay`, `z-index:1` codé en dur, créé paresseusement donc son ordre d'insertion DOM n'est pas garanti par rapport au canvas) mais au-dessus des `<video>` (z-index:auto, ordonnées par position DOM). Un z-index explicite mais inférieur évite toute dépendance fragile à l'ordre d'insertion.

## v0.3.72 — Filtre "sélection déjà faite"
Nouveau chip `✂️` (`data-filter="hasselect"`) dans `.filter-chips`. La variable `hasSelect` (`(n.selects||[]).length > 0`) existait déjà dans `renderClipList()` — utilisée uniquement pour afficher un point sur la vignette (`.clip-select-dot`), jamais branchée à un filtre. Ajout d'une condition `if(activeFilter === 'hasselect' && !hasSelect) return;` dans la boucle de filtrage — aucune nouvelle donnée à calculer.

## v0.3.73 — La lane des repères navigue au lieu de toujours poser un repère
Signalement : « plutôt que de placer un repère quand je clique au-dessus de la timeline, que je puisse me déplacer dans la sélection quand je maintiens le clic gauche. »

`_basketMarkerLaneClick` (un simple `onclick` qui posait toujours un repère) remplacé par `_basketMarkerLaneMouseDown` : même distinction seuil-3px clic/glisser que les poignées de trim et le réordonnancement des segments (v0.3.66/v0.3.69) — en dessous du seuil au relâchement, pose un repère (comportement d'origine préservé pour un clic rapide) ; au-delà, appelle `_basketSeekSeqRatio(ratio)` en boucle pendant le glisser (même mécanisme que le scrub de la piste des clips juste en-dessous, `_basketSeqMouseDown`).

**Piège trouvé et corrigé avant livraison** : les pins de repères existants (enfants de la lane) ne stoppaient la propagation qu'au `click`, pas au `mousedown`. Comme la lane écoute désormais `mousedown` (pas `click`) pour démarrer sa propre logique clic/glisser, presser un pin existant aurait AUSSI déclenché la logique de la lane parente (mousedown bubble avant que le stopPropagation du click du pin n'ait eu lieu) et posé un repère parasite au même endroit. Fix : `pin.addEventListener('mousedown', e => e.stopPropagation())` ajouté en plus du `onclick` existant.

# État au 9 septembre 2026 — v0.3.75 : la preview LUT réapparaît automatiquement au relancement

## Signalement
« Je veux aussi que ça garde en mémoire pour chaque clip le fait qu'on a appliqué des réglages au LUT, mais aussi quand je quitte le logiciel et le relance que la LUT apparaisse bien sur les clips où je l'ai appliqué (avec ses réglages propres). »

## Diagnostic
Deux moitiés de la demande, un seul vrai manque. Les assignations elles-mêmes (`_lutAssign` — quelle LUT + quels réglages pour quel clip/caméra) étaient déjà persistées dans `localStorage['derush_lut_assign_' + pid]` depuis l'introduction du modèle d'assignation par plan (v0.3.5x) — cette partie fonctionnait déjà. Le contenu brut des fichiers `.cube` est lui aussi déjà persisté (IndexedDB, `derush_luts`). Ce qui manquait : `_lutEnabled`, l'interrupteur maître de preview (bouton 🎨), portait littéralement le commentaire `// master toggle preview (session, pas persisté)` — remis à `false` à chaque lancement de l'application, sans exception. Donc même avec toutes les données déjà en place, rien ne s'affichait tant que l'utilisateur n'avait pas re-cliqué sur 🎨 après chaque redémarrage — exactement le symptôme décrit.

## Fix (`js/lut.js`)
- `_lutPersistEnabled()` (nouvelle fonction, symétrique de `_lutPersistAssign()`) écrit `_lutEnabled` dans `localStorage['derush_lut_enabled_' + pid]` — appelée depuis les deux seuls points qui mutent `_lutEnabled` directement : `toggleLUT()` et `confirmLutScope()` (qui active la preview automatiquement à la première assignation d'une LUT).
- `_lutLoadAssign(pid)` (déjà appelée par `enterWorkspace(pid)` à l'entrée dans un projet) relit maintenant cette clé en plus de `_lutAssign`, restaurant `_lutEnabled` avant que la restauration du dernier clip consulté (`_loadClipResumeTime` → `selectClip` → `_lutRefreshForActiveClip`) ne décide d'afficher ou non le rendu.
- Aucun autre changement nécessaire : le mécanisme de résolution/rendu (`_lutResolveFor`, `_lutEnsureLoaded`, `_renderLUT`) fonctionnait déjà correctement une fois `_lutEnabled` correctement restauré — le bug était uniquement dans l'état initial de cette seule variable.
- Persisté **par projet**, comme `_lutAssign` — activer la preview sur un projet n'active rien sur les autres.

# Archive du 15/09/2026 — contenu retiré de CLAUDE.md pour repasser sous la limite de 150k caractères

`CLAUDE.md` avait dépassé 193 542 caractères (limite d'outillage : 150 000), au-delà de sa propre règle de ne garder qu'une référence technique courte. Cette section archive **verbatim** tout le contenu narratif/enquête retiré ce jour-là (retours terrain, sagas de debug, justifications détaillées) ; `CLAUDE.md` ne garde plus que des versions condensées de 2-5 lignes pointant ici. Rien n'a été perdu — voir `CLAUDE.md` § « Pièges critiques à retenir » pour les numéros de pièges (37-41 notamment) dont la version longue est ci-dessous.

## FCPXML — mute automatique du canal LTC des FS5 : ESSAYÉ, NE FONCTIONNE PAS (sept. 2026)

Retour terrain : « je dois faire à chaque fois que j'importe une timeline [le mute du canal LTC dans DaVinci] ? » — couper le bruit LTC (BZZZZ) à la main dans Clip Attributes après CHAQUE réimport d'une timeline FCPXML, parce que les changements de Clip Attributes faits sur un item du Media Pool ne se répercutent pas rétroactivement sur les instances déjà découpées par un import ultérieur (comportement DaVinci, pas un bug Derush).

**Tentative de fix, implémentée puis intégralement retirée** : ajout d'un élément `<audio-channel-source>` (FCPXML 1.8+, standard) sur chaque `<asset-clip>` FS5, avec le canal LTC détecté automatiquement par facteur de crête (même technique que `transcode_proxies.sh`) et marqué `active="0"`. Détection et génération XML **correctement vérifiées** avant livraison (testé sur 3 clips réels DRIFT_CLUB au canal LTC connu indépendamment : les 3 corrects ; XML bien formé, un piège de silence-numérique-donnant-un-crest-factor-dégénéré trouvé et corrigé avant livraison). **Testé en conditions réelles par l'utilisateur après le build → le bruit LTC était toujours présent, aucun effet.**

**Cause, confirmée par recherche externe (pas une supposition)** : c'est un **bug connu et documenté de longue date dans DaVinci Resolve**, qui gère mal l'assignation de canal audio par source à l'import de XML/FCPXML (Premiere AAF/XML comme FCPXML), quel que soit ce que le fichier source déclare — DaVinci ignore ou mésinterprète `<audio-channel-source>` à l'import, indépendamment de sa validité. Sources : [Lowepost — Resolve imports multitrack field audio via XMLs and AAFs incorrectly](https://lowepost.com/forums/topic/6374-resolve-imports-multitrack-field-audio-via-xmls-and-aafs-incorrectly-sets-timeline-audio-clips-source-channel-to-mute-rather-than-the-correct-channel/), [getrecut.com — Importing XML with Multi-Track Audio into DaVinci Resolve](https://getrecut.com/xml-and-multitrack-audio-davinci-resolve/). **Le contournement manuel (Clip Attributes après import) reste la seule option connue** — aucun fix côté application exportatrice (Derush ou autre) ne peut compenser un bug d'interprétation côté DaVinci.

**Code intégralement retiré** (`_detect_fs5_ltc_channel`/`_attach_fs5_ltc_mute` et leurs 4 points d'appel dans `derush_exports.py`) — laisser un coût d'export (jusqu'à 4 appels ffmpeg par clip FS5) sans aucun bénéfice réel aurait été pur gaspillage. **Ne pas retenter cette approche** sans une preuve nouvelle que DaVinci a corrigé ce bug d'import.

**Piste alternative explorée ensuite — automatiser via l'API de scripting plutôt que le FCPXML — également dans l'impasse** : deux méthodes **en lecture** exposent exactement la donnée voulue, avec un schéma JSON très clair —
- `TimelineItem.GetSourceAudioChannelMapping()` → `{"embedded_audio_channels":N,"linked_audio":{"<ch>":{"channels":1,"offset":N,"path":"..."}, ...},"track_mapping":{}}` (vu avec `track_mapping` vide sur les clips testés).
- `MediaPoolItem.GetAudioMapping()` → même structure, mais avec `track_mapping` **rempli** sur un clip déjà configuré manuellement : `{"1":{"channel_idx":[1],"mute":true,"type":"mono"}, "2":{"channel_idx":[2],"mute":false,...}, ...}` — c'est très exactement la donnée qui pilote le mute par canal fait à la main dans Clip Attributes.

Aucune des deux n'a de méthode d'écriture correspondante exposée par cette version de l'API (`SetSourceAudioChannelMapping`, `SetAudioMapping` : les deux lèvent `TypeError("'NoneType' object is not callable")` — la méthode n'existe pas réellement). **Piège à retenir** : `hasattr(item, 'NomInventé')` renvoie systématiquement `True` sur ces objets `PyRemoteObject` de l'API Resolve, quel que soit le nom testé — ce n'est PAS un moyen fiable de vérifier qu'une méthode existe réellement sur cette API ; seul un appel réel (avec les risques que ça implique sur un projet en cours d'édition) le confirme. Les deux appels d'essai ont été faits en no-op (mêmes données relues qu'écrites) après accord explicite de l'utilisateur, et vérifiés sans effet (`avant == après`).

**Conclusion sur ce sujet** : aucun levier trouvé, ni côté export (FCPXML), ni côté API de scripting (lecture seule sur cette donnée précise). La correction manuelle par lot dans Clip Attributes reste la seule option fiable. Ne pas retenter sans une nouvelle piste concrète (ex. une méthode d'écriture ajoutée dans une future version de l'API Resolve).

## Précondition FCPXML/Media Pool — pourquoi deux tentatives ont semblé échouer sur la précision du TC

⚠️ **Précondition non négociable** : le Start TC du Media Pool DaVinci DOIT avoir été corrigé à la même valeur LTC (`Update Timecode from Audio Track` / `fs5_fix_timecode_resolve.py`) **ET le Media Pool doit contenir TOUS les médias référencés** (toutes journées, toutes caméras) **avant** l'import de cet export. Deux tentatives précédentes (v0.3.85, v0.3.87) semblaient échouer sur la précision du TC, mais l'investigation du 11/09/2026 (logs DaVinci, `davinci_resolve.log`) a montré qu'un Media Pool **incomplet** était au moins en partie responsable des échecs observés en v0.3.87 (un clip GoPro jamais touché par le LTC échouait identiquement) — le vrai taux d'échec dû à la précision du décodage TC seul, dans des conditions propres, n'a été établi qu'après (voir la saga piège #37 ci-dessous).

## Autocomplete tags — historique des trois passes de fix (août 2026)

`.sp-tag-suggest` est en `height` fixe (74px, pas `max-height`) + `align-content:flex-start` : le nombre de pills affichées varie à chaque frappe (filtrage), un `max-height` aurait laissé la boîte se redimensionner verticalement à chaque lettre tapée. Hauteur fixe = zone toujours réservée, y compris quand 0 suggestion ne matche (boîte présente mais vide, jamais retirée du DOM/masquée).

La hauteur fixe seule ne suffisait **pas** (retour terrain persistant : « la fenêtre change de taille et de forme ») — la vraie 2e cause était la **largeur** : `.marker-popup` n'avait qu'un `min-width` (360px), jamais de `width`. Un conteneur `flex-wrap` sans largeur définie sur son ancêtre se dimensionne en *shrink-to-fit* : le calcul essaie d'abord de caser tout le contenu (ici les pills de suggestion) sur une seule ligne (candidat max-content) avant de considérer le wrap — donc plus il y avait de suggestions filtrées large-content, plus la popup entière s'élargissait pour les accueillir sans retour à la ligne, puis se recentrait (`transform:translate(-50%,-50%)` sur `top/left:50%`) → l'impression de fenêtre qui « change de taille et de forme » à chaque lettre. Fix définitif : `.marker-popup { width: 520px; }` (remplace `min-width`, taille demandée en retour terrain une fois le tremblement corrigé) — largeur désormais fixe, le flex-wrap des suggestions comme des chips de tags déjà posés est contraint à l'intérieur, plus aucune variation de largeur possible. Aucun enfant de `#markerPopup`/`#selectPopup` n'a de largeur pixel fixe (tout est `width:100%` ou wrap naturel), donc sans risque de débordement.

Flip vers le haut de `#tagAutocomplete` : le champ Tags est tout en bas du panneau de notes, donc `window.innerHeight - r.bottom` est souvent petit. `renderTagAutocomplete` mesure `box.offsetHeight` (menu déjà rempli/affiché) et bascule `top` au-dessus du champ (`r.top - boxH - 2`) si l'espace restant sous le champ est inférieur à la hauteur du menu **et** qu'il y a la place au-dessus — sinon les suggestions rendaient hors de la fenêtre, invisibles sans scroller la page (retour terrain 18/08/2026).

## LUT partagée — motivation et détails d'implémentation complets (sept. 2026)

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

## API de scripting DaVinci Resolve — précisions supplémentaires (diagnostic, sept. 2026)

**Limite** : pas d'outil de contrôle souris/clavier dans cette session (pas d'automation de l'UI Resolve, pas de clic sur les menus) — uniquement lecture/écriture de données via l'API scripting. Suffisant pour tout le diagnostic TC de la saga FS5 (piège #37).

Un `TimelineItem` offline n'expose PAS son TC source déclaré (`GetSourceStartFrame()` renvoie `None`) → pour le retrouver, croiser `(GetName(), GetDuration(), GetStart())` avec le FCPXML réellement importé (parsé en Python, `<asset-clip offset/duration/start>` + `<asset ref/src>`) — ce triplet désambiguïse de façon fiable même quand plusieurs jours partagent le même nom de fichier (cas FS5 : `ClipNNNN.MXF` réutilisé chaque journée).

## Modale d'export — détail du filtre min_rating=1 (sept. 2026)

Retour terrain : « un filtre pour exporter que les clips qui ont au moins une étoile ». Le filtre `min_rating` était déjà générique côté serveur (`fc_min_rating`, partagé par tous les exports filtrés — inclut un clip dès qu'**un seul membre de l'équipe**, tous confondus, lui a mis au moins cette note). Même ladder 3/2/1 déjà utilisée par le sélecteur "Rating min." du rough cut (`#rcRating`). Ces boutons exportaient en FCPXML jusqu'au 14 sept. 2026 (voir § Export DRT multipiste), convertis en `drt` une fois le multipiste son ingé validé fiable ; le bouton "Timeline DaVinci complète" (workflow complet, non filtré) a suivi le même changement. XML Premiere (`xml_fcp7`), Subclips, Rough cut et l'export du pré-montage restent en FCPXML/XML — pas concernés par ce changement, DRT étant spécifique à DaVinci et nécessitant une connexion live.

Sous les boutons DRT de « Timelines de selects », une ligne « Markers EDL correspondant » : un `exportDataWithParams('markers_edl', {...})` par filtre, MÊMES params (`min_rating`/`cats`/`rejected`/`label`) que le bouton DRT au-dessus — le découpage par marqueurs X reste identique entre les deux (les deux s'appuient sur la même règle de segments, voir `_aaf_kept_segments`). L'endpoint passe `filter_config` à `export_markers_edl` (v0.3.83) et nomme le fichier avec `label`.

## Nom de fichier à l'export FCPXML — détail complet (sept. 2026)

Retour terrain : « quand j'exporte le FCPXML, qu'il me propose de lui donner un nom plutôt qu'un nom automatique ». Le nom de fichier final vient **entièrement du client** — `_text_response(content, f"{label}_selects.fcpxml", ...)` côté serveur utilise tel quel le `label` reçu en query param (déjà vrai avant cette feature, aucun changement serveur nécessaire) — donc toute la feature est côté front.

`_promptExportName(defaultName)` (`derush_app.html`, juste avant `exportData`) : modale `#exportNameOverlay`/`#exportNameInput` (jamais `prompt()` natif — piège #1, casse le focus state Electron) retournant une **Promise**, résolue avec le nom saisi ou `null` si annulé (`Échap`, ✕, ou nom vide validé). Pré-remplie avec le nom qui aurait été utilisé automatiquement (nom du projet, ou le libellé déjà spécifique d'un bouton filtré comme `selects_3stars`) — l'utilisateur part d'une valeur sensée qu'il peut librement remplacer plutôt que de taper depuis rien. `_sanitizeFilenamePart(s)` neutralise les caractères invalides pour un nom de fichier Windows (`\/:*?"<>|`).

**Scope volontairement limité aux exports `.fcpxml`** (demande explicite « le fcpxml », pas XML Premiere/EDL/CSV) : `exportDataWithParams(fmt, params)` prompt seulement si `fmt === 'fcpxml'`, et `_basketExport(fmt, onlySelected)` (`js/selects.js`, pré-montage) prompt seulement pour `fmt === 'fcpxml'` — `xml_fcp7` sur les mêmes boutons reste inchangé (nom automatique). Chaque appelant annule l'export entier (`return` sans naviguer/`window.open`) si la modale est annulée — jamais de fallback silencieux sur le nom automatique dans ce cas, pour que "Annuler" annule vraiment. **Depuis que « Timelines de selects » exporte en `drt` (§ Export DRT multipiste), ces boutons ne déclenchent plus ce prompt** — resté `fcpxml`-only, jamais étendu à `drt` (pas demandé) ; seuls `exportSubclips()`/`exportRoughCut()` (restés en FCPXML) et le pré-montage en gardent le bénéfice.

## Export DRT multipiste — récit complet de l'enquête (sept. 2026)

Retour terrain : le FCPXML ne peut porter qu'**une seule piste son par clip**, alors que le vrai besoin est une piste par micro d'ingé son. Deux voies antérieures ont été explorées et fermées avant d'arriver à celle-ci — voir `D:\METHODOLOGIE_IMPORT_RUSHS_DAVINCI.md` §14-29 pour le récit complet de l'enquête (mécanismes testés, preuves, tous les échecs instructifs) :
- **AAF** (`export_aaf`, `derush_exports.py`, `pyaaf2`) : construction fonctionnelle et fiable pour l'image (rattachement par UMID, jamais de doublon) et pour le son caméra, mais **le rattachement AAF de l'audio se fait par timecode seul chez DaVinci, jamais par nom de fichier** — prouvé par intervention directe (suppression en cascade de candidats concurrents), vrai même pour un AAF natif exporté par DaVinci lui-même. Une collision de TC entre journées (structurelle sur du tournage time-of-day multi-jours) fait donc jouer le mauvais fichier, sans que rien côté construction du fichier ne puisse s'en prémunir. Code conservé tel quel (repli historique), plus la voie recommandée.
- **API `MediaPool.AppendToTimeline`** : ne pose jamais plus d'un canal audio par plan, quels que soient les paramètres.

**Solution retenue : `export_drt` (`derush_drt.py`)**, via `MediaPool.CreateTimelineFromClips` — seule méthode qui restitue correctement TOUTES les pistes ingé son. Contrainte assumée par l'utilisateur : **DaVinci Resolve doit tourner en direct**, projet ouvert, Media Pool complet et déjà synchronisé (Auto Sync Audio Based on Timecode déjà fait — § Workflow FS5), au moment de l'export — ce n'est plus un fichier portable généré hors-ligne comme les autres exports. Le rattachement se fait entièrement par l'identité live du `MediaPoolItem` (retrouvé par nom de fichier + jour), jamais par un fichier échangé ni par une résolution de timecode — élimine la classe de bug ci-dessus par construction, pas en la contournant.

Validé de bout en bout sur un export réel de 53 plans (filtre ⭐⭐⭐, projet complet, y compris les clips historiquement à problème) : confirmé fonctionnel par l'utilisateur.

**Nouvelle piste validée (§27-28 de la méthodologie) : générateur DRT** (format natif Resolve). Le DRT n'identifie jamais le son ingé par fichier séparé (donc aucune collision TC possible) — recette confirmée fonctionnelle : `MediaPoolItem.GetMediaId()` fournit l'identité persistante requise, et le `FieldsBlob` opaque de chaque plan (jamais patchable à la main, encodage à longueur variable) doit être obtenu via un aller-retour "oracle" à la demande (`Timeline.Export(path, resolve.EXPORT_DRT)` sur une timeline API jetable au bon trim), puis réutilisé tel quel. **Implication non tranchée à l'époque** : nécessite Resolve ouvert en direct à l'export (pas un fichier portable hors-ligne) — pesée contre le repli duplication AAF et l'assemblage manuel, tranchée en faveur du DRT (validé sur l'export de 53 plans ci-dessus).

## Pré-montage (Basket overlay) — récits complets par feature (sept. 2026)

**Dupliquer une sélection** (`⧉` dans `.basket-item-actions`, `_basketDuplicateItem(idx)`) — retour terrain : « pouvoir copier coller une sélection plusieurs fois dans le prémontage » (répéter un même plan à plusieurs endroits du montage, ex. un plan de coupe/réaction). Un clic = une copie insérée juste après l'original dans `allBaskets[uid]` ; re-cliquer (sur l'original ou une copie) ajoute une copie de plus — "coller plusieurs fois" sans presse-papier/état de sélection à gérer, combiné au glisser-déposé déjà existant pour repositionner une copie ailleurs dans la bobine. Crée une **sélection indépendante** (nouvel id aléatoire dans `n.selects`, mêmes `in`/`out`/`tags`/`desc` au départ, nom suffixé `" (copie N)"` via `_basketNextSuffixedName`) plutôt que de réutiliser `select_id` — sinon retrimmer une copie depuis la timeline de séquence (qui mute `sel.in`/`out` en place) changerait aussi silencieusement toutes les autres occurrences de la même sélection dans le pré-montage. Deux poussées d'annulation distinctes (`pushUndo(clip.id)` pour `allNotes`, `_pushBasketUndo()` pour `allBaskets`), même pattern déjà utilisé par `confirmSelect()` pour une nouvelle sélection auto-ajoutée au pré-montage — Ctrl+Z peut donc nécessiter deux appuis pour tout annuler.

**Double lecteur crossfade** (`#basketVid`/`#basketVidB`, `_basketActiveVid()`/`_basketInactiveVid()`) : quand le segment suivant est sur un clip **différent** de celui en lecture, il est préchargé en arrière-plan dans le lecteur inactif (`_basketPreloadNextSegment`, identité clip **+** sélection via `dataset.clipId`/`dataset.selectId`) pour basculer instantanément sans flash noir ni gel. Quand il est sur le **même** clip que l'actif, `_basketPreloadNextSegment` s'abstient explicitement — recharger un fichier déjà en cours de décodage dans l'autre élément juste pour y basculer ensuite est coûteux et, répété sur toute une série de sélections découpées dans le même rush (le cas le plus courant du pré-montage), a fini par ne plus jamais finir à temps → flash noir à chaque transition → crash du renderer Electron après une ou deux lectures (retour terrain, build packagée, sept. 2026). Cette transition reste fluide via le chemin de repli de `_basketGoto` (pause → seek → attend `seeked` → reprend, sur l'élément déjà chargé, sans rien recharger) — voir piège #31/#33.

**Réordonner directement sur la timeline de séquence** (façon DaVinci, `_wireBasketSeqSegDrag`, `isMine` seulement) — retour terrain : « clic gauche sur un clip dans la timeline pour le déplacer et l'intercaler entre deux clips ou au début/fin de la séquence ». Drag-and-drop natif HTML5 sur le **corps** du segment (`el.draggable = true`), distinct du drag mousedown/mousemove custom des poignées de trim (`handleIn.draggable = handleOut.draggable = false` + leur `preventDefault`/`stopPropagation` sur `mousedown` empêchent le drag natif de démarrer quand on saisit précisément une poignée). La **moitié survolée** du segment cible (`dragover`, comparaison à `rect.width/2`) détermine si le clip glissé s'insère avant (`.drop-before`, liseré vert à gauche) ou après (`.drop-after`, à droite) — permet de viser précisément l'intercalation entre deux clips, ou le tout début/toute la fin en lâchant sur la moitié extérieure du premier/dernier segment. `_basketSeqReorder(fromIdx, toIdx, before)` fait le même travail sur `allBaskets[uid]` que `_wireBasketDrag` (réordonnancement depuis la LISTE à gauche) — deux implémentations séparées, même sous-jacent (`splice`+`_pushBasketUndo`+`saveBasket`). Le clic initial sur le segment déclenche aussi le scrub existant (`_basketSeqMouseDown` reste attaché à l'ancêtre `#basketSeqTimeline`, non court-circuité) : effet de bord accepté (la tête de lecture saute au point cliqué avant que le drag natif ne prenne la main), pas gênant en pratique.

**Précision de trim façon DaVinci (sept. 2026)** — retour terrain : glisser une poignée `.bseq-handle-in`/`-out` perdait facilement le point d'atterrissage précis. Trois briques dans `js/selects.js`, juste avant `_wireBasketSeqHandle` :
- `_basketSnapClamp(edge, rawT, otherBound, fps, clipDur, minDur)` — arrondit **toujours** à la frame exacte (`Math.round(t*fps)/fps`) puis clampe ; utilisée à la fois par le glisser souris et le nudge clavier, donc les deux méthodes convergent vers la même grille.
- `_basketFmtDelta(deltaSec, fps)` → `{text:"+1s04f"/"−12f"/"±0f", cls:"pos"/"neg"/"zero"}`.
- `_basketShowTrimHud(handleEl, tcText, deltaSec, fps, hint)`/`_basketHideTrimHud()` — bulle `#basketTrimHud` (`position:fixed`, repositionnée en JS au-dessus de la poignée) affichant TC exact + delta depuis le point de départ + rappel des raccourcis, visible en continu pendant tout le geste (glisser ou nudge clavier) — la vraie réponse à « je ne sais plus où j'atterris ».

**Trim armé au clavier** (`_basketArmedTrim`, état global) : cliquer une poignée **sans glisser** l'« arme » (`_basketArmTrimHandle`) au lieu de ne rien faire — façon DaVinci, sélectionner un point de montage puis `←`/`→` (1 frame) ou `Maj+←`/`→` (1s) l'ajuste précisément (`_basketNudgeArmedTrim`, géré dans `_basketKeydown`). `Entrée` valide (`_basketCommitArmedTrim`), `Échap` annule (`_basketCancelArmedTrim`, `sel.in`/`out` jamais mutés tant que non validé — même principe que le glisser, un seul `pushUndo`/`saveNotes` par session de trim, pas un par frappe).
- **Piège DOM évité** : valider un trim armé rappelle `renderBasketOverlay()` → `_basketRenderSeqTimeline()` **détruit et recrée toutes** les poignées (`track.querySelectorAll('.basket-seq-seg').forEach(el=>el.remove())`), y compris celle qu'on vient potentiellement de cliquer dans le même geste. `_wireBasketSeqHandle` flush donc un trim armé en tête de `mousedown` puis **s'arrête là** (`return`) plutôt que de continuer avec une référence `handleEl` désormais détachée (un `getBoundingClientRect()` sur un nœud hors document renvoie des zéros → HUD mal positionné) — un second clic engage la nouvelle poignée sur un DOM frais.
- **Garde anti-référence-obsolète générale** : `renderBasketOverlay()` commence par `if(_basketArmedTrim) { _basketCommitArmedTrim(); return; }` — tout re-rendu déclenché ailleurs (ajout/retrait/réorganisation d'item, switch d'utilisateur affiché) valide d'abord le trim en attente ; `_basketCommitArmedTrim()` vide `_basketArmedTrim` **avant** son propre appel à `renderBasketOverlay()`, donc pas de récursion infinie. `_basketGoto()` et `closeBasket()` flushent aussi explicitement (navigation ou fermeture = validation implicite).
- **Flèches à double rôle** dans `_basketKeydown` : nudge du point armé s'il y en a un, sinon nudge classique de la tête de lecture (`1/fps` / `Maj` = 1s) — mêmes conventions que le lecteur principal.

**Repères de séquence + magnétisme (sept. 2026)** — retour terrain suivant : « des petits marqueurs, pas ceux avec des commentaires, juste des repères pour faire coulisser les poignées à cet endroit précis avec un peu de magnétisme ». Distincts des marqueurs annotés (`addMarker`, catégorie/description/discussion, posés sur UN clip) : ce sont de simples points d'accroche, **personnels**, en **secondes-séquence** (position dans la bobine assemblée, pas dans un clip source) :
- État : `_basketSeqMarkers` (array de floats triés), persisté en `localStorage['derush_basket_seq_markers_' + pid]` (`_loadBasketSeqMarkers`/`_saveBasketSeqMarkers`) — même logique que `_lutAssign`/`_bwfMixerSettings`, pas dans `allNotes`/le projet partagé. Chargés à `openBasket()`.
- UI : lane dédiée `#basketSeqMarkers` (12px, au-dessus de `#basketSeqTimeline`, largeur synchronisée en JS à chaque zoom — `_basketSeqWheel`). **Clic simple** sur la lane = ajoute un repère à cette position ; **clic maintenu + glisser** = scrube la séquence à la place (retour terrain : « plutôt que de placer un repère quand je clique au-dessus de la timeline, que je puisse me déplacer dans la sélection quand je maintiens le clic gauche »). `_basketMarkerLaneMouseDown(e)` : même distinction seuil-de-3px clic/glisser que les poignées de trim et le réordonnancement des segments — si le mouvement dépasse le seuil, appelle en boucle `_basketSeekSeqRatio(ratio)` (même mécanisme que le scrub de `_basketSeqMouseDown` sur la piste juste en-dessous) ; sinon, au relâchement, pose un repère (`_basketDeselectSeqMarker()` + `_basketAddSeqMarkerAt`). Les pins de repère (`.basket-seq-marker-pin`, enfants de la lane) stoppent la propagation dès leur PROPRE `mousedown` (pas seulement leur `click`) pour ne jamais déclencher aussi la logique de la lane parente. Bouton `Repère` (`#basketAddMarkerBtn`, `.basket-seq-toolbar` alignée à **gauche** au-dessus de la timeline) et touche **`M`** = ajout direct à la position de lecture courante (`_basketAddSeqMarkerAtPlayhead`, même formule de position-séquence que `_basketUpdateSeqHead`) — chemins qui ne passent pas par la lane, donc pas concernés par la distinction clic/glisser. Icône du bouton = même losange ambre que les repères sur la timeline (`.bseq-marker-diamond`, classe de base partagée avec `.basket-seq-marker-pin` — celle-ci surcharge juste `width`/`height` à 9px via l'ordre du CSS, le bouton reste à 8px).
- **Clic sur un repère existant = sélection + seek, PAS suppression** (retour terrain explicite : « je ne veux pas que le clic l'efface, je veux avancer le clip à cet endroit et voir l'image ; la suppression doit être un geste à part »). `_basketSelectSeqMarker(t)` : marque `_basketSelectedSeqMarker = t` (valeur en secondes, pas un index — un index se périmerait au moindre ajout/retrait puisque le tableau est retrié), ré-affiche le repère en surbrillance (`.basket-seq-marker-pin.selected`), puis traduit `t` en `{idx, offset}` via `_basketSeqTimeToSegmentOffset(t)` et appelle `_basketGoto(idx, offset, false)` — la visionneuse affiche l'image exacte à cet endroit, en pause. `Suppr`/`Backspace` (dans `_basketKeydown`, uniquement si un repère est sélectionné) → `_basketDeleteSelectedSeqMarker()`. `Échap` : cascade de priorité — annule d'abord un trim armé s'il y en a un (`_basketArmedTrim`), sinon désélectionne le repère s'il y en a un (`_basketDeselectSeqMarker()`, retourne `false` si rien n'était sélectionné), sinon ferme l'overlay (`closeBasket()`).
- **Magnétisme** (dans `onMove` de `_wireBasketSeqHandle`, drag souris uniquement — le trim clavier armé reste volontairement exact/non magnétique, il a déjà sa propre précision) : rayon d'accroche en **pixels écran** (10px, indépendant du zoom) converti en secondes via `pxPerSec` courant. Ne compare JAMAIS la position brute du point dragué à un repère — compare la **frontière qui bouge réellement dans la séquence** pour ce segment, qui est TOUJOURS sa frontière avec le segment SUIVANT (`seg.start + dur`), quelle que soit la poignée tenue : `_basketSeqSegments()` positionne chaque bloc en cumulant les durées des précédents, donc la frontière d'un segment avec son PRÉCÉDENT ne bouge jamais quand on trimme CE segment — seule sa frontière avec le suivant se déplace (piège potentiel si on modélise ça autrement : le point qu'on croit intuitivement "ancré à la poignée in" ne l'est pas visuellement, cf. la poignée `bseq-handle-in` en `left:0` d'une boîte dont c'est justement le bord DROIT qui bouge). Si un repère est dans le rayon, `_basketNearestSeqMarker` le retourne, la durée cible est recalculée puis repassée dans `_basketSnapClamp` (donc re-alignée sur la grille de frames — l'accroche peut être à moins d'une frame du repère exact, jamais pile dessus si ça tombe entre deux frames). HUD (`_basketShowTrimHud`) affiche un 🧲 suffixé au TC quand accroché.
- **Limite assumée, pas un bug** : un repère est un nombre en secondes-séquence figé — si on retrime largement un segment plus tôt dans la bobine (ou qu'on réordonne), la position "logique" que visait le repère peut ne plus correspondre au même instant qu'à sa création (pas de ripple automatique des repères, comme dans la plupart des NLE hors mode ripple-marker dédié). Comportement volontaire, pas dans le scope demandé.
- **Piège trouvé et corrigé avant livraison** : les pins de repères existants (enfants de la lane) ne stoppaient la propagation qu'au `click`, pas au `mousedown`. Comme la lane écoute désormais `mousedown` (pas `click`) pour démarrer sa propre logique clic/glisser, presser un pin existant aurait AUSSI déclenché la logique de la lane parente et posé un repère parasite au même endroit. Fix : `pin.addEventListener('mousedown', e => e.stopPropagation())` ajouté en plus du `onclick` existant.

**Couper (façon DaVinci, sept. 2026)** — retour terrain : « ajouter un outil cut dans le prémontage à côté de repère mais aussi en appuyant sur C qui me permet de couper un clip dans la timeline ». Bouton `#basketCutBtn` (à côté de `#basketAddMarkerBtn` dans `.basket-seq-toolbar`) et touche **`C`** (`_basketKeydown`) → `_basketCutAtPlayhead()` (`js/selects.js`, juste après `_basketCancelArmedTrim`) : scinde en deux la sélection chargée dans la visionneuse, à la position de lecture courante (`vid.currentTime`, snap frame-exact comme le trim). Même schéma que `_basketDuplicateItem` (auquel il emprunte le pattern de save) : la 1ère moitié réutilise `sel`/`select_id` (mute `sel.out = cutT` en place), la 2e moitié est un **nouvel enregistrement** dans `n.selects` (nouvel id, `in:cutT, out:origOut`, nom suffixé `" (cut N)"` via `_basketNextSuffixedName`) avec un nouvel item inséré juste après dans `allBaskets[uid]` — jamais de mutation partagée entre les deux moitiés, retrimmer l'une n'affecte pas l'autre. Refuse la coupe (toast warn) si `sel.out - sel.in < _BASKET_TRIM_MIN_DUR * 2` (pas de marge suffisante) ou si le point clampé tomberait à moins de `_BASKET_TRIM_MIN_DUR` (~2 frames) d'un bord — réutilise la même constante que le trim, pas de moitié de durée quasi nulle. `isMine` seulement (bouton masqué via `renderBasketOverlay()` sinon, même toggle que `#basketClearBtn`) ; flush un trim armé en attente (`_basketCommitArmedTrim()`) avant de couper, comme les autres gestes qui déclenchent un re-rendu de la timeline de séquence.

**Nommage numéroté des sélections générées** (`_basketNextSuffixedName(selects, name, suffix)`, `js/selects.js`, juste avant `_basketDuplicateItem`) — retour terrain : « tu peux la nommer avec le suffixe cut et un numéro [...] quand je copie un même clip tu peux la nommer avec le suffixe copie et un numéro » (avant : suffixe fixe `" (copie)"` / `" (2)"` identique à chaque nouvelle occurrence, aucun moyen de distinguer copie 1 de copie 2 par le nom seul). Partagée par `_basketDuplicateItem` (`suffix='copie'`) et `_basketCutAtPlayhead` (`suffix='cut'`) : `_basketBaseSelectName(name)` retire d'abord un éventuel suffixe `" (copie N)"`/`" (cut N)"` déjà présent (regex) pour retomber sur le nom de base, puis balaie **toutes** les sélections du même clip (`n.selects`, avant l'ajout du nouvel enregistrement) cherchant `"<base> (<suffix> N)"` pour prendre le N max + 1 — numérote donc à plat même si on duplique une copie ou coupe un segment déjà issu d'une coupe, jamais d'empilement `" (copie 1) (copie 1)"`. Les deux suffixes (`copie`/`cut`) ont leur propre compteur indépendant sur un même clip.

**Renommer une sélection** (`✏️` dans `.basket-item-actions`, à côté de `⧉` et `🗑`) — retour terrain : « je voudrais pouvoir aussi renommer les sélections dans le prémontage à côté de copie et supprimer ». Petite modale dédiée `#basketRenameOverlay`/`#basketRenameInput` (`derush_app.html`, juste après `#basketOverlay`) plutôt qu'un `prompt()` natif (piège #1 : casse le focus state sous Electron) ou une édition inline dans `.basket-item-name` — le `body.innerHTML` entier de la liste est reconstruit à chaque `renderBasketOverlay()` (poll 15s, WS `basket_updated`), ce qui détruirait un champ en cours d'édition inline. `_basketRenameItem(idx)` (`js/selects.js`, juste après `_basketDuplicateItem`) stocke `_basketRenameItemRef = r.item` (référence par **identité** de l'item du panier, pas par index — même raison que `_basketCurrentItemRef` : l'index dans `_basketLastResolved` peut se périmer si un re-rendu externe survient pendant que la modale reste ouverte). `_basketConfirmRename()` retrouve l'item via `_basketLastResolved.find(x => x.item === _basketRenameItemRef)`, refuse un nom vide (toast warn), mute `r.sel.name` en place (même objet que dans `n.selects`, pas de nouvel enregistrement — contrairement à dupliquer/couper), `pushUndo(r.clip.id)` + `saveNotes(true)`. `Entrée` valide, `Échap` annule (`_basketRenameKeydown` sur l'input) ; `closeBasket()` annule aussi la modale si elle était restée ouverte.

**Export FCPXML/Premiere du panier — sélection partielle** (sept. 2026) — retour terrain : « pouvoir sélectionner plusieurs plusieurs clips au sein du pré-montage et n'exporter qu'une timeline de cette sélection, pas forcément tous les plans ». Avant : `📤 Exporter` (`_basketExport(fmt)`) n'exportait que la bobine **entière** de `_basketViewUser` (`export_basket_fcpxml`/`export_basket_xml_fcp7`, `derush_exports.py`, déjà appuyés sur `_basket_entries`).
- Case à cocher sur chaque ligne du panier (`.basket-item-check`, `renderBasketOverlay()`) — état transitoire `_basketExportSelIds` (`Set` d'`item.id`, l'id **propre à la ligne** du panier, distinct du `select_id` de la sélection in/out sur le clip) : jamais persisté ni sauvegardé/synchronisé (comme `_lutSettings` en édition, ce n'est pas une donnée de projet), purgé des ids dont l'item a disparu à chaque `renderBasketOverlay()`, et vidé au changement d'utilisateur consulté (`_basketSwitchUser`) **et à la fermeture du panier** (`closeBasket()`, sept. 2026) puisque les ids n'ont de sens que pour le panier actuellement affiché. `row.dataset.itemId` porte l'id pour le retrouver au toggle.
- **Piège corrigé — coches oubliées d'une session précédente** (retour terrain : « j'ai exporté la sélection mais il y a pourtant des clips que je n'ai pas sélectionné dedans »). `closeBasket()` ne vidait PAS `_basketExportSelIds`/l'ancre de plage — seul un changement d'utilisateur consulté ou un clic sur `✕ Sélection` le faisait. Des coches posées lors d'une session antérieure (visibles si on scrolle, mais faciles à manquer sur un long panier) restaient donc actives silencieusement et pouvaient se retrouver incluses dans un export "sélection cochée" bien plus tard, sans rapport avec la tâche en cours — donnant l'impression de clips "non sélectionnés" apparaissant dans l'export. `closeBasket()` vide désormais les deux à chaque fermeture : chaque ouverture du pré-montage repart d'une ardoise vierge. **L'ordre d'export, lui, n'était pas bugué** : `_basket_entries` (`derush_exports.py`) itère toujours sur `basket` (l'ordre réel du panier) et n'utilise le `Set` d'ids cochés que pour un test d'appartenance O(1) — jamais pour l'ordre. Vérifié par un test isolé (filtre + ordre préservés) avant d'implémenter le fix ci-dessus.
- `draggable="false"` + `stopPropagation` sur `mousedown` **et** `click` du `<label>` de la case — la ligne entière (`.basket-item`) est `draggable` pour le réordonnancement HTML5 natif ; sans ces gardes, cliquer précisément la case pourrait démarrer le drag du parent au lieu de cocher (même classe de piège que les poignées de trim, #32).
- **Maj+clic = plage** (retour terrain : « pouvoir sélectionner plusieurs clips en même temps avec la touche shift »), façon Explorateur Windows/Gmail. La case porte un `onclick` (`_basketCheckboxClick(e, itemId, idx)`), **pas** `onchange` — un `change` de checkbox est un `Event` générique sans `shiftKey`, alors qu'un `click` est un `MouseEvent` qui le porte. Clic simple : toggle normal + pose l'ancre sur cet item. Maj+clic : `e.preventDefault()` annule le toggle natif déjà appliqué par le navigateur (le clic sur une checkbox la bascule *avant* de déclencher l'event `click`), puis `_basketApplyRangeSelect(anchorIdx, idx)` coche toute la plage `[min,max]` sans jamais rien décocher hors plage ; l'ancre **ne bouge pas** sur un Maj+clic, ce qui permet d'étendre/rétrécir la plage en Maj+cliquant plusieurs fois de suite depuis le même point de départ.
- **Piège corrigé — ancre positionnelle périmée après un réordonnancement** (retour terrain : « des plans qui ne sont même pas dans le prémontage sont intégrés dans la sélection... peut-être qu'il va chercher dans le mauvais jour ? »). Enquête : aucun doublon d'`id` de clip dans les données réelles (vérifié directement sur `drift_club.derush.json`, formule `f"{day}_{camera}_{f.stem}"` — le jour est bien inclus, pas de collision inter-jours possible), et `_basket_entries` filtre/ordonne correctement (revérifié). La vraie cause : `_basketExportAnchorIdx` (version initiale) stockait un **index positionnel** dans `_basketLastResolved`. Un glisser-déposer (liste OU timeline de séquence) survenant ENTRE le clic d'ancrage et le Maj+clic suivant change l'ordre du panier SANS invalider cet index — au prochain Maj+clic, l'ancre pointe alors sur un item complètement différent de celui réellement visé au moment du clic initial, et la plage `_basketApplyRangeSelect` calculée entre les deux mauvaises positions embarque des plans sans rapport avec l'intention réelle. Fix : `_basketExportAnchorItemId` stocke désormais l'**id stable** de l'item ancré (pas un index) ; `_basketAnchorCurrentIdx()` retrouve sa position COURANTE dans `_basketLastResolved` à chaque usage (`.findIndex`), donc la plage reste correcte quel que soit le nombre de réordonnancements survenus entretemps — ou renvoie `-1` si l'item ancré a été retiré du panier depuis (traité comme "pas d'ancre"). Reproduit et vérifié par un test Playwright dédié avant et après le fix.
- Bouton `#basketExportBtn` affiche le nombre coché (`_basketUpdateExportSelUI()`) ; `#basketExportMenu` gagne deux entrées `.basket-export-sel-only` (« FCPXML/XML — sélection cochée »), `disabled` tant que `_basketExportSelIds` est vide. `#basketExportSelClearBtn` (✕ Sélection) décoche tout.
- **Maj+clic sur le CORPS de la ligne** (`_basketRowShiftClick(idx)`, `_wireBasketRowHover`), pas seulement sur la case — retour terrain immédiat après la 1ʳᵉ livraison : « ça ne fonctionne pas le Maj+clic je ne peux pas sélectionner plusieurs plans ». Repro isolée en Playwright headless : `_basketCheckboxClick` fonctionnait bien en Chromium réel *quand on clique précisément la case de ~16px*, mais l'usage naturel est de Maj+cliquer la ligne/vignette (bien plus grande cible) — le listener `click` du corps de la ligne ignorait totalement `shiftKey` et appelait toujours `_basketPlayFrom`. Le row-listener vérifie maintenant `e.target.closest('.basket-item-check')` (laisse la case gérer son propre clic) puis `e.shiftKey` avant de lancer la lecture ; `_basketRowShiftClick` réplique `_basketApplyRangeSelect` avec, en plus, un cas explicite "pas encore d'ancre" (premier Maj+clic du panier) qui coche l'item cliqué et le prend comme ancre plutôt que de ne rien faire.
- `_basketExport(fmt, onlySelected)` : si `onlySelected` et Set vide → toast warn, sinon `?items=id1,id2,...` (join simple, les `item.id` sont des chaînes base36 aléatoires alphanumériques — pas d'échappement nécessaire) ajouté à l'URL d'export, mêmes autres query params (`user`, `label`, `root` — piège #36) que l'export complet.
- Serveur : `_basket_entries(project, user_key, item_ids=None)` (`derush_exports.py`) accepte le filtre optionnel — ne garde que les items dont `item['id']` est dans `item_ids`, **dans l'ordre du panier**. `export_basket_fcpxml`/`export_basket_xml_fcp7` relaient `item_ids` tel quel. Endpoint (`derush_server.py`, route `basket_fcpxml`/`basket_xml_fcp7`) lit `qs.get('items')`, split sur `,`, `None` si absent. Nom de fichier suffixé `_selection` quand un filtre est actif.

**Export DRT du panier (14 sept. 2026)** — les deux boutons FCPXML du menu 📤 Exporter du pré-montage (tout / sélection cochée) sont devenus des boutons **Timeline DaVinci (DRT)**, même changement que pour la modale d'export principale (§ Export DRT multipiste) : le pré-montage bénéficie donc aussi de toutes les pistes son ingé, plus fiable que l'ancien FCPXML pour cet usage. `export_basket_drt(project, user_key, item_ids)` (`derush_drt.py`) réutilise `_basket_entries` (mêmes `(clip, sel)`, `sel['in']`/`sel['out']` en secondes) et le cœur commun `_build_and_export_drt` partagé avec `export_drt` — même mécanisme (`CreateTimelineFromClips` + export natif), même contrainte (DaVinci Resolve lancé, projet ouvert). Endpoint `basket_drt` (`derush_server.py`), `_basketExport('drt', onlySelected)` côté client (`js/selects.js`, déjà générique sur `fmt`, aucun changement JS nécessaire au-delà des boutons HTML). `export_basket_fcpxml`/`export_basket_xml_fcp7` conservés côté code (XML Premiere reste au bouton, FCPXML n'a plus de bouton nulle part dans l'app).

## Preview LUT — panneau réduit → languette, historique en trois passes (sept. 2026)

Retour terrain en trois temps : (1) « pouvoir la diminuer pour que ça ne prenne pas trop de place » (1er jet : ne cachait que les sliders, titre+Reset restaient visibles) ; (2) « je veux que Réglages LUT et Reset ne soit plus visible, juste un petit bout qui dépasse, comme Photoshop » (2e jet : panneau réduit à une languette interne à `#lutSettingsPanel`) ; (3) « je veux juste une petite languette collée à la barre latérale au niveau de la sélection des LUTs, comme un marque-page qui sortirait légèrement d'un livre » — design final :
- Réduit = `#lutSettingsPanel` **entièrement caché** (`display:none`, comme fermé) ; une languette **séparée** `#lutPanelTab` (bouton vide, 12×30px, coins arrondis à gauche seulement, `box-shadow` vers la gauche pour l'effet "dépasse du bord") prend le relais, positionnée en `position:absolute` dans `#videoWrapper`.
- `_lutPositionPanelTab()` aligne la languette sur le bouton `#lutBtn` (🎨, dans `.player-toolbar`) via `getBoundingClientRect()` des deux éléments + de `#videoWrapper` (conversion en coordonnées relatives à l'ancêtre positionné du panneau) — recalculé à CHAQUE affichage plutôt que mémorisé, pour rester juste après un redimensionnement de fenêtre. Même technique que le panneau du mixeur BWF (`js/bwf-mixer.js`) pour un problème similaire (deux boutons déclencheurs dans des zones DOM différentes).
- **Piège d'ordre trouvé et corrigé avant livraison** : `_lutPositionPanelTab()` lit la position de `#lutBtn`, qui doit donc déjà être visible (`display:''`) au moment du calcul — `_lutUpdateBtnVisual(resolved)` doit impérativement s'exécuter **avant** `_lutSettingsUpdateUI()`/`_lutApplyPanelCollapsed()` dans `_lutRefreshForActiveClip()`, pas après (l'ordre "naturel" du code aurait mis à jour le bouton en dernier).
- `_lutPanelShouldShow` (bool) reflète si un panneau — sous une forme ou une autre — doit être visible EN CE MOMENT (LUT résolue + preview active) ; piloté uniquement par `_lutRefreshForActiveClip()`, lu par `_lutApplyPanelCollapsed()` pour choisir entre tout cacher (rien à régler), afficher le panneau complet, ou afficher la languette — sans quoi la languette pourrait apparaître collée à la toolbar même sans LUT active, un onglet qui ne mène nulle part.
- `_lutTogglePanelCollapsed()` bascule `_lutPanelCollapsed` (bool, persisté `localStorage['derush_lut_panel_collapsed']`) puis rappelle `_lutApplyPanelCollapsed()`. Le panneau (sous une forme ou une autre) reste toujours affiché tant qu'une LUT est active — replié, il ne se referme pas tout seul, distinct du show/hide global lié à `_lutEnabled`+LUT résolue.

## Plein écran — popups oubliés du périmètre (v0.3.63)

`toggleFullscreen()` mettait en fullscreen uniquement `#videoWrapper` (juste la vidéo + canvases) : la timeline et ses marqueurs, siblings en dehors de cet élément, disparaissaient complètement en plein écran. Fix : nouveau conteneur `.player-fs-wrap` (`#playerFsWrap`), englobant `.player-area` + `.player-controls` + `.timeline-bar` (mais pas `.notes-panel`, qui reste hors-champ). CSS : `.player-fs-wrap { flex:1; display:flex; flex-direction:column; }`, `.player-fs-wrap:fullscreen { width/height:100%; background:#000; }`.

`#popupOverlay`+`#markerPopup` (nouveau marqueur) et `#selectPopupOverlay`+`#selectPopup` (sélection in/out) étaient restés siblings de `.player-fs-wrap`, pas descendants — la Fullscreen API ne peint que le sous-arbre de l'élément fullscreen, donc ces popups `position:fixed` continuaient d'exister (remplis, `display:block`) mais n'étaient tout simplement plus rendus à l'écran tant qu'on ne quittait pas le plein écran (retour terrain : « je mets un marqueur en fullscreen, la fenêtre ne s'affiche pas, elle est visible dès que je sors »). Fix : les deux blocs déplacés à l'intérieur de `.player-fs-wrap`, juste avant sa fermeture. Comme `position:fixed` a pour containing block le viewport tant qu'aucun ancêtre n'a de `transform`/`filter`/`contain` (`.player-fs-wrap` n'en a pas), le déplacement est neutre hors plein écran — même position, même z-index, seule la visibilité en plein écran change.

## Bandes noires incrustées — essais ratés avant la solution retenue (juin 2026)

Certains rushs ont des bandes noires *bakées* dans le fichier (matte cinéma au tournage — ex. FX6 J01 de DRIFT : matte 1.9:1, `1920×1012` dans du 1920×1080, ~34px de noir haut/bas). Deux conséquences corrigées : (1) le cadre 4:3 calait son haut/bas dans le noir ; (2) en comparaison/multicam, l'image bakée paraissait plus basse qu'un clip plein cadre (FS5).

**Détection : côté SERVEUR (fiable), pas client.** L'ancienne détection JS sur une frame isolée était trompée par les plans sombres (bug du comparateur). Désormais : `detect_letterbox(file_path)` : `ffmpeg cropdetect=24:2:0` sur 80 frames (`-ss 3`) → `{top,bottom,left,right}` (fractions) **+ `cw,ch`**. Ignore le bruit (<1.5%) et l'aberrant (>35%). Multi-frames = robuste au plan sombre. **Filtre de symétrie (v0.3.49)** : une vraie bande incrustée est centrée sur le capteur (`top≈bottom` ou `left≈right`) — un inset détecté sur un seul côté d'un axe (l'autre à 0, ou très déséquilibré, tolérance 50%) est mis à zéro des deux côtés : c'est un vignettage/occlusion réel (pare-soleil, capuchon, micro dans le coin...), pas une bande à retirer.

**Crop côté client : box 16:9 + ZOOM (transform:scale).** Tentatives ratées : `object-view-box` (non supporté Vivaldi → `false`, ignoré) ; `aspect-ratio` sur le `<video>` (non respecté → `object-fit:cover` sur-croppait) ; `aspect-ratio` = ratio contenu (dans une zone plus haute que 16:9, le contenu plus large devient plus court → mismatch). Solution retenue (indépendante de la forme de la zone) : la vidéo compare est dans une box `.cmp-vbox` **16:9** (= ratio du fichier, identique pour les 2 clips → même taille/hauteur). Pour un clip baké on **zoome la vidéo** juste assez pour faire sortir les bandes, `overflow:hidden` les masque. `_setVideoCrop(videoEl, ins)` : `z = max(1/(1-top-bottom), 1/(1-left-right))`.

**Portée : COMPARATEUR seulement** (`doCrop=true`). Lecteur (`selectClip`) et multicam → `doCrop=false` (juste `_contentInsets` pour le cadre). Premier affichage d'un clip baké : ~1-2 s (cropdetect serveur) puis caché.

**CSS compare-timeline — la vraie cause du "hauteurs différentes"** (FS5 vs FX6, pourtant tous deux 16:9, proxys 1280×720 et 1920×1080 SAR 1:1 vérifiés à l'ffprobe) : la grille `.compare-grid` en `1fr 1fr` n'était PAS à colonnes égales. Les items grid ont `min-width:auto` par défaut → la colonne dont le `<select>` contient un nom de fichier long et insécable (`DRIFT_avril0001S03.MP4`) prenait plus de largeur → sa vidéo `object-fit:contain` (zone plus haute que 16:9 → limitée par la largeur) devenait plus haute. Fix : `.compare-slot { min-width: 0; }` + `.compare-slot-header select { flex: 1; min-width: 0; }`.

Trois essais ratés pour les vidéos compare elles-mêmes avant `object-fit:contain` : (1) `max-width/max-height` → identique pour du même ratio, ok mais pas la vraie cause ; (2) `height:100%+width:auto` → sur un flex item, les clips se résolvaient mal et disparaissaient ; (3) `height:100%` absolu → la zone étant plus haute que 16:9, ça forçait une largeur énorme → rognage massif des côtés.

## Optimisations performance — contexte utilisateur (17-18 mai 2026)

Le user a constaté des lags, plantages, "écran noir vidéo figée" après 6-7 ouvertures du viewer multicam ou hover rapide sur GoPro. Coupable principal : ThreadedHTTPServer fanout illimité — un hover sur 20 clips déclenchait 240 ffmpeg simultanés et saturait la RAM/CPU, d'où la sémaphore globale (`_FFMPEG_MAX_CONCURRENT = max(2, min(8, cpu_count//2))`). Avant le fix `compute_waveform_peaks` : `struct.unpack` + boucle Python pure → tuple Python de millions d'int (300 MB-1 GB pour clip 1h+) ; le numpy-isage (`np.frombuffer` zero-copy + `.reshape(N,B).mean(axis=1)` vectorisé) a donné ~10× moins de RAM, ~100× plus rapide. Cleanup WebAudio + `<video>` dans `closeMcViewer`/`closeCompare` corrigé après avoir identifié qu'un `MediaElementSource` gardait référence aux `<video>` → leak mémoire massif à chaque close/open répété.

## Wrapper Electron — contexte du choix (POC Phase A, 18 mai 2026)

**Pourquoi** : la dépendance au browser tiers (Firefox/Chrome/Safari) cause des problèmes de portabilité, codecs (Firefox ne lit pas HEVC), et fuites mémoire qu'on ne peut pas contrôler. Electron embarque Chromium → comportement uniforme, codecs OS, contrôle fin. `npm.cmd start` (dev) → Electron spawn `python derush_server.py --no-browser`, poll `localhost:8765`, ouvre `BrowserWindow` dessus. Fermeture window → `stopBackend()` kill le subprocess. Phase B : `npm run build` bundle Chromium + `dist/DerushTool.exe` PyInstaller en un seul exe portable (~280 MB), configuré via `extraResources` dans `package.json`.

## Scripts utilitaires — détails complets des scripts one-shot

- `_patch_gopro_proxy.py` : one-shot, patche les `proxy_url` GoPro dans le JSON projet pour pointer sur les LRV (évite un rescan complet).
- `_patch_fx6_proxy.py` : one-shot DRIFT_CLUB : les proxys caméra FX6 (`Sub/`) ont été re-transcodés sans le suffixe Sony `S03` → tous les FX6 affichaient « vidéo introuvable ». Réécrit `proxy_url` `Sub/<stem>S03.MP4` → `Sub/<stem>.MP4` pour les 225 clips FX6, uniquement si le fichier cible existe. Ne touche qu'à `proxy_url` — pas aux IDs, aux `notes`, ni à `ltc_tc_in_sec` (contrairement à un rescan qui régénère `clips[]` et efface le LTC décodé). Sept. 2026.
- `fs5_fix_timecode_resolve.py` : one-shot DRIFT_CLUB, script Console DaVinci Resolve — réécrit le Start TC des 127 rushes FS5 (clés `<dossier jour>/<fichier>`) avec le vrai timecode décodé du LTC audio par Derush (`ltc_tc_in_sec`), le TC interne FS5 étant faux. Démarre en `DRY_RUN=True`. Se lance sur les clips du Media Pool DaVinci (pas via Derush), avant l'Auto Sync Audio Based on Timecode. Piège vécu : sur un projet où la timeline picture est DÉJÀ montée/conformée sur l'ancien TC, changer le Start TC fait passer les clips *Media Offline* + reconform lent → Resolve peut freezer/crasher. Dans ce cas, synchro waveform ou set du Start TC clip par clip. `fs5_revert_timecode_resolve.py` répare le cas offline.
- `check_proxy_links_resolve.py` : diagnostic (lecture seule) DRIFT_CLUB : parcourt tout le Media Pool DaVinci via l'API de scripting et liste les clips dont le champ `Proxy Media Path` ne correspond pas au clip lui-même (même stem attendu, `Clip/<stem>.MXF` → `Sub/<stem>.mp4`). Trouvé sept. 2026 : 131 clips sur 429 mal liés, `Proxy Media Path` pointant vers le MXF plein résolution d'un autre clip/jour — cause : `Link Proxy Media` lancé en recherche "comprehensive" sur plusieurs rushs à la fois, qui a mal apparié une partie des clips. Contamine en cascade l'Auto Sync Audio Based on Timecode (qui synchronise correctement, mais sur le TC du mauvais média lié). Voir piège #38.
- `check_tc_collisions_resolve.py` : diagnostic permanent (lecture seule) : parcourt tout le Media Pool DaVinci et liste (1) les paires de WAV dont la plage de TC se recouvre entre journées différentes, (2) les noms de fichiers (vidéo ou audio) portés par plusieurs clips, (3) tous les clips dont la plage de TC contient un timecode `CIBLE` configurable. Origine : script d'audit externe, adapté à la connexion `dvr.scriptapp('Resolve')` de ce projet + corrigé d'un bug trouvé en marchant dessus (14 sept. 2026) : la propriété `Frames` de l'API est VIDE sur les clips audio dans cette version de Resolve, donnant `end == start` pour tout WAV et masquant 100% des collisions (`End TC`, fiable sur les deux types de clip, est la source utilisée maintenant). Sur `DRIFT_CLUB` (641 clips) : 481 paires de recouvrement WAV inter-journées, et le TC de départ réel de `2-6T02.WAV` (audio attendu par `Clip0008.MXF`/J11) est aussi couvert par 4 autres fichiers de 4 autres journées — preuve empirique de la piste de collision pour le mystère du mauvais son. Voir `D:\METHODOLOGIE_IMPORT_RUSHS_DAVINCI.md` §22.

## Piège #37 — saga complète : décodeur LTC en avance d'une frame

Avant de conclure qu'un mécanisme externe (ici : la reconnaissance d'asset de DaVinci) est intrinsèquement imprévisible, épuiser les facteurs confondants qu'on contrôle soi-même — et utiliser TOUS les outils d'investigation disponibles, pas seulement le raisonnement depuis l'extérieur. Saga TC LTC des FS5 dans l'export (`_clip_asset_tc_sec`, `derush_exports.py` + décodeur `_ltc_decode_pcm`, `derush_server.py`), en 3 temps :
1. **v0.3.85 → 0.3.86** : LTC embarqué sans Media Pool corrigé en parallèle → rejet massif → revert (TC brut partout).
2. **v0.3.87 → 0.3.88** : LTC ré-embarqué avec Media Pool corrigé → une partie des FS5 quand même hors ligne, périmètre en apparence dispersé/imprévisible → conclusion hâtive « le mécanisme interne de DaVinci est trop opaque, abandon définitif ». **Prématuré** : en creusant `davinci_resolve.log` (`%APPDATA%\Blackmagic Design\DaVinci Resolve\Support\Logs\`, accessible directement sur disque sans permission spéciale), un clip **GoPro** jamais concerné par le LTC échouait à l'identique → Media Pool **incomplet** (médias de certains jours jamais importés), pas une question de précision. Restauré en v0.3.89.
3. **v0.3.90 — résolution** : Media Pool complété + testé proprement, 23 clips FS5 encore hors ligne sur 228. Plutôt que deviner depuis l'extérieur, connexion directe à l'**API de scripting DaVinci** (`DaVinciResolveScript`, module Python bundlé avec Resolve) pendant que le projet était ouvert : liste exhaustive des items timeline sans `GetMediaPoolItem()` lié (= offline), croisée avec le FCPXML importé (pour lever l'ambiguïté des noms de fichiers répétés sur plusieurs jours) et avec le Start TC réel de chaque clip dans le Media Pool. Résultat : **22 des 23 clips montraient un écart IDENTIQUE d'exactement +1 frame**, toujours dans le même sens — un bug systématique et déterministe dans `_ltc_decode_pcm`, pas un problème de matching DaVinci. Corrigé par calibration (`-frame_period` sur la valeur retournée). Le seul vrai outlier (+118 frames) était un échec du décodage LTC de Resolve lui-même sur CE clip précis (retombé sur le TC brut), cas distinct et sans rapport.

**Leçons** : (a) un log applicatif tiers accessible sur disque peut trancher en minutes ce que des heures de déduction (calculs de frames, comparaisons manuelles clip par clip, hypothèses sur des motifs jour/caméra/canal) ne résolvaient pas — chercher les logs de l'appli concernée est un réflexe à avoir tôt, pas en dernier recours. (b) Une API de scripting officielle de l'appli tierce (ici Resolve) permet d'obtenir des données exactes et exhaustives (tous les clips, tous les TC réels) là où on ne pouvait avant que demander à l'utilisateur de copier 2-3 valeurs à la main — un changement d'échelle qui a permis de voir un pattern invisible sur un petit échantillon. (c) Un écart mesuré comme "aléatoire"/"imprévisible" sur 2-3 exemples peut se révéler parfaitement déterministe une fois mesuré sur un échantillon assez large — ne jamais généraliser une conclusion de non-fiabilité depuis 2 points de données.

## Piège #38 — saga complète : Link Proxy Media qui lie le mauvais fichier

`Link Proxy Media` en recherche "comprehensive" sur DaVinci peut associer le mauvais fichier comme proxy — jusqu'au MXF plein résolution d'un AUTRE clip/jour, pas juste un mauvais fichier `Sub/`` (retour terrain sept. 2026, `DRIFT_CLUB` : « le clip mai0213 correspond à un autre plan... le son ingé associé est celui de mai0177 »). Enquête menée par élimination sur les vraies données AVANT de conclure (piège #37 encore applicable) : `clip['id']` inclut le jour (aucune collision sur 428 clips), les fichiers `Sub/*.MP4` de Derush ont la bonne durée, aucune collision d'UMID (`material_package_umid`/`file_package_umid`, exposés par `ffprobe -show_entries format_tags=material_package_umid` — plus fiable que le sidecar XML qui peut diverger). La vraie cause, confirmée par le témoignage utilisateur : un `Link Proxy Media` fait en une fois sur plusieurs rushs de plusieurs jours, avec la recherche étendue ("comprehensive search") proposée par Resolve quand il ne trouve pas de correspondance directe — cette recherche élargie confond des fichiers de jours différents avec des noms/motifs similaires (`Clip0001.MXF` répété sur 8 jours pour les FS5, mais aussi des FX6 `DRIFT_avril00XX`/`DRIFT_MAI0XXX` pourtant à noms uniques). Une fois le mauvais lien établi, **contamination en cascade** : *Auto Sync Audio Based on Timecode* ne se trompe pas en soi, il synchronise correctement sur le TC du média *actuellement lié* — sauf que ce média est celui du mauvais clip, donc le son ingé récupéré est réellement celui qui correspond à ce mauvais TC.

**Diagnostic** : `check_proxy_links_resolve.py` — lecture seule via l'API de scripting, compare `GetClipProperty()['Proxy Media Path']` au nom du clip lui-même sur tout le Media Pool. Sur `DRIFT_CLUB` : **131 clips sur 429** mal liés (FS5 et FX6 confondus — cohérent avec une cause côté algorithme de matching de Resolve, pas côté métadonnées caméra spécifiques à un modèle).

**Piège d'API découvert en essayant de corriger automatiquement** : `MediaPoolItem.LinkProxyMedia(path)` ne permet PAS d'établir un nouveau lien différent de l'existant — testé avec chemin absolu, slashes avant/arrière, avec et sans `UnlinkProxyMedia()` préalable : échoue systématiquement (`False`) dès que le chemin cible diffère de l'actuel, y compris vers un fichier valide et vérifié sur disque. Ne réussit (`True`) qu'en no-op, relier un clip au chemin qu'il a déjà. **Pas de correctif automatisé fiable par ce biais** — abandonné plutôt que de risquer d'aggraver un projet en cours d'édition. `UnlinkProxyMedia()` fonctionne bien en revanche (clip retombe sur lecture plein résolution, un état plus sûr qu'un mauvais lien même sans proxy rapide).

**Remède recommandé** : dans l'UI DaVinci, `Relink Proxy Media` (pas `Link Proxy Media` initial) scopé sur **UN SEUL dossier `Sub/` d'UN SEUL jour à la fois**, en recherche exacte (pas "comprehensive") — élimine le risque de confusion inter-jours en restreignant le champ de recherche.

## Piège #39 — saga complète : Auto Sync Audio associe le son du mauvais jour

`Auto Sync Audio Based on Timecode` peut associer le son d'un AUTRE JOUR, même avec un proxy et un Start TC corrects — le timecode SMPTE ne code que l'heure (HH:MM:SS:FF), **jamais la date**, il se répète à l'identique chaque jour. Si le bin de son ingé sélectionné pour l'opération contient des WAV de **plusieurs journées**, tout fichier d'un autre jour dont l'heure d'enregistrement coïncide par hasard avec celle du bon jour devient un candidat ambigu pour DaVinci — qui n'a aucun moyen de distinguer les jours. Confirmé par comparaison des `TimeReference` BWF réels (`ffprobe -show_entries format_tags=time_reference`, à diviser par la fréquence d'échantillonnage) : sur `DRIFT_CLUB`, `MIROIRT03.WAV` (J01, le bon fichier) couvre 16:19:25→16:26:17, quasiment identique à la fenêtre du clip `DRIFT_avril0004` (16:19:24→16:26:34) — mais `GABBERT12.WAV` (**J03**, un tout autre jour) couvre 16:13:20→16:25:12 et `REC-B-001.WAV` (**J02**) couvre 16:15:36→16:33:24, chevauchant TOUS LES DEUX cette même fenêtre par pur hasard. Le réglage Préférences "Limit media pool audio sync to first timecode match" atténue (moins de canaux ajoutés par clip, ex. 21→14 mesuré) mais ne résout pas le fond du problème si plusieurs jours restent mélangés — le "premier match" n'est pas forcément le bon jour.

**Piège d'API supplémentaire découvert en cherchant un correctif** : `MediaPool.UnlinkClips([item])`, tenté pour casser une association audio à tort, a mis le clip **hors ligne** (`Media Offline`) au lieu de rompre juste le couplage audio — pas la fonction espérée. Récupéré par un simple **Ctrl+Z** (confirmé fonctionnel). `SetClipProperty('Start TC', ...)` en revanche est une écriture fiable (déjà utilisée par `fs5_fix_timecode_resolve.py`) et a permis de corriger un Start TC resté faux en cache après le mauvais lien proxy (`25:57:32:02` au lieu du vrai `16:19:24:19`, vérifié `ffprobe`) — mais corriger le Start TC seul **n'a pas suffi** à corriger l'audio tant que le Media Pool restait par ailleurs contaminé (jours mélangés) : le fix définitif est de repartir d'un import propre, scopé par jour, plutôt que de patcher un projet déjà pollué.

**Tentative de réorganisation du disque en dossiers par jour (liens symboliques) abandonnée** : le disque `D:\` est en **exFAT**, qui ne supporte ni les jonctions NTFS (`mklink /J`) ni les liens symboliques — limite dure du système de fichiers, pas des droits. Aucun contournement sans reformater (jamais envisagé sur des rushs originaux). L'organisation en **bins par jour dans le Media Pool DaVinci lui-même** (un bin `J0X` contenant des sous-bins `FS5`/`FX6`/`GOPRO`/`SON` de ce jour uniquement) obtient le même bénéfice de scoping sans toucher au disque — solution finale adoptée.

**Remède validé de bout en bout** (12 sept. 2026, confirmé par le monteur sur l'ensemble du projet) : organiser le Media Pool en bins par jour, puis faire **Link Proxy Media, correction TC FS5, et Auto Sync Audio strictement un jour à la fois** (jamais plusieurs jours mélangés dans une même opération) — plus de média offline, plus de son mal associé, sélection FCPXML exacte. Procédure complète, avec le détail jour par jour, dans `D:\METHODOLOGIE_IMPORT_RUSHS_DAVINCI.md` (§8-9 et étapes 1/2/4 de la procédure).

## Piège #40 — saga complète : silence audio résiduel sur certains clips FX6 (piste ouverte, non confirmée)

ABANDONNÉ (13 sept. 2026), piste ouverte non testée — silence audio résiduel sur certains clips de la timeline "Panier" malgré des données 100% correctes. Suite du piège #39 sur `DRIFT_CLUB` : même après la procédure "un jour à la fois" validée, quelques clips (ex. `DRIFT_MAI0217`, FX6, J11) restent silencieux sur cette timeline précise alors que TOUT est vérifié correct : lien proxy (`Proxy Media Path` pointe bien sur son propre fichier — piège #38 écarté), aucun canal `mute:true` dans `GetAudioMapping()`/`track_mapping` (MediaPoolItem et TimelineItem), `linked_audio` pointe vers le bon WAV ingé avec le bon `offset`, structure de mapping strictement identique (juste plus de canaux liés : 7 au lieu de 1-4) à des clips FX6 sains de la même timeline. Reproduit de façon isolée et déterministe : réinjecter CE clip en tête d'un FCPXML minimal entouré de clips sains donne EXACTEMENT le même résultat (lui seul reste muet) — élimine taille de lot, ordre d'import, et FCPXML comme causes.

**Nouvelle piste (retour terrain, non vérifiée par API — la donnée pertinente n'est pas exposée par le scripting Resolve)** : la piste audio timeline concernée est en format **Adaptive 36 canaux**. Par défaut, seuls les canaux 1-2 d'une piste Adaptive sont réellement patchés vers le bus de sortie Main dans Fairlight ; les canaux au-delà (3 à 36) peuvent porter du son bien réel sans jamais être routés vers la sortie tant qu'ils ne sont pas explicitement patchés. Sur `DRIFT_MAI0217`, Clip Attributes → Audio montre que le son occupe les canaux **9 à 15** de cette piste (pas 1-2) — cohérent avec un silence de sortie malgré une donnée saine en amont. Hypothèse non encore confirmée/infirmée en conditions réelles au moment de la rédaction (utilisateur a reporté le test).

**2 remèdes à tester, par ordre de rapidité** : (a) dans Clip Attributes → Audio du clip affecté, réassigner directement le(s) canal/canaux source vers la cible 1/2 au lieu de 9-15 — le plus rapide, clip par clip ; (b) menu **Fairlight → Patch…** (fenêtre dédiée de matrice de routage Track→Bus→Sortie physique, distincte du mixeur standard) pour patcher les canaux 9-15 de la piste vers Main — si ça marche, corrigerait potentiellement TOUS les clips touchés d'un coup plutôt qu'un par un.

**Pourquoi ça expliquerait aussi le seul fix manuel connu jusqu'ici** (mute canal 1 → démute → OK dans Clip Attributes, piège documenté avant sept. 2026) : cette manip pourrait, en pratique, réinitialiser l'assignation de canal cible du clip vers 1-2 par défaut plutôt que de vraiment "réparer" un mute — cohérent avec le fait que ça marchait clip par clip mais jamais en masse (une édition en masse de Clip Attributes ne réinitialise pas forcément l'assignation de canal cible de la même façon pour tous les clips, selon leur nombre de canaux liés).

**Contexte** : l'utilisateur envisage de tester DaVinci Resolve **v21** sur ce projet pour voir si ce comportement d'assignation de canal/patch a changé. Si le remède (a) ou (b) fonctionne avant ça, documenter ici lequel et mettre à jour `D:\METHODOLOGIE_IMPORT_RUSHS_DAVINCI.md`.

## Piège #41 — saga complète : mystère Clip0008.MXF/J11, résolution par changement de mécanisme

Mystère `Clip0008.MXF`/J11 (« bon nom affiché, mauvais son joué ») — mécanisme démontré, résolu par un changement de mécanisme d'export, pas par un correctif (14 sept. 2026). Après une autocritique méritée de l'utilisateur (« tu boucles sur les mêmes problèmes ») sur des cycles de correctifs adjacents détectables par relecture statique (validateur AAF) qui ne pouvaient mécaniquement pas expliquer un symptôme de résolution DaVinci↔Media Pool, la bascule vers des **tests d'intervention directe** (retirer des fichiers concurrents un par un, comparer des mécanismes de construction sur la MÊME timeline) a débloqué le dossier :
- **Mécanisme démontré** : pour les mobs SON (pas image), DaVinci résout un AAF importé par **timecode seul, jamais par nom de fichier** — preuve par suppression en cascade des 4 fichiers concurrents sur le TC de `2-6T02.WAV` (le son entendu change à chaque suppression, le nom affiché jamais), confirmé même sur un AAF natif exporté par Resolve lui-même. L'image (MXF) reste fiable malgré des collisions de nom identiques grâce à son UMID gravé dans le fichier.
- **Piste Reel Name/TapeMob testée, infirmée** : DaVinci ne la consulte pas à l'import AAF pour l'audio.
- **Piste API `AppendToTimeline`** : ne pose jamais qu'un seul canal, quels que soient les paramètres (`AppendClipInfo` n'a pas de sélecteur de canal source, seulement `trackIndex` = piste de DESTINATION).
- **Solution retenue : `MediaPool.CreateTimelineFromClips` + export DRT natif** (`export_drt`, `derush_drt.py`). Contrairement à `AppendToTimeline`, calcule un `FieldsBlob` distinct et correct par canal ; la lecture EN DIRECT de cette même timeline dans Resolve reste muette (bug distinct, sans incidence puisqu'on exporte puis réimporte, jamais d'écoute en direct).
- **Symptôme caméra désolidarisé** : le silence caméra sur `Clip0008` persiste même sous glisser-déposé manuel (le procédé de référence le plus fiable) → confirmé indépendant de tout mécanisme d'export/construction testé. Sujet Media Pool/projet à part entière, probablement lié à `DRIFT_MAI0217`/`DRIFT_MAI0237` (piège #40), **hors du périmètre qu'aucun export Derush Tool ne peut corriger.**
- Détail complet (tests, données, scripts) dans `D:\METHODOLOGIE_IMPORT_RUSHS_DAVINCI.md` §21-26.

## Piège #47 — export DRT cassé sur Mac + matching clip trop strict (27 sept. 2026)

Question de l'utilisateur (« est-ce que ça marche aussi sur Mac ? As-tu pris en compte les différences de chemins/API ? ») a servi de déclencheur à un audit du module `derush_drt.py`, pas encore testé en conditions réelles sur Mac. Deux problèmes trouvés par relecture :

1. **`_RESOLVE_API_PATHS` (dossier `Scripting`, contient les bindings Python de l'API) ne listait que le chemin Windows.** `_RESOLVE_LIB_PATHS` (la lib `fusionscript.dll`/`.so`) avait bien les deux OS, ce qui masquait l'oubli à une relecture rapide — sur Mac, `_connect_resolve` ne trouvait jamais `RESOLVE_SCRIPT_API` automatiquement et l'export échouait avec « DaVinci Resolve introuvable sur cette machine », même Resolve lancé et le bon projet ouvert. Chemin standard Mac ajouté : `/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting`.
2. **Question de fond posée par l'utilisateur** : « si je n'ai pas des dossiers bins avec les jours dans Resolve, ça ne fonctionnera pas ? » — `_find_media_pool_item` exigeait un code jour (`J02`, `J11`...) comme segment de bin EN PLUS du nom de fichier, une convention propre à ce tournage (racine du script utilitaire `link_timeline_clips_resolve.py` etc., héritée du contexte FS5/collisions inter-jours du piège #38/#41). Sur un futur projet sans cette organisation en bins par jour, l'export échouait systématiquement avec « Clip introuvable », alors même que le clip existe bel et bien dans le Media Pool. Assoupli : matching par nom de fichier seul d'abord (couvre le cas courant, filename unique dans tout le Media Pool) ; le jour ne sert plus qu'à désambiguïser si plusieurs items partagent le même nom — garde la même philosophie « erreur explicite plutôt que deviner » en cas d'ambiguïté irréductible.

Le reste du module (`_find_media_pool_item`, `CreateTimelineFromClips`, `_fix_clip_linking`, etc.) ne résout jamais de chemin de fichier local — le rattachement se fait entièrement par identité live du `MediaPoolItem` retrouvé dans le Media Pool ouvert, donc déjà robuste aux différences Windows/Mac de lettres de lecteur vs `/Volumes/...`. Pas de test réel effectué sur une machine Mac à cette date — fix par lecture de code + connaissance des chemins standards Blackmagic, à confirmer par un export réel sur Mac dès que possible.
