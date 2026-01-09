from flask import Flask, request, jsonify
from flask_cors import CORS
from tum_live import get_courses, get_lecture_urls, get_playlist_url
from multiprocessing import Semaphore, Value
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
import atexit

import signal
import psutil
import shutil
import atexit

app = Flask(__name__)
CORS(app)

# Shared cancellation flag that all processes can access
cancellation_flag = Value('i', 0)  # 0 = not cancelled, 1 = cancelled

def emergency_shutdown():
    """Emergency shutdown - kill everything immediately"""
    print("\n" + "="*60)
    print("EMERGENCY SHUTDOWN INITIATED")
    print("="*60)
    
    try:
        # Set cancellation flag immediately
        cancellation_flag.value = 1
        
        # Kill all download processes immediately
        kill_all_python_download_processes()
        kill_all_download_processes()
        
        # Clean up resources
        cleanup_semaphore()
        
        # Only clean up temp files if we're actually shutting down
        # Check if this is a real shutdown vs normal operation
        import sys
        if hasattr(sys, '_getframe'):
            frame = sys._getframe(1)
            caller = frame.f_code.co_name
            # Only do aggressive cleanup if called from signal handler or main
            if caller in ['signal_handler', '<module>', 'main']:
                aggressive_cleanup()
                downloader.cleanup_all_temp_files()
        
        print("Emergency shutdown completed")
        
    except Exception as e:
        print(f"Error during emergency shutdown: {e}")
    
    # Force exit
    os._exit(0)

def signal_handler(signum, frame):
    """Handle shutdown signals (SIGINT, SIGTERM)"""
    signal_names = {
        signal.SIGINT: "SIGINT (Ctrl+C)",
        signal.SIGTERM: "SIGTERM (Termination)"
    }
    
    signal_name = signal_names.get(signum, f"Signal {signum}")
    print(f"\nReceived {signal_name} - Initiating graceful shutdown...")
    
    emergency_shutdown()

def setup_signal_handlers():
    """Set up signal handlers for graceful shutdown"""
    try:
        # Handle Ctrl+C and termination signals
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
        
        # DON'T register atexit handler - it causes problems during normal operation
        # atexit.register(emergency_shutdown)
        
        print("Signal handlers registered for graceful shutdown")
        
    except Exception as e:
        print(f"Warning: Could not set up signal handlers: {e}")

# Set up signal handlers immediately
setup_signal_handlers()

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
    """Parse and create temporary folder from config - use more stable location"""
    tmp_directory = None
    if 'Temp-Dir' in cfg:
        tmp_directory = Path(cfg['Temp-Dir'])
    if not tmp_directory:
        # Use a more stable location instead of system temp
        # Try user's home directory first, fallback to system temp
        try:
            tmp_directory = Path.home() / ".tum_video_scraper_temp"
        except:
            tmp_directory = Path(tempfile.gettempdir(), "tum_video_scraper")
    
    # Ensure directory exists and is writable
    try:
        tmp_directory.mkdir(parents=True, exist_ok=True)
        # Test write access
        test_file = tmp_directory / "test_write.tmp"
        test_file.touch()
        test_file.unlink()
    except Exception as e:
        print(f"Warning: Cannot use temp directory {tmp_directory}: {e}")
        # Fallback to system temp
        tmp_directory = Path(tempfile.gettempdir(), "tum_video_scraper")
        tmp_directory.mkdir(parents=True, exist_ok=True)
    
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

# Simple progress tracking - just count completed lectures
total_lectures_to_download = 0
completed_lectures_count = 0
lecture_completion_status = {}  # filename -> True/False

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

