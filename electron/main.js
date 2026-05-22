// Electron wrapper for Derush Tool.
//
// Behaviour:
//   1. Spawn the Python backend (in dev: `python derush_server.py --no-browser`;
//      packaged: the bundled DerushTool.exe with --no-browser flag).
//   2. Poll http://localhost:8765 until the server responds.
//   3. Open a Chromium BrowserWindow on that URL.
//   4. On window close, terminate the backend subprocess cleanly.
//
// The Python server keeps its own HTTP transport — Electron is only acting as a
// dedicated Chromium frontend. This lets all collaborators on the LAN keep using
// http://<lan-ip>:8765 from their own browser if they want, while the local user
// gets a controlled Chromium with HEVC support and no leak quirks.

const { app, BrowserWindow, Menu, shell, dialog, nativeTheme } = require('electron');
// Force le dark mode pour que la title bar native (Win 10) soit sombre aussi
nativeTheme.themeSource = 'dark';
const path = require('path');
const { spawn } = require('child_process');
const http = require('http');
const fs = require('fs');
const { autoUpdater } = require('electron-updater');

const SERVER_PORT = 8765;
const SERVER_URL = `http://localhost:${SERVER_PORT}`;
const ICON_PATH = path.join(__dirname, 'derush_icon.png');

// Lit l'icône en base64 une fois au boot pour l'embed dans le splash HTML
let ICON_DATA_URL = '';
try {
  const buf = fs.readFileSync(ICON_PATH);
  ICON_DATA_URL = 'data:image/png;base64,' + buf.toString('base64');
} catch (e) { console.warn('[derush] icon not found at', ICON_PATH); }

let backendProc = null;
let mainWindow = null;
let splashWindow = null;

// ── Resolve which Python backend to launch ───────────────────────────────────
function backendCommand() {
  // Packaged: app.isPackaged === true → use the bundled DerushTool exe sitting
  // in extraResources (declared in package.json under build.extraResources).
  // Win onedir layout : resources/DerushTool/DerushTool.exe + resources/DerushTool/_internal/
  // Mac : resources/DerushTool/DerushTool.app/Contents/MacOS/DerushTool
  if (app.isPackaged) {
    if (process.platform === 'darwin') {
      // extraResources copies dist/DerushTool (onedir) → Resources/DerushTool/
      // The binary sits directly there, not inside a .app sub-bundle.
      const exe = path.join(process.resourcesPath, 'DerushTool', 'DerushTool');
      try { fs.chmodSync(exe, 0o755); } catch (e) { console.warn('[derush] chmod:', e.message); }
      return { cmd: exe, args: ['--no-browser'] };
    }
    const exe = path.join(process.resourcesPath, 'DerushTool', 'DerushTool.exe');
    return { cmd: exe, args: ['--no-browser'] };
  }
  // Dev: run the source server.py directly. Mac : `python3`, Windows : `python`.
  const serverPy = path.join(__dirname, '..', 'derush_server.py');
  const pythonBin = process.platform === 'darwin' ? 'python3' : 'python';
  return { cmd: pythonBin, args: [serverPy, '--no-browser'] };
}

function startBackend() {
  const { cmd, args } = backendCommand();
  console.log(`[derush] Spawning backend: ${cmd} ${args.join(' ')}`);
  // On macOS, Electron launched from the Dock has a minimal PATH (/usr/bin:/bin…).
  // Inject Homebrew so that bare 'ffmpeg' commands also work as a fallback.
  const spawnEnv = { ...process.env };
  if (process.platform === 'darwin') {
    const brewBin = fs.existsSync('/opt/homebrew/bin') ? '/opt/homebrew/bin' : '/usr/local/bin';
    spawnEnv.PATH = `${brewBin}:${process.env.PATH || '/usr/bin:/bin:/usr/sbin:/sbin'}`;
  }
  backendProc = spawn(cmd, args, {
    cwd: path.join(__dirname, '..'),
    windowsHide: true,
    stdio: ['ignore', 'pipe', 'pipe'],
    env: spawnEnv,
  });
  backendProc.stdout.on('data', (d) => process.stdout.write(`[backend] ${d}`));
  backendProc.stderr.on('data', (d) => process.stderr.write(`[backend] ${d}`));
  backendProc.on('exit', (code) => {
    console.log(`[derush] Backend exited with code ${code}`);
    backendProc = null;
    if (mainWindow && !mainWindow.isDestroyed()) {
      // If backend dies while UI is up, the page will start failing — close to
      // avoid the user staring at a blank screen.
      mainWindow.close();
    }
  });
}

