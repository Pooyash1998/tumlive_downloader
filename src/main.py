import argparse
import os
import tempfile
from typing import List
from multiprocessing import Semaphore
from pathlib import Path
import yaml
import downloader
import tum_live


def load_config_file(args: argparse.Namespace):
    cfg = {}
    if args.config_file:
        config_file_path = Path("../",args.config_file)
        if not os.path.isfile(config_file_path):
            raise argparse.ArgumentTypeError("The supplied CONFIG_FILE does not exist.")
        with open(config_file_path, "r") as config_file:
            cfg = yaml.load(config_file, Loader=yaml.SafeLoader)
    return cfg

def parse_command_line_arguments():
    # Command line arguments take priority over config file !!
    parser = argparse.ArgumentParser(description="Download and jump-cut TUM-Lecture-Videos")
    parser.add_argument("-u", "--username", help="TUM-Username (go42tum)", type=str)
    parser.add_argument("-p", "--password", help="TUM-Password (must fit to the TUM-Username)", type=str)

    parser.add_argument("-k", "--keep", type=bool,
                        help="Whether to keep the original file of a downloaded video. Defaults to True. Optional.")
    parser.add_argument("-j", "--jump_cut", type=bool,
                        help="Whether to jump-cut the videos or not. Defaults to True. Optional.")

    parser.add_argument("-o", "--output_folder", type=Path,
                        help="Path to the output folder. Downloaded and converted videos get saved here.")
    parser.add_argument("-t", "--temp_dir", type=Path,
                        help="Path for temporary files. Defaults to the system specific tmp folder. Optional.")

    parser.add_argument("-d", "--maximum_parallel_downloads", type=int,
                        help="Maximal number of videos to download and convert in parallel. Defaults to 3. Optional.")
    parser.add_argument("-c", "--config_file", type=Path,
                        help="Path to a config file. Command line arguments take priority over config file. Optional.")
    return parser.parse_args()

def parse_destination_folder(args: argparse.Namespace, cfg) -> Path:
    destination_folder_path = None
    if args.output_folder:
        destination_folder_path = args.output_folder
    elif 'Output-Folder' in cfg: 
        destination_folder_path = Path(cfg['Output-Folder'])

    if not destination_folder_path:
        raise argparse.ArgumentTypeError("The supplied OUTPUT_FOLDER is invalid")
    destination_folder_path = Path(destination_folder_path)
    if not destination_folder_path.is_dir():
        destination_folder_path.mkdir(exist_ok=True)  # create the directory anyway
    return destination_folder_path

def parse_tmp_folder(args: argparse.Namespace, cfg) -> Path:
    tmp_directory = None
    if 'Temp-Dir' in cfg:
        tmp_directory = Path(cfg['Temp-Dir'])
    if args.temp_dir:
        tmp_directory = args.temp_dir
    if not tmp_directory:
        tmp_directory = Path(tempfile.gettempdir(), "tum_video_scraper")  # default: (/tmp/tum_video_scraper/)
    if not os.path.isdir(tmp_directory):
        tmp_directory.mkdir(exist_ok=True)  # Create temporary work-directory if it does not exist
    return tmp_directory

def parse_tum_live_subjects(cfg) -> List[tuple[str, str]]:
    return list(cfg.get("TUM-live", {}).items()) 


def parse_keep_original_and_jump_cut(args: argparse.Namespace, cfg) -> tuple[bool, bool]:
    keep_original = True
    jump_cut = True
    if 'Keep-Original-File' in cfg:
        keep_original = cfg['Keep-Original-File']
    if 'Jumpcut' in cfg:
        jump_cut = cfg['Jumpcut']
    if args.keep:
        keep_original = args.keep
    if args.jump_cut:
        jump_cut = args.jump_cut
    return keep_original, jump_cut


def parse_maximum_parallel_downloads(args: argparse.Namespace, cfg) -> Semaphore:
    maximum_parallel_downloads = 3
    if 'Maximum-Parallel-Downloads' in cfg:
        maximum_parallel_downloads = cfg['Maximum-Parallel-Downloads']
    if args.maximum_parallel_downloads:
        maximum_parallel_downloads = args.maximum_parallel_downloads
    # Keeps us from using massive amounts of RAM
    return Semaphore(maximum_parallel_downloads)


def parse_username_password(args: argparse.Namespace, cfg) -> tuple[str | None, str | None]:
    username = args.username or cfg.get('Username')
    password = args.password or cfg.get('Password')

    # Allows setting the password from stdin
    if username and not password:
        password = input("Please enter your TUM-Password (must fit to the TUM-Username):\n")

    return username, password


def parse_arguments():
    args = parse_command_line_arguments()
    cfg = load_config_file(args)

    tum_live_subjects = parse_tum_live_subjects(cfg)
    (keep_original, jump_cut) = parse_keep_original_and_jump_cut(args, cfg)

    destination_folder_path = parse_destination_folder(args, cfg)
    tmp_folder_path = parse_tmp_folder(args, cfg)

    semaphore = parse_maximum_parallel_downloads(args, cfg)

    (username, password) = parse_username_password(args, cfg)

    return tum_live_subjects, \
        keep_original, jump_cut, \
        destination_folder_path, tmp_folder_path, \
        semaphore, \
        username, password


def main():
    # We are a friendly background process
    os.nice(15)

    # Parse arguments
    tum_live_subjects, \
        keep_original, \
        jump_cut, \
        destination_folder_path, \
        tmp_folder_path, \
        semaphore, \
        username, \
        password = parse_arguments()

    print("Starting new run!")

    # Scrape TUM-live videos
    print("\nScanning TUM-live:")
    if not tum_live_subjects :
        driver, tum_live_subjects = tum_live.get_courses(username, password)
    else:
        course_names_only= [course[0] for course in tum_live_subjects]
        print("Found following Courses in the Config:")
        print('\n'.join(course_names_only))
        driver = tum_live.login(username, password)

    All_lectures_url = tum_live.get_lecture_urls (driver, tum_live_subjects)
    All_lectures_m3u8 = tum_live.get_playlist_url (driver, All_lectures_url)
    # Download videos
    print("\n--------------------\n")
    print("Starting downloads:")
    spawned_child_processes = []
    for subject, playlists in All_lectures_m3u8.items():
        subject_folder = Path(destination_folder_path, subject)
        subject_folder.mkdir(exist_ok=True)
        spawned_child_processes += downloader.download_list_of_videos(playlists,
                                                                      subject_folder, tmp_folder_path,
                                                                      keep_original, jump_cut,
                                                                      semaphore)
    for process in spawned_child_processes:
        process.join()

if __name__ == '__main__':
    import sys
    if len(sys.argv) > 1:
        main()  # Run CLI version if arguments are provided
    else:
        from gui import main as gui_main
        gui_main()  # Run GUI version if no arguments