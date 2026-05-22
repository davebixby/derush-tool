"""
DERUSH TOOL — Launcher avec icône système (tray)
Lance le serveur dans un thread, ouvre le navigateur, affiche une icône tray.
"""
import threading
import webbrowser
import time
import sys
from pathlib import Path

# Add bundle dir to path when frozen by PyInstaller
if getattr(sys, 'frozen', False):
    sys.path.insert(0, str(Path(sys._MEIPASS)))

import derush_server

def _create_icon_image():
    """Crée une icône simple si pas de fichier icône disponible."""
    try:
        from PIL import Image, ImageDraw
        img = Image.new('RGBA', (64, 64), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        draw.ellipse([4, 4, 60, 60], fill='#6366f1')
        draw.rectangle([20, 22, 44, 42], fill='white')
        draw.rectangle([26, 44, 38, 54], fill='white')
        return img
    except Exception:
        return None

def _load_icon():
    from PIL import Image
    if getattr(sys, 'frozen', False):
        icon_path = Path(sys._MEIPASS) / 'derush_icon.png'
    else:
        icon_path = Path(__file__).parent / 'derush_icon.png'
    if icon_path.exists():
        return Image.open(icon_path)
    return _create_icon_image()

def main():
    no_browser = '--no-browser' in sys.argv

    # Start server in daemon thread
    server_thread = threading.Thread(target=derush_server.run, daemon=True)
    server_thread.start()

    port = derush_server.PORT

    if no_browser:
        # Lancé par un wrapper externe (Electron) — pas de navigateur, pas de tray,
        # pas de sleep. On laisse juste le thread serveur tourner.
        try:
            server_thread.join()
        except KeyboardInterrupt:
            sys.exit(0)
        return

    # Wait then open browser
    time.sleep(1.5)
    webbrowser.open(f'http://localhost:{port}')

    # Try to show system tray icon
    try:
        import pystray
        from PIL import Image

        icon_image = _load_icon()
        if icon_image is None:
            # No PIL / no image — just wait for server thread
            server_thread.join()
            return

        def on_open(icon, item):
            webbrowser.open(f'http://localhost:{port}')

        def on_quit(icon, item):
            icon.stop()
            sys.exit(0)

        menu = pystray.Menu(
            pystray.MenuItem('Ouvrir l\'interface', on_open, default=True),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem('Quitter', on_quit),
        )

        tray = pystray.Icon(
            'DerushTool',
            icon_image,
            'Derush Tool',
            menu=menu,
        )
        tray.run()

    except ImportError:
        # pystray not available — run headless, wait for Ctrl+C
        print("pystray non disponible — mode console.")
        try:
            server_thread.join()
        except KeyboardInterrupt:
            print("\nArrêt.")
            sys.exit(0)

if __name__ == '__main__':
    main()