function stopBackend() {
  if (backendProc) {
    console.log('[derush] Stopping backend…');
    try { backendProc.kill('SIGTERM'); } catch (e) {}
    // Give it a moment to honor the heartbeat-shutdown, otherwise force.
    setTimeout(() => { if (backendProc) try { backendProc.kill('SIGKILL'); } catch (e) {} }, 2000);
    backendProc = null;
  }
}

// ── Poll until backend answers HTTP ──────────────────────────────────────────
function waitForServer(timeoutMs = 15000) {
  const start = Date.now();
  return new Promise((resolve, reject) => {
    const tryOnce = () => {
      const req = http.get(SERVER_URL, { timeout: 1500 }, (res) => {
        // Any response (even 401/redirect to /login) means the server is up.
        res.resume();
        resolve();
      });
      req.on('error', () => retry());
      req.on('timeout', () => { req.destroy(); retry(); });
    };
    const retry = () => {
      if (Date.now() - start > timeoutMs) {
        reject(new Error(`Backend did not respond on ${SERVER_URL} within ${timeoutMs}ms`));
      } else {
        setTimeout(tryOnce, 300);
      }
    };
    tryOnce();
  });
}

// ── Splash window pendant le démarrage du backend ───────────────────────────
function createSplash() {
  splashWindow = new BrowserWindow({
    width: 420,
    height: 260,
    frame: false,
    transparent: false,
    alwaysOnTop: true,
    resizable: false,
    movable: true,
    skipTaskbar: false,
    backgroundColor: '#0f0f13',
    title: 'Derush Tool',
    icon: ICON_PATH,
    webPreferences: { nodeIntegration: false, contextIsolation: true, sandbox: true },
  });
  const logo = ICON_DATA_URL
    ? `<img src="${ICON_DATA_URL}" class="logo" alt="Derush">`
    : '<div class="logo logo-fallback">🎬</div>';
  const splashHtml = `<!DOCTYPE html><html><head><meta charset="utf-8"><style>
    html,body{margin:0;height:100%;background:linear-gradient(135deg,#0f0f13 0%,#1a1530 100%);color:#e0e0e8;font-family:'Segoe UI',sans-serif;display:flex;flex-direction:column;align-items:center;justify-content:center;user-select:none;overflow:hidden;}
    .logo{width:80px;height:80px;border-radius:50%;border:2px solid rgba(167,139,250,.5);box-shadow:0 0 24px rgba(167,139,250,.4),inset 0 0 0 4px rgba(15,15,19,.3);image-rendering:auto;animation:breath 2.5s ease-in-out infinite;}
    .logo-fallback{font-size:48px;display:flex;align-items:center;justify-content:center;}
    @keyframes breath{0%,100%{transform:scale(1);}50%{transform:scale(1.06);}}
    .title{font-size:22px;font-weight:700;color:#fff;letter-spacing:.03em;margin-top:18px;text-shadow:0 0 12px rgba(167,139,250,.4);}
    .title .accent{color:#a78bfa;}
    .sub{font-size:11px;color:#6b6b80;letter-spacing:.12em;text-transform:uppercase;margin-top:4px;}
    .bar{margin-top:22px;width:280px;height:3px;background:rgba(255,255,255,.06);border-radius:2px;overflow:hidden;position:relative;}
    .bar::before{content:'';position:absolute;left:-40%;top:0;bottom:0;width:40%;background:linear-gradient(90deg,transparent,#a78bfa,transparent);animation:slide 1.2s ease-in-out infinite;}
    @keyframes slide{from{left:-40%}to{left:100%}}
  </style></head><body>
    ${logo}
    <div class="title">DERUSH <span class="accent">TOOL</span></div>
    <div class="sub">Démarrage du serveur…</div>
    <div class="bar"></div>
  </body></html>`;
  splashWindow.loadURL('data:text/html;charset=utf-8,' + encodeURIComponent(splashHtml));
  splashWindow.on('closed', () => { splashWindow = null; });
}

function closeSplash() {
  if (splashWindow && !splashWindow.isDestroyed()) {
    try { splashWindow.close(); } catch (e) {}
  }
  splashWindow = null;
}

