# Changelog

Toutes les évolutions notables de Derush Tool. Format inspiré de [Keep a Changelog](https://keepachangelog.com/fr/).

---

## [0.3.13] — 2026-07-26

### 🐛 Corrigé
- **Comparateur — reprise sur une position obsolète** : ouvrir ⚡ Comparer chargeait le slot gauche avec la dernière position mémorisée d'une session comparateur précédente sur ce clip (ex. 3/4 de la timeline), au lieu de la position réelle en cours dans le lecteur principal. Ouvrir Comparer synchronise désormais le slot 0 sur l'endroit exact où était le lecteur principal.
- **Comparateur — barre de progression figée** : charger un nouveau clip dans un slot pouvait laisser la barre de progression affichée à la position du clip précédent tant qu'aucun `timeupdate` n'avait refiré (typiquement un clip qui démarre à 0 et reste en pause). La barre et le TC sont désormais réinitialisés immédiatement au chargement.

### ✨ Ajouté
- **Miniatures dans le sélecteur de clips du comparateur** : le menu déroulant de chaque slot affiche désormais une vignette devant chaque nom de fichier pour repérer les clips plus facilement. Remplace le `<select>` natif par un combo custom (le `<select>` est gardé caché comme source de vérité pour le reste du code).

---

## [0.3.12] — 2026-07-26

### ✨ Ajouté
- **Reprise de la position de lecture par clip** : quitter un clip en cours de lecture (dans le lecteur principal, un slot du comparateur, ou le viewer multicam) puis y revenir replace la tête de lecture là où elle avait été laissée, au lieu de repartir du début. Mémorisation en mémoire pour la session en cours (`_clipResumeTime` par `clip.id`, `_mcGroupResumeTime` par groupe multicam) — pas de persistance entre relances de l'app.

---

## [0.3.11] — 2026-07-26

### 🐛 Corrigé
- **Perte de clips au rescan** (grave) : un scan lancé avec un chemin de rushs momentanément invalide (ex. lettre de lecteur d'un disque externe qui a changé) ne trouvait aucun fichier et **écrasait silencieusement** la liste de clips existante du projet — 428 clips perdus en un clic dans un cas réel. `POST /api/project/<pid>/scan` refuse désormais d'appliquer un résultat qui contiendrait moins de la moitié des clips existants (HTTP 409, rien n'est modifié) ; il faut relancer explicitement avec `force:true` pour confirmer un vidage volontaire. Le bouton 🔄 Rescanner du frontend affiche l'avertissement en toast et permet de forcer en recliquant dans les 15 secondes — aucun `confirm()` natif utilisé (cf. bug focus Electron déjà connu).

---

## [0.3.10] — 2026-07-26

### 🐛 Corrigé
- **Timeline invisible en plein écran** : `⤢ Plein écran` ne mettait en fullscreen que la vidéo elle-même (`#videoWrapper`) — la barre de transport et la timeline (avec les marqueurs) restaient en dehors et disparaissaient. Un nouveau conteneur (`#playerFsWrap`) englobe désormais la vidéo + la barre de contrôle + la timeline, donc les marqueurs restent visibles et cliquables en plein écran. Le comparateur avait déjà ses marqueurs sur la timeline de chaque slot (`renderCmpMarkers`) — si un exécutable installé ne les affiche pas, c'est probablement un build antérieur à cette fonctionnalité, pas un bug du code actuel : redéployer depuis les sources courantes.

### 🎨 Interface
- **Bouton 💾 Sauver** déplacé de la barre d'outils flottante vers la barre du bas (`player-controls`), à côté du statut de sauvegarde — toujours visible sans ouvrir la colonne d'icônes.

---

## [0.3.9] — 2026-06-04

### 🎨 Interface
- **Réorganisation des contrôles du lecteur** : la barre du bas ne garde plus que la lecture (timer, sauts, ⏯, vitesses 1×→2×). Tous les outils (Comparer, Cadre, LUT, Multi-cam, Session, Exporter, Partager, Santé, Stats, Sync, Sauver) passent dans une **barre d'icônes verticale flottante** en haut à droite de la vidéo.
- **Cadre / format appliqué partout** : le format choisi (4:3, 2.39:1…) s'applique maintenant aussi dans le **comparateur** (les deux clips) et dans le **viewer multi-cam** (tous les angles), pas seulement sur le lecteur principal.
- **Comparateur — hauteurs égales** : les deux clips s'affichent désormais exactement à la même taille (colonnes forcées égales via `min-width: 0`, affichage `object-fit: contain`).
- **Bandes noires incrustées rognées automatiquement** : les rushs tournés avec un cache cinéma baké dans l'image (ex. matte 1.9:1 des FX6 du J01) sont détectés (ffmpeg côté serveur) et affichés **sans les bandes**, dans le lecteur, le comparateur et le multi-cam. Une FX6 mattée s'aligne donc en hauteur avec une FS5 plein cadre. Le cadre/format (4:3, 2.39:1…) se cale aussi sur l'image réelle.

### 🐛 Corrigé
- **Sync en cours de session** : les notes et commentaires des autres collaborateurs apparaissent maintenant automatiquement (en ≤ 60 s) sans avoir à cliquer sur « Synchroniser » ni à rouvrir le projet. Le rafraîchissement automatique faisait jusqu'ici une simple relecture locale ; il déclenche désormais un *pull* léger depuis le cloud.
- **Cadre / format d'image** : le cadre se délimite désormais sur l'**image réelle**. Si un rush a des bandes noires incrustées (master letterboxé), un format comme 4:3 ne calera plus son haut/bas dans ces bandes — il les détecte et s'aligne sur l'image visible.

### 🏗️ Interne
- `sync_project(pid, push=False)` : mode *pull-only* (ramène + fusionne sans renvoyer vers le cloud), n'écrit le fichier projet que si la fusion change réellement quelque chose (plus de rotation inutile des backups locaux).
- Nouvel endpoint `POST /api/sync/pull`.
- Détection client-side des bandes noires incrustées (`_detectContentInsets` / `_contentInsets` par clip, accumulation du minimum, seuil luma 24).

---

## [0.3.8] — 2026-06-01

### ✨ Ajouté
- **Mode sombre / clair** : bouton 🌙/☀️ dans la sidebar header, toggle persisté en localStorage.
- **Jauge de progression par utilisateur** : petites barres sous le badge utilisateur montrant combien de clips chaque collaborateur a annotés (ex. Paola 45/200).
- **Filtres sauvegardés (smart bins)** : bouton "+ Sauver" qui apparaît dès qu'un filtre non-défaut est actif. Les presets sont nommés automatiquement (⭐⭐⭐ · 📷 FX6 · 📅 J04), stockés par projet en localStorage, et rappelés par un clic.
- **Notifications @mention** : si un collaborateur écrit `@Sébastien` dans une discussion de marker, une notification desktop s'affiche (demande de permission au premier chargement d'un projet). Fonctionne via WebSocket temps réel et polling.

---

## [0.3.6] — 2026-05-22

### 🔒 Stabilité & sécurité (audit technique)
- **Verrou par projet** : fin des écritures concurrentes qui pouvaient s'écraser entre elles (perte d'annotations).
- **Écriture atomique** des fichiers projet (`.tmp` + `os.replace`) : plus de fichier tronqué en cas de crash.
- **Hachage des mots de passe en PBKDF2** salé (au lieu de SHA-256 nu), migration transparente au login.
- **Anti-brute-force** sur le login (429 après trop d'échecs) ; **expiration** des liens de review (30 j).
- Réponse 500 propre sur erreur serveur ; clé de sync transmissible par en-tête HTTP.

### 🐛 Corrigé
- **Sync** : une suppression de marqueur ne « revient » plus (chaque machine ne publie que ses propres notes).
- **Marqueur perdu** après synchronisation : alignement de la clé de notes entre UI, serveur et export.
- L'utilisateur ne se voit plus lui-même dans « Avis des autres ».
- Barre de génération des aperçus : va jusqu'au bout au lieu de rester bloquée.
- Export FCPXML : timeline complète (fin du dédoublement de clés de notes).

### 🏗️ Interne
- Cache de chargement des projets, indexation FTS debouncée.
- Découpage du serveur en modules (`derush_core`, `derush_exports`) ; tests unitaires Python.

---

## [0.3.5] — 2026-05-19 (soir)

### ✨ Ajouté
- **Support Mac Apple Silicon** (arm64) : `derush.spec` cross-platform, `build_mac.sh` auto-vérificateur, `BUILD_MAC.md` guide complet français, script bash qui vérifie Xcode CLT/Homebrew/Python/Node/ffmpeg et compile le `.app` + zip distribuable.
- **Résolveur de chemins tolérant** : `_resolve_relpath_tolerant()` walk segment par segment avec variantes numériques (`01↔1↔001`) et case-insensitive. Fix le cas SSD copié entre PCs où les noms de slot perdent leur zéro de tête.
- **Skeleton shimmer + barre de progression** des thumbnails : feedback visuel pendant la génération initiale (5+ min sur fresh install). Compteur dédoublonné « X / 428 aperçus prêts ».
- **Spinner sur le player vidéo** + écran d'erreur explicite (chemin demandé + code HTTP) si le proxy est introuvable.
- **Placeholder ⚠ rouge** sur les vignettes en 404 (au lieu de l'icône image-cassée du browser).
- **Bouton 📁 Parcourir** dans le setup wizard pour pointer le dossier projets via dialog natif.
- **Messages d'erreur sync clairs** : « Clé sync incorrecte », « Aucun projet trouvé », « Serveur injoignable » au lieu des codes HTTP bruts.
- **Distribution zip Windows** (au lieu de portable .exe auto-extractible) : démarrage 3–5s au lieu de 1 min.

### 🐛 Corrigé
- **Tombstone bug** : un user supprimé puis re-créé disparaissait à chaque sync car le tombstone le re-filtrait. Fix dans `authorize_user` (lift local) et `merge_projects` (un user vivant en local lève le tombstone globalement).
- **URL encoding sync** : crash `URL can't contain control characters` quand le pid contient un espace. Fix `_urlquote()` + validation locale `re.match(r'^[a-zA-Z0-9_\-]+$')`.
- **tkinter folder picker sur Mac** : hangue silencieux car tkinter doit tourner sur le main thread. Remplacé par `osascript` natif macOS (NSOpenPanel via AppleScript). Windows garde tkinter.
- **« Rejoindre un projet » sur la page de login** : retiré (contre-intuitif, on ne peut pas rejoindre sans être connecté). Reste visible uniquement après login.
- **403 « Accès refusé » silencieux** sur set_root_path : message diagnostique explicite (« L'utilisateur X n'est pas inscrit sur ce projet. Users actuels : … »).

---

## [0.3.0] — 2026-05-19

### ✨ Ajouté
- **Auto-détection de plans** : bouton 🔍 Auto-plans qui scanne les rushs via ffmpeg scene change et propose des markers candidats. Clic gauche = accepter, droit = rejeter.
- **Session live** : un utilisateur peut diriger la session et ses actions (clip select, seek, play/pause) sont diffusées aux autres en temps réel via WebSocket. Bouton 🎬 Diriger / 👁 Suivre.
- **Édition collaborateurs** : bouton ✏️ dans la gestion utilisateurs pour modifier rôle, couleur, ou régénérer une clé d'invitation perdue.
- **Stats dashboard** 📊 : modal avec cards totaux, progression %, distribution ratings/markers/caméras/jours, top tags, activité par utilisateur.
- **Modal À propos** ℹ️ : logo + version + liens GitHub/Releases/Guide.
- **Splash window amélioré** : logo embarqué + animation breath + barre progress, fond gradient.
- **Icône taskbar Electron** : icône custom dans la barre Windows + barre titre.

### 🐛 Corrigé
- **Auto-détection 0 candidats** : `-loglevel info` masquait les lignes showinfo de ffmpeg → 0 résultats. Passé à `verbose` + regex stricte pour éliminer le faux positif à t=0 venant du log graph.
- **Bouton 🔑 invite key cassé** : `JSON.stringify(uname)` dans attribut HTML double-quoted → guillemets imbriqués → onclick invalide. Fix : attribut single-quoted.

### 🧪 Stabilité
- **Tests E2E auto-detect + session-live** : 9 tests supplémentaires (Playwright), total 23/23 passants.

---

## [0.2.0] — 2026-05-19

### ✨ Ajouté
- **Son ingé sur player single** : bouton 🔊 Son ingé qui apparaît automatiquement quand un BWF couvre le clip. Sync TC parfait avec le video. Cohérent visuellement avec celui du multicam (vert éclatant = ingé / barré = caméra).
- **BWF multipistes** : downmix WebAudio API de toutes les pistes (jusqu'à 8) vers stéréo. Tu entends toutes les pistes mélangées au lieu des 2 premières seulement.
- **Lien de review partageable** : bouton 🔗 Partager → URL publique unique qui montre annotations + 4 previews HD 640×360 par clip + formulaire commentaires. Pas besoin d'installer quoi que ce soit côté client/réal.
- **Retours externes** : les commentaires postés via le lien partagé arrivent dans Derush, affichés sous chaque clip dans la section "🔗 Retours externes".
- **Crash reporter** : capture des exceptions Python + JS, journal `%APPDATA%\DerushTool\crashes.jsonl`, viewer "🐞 Journal des erreurs" depuis l'écran projets.
- **Export Adobe Premiere XML** (Final Cut Pro 7 XML) : nouveau bouton dans le modal Export, supporte markers + ratings + zones X coupées.
- **LUT scoping par caméra** : à l'ouverture d'un .cube, popup pour choisir les caméras concernées (ou "ce rush uniquement"). Activation/désactivation auto selon le clip.
- **Réglages LUT** : panneau intensité (0-100%), exposition (-2/+2 EV), saturation (0-200%). Pipeline GPU expo→LUT→intensité→satu→dithering.
- **Dithering anti-banding** : bruit sub-pixel ±0.5/255 dans le shader LUT, casse les bandes visibles sur les ciels/dégradés sans perception consciente.
- **Sync cloud hardening** : pull au moment d'ouvrir un projet + push debounced 3s après chaque save (au lieu d'attendre 10 min).
- **Swap multicam** : bouton 🔄 Swap qui intervertit physiquement les emplacements gauche/droite des vidéos.
- **Login pré-rempli** : checkbox "Se souvenir de moi", credentials sauvegardés dans localStorage.

### 🎨 Amélioré
- **LUT preview** : passage Canvas 2D nearest-neighbour 480px → WebGL2 + sampler3D + interpolation trilinéaire HW pleine résolution. Plus de pixelisation ni de banding.
- **Timeline** : passe de 48 → 88px. Markers compacts (12×12) avec stacking vertical anti-overlap (3 niveaux). Chaque pin reste cliquable même en cluster.
- **Shapes markers** différenciées : 1/2/3 cercle, T (problème image) carré, S (problème son) triangle, D (note) losange, X (à couper) croix.
- **Labels** : "Image"/"Son" → "Problème image"/"Problème son" (plus explicite).
- **4 previews HD share** : 640×360 lanczos q=3 (vs 320×180 fast_bilinear avant).
- **Splash window Electron** au démarrage avec barre de progression CSS pendant le boot du backend.
- **Scrollbar custom** fine violet translucide dans toute l'app.

### 🐛 Corrigé
- **Bug textarea popup marker** : `confirm()` natif cassait le focus state Chromium → textarea inéditable après suppression d'un marker. Tous les `confirm()` virés et remplacés par toast.
- **Bug saveDrawing** : `prompt()` désactivé dans Electron renvoyait null silencieusement → le bouton Valider ne créait pas le marker. Réutilise le popup marker existant.
- **Bug navigateur double** : le bundle PyInstaller ouvrait Firefox en plus d'Electron au démarrage. `--no-browser` honoré dans `derush_launcher.py`.
- **Bug ratio LUT** : `object-fit: contain` sur le canvas LUT pour matcher l'aspect du video.
- **Bug commentaires dupliqués share** : pull concurrent → N copies. Lock per-pid + dédoublonnage rétroactif.
- **Bug commentaire `since=None`** : comparaison alphanumérique `'2026-' <= 'None'` → tous les commentaires filtrés.
- **Bug scroll viewer share** : div #root sans flex/height → aside ne pouvait pas scroller.
- **Caret invisible** : textarea créée hors du popup display:none → Chromium n'initialisait pas le caret. Création maintenant après popup visible (double RAF).
- **Head timeline derrière waveform** : isolation stacking context + z-index head 20.

### ⚡ Performance
- **PyInstaller passage onefile → onedir** : startup quasi instantané au 2e lancement (cache portable). 226 MB → 183 MB.
- **Custom ffmpeg semaphore** : max 8 ffmpeg concurrents globaux, throttle interne `compute_strip` à 3 workers.
- **Dedup compute** : 2 requêtes simultanées sur même clip = 1 seul ffmpeg.
- **Waveform numpy-isé** : 10× moins RAM, 100× plus rapide.

---

## [0.1.0] — 2026-05-18

### 🎉 Première release portable
- Wrapper Electron + PyInstaller onefile (226 MB).
- Toutes les features de base : login, projets, scan, ratings, markers, drawings, tags, notes, exports DaVinci, sync cloud, multicam, BWF.
