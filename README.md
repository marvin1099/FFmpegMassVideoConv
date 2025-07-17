# FFmpegMassVideoConv

**Mass video conversion using FFmpeg and a simple cross-platform Python script**
- Works on **Windows**, **macOS**, and **Linux**
- Requires **no extra Python dependencies**
- Supports **multi-PC conversions via shared network drives**

Main Repo: [codeberg.org/marvin1099/FFmpegMassVideoConv](https://codeberg.org/marvin1099/FFmpegMassVideoConv)  
Backup Repo: [github.com/marvin1099/FFmpegMassVideoConv](https://github.com/marvin1099/FFmpegMassVideoConv)

---

## Features

* **Saves your last CLI settings** as a default config on your system
* **Task configs per folder** track what’s converted, failed, or canceled
* **Simulation mode** (`-S`) to preview conversions without running FFmpeg
* **Auto-remove failed outputs** (`-x`) and/or delete originals after success (`-X`)  
* **Limit conversions per run** with `-m` (`-1` for infinite)
* **Multi-PC support** over shared drives (e.g., SMB)
* **Safe recovery** with task locking and PC UUIDs

---

## Requirements

Make sure both tools are installed and added to your system `PATH`:

1. [FFmpeg](https://ffmpeg.org/)
2. [Python 3](https://www.python.org/)

---

## Installation

Download the script from the [releases page](https://codeberg.org/marvin1099/FFmpegMassVideoConv/releases)

Run it like this in the console (Linux/macOS):
```bash
chmod +x path/to/FFmpegConv.py
python path/to/FFmpegConv.py /your/target/dir
```

On Windows run via cmd:
```cmd
python path\to\FFmpegConv.py X:\your\target\dir
```

The paths can be given in relative format as well (from working path), eg:
```bash
python path/to/FFmpegConv.py your/subdirectory/
```

The python keyword at the start of the command can also be removed as long as you have python installed correctly.  
You will also have to add ./ (.\ on Windows) in front if you are in the same directory as the script.

---

## About Config Files

There are **two config types**:

### 1. **Default Settings Config** (`-c PATH`)

* Stores your last-used CLI settings (output format, codec, etc.)
* The default is saved in:
  * **Linux**: `~/.config/ffmpeg_mass_conv_helper/default_conversion_settings.json`
  * **Windows**: `%APPDATA%\ffmpeg_mass_conv_helper\default_conversion_settings.json`
  * **macOS**: `~/Library/Application Support/ffmpeg_mass_conv_helper/default_conversion_settings.json`

* You can manually specify this with `-c /path/to/config.json`
* Relative paths for -c will allways start in the same folder as default_conversion_settings.json
* Great for presets or different use cases (e.g., Youtube vs Backup Vault).  
  For the vault you may use a high qualty conversion config; while for YT may use a low qualty conversion config.

### 2. **Folder Task Configs**

* Automatically stored as `conversion-config.json` **inside the target directory**
* Tracks:
  * Tasks and their **status** (`todo`, `completed`, `failed`, `canceled`)
  * The **worker UUID** that created or owns a task
  * Live **timestamps** for safe soft-locking  
    The timestamps in the task config ensures no two PCs work on the same task, even after power loss.

---

## Network Drive Support

Want to run the script from multiple PCs (e.g., a gaming and streaming PC)?  
Just **mount the same shared folder** on both machines using **SMB** or similar.  
This will speed up the conversion of a big video amount for each PC that is running the script.

Each PC:

* Only works on its own assigned tasks
* Won’t touch files owned by another
* Resumes safely after interruptions

*Search online for “create SMB share” (for making one) and “mount SMB share” (to add a exiting one) for shared drive help.*

---

## Usage Examples

Convert all video files in a folder:

```bash
python FFmpegConv.py /media/Videos
```

Change output filename style:

```bash
python FFmpegConv.py -o {n}-q22.mp4 -d /media/Videos
```

Use custom codec settings (The placholder {a}) :

```bash
python FFmpegConv.py -v {a} {b} 20 -d /media/Videos
```

Limit to 5 files per run:

```bash
python FFmpegConv.py -m 5 -d /media/Videos
```

Simulate without converting:

```bash
python FFmpegConv.py -S -d /media/Videos
```

Use a custom config:

```bash
python FFmpegConv.py -c ~/.config/my_custom_settings.json -d /media/Videos
```

---

## CLI Argument Overview

Check [Placeholders in Arguments](#placeholders-in-arguments) On how the placeholders {a}, {b}, {c}, {n}, or {e} work.

```text
usage: mass-convert.py [-h] [-c CONFIG_FILE] [-f FFMPEG] [-r REGEX [REGEX ...]] [-w WORKINGDIR] [-o OUTPUT] [-s START [START ...]]
[-v VIDEO [VIDEO ...]] [-a AUDIO [AUDIO ...]] [-e ENDING [ENDING ...]] [-d DIRECTORIES [DIRECTORIES ...]]
[-x [REMOVE_FAILED]] [-X [REMOVE]] [-m MAXCONVERT] [-S SIMULATE]

options:
-h, --help            show this help message and exit
-c, --config-file CONFIG_FILE
                      Set the default settings file location (default; not stored: /home/marvin/.config/ffmpeg_mass_conv_helper/default_conversion_settings.json)
-f, --ffmpeg FFMPEG   Set ffmpeg path (default: 'ffmpeg')
-r, --regex REGEX [REGEX ...]
                      Regex'es to search for in file name (default: ['.*\.mp4$','.*\.mkv$'])
-w, --working-dir WORKINGDIR
                      Set the working directory
-o, --output OUTPUT   Output file sting, use {n}/{e} for the filename/extension (default {n}-q22.{e})
-s, --start START [START ...]
                      The start of the FFmpeg command (default ['-y'])
-v, --video-encoder VIDEO [VIDEO ...]
                      Video encoder (default: ['hevc_nvenc','-qp','22'])
-a, --audio-encoder AUDIO [AUDIO ...]
                      Audio encoder (default: ['copy'])
-e, --ending ENDING [ENDING ...]
                      The end of the FFmpeg command (default=['-map','0'])
-d, --directories DIRECTORIES [DIRECTORIES ...]
                      Explicitly specified directories to process
-x, --remove-failed [REMOVE_FAILED]
                      Set off by using FALSE to disable deleting any file made by ffmpeg that resulted in an error
-X, --remove [REMOVE]
                      Enable deletion of original files with TRUE (WARNING: THEY WONT BE RECOVERABLE)
-m, --maxconvert MAXCONVERT
                      Maximum number of videos to convert before exiting (default: unlimited; set via -1)
-S, --simulate SIMULATE
                      Simulate prosseing with TRUE (wont mark tasks as pending, failed, canceled or completed)
```

---

## What Gets Tracked

Each run saves conversion results per folder in the config file named conversion-config.json:

| Status      | Meaning                             |
| ----------- | ----------------------------------- |
| `todo`      | Task not yet started                |
| `pending`   | Task currently in progress          |
| `completed` | Task finished successfully          |
| `failed`    | Task failed or ffmpeg errored       |
| `canceled`  | Task was interrupted (e.g., Ctrl+C) |

---

## Placeholders in Arguments

You can use dynamic placeholders like `{a}`, `{b}`, `{c}`, `{n}`, and `{e}` in these arguments:

* `--start`, `--video-encoder`, `--audio-encoder`, `--ending`, `--regex`, `--output`

Default video encoder (--video-encoder):

```json
["hevc_nvenc", "-qp", "22"]
```

Override like this:

```bash
-v libx264 {b} {c}
```

Becomes:

```bash
-v libx264 -qp 22
```

For output name:

```bash
-o {n}-q22.{e}
```

→ `my_video-q22.mp4`

To check the defaults for the converter run `FFmpegConv.py -h` or go to section [CLI Argument Overview](#cli-argument-overview).