// ── Create the Chromium window ───────────────────────────────────────────────
function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1600,
    height: 1000,
    minWidth: 1100,
    minHeight: 700,
    title: 'Derush Tool',
    icon: ICON_PATH,
    backgroundColor: '#0a0a0f',
    autoHideMenuBar: true,
    show: false,  // restera caché jusqu'à did-finish-load (évite le flash blanc)
    // Title bar sombre : nativeTheme dark (set en haut de main.js) → la title bar
    // native Windows 11 utilise les couleurs sombres système. Sur Windows 10, le
    // backgroundColor de la window est appliqué aussi à la title bar non-cliente.
    // Pas de titleBarStyle:hidden (sinon plus de drag, plus de boutons natifs).
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      nodeIntegration: false,
      contextIsolation: true,
      sandbox: true,
      backgroundThrottling: false,
    },
  });

  // Quand l'UI principale est rendue, on ferme le splash et on affiche.
  mainWindow.once('ready-to-show', () => {
    closeSplash();
    mainWindow.show();
  });

  // Hide the menu bar entirely (no File/Edit/View clutter).
  Menu.setApplicationMenu(null);

  // External links open in the system browser, not inside the app.
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url);
    return { action: 'deny' };
  });

  mainWindow.loadURL(SERVER_URL);

  // Dev convenience: F12 toggles DevTools.
  mainWindow.webContents.on('before-input-event', (event, input) => {
    if (input.key === 'F12' && input.type === 'keyDown') {
      mainWindow.webContents.toggleDevTools();
    }
  });

  mainWindow.on('closed', () => {
    mainWindow = null;
  });
}

// ── Auto-update via GitHub Releases ──────────────────────────────────────────
// Check au démarrage en background. Si maj dispo → download silencieux puis
// notification utilisateur quand prête à installer (redémarrage requis).
// Marche en prod uniquement (app.isPackaged) — désactivé en dev pour ne pas
// tenter de fetch des releases inexistantes pendant le développement.
function setupAutoUpdater() {
  if (!app.isPackaged) return;
  autoUpdater.autoDownload = true;
  autoUpdater.autoInstallOnAppQuit = false;  // on contrôle quand on installe (via dialog)
  autoUpdater.on('error', (err) => console.warn('[update] error:', err.message));
  autoUpdater.on('update-available', (info) => {
    console.log('[update] available:', info.version, '— download starting');
  });
  autoUpdater.on('update-not-available', () => console.log('[update] none'));
  autoUpdater.on('download-progress', (p) => {
    console.log(`[update] downloading ${Math.round(p.percent)}% (${(p.bytesPerSecond/1024/1024).toFixed(1)} MB/s)`);
  });
  autoUpdater.on('update-downloaded', (info) => {
    const choice = dialog.showMessageBoxSync({
      type: 'info',
      title: 'Mise à jour disponible',
      message: `Derush Tool v${info.version} est prêt à être installé.`,
      detail: 'Souhaites-tu redémarrer maintenant pour installer la mise à jour ?',
      buttons: ['Redémarrer et installer', 'Plus tard'],
      defaultId: 0,
      cancelId: 1,
    });
    if (choice === 0) {
      autoUpdater.quitAndInstall(false, true);
    }
  });
  // Check 5s après le démarrage pour ne pas bloquer le boot
  setTimeout(() => {
    autoUpdater.checkForUpdates().catch(err => console.warn('[update] check failed:', err.message));
  }, 5000);
}

// ── App lifecycle ────────────────────────────────────────────────────────────
app.whenReady().then(async () => {
  createSplash();
  startBackend();
  setupAutoUpdater();
  try {
    await waitForServer();
  } catch (err) {
    closeSplash();
    dialog.showErrorBox(
      'Backend introuvable',
      `Le serveur Python n'a pas démarré:\n\n${err.message}\n\n` +
      'Vérifie que Python est installé (en dev) ou que DerushTool.exe est ' +
      'présent dans le dossier resources (en prod).'
    );
    app.quit();
    return;
  }
  createWindow();
});

app.on('window-all-closed', () => {
  stopBackend();
  app.quit();  // always quit — DerushTool has no reason to linger in the Dock
});

app.on('before-quit', stopBackend);

// No 'activate' handler — DerushTool should not reopen from the Dock after quit.
