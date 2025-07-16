#!/usr/bin/env python3

import subprocess
import platform
import argparse
import ctypes
import random
import json
import time
import os
import re

LOCK_KEY = 'on_write\0'
CONV_FILE = 'default_conversion_settings.json'


def get_config_dir():
    if platform.system() == "Windows":
        base_dir = os.environ.get("APPDATA", os.path.expanduser("~\\AppData\\Roaming"))
    elif platform.system() == "Darwin":
        base_dir = os.path.expanduser("~/Library/Application Support")
    else:
        base_dir = os.path.expanduser("~/.config")

    config_dir = os.path.join(base_dir, "ffmpeg_mass_conv_helper")
    os.makedirs(config_dir, exist_ok=True)
    return os.path.join(config_dir, "")

CONFIG_DIR = get_config_dir()

def load_last_config(CONFIG_PATH=os.path.join(CONFIG_DIR, CONV_FILE)):
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_last_config(args, ignore=[],original={},CONFIG_PATH=os.path.join(CONFIG_DIR, CONV_FILE)):
    save_args = dict(vars(args))
    try:
        for i in ignore:
            if i in save_args:
                del save_args[i]
        if original != save_args:
            with open(CONFIG_PATH, "w") as f:
                json.dump(save_args, f, indent=2)
            print(f"Last cli args where saved to:\n> {CONFIG_PATH}")
            print("")
    except Exception as e:
        print(f"Warning: Failed to save config: {e}")
        print("")

def str2bool(v):
    if isinstance(v, bool):
        return v
    return v.lower() in ("yes", "true", "t", "y", "1")

def parse_arguments():
    # Minimal parser to get the config file path early
    mini_parser = argparse.ArgumentParser(add_help=False)
    mini_parser.add_argument("-c", "--config-file", type=str, default=None)
    known_args, _ = mini_parser.parse_known_args()

    # Determine config file path
    default_config_file = os.path.join(CONFIG_DIR, CONV_FILE)
    config_file = known_args.config_file or default_config_file

    last_config = load_last_config(config_file)
    last_config_copy = dict(last_config)
    parser = argparse.ArgumentParser(
        description="Simple FFmpeg mass conversion tool\n"
                    "To use only some of the default args use {a} {b} {c}\n"
                    "For example for -v {a} {b} will result in -qp 22",
        epilog="The config will be named conversion-config.json and located in the currend conversion dir\n"
               "The default config will result in the following command in the selected directories:\n"
               "\tffmpeg -y -i FILEIN -c:v hevc_nvenc -rc constqp -qp 22 -c:a copy -map 0 FILEOUT",
        formatter_class=argparse.RawTextHelpFormatter
    )
    # here declare --config-file again to make it show in --help
    parser.add_argument("-c", "--config-file", type=str, default=config_file,
        help=f"Set the default settings file location (default; not stored): {default_config_file})")

    parser.add_argument('-f', '--ffmpeg', default=last_config.get('ffmpeg', 'ffmpeg'), help='Set ffmpeg path (default: \'ffmpeg\')')
    parser.add_argument('-r', '--regex', nargs='+', default=last_config.get('regex', ['{a}', '{b}']), help='Regex\'es to search for in file name (default: [\'.*\\.mp4$\',\'.*\\.mkv$\'])')
    parser.add_argument('-w', '--working-dir', dest="workingdir", default=last_config.get('workingdir', None), help='Set the working directory')
    parser.add_argument('-o', '--output', default=last_config.get('output', '{n}-q22.{e}'), help='Output file sting, use {n}/{e} for the filename/extension (default {n}-q22.{e})')
    parser.add_argument('-s', '--start', nargs='+', default=last_config.get('start', ['{a}']), help="The start of the FFmpeg command (default [\'-y\'])")
    parser.add_argument('-v', '--video-encoder', dest="video", nargs='+', default=last_config.get('video', ['{a}', '{b}', '{c}']), help='Video encoder (default: [\'hevc_nvenc\',\'-qp\',\'22\'])')
    parser.add_argument('-a', '--audio-encoder', dest="audio", nargs='+', default=last_config.get('audio',['{a}']), help='Audio encoder (default: [\'copy\'])')
    parser.add_argument('-e', '--ending', nargs='+', default=last_config.get('ending', ['{a}', '{b}']), help='The end of the FFmpeg command (default=[\'-map\',\'0\'])')
    parser.add_argument('-d', '--directories', nargs='+', default=[], help='Explicitly specified directories to process')
    parser.add_argument('-x', '--remove-failed', dest="remove_failed", type=str2bool, default=last_config.get('remove_failed', True), nargs='?', const=True, help='Enable to delete any file made by ffmpeg that resulted in an error')
    parser.add_argument('-X', '--remove', type=str2bool, default=last_config.get('remove', False), nargs='?', const=True, help='Enable deletion of original files (WARNING: THEY WONT BE RECOVERABLE)')
    parser.add_argument('-m', '--maxconvert', type=int, default=last_config.get('maxconvert', -1), help='Maximum number of videos to convert before exiting (default: unlimited; set via -1)')

    args, unknown_args = parser.parse_known_args()

    if args.workingdir and os.path.isdir(args.workingdir):
        os.chdir(args.workingdir)
    else:
        if args.workingdir and args.directories:
            print("Working dir invalid using active dir\n")
        args.workingdir = os.getcwd()

    args.directories = [directory for directory in args.directories + unknown_args if os.path.isdir(directory)]
    if not args.directories:
        args.directories = [directory for directory in last_config.get('directories', []) if os.path.isdir(directory)]

    if args.directories:
        save_last_config(args, ignore=["config_file", "workingdir"], original=last_config_copy)

        # replace placeholders via .format
        args.regex = [arg.format(a=".*\\.mp4$", b=".*\\.mkv$") for arg in args.regex]
        args.start = [arg.format(a="-y") for arg in args.start]
        if args.video:
            args.video = ["-c:v"] + [arg.format(a="hevc_nvenc",b="-qp",c="22") for arg in args.video]
        if args.audio:
            args.audio = ["-c:a"] + [arg.format(a="copy") for arg in args.audio]
        args.ending = [arg.format(a="-map",b="0") for arg in args.ending]

        return args
    else:
        parser.print_help()
        print("\nNo existing directories, to process, saved or given")
        exit(1)


