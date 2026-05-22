# Derush Tool — Guide de build pour macOS

Ce guide te permet de produire un `DerushTool.app` natif pour Mac Apple Silicon
(M1, M2, M3) à partir des sources Windows. Tout se passe **sur le Mac**, pas
sur Windows : PyInstaller et electron-builder ne savent pas faire de
cross-compilation pour macOS.

**Cible** : Mac mini M1 (build) + MacBook Pro M2 (distribution du `.app`)

**Durée totale** : ~30 min la première fois (install des dépendances comprise),
~3 min pour les builds suivants.

---

## Sommaire

1. [Prérequis à installer une seule fois](#1-prérequis-à-installer-une-seule-fois)
2. [Récupérer les sources depuis Windows](#2-récupérer-les-sources-depuis-windows)
3. [Lancer le build](#3-lancer-le-build)
4. [Tester le .app sur le Mac mini](#4-tester-le-app-sur-le-mac-mini)
5. [Distribuer vers le MacBook Pro M2](#5-distribuer-vers-le-macbook-pro-m2)
6. [Workflow de mise à jour](#6-workflow-de-mise-à-jour)
7. [Dépannage](#7-dépannage)

---

## 1. Prérequis à installer une seule fois

Toutes les commandes vont dans **Terminal** (`/Applications/Utilities/Terminal.app`,
ou Spotlight `Cmd+Espace` → tape `Terminal`).

### 1.1 Xcode Command Line Tools

Indispensable pour compiler des modules Python natifs (numpy, Pillow).

```bash
xcode-select --install
```

Une popup apparaît → clique **« Installer »**. ~10 min de download. Si tu vois
« command line tools are already installed », c'est bon, passe à la suite.

### 1.2 Homebrew (gestionnaire de paquets Mac)

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

À la fin, le script te dit deux commandes à ajouter à ton PATH (style
`eval "$(/opt/homebrew/bin/brew shellenv)"`). Copie-colle-les **exactement comme
indiqué** dans le Terminal, puis ferme/rouvre Terminal.

Vérifie :
```bash
brew --version
```
Doit afficher `Homebrew X.Y.Z`.

### 1.3 Python 3, Node.js, ffmpeg

```bash
brew install python@3.11 node ffmpeg
```

~5 min de download + install. À la fin, vérifie :
```bash
python3 --version    # doit afficher 3.11.x
node --version       # doit afficher v20.x ou plus
ffmpeg -version      # doit afficher la version de ffmpeg
ffprobe -version     # idem
```

---

## 2. Récupérer les sources depuis Windows

Tu as plusieurs choix selon ce qui est dispo :

### Option A — Clé USB (recommandé)

Sur Windows, un script prépare le zip automatiquement. Dans PowerShell, depuis
le dossier source, lance :

```powershell
.\zip_for_mac.ps1
```

Il produit `derush_tool_mac_vX.Y.Z.zip` sur le Bureau, en excluant tout seul les
dossiers et binaires inutiles : `dist/`, `build/`, `electron/dist/`,
`electron/node_modules/`, `projects/`, les caches, et les `ffmpeg.exe` /
`ffprobe.exe` Windows (~300 Mo, recopiés depuis Homebrew côté Mac). Il garde
`electron/package-lock.json` (la recette pour réinstaller les bonnes versions).

Copie ce `.zip` sur la clé USB. Sur Mac, copie-le par exemple dans
`~/Documents/` et dézippe.

> **Zip à la main ?** Prends tout le dossier source **sauf** `dist/`, `build/`,
> `electron/dist/`, `electron/node_modules/`, `projects/` et les deux
> `ffmpeg.exe` / `ffprobe.exe`.

### Option B — AirDrop

Sélectionne le dossier source dans l'Explorateur Windows → clic droit → Envoyer
vers… (mais AirDrop n'est pas natif Windows, donc zip + clé USB est plus
simple).

### Option C — Git (si tu pousses un jour le repo)

```bash
cd ~/Documents
git clone https://github.com/ton-user/derush-tool.git derush_tool
```

### Vérification

Quel que soit le moyen, tu dois te retrouver avec un dossier `derush_tool/` qui
contient au minimum :
```
derush_tool/
├── derush_server.py
├── derush_launcher.py
├── derush_app.html
├── derush_setup.html
├── derush.spec
├── requirements.txt
├── VERSION
├── build_mac.sh         ← le script qu'on va lancer
├── electron/
│   ├── main.js
│   ├── package.json
│   └── …
└── js/
```

---

## 3. Lancer le build

Ouvre Terminal et navigue vers le dossier source :

```bash
cd ~/Documents/derush_tool
```

(adapte le chemin selon où tu as mis le dossier)

Rends le script exécutable (à faire **une seule fois**) :

```bash
chmod +x build_mac.sh
```

Lance le build :

```bash
./build_mac.sh
```

Le script va :
1. **Vérifier toutes les dépendances** et te dire quoi installer si quelque chose manque
2. **Copier ffmpeg/ffprobe** depuis Homebrew vers le projet (pour qu'ils soient bundlés)
3. **Générer l'icône .icns** depuis le PNG s'il manque
4. **Créer un environnement Python virtuel** (`.venv/`) pour ne pas polluer ton système
5. **Installer les packages Python** (pyinstaller, pystray, Pillow, numpy)
6. **Builder via PyInstaller** → produit `dist/DerushTool.app/`
7. **Builder via electron-builder** → produit `electron/dist/DerushTool-X.Y.Z-mac-arm64.zip`

À la fin, tu verras :
```
========================================================
  BUILD TERMINE
========================================================
OK Zip pret : /Users/.../derush_tool/electron/dist/DerushTool-0.3.5-mac-arm64.zip (250M)
```

**Premier build** : ~10 min (download/install des deps Python + Electron).
**Builds suivants** : ~2 min.

---

## 4. Tester le .app sur le Mac mini

### 4.1 Dézipper

Le `.zip` produit contient un `DerushTool.app`. Pour l'installer :

```bash
# Decompresse dans /Applications (necessite ton mot de passe Mac)
unzip electron/dist/DerushTool-0.3.5-mac-arm64.zip -d /Applications/

# Ou dezippe ailleurs si tu prefereres
unzip electron/dist/DerushTool-0.3.5-mac-arm64.zip -d ~/Desktop/
```

Tu peux aussi double-cliquer sur le `.zip` dans Finder → ça crée le `.app` à
côté.

### 4.2 Premier lancement — contourner Gatekeeper

L'app n'est **pas signée par Apple** (ça coûte 99$/an + procédure de
notarization). Au premier lancement Gatekeeper va dire « Impossible d'ouvrir,
développeur non identifié ».

**Méthode 1 — Clic droit (recommandée)** :
1. Dans Finder, **clic droit** (ou Ctrl+clic) sur `DerushTool.app`
2. Choisis **« Ouvrir »**
3. Popup → clique **« Ouvrir »** quand même

Cette autorisation est mémorisée : les lancements suivants se font normalement
par double-clic.

**Méthode 2 — Via Terminal (si la méthode 1 ne marche pas)** :
```bash
xattr -dr com.apple.quarantine /Applications/DerushTool.app
```
Puis double-clic normal.

### 4.3 Vérifier que ça marche

L'app doit :
1. Afficher le splash sombre avec le logo qui pulse
2. Démarrer le backend Python en arrière-plan
3. Ouvrir la fenêtre principale Chromium
4. Te montrer soit le setup wizard (premier démarrage) soit la page de login

Si tu vois une erreur « Backend introuvable », vérifie dans Terminal :
```bash
# Verifie que le binaire Python embarque tourne
/Applications/DerushTool.app/Contents/Resources/DerushTool/DerushTool.app/Contents/MacOS/DerushTool --no-browser
```
S'il sort un message clair, paste-le moi.

---

## 5. Distribuer vers le MacBook Pro M2

Une fois que tu as un `.zip` qui marche sur le Mac mini :

### 5.1 Copier le .zip

Options :
- **AirDrop** : clic droit sur le `.zip` dans Finder → Partager → AirDrop → MBP
- **iCloud Drive** : dépose dans `~/Library/Mobile Documents/com~apple~CloudDocs/`
- **Clé USB**
- **Câble USB-C direct** (target disk mode) ou via partage de fichiers

### 5.2 Installer sur le MBP

Sur le MBP :
1. Dézippe le `.zip` → glisse le `.app` dans `/Applications`
2. **Premier lancement** : clic droit → Ouvrir → confirme (même Gatekeeper que sur le Mac mini)
3. Si tu veux que ton équipe rejoigne le projet via sync, lance l'app, fais le setup, et utilise une clé d'invitation comme sur Windows.

---

## 6. Workflow de mise à jour

Quand tu modifies du code Windows et que tu veux re-builder Mac :

1. Sur Windows, zippe à nouveau le dossier source (en excluant `dist/`, `build/`, `node_modules/`, `.venv/`)
2. Sur Mac, supprime l'ancien dossier source et dézippe le nouveau, OU :
   - Copie juste les fichiers modifiés par-dessus (plus rapide si peu de changements)
3. Lance `./build_mac.sh` à nouveau

> ⚠️ **Ne supprime pas `electron/node_modules` ni `.venv`.** Si tu remplaces tout
> le dossier source, mets ces deux-là de côté et remets-les ensuite — sinon
> `npm install` se relance, et sur un réseau qui intercepte le HTTPS il rééchoue
> (voir § 7). Le plus sûr : ne réécris que les fichiers sources modifiés.

Le script garde le `.venv` et `electron/node_modules` entre les builds (gros gain de temps).
Pour partir vraiment de zéro :
```bash
rm -rf .venv electron/node_modules dist build
```

### Versioning

Le numéro de version est dans le fichier `VERSION` (1 ligne, format `X.Y.Z`).
Augmente-le avant chaque build qu'on distribue (le `.zip` aura le nouveau
numéro dans son nom).

Vérifie aussi `electron/package.json` (clé `version`) — il faut que les deux
soient cohérents. Le script Windows `build_windows.bat` (à venir) le fera
automatiquement.

---

## 7. Dépannage

### « xcrun: error: invalid active developer path »

Réinstalle Xcode CLT :
```bash
sudo xcode-select --reset
xcode-select --install
```

### Le script s'arrête avec « brew: command not found »

Homebrew n'est pas dans le PATH. Ajoute la ligne que brew t'a donnée à la fin de l'install dans `~/.zshrc` :
```bash
echo 'eval "$(/opt/homebrew/bin/brew shellenv)"' >> ~/.zshrc
source ~/.zshrc
```

### PyInstaller plante avec « lipo: can't open input file »

Tu as probablement un mix arm64/x86_64 dans tes binaires. Vérifie l'architecture de ffmpeg :
```bash
file $(which ffmpeg)
```
Doit afficher `Mach-O 64-bit executable arm64`. Si c'est `x86_64`, t'as installé un brew Intel sur ARM. Désinstalle et réinstalle :
```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/uninstall/master/uninstall.sh)"
# Puis re-installe Homebrew (point 1.2 ci-dessus)
```

### electron-builder échoue avec « code signing required »

Le script désactive le signing dans `package.json` (`"identity": null`). Si tu as
quand même cette erreur, force avec :
```bash
cd electron
CSC_IDENTITY_AUTO_DISCOVERY=false npm run build:mac
```

### `npm install` échoue avec `UNABLE_TO_GET_ISSUER_CERT_LOCALLY`

Le réseau (studio, entreprise) intercepte les connexions HTTPS et présente un
certificat que npm ne reconnaît pas.

`NODE_TLS_REJECT_UNAUTHORIZED=0` **ne suffit pas** : npm a son propre réglage
`strict-ssl` qui l'écrase. Il faut les **deux**, dans le même terminal :

```bash
cd ~/Documents/derush_tool/electron
npm config set strict-ssl false
export NODE_TLS_REJECT_UNAUTHORIZED=0
rm -rf node_modules
npm install
```

`strict-ssl false` débloque les paquets npm ; `NODE_TLS_REJECT_UNAUTHORIZED=0`
débloque le téléchargement du binaire Electron. Build terminé, remets npm
propre : `npm config set strict-ssl true`.

**Solution la plus propre** : builder sur un réseau sans interception — par
exemple le partage de connexion d'un iPhone. Là, `npm install` passe sans rien
désactiver.

### Le backend ne démarre pas — « Le serveur Python n'a pas démarré » / `spawn … ENOENT`

Le `.app` Electron ne trouve pas le backend Python embarqué. Vérifie que
`package.json` a bien un `extraResources` **dans le bloc `mac`** pointant
`../dist/DerushTool.app` vers `DerushTool/DerushTool.app` (et non un
`extraResources` commun pointant le dossier `../dist/DerushTool`). Sur Mac,
`main.js` attend `Resources/DerushTool/DerushTool.app/Contents/MacOS/DerushTool`.

### `cp: … /ffmpeg: Permission denied` au 2ᵉ build

Les binaires Homebrew sont en lecture seule ; une copie précédente l'est aussi et
bloque l'écrasement. Le script fait maintenant un `rm -f` avant copie. Si tu as
une vieille version du script, supprime les fichiers à la main :
`rm -f ffmpeg ffprobe` à la racine, puis relance.

### L'app se lance mais reste sur le splash

Le backend Python n'a pas démarré. Pour debug :
```bash
# Lance l'app depuis Terminal pour voir les logs
/Applications/DerushTool.app/Contents/MacOS/DerushTool
```
Et envoie-moi les messages.

### « Cannot find module 'electron' » dans les logs

Le `node_modules` Electron n'a pas été installé. Force :
```bash
cd electron
rm -rf node_modules
npm install
```
Puis relance `./build_mac.sh`.

### La vidéo ne joue pas (HEVC GoPro ou autre)

Chromium sur Mac arm64 supporte HEVC nativement via VideoToolbox (depuis macOS
Big Sur). Si ça ne marche pas, vérifie l'extension :
```bash
ffprobe /chemin/vers/clip.MP4 2>&1 | grep -i hevc
```
Si c'est bien HEVC et que ça ne joue pas, c'est un bug Electron à investiguer.

### Le tkinter folder picker ne s'ouvre pas

PyInstaller doit bundler tk correctement pour Python brew :
```bash
brew install python-tk@3.11
```
Puis recompile.

---

## Notes diverses

- L'app **n'est pas signée** par Apple. Si tu veux distribuer à grande échelle
  (App Store, ou juste éviter le clic-droit-Ouvrir), il faut un compte Apple
  Developer (99$/an) + procédure de notarization. C'est un projet à part entière.

- **Pas d'auto-update** sur Mac pour l'instant. Pour mettre à jour, tu refais le
  build et distribue le nouveau `.zip`.

- Le binaire produit est **arm64 only**. Il tournera sur Mac Intel via Rosetta
  mais sera 2-3x plus lent. Pour un vrai build Intel, change la cible
  `electron/package.json` → `"arch": ["x64"]` et re-build sur un Mac Intel (ou
  utilise `"arch": ["universal"]` pour un binaire universal2 sur un Mac arm64
  avec les bons tools).

- La taille du `.zip` est ~250 Mo (Chromium + Python + ffmpeg). Comme sur Windows.

---

**Une fois que c'est en place, le workflow devient** :
1. Tu modifies le code sur Windows
2. Tu zippes les sources
3. Tu transfères le zip au Mac mini (clé USB / AirDrop / iCloud)
4. Tu lances `./build_mac.sh`
5. Tu transfères le nouveau `.zip` produit vers le MBP

3 minutes une fois que t'as fait le setup initial.
