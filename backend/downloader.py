import re
import shutil
import subprocess
import sys
import time
from tqdm import tqdm
from multiprocessing import Process, Semaphore
from pathlib import Path
import m3u8
from concurrent.futures import ThreadPoolExecutor
import requests
from urllib.parse import urljoin
import logging
from threading import Lock
from datetime import datetime
import json
import tempfile

def log(msg: str):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)

# Use a file-based progress tracking system
PROGRESS_FILE = Path(tempfile.gettempdir()) / "tum_download_progress.json"

def update_progress(filename: str, current: int, total: int, rate: float = 0):
    """Update progress for a specific file using file-based storage - SIMPLE VERSION"""
    try:
        # Read existing progress
        progress_data = {}
        if PROGRESS_FILE.exists():
            try:
                with open(PROGRESS_FILE, 'r') as f:
                    progress_data = json.load(f)
            except:
                progress_data = {}
        
        # Simple status determination
        if current >= total and total > 0:
            status = 'completed'
            percentage = 100
        elif current > 0:
            status = 'downloading'
            percentage = min(100, int((current / total) * 100)) if total > 0 else 0
        else:
            status = 'starting'
            percentage = 0
        
        # Update progress for this file
        progress_data[filename] = {
            'current': current,
            'total': total,
            'percentage': percentage,
            'rate': round(rate, 1),
            'status': status,
            'last_update': time.time()
        }
        
        # Write back to file atomically
        temp_file = PROGRESS_FILE.with_suffix('.tmp')
        with open(temp_file, 'w') as f:
            json.dump(progress_data, f)
        temp_file.replace(PROGRESS_FILE)
        
        print(f"Progress update: {filename} -> {percentage}% ({status})")
        
    except Exception as e:
        print(f"Error updating progress: {e}")

def get_progress_data():
    """Get current progress data for all downloads"""
    try:
        if PROGRESS_FILE.exists():
            with open(PROGRESS_FILE, 'r') as f:
                return json.load(f)
    except:
        pass
    return {}

def clear_progress_data():
    """Clear all progress data"""
    try:
        if PROGRESS_FILE.exists():
            PROGRESS_FILE.unlink()
    except:
        pass


def download_list_of_videos(videos: list[tuple[str, str]],
                            output_folder_path: Path, tmp_directory: Path,
                            semaphore: Semaphore, cancellation_flag) -> [Process]:
    # Clear any existing progress data
    clear_progress_data()
    
    child_process_list = []
    for filename, url in videos:
        # Check shared cancellation flag before starting new processes
        if cancellation_flag.value == 1:
            print(f"Download cancelled via shared flag, skipping {filename}")
            break
        
        original_filename = filename
        filename = re.sub('[\\\\/:*?"<>|]|[\x00-\x20]', '_', filename) + ".mp4"  # Filter illegal filename chars
        
        print(f"Downloader: {original_filename} -> {filename}")
        
        output_file_path = Path(output_folder_path, filename)
        """We use locks to prevent processing the same video twice (e.g. if we run in multiple independent instances)"""
        """Locks can also be created by the user to keep us from downloading a specific video"""
        if not (Path(output_file_path.as_posix() + ".lock").exists()  # Check if lock file exists
                or output_file_path.exists()):  # Check if file exists (we downloaded and converted it already)
            
            # Double-check cancellation flag before creating lock file
            if cancellation_flag.value == 1:
                print(f"Download cancelled before creating lock for {filename}")
                break
                
            Path(output_file_path.as_posix() + ".lock").touch()  # Create lock file
            
            # Initialize progress for this file
            update_progress(filename, 0, 100, 0)  # Start with 0/100
            
            print(f"Starting download process for: {filename}")
            
            child_process = Process(target=download,  # Download video in separate process
                                    args=(filename, url,
                                          output_file_path, tmp_directory,
                                          semaphore, cancellation_flag))
            child_process.start()
            child_process_list.append(child_process)
            print(f"Process started for {filename} with PID: {child_process.pid}")
        else:
            print(f"Skipping {filename} - already exists or locked")
    return child_process_list

