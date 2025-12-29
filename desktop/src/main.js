const { app, BrowserWindow, dialog, shell } = require("electron");
const { spawn } = require("child_process");
const crypto = require("crypto");
const fs = require("fs");
const http = require("http");
const net = require("net");
const path = require("path");

let backendProcess = null;
let backendBaseUrl = null;
let backendLogStream = null;
let splashWindow = null;
let mainWindow = null;
let isQuitting = false;

const APP_ID = "com.salarytracker.desktop";

function resolveSystemLocale() {
  if (typeof app.getPreferredSystemLanguages === "function") {
    const languages = app.getPreferredSystemLanguages();
    if (Array.isArray(languages) && languages.length > 0) {
      return languages[0];
    }
  }
  if (typeof app.getLocale === "function") {
    const locale = app.getLocale();
    if (locale) {
      return locale;
    }
  }
  const envLocale =
    process.env.LC_ALL || process.env.LC_CTYPE || process.env.LANG;
  if (envLocale) {
    return envLocale.split(".")[0].replace("_", "-");
  }
  return null;
}

const systemLocale = resolveSystemLocale();
if (systemLocale) {
  app.commandLine.appendSwitch("lang", systemLocale);
}

function resolveBackendRoot() {
  if (!app.isPackaged) {
    return path.resolve(__dirname, "..", "..");
  }
  return path.join(process.resourcesPath, "backend");
}

function resolvePythonCommand() {
  if (process.env.PYTHON) {
    const pythonEnv = process.env.PYTHON;
    return path.isAbsolute(pythonEnv)
      ? pythonEnv
      : path.resolve(process.cwd(), pythonEnv);
  }
  if (process.env.VIRTUAL_ENV) {
    const candidate =
      process.platform === "win32"
        ? path.join(process.env.VIRTUAL_ENV, "Scripts", "python.exe")
        : path.join(process.env.VIRTUAL_ENV, "bin", "python");
    if (fs.existsSync(candidate)) {
      return candidate;
    }
  }
  if (process.platform === "win32") {
    return "python";
  }
  return "python3";
}

function resolveBackendLaunch(backendRoot, port) {
  if (app.isPackaged) {
    const binaryName =
      process.platform === "win32"
        ? "salary-tracker-backend.exe"
        : "salary-tracker-backend";
    const executable = path.join(backendRoot, binaryName);
    if (!fs.existsSync(executable)) {
      throw new Error(
        `Backend executable not found at ${executable}. Rebuild the desktop app.`
      );
    }
    return { command: executable, args: ["--port", String(port)] };
  }

  const python = resolvePythonCommand();
  const scriptPath = path.join(
    backendRoot,
    "desktop",
    "backend",
    "desktop_backend.py"
  );
  if (!fs.existsSync(scriptPath)) {
    throw new Error(
      `Backend launcher not found at ${scriptPath}. Reinstall the desktop app.`
    );
  }
  return { command: python, args: [scriptPath, "--port", String(port)] };
}

function safeCloseWindow(windowRef) {
  if (windowRef && !windowRef.isDestroyed()) {
    windowRef.close();
  }
}

function ensureSecretKey(userDataPath) {
  const secretPath = path.join(userDataPath, "secret_key.txt");
  if (fs.existsSync(secretPath)) {
    return fs.readFileSync(secretPath, "utf8").trim();
  }
  const secret = crypto.randomBytes(32).toString("hex");
  fs.writeFileSync(secretPath, secret, "utf8");
  return secret;
}

function pickPort() {
  return new Promise((resolve, reject) => {
    const server = net.createServer();
    server.listen(0, "127.0.0.1", () => {
      const address = server.address();
      server.close(() => resolve(address.port));
    });
    server.on("error", reject);
  });
}

function waitForServer(url, timeoutMs = 20000) {
  return new Promise((resolve, reject) => {
    const deadline = Date.now() + timeoutMs;

    const attempt = () => {
      const request = http.get(url, (res) => {
        res.resume();
        resolve();
      });
      request.on("error", () => {
        if (Date.now() > deadline) {
          reject(new Error("Backend did not start in time."));
          return;
        }
        setTimeout(attempt, 400);
      });
    };

    attempt();
  });
}