def reset_download_state():
    """Reset all download-related global state variables"""
    global download_status, lecture_progress, active_download_processes, download_thread_active, current_download_semaphore, download_cancelled, cancellation_flag
    global total_lectures_to_download, completed_lectures_count, lecture_completion_status
    
    print("Resetting all download states...")
    
    # Reset status
    download_status = {"status": "idle", "message": "", "progress": 0}
    
    # Clear progress tracking
    lecture_progress.clear()
    
    # Clear process tracking
    active_download_processes.clear()
    
    # Clear thread and semaphore references
    download_thread_active = None
    current_download_semaphore = None
    
    # Reset cancellation flags
    download_cancelled = False
    cancellation_flag.value = 0  # Reset shared flag
    
    # Reset simple progress counters
    total_lectures_to_download = 0
    completed_lectures_count = 0
    lecture_completion_status.clear()
    
    # Clear downloader progress data
    downloader.clear_progress_data()
    
    print("Download state reset complete")

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
    
    # Reset all download states before starting new download
    reset_download_state()
    
    # Start download in background thread
    def download_thread():
        global download_status, download_cancelled, lecture_progress, active_download_processes, current_download_semaphore
        global total_lectures_to_download, completed_lectures_count, lecture_completion_status
        
        try:
            # IMPORTANT: Reset all states at the beginning of new download
            download_cancelled = False
            lecture_progress.clear()
            active_download_processes.clear()
            current_download_semaphore = None
            downloader.clear_progress_data()
            lecture_completion_status.clear()
            completed_lectures_count = 0
            
            download_status = {"status": "downloading", "message": "Preparing downloads...", "progress": 0}
            
            # PHASE 1: Fetch all playlist URLs first (0-20% progress)
            print("=== PHASE 1: FETCHING PLAYLIST URLs ===")
            all_playlists = {}
            total_stream_types = len(lectures_by_stream_type)
            current_stream = 0
            
            # Fetch URLs for each stream type
            for stream_type, lectures_dict in lectures_by_stream_type.items():
                current_stream += 1
                progress = int((current_stream / total_stream_types) * 20)  # 0-20% for URL fetching
                download_status = {
                    "status": "downloading",
                    "message": f"Fetching playlist URLs for {stream_type}... ({current_stream}/{total_stream_types})",
                    "progress": progress
                }
                
                print(f"Fetching URLs for {stream_type}...")
                
                # Get playlist URLs using the existing function
                playlists = get_playlist_url(driver, lectures_dict)
                
                if course_name in playlists:
                    # Modify the playlist to include stream type in filename
                    modified_playlist = []
                    for title, m3u8_url in playlists[course_name]:
                        # Add stream type suffix to filename
                        filename_with_suffix = f"{title}_{stream_type.lower()}"
                        modified_playlist.append((filename_with_suffix, m3u8_url))
                    
                    all_playlists[stream_type] = modified_playlist
                    print(f"Got {len(modified_playlist)} URLs for {stream_type}")
                else:
                    print(f"No playlists found for {course_name} in {stream_type}")
            
            # NOW calculate the correct total from actual playlists
            total_lectures_to_download = sum(len(playlist) for playlist in all_playlists.values())
            print(f"TOTAL LECTURES TO DOWNLOAD: {total_lectures_to_download}")
            
            print("=== PHASE 2: STARTING DOWNLOADS ===")
            
            # Update status after URL fetching is complete
            download_status = {
                "status": "downloading",
                "message": "All URLs fetched, starting downloads...",
                "progress": 20
            }
            
            # Create one semaphore for all downloads
            download_semaphore = Semaphore(max_parallel_downloads)
            current_download_semaphore = download_semaphore
            
            # Create the course output folder first
            course_output_path = Path(output_dir) / course_name
            course_output_path.mkdir(parents=True, exist_ok=True)
            
            # Initialize completion tracking for all lectures
            for stream_type, modified_playlist in all_playlists.items():
                for title, _ in modified_playlist:
                    # Apply the same filename sanitization as the downloader
                    sanitized_filename = re.sub('[\\\\/:*?"<>|]|[\x00-\x20]', '_', title) + ".mp4"
                    lecture_completion_status[sanitized_filename] = False
                    
                    # Initialize progress display
                    display_name = sanitized_filename.replace('.mp4', '')
                    lecture_progress[display_name] = {
                        "name": display_name,
                        "progress": 0,
                        "current": 0,
                        "total": 100,
                        "rate": 0,
                        "status": "queued",
                        "message": "Queued for download..."
                    }
            
            print(f"Initialized tracking for {len(lecture_completion_status)} lectures")
            
            # Update status to show queued lectures immediately
            download_status = {
                "status": "downloading",
                "message": f"{len(lecture_completion_status)} queued • 0/{total_lectures_to_download} total",
                "progress": 20
            }
            
            # Start downloads for each stream type
            all_processes = []
            for stream_type, modified_playlist in all_playlists.items():
                print(f"Starting downloads for {stream_type} ({len(modified_playlist)} files)")
                
                # Start download processes
                processes = downloader.download_list_of_videos(
                    modified_playlist,        # videos: list[tuple[str, str]]
                    course_output_path,       # output_folder_path: Path (now exists)
                    parse_tmp_folder(config), # tmp_directory: Path
                    download_semaphore,       # semaphore: Semaphore (reuse same one)
                    cancellation_flag         # shared cancellation flag
                )
                all_processes.extend(processes)
                active_download_processes.extend(processes)
                print(f"Started {len(processes)} processes for {stream_type}")
            
            print(f"TOTAL PROCESSES STARTED: {len(all_processes)}")
            print(f"MAX PARALLEL DOWNLOADS: {max_parallel_downloads}")
            print(f"SEMAPHORE VALUE: {download_semaphore._value if hasattr(download_semaphore, '_value') else 'unknown'}")
            
            # Monitor download progress (20-100% progress)
            print("=== PHASE 3: MONITORING PROGRESS ===")
            
            while all_processes and not download_cancelled:
                if download_cancelled:
                    print("Download cancellation detected in monitoring loop")
                    break
                
                # Get real progress data from downloader
                real_progress = downloader.get_progress_data()
                
                # Update individual lecture progress and count completions
                active_downloads = 0
                queued_downloads = 0
                
                # Update progress for lectures that have real progress data
                for filename, progress_data in real_progress.items():
                    display_name = filename.replace('.mp4', '')
                    
                    # Update lecture progress display
                    lecture_progress[display_name] = {
                        "name": display_name,
                        "progress": progress_data['percentage'],
                        "current": progress_data['current'],
                        "total": progress_data['total'],
                        "rate": progress_data['rate'],
                        "status": progress_data['status'],
                        "message": f"{progress_data['current']}/{progress_data['total']} segments ({progress_data['rate']:.1f} seg/s)" if progress_data['rate'] > 0 else f"{progress_data['current']}/{progress_data['total']} segments"
                    }
                    
                    # Count by status and mark completed lectures ONCE
                    if progress_data['status'] == 'downloading':
                        active_downloads += 1
                    elif progress_data['status'] == 'completed':
                        # Only increment if not already marked as completed
                        if not lecture_completion_status.get(filename, False):
                            lecture_completion_status[filename] = True
                            completed_lectures_count += 1
                            print(f"LECTURE COMPLETED: {filename} (total now: {completed_lectures_count})")
                
                # Count lectures that are still queued (not in real_progress)
                for lecture_name, lecture_data in lecture_progress.items():
                    filename_with_ext = lecture_name + ".mp4"
                    if filename_with_ext not in real_progress:
                        if lecture_data['status'] == 'queued':
                            queued_downloads += 1
                            lecture_progress[lecture_name]['message'] = f"Queued for download..."
                
                # Remove finished processes
                finished_processes = []
                for i, process in enumerate(all_processes):
                    if not process.is_alive():
                        finished_processes.append(i)
                
                for i in reversed(finished_processes):
                    all_processes.pop(i)
                
                # Calculate simple, reliable overall progress
                if total_lectures_to_download > 0:
                    # SIMPLE FORMULA: 20% + (completed * 80 / total)
                    progress_increment = 80 / total_lectures_to_download  # Each lecture is worth this much
                    progress = 20 + int(completed_lectures_count * progress_increment)
                    
                    print(f"SIMPLE PROGRESS: {completed_lectures_count}/{total_lectures_to_download} completed = {progress}%")
                    print(f"Each lecture worth: {progress_increment:.1f}%")
                    
                    # Create status message
                    status_parts = []
                    if active_downloads > 0:
                        status_parts.append(f"{active_downloads} downloading")
                    if queued_downloads > 0:
                        status_parts.append(f"{queued_downloads} queued")
                    if completed_lectures_count > 0:
                        status_parts.append(f"{completed_lectures_count} completed")
                    
                    status_message = f"{', '.join(status_parts)} • {completed_lectures_count}/{total_lectures_to_download} total"
                    
                    download_status = {
                        "status": "downloading", 
                        "message": status_message, 
                        "progress": progress
                    }
                
                # Wait before checking again
                time.sleep(1)
            
            # Download completed
            lecture_progress.clear()
            active_download_processes.clear()
            current_download_semaphore = None
            download_thread_active = None
            download_cancelled = False
            
            download_status = {"status": "completed", "message": f"All {completed_lectures_count} lectures downloaded successfully!", "progress": 100}
            
        except Exception as e:
            import traceback
            error_details = traceback.format_exc()
            print(f"Download error: {error_details}")
            active_download_processes.clear()
            current_download_semaphore = None
            download_thread_active = None
            download_cancelled = False
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
        
        # 0. Set cancellation flags to stop new processes IMMEDIATELY
        download_cancelled = True
        cancellation_flag.value = 1  # Set shared flag for all processes
        
        print("Cancellation flags set - no new processes should start")
        
        # 1. Immediately kill ALL Python processes that might be downloading
        # This is more aggressive - kill first, ask questions later
        kill_all_python_download_processes()
        
        # 2. Wait a moment for processes to die
        print("Waiting for processes to die...")
        time.sleep(3)
        
        # 3. Kill tracked processes (in case some survived)
        kill_all_download_processes()
        
        # 4. Wait longer for processes to actually die
        print("Waiting longer for processes to die...")
        time.sleep(3)
        
        # 5. Clean up semaphore more aggressively
        cleanup_semaphore()
        
        # 6. Clear all tracking variables and reset ALL states
        active_download_processes.clear()
        download_thread_active = None
        current_download_semaphore = None
        
        # 7. Clear progress data and reset download status
        downloader.clear_progress_data()
        lecture_progress.clear()
        
        # IMPORTANT: Reset download_status to idle to stop frontend polling
        download_status = {"status": "idle", "message": "", "progress": 0}
        
        # 8. Clean up all temporary files and lock files
        aggressive_cleanup()
        
        # 9. Final verification - remove any lock files that might have been recreated
        print("Final lock file cleanup...")
        time.sleep(1)
        final_lock_cleanup()
        
        # 10. One more process check to make sure everything is dead
        print("Final process verification...")
        remaining_processes = []
        for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
            try:
                if proc.info['name'] in ['python', 'python3', 'Python']:
                    cmdline = ' '.join(proc.info['cmdline'] or [])
                    if any(keyword in cmdline for keyword in ['downloader.py', 'tum_video_scraper']):
                        remaining_processes.append(proc.info['pid'])
                        print(f"WARNING: Found remaining download process {proc.info['pid']}")
                        try:
                            proc.kill()
                        except:
                            pass
            except:
                pass
        
        if remaining_processes:
            print(f"WARNING: {len(remaining_processes)} download processes may still be running")
        else:
            print("All download processes appear to be terminated")
        
        # 11. Final status update for the response (but keep download_status as idle)
        print("=== DOWNLOAD CANCELLATION COMPLETED ===")
        return jsonify({"success": True, "message": "Download cancelled and all resources cleaned up"})
        
    except Exception as e:
        print(f"Error during cancellation: {e}")
        return jsonify({"error": f"Failed to cancel download: {str(e)}"}), 500

