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
import signal
import psutil
import shutil

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
session_manual_courses = []  # Track manual courses added during session (not saved to config)
active_download_processes = []  # Track active download processes for cancellation
download_thread_active = None  # Track the main download thread
current_download_semaphore = None  # Track current semaphore for cleanup
download_cancelled = False  # Flag to prevent new processes during cancellation

@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint for wait-on"""
    return jsonify({"status": "ok", "message": "TUM Live Downloader backend is running"})

@app.route('/api/config', methods=['GET'])
def get_config():
    """Get configuration"""
    global config, session_manual_courses
    config = load_config_file()
    
    # Get manual courses from config (read-only)
    config_manual_courses = parse_manual_courses(config)
    
    # Combine config manual courses with session manual courses
    all_manual_courses = config_manual_courses + session_manual_courses
    manual_courses = [{"name": name, "url": url} for name, url in all_manual_courses]
    
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
        
        # Add manual courses from config (read-only) and session
        config_manual_courses = parse_manual_courses(config)
        all_manual_courses = config_manual_courses + session_manual_courses
        courses.extend(all_manual_courses)
        
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
    global driver, courses, config, session_manual_courses
    
    if not driver or not courses:
        return jsonify({"error": "Not logged in"}), 401
    
    try:
        # Get manual course names from both config and session
        config_manual_courses = parse_manual_courses(config)
        all_manual_courses = config_manual_courses + session_manual_courses
        manual_course_names = {name for name, url in all_manual_courses}
        
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
            download_cancelled = False  # Reset cancellation flag
            download_status = {"status": "downloading", "message": "Preparing downloads...", "progress": 0}
            
            # Create one semaphore for all downloads
            download_semaphore = Semaphore(max_parallel_downloads)
            current_download_semaphore = download_semaphore  # Track for cleanup
            
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
                    active_download_processes.extend(processes)  # Track for cancellation
            
            # Monitor download progress (remaining 90% progress)
            download_status = {"status": "downloading", "message": "Downloading videos...", "progress": 10}
            
            # Clear old progress and get real progress from downloader
            lecture_progress.clear()
            
            completed_lectures = 0
            error_log_path = Path(output_dir) / "download_errors.log"
            
            # Monitor processes and get real progress
            while all_processes and not download_cancelled:
                # Check if download was cancelled
                if download_cancelled:
                    print("Download cancellation detected in monitoring loop")
                    break
                
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
            active_download_processes.clear()  # Clear tracked processes
            current_download_semaphore = None  # Clear semaphore reference
            download_thread_active = None  # Clear thread reference
            download_cancelled = False  # Reset cancellation flag
            download_status = {"status": "completed", "message": f"All {total_lectures} lectures downloaded successfully!", "progress": 100}
            
        except Exception as e:
            import traceback
            error_details = traceback.format_exc()
            print(f"Download error: {error_details}")
            active_download_processes.clear()  # Clear tracked processes on error
            current_download_semaphore = None  # Clear semaphore reference
            download_thread_active = None  # Clear thread reference
            download_cancelled = False  # Reset cancellation flag
            download_status = {"status": "error", "message": f"Download failed: {str(e)}", "progress": 0}
    
    download_thread_active = threading.Thread(target=download_thread, daemon=True)
    download_thread_active.start()
    
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

@app.route('/api/download/cancel', methods=['POST'])
def cancel_download():
    """Aggressively cancel active download and clean up everything"""
    global download_status, lecture_progress, active_download_processes, download_thread_active, current_download_semaphore, download_cancelled
    
    try:
        print("=== STARTING AGGRESSIVE DOWNLOAD CANCELLATION ===")
        
        # 0. Set cancellation flag to stop new processes
        download_cancelled = True
        
        # 1. Kill all download processes aggressively
        kill_all_download_processes()
        
        # 2. Wait for processes to actually die
        print("Waiting for processes to die...")
        time.sleep(2)
        
        # 3. Clean up semaphore
        cleanup_semaphore()
        
        # 4. Clear all tracking variables
        active_download_processes.clear()
        download_thread_active = None
        current_download_semaphore = None
        
        # 5. Clear progress data
        downloader.clear_progress_data()
        lecture_progress.clear()
        
        # 6. Wait a bit more before file cleanup
        print("Waiting before file cleanup...")
        time.sleep(1)
        
        # 7. Clean up all temporary files and lock files
        aggressive_cleanup()
        
        # 8. Final verification - remove any lock files that might have been recreated
        print("Final lock file cleanup...")
        time.sleep(1)
        final_lock_cleanup()
        
        # 9. Update status
        download_status = {"status": "cancelled", "message": "Download cancelled and cleaned up", "progress": 0}
        
        print("=== DOWNLOAD CANCELLATION COMPLETED ===")
        return jsonify({"success": True, "message": "Download cancelled and all resources cleaned up"})
        
    except Exception as e:
        print(f"Error during cancellation: {e}")
        return jsonify({"error": f"Failed to cancel download: {str(e)}"}), 500

def kill_all_download_processes():
    """Aggressively kill all download processes and their children"""
    print("Killing all download processes...")
    
    killed_pids = set()
    
    # First pass: Kill all tracked processes and their children
    for process in active_download_processes:
        try:
            if process.is_alive():
                pid = process.pid
                print(f"Killing process {pid}")
                killed_pids.add(pid)
                
                # Get all child processes using psutil
                try:
                    parent = psutil.Process(pid)
                    children = parent.children(recursive=True)
                    
                    # Kill all children first
                    for child in children:
                        try:
                            child_pid = child.pid
                            print(f"Killing child process {child_pid}")
                            killed_pids.add(child_pid)
                            child.kill()
                            child.wait(timeout=3)  # Wait for child to die
                        except psutil.TimeoutExpired:
                            print(f"Child process {child_pid} didn't die, force killing")
                            try:
                                os.kill(child_pid, signal.SIGKILL)
                            except:
                                pass
                        except Exception as e:
                            print(f"Error killing child {child_pid}: {e}")
                    
                    # Kill parent
                    parent.kill()
                    parent.wait(timeout=3)  # Wait for parent to die
                    
                except psutil.TimeoutExpired:
                    print(f"Process {pid} didn't die, force killing")
                    try:
                        os.kill(pid, signal.SIGKILL)
                    except:
                        pass
                except psutil.NoSuchProcess:
                    print(f"Process {pid} already dead")
                except Exception as e:
                    print(f"Error killing process {pid}: {e}")
                    # Force kill using multiprocessing as fallback
                    try:
                        process.terminate()
                        process.join(timeout=3)
                        if process.is_alive():
                            process.kill()
                            process.join(timeout=2)
                    except:
                        pass
        except Exception as e:
            print(f"Error handling process: {e}")
    
    # Second pass: Kill any remaining python processes related to downloading
    print("Scanning for orphaned download processes...")
    try:
        for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
            try:
                pid = proc.info['pid']
                if pid in killed_pids:
                    continue  # Already killed
                    
                if proc.info['name'] in ['python', 'python3', 'Python']:
                    cmdline = ' '.join(proc.info['cmdline'] or [])
                    # Check if it's a download-related process
                    if any(keyword in cmdline for keyword in ['downloader.py', 'tum_video_scraper', 'download_list_of_videos', 'ffmpeg']):
                        print(f"Killing orphaned download process {pid}: {cmdline[:100]}")
                        proc.kill()
                        proc.wait(timeout=3)
                        killed_pids.add(pid)
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.TimeoutExpired):
                pass
            except Exception as e:
                print(f"Error checking process: {e}")
    except Exception as e:
        print(f"Error scanning for orphaned processes: {e}")
    
    # Third pass: Wait a moment and verify all processes are dead
    print("Verifying all processes are dead...")
    time.sleep(1)
    
    for pid in killed_pids:
        try:
            if psutil.pid_exists(pid):
                print(f"WARNING: Process {pid} still exists, force killing with SIGKILL")
                os.kill(pid, signal.SIGKILL)
        except:
            pass
    
    print(f"Killed {len(killed_pids)} processes")

def cleanup_semaphore():
    """Clean up semaphore resources"""
    global current_download_semaphore
    
    print("Cleaning up semaphore...")
    if current_download_semaphore:
        try:
            # Release all semaphore resources
            while True:
                try:
                    current_download_semaphore.release()
                except:
                    break
        except Exception as e:
            print(f"Error cleaning semaphore: {e}")
        
        current_download_semaphore = None

def aggressive_cleanup():
    """Aggressively clean up all temporary files and lock files"""
    print("Starting aggressive cleanup...")
    
    try:
        config = load_config_file()
        output_dir = parse_destination_folder(config)
        tmp_dir = parse_tmp_folder(config)
        
        # 1. Remove all .lock files
        print("Removing lock files...")
        for lock_file in output_dir.rglob("*.lock"):
            try:
                lock_file.unlink()
                print(f"Removed lock file: {lock_file}")
            except Exception as e:
                print(f"Failed to remove lock file {lock_file}: {e}")
        
        # 2. Remove all temporary download folders
        print("Removing temporary download folders...")
        if tmp_dir.exists():
            for item in tmp_dir.iterdir():
                if item.is_dir() and ('_ts' in item.name or 'tum_video_scraper' in item.name):
                    try:
                        shutil.rmtree(item)
                        print(f"Removed temp folder: {item}")
                    except Exception as e:
                        print(f"Failed to remove temp folder {item}: {e}")
        
        # 3. Remove progress files
        print("Removing progress files...")
        progress_files = [
            Path(tempfile.gettempdir()) / "tum_download_progress.json",
            tmp_dir / "tum_download_progress.json"
        ]
        
        for progress_file in progress_files:
            try:
                if progress_file.exists():
                    progress_file.unlink()
                    print(f"Removed progress file: {progress_file}")
            except Exception as e:
                print(f"Failed to remove progress file {progress_file}: {e}")
        
        # 4. Use downloader's cleanup function
        print("Running downloader cleanup...")
        downloader.cleanup_all_temp_files()
        
        # 5. Remove any partial downloads (files without corresponding .mp4)
        print("Removing partial downloads...")
        for output_folder in output_dir.iterdir():
            if output_folder.is_dir():
                for file in output_folder.iterdir():
                    if file.is_file() and not file.name.endswith('.mp4') and not file.name.endswith('.lock'):
                        try:
                            file.unlink()
                            print(f"Removed partial file: {file}")
                        except Exception as e:
                            print(f"Failed to remove partial file {file}: {e}")
                            
    except Exception as e:
        print(f"Error during aggressive cleanup: {e}")

def final_lock_cleanup():
    """Final pass to remove any lock files that might have been recreated"""
    try:
        config = load_config_file()
        output_dir = parse_destination_folder(config)
        
        print("Final lock file scan...")
        lock_files_found = list(output_dir.rglob("*.lock"))
        
        if lock_files_found:
            print(f"Found {len(lock_files_found)} lock files to remove")
            for lock_file in lock_files_found:
                try:
                    lock_file.unlink()
                    print(f"Removed lock file: {lock_file}")
                except Exception as e:
                    print(f"Failed to remove lock file {lock_file}: {e}")
        else:
            print("No lock files found in final cleanup")
            
    except Exception as e:
        print(f"Error during final lock cleanup: {e}")

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
    """Add a manual course (session only, doesn't modify config)"""
    global courses, all_lectures, driver, session_manual_courses
    
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
        # Check if course already exists in session or config
        config_manual_courses = parse_manual_courses(config)
        all_existing_courses = [name for name, url in courses] + [name for name, url in session_manual_courses]
        
        if course_name in all_existing_courses:
            return jsonify({"error": "Course with this name already exists"}), 400
        
        # Add to session manual courses (not saved to config)
        session_manual_courses.append((course_name, course_url))
        
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
            "message": f"Course '{course_name}' added for this session",
            "course": {"name": course_name, "url": course_url}
        })
        
    except Exception as e:
        return jsonify({"error": f"Failed to add course: {str(e)}"}), 500