def folders_process(folders, regex, output):
    videos = {}
    for folder in folders:
        for video in os.listdir(folder):
            vid_name = os.path.basename(video)
            if any(re.match(ft, vid_name) for ft in regex):
                video_name, video_extension = os.path.splitext(vid_name)
                output_name = output.format(n=video_name, e=video_extension[1:])
                if os.path.isabs(output_name):
                    print("A absulute path is set for output, this is problay not wanted")
                output_path = output_name

                if folder not in videos:
                    videos[folder] = {}
                videos[folder][video] = {
                    'worker': None,
                    'worker_uuid': None,
                    'status': 'todo',
                    'output': output_path
                }
    return videos


def load_folder_config(folder):
    config_path = os.path.join(folder, "conversion-config.json")
    if os.path.exists(config_path):
        with open(config_path, 'r') as config_file:
            config = json.load(config_file)
    else:
        config = {}
    return config, config_path


def save_folder_config(config, config_path):
    with open(config_path, 'w') as config_file:
        json.dump(config, config_file, indent=4)


def is_worker_active(pid):
    """Check if a process with the given PID is running."""
    if platform.system() == 'Windows':
        # Windows implementation
        PROCESS_QUERY_INFORMATION = 0x0400
        process_handle = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_INFORMATION, False, pid)

        if process_handle:
            ctypes.windll.kernel32.CloseHandle(process_handle)
            return True
        else:
            return False
    else:
        # Unix-like (Linux, macOS) implementation
        try:
            # os.kill with signal 0 checks if the process is running without sending any signal
            os.kill(pid, 0)
        except OSError:
            return False
        else:
            return True


def get_machine_uuid():
    if platform.system() == "Linux" or platform.system() == "Darwin":
        try:
            with open("/etc/machine-id", "r") as f:
                return f.read().strip()
        except FileNotFoundError:
            try:
                with open("/var/lib/dbus/machine-id", "r") as f:
                    return f.read().strip()
            except FileNotFoundError:
                return str(uuid.getnode())
    elif platform.system() == "Windows":
        try:
            import winreg
            key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography")
            value, _ = winreg.QueryValueEx(key, "MachineGuid")
            return value
        except Exception:
            return str(uuid.getnode())
    else:
        return str(uuid.getnode())


def deep_merge(base, add_or_overide):
    a, b = base, add_or_overide
    for key, b_val in b.items():
        if key in a:
            a_val = a[key]
            if isinstance(a_val, dict) and isinstance(b_val, dict):
                deep_merge(a_val, b_val)
            else:
                a[key] = b_val
        else:
            a[key] = b_val
    return a


def acquire_lock(folder, lock_timeout=60, wait_interval=random.randrange(30, 60, 1)/100, max_wait=120):
    """Try to acquire lock by setting LOCK_KEY timestamp."""
    start_wait = time.time()
    while True:
        now = time.time()
        config, config_path = load_folder_config(folder)
        on_write = config.get(LOCK_KEY, 0)

        # If lock is expired or not present
        if on_write < now - lock_timeout:
            config[LOCK_KEY] = now
            save_folder_config(config, config_path)
            return config, config_path

        if time.time() - start_wait > max_wait:
            raise TimeoutError(f"Could not acquire lock on {folder} after {max_wait} seconds")

        time.sleep(wait_interval)