async function startBackend() {
  const backendRoot = resolveBackendRoot();
  const port = await pickPort();
  const userDataPath = app.getPath("userData");
  const secretKey = ensureSecretKey(userDataPath);

  const env = {
    ...process.env,
    DJANGO_DEBUG: "false",
    DJANGO_ALLOWED_HOSTS: "127.0.0.1,localhost",
    DJANGO_CSRF_TRUSTED_ORIGINS: `http://127.0.0.1:${port},http://localhost:${port}`,
    DJANGO_DB_PATH: path.join(userDataPath, "db.sqlite3"),
    DJANGO_SECRET_KEY: secretKey,
    DJANGO_LOG_LEVEL: "INFO",
    DJANGO_DESKTOP_MODE: "true",
    PYTHONUNBUFFERED: "1",
  };

  const launch = resolveBackendLaunch(backendRoot, port);
  const logPath = path.join(userDataPath, "backend.log");
  backendLogStream = fs.createWriteStream(logPath, { flags: "a" });
  backendLogStream.write(
    `\n[${new Date().toISOString()}] Starting backend on port ${port}\n`
  );

  const serverProcess = spawn(
    launch.command,
    launch.args,
    {
      cwd: backendRoot,
      env,
      stdio: ["ignore", "pipe", "pipe"],
    }
  );

  serverProcess.stdout.on("data", (data) => {
    backendLogStream.write(data);
  });

  serverProcess.stderr.on("data", (data) => {
    backendLogStream.write(data);
  });

  serverProcess.on("close", () => {
    if (backendLogStream) {
      backendLogStream.end();
      backendLogStream = null;
    }
  });

  serverProcess.on("exit", (code) => {
    if (code !== 0 && !isQuitting) {
      dialog.showErrorBox(
        "Backend stopped",
        `The local server exited unexpectedly.\n\nLogs: ${logPath}`
      );
      app.quit();
    }
  });

  return { port, process: serverProcess };
}

function createSplashWindow() {
  splashWindow = new BrowserWindow({
    width: 420,
    height: 320,
    resizable: false,
    frame: false,
    transparent: false,
    alwaysOnTop: true,
    show: true,
    backgroundColor: "#0f172a",
  });

  splashWindow.loadFile(path.join(__dirname, "splash.html"));
}

function attachExternalLinkHandlers(window, baseUrl) {
  window.webContents.setWindowOpenHandler(({ url }) => {
    if (url.startsWith(baseUrl)) {
      return { action: "allow" };
    }
    shell.openExternal(url);
    return { action: "deny" };
  });

  window.webContents.on("will-navigate", (event, url) => {
    if (!url.startsWith(baseUrl)) {
      event.preventDefault();
      shell.openExternal(url);
    }
  });
}

async function createMainWindow(baseUrl) {
  mainWindow = new BrowserWindow({
    width: 1200,
    height: 820,
    minWidth: 1024,
    minHeight: 700,
    show: false,
    backgroundColor: "#0f172a",
    autoHideMenuBar: true,
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });

  attachExternalLinkHandlers(mainWindow, baseUrl);

  mainWindow.once("ready-to-show", () => {
    mainWindow.show();
    safeCloseWindow(splashWindow);
    splashWindow = null;
  });

  await mainWindow.loadURL(baseUrl);

  mainWindow.on("closed", () => {
    mainWindow = null;
  });
}

function stopBackend() {
  if (!backendProcess) {
    return;
  }
  backendProcess.kill();
  backendProcess = null;
  backendBaseUrl = null;
  if (backendLogStream) {
    backendLogStream.end();
    backendLogStream = null;
  }
}

async function bootstrap() {
  try {
    if (backendProcess && backendBaseUrl && !mainWindow) {
      await createMainWindow(backendBaseUrl);
      return;
    }

    createSplashWindow();
    const backend = await startBackend();
    backendProcess = backend.process;
    backendBaseUrl = `http://127.0.0.1:${backend.port}`;
    await waitForServer(backendBaseUrl);
    await createMainWindow(backendBaseUrl);
  } catch (error) {
    safeCloseWindow(splashWindow);
    splashWindow = null;
    dialog.showErrorBox("Startup failed", error.message || String(error));
    app.quit();
  }
}

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
}

app.setAppUserModelId(APP_ID);
app.whenReady().then(bootstrap);

app.on("window-all-closed", () => {
  stopBackend();
  if (process.platform !== "darwin") {
    app.quit();
  }
});

app.on("before-quit", () => {
  isQuitting = true;
  stopBackend();
});

app.on("activate", () => {
  if (BrowserWindow.getAllWindows().length === 0) {
    bootstrap();
  }
});
