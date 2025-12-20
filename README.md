# TUM Live Downloader

A modern desktop application for downloading TUM Live lectures with a beautiful web-based UI.

## Features

- 🎨 **Modern UI** - Clean, responsive web interface
- 🔐 **Saved Credentials** - Remember login details
- 📋 **Lecture Management** - Browse and select lectures easily
- 🎥 **Multiple Camera Types** - COMB, PRES, CAM support
- 📊 **Progress Tracking** - Real-time download progress
- ⚡ **Fast Downloads** - Parallel downloading support

## Setup

### Prerequisites

- Node.js (v16 or higher)
- Python 3.8+
- Firefox browser (for Selenium)

### Installation

1. **Install Node.js dependencies:**
   ```bash
   npm install
   ```

2. **Install Python dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

3. **Run the application:**
   ```bash
   npm run dev
   ```

   Or for production:
   ```bash
   npm start
   ```

## Configuration

Create a `config.yml` file in the root directory:

```yaml
Username: "your_tum_username"
Password: "your_password"
Output-Folder: "./downloads"
Temp-Dir: "./tmp"
Maximum-Parallel-Downloads: 3
Keep-Original-File: true
Jumpcut: true
```

## Building

To build the application for distribution:

```bash
npm run build
```

## Project Structure

```
├── electron/          # Electron main process
├── backend/           # Python Flask API server
│   ├── server.py      # Flask API server
│   ├── tum_live.py    # TUM Live API functions
│   └── downloader.py  # Download logic
├── frontend/          # Web UI (HTML/CSS/JS)
├── config.yml         # Configuration file
└── package.json       # Node.js dependencies
```

## Architecture

- **Frontend**: HTML/CSS/JavaScript with modern design
- **Backend**: Python Flask API server
- **Desktop**: Electron wrapper for native app experience
- **Communication**: REST API between frontend and backend

## API Endpoints

- `GET /api/config` - Get configuration
- `POST /api/login` - Login and get courses
- `GET /api/lectures` - Get available lectures
- `POST /api/download` - Start download
- `GET /api/download/status` - Get download status
- `POST /api/logout` - Logout

## Development

The app consists of three main parts:

1. **Electron Main Process** (`electron/main.js`) - Desktop app wrapper
2. **Python Backend** (`backend/server.py`) - API server and download logic
3. **Web Frontend** (`frontend/`) - Modern web UI

For development, both the Python server and Electron app run simultaneously.