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

app = Flask(__name__)
CORS(app)

# Shared cancellation flag that all processes can access
cancellation_flag = Value('i', 0)  # 0 = not cancelled, 1 = cancelled

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

def reset_download_state():
    """Reset all download-related global state variables"""
    global download_status, lecture_progress, active_download_processes, download_thread_active, current_download_semaphore, download_cancelled, cancellation_flag
    
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
        
        try:
            # IMPORTANT: Reset all states at the beginning of new download
            download_cancelled = False  # Reset cancellation flag
            lecture_progress.clear()  # Clear any old progress data
            active_download_processes.clear()  # Clear old process tracking
            current_download_semaphore = None  # Clear old semaphore reference
            downloader.clear_progress_data()  # Clear downloader progress data
            
            download_status = {"status": "downloading", "message": "Preparing downloads...", "progress": 0}
            
            # PHASE 1: Fetch all playlist URLs first (before showing any queued downloads)
            print("=== PHASE 1: FETCHING PLAYLIST URLs ===")
            all_playlists = {}
            total_stream_types = len(lectures_by_stream_type)
            current_stream = 0
            total_lectures = sum(len(lectures) for lectures in lectures_by_stream_type.values())
            
            # Fetch URLs for each stream type
            for stream_type, lectures_dict in lectures_by_stream_type.items():
                current_stream += 1
                download_status = {
                    "status": "downloading",
                    "message": f"Fetching playlist URLs for {stream_type}... ({current_stream}/{total_stream_types})",
                    "progress": int((current_stream / total_stream_types) * 20)  # First 20% for URL fetching
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
            
            print("=== PHASE 2: INITIALIZING DOWNLOADS ===")
            
            # Update status after URL fetching is complete
            download_status = {
                "status": "downloading",
                "message": "All URLs fetched, initializing downloads...",
                "progress": 20
            }
            
            # Create one semaphore for all downloads
            download_semaphore = Semaphore(max_parallel_downloads)
            current_download_semaphore = download_semaphore  # Track for cleanup
            
            # Clear any existing progress data before starting
            downloader.clear_progress_data()
            lecture_progress.clear()
            
            # PHASE 3: Start all downloads and initialize progress tracking
            all_processes = []
            
            # Create the course output folder first
            course_output_path = Path(output_dir) / course_name
            course_output_path.mkdir(parents=True, exist_ok=True)
            
            # Start downloads for each stream type
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
                active_download_processes.extend(processes)  # Track for cancellation
                
                # Initialize progress for all lectures AFTER downloader clears progress
                for title, _ in modified_playlist:
                    # Apply the same filename sanitization as the downloader
                    sanitized_filename = re.sub('[\\\\/:*?"<>|]|[\x00-\x20]', '_', title) + ".mp4"
                    display_name = sanitized_filename.replace('.mp4', '')
                    
                    lecture_progress[display_name] = {
                        "name": display_name,
                        "progress": 0,
                        "current": 0,
                        "total": 1,
                        "rate": 0,
                        "status": "queued",
                        "message": "Queued for download..."
                    }
                    
                    print(f"Initialized progress for: {display_name}")
            
            # Small delay to ensure all processes are started
            time.sleep(2)
            
            # Monitor download progress (remaining 80% progress)
            download_status = {"status": "downloading", "message": "Downloads started, monitoring progress...", "progress": 25}
            
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
                
                print(f"Real progress data keys: {list(real_progress.keys())}")
                print(f"Lecture progress keys: {list(lecture_progress.keys())}")
                
                # Update lecture progress with real data and track queued lectures
                active_downloads = 0
                queued_downloads = 0
                completed_count = 0
                
                # DON'T clear lecture_progress - we want to keep queued entries
                # Just update existing entries with real progress data
                for filename, progress_data in real_progress.items():
                    display_name = filename.replace('.mp4', '')
                    
                    print(f"Updating progress for: {display_name} -> {progress_data['percentage']}% ({progress_data['status']})")
                    
                    # Update existing entry or create new one
                    lecture_progress[display_name] = {
                        "name": display_name,
                        "progress": progress_data['percentage'],
                        "current": progress_data['current'],
                        "total": progress_data['total'],
                        "rate": progress_data['rate'],
                        "status": progress_data['status'],
                        "message": f"{progress_data['current']}/{progress_data['total']} segments ({progress_data['rate']:.1f} seg/s)" if progress_data['rate'] > 0 else f"{progress_data['current']}/{progress_data['total']} segments"
                    }
                    
                    # Count by status
                    if progress_data['status'] == 'downloading':
                        active_downloads += 1
                    elif progress_data['status'] == 'completed':
                        completed_count += 1
                
                # Count running processes to determine queued vs active
                running_processes = sum(1 for p in all_processes if p.is_alive())
                
                # Update status for lectures that are still queued (not in real_progress)
                for lecture_name, lecture_data in lecture_progress.items():
                    if lecture_name not in [fname.replace('.mp4', '') for fname in real_progress.keys()]:
                        # This lecture hasn't started downloading yet
                        if lecture_data['status'] == 'queued':
                            queued_downloads += 1
                            lecture_progress[lecture_name]['message'] = f"Queued (Position: {queued_downloads})"
                
                # Check which processes have finished (but don't count them as completed lectures yet)
                finished_processes = []
                for i, process in enumerate(all_processes):
                    if not process.is_alive():
                        finished_processes.append(i)
                        
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
                
                # Calculate overall progress based on completed lectures (not average progress)
                if total_lectures > 0:
                    # Progress is based on completed lectures out of total lectures
                    completion_ratio = completed_count / total_lectures
                    progress = 25 + int(completion_ratio * 75)  # Use remaining 75% for actual downloads
                    
                    # Create detailed status message
                    status_parts = []
                    if active_downloads > 0:
                        status_parts.append(f"{active_downloads} downloading")
                    if queued_downloads > 0:
                        status_parts.append(f"{queued_downloads} queued")
                    if completed_count > 0:
                        status_parts.append(f"{completed_count} completed")
                    
                    status_message = f"{', '.join(status_parts)} • {completed_count}/{total_lectures} total"
                    
                    download_status = {
                        "status": "downloading", 
                        "message": status_message, 
                        "progress": progress  # Don't cap at 99% - let it reach 100% when all are done
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
    app.run(host='0.0.0.0', port=5001, debug=False)