@app.route('/api/manual-course/<course_name>', methods=['DELETE'])
def remove_manual_course(course_name):
    """Remove a manual course (session only, doesn't modify config)"""
    global courses, all_lectures, session_manual_courses
    
    try:
        # Check if it's a session manual course (can be removed)
        session_course_names = [name for name, url in session_manual_courses]
        
        if course_name not in session_course_names:
            return jsonify({"error": "Can only remove courses added in this session"}), 400
        
        # Remove from session manual courses
        session_manual_courses = [(name, url) for name, url in session_manual_courses if name != course_name]
        
        # Remove from current courses list
        courses = [(name, url) for name, url in courses if name != course_name]
        
        # Remove from lectures cache
        if course_name in all_lectures:
            del all_lectures[course_name]
        
        return jsonify({
            "success": True, 
            "message": f"Course '{course_name}' removed from session"
        })
        
    except Exception as e:
        return jsonify({"error": f"Failed to remove course: {str(e)}"}), 500

def logout():
    """Logout and cleanup"""
    global driver, courses, all_lectures, session_manual_courses
    
    if driver:
        driver.quit()
        driver = None
    
    courses = []
    all_lectures = {}
    session_manual_courses = []  # Clear session manual courses on logout
    
    return jsonify({"success": True})

if __name__ == '__main__':
    print("Starting TUM Live Downloader backend...")
    app.run(host='127.0.0.1', port=5001, debug=False)