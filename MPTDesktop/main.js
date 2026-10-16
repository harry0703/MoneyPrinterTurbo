/* MoneyPrinterTurbo Desktop - Electron main process.
 *
 * Responsibilities:
 *  - Spawn the PyInstaller-frozen backend (MoneyPrinterTurboServer.exe) as a
 *    sidecar process with a dynamically allocated local port.
 *  - Show a splash screen while the local server warms up.
 *  - Open the Streamlit WebUI in a native, chrome-less application window.
 *  - Guarantee a clean backend shutdown when the app window closes.
 */
"use strict";

const { app, BrowserWindow, shell, dialog, ipcMain } = require("electron");
const { spawn } = require("child_process");
const http = require("http");
const net = require("net");
const path = require("path");
const fs = require("fs");

const PRODUCT_NAME = "MoneyPrinterTurbo";
const IS_PACKAGED = app.isPackaged;

let mainWindow = null;
let splashWindow = null;
let backendProcess = null;
let backendPort = 0;
let backendBaseUrl = "";
let backendReady = false;
let quitting = false;

// ---------------------------------------------------------------------------
// Resource paths
// ---------------------------------------------------------------------------
function resourceRoot() {
  if (IS_PACKAGED) {
    return process.resourcesPath;
  }
  return path.join(__dirname, "resources");
}

function backendExePath() {
  const candidates = [
    path.join(resourceRoot(), "mpt-backend", "MoneyPrinterTurboServer.exe"),
    path.join(resourceRoot(), "mpt-backend", "MoneyPrinterTurboServer", "MoneyPrinterTurboServer.exe"),
    path.join(resourceRoot(), "backend", "MoneyPrinterTurboServer", "MoneyPrinterTurboServer.exe"),
  ];
  for (const candidate of candidates) {
    if (fs.existsSync(candidate)) {
      return candidate;
    }
  }
  return candidates[0];
}

function bundledFfmpegPath() {
  const candidate = path.join(resourceRoot(), "ffmpeg", "bin", "ffmpeg.exe");
  return fs.existsSync(candidate) ? candidate : "";
}

// ---------------------------------------------------------------------------
// Dynamic local port selection
// ---------------------------------------------------------------------------
function findFreePort(preferred) {
  return new Promise((resolve, reject) => {
    const candidates = [preferred];
    for (let p = 8501; p <= 8599; p += 1) {
      if (p !== preferred) {
        candidates.push(p);
      }
    }
    let index = 0;
    const tryNext = () => {
      if (index >= candidates.length) {
        reject(new Error("No free port available in range 8501-8599"));
        return;
      }
      const port = candidates[index];
      index += 1;
      const server = net.createServer();
      server.once("error", tryNext);
      server.once("listening", () => {
        server.close(() => resolve(port));
      });
      server.listen(port, "127.0.0.1");
    };
    tryNext();
  });
}

// ---------------------------------------------------------------------------
// Backend health polling
// ---------------------------------------------------------------------------
function waitForBackend(url, timeoutMs, onTick) {
  const startedAt = Date.now();
  return new Promise((resolve, reject) => {
    const attempt = () => {
      const req = http.get(`${url}/_stcore/health`, (res) => {
        res.resume();
        if (res.statusCode === 200) {
          resolve();
        } else {
          retry();
        }
      });
      req.on("error", retry);
      req.setTimeout(4000, () => {
        req.destroy();
        retry();
      });
    };
    const retry = () => {
      if (Date.now() - startedAt > timeoutMs) {
        reject(new Error(`Backend did not become healthy within ${timeoutMs / 1000}s`));
        return;
      }
      if (onTick) {
        onTick(Math.round((Date.now() - startedAt) / 1000));
      }
      setTimeout(attempt, 1000);
    };
    attempt();
  });
}

// ---------------------------------------------------------------------------
// Backend process lifecycle
// ---------------------------------------------------------------------------
function startBackend(port) {
  const exe = backendExePath();
  if (!fs.existsSync(exe)) {
    throw new Error(
      `Backend executable not found:\n${exe}\n\nThe packaged backend is missing. Re-run the build.`
    );
  }
  const env = Object.assign({}, process.env, {
    MPT_WEBUI_HOST: "127.0.0.1",
    MPT_WEBUI_PORT: String(port),
    PYTHONIOENCODING: "utf-8",
  });
  const ffmpeg = bundledFfmpegPath();
  if (ffmpeg) {
    env.MPT_FFMPEG_PATH = ffmpeg;
  }
  backendProcess = spawn(exe, [], {
    cwd: path.dirname(exe),
    env,
    windowsHide: true,
    stdio: ["ignore", "pipe", "pipe"],
  });
  backendProcess.stdout.on("data", (chunk) => {
    process.stdout.write(`[backend] ${chunk}`);
  });
  backendProcess.stderr.on("data", (chunk) => {
    process.stderr.write(`[backend] ${chunk}`);
  });
  backendProcess.once("exit", (code) => {
    backendProcess = null;
    if (!quitting && backendReady) {
      dialog.showErrorBox(
        PRODUCT_NAME,
        "El servidor local se detuvo inesperadamente. La aplicacion se cerrara."
      );
      app.quit();
    }
  });
}

