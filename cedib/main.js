const { app, BrowserWindow, ipcMain, globalShortcut } = require('electron');

let win;

function createWindow() {
  win = new BrowserWindow({
    width: 1600,
    height: 900,
    fullscreen: false,
    frame: false,
    webPreferences: {
      nodeIntegration: true,
      contextIsolation: false
    }
  });

  win.loadFile('index.html');

  // Atalho F11 para alternar Tela Cheia
  globalShortcut.register('F11', () => {
    if (win) {
      win.setFullScreen(!win.isFullScreen());
    }
  });
}

ipcMain.on('window-minimize', () => win && win.minimize());
ipcMain.on('window-toggle-maximize', () => {
  if (!win) return;
  if (win.isFullScreen()) {
    win.setFullScreen(false);
  } else if (win.isMaximized()) {
    win.unmaximize();
  } else {
    win.maximize();
  }
});
ipcMain.on('window-close', () => app.quit());

app.whenReady().then(createWindow);

app.on('will-quit', () => {
  globalShortcut.unregisterAll();
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit();
});