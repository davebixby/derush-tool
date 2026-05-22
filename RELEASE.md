# Publier une nouvelle release de Derush Tool

Workflow pour pousser une nouvelle version vers GitHub Releases. Les utilisateurs avec
une version installée recevront la mise à jour automatiquement (notification au démarrage).

## Pré-requis (une seule fois)

1. **Token GitHub** avec scope `repo` → https://github.com/settings/tokens/new
2. Stocke-le dans une variable d'environnement utilisateur Windows (persistant) :
   ```powershell
   [Environment]::SetEnvironmentVariable('GH_TOKEN', 'ghp_TON_TOKEN_ICI', 'User')
   ```
   Fermer/rouvrir la PowerShell après cette commande.

> **Note Windows** : `User`-level env vars ne sont pas toujours propagées aux
> subprocess `npm` lancés via PowerShell. Pour être safe, injecte-la dans la
> session avant chaque release (voir étape 3).

## Pour chaque release

### 1. Bump la version

Dans **2 fichiers** (à garder synchronisés) :
- `VERSION` à la racine → `0.3.0`
- `electron/package.json` → `"version": "0.3.0"`

### 2. Mets à jour CHANGELOG.md

Ajoute une nouvelle section en haut de `CHANGELOG.md` :
```markdown
## [0.3.0] — 2026-MM-DD

### ✨ Ajouté
- …

### 🐛 Corrigé
- …
```

### 3. Build + publish d'un seul coup

```powershell
# Rebuild le PyInstaller backend
cd C:\Users\delah\.gemini\antigravity\scratch\derush_tool
if (Test-Path 'dist\DerushTool') { Remove-Item 'dist\DerushTool' -Recurse -Force }
pyinstaller derush.spec --noconfirm --clean

# Build + publish Electron portable vers GitHub Releases
cd electron
# Injecte explicitement GH_TOKEN dans la session (User env vars pas toujours propagées)
$env:GH_TOKEN = [Environment]::GetEnvironmentVariable('GH_TOKEN', 'User')
npm run release
```

Le script `release` (= `electron-builder --publish always`) va :
- Compiler le `.exe` portable
- Créer un draft release sur GitHub avec le tag `vX.Y.Z`
- Uploader le `.exe` et les fichiers `latest.yml` (signature pour electron-updater)

### 4. Finalise la release sur GitHub

1. Va sur https://github.com/davebixby/derush-tool/releases
2. Le draft est créé → clique dessus → "Edit release"
3. Optionnellement, copie-colle la section CHANGELOG correspondante dans la description
4. Coche **"Set as the latest release"**
5. Clique **"Publish release"**

À partir de ce moment, les utilisateurs ayant la version précédente verront au prochain
démarrage une popup "Derush Tool vX.Y.Z est prêt à être installé".

## Workflow rapide (TL;DR)

```powershell
# 1. Bump VERSION + electron/package.json + CHANGELOG.md
# 2. Build & publish :
cd C:\Users\delah\.gemini\antigravity\scratch\derush_tool
Remove-Item 'dist\DerushTool' -Recurse -Force -ErrorAction SilentlyContinue
pyinstaller derush.spec --noconfirm --clean
cd electron
$env:GH_TOKEN = [Environment]::GetEnvironmentVariable('GH_TOKEN', 'User')
npm run release
# 3. Finalize sur https://github.com/davebixby/derush-tool/releases
```