function stopBackend() {
  if (backendProcess) {
    try {
      // Kill the whole process tree (uvicorn workers, ffmpeg children, etc.)
      spawn("taskkill", ["/PID", String(backendProcess.pid), "/T", "/F"], {
        windowsHide: true,
        stdio: "ignore",
      });
    } catch (err) {
      try {
        backendProcess.kill();
      } catch (innerErr) {
        /* noop */
      }
    }
    backendProcess = null;
  }
}

// ---------------------------------------------------------------------------
// Windows
// ---------------------------------------------------------------------------
function createSplashWindow() {
  splashWindow = new BrowserWindow({
    width: 480,
    height: 320,
    frame: false,
    resizable: false,
    center: true,
    transparent: true,
    alwaysOnTop: true,
    show: false,
    webPreferences: {
      // Trusted, bundled static file only. The splash needs ipcRenderer to
      // display backend startup progress.
      nodeIntegration: true,
      contextIsolation: false,
      sandbox: false,
    },
  });
  splashWindow.loadFile(path.join(__dirname, "splash.html"));
  splashWindow.once("ready-to-show", () => {
    splashWindow.show();
  });
}

function createMainWindow() {
  mainWindow = new BrowserWindow({
    width: 1440,
    height: 900,
    minWidth: 1024,
    minHeight: 700,
    show: false,
    title: PRODUCT_NAME,
    icon: path.join(__dirname, "assets", "icon.ico"),
    autoHideMenuBar: true,
    backgroundColor: "#0e1117",
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      nodeIntegration: false,
      contextIsolation: true,
      sandbox: true,
    },
  });
  mainWindow.setMenuBarVisibility(false);

  // Desktop behaviour: never navigate away inside the window; external links
  // open in the system browser instead.
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    if (url && !url.startsWith("http://127.0.0.1")) {
      shell.openExternal(url);
    }
    return { action: "deny" };
  });
  mainWindow.webContents.on("will-navigate", (event, url) => {
    if (!url.startsWith("http://127.0.0.1")) {
      event.preventDefault();
      shell.openExternal(url);
    }
  });

  mainWindow.once("ready-to-show", () => {
    mainWindow.show();
    mainWindow.maximize();
  });
  mainWindow.on("closed", () => {
    mainWindow = null;
  });
}

function sendSplashMessage(message) {
  if (splashWindow && !splashWindow.isDestroyed()) {
    splashWindow.webContents.send("backend-status", message);
  }
}

// ---------------------------------------------------------------------------
// App lifecycle
// ---------------------------------------------------------------------------
const gotLock = app.requestSingleInstanceLock();
if (!gotLock) {
  app.quit();
} else {
  app.on("second-instance", () => {
    if (mainWindow) {
      if (mainWindow.isMinimized()) {
        mainWindow.restore();
      }
      mainWindow.focus();
    }
  });

  app.whenReady().then(async () => {
    try {
      createSplashWindow();
      sendSplashMessage("Reservando puerto local...");
      backendPort = await findFreePort(8501);
      backendBaseUrl = `http://127.0.0.1:${backendPort}`;
      sendSplashMessage(`Iniciando servidor local (puerto ${backendPort})...`);
      startBackend(backendPort);
      await waitForBackend(backendBaseUrl, 180000, (elapsed) => {
        sendSplashMessage(`Inicializando servidor local... ${elapsed}s`);
      });
      backendReady = true;
      sendSplashMessage("Servidor listo. Abriendo interfaz...");
      createMainWindow();
      await mainWindow.loadURL(backendBaseUrl);
      mainWindow.setTitle(PRODUCT_NAME);
      if (splashWindow && !splashWindow.isDestroyed()) {
        splashWindow.close();
        splashWindow = null;
      }
    } catch (err) {
      stopBackend();
      dialog.showErrorBox(
        `${PRODUCT_NAME} - Error de inicio`,
        `No se pudo iniciar el servidor local:\n\n${err && err.message ? err.message : String(err)}`
      );
      app.quit();
    }
  });

  app.on("window-all-closed", () => {
    app.quit();
  });

  app.on("before-quit", () => {
    quitting = true;
  });

  app.on("will-quit", () => {
    stopBackend();
  });
}