def video_tasker(videos, args):
    worker_pid = os.getpid()
    if not worker_pid:
        raise NameError("Error getting own worker pid")

    worker_uuid = get_machine_uuid()
    if not worker_uuid:
        raise NameError("Error getting own worker uuid")

    KeyInterrupt = False
    for folder, folder_videos in videos.items():
        config, config_path = acquire_lock(folder)

        # Recover abandoned tasks
        override = {}
        for video, details in config.items():
            if isinstance(details, dict) and details['status'] == 'pending':
                worker_pid = details.get('worker')
                worker_uuid_old = details.get('worker_uuid')

                if not worker_uuid_old or (worker_uuid_old and worker_uuid_old == worker_uuid):
                    if not is_worker_active(int(worker_pid)):
                        override[video] = {}
                        override[video]['status'] = 'killed'
                        override[video]['worker'] = None
                        override[video]['worker_uuid'] = None

        loaded_config, config_path = load_folder_config(folder)
        config = deep_merge(loaded_config, override)

        # Delete any entrys that are a output file
        for video, details in dict(folder_videos.items()).items():
            if isinstance(details, dict) and details['output'] in folder_videos.keys():
                del folder_videos[details['output']]

        config[LOCK_KEY] = time.time()
        save_folder_config(config, config_path)

        # Merge new videos with existing config
        for video, details in folder_videos.items():
            if video not in config:
                # New video, add to config
                config[video] = details
            else:
                # Video exists in config
                if config[video]['status'] in ['todo', 'failed', 'killed', 'canceled']:
                    # Update output if the new format is different
                    if config[video]['output'] != details['output']:
                        config[video]['output'] = details['output']

        loaded_config, config_path = load_folder_config(folder)
        config = deep_merge(loaded_config, override)
        override[LOCK_KEY] = time.time()
        save_folder_config(config, config_path)

        Locked = False
        maxconvert = int(args.maxconvert)
        # Process videos
        for video, details in config.items():
            if maxconvert == 0:
                print(f"Max Convert amount of {args.maxconvert} reached")
                break

            override = {}
            if isinstance(details, dict) and details['status'] in ['todo', 'failed', 'killed', 'canceled']:
                try:
                    inputfile = os.path.join(folder, video)
                    if not os.path.isfile(inputfile):
                        print(f"Warning video file '{inputfile}' could not be found, skipping file...")
                        continue

                    override[video] = {}
                    override[video]['worker'] = worker_pid
                    override[video]['worker_uuid'] = worker_uuid
                    override[video]['status'] = 'pending'
                    if Locked:
                        loaded_config, config_path = acquire_lock(folder)
                        Locked = False
                    else:
                        loaded_config, config_path = load_folder_config(folder)

                    override[LOCK_KEY] = 0
                    config = deep_merge(loaded_config, override)
                    Locked = True
                    save_folder_config(config, config_path)

                    if os.path.isabs(details['output']):
                        output = details['output']
                    else:
                        output = os.path.join(folder, details['output'])

                    ffmpeg_cmd = [args.ffmpeg] + args.start + ['-i', inputfile] + args.video + args.audio + args.ending + [output]

                    print(f"\tRunning command:\n{args.ffmpeg} '{'\' \''.join(ffmpeg_cmd[1:])}'\n")
                except KeyboardInterrupt:
                    KeyInterrupt = True
                except Exception as e:
                    print(f"Error unknown Exception {e}, Exiting")
                    exit()
                try:
                    if not KeyInterrupt:
                        result = subprocess.run(ffmpeg_cmd)
                    else:
                        result = 1
                        KeyInterrupt = True
                except KeyboardInterrupt:
                    result = 1
                    KeyInterrupt = True
                except Exception as e:
                    result = 1
                try:
                    if result == 1 or result.returncode != 0:
                        # Mark task as failed
                        override[video]['status'] = 'canceled' if KeyInterrupt else 'failed'
                        print(f"\n\tConversion failed for {video}. Return code: {"130" if KeyInterrupt else "1" if result == 1 else result.returncode}\n")

                        if args.remove_failed:
                            if os.path.isfile(output):
                                os.remove(output)
                            else:
                                print(f"Warning could not delete broken output file, as file '{output}' was not found")
                        if args.remove:
                            print("Skipping removal of the original file, as the task has failed")
                    else:
                        # Mark task as completed
                        override[video]['status'] = 'completed'
                        print(f"\n\tConversion successful for {video}\n")

                        if args.remove:
                            if os.path.isfile(inputfile):
                                os.remove(inputfile)
                            else:
                                print("Warning could not delete original video, as it was not found")

                        if maxconvert > 0:
                            maxconvert -= 1

                    override[video]['worker'] = None
                    override[video]['worker_uuid'] = None

                    loaded_config, config_path = acquire_lock(folder)
                    Locked = False
                    override[LOCK_KEY] = 0
                    config = deep_merge(loaded_config, override)
                    Locked = True
                    save_folder_config(config, config_path)
                except KeyboardInterrupt:
                    KeyInterrupt = True
                    break
                except Exception as e:
                    break

                if KeyInterrupt:
                    raise KeyboardInterrupt

            if maxconvert == 0:
                print(f"Max Convert amount of {args.maxconvert} reached")
                break

        if not Locked:
            loaded_config, config_path = load_folder_config(folder)
            override = {LOCK_KEY: 0}
            config = deep_merge(loaded_config, override)
            Locked = True
            save_folder_config(config, config_path)

        if KeyInterrupt:
            raise KeyboardInterrupt

    print("\nAll Tasks where Finished")


def main():
    args = parse_arguments()
    videos = folders_process(args.directories, args.regex, args.output)
    video_tasker(videos, args)


if __name__ == "__main__":
    main()
