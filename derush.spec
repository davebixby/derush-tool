# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec — Derush Tool
# Build: pyinstaller derush.spec

from pathlib import Path
ROOT = Path(SPECPATH)

a = Analysis(
    [str(ROOT / 'derush_launcher.py')],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[
        (str(ROOT / 'derush_server.py'),    '.'),
        (str(ROOT / 'derush_app.html'),     '.'),
        (str(ROOT / 'derush_setup.html'),   '.'),
        (str(ROOT / 'GUIDE.html'),          '.'),
        (str(ROOT / 'VERSION'),             '.'),
        (str(ROOT / 'CHANGELOG.md'),        '.'),
        # Bundle tous les modules JS externalisés (js/*.js → _internal/js/)
        *([(str(p), 'js') for p in (ROOT / 'js').glob('*.js')] if (ROOT / 'js').exists() else []),
        # Bundle ffmpeg/ffprobe binaries if present
        *( [(str(ROOT / 'ffmpeg.exe'),   '.')] if (ROOT / 'ffmpeg.exe').exists()   else [] ),
        *( [(str(ROOT / 'ffprobe.exe'),  '.')] if (ROOT / 'ffprobe.exe').exists()  else [] ),
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
    upx=True,
    console=False,
    icon=str(ROOT / 'derush_icon.ico') if (ROOT / 'derush_icon.ico').exists() else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='DerushTool',
)
