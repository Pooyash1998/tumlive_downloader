from flask import Flask, request, jsonify
from flask_cors import CORS
from tum_live import get_courses, get_lecture_urls, get_playlist_url
from multiprocessing import Semaphore
import threading
import queue
import sys
import os
import re
import time
import downloader
from pathlib import Path
import yaml
import tempfile
from datetime import datetime

app = Flask(__name__)
CORS(app)

def load_config_file():
    """Load configuration from config file"""
    config_file_paths = [
        Path("config.yml"),
        Path("../config.yml"), 
        Path("config.yaml"),
        Path("../config.yaml")
    ]
    
    for path in config_file_paths:
        if path.exists():
            try:
                with open(path, "r") as config_file:
                    cfg = yaml.load(config_file, Loader=yaml.SafeLoader)
                    return cfg if cfg else {}
            except Exception:
                continue
    return {}

def parse_destination_folder(cfg) -> Path:
    """Parse and create destination folder from config"""
    destination_folder_path = None
    if 'Output-Folder' in cfg: 
        destination_folder_path = Path(cfg['Output-Folder'])
    if not destination_folder_path:
        destination_folder_path = Path.home() / "Downloads"
    destination_folder_path = Path(destination_folder_path)
    if not destination_folder_path.is_dir():
        destination_folder_path.mkdir(exist_ok=True)
    return destination_folder_path

def parse_tmp_folder(cfg) -> Path:
    """Parse and create temporary folder from config"""
    tmp_directory = None
    if 'Temp-Dir' in cfg:
        tmp_directory = Path(cfg['Temp-Dir'])
    if not tmp_directory:
        tmp_directory = Path(tempfile.gettempdir(), "tum_video_scraper")
    if not os.path.isdir(tmp_directory):
        tmp_directory.mkdir(exist_ok=True)
    return tmp_directory

def parse_maximum_parallel_downloads(cfg) -> int:
    """Parse maximum parallel downloads from config"""
    return cfg.get('Maximum-Parallel-Downloads', 3)

def parse_manual_courses(cfg) -> list[tuple[str, str]]:
    """Parse manual courses from config"""
    manual_courses = []
    if 'Manual-Courses' in cfg and cfg['Manual-Courses']:
        for course_name, course_url in cfg['Manual-Courses'].items():
            manual_courses.append((course_name, course_url))
    return manual_courses

driver = None
courses = []
all_lectures = {}
config = {}
download_status = {"status": "idle", "message": "", "progress": 0}
lecture_progress = {}  # Track individual lecture progress