def kill_all_python_download_processes():
    """Immediately kill ALL Python processes that might be downloading - nuclear option"""
    print("NUCLEAR OPTION: Killing ALL Python download processes immediately...")
    
    killed_count = 0
    
    try:
        for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
            try:
                if proc.info['name'] in ['python', 'python3', 'Python']:
                    cmdline = ' '.join(proc.info['cmdline'] or [])
                    
                    # Kill any Python process that looks like it's downloading
                    if any(keyword in cmdline for keyword in [
                        'downloader.py', 'tum_video_scraper', 'download_list_of_videos', 
                        'ffmpeg', 'm3u8', 'segments', '.ts', '.mp4'
                    ]):
                        pid = proc.info['pid']
                        print(f"NUCLEAR: Killing Python download process {pid}: {cmdline[:100]}")
                        
                        try:
                            # Kill immediately with SIGKILL (no graceful shutdown)
                            proc.kill()
                            killed_count += 1
                        except psutil.NoSuchProcess:
                            print(f"Process {pid} already dead")
                        except Exception as e:
                            print(f"Error killing process {pid}: {e}")
                            
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
            except Exception as e:
                print(f"Error checking process: {e}")
                
    except Exception as e:
        print(f"Error in nuclear process kill: {e}")
    
    print(f"NUCLEAR: Killed {killed_count} Python download processes")
    
    # Wait a moment for processes to die
    time.sleep(2)

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
    time.sleep(2)  # Give more time for processes to die
    
    for pid in killed_pids:
        try:
            if psutil.pid_exists(pid):
                print(f"WARNING: Process {pid} still exists, force killing with SIGKILL")
                os.kill(pid, signal.SIGKILL)
        except:
            pass
    
    # Fourth pass: Force terminate all tracked processes using multiprocessing
    print("Force terminating all tracked processes...")
    for process in active_download_processes:
        try:
            if process.is_alive():
                print(f"Force terminating process {process.pid}")
                process.terminate()
                process.join(timeout=1)
                if process.is_alive():
                    print(f"Force killing process {process.pid}")
                    process.kill()
                    process.join(timeout=1)
        except Exception as e:
            print(f"Error force terminating process: {e}")
    
    print(f"Process cleanup completed. Attempted to kill {len(killed_pids)} processes")

