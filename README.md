# FFmpegMassVideoConv

**Mass video conversion using FFmpeg and a simple cross-platform Python script**
- Works on **Windows**, **macOS**, and **Linux**
- Requires **no extra Python dependencies**
- Supports **multi-PC conversions via shared network drives**
- **Path translation** for PCs with different mount points
- **Timestamp backlog** for SMB shares where `os.utime()` is blocked

Main Repo: [codeberg.org/marvin1099/FFmpegMassVideoConv](https://codeberg.org/marvin1099/FFmpegMassVideoConv)  
Backup Repo: [github.com/marvin1099/FFmpegMassVideoConv](https://github.com/marvin1099/FFmpegMassVideoConv)

---

## Features

* **Saves your last CLI settings** as a default config on your system
* **Task configs per folder** track what's converted, failed, or canceled
* **Simulation mode** (`-S` / `-n`) to preview conversions without running FFmpeg
* **Auto-remove failed outputs** (`-x`) and/or delete originals after success (`-X`)
* **Limit conversions per run** with `-m` (`-1` for unlimited)
* **Multi-PC support** over shared drives (e.g., SMB)
* **Path translation** — different mount points on different PCs (`-A`, `-R`, `-L`, `-P`, `-U`)
* **Timestamp backlog** — when setting timestamps fails on SMB, entries are saved and retried later (`-t`)
* **Safe recovery** with distributed locking and worker UUIDs
* **Escape prefix** (`^`) to pass flags like `-qp` or `-map` through argparse

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
chmod +x path/to/ffmpeg-conv.py
python path/to/ffmpeg-conv.py /your/target/dir
```

On Windows run via cmd:
```cmd
python path\to\ffmpeg-conv.py X:\your\target\dir
```

The paths can be given in relative format as well (from working path), eg:
```bash
python path/to/ffmpeg-conv.py your/subdirectory/
```

The python keyword at the start of the command can also be removed as long as you have python installed correctly.  
You will also have to add ./ (.\ on Windows) in front if you are in the same directory as the script.

---

## About Config Files

There are **two config types**:

### 1. **Default Settings Config** (`-c PATH`)

* Stores your last-used CLI settings (output format, codec, path maps, etc.)
* The default is saved in:
  * **Linux**: `~/.config/ffmpeg_mass_conv/settings.json`
  * **Windows**: `%APPDATA%\ffmpeg_mass_conv\settings.json`
  * **macOS**: `~/Library/Application Support/ffmpeg_mass_conv/settings.json`

* You can manually specify this with `-c /path/to/config.json`
* Relative paths for `-c` are resolved relative to the default config directory
* Great for presets or different use cases (e.g., Youtube vs Backup Vault)

### 2. **Folder Task Configs**

* Automatically stored as `conversion-config.json` **inside the target directory**
* Tracks:
  * Tasks and their **status** (`todo`, `pending`, `completed`, `failed`, `killed`, `canceled`)
  * The **worker UUID** and **PID** that claimed a task
  * Live **timestamps** for safe soft-locking
  * **Timestamp backlog** entries for failed `os.utime()` calls

---

## Network Drive Support

Want to run the script from multiple PCs (e.g., a gaming and streaming PC)?  
Just **mount the same shared folder** on both machines using **SMB** or similar.  
This will speed up the conversion of a big video amount for each PC that is running the script.

### Path Translation (Different Mount Points)

If PCs mount the same share at different paths (e.g., `//nas/videos` vs `/mnt/videos`), define translations:

```bash
# Add a translation rule (saved in your local settings)
python ffmpeg-conv.py -A nas-share //nas/videos /mnt/videos

# List saved translations
python ffmpeg-conv.py -L

# Activate one or more for this run
python ffmpeg-conv.py -P nas-share /your/target/dir

# Activate all saved translations
python ffmpeg-conv.py -U /your/target/dir
```

Use `-p` to prefer local paths (skip translation if the path already exists locally).

Each PC:

* Only works on its own assigned tasks
* Won't touch files owned by another
* Resumes safely after interruptions

*Search online for "create SMB share" (for making one) and "mount SMB share" (to add a existing one) for shared drive help.*

### Timestamp Backlog

SMB shares often block `os.utime()`. When this happens, the script saves a backlog entry under `\0timestamp_backlog` in the shared config. On every subsequent run the backlog is retried; entries are removed only on success.

To exclusively retry the backlog without starting any conversions:

```bash
python ffmpeg-conv.py -t true /your/target/dir
```

This lets a separate script (e.g., a cron job that remounts with different options) fix timestamps quickly.

---

## Usage Examples

Convert all video files in a folder:

```bash
python ffmpeg-conv.py /media/Videos
```

Process multiple folders:

```bash
python ffmpeg-conv.py /media/Videos /media/Movies
```

Change output filename style:

```bash
python ffmpeg-conv.py -o {n}-q22.mp4 /media/Videos
```

Use custom codec settings (the placeholder {a}):

```bash
python ffmpeg-conv.py -v libx264 {b} 18 /media/Videos
```

Override only part of a default list with `^` escape:

```bash
python ffmpeg-conv.py -e ^-map 0 ^-map_metadata 0 ^-c:s copy /media/Videos
```

Limit to 5 files per run:

```bash
python ffmpeg-conv.py -m 5 /media/Videos
```

Simulate without converting (one-off, not saved):

```bash
python ffmpeg-conv.py -n /media/Videos
```

Simulate (saved in config):

```bash
python ffmpeg-conv.py -S true /media/Videos
```

Use a custom config:

```bash
python ffmpeg-conv.py -c ~/.config/my_custom_settings.json /media/Videos
```

Retry timestamp backlog only (no conversions):

```bash
python ffmpeg-conv.py -t true /media/Videos
```

---

## CLI Argument Overview

Check [Placeholders in Arguments](#placeholders-in-arguments) on how `{a}`, `{b}`, `{c}`, `{d}`, `{n}`, and `{e}` work.

```text
usage: ffmpeg-conv.py [-h] [-c PATH] [-d DIR [DIR ...]] [-w PATH]
                      [-A ARG [ARG ...]] [-R NAME [NAME ...]] [-L]
                      [-P NAME [NAME ...]] [-U] [-p [Yes or No]] [-f BIN]
                      [-i FLAG] [-r PAT [PAT ...]] [-o TMPL] [-s ARG [ARG ...]]
                      [-v ARG [ARG ...]] [-a ARG [ARG ...]] [-e ARG [ARG ...]]
                      [-x [Yes or No]] [-X [Yes or No]] [-m MAX_CONVERT]
                      [-S [Yes or No]] [-n] [-k [Yes or No]] [-t [Yes or No]]
                      [DIR ...]

Configuration:
  -c, --config-file PATH      Local user settings file (not shared)

Directories:
  DIR                         Target directories (positional)
  -d, --dirs DIR [DIR ...]    Additional target directories (flag form)
  -w, --working-dir PATH      Change working directory

Path translation:
  -A, --path-add NAME REMOTE LOCAL    Add/update a translation
  -R, --path-remove NAME [NAME ...]   Remove saved translation(s)
  -L, --path-list                     List all saved translations
  -P, --path-use NAME [NAME ...]      Activate specific translations
  -U, --path-use-all                  Activate all saved translations
  -p, --prefer-local [Yes or No]      Skip translation when local path exists

FFmpeg settings:
  -f, --ffmpeg BIN                    FFmpeg binary path (default: ffmpeg)
  -i, --input-flags FLAG              Flags before input (default: -i)
  -r, --regex PAT [PAT ...]           Filename regex patterns
  -o, --output TMPL                   Output template: {n}=name, {e}=ext
  -s, --start ARG [ARG ...]           Args after ffmpeg, before input
  -v, --video-encoder ARG [ARG ...]   Video encoder (-c:v is automatic)
  -a, --audio-encoder ARG [ARG ...]   Audio encoder (-c:a is automatic)
  -e, --ending ARG [ARG ...]          Args appended after output

Behaviour:
  -x, --remove-failed [Yes or No]     Delete output on failure (default: on)
  -X, --remove-original [Yes or No]   Delete source after success (default: off)
  -m, --max-convert MAX_CONVERT       Stop after N successes (-1 = unlimited)
  -S, --simulate [Yes or No]          Simulate mode (saved)
  -n, --dry-run                       One-off simulate (not saved)
  -k, --keep-timestamps [Yes or No]   Restore source timestamps (default: on)
  -t, --timestamp-backlog-only [Yes or No]  Retry backlog and exit
```

Default FFmpeg command:
```text
ffmpeg -y -i INPUT -c:v hevc_nvenc -qp 22 -c:a copy -map 0 -map_metadata 0 OUTPUT
```

---

## What Gets Tracked

Each run saves conversion results per folder in the config file named `conversion-config.json`:

| Status      | Meaning                                   |
| ----------- | ----------------------------------------- |
| `todo`      | Task not yet started                      |
| `pending`   | Task currently in progress                |
| `completed` | Task finished successfully                |
| `failed`    | Task failed or ffmpeg errored             |
| `killed`    | Task was abandoned by a crashed worker    |
| `canceled`  | Task was interrupted (e.g., Ctrl+C)       |

---

## Timestamp Backlog (`\0timestamp_backlog`)

When `os.utime()` fails (common on SMB shares), the script stores an entry in the shared config:

```json
{
  "\0timestamp_backlog": [
    {
      "before_translated_path": "/mnt/videos/my_video-q22.mkv",
      "set_to_unix": 1712345678
    }
  ]
}
```

The key uses a null-byte prefix (`\0`), which can never appear in a real filename, just like the `\0lock` key used for distributed locking. Entries are automatically retried on every run and removed only on success.

---

## Placeholders in Arguments

You can use dynamic placeholders in list arguments. `{a}`, `{b}`, `{c}`, `{d}` expand to per-field defaults; `{n}` and `{e}` expand to the filename stem and extension at runtime.

Affected arguments: `--start`, `--video-encoder`, `--audio-encoder`, `--ending`, `--regex`, `--output`

Default video encoder (`-v`):
```text
{a} = hevc_nvenc    {b} = -qp    {c} = 22
```
Override like this:
```bash
-v libx264 {b} {c}
```
Becomes:
```text
-c:v libx264 -qp 22
```

Default ending (`-e`):
```text
{a} = -map    {b} = 0    {c} = -map_metadata    {d} = 0
```

For output name:
```bash
-o {n}-q22.{e}
```
→ `my_video-q22.mp4`

---

## Escape Prefix (`^`)

Values starting with `-` are intercepted by argparse as flags. Prefix with `^` to pass them literally:

```bash
# Without ^ argparse would interpret -qp as a flag
python ffmpeg-conv.py -v libx264 ^-qp 18 /media/Videos

# Same for -map, -map_metadata, etc.
python ffmpeg-conv.py -e ^-map 0 ^-map_metadata 0 ^-c:s copy /media/Videos
```

To check the full defaults and current help run `ffmpeg-conv.py -h`.
