# TUM Live Downloader

A modern application for downloading TUM Live lectures with a user friendly UI and parallel download management.

## Motivation 

As a TUM student, watching lectures exclusively online is often inconvenient. Scrubbing back and forth is slow, and the internet connection in the library is not always reliable.

I initially built a CLI tool, but it quickly became impractical for daily use. This project evolved into a full desktop application with a graphical interface, allowing lectures to be fetched and downloaded with minimal effort.

The goal is simple: reliable offline access to TUM Live lectures.

## Quick Start

### Prerequisites

- **Node.js** (v16 or higher)
- **Python** 3.10+
- **Firefox** browser (for Selenium automation)
- **ffmpeg** required for video assembly
- **Conda** (recommended)

### Installation

You can run **TUM Live Downloader** either manually using Conda and npm, or using Docker.

#### 🐳 Docker Installation (Recommended)

1️⃣ **Clone the repository**
```bash
git clone https://github.com/Pooyash1998/tumlive_downloader.git
cd tumlive_downloader
```

2️⃣ **Create config file (optional)**
```bash
cp example_config.yml config.yml
# Edit config.yml with your credentials (stays on your machine - not copied to Docker)
```

3️⃣ **Build and run with Docker Compose**
```bash
docker-compose up -d --build
```

4️⃣ **Access the web interface**
- **Web Interface**: http://localhost:8080
- **API Backend**: http://localhost:5001 (optional)

#### 🔧 Manual Installation (Recommended for Desktop)

1️⃣ **Clone the repository**
```bash
git clone https://github.com/Pooyash1998/tumlive_downloader.git
cd tumlive_downloader
```

2️⃣ **Create and activate Conda environment**
```bash
conda create -n tumlive python=3.10 -y
conda activate tumlive
```

3️⃣ **Install Python dependencies**
```bash
pip install -r requirements.txt
```
This installs:
- Selenium (automatic Firefox driver management)
- Flask backend
- Download and parsing utilities

4️⃣ **Install Node.js dependencies**
```bash
npm install
```
This installs:
- Electron
- Frontend dependencies
- Development tooling

5️⃣ **Run the application**

**Development mode:**
```bash
npm run dev
```

**Production mode:**
```bash
npm start
```

**Backend runs on:** `http://127.0.0.1:5001`

> ⚠️ **macOS Users**  
> If you see a "port already in use" error:
> - Disable AirPlay Receiver in **System Settings → General → AirDrop & Handoff**
> - Or the app will automatically fall back to port 5001

## Configuration

Create a `config.yml` file in the root directory using the given `example_config.yml`:

It's not mandatory but using the config file you can save your TUM credentials so you don't have to put it in every time you login. Also if you wish to download lectures from older semesters you can either add them in the config file or you have to add it via GUI every time. So it helps to keep some settings for ease of use.

**Example config:**

```yaml
# TUM Live Downloader Configuration

# Login credentials
Username: "go55tum"
Password: "johndoe"

# Output settings
Output-Folder: "/output"
Maximum-Parallel-Downloads: 3

# Manual courses (courses from previous semesters not shown in current account)
# Add courses from older semesters that you want to download
Manual-Courses:
  "Machine Learning": "https://live.rbg.tum.de/?year=2025&term=W&slug=WiSe25_26_ML&view=3"
  "Introduction to Deep Learning": "https://live.rbg.tum.de/?year=2025&term=W&slug=WiSe25_26_ItDL&view=3"
```

### Manual Courses

Add courses from previous semesters in two ways:

1. **Config File**: Add to `Manual-Courses` section (read-only, permanent)
2. **GUI**: Click "Add Manual Course" button (session-only, removable)

Manual courses appear with:
- Blue dashed border
- "MANUAL" badge
- Remove button (for session-added courses only)

## User Interface

### Course Selection
- **Grid Layout**: Visual course cards with hover effects
- **Manual Courses**: Distinct styling with management options
- **Quick Actions**: Add manual courses, logout, settings

### Lecture View
- **Smart Filtering**: Filter by week, day, camera type
- **Grouping Options**: Group by week or weekday
- **Sorting**: Ascending/descending date order
- **Bulk Selection**: Select all with individual toggles

