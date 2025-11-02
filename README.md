[![TUM](https://custom-icon-badges.demolab.com/badge/TUM-exzellent-0065bd.svg?logo=tum_logo_2023)](https://www.tum.de/) [![TUM-Live](https://custom-icon-badges.demolab.com/badge/TUM--Live-live-e5312b.svg?logo=tum_live_logo)](https://live.rbg.tum.de/)

# About

This repository was initially forked from [Valentin-Metz/tum_video_scraper](https://github.com/Valentin-Metz/tum_video_scraper).  
However, due to massive structural changes in the TUM-Live platform design, most parts of the original codebase had to be rewritten to remain compatible with the updated lecture streaming system.

Changes include: lecture URL handling, file handling and temporary storage, and general refactoring for better compatibility and reliability.  

Downloader logic – Previously, downloading was slow because `ffmpeg` streamed the M3U8 playlist sequentially. Now, all TS segments are downloaded concurrently and then merged, greatly improving speed and efficiency.  

Despite these extensive modifications, several nice features of the original project remain unchanged, such as the CLI argument parsing logic, jump-cut functionality (using `auto-editor`), and the file locking mechanism.  

Overall, while the codebase has been heavily refactored to accommodate TUM-Live’s redesign, the goal remains the same: **reliable, automated downloading and processing of TUM lectures, now much faster thanks to parallel segment handling.**

---

# Usage

This scraper allows you to download TUM-Live lectures, optionally skip silence with jump-cut, and save them as MP4 files. There are several ways to do this.

## 1. GUI

You can run the script `main.py` without any arguments to start the graphical interface.

Passing even one parameter disables the GUI and switches to CLI mode.

---

## 2. Command-line Interface (CLI)

You can use the script in the terminal and pass your TUM credentials and other options as command-line flags, or you can use a configuration file.

If you want the config file to be used, specify it with:

```bash
python3 main.py -c config.yml
```

---

### How to set up the config file

Use `example_config.yml` as a template. You can set various options there, but you don’t have to include all of them. Command-line arguments take priority over entries in the config file.

To specify exactly which courses should be downloaded, set them manually in the config file. There is no CLI argument for this to keep the interface clean.
If the `TUM_LIVE` entry is omitted, the program automatically fetches all registered courses in your account.

Example:

```yaml
TUM_LIVE:
  "ML": "https://live.rbg.tum.de/?year=2025&term=W&slug=WiSe25_26_ML&view=3"
  "IDL": "https://live.rbg.tum.de/?year=2025&term=W&slug=WiSe25_26_ItDL&view=3"
```

Each entry is the course name followed by its URL, which you can find on TUM-Live when clicking on a course.

---

### Selecting the video stream

TUM-Live usually offers three stream variants:

1. The combined view (specified with `:COMB` after the subject identifier)
2. The presentation view (specified with `:PRES` after the subject identifier)
3. The presenter camera view (specified with `:CAM` after the subject identifier)

The default is the combined view.

---

### Jump-cut conversion

If you want to enable jump-cut conversion (using `auto-editor`), set the respective flag in the config file or CLI. Note that this process will slow down the overall runtime.

---

## Docker

The suggested way to run this project is with Docker:

```bash
docker 
```

You’ll need to link in the configuration file `config.yml`.
You can find an example in the root of this repository under `example_config.yml`.
The output folder you specify in the config file will be the target location inside the Docker container,
so make sure to mount your desired local folder to `/app/output`.

---

## You won’t need anything below this line if you are running it from Docker.

---

# Installation

If you want to run this project directly from the Python source,
you’ll need to install the following system dependencies:

```
python  >= 3.13
ffmpeg  >= 6.1
firefox >= 120.0
geckodriver >= 0.33
```

You’ll also need the Python dependencies listed in `requirements.txt`.

Create a virtual environment (in the project folder) and install dependencies, or use Conda to manage both system and package dependencies.

For example, using venv:

```bash
python3 -m venv venv
source ./venv/bin/activate
python3 -m pip install -U pip
python3 -m pip install -U -r requirements.txt
```

Run the project (assuming your working directory is `/src`):

```bash
python3 main.py -c config.yml
```

# Lock files (`.lock`)

`.lock` files are used to prevent the same video from being downloaded twice.
They are created at the start of a run and deleted when the run completes.

If the process is interrupted, leftover `.lock` files will remain.
You can safely delete them manually before restarting the scraper.

You can also use this feature to perform partial downloads of a lecture series.
Simply start the scraper, interrupt it after the `.lock` files are created,
and delete only those `.lock` files corresponding to the videos you want to redownload.
# TODO 
- [X] make sure tmp folder is removed after execution ends.
- [X] change .lock file logic to consider .ts segments.
- [ ] Improve GUI design and error reporting.
- [ ] Add support for setting stream mode via arg or cfg.
- [ ] Docker file.
- [ ] tests for CLI and config parsing.
- [X] Show Progress instead of Logging messeages.
