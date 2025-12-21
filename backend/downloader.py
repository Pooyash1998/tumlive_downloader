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

def log(msg: str):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def download_list_of_videos(videos: list[tuple[str, str]],
                            output_folder_path: Path, tmp_directory: Path,
                            semaphore: Semaphore) -> [Process]:
    child_process_list = []
    for filename, url in videos:
        filename = re.sub('[\\\\/:*?"<>|]|[\x00-\x20]', '_', filename) + ".mp4"  # Filter illegal filename chars
        output_file_path = Path(output_folder_path, filename)
        output_file_path_jc = Path(re.sub(r'\.(?=[^.]*$)', '_jc.', output_file_path.as_posix()))  # Add _jc to filename
        """We use locks to prevent processing the same video twice (e.g. if we run in multiple independent instances)"""
        """Locks can also be created by the user to keep us from downloading a specific video"""
        if not (Path(output_file_path.as_posix() + ".lock").exists()  # Check if lock file exists
                or output_file_path.exists()
                or output_file_path_jc.exists()):  # Check if file exists (we downloaded and converted it already)
            Path(output_file_path.as_posix() + ".lock").touch()  # Create lock file
            child_process = Process(target=download,  # Download video in separate process
                                    args=(filename, url,
                                          output_file_path, output_file_path_jc, tmp_directory,
                                          keep_original, jump_cut,
                                          semaphore))
            child_process.start()
            child_process_list.append(child_process)
    return child_process_list

def download(filename: str, playlist_url: str,
             output_file_path: Path, tmp_directory: Path,
             keep_original: bool,
             semaphore: Semaphore):
    
    print(f"Download of {filename} started")
    semaphore.acquire()  # Acquire lock
    download_start_time = time.time()  # Track download time
    # --- Phase 1: we parse the playlist and download its .ts segments in parallel ---
    try:
        playlist = m3u8.load(playlist_url)
        ts_urls = [urljoin(playlist_url, seg.uri) if not seg.uri.startswith("http") else seg.uri
                   for seg in playlist.segments]
        ts_folder = Path(tmp_directory, f"{filename}_ts")
        ts_folder.mkdir(parents=True, exist_ok=True)

        lock = Lock()
        # Progress bar for each Lecture
        pbar = tqdm(total=len(ts_urls), desc=f"{filename}", position=0, leave=True, dynamic_ncols=True)

        def download_ts(ts_url, index):
            nonlocal pbar
            ts_path = ts_folder / f"{index:05d}.ts"
            if ts_path.exists():
                with lock:
                    pbar.update(1)
                return ts_path # Skip download if file already exists
            
            max_retries = 5
            for attempt in range(max_retries):
                try:
                    r = requests.get(ts_url, stream=True, timeout=15)
                    r.raise_for_status()
                    with open(ts_path, "wb") as f:
                        for chunk in r.iter_content(1024*1024):
                            if chunk:
                                f.write(chunk)
                    with lock:
                        pbar.update(1)
                    return ts_path # Success -> Exit loop
                
                except Exception as e:
                    print(f"[Retry {attempt + 1}/{max_retries}] Failed to download segment {ts_url}: {e}", file=sys.stderr)
                    time.sleep(2 ** attempt)  # Exponential backoff
            print(f"Failed to download segment {index} after {max_retries} failed attempts.", file=sys.stderr)
            return None 
        
        with ThreadPoolExecutor(max_workers=16) as executor:
            segment_paths = list(executor.map(download_ts, ts_urls, range(len(ts_urls))))
        segment_paths = [p for p in segment_paths if p is not None]
        if len(segment_paths) < len(ts_urls):
            missing = len(ts_urls) - len(segment_paths)
            print(f"{missing} segments failed to download for {filename}.Delete the lock file and rerun the script to retry.", file=sys.stderr)
    
    except Exception as e:
        print(f"Failed to download segments for {filename}: {e}", file=sys.stderr)
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
        print(f"Error during download of \"{filename}\" with ffmpeg:", file=sys.stderr)
        print(f"Playlist file: {playlist_url}", file=sys.stderr)
        print(f"Designated download location: {temporary_file_path}", file=sys.stderr)
        print(f"Designated output location: {output_file_path}", file=sys.stderr)
        print(f"Output of ffmpeg to stdout:\n{ffmpeg.stdout.decode('utf-8')}", file=sys.stderr)
        print(f"Output of ffmpeg to stderr:\n{ffmpeg.stderr.decode('utf-8')}", file=sys.stderr)
        return

    print(f"Download of {filename} completed after {(time.time() - download_start_time):.0f}s")
    log(f"Completed {filename} in {(time.time() - download_start_time):.1f}s "
    f"({len(segment_paths)} segments)")
    shutil.copy2(temporary_file_path, output_file_path)  # Copy original file to output location    
    print(f"Completed {filename} after {(time.time() - download_start_time):.0f}s")
    temporary_file_path.unlink()  # Delete temp file
    Path(output_file_path.as_posix() + ".lock").unlink()  # Remove lock file
    shutil.rmtree(ts_folder)  # Remove ts folder
    semaphore.release()  # Release lock