@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint for wait-on"""
    return jsonify({"status": "ok", "message": "TUM Live Downloader backend is running"})

@app.route('/api/config', methods=['GET'])
def get_config():
    """Get configuration"""
    global config
    config = load_config_file()
    
    # Get manual courses using the parser function
    manual_courses_tuples = parse_manual_courses(config)
    manual_courses = [{"name": name, "url": url} for name, url in manual_courses_tuples]
    
    return jsonify({
        "username": config.get('Username', ''),
        "hasCredentials": bool(config.get('Username') and config.get('Password')),
        "outputDir": str(parse_destination_folder(config)),
        "maxDownloads": parse_maximum_parallel_downloads(config),
        "manualCourses": manual_courses
    })

@app.route('/api/login', methods=['POST'])
def login():
    """Login and get courses"""
    global driver, courses, all_lectures, config
    
    data = request.json
    username = data.get('username')
    password = data.get('password')
    use_saved_password = data.get('useSavedPassword', False)
    
    # If using saved password, get it from config
    if use_saved_password:
        config = load_config_file()
        password = config.get('Password')
        if not password:
            return jsonify({"error": "No saved password found"}), 400
    
    if not username or not password:
        return jsonify({"error": "Username and password required"}), 400
    
    try:
        driver, courses = get_courses(username, password)
        
        # Add manual courses from config using the parser function
        manual_courses_tuples = parse_manual_courses(config)
        courses.extend(manual_courses_tuples)
        
        # Fetch ALL lectures for ALL courses at once (including manual ones)
        all_lectures = get_lecture_urls(driver, courses)
        
        return jsonify({
            "success": True,
            "courses": [{"name": name, "url": url} for name, url in courses]
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 400

@app.route('/api/courses', methods=['GET'])
def get_courses_list():
    """Get list of available courses"""
    global driver, courses, config
    
    if not driver or not courses:
        return jsonify({"error": "Not logged in"}), 401
    
    try:
        # Get manual course names using the parser function
        manual_courses_tuples = parse_manual_courses(config)
        manual_course_names = {name for name, url in manual_courses_tuples}
        
        # Format courses for frontend
        formatted_courses = []
        for course_name, course_url in courses:
            formatted_courses.append({
                "name": course_name,
                "url": course_url,
                "isManual": course_name in manual_course_names
            })
        
        return jsonify({"courses": formatted_courses})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/lectures/<course_name>', methods=['GET'])
def get_course_lectures(course_name):
    """Get lectures for a specific course (from cache)"""
    global all_lectures
    
    if not all_lectures:
        return jsonify({"error": "No lectures cached. Please login again."}), 401
    
    try:
        # Get lectures from cache
        course_lectures = all_lectures.get(course_name, [])
        
        # Format lectures for frontend
        formatted_lectures = []
        for lecture in course_lectures:
            for camera_type in ["COMB", "PRES", "CAM"]:
                formatted_lectures.append({
                    "id": f"{course_name}:{lecture['id']}:{camera_type}",
                    "lectureId": lecture['id'],
                    "title": lecture['title'],
                    "date": lecture['date'].isoformat(),
                    "time": lecture['time'].strftime("%H:%M"),
                    "weekday": lecture['weekday'],
                    "week": lecture['week'],
                    "cameraType": camera_type,
                    "url": lecture['url'],
                    "courseName": course_name
                })
        
        return jsonify({"lectures": formatted_lectures})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/download', methods=['POST'])
def start_download():
    """Start download process"""
    global driver, download_status, config
    
    data = request.json
    course_name = data.get('courseName', '')
    lectures_by_stream_type = data.get('lecturesByStreamType', {})
    output_dir = data.get('outputDir', '')
    max_parallel_downloads = data.get('maxParallelDownloads', 3)
    
    # Validate max parallel downloads
    max_parallel_downloads = max(1, min(16, int(max_parallel_downloads)))
    
    if not lectures_by_stream_type:
        return jsonify({"error": "No lectures selected"}), 400
    
    if not output_dir:
        return jsonify({"error": "Output directory required"}), 400
    
    if not course_name:
        return jsonify({"error": "Course name required"}), 400
    
    # Start download in background thread
    def download_thread():
        global download_status
        
        try:
            download_status = {"status": "downloading", "message": "Preparing downloads...", "progress": 0}
            
            # Create one semaphore for all downloads
            download_semaphore = Semaphore(max_parallel_downloads)
            
            all_processes = []
            total_stream_types = len(lectures_by_stream_type)
            current_stream = 0
            total_lectures = sum(len(lectures) for lectures in lectures_by_stream_type.values())
            
            # Process each stream type separately
            for stream_type, lectures_dict in lectures_by_stream_type.items():
                current_stream += 1
                download_status = {
                    "status": "downloading",
                    "message": f"Getting playlist URLs for {stream_type}...",
                    "progress": int((current_stream / total_stream_types) * 10)  # First 10% for playlist fetching
                }
                
                # Get playlist URLs using the existing function
                playlists = get_playlist_url(driver, lectures_dict)
                
                if course_name in playlists:
                    # Create the course output folder first
                    course_output_path = Path(output_dir) / course_name
                    course_output_path.mkdir(parents=True, exist_ok=True)
                    
                    # Modify the playlist to include stream type in filename
                    modified_playlist = []
                    for title, m3u8_url in playlists[course_name]:
                        # Add stream type suffix to filename
                        filename_with_suffix = f"{title}_{stream_type.lower()}"
                        modified_playlist.append((filename_with_suffix, m3u8_url))
                    
                    # Just pass the arguments to downloader - reuse the same semaphore
                    processes = downloader.download_list_of_videos(
                        modified_playlist,        # videos: list[tuple[str, str]]
                        course_output_path,       # output_folder_path: Path (now exists)
                        parse_tmp_folder(config), # tmp_directory: Path
                        download_semaphore        # semaphore: Semaphore (reuse same one)
                    )
                    all_processes.extend(processes)
            
            # Monitor download progress (remaining 90% progress)
            download_status = {"status": "downloading", "message": "Downloading videos...", "progress": 10}
            
            # Clear old progress and get real progress from downloader
            lecture_progress.clear()
            
            completed_lectures = 0
            error_log_path = Path(output_dir) / "download_errors.log"
            
            # Monitor processes and get real progress
            while all_processes:
                # Get real progress data from downloader
                real_progress = downloader.get_progress_data()
                
                # Calculate overall progress based on individual lecture progress
                total_progress = 0
                active_lectures = 0
                
                # Update lecture progress with real data
                lecture_progress.clear()
                for filename, progress_data in real_progress.items():
                    # Use filename as key (remove .mp4 extension for display)
                    display_name = filename.replace('.mp4', '')
                    lecture_progress[display_name] = {
                        "name": display_name,
                        "progress": progress_data['percentage'],
                        "current": progress_data['current'],
                        "total": progress_data['total'],
                        "rate": progress_data['rate'],
                        "status": progress_data['status'],
                        "message": f"{progress_data['current']}/{progress_data['total']} segments ({progress_data['rate']:.1f} seg/s)" if progress_data['rate'] > 0 else f"{progress_data['current']}/{progress_data['total']} segments"
                    }
                    
                    # Add to overall progress calculation
                    total_progress += progress_data['percentage']
                    active_lectures += 1
                
                # Check which processes have finished
                finished_processes = []
                for i, process in enumerate(all_processes):
                    if not process.is_alive():
                        finished_processes.append(i)
                        completed_lectures += 1
                        
                        # Check for process errors and log them
                        if process.exitcode != 0:
                            error_msg = f"Process failed with exit code {process.exitcode} for lecture {i}"
                            try:
                                with open(error_log_path, 'a', encoding='utf-8') as f:
                                    f.write(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {error_msg}\n")
                            except Exception as log_error:
                                print(f"Failed to write error log: {log_error}")
                
                # Remove finished processes
                for i in reversed(finished_processes):
                    all_processes.pop(i)
                
                # Calculate more responsive overall progress
                if total_lectures > 0:
                    if active_lectures > 0:
                        # Use average progress of active lectures for more responsive updates
                        avg_lecture_progress = total_progress / active_lectures
                        # Combine completed lectures with average progress of active ones
                        overall_progress = ((completed_lectures * 100) + avg_lecture_progress) / total_lectures
                        progress = 10 + int((overall_progress / 100) * 90)
                    else:
                        # Fallback to simple completion-based progress
                        progress = 10 + int((completed_lectures / total_lectures) * 90)
                    
                    download_status = {
                        "status": "downloading", 
                        "message": f"Downloaded {completed_lectures}/{total_lectures} lectures...", 
                        "progress": min(99, progress)  # Cap at 99% until fully complete
                    }
                
                # Wait a bit before checking again - reduced for more responsive updates
                time.sleep(1)  # Check every 1 second for more responsive updates
            
            # Clear lecture progress when done
            lecture_progress.clear()
            download_status = {"status": "completed", "message": f"All {total_lectures} lectures downloaded successfully!", "progress": 100}
            
        except Exception as e:
            import traceback
            error_details = traceback.format_exc()
            print(f"Download error: {error_details}")
            download_status = {"status": "error", "message": f"Download failed: {str(e)}", "progress": 0}
    
    threading.Thread(target=download_thread, daemon=True).start()
    
    return jsonify({"success": True, "message": "Download started"})

@app.route('/api/download/status', methods=['GET'])
def get_download_status():
    """Get current download status"""
    return jsonify(download_status)

@app.route('/api/download/progress', methods=['GET'])
def get_download_progress():
    """Get detailed progress for individual lectures"""
    return jsonify({
        "overall": download_status,
        "lectures": lecture_progress
    })

@app.route('/api/browse-folder', methods=['POST'])
def browse_folder():
    """Open folder browser dialog"""
    try:
        import subprocess
        import os
        
        # Use macOS native folder picker via AppleScript
        if os.name == 'posix' and os.uname().sysname == 'Darwin':  # macOS
            script = '''
            tell application "System Events"
                activate
                set folderPath to choose folder with prompt "Select Output Directory"
                return POSIX path of folderPath
            end tell
            '''
            
            result = subprocess.run(['osascript', '-e', script], 
                                  capture_output=True, text=True, timeout=30)
            
            if result.returncode == 0:
                folder_path = result.stdout.strip()
                if folder_path and folder_path != '':
                    return jsonify({"success": True, "path": folder_path})
                else:
                    return jsonify({"success": False, "message": "No folder selected"})
            else:
                return jsonify({"success": False, "message": "Dialog cancelled"})
        
        else:
            # Fallback to tkinter for other systems
            import tkinter as tk
            from tkinter import filedialog
            
            # Create a root window and hide it
            root = tk.Tk()
            root.withdraw()
            root.attributes('-topmost', True)
            
            # Open folder dialog
            folder_path = filedialog.askdirectory(
                title="Select Output Directory",
                mustexist=True
            )
            
            root.destroy()
            
            if folder_path:
                return jsonify({"success": True, "path": folder_path})
            else:
                return jsonify({"success": False, "message": "No folder selected"})
                
    except subprocess.TimeoutExpired:
        return jsonify({"success": False, "error": "Dialog timeout"}), 500
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/manual-course', methods=['POST'])
def add_manual_course():
    """Add a manual course"""
    global courses, all_lectures, driver, config
    
    data = request.json
    course_name = data.get('courseName', '').strip()
    course_url = data.get('courseUrl', '').strip()
    
    if not course_name or not course_url:
        return jsonify({"error": "Course name and URL are required"}), 400
    
    if not driver:
        return jsonify({"error": "Not logged in"}), 401
    
    # Validate URL format
    if not course_url.startswith('https://live.rbg.tum.de/'):
        return jsonify({"error": "URL must be a valid TUM Live URL"}), 400
    
    try:
        # Load current config
        config = load_config_file()
        
        # Initialize Manual-Courses if it doesn't exist
        if 'Manual-Courses' not in config:
            config['Manual-Courses'] = {}
        
        # Check if course already exists
        if course_name in config['Manual-Courses']:
            return jsonify({"error": "Course with this name already exists"}), 400
        
        # Add the course to config
        config['Manual-Courses'][course_name] = course_url
        
        # Save config
        config_path = Path("config.yml")
        with open(config_path, 'w') as f:
            yaml.dump(config, f, default_flow_style=False)
        
        # Add to current courses list
        courses.append((course_name, course_url))
        
        # Fetch lectures for this new course
        try:
            new_course_lectures = get_lecture_urls(driver, [(course_name, course_url)])
            all_lectures.update(new_course_lectures)
        except Exception as e:
            print(f"Warning: Could not fetch lectures for manual course {course_name}: {e}")
            all_lectures[course_name] = []
        
        return jsonify({
            "success": True, 
            "message": f"Course '{course_name}' added successfully",
            "course": {"name": course_name, "url": course_url}
        })
        
    except Exception as e:
        return jsonify({"error": f"Failed to add course: {str(e)}"}), 500

@app.route('/api/manual-course/<course_name>', methods=['DELETE'])
def remove_manual_course(course_name):
    """Remove a manual course"""
    global courses, all_lectures, config
    
    try:
        # Load current config
        config = load_config_file()
        
        if 'Manual-Courses' not in config or course_name not in config['Manual-Courses']:
            return jsonify({"error": "Manual course not found"}), 404
        
        # Remove from config
        del config['Manual-Courses'][course_name]
        
        # Save config
        config_path = Path("config.yml")
        with open(config_path, 'w') as f:
            yaml.dump(config, f, default_flow_style=False)
        
        # Remove from current courses list
        courses = [(name, url) for name, url in courses if name != course_name]
        
        # Remove from lectures cache
        if course_name in all_lectures:
            del all_lectures[course_name]
        
        return jsonify({
            "success": True, 
            "message": f"Course '{course_name}' removed successfully"
        })
        
    except Exception as e:
        return jsonify({"error": f"Failed to remove course: {str(e)}"}), 500

def logout():
    """Logout and cleanup"""
    global driver, courses, all_lectures
    
    if driver:
        driver.quit()
        driver = None
    
    courses = []
    all_lectures = {}
    
    return jsonify({"success": True})

if __name__ == '__main__':
    print("Starting TUM Live Downloader backend...")
    app.run(host='127.0.0.1', port=5001, debug=False)