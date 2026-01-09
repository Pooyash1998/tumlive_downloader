const { app, BrowserWindow, ipcMain, shell, nativeImage } = require('electron');
const path = require('path');
const { spawn } = require('child_process');

let mainWindow;
let pythonProcess;
let isQuitting = false;

function killPythonBackend() {
  if (pythonProcess && !pythonProcess.killed) {
    console.log('Killing Python backend process...');
    
    try {
      // Try graceful shutdown first
      pythonProcess.kill('SIGTERM');
      
      // Force kill after 3 seconds if still running
      setTimeout(() => {
        if (pythonProcess && !pythonProcess.killed) {
          console.log('Force killing Python backend...');
          pythonProcess.kill('SIGKILL');
        }
      }, 3000);
      
    } catch (error) {
      console.error('Error killing Python process:', error);
    }
    
    pythonProcess = null;
  }
}

function emergencyShutdown() {
  if (isQuitting) return; // Prevent multiple shutdowns
  isQuitting = true;
  
  console.log('🚨 Emergency shutdown initiated...');
  
  // Kill Python backend immediately
  killPythonBackend();
  
  // Close all windows
  BrowserWindow.getAllWindows().forEach(window => {
    if (!window.isDestroyed()) {
      window.destroy();
    }
  });
  
  // Force quit after a short delay
  setTimeout(() => {
    console.log('🔚 Force quitting application...');
    app.exit(0);
  }, 1000);
}

function createWindow() {
  // Try PNG first, then icns
  const pngPath = path.join(__dirname, '../icon.iconset/icon.png');
  const icnsPath = path.join(__dirname, '../app.icns');
  
  console.log('PNG path:', pngPath);
  console.log('ICNS path:', icnsPath);
  
  // Create native image from PNG (more reliable)
  const icon = nativeImage.createFromPath(pngPath);
  console.log('Icon loaded:', !icon.isEmpty());
  
  mainWindow = new BrowserWindow({
    width: 1200,
    height: 800,
    minWidth: 800,
    minHeight: 600,
    icon: icon,
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
      preload: path.join(__dirname, 'preload.js')
    },
    titleBarStyle: 'default',
    movable: true,
    show: false
  });

  // Set dock icon on macOS
  if (process.platform === 'darwin') {
    app.dock.setIcon(icon);
  }

  // Start Python backend
  startPythonBackend();

  // Load the app
  mainWindow.loadFile(path.join(__dirname, '../frontend/index.html'));

  // Show window when ready
  mainWindow.once('ready-to-show', () => {
    mainWindow.show();
  });

  // Handle window closing
  mainWindow.on('close', (event) => {
    if (!isQuitting) {
      console.log('Main window closing - initiating shutdown...');
      event.preventDefault(); // Prevent immediate close
      emergencyShutdown();
    }
  });

  mainWindow.on('closed', () => {
    mainWindow = null;
  });
}

function startPythonBackend() {
  // Only start Python backend in production mode
  if (process.argv.includes('--dev')) {
    console.log('Development mode: Python backend managed externally');
    return;
  }
  
  console.log('Production mode: Starting Python backend...');
  
  const pythonScript = path.join(__dirname, '../backend/server.py');
  const workingDir = path.join(__dirname, '..');
  
  console.log('Python script path:', pythonScript);
  console.log('Working directory:', workingDir);
  
  // Try python3 first, then python as fallback
  const tryStartPython = (pythonCmd) => {
    console.log('Trying Python command:', pythonCmd);
    
    const process = spawn(pythonCmd, [pythonScript], {
      cwd: workingDir, // Set working directory to project root
      stdio: ['pipe', 'pipe', 'pipe']
    });
    
    return process;
  };
  
  // Start with python3, fallback to python if it fails
  pythonProcess = tryStartPython('python3');
  
  pythonProcess.on('error', (error) => {
    console.error('python3 failed, trying python:', error.message);
    pythonProcess = tryStartPython('python');
    
    pythonProcess.on('error', (error) => {
      console.error('Failed to start Python backend with both python3 and python:', error);
    });
  });
  
  pythonProcess.stdout.on('data', (data) => {
    console.log(`Python: ${data.toString().trim()}`);
  });
  
  pythonProcess.stderr.on('data', (data) => {
    console.error(`Python Error: ${data.toString().trim()}`);
  });
  
  pythonProcess.on('exit', (code, signal) => {
    console.log(`Python backend exited with code ${code}, signal ${signal}`);
  });
  
  console.log('Python backend started with PID:', pythonProcess.pid);
}

app.whenReady().then(() => {
  // Set app icon
  if (process.platform !== 'darwin') {
    app.setAppUserModelId('com.tumlive.downloader');
  }
  createWindow();
});

app.on('window-all-closed', () => {
  console.log('All windows closed - shutting down...');
  emergencyShutdown();
});

app.on('activate', () => {
  if (BrowserWindow.getAllWindows().length === 0) {
    createWindow();
  }
});

// Handle app quit events
app.on('before-quit', (event) => {
  if (!isQuitting) {
    console.log('App quit requested - initiating shutdown...');
    event.preventDefault();
    emergencyShutdown();
  }
});

app.on('will-quit', (event) => {
  if (!isQuitting) {
    console.log('App will quit - initiating shutdown...');
    event.preventDefault();
    emergencyShutdown();
  }
});

// Handle process signals
process.on('SIGINT', () => {
  console.log('Received SIGINT - shutting down...');
  emergencyShutdown();
});

process.on('SIGTERM', () => {
  console.log('Received SIGTERM - shutting down...');
  emergencyShutdown();
});

// Handle uncaught exceptions
process.on('uncaughtException', (error) => {
  console.error('💥 Uncaught exception:', error);
  emergencyShutdown();
});

process.on('unhandledRejection', (reason, promise) => {
  console.error('💥 Unhandled rejection at:', promise, 'reason:', reason);
  emergencyShutdown();
});

// Handle external links
ipcMain.handle('open-external', async (event, url) => {
  await shell.openExternal(url);
});