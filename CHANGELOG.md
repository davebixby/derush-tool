# Changelog

Toutes les évolutions notables de Derush Tool. Format inspiré de [Keep a Changelog](https://keepachangelog.com/fr/).

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
