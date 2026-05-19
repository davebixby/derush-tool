# Changelog

Toutes les évolutions notables de Derush Tool. Format inspiré de [Keep a Changelog](https://keepachangelog.com/fr/).

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
