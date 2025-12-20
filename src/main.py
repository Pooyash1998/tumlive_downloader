import os
import tempfile
from gui import main as gui_main
from multiprocessing import Semaphore
from pathlib import Path
import yaml

def load_config_file():
    """Load configuration from config file"""
    config_file_paths = [
        Path("config.yml"),
        Path("../config.yml"), 
        Path("config.yaml"),
        Path("../config.yaml")
    ]
    
    config_file_path = None
    for path in config_file_paths:
        if path.exists():
            config_file_path = path
            break
    
    if not config_file_path:
        raise Exception("No config file found. Please create config.yml or config.yaml") 
        
    with open(config_file_path, "r") as config_file:
        cfg = yaml.load(config_file, Loader=yaml.SafeLoader)
    return cfg

def parse_destination_folder(cfg) -> Path:
    """Parse and create destination folder from config"""
    destination_folder_path = None
    if 'Output-Folder' in cfg: 
        destination_folder_path = Path(cfg['Output-Folder'])
    if not destination_folder_path:
        raise Exception("The supplied OUTPUT_FOLDER is invalid")
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

def parse_maximum_parallel_downloads(cfg) -> Semaphore:
    """Parse maximum parallel downloads from config"""
    maximum_parallel_downloads = 3
    if 'Maximum-Parallel-Downloads' in cfg:
        maximum_parallel_downloads = cfg['Maximum-Parallel-Downloads']
    return Semaphore(maximum_parallel_downloads)

def parse_username_password(cfg) -> tuple[str | None, str | None]:
    """Parse username and password from config"""
    username = cfg.get('Username', None)
    password = cfg.get('Password', None)
    return username, password

def main():    
    gui_main()