### Download Progress
- **Three-Phase Process**:
  1. **URL Fetching**: Gathering playlist URLs
  2. **Initialization**: Starting download processes  
  3. **Downloads**: Real-time segment progress
- **Status Sorting**: Active downloads appear first
- **Live Updates**: Segment-by-segment progress with rates
- **Minimizable Dialog**: Continue working while downloading

## Architecture

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   Electron      │    │   Frontend      │    │   Backend       │
│   (Desktop)     │◄──►│   (Web UI)      │◄──►│   (Flask API)   │
│                 │    │                 │    │                 │
│ • Window mgmt   │    │ • Modern UI     │    │ • TUM Live API  │
│ • Native APIs   │    │ • Progress UI   │    │ • Downloads     │
│ • File dialogs  │    │ • Real-time     │    │ • Process mgmt  │
└─────────────────┘    └─────────────────┘    └─────────────────┘
```

### Components

- **Electron** (`electron/`) - Native desktop wrapper with system integration
- **Frontend** (`frontend/`) - Modern web UI with responsive design
- **Backend** (`backend/`) - Python Flask API with download orchestration

### File Organization

```
downloads/
├── Course Name/
│   ├── Lecture_01_comb.mp4     # Combined stream
│   ├── Lecture_01_pres.mp4     # Presentation stream  
│   ├── Lecture_01_cam.mp4      # Camera stream
│   └── download_errors.log     # Error log (if any)
└── Another Course/
    └── ...
```

## Advanced Features

### Download Management
- **Parallel Processing**: 1-16 simultaneous downloads
- **Progress Tracking**: Real-time segment progress with download rates
- **Error Handling**: Automatic retries with exponential backoff

### Process Cleanup
- **Multi-Pass Killing**: Tracked processes → Orphaned processes → Force kill
- **Semaphore Cleanup**: Prevents resource leaks
- **File Cleanup**: Removes temp files, lock files, partial downloads
- **Nuclear Option**: Aggressive cleanup for stubborn processes

## Development

### Project Structure
```
├── electron/          # Electron main process
│   ├── main.js        # Main process entry
│   └── preload.js     # Renderer preload script
├── backend/           # Python Flask API
│   ├── server.py      # Main API server
│   ├── tum_live.py    # TUM Live integration
│   └── downloader.py  # Download engine
├── frontend/          # Web UI
│   ├── index.html     # Main UI
│   ├── app.js         # Frontend logic
│   └── styles.css     # Modern styling
└── config.yml         # Configuration
```

### API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/config` | Get configuration and manual courses |
| `POST` | `/api/login` | Authenticate and fetch courses |
| `GET` | `/api/courses` | List available courses |
| `GET` | `/api/lectures/<course>` | Get lectures for course |
| `POST` | `/api/download` | Start download process |
| `GET` | `/api/download/progress` | Real-time progress data |
| `POST` | `/api/download/cancel` | Cancel active downloads |
| `POST` | `/api/manual-course` | Add manual course (session) |
| `DELETE` | `/api/manual-course/<name>` | Remove manual course |
| `POST` | `/api/browse-folder` | Open native folder picker |

## Troubleshooting

### Common Issues

**Port 5001 in use:**
- Disable AirPlay Receiver in macOS System Settings
- Or app will automatically use alternative port

**Downloads not starting:**
- Check Firefox installation
- Verify TUM credentials
- Check network connectivity

**Processes not cleaning up:**
- Use the cancel button (don't force quit)
- Check Activity Monitor for orphaned Python processes
- Restart app if needed

**Manual courses not appearing:**
- Check URL format (must be TUM Live URL)
- Verify course is accessible
- Try adding via config file instead

### Debug Mode

Enable debug logging by setting environment variable:
```bash
DEBUG=1 npm run dev
```

## License

MIT License - see [LICENSE](LICENSE) file for details.

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Test thoroughly
5. Submit a pull request

## 🔗 Links

- **TUM Live**: https://live.rbg.tum.de/
- **GitHub**: https://github.com/Pooyash1998/tumlive_downloader
- **Issues**: https://github.com/Pooyash1998/tumlive_downloader/issues