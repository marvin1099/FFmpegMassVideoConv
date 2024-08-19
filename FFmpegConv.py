#!/usr/bin/env python3

import subprocess
import platform
import argparse
import ctypes
import json
import os
import re


def parse_arguments():
    parser = argparse.ArgumentParser(
        description="Simple FFmpeg mass conversion tool\n"
                    "To use only some of the default args use {a} {b} {c}\n"
                    "For example for -v {b} will result in -qp",
        epilog="The config will be named conversion-config.json and located in the currend conversion dir\n"
               "The default config will result in the following command in the selected directories:\n"
               "\tffmpeg -y -i FILEIN -c:v hevc_nvenc -rc constqp -qp 22 -c:a copy -map 0 FILEOUT",
        formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument('-f', '--ffmpeg', default='ffmpeg', help='Set ffmpeg path (default: \'ffmpeg\')')
    parser.add_argument('-r', '--regex', nargs='+', default=['{a}', '{b}'], help='Regex to search for in file name (default: [\'.*\\.mp4$\',\'.*\\.mkv$\'])')
    parser.add_argument('-w', '--working-dir', dest="workingdir", default=None, help='Set the working directory')
    parser.add_argument('-o', '--output', default="{n}-q22.{e}", help='Output file sting, use {n}/{e} for the filename/extension (default {n}-q22.{e})')
    parser.add_argument('-s', '--start', nargs='+', default=['{a}'], help="The start of the FFmpeg command (default [\'-y\'])")
    parser.add_argument('-v', '--video-encoder', dest="video", nargs='+', default=['{a}', '{b}', '{c}'], help='Video encoder (default: [\'hevc_nvenc\',\'-qp\',\'22\'])')
    parser.add_argument('-a', '--audio-encoder', dest="audio", nargs='+', default=['{a}'], help='Audio encoder (default: [\'copy\'])')
    parser.add_argument('-e', '--ending', nargs='+', default=['{a}', '{b}'], help='The end of the FFmpeg command (default=[\'-map\',\'0\'])')
    parser.add_argument('-d', '--directorys', nargs='+', default=[], help='Explicitly specified directorys to process')

    args, unknown_args = parser.parse_known_args()
    args.regex = [arg.format(a=".*\\.mp4$", b=".*\\.mkv$") for arg in args.regex]
    args.start = [arg.format(a="-y") for arg in args.start]
    if args.video:
        args.video = ["-c:v"] + [arg.format(a="hevc_nvenc",b="-qp",c="22") for arg in args.video]
    if args.audio:
        args.audio = ["-c:a"] + [arg.format(a="copy") for arg in args.audio]
    args.ending = [arg.format(a="-map",b="0") for arg in args.ending]

    args.directorys = [directory for directory in args.directorys + unknown_args if os.path.isdir(directory)]

    if args.workingdir and os.path.isdir(args.workingdir):
        os.chdir(args.workingdir)
    else:
        if args.workingdir and args.directorys:
            print("Working dir invalid using active dir\n")
        args.workingdir = os.getcwd()

    if args.directorys:
        return args
    else:
        parser.print_help()
        print("\nNo directorys given to process")
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


def video_tasker(videos, args):
    worker_pid = os.getpid()
    for folder, folder_videos in videos.items():
        config, config_path = load_folder_config(folder)

        # Recover abandoned tasks
        for video, details in config.items():
            if details['status'] == 'pending' and not is_worker_active(int(details['worker'])):
                    details['status'] = 'todo'
                    details['worker'] = None

        # Delete any entrys that are a output file
        for video, details in dict(folder_videos.items()).items():
            if details['output'] in folder_videos.keys():
                del folder_videos[details['output']]

        # Merge new videos with existing config
        for video, details in folder_videos.items():
            if video not in config:
                # New video, add to config
                config[video] = details
            else:
                # Video exists in config
                if config[video]['status'] in ['todo', 'failed']:
                    # Update output if the new format is different
                    if config[video]['output'] != details['output']:
                        config[video]['output'] = details['output']

        # Process videos
        for video, details in config.items():
            if details['status'] in ['todo', 'failed']:
                details['worker'] = worker_pid
                details['status'] = 'pending'
                save_folder_config(config, config_path)
                if os.path.isabs(details['output']):
                    output = details['output']
                else:
                    output = os.path.join(folder, details['output'])
                ffmpeg_cmd = [args.ffmpeg] + args.start + ['-i', os.path.join(folder, video)] + args.video + args.audio + args.ending + [output]
                print(f"\tRunning command:\n{args.ffmpeg} '{'\'\''.join(ffmpeg_cmd[1:])}'\n")
                result = subprocess.run(ffmpeg_cmd)

                if result.returncode == 0:
                    # Mark task as completed
                    details['status'] = 'completed'
                    print(f"\n\tConversion successful for {video}\n")
                else:
                    # Mark task as failed
                    details['status'] = 'failed'
                    print(f"\n\tConversion failed for {video}. Return code: {result.returncode}\n")

                details['worker'] = None

                save_folder_config(config, config_path)


def main():
    args = parse_arguments()
    videos = folders_process(args.directorys, args.regex, args.output)
    video_tasker(videos,args)


if __name__ == "__main__":
    main()
