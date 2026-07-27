# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec — Derush Tool (cross-platform : Windows + macOS)
# Build: pyinstaller derush.spec

import sys
from pathlib import Path

ROOT = Path(SPECPATH)
IS_MAC = sys.platform == 'darwin'
IS_WIN = sys.platform == 'win32'

# Bundle ffmpeg/ffprobe : noms differents selon plateforme
# Win : ffmpeg.exe / ffprobe.exe a la racine du projet
# Mac : ffmpeg / ffprobe a la racine (binaire arm64/universal copie via build_mac.sh)
ffmpeg_bin = 'ffmpeg.exe'  if IS_WIN else 'ffmpeg'
ffprobe_bin = 'ffprobe.exe' if IS_WIN else 'ffprobe'

a = Analysis(
    [str(ROOT / 'derush_launcher.py')],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[
        (str(ROOT / 'derush_server.py'),    '.'),
        (str(ROOT / 'derush_core.py'),      '.'),
        (str(ROOT / 'derush_exports.py'),   '.'),
        (str(ROOT / 'derush_app.html'),     '.'),
        (str(ROOT / 'derush_setup.html'),   '.'),
        (str(ROOT / 'GUIDE.html'),          '.'),
        (str(ROOT / 'VERSION'),             '.'),
        (str(ROOT / 'CHANGELOG.md'),        '.'),
        # Bundle tous les modules JS externalisés (js/*.js → _internal/js/)
        *([(str(p), 'js') for p in (ROOT / 'js').glob('*.js')] if (ROOT / 'js').exists() else []),
        # Bundle ffmpeg/ffprobe binaries if present
        *( [(str(ROOT / ffmpeg_bin),   '.')] if (ROOT / ffmpeg_bin).exists()   else [] ),
        *( [(str(ROOT / ffprobe_bin),  '.')] if (ROOT / ffprobe_bin).exists()  else [] ),
        # Seed sync_url/sync_key (gitignored, contient la vraie clé) : si présent sur
        # la machine de build, le build "sort de l'usine" déjà configuré pour la sync
        # cloud — sinon absent, un tiers qui build depuis les sources publiques
        # retombe simplement sur le placeholder public (voir derush_server.py).
        *( [(str(ROOT / 'derush_config.seed.json'), '.')] if (ROOT / 'derush_config.seed.json').exists() else [] ),
        # Include icon if it exists
        *( [(str(ROOT / 'derush_icon.png'), '.')] if (ROOT / 'derush_icon.png').exists() else [] ),
    ],
    hiddenimports=[
        'pystray',
        'PIL',
        'PIL.Image',
        'PIL.ImageDraw',
        'http.server',
        'xml.etree.ElementTree',
        'tkinter',
        'tkinter.filedialog',
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

# UPX : Windows only. Sur Mac il abime souvent les binaires Python et le code
# signing devient impossible (les binaires modifies ne matchent plus leur signature).
use_upx = IS_WIN

# Icon : .ico sur Win, .icns sur Mac
if IS_MAC and (ROOT / 'derush_icon.icns').exists():
    icon_path = str(ROOT / 'derush_icon.icns')
elif IS_WIN and (ROOT / 'derush_icon.ico').exists():
    icon_path = str(ROOT / 'derush_icon.ico')
else:
    icon_path = None

# Mode onedir : EXE léger + COLLECT dossier dist/DerushTool/ avec _internal/
# Beaucoup plus rapide à démarrer que onefile (pas de self-extract au runtime).
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='DerushTool',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=use_upx,
    # Windows: console=False = pas de fenêtre cmd.exe
    # Mac:     console=True  = binaire POSIX pur, pas de NSApplicationLoad()
    #          → pas de fenêtre noire/Dock quand Electron le spawne headlessly
    console=IS_WIN,
    icon=icon_path,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=use_upx,
    upx_exclude=[],
    name='DerushTool',
)

# Sur Mac : on emballe le COLLECT en .app (bundle macOS standard).
# Sinon Finder voit juste un dossier "DerushTool/" — pas un vrai .app.
if IS_MAC:
    app = BUNDLE(
        coll,
        name='DerushTool.app',
        icon=icon_path,
        bundle_identifier='be.sebastiendelahaye.derushtool.backend',
        info_plist={
            'CFBundleShortVersionString': (ROOT / 'VERSION').read_text().strip() if (ROOT / 'VERSION').exists() else '0.3.5',
            'CFBundleVersion': (ROOT / 'VERSION').read_text().strip() if (ROOT / 'VERSION').exists() else '0.3.5',
            'NSHighResolutionCapable': True,
            'LSBackgroundOnly': False,
            # Permission requise pour ouvrir des dossiers via tkinter.filedialog
            # sinon Catalina+ bloque silencieusement
            'NSDesktopFolderUsageDescription': 'Derush Tool a besoin d\'accéder aux dossiers de rushes que vous selectionnez.',
            'NSDocumentsFolderUsageDescription': 'Derush Tool a besoin d\'accéder à vos dossiers de rushes.',
            'NSRemovableVolumesUsageDescription': 'Derush Tool lit les rushes depuis les disques externes (SSD USB, cartes SD).',
        },
    )