def download(filename: str, playlist_url: str,
             output_file_path: Path, tmp_directory: Path,
             semaphore: Semaphore, cancellation_flag):
    
    print(f"Download of {filename} started - attempting to acquire semaphore...")
    
    # Check shared cancellation flag before doing anything
    if cancellation_flag.value == 1:
        print(f"Download cancelled before starting for {filename}")
        return
    
    # Update status to "starting"
    update_progress(filename, 0, 100, 0)  # Start with 0/100
    
    # Check cancellation flag before acquiring semaphore
    if cancellation_flag.value == 1:
        print(f"Download cancelled before acquiring semaphore for {filename}")
        return
    
    print(f"Acquiring semaphore for {filename}...")
    semaphore.acquire()  # Acquire lock
    print(f"Semaphore acquired for {filename} - starting download")
    
    # Check cancellation flag after acquiring semaphore
    if cancellation_flag.value == 1:
        print(f"Download cancelled after acquiring semaphore for {filename}")
        semaphore.release()
        return
    
    download_start_time = time.time()  #Track download time
    
    # Update status to "downloading" after acquiring semaphore
    update_progress(filename, 1, 100, 0)  # Show 1% to indicate download started
    
    # Create error log path in the same directory as output
    error_log_path = output_file_path.parent / "download_errors.log"
    
    def log_error(message):
        """Log error to file"""
        try:
            with open(error_log_path, 'a', encoding='utf-8') as f:
                f.write(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {filename}: {message}\n")
        except Exception as e:
            print(f"Failed to write error log: {e}")
    
    # --- Phase 1: we parse the playlist and download its .ts segments in parallel ---
    try:
        playlist = m3u8.load(playlist_url)
        ts_urls = [urljoin(playlist_url, seg.uri) if not seg.uri.startswith("http") else seg.uri
                   for seg in playlist.segments]
        ts_folder = Path(tmp_directory, f"{filename}_ts")
        
        # Ensure temp folder exists and is stable
        ts_folder.mkdir(parents=True, exist_ok=True)
        
        # Test write access to temp folder
        test_file = ts_folder / "test_access.tmp"
        try:
            test_file.touch()
            test_file.unlink()
        except Exception as e:
            error_msg = f"Cannot write to temp directory {ts_folder}: {e}"
            print(error_msg, file=sys.stderr)
            log_error(error_msg)
            update_progress(filename, 0, 100, 0)
            semaphore.release()
            return

        # Initialize progress tracking
        total_segments = len(ts_urls)
        completed_segments = 0
        # Don't update progress here - we'll update it based on segment completion

        lock = Lock()
        # Progress bar for each Lecture
        pbar = tqdm(total=len(ts_urls), desc=f"{filename}", position=0, leave=True, dynamic_ncols=True)

        def download_ts(ts_url, index):
            nonlocal pbar, completed_segments
            
            # Check for cancellation before downloading each segment
            if cancellation_flag.value == 1:
                print(f"Download cancelled during segment download for {filename}")
                return None
            
            ts_path = ts_folder / f"{index:05d}.ts"
            
            # Check if temp folder still exists, recreate if needed
            if not ts_folder.exists():
                print(f"Temp folder disappeared, recreating: {ts_folder}")
                try:
                    ts_folder.mkdir(parents=True, exist_ok=True)
                except Exception as e:
                    print(f"Failed to recreate temp folder: {e}")
                    return None
            
            if ts_path.exists():
                with lock:
                    pbar.update(1)
                    completed_segments += 1
                    # Calculate progress as percentage and update
                    elapsed = time.time() - download_start_time
                    rate = completed_segments / elapsed if elapsed > 0 else 0
                    progress_percentage = int((completed_segments / total_segments) * 100) if total_segments > 0 else 0
                    update_progress(filename, progress_percentage, 100, rate)
                return ts_path # Skip download if file already exists
            
            max_retries = 5
            for attempt in range(max_retries):
                # Check for cancellation before each retry
                if cancellation_flag.value == 1:
                    print(f"Download cancelled during retry for {filename}")
                    return None
                    
                try:
                    # Ensure parent directory exists before every download attempt
                    ts_path.parent.mkdir(parents=True, exist_ok=True)
                    
                    # Verify directory exists and is writable
                    if not ts_path.parent.exists():
                        raise Exception(f"Cannot create temp directory: {ts_path.parent}")
                    
                    r = requests.get(ts_url, stream=True, timeout=15)
                    r.raise_for_status()
                    
                    # Write to temporary file first, then rename (atomic operation)
                    temp_path = ts_path.with_suffix('.tmp')
                    
                    # Ensure temp file directory still exists
                    temp_path.parent.mkdir(parents=True, exist_ok=True)
                    
                    with open(temp_path, "wb") as f:
                        for chunk in r.iter_content(1024*1024):
                            # Check for cancellation during chunk download
                            if cancellation_flag.value == 1:
                                print(f"Download cancelled during chunk download for {filename}")
                                # Clean up temp file
                                try:
                                    temp_path.unlink()
                                except:
                                    pass
                                return None
                            if chunk:
                                f.write(chunk)
                    
                    # Verify temp file was written successfully
                    if not temp_path.exists() or temp_path.stat().st_size == 0:
                        raise Exception(f"Temp file not written properly: {temp_path}")
                    
                    # Atomic rename to final location
                    temp_path.rename(ts_path)
                    
                    # Verify final file exists
                    if not ts_path.exists():
                        raise Exception(f"Final file not created: {ts_path}")
                    
                    with lock:
                        pbar.update(1)
                        completed_segments += 1
                        # Calculate progress as percentage and update
                        elapsed = time.time() - download_start_time
                        rate = completed_segments / elapsed if elapsed > 0 else 0
                        progress_percentage = int((completed_segments / total_segments) * 100) if total_segments > 0 else 0
                        update_progress(filename, progress_percentage, 100, rate)
                    return ts_path # Success -> Exit loop
                
                except Exception as e:
                    error_msg = f"[Retry {attempt + 1}/{max_retries}] Failed to download segment {ts_url}: {e}"
                    print(error_msg, file=sys.stderr)
                    
                    # Clean up any partial temp file
                    try:
                        temp_path = ts_path.with_suffix('.tmp')
                        if temp_path.exists():
                            temp_path.unlink()
                    except:
                        pass
                    
                    if attempt == max_retries - 1:  # Last attempt failed
                        log_error(f"Segment {index} failed after {max_retries} attempts: {e}")
                    time.sleep(2 ** attempt)  # Exponential backoff
            print(f"Failed to download segment {index} after {max_retries} failed attempts.", file=sys.stderr)
            return None
        
        with ThreadPoolExecutor(max_workers=16) as executor:
            segment_paths = list(executor.map(download_ts, ts_urls, range(len(ts_urls))))
        segment_paths = [p for p in segment_paths if p is not None]
        if len(segment_paths) < len(ts_urls):
            missing = len(ts_urls) - len(segment_paths)
            error_msg = f"{missing} segments failed to download. Delete the lock file and rerun the script to retry."
            print(error_msg, file=sys.stderr)
            log_error(error_msg)
    
    except Exception as e:
        error_msg = f"Failed to download segments: {e}"
        print(error_msg, file=sys.stderr)
        log_error(error_msg)
        update_progress(filename, 0, 100, 0)  # Reset progress on error
        semaphore.release()
        return
    
    # --- Phase 2: now merge the segments with ffmpeg locally ---
    temporary_file_path = Path(ts_folder, filename)  # Download location
    list_file = ts_folder / "segments.txt"
    with open(list_file, "w") as f:
        for ts_path in sorted(segment_paths):
            f.write(f"file '{ts_path.name}'\n")

    ffmpeg = subprocess.run([
        'ffmpeg',
        '-y',  # Overwrite output file if it already exists
        '-f', 'concat',
        '-safe', '0',
        '-protocol_whitelist', 'file,http,https,tcp,tls',
        '-hwaccel', 'auto',  # Hardware acceleration
        '-i',  'segments.txt',  # Input file
        '-c', 'copy',  # Codec name
        '-movflags', '+faststart',  # optional, improves mp4 playback
        filename  # Output file
    ], cwd=ts_folder, capture_output=True)

    if ffmpeg.returncode != 0:  # Print debug output in case of error
        error_msg = f"FFmpeg failed with return code {ffmpeg.returncode}"
        print(f"Error during download of \"{filename}\" with ffmpeg:", file=sys.stderr)
        print(f"Playlist file: {playlist_url}", file=sys.stderr)
        print(f"Designated download location: {temporary_file_path}", file=sys.stderr)
        print(f"Designated output location: {output_file_path}", file=sys.stderr)
        print(f"Output of ffmpeg to stdout:\n{ffmpeg.stdout.decode('utf-8')}", file=sys.stderr)
        print(f"Output of ffmpeg to stderr:\n{ffmpeg.stderr.decode('utf-8')}", file=sys.stderr)
        
        # Log the error
        log_error(f"FFmpeg failed: {error_msg}")
        log_error(f"FFmpeg stderr: {ffmpeg.stderr.decode('utf-8')}")
        return

    print(f"Download of {filename} completed after {(time.time() - download_start_time):.0f}s")
    log(f"Completed {filename} in {(time.time() - download_start_time):.1f}s "
    f"({len(segment_paths)} segments)")
    
    # Mark as completed in progress tracking
    update_progress(filename, 100, 100, 0)  # 100% completed
    
    shutil.copy2(temporary_file_path, output_file_path)  # Copy original file to output location    
    print(f"Completed {filename} after {(time.time() - download_start_time):.0f}s")
    temporary_file_path.unlink()  # Delete temp file
    Path(output_file_path.as_posix() + ".lock").unlink()  # Remove lock file
    shutil.rmtree(ts_folder)  # Remove ts folder
    semaphore.release()  # Release lock

def cleanup_all_temp_files():
    """Clean up all temporary files and folders created by downloader"""
    try:
        import tempfile
        import shutil
        
        temp_dir = Path(tempfile.gettempdir())
        
        # Remove progress file
        progress_file = temp_dir / "tum_download_progress.json"
        if progress_file.exists():
            progress_file.unlink()
            print(f"Removed progress file: {progress_file}")
        
        # Remove any tum_video_scraper temp folders
        tum_temp_dir = temp_dir / "tum_video_scraper"
        if tum_temp_dir.exists():
            shutil.rmtree(tum_temp_dir)
            print(f"Removed temp directory: {tum_temp_dir}")
            
        # Remove any _ts folders in temp directory
        for item in temp_dir.iterdir():
            if item.is_dir() and item.name.endswith('_ts'):
                try:
                    shutil.rmtree(item)
                    print(f"Removed temp folder: {item}")
                except Exception as e:
                    print(f"Failed to remove temp folder {item}: {e}")
    except Exception as e:
        print(f"Error cleaning up temp files: {e}")
