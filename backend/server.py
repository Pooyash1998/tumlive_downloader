from flask import Flask, request, jsonify
from flask_cors import CORS
import threading
import queue
import sys
import os
import re

# Import our modules (now in same directory)
from tum_live import get_courses, get_lecture_urls, get_playlist_url
import downloader
from multiprocessing import Semaphore
from pathlib import Path
import yaml
import tempfile

app = Flask(__name__)
CORS(app)

# Configuration functions
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

# Global variables
driver = None
courses = []
config = {}
download_status = {"status": "idle", "message": "", "progress": 0}

@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint for wait-on"""
    return jsonify({"status": "ok", "message": "TUM Live Downloader backend is running"})

@app.route('/api/config', methods=['GET'])
def get_config():
    """Get configuration"""
    global config
    config = load_config_file()
    return jsonify({
        "username": config.get('Username', ''),
        "hasCredentials": bool(config.get('Username') and config.get('Password')),
        "outputDir": str(parse_destination_folder(config)),
        "maxDownloads": parse_maximum_parallel_downloads(config)
    })

@app.route('/api/login', methods=['POST'])
def login():
    """Login and get courses"""
    global driver, courses, config
    
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
        # Use existing get_courses function
        driver, courses = get_courses(username, password)
        
        return jsonify({
            "success": True,
            "courses": [{"name": name, "url": url} for name, url in courses]
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 400

@app.route('/api/lectures', methods=['GET'])
def get_lectures():
    """Get lectures for all courses"""
    global driver, courses
    
    if not driver or not courses:
        return jsonify({"error": "Not logged in"}), 401
    
    try:
        lectures = get_lecture_urls(driver, courses)
        
        # Format lectures for frontend
        formatted_lectures = []
        for course_name, lecture_list in lectures.items():
            for lecture_id, lecture_url in lecture_list:
                for camera_type in ["COMB", "PRES", "CAM"]:
                    formatted_lectures.append({
                        "id": f"{course_name}:{lecture_id}:{camera_type}",
                        "courseName": course_name,
                        "lectureId": lecture_id,
                        "lectureUrl": lecture_url,
                        "cameraType": camera_type,
                        "displayName": f"{course_name} - {lecture_id}",
                        "date": "",
                        "weekNumber": "",
                        "dayOfWeek": "",
                        "duration": "",
                        "semester": ""
                    })
        
        return jsonify({"lectures": formatted_lectures})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/download', methods=['POST'])
def start_download():
    """Start download process"""
    global driver, download_status, config
    
    data = request.json
    selected_lectures = data.get('lectures', [])
    output_dir = data.get('outputDir', '')
    max_parallel_downloads = data.get('maxParallelDownloads', 3)
    
    # Validate max parallel downloads
    max_parallel_downloads = max(1, min(16, int(max_parallel_downloads)))
    
    if not selected_lectures:
        return jsonify({"error": "No lectures selected"}), 400
    
    if not output_dir:
        return jsonify({"error": "Output directory required"}), 400
    
    # Start download in background thread
    def download_thread():
        global download_status
        
        try:
            download_status = {"status": "downloading", "message": "Preparing downloads...", "progress": 0}
            
            # Group by course and camera type
            courses_to_download = {}
            for lecture in selected_lectures:
                course_name = lecture["courseName"]
                camera_type = lecture["cameraType"]
                
                if course_name not in courses_to_download:
                    courses_to_download[course_name] = {}
                if camera_type not in courses_to_download[course_name]:
                    courses_to_download[course_name][camera_type] = []
                
                courses_to_download[course_name][camera_type].append(lecture)
            
            # Get lecture URLs
            selected_courses_list = [(name, "") for name in courses_to_download.keys()]
            lectures = get_lecture_urls(driver, selected_courses_list)
            
            spawned_processes = []
            total_items = len(selected_lectures)
            current_item = 0
            
            for course_name, camera_types in courses_to_download.items():
                for camera_type, lecture_infos in camera_types.items():
                    current_item += 1
                    progress = int((current_item / total_items) * 100)
                    download_status = {
                        "status": "downloading",
                        "message": f"Processing {course_name} ({camera_type})...",
                        "progress": progress
                    }
                    
                    # Get playlist URLs
                    course_lectures = {course_name: lectures.get(course_name, [])}
                    playlists = get_playlist_url(driver, course_lectures, camera_type)
                    
                    if course_name in playlists:
                        subject_folder = Path(output_dir, f"{course_name}_{camera_type}")
                        subject_folder.mkdir(exist_ok=True)
                        
                        spawned_processes += downloader.download_list_of_videos(
                            playlists[course_name],
                            subject_folder,
                            parse_tmp_folder(config),
                            config.get('Keep-Original-File', True),
                            config.get('Jumpcut', True),
                            Semaphore(max_parallel_downloads)  # Use custom value
                        )
            
            # Wait for completion
            download_status = {"status": "downloading", "message": "Finalizing downloads...", "progress": 95}
            for process in spawned_processes:
                process.join()
            
            download_status = {"status": "completed", "message": "Downloads completed successfully!", "progress": 100}
            
        except Exception as e:
            download_status = {"status": "error", "message": f"Download failed: {str(e)}", "progress": 0}
    
    threading.Thread(target=download_thread, daemon=True).start()
    
    return jsonify({"success": True, "message": "Download started"})

@app.route('/api/download/status', methods=['GET'])
def get_download_status():
    """Get current download status"""
    return jsonify(download_status)

@app.route('/api/logout', methods=['POST'])
def logout():
    """Logout and cleanup"""
    global driver, courses
    
    if driver:
        driver.quit()
        driver = None
    
    courses = []
    
    return jsonify({"success": True})

if __name__ == '__main__':
    print("Starting TUM Live Downloader backend...")
    app.run(host='127.0.0.1', port=5001, debug=False)