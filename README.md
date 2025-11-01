[![TUM](https://custom-icon-badges.demolab.com/badge/TUM-exzellent-0065bd.svg?logo=tum_logo_2023)](https://www.tum.de/)
[![TUM-Live](https://custom-icon-badges.demolab.com/badge/TUM--Live-live-e5312b.svg?logo=tum_live_logo)](https://live.rbg.tum.de/)

# Docker

The suggested way to run this project is with [Docker](https://docs.docker.com/engine/reference/commandline/run/):

```bash
docker run -it -v ./config.yml:/app/config.yml -v target_location:/app/output ghcr.io/valentin-metz/tum_video_scraper:master
```

You'll need to link in the configuration file `config.yml`.
You can find an example in the root of this repository under `example_config.yml`.
The output folder you specify in the config file will be the target location *inside* the docker container,
so make sure to mount your target location to `/app/output`.

# How to find subject identifiers?

Subject identifiers are used to specify the subjects you want to download.

## TUM-Live:

For [TUM-Live](https://live.rbg.tum.de/), you can find them in the URL of your lecture series.

Finally, you can specify the video stream you want to download.
Usually TUM-Live offers three:
1. The combined view (specified with `:COMB` after the subject identifier)
2. The presentation view (specified with `:PRES` after the subject identifier)
3. The presenter camera view (specified with `:CAM` after the subject identifier)

# There are `.lock` files in my output folder!

The `.lock` files are used to prevent the same video from being downloaded twice.
They are generated at the start of a run, and if the run gets interrupted, they will not be deleted.
If you want to run the scraper again, you'll need to delete the `.lock` files manually.

You can use this feature to do partial downloads of a lecture series.
Simply start the scraper, interrupt it after the `.lock` files have been created,
and delete only those `.lock` files of which you want to download the videos.

-----

You won't need anything below this line if you are running from Docker.

-----

# Installation

If you want to run this project directly from the python source,
you'll need to install the following system dependencies:

```
python  >= 3.11
ffmpeg  >= 6.1
firefox >= 120.0
geckodriver >= 0.33
```

In addition to that, you'll need the python dependencies specified in `requirements.txt`.
Create a virtual environment (in the project folder) and install project-dependencies into it:

```bash
python3 -m venv venv
source ./venv/bin/activate
python3 -m pip install -U pip
python3 -m pip install -U -r requirements.txt
```

Run the project with:

```bash
python3 src/main.py -c config.yml
```
