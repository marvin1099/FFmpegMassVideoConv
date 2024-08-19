# FFmpegMassVideoConv

Mass video conversion with ffmpeg using a cross platform python script,  
without any additonal python dependencies.

Main Repo: https://codeberg.org/marvin1099/FFmpegMassVideoConv  
Backup Repo: https://github.com/marvin1099/FFmpegMassVideoConv

# Dependencies
Make shure you have installed (and also added in the system enviroment path):  
1. ffmpeg
2. python

## Install
download the ffmpeg-script.sh from releases section:  
https://codeberg.org/marvin1099/FFmpegMassVideoConv/releases  
if needed make the file executable  
run it with the folders you want to convert

## Use
To print the usage run:
```
PATH/TO/FFmpegConv.py
```
Relace PATH/TO/ with the path the FFmpegConv.py is at.

Then it will show the usage (also at the bottom of the readme).  
Then you just add the conversion directorys at the end and all of then will be converted. 

## Exaples
```
PATH/TO/FFmpegConv.py /MY/COOL/RECORDS
```
will convert all files in the diretory /MY/COOL/RECORDS

```
PATH/TO/FFmpegConv.py -v {a} {b} 20 -d /MY/COOL/RECORDS
```
will convert all files in the diretory using -qp 20

```
PATH/TO/FFmpegConv.py -o {n}-q22.mp4 -d /MY/COOL/RECORDS
```
will convert all files in the diretory using and save them as NAME-q22.mp4

## Usage
```
usage: FFmpegConv.py [-h] [-f FFMPEG] [-r REGEX [REGEX ...]] [-w WORKINGDIR] [-o OUTPUT]
[-s START [START ...]] [-v VIDEO [VIDEO ...]] [-a AUDIO [AUDIO ...]]
[-e ENDING [ENDING ...]] [-d DIRECTORYS [DIRECTORYS ...]]

Simple FFmpeg mass conversion tool
To use only some of the default args use {a} {b} {c}
For example for -v {b} will result in -qp

options:
-h, --help            show this help message and exit
-f FFMPEG, --ffmpeg FFMPEG
    Set ffmpeg path (default: 'ffmpeg')
-r REGEX [REGEX ...], --regex REGEX [REGEX ...]
    Regex to search for in file name (default: ['.*\.mp4$','.*\.mkv$'])
-w WORKINGDIR, --working-dir WORKINGDIR
    Set the working directory
-o OUTPUT, --output OUTPUT
    Output file sting, use {n}/{e} for the filename/extension (default {n}-q22.{e})
-s START [START ...], --start START [START ...]
    The start of the FFmpeg command (default ['-y'])
-v VIDEO [VIDEO ...], --video-encoder VIDEO [VIDEO ...]
    Video encoder (default: ['hevc_nvenc','-qp','22'])
-a AUDIO [AUDIO ...], --audio-encoder AUDIO [AUDIO ...]
    Audio encoder (default: ['copy'])
-e ENDING [ENDING ...], --ending ENDING [ENDING ...]
    The end of the FFmpeg command (default=['-map','0'])
-d DIRECTORYS [DIRECTORYS ...], --directorys DIRECTORYS [DIRECTORYS ...]
    Explicitly specified directorys to process

The config will be named conversion-config.json and located in the currend conversion dir
The default config will result in the following command in the selected directories:
    ffmpeg -y -i FILEIN -c:v hevc_nvenc -qp 22 -c:a copy -map 0 FILEOUT

No directorys given to process
```