def cleanup_semaphore():
    """Clean up semaphore resources more aggressively"""
    global current_download_semaphore
    
    print("Cleaning up semaphore...")
    if current_download_semaphore:
        try:
            # Try to release all possible semaphore resources
            # Since we don't know how many are acquired, try releasing many times
            for i in range(20):  # Try releasing up to 20 times
                try:
                    current_download_semaphore.release()
                    print(f"Released semaphore resource {i+1}")
                except ValueError:
                    # ValueError means no more resources to release
                    print(f"No more semaphore resources to release (released {i})")
                    break
                except Exception as e:
                    print(f"Error releasing semaphore resource {i+1}: {e}")
                    break
        except Exception as e:
            print(f"Error cleaning semaphore: {e}")
        
        current_download_semaphore = None
        print("Semaphore cleanup completed")
    
    # Also try to clean up any system semaphores that might be leaked
    try:
        import subprocess
        # On macOS/Linux, try to find and clean up semaphores
        result = subprocess.run(['ipcs', '-s'], capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            lines = result.stdout.split('\n')
            for line in lines:
                if 'mp-' in line:  # multiprocessing semaphores typically have mp- prefix
                    print(f"Found potential leaked semaphore: {line}")
    except Exception as e:
        print(f"Could not check system semaphores: {e}")

def aggressive_cleanup():
    """Clean up temporary files and lock files - but preserve active downloads"""
    print("Starting selective cleanup...")
    
    try:
        config = load_config_file()
        output_dir = parse_destination_folder(config)
        tmp_dir = parse_tmp_folder(config)
        
        # 1. Remove all .lock files (these are safe to remove)
        print("Removing lock files...")
        for lock_file in output_dir.rglob("*.lock"):
            try:
                lock_file.unlink()
                print(f"Removed lock file: {lock_file}")
            except Exception as e:
                print(f"Failed to remove lock file {lock_file}: {e}")
        
        # 2. Only remove temp folders if downloads are actually cancelled
        global download_cancelled, cancellation_flag
        if download_cancelled or cancellation_flag.value == 1:
            print("Downloads cancelled - removing temporary download folders...")
            if tmp_dir.exists():
                for item in tmp_dir.iterdir():
                    if item.is_dir() and ('_ts' in item.name or 'tum_video_scraper' in item.name):
                        try:
                            shutil.rmtree(item)
                            print(f"Removed temp folder: {item}")
                        except Exception as e:
                            print(f"Failed to remove temp folder {item}: {e}")
        else:
            print("Downloads still active - preserving temp folders")
        
        # 3. Remove progress files (safe to remove)
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
        
        # 4. Only use downloader's cleanup if downloads are cancelled
        if download_cancelled or cancellation_flag.value == 1:
            print("Running downloader cleanup...")
            downloader.cleanup_all_temp_files()
        
        # 5. Remove any partial downloads (files without corresponding .mp4) - only if cancelled
        if download_cancelled or cancellation_flag.value == 1:
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
        print(f"Error during selective cleanup: {e}")

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
    try:
        print("Starting TUM Live Downloader backend...")
        print("Backend will be available at: http://127.0.0.1:5001")
        print("Press Ctrl+C to stop")
        print("-" * 50)
        
        # Run the Flask app
        app.run(host='127.0.0.1', port=5001, debug=False, use_reloader=False)
        
    except KeyboardInterrupt:
        print("\nKeyboard interrupt received")
        emergency_shutdown()
    except Exception as e:
        print(f"\n💥 Server error: {e}")
        emergency_shutdown()
    finally:
        print("🔚 Backend server stopped")