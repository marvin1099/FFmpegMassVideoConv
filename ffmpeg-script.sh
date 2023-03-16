#!/bin/bash

if [[ $1 == "" || $1 == "-h" || $1 == "help" || $1 == "-help" ]]
then
    echo "Usage:
-help           For this message
-fstart         To change the start argumens                default='-y'
-ibefore        To change the args before the input         default='-i'
-finput         To change the input string (Not recommended). Only makes sence
  if you need to transform the input from the ToDoFile      default='/n/e' (this means file+ext)
-cvideo         To change the video encoder                 default='-c:v' 'hevc_nvenc'
-cvquality      To change the video quality settings        default='-rc' 'constqp' '-qp' '22'
-caudio         To change the audio encoder                 default='-c:a' 'copy'
-caquality      To change the audio quality encoder         empty default
-eextra         To change the extra settings after          default='-map' '0'
-workout        To change the output filename               default='/n' '22.mkv' (this is name+ q22.mkv)
-findfiletypes  To change the default files to lock for     default='*.mp4' '*.mkv'
-resumefailed   To restart failed files on power loss       default='false'
-folders        To add the folders to convert (Requered)    empty default

The default config will result in the following output in the selected folders:
> ffmpeg -i FILEIN -c:v hevc_nvenc -rc constqp -qp 22 -c:a copy -map 0 FILEOUT"
    exit
fi

Origdir=$(pwd)

#Get aguments and reverse them
for i in "$@"
do
    if [[ $args == "" ]]
    then
        args="$i"
    else
        args="$i"$'\n'"$args"
    fi
done

#Loop all argumens and match arguments to varribles
#The argumens are reversed so that we can allready know all arguments that correspond to -folders or other args
IFS=$'\n'
for i in $args
do
    if [[ $i == "-cvideo" ]] #Video codec # def. -c:v hevc_nvenc
    then
        cvideo="$liars"
        liars=""
    elif [[ $i == "-cvquality" ]] #Video settings # def. -rc constqp -qp 22
    then
        cvquality="$liars"
        liars=""
    elif [[ $i == "-caudio" ]] #Audio codec # def. -c:a copy
    then
        caudio="$liars"
        liars=""
    elif [[ $i == "-caquality" ]] #Audio settings
    then
        caquality="$liars"
        liars=""
    elif [[ $i == "-eextra" ]] #extra settings # def. -map 0
    then
        eextra="$liars"
        liars=""
    elif [[ $i == "-iafter" ]] #after inputfile args # eg. -to 00:01:00.000
    then
        iafter="$liars"
        liars=""
    elif [[ $i == "-fstart" ]] #the very beginnig # def. -y # eg. -ss 00:00:00.000
    then
        fstart="$liars"
        liars=""
    elif [[ $i == "-ibefore" ]] #before inputfile # def. -i
    then
        ibefore="$liars"
        liars=""
    elif [[ $i == "-finput" ]] #Imputfilenape # def. /n/e # input.mkv
    then
        finput="$liars"
        liars=""
    elif [[ $i == "-foutput" ]] #Outputfilename # def. /n q22.mkv # newoutput.mkv
    then
        foutput=$(echo $liars)
        liars=""
    elif [[ $i == "-findfiletypes" ]] #Filse to find # def. *.mkv *.mp4
    then
        findfiletypes="$liars"
        liars=""
    elif [[ $i == "-resumefailed" ]] #Resume after power loss
    then
        resumefailed=$(echo $liars)
        liars=""
    elif [[ $i == "-folders" ]] #folders inputs
    then
        folders="$liars"
        liars=""
    else #Save args to be used with input
        if [[ $liars == "" ]]
        then
            liars="$i"
        else
            liars="$i"$'\n'"$liars"
        fi
    fi
done

#Defaults for the command
if [[ $cvideo == "" ]]
then
    cvideo="-c:v"$'\n'"hevc_nvenc"
fi
if [[ $cvquality == "" ]]
then
    cvquality="-rc"$'\n'"constqp"$'\n'"-qp"$'\n'"22"
fi
if [[ $caudio == "" ]]
then
    caudio="-c:a"$'\n'"copy"
fi
#if [[ $caquality == "" ]] #empty default (placeholder)
#then
#    caquality=""
#fi
if [[ $eextra == "" ]]
then
    eextra="-map"$'\n'"0"
fi
#if [[ $iafter == "" ]] #empty default (placeholder)
#then
#    iafter=""
#fi
if [[ $fstart == "" ]]
then
    fstart="-y"
fi
if [[ $ibefore == "" ]]
then
    ibefore="-i"
fi
if [[ $finput == "" ]]
then
    finput="/n/e"
fi
if [[ $foutput == "" ]]
then
    foutput="/n q22.mkv"
fi
if [[ $(echo $findfiletypes) == "" ]]
then
    findfiletypes="*.mp4"$'\n'"*.mkv"
fi
if [[ $resumefailed == "" ]]
then
    resumefailed="false"
fi
if [[ $(echo $folders) == "" ]]
then
    echo "Folder input is requied exiting"
    exit
fi
#Ffmpeg example comands for the creator
#ffmpeg -ss 00:00:00.000 -i input.mkv -to 00:01:00.000 -c:v hevc_nvenc -rc constqp -qp 22 -c:a copy -map 0 newoutput.mp4
#ffmpeg -y -i "$workin" -c:v $enco -rc constqp -qp $quality -c:a copy -map 0 "$workout" #ffmpeg $fstart $ibefore "$workin" $cvideo #ffmpeg $fstart $ibefore $finput $cvideo $cvquality $caudio $caquality $eextra $foutput

#Loop throgh all folders then convert all videos inside them
for f in $folders
do
    #Go to start dir
    cd "$Origdir"
    #Go to videodir
    rundir=$f
    cd "$rundir"

    #Clear varribles
    restart=0
    allfiles=""
    extrafiles=""
    blockedfiles=""
    IFS=$'\n'
    if [[ ! -f ./ffmpegtodo.txt ]] #if nothing todo find file see if they are done and save what is not don
    then
        for t in $findfiletypes
        do
            allfiles="$allfiles"$'\n'"$(find ./$t -maxdepth 1 -printf "%f\n" 2>/dev/null)"
        done
        echo "$allfiles" | awk '{if($0!="") {print $0}}' > ./ffmpegtodo.txt
        echo "Taskfile created"$'\n'"Restart script to run on Taskfile"
        restart=1
    else
        for t in $extrafiles
        do
            extrafiles="$extrafiles"$'\n'"$(find ./$t -maxdepth 1 -printf "%f\n" 2>/dev/null)"
        done
        allfiles="$(awk '{print $0}' ./ffmpegtodo.txt 2>/dev/null)"
        for i in $extrafiles
        do
            if [[ $i != "" ]]
            then
                Found=0
                for j in $allfiles
                do
                    if [[ $j == $i ]]
                    then
                        Found=1
                        break
                    fi
                done
                if [[ $Found == 0 ]]
                then
                    blockedfiles="$blockedfiles"$'\n'"$i"
                fi
            fi
        done
        if [[ -f ./ffmpegfinished.txt ]]
        then
            echo "$blockedfiles" | awk '{if($0!="") {print $0}}' ./ffmpegfinished.txt > ./ffmpegfinished.txt
        else
            echo "$blockedfiles" | awk '{if($0!="") {print $0}}' > ./ffmpegfinished.txt
        fi
    fi

    if [[ -f ./ffmpegconverting.txt ]] && [[ $resumefailed == "true" || $resumefailed == "1" ]] #resume on power loss
    then
        prossing="$(awk '{print $0}' ./ffmpegconverting.txt 2>/dev/null)"
        allfiles="$prossing"$'\n'"$allfiles"
        for i in $prossing
        do
            if [[ $i != "" ]]
            then
                iext=".${i##*.}"
                iname=$(basename $i $iext)
                workin="$(echo "$finput" | awk '{gsub("/n","'"$iname"'",$0); gsub("/e","'"$iext"'",$0); print $0}')"
                workout="$(echo "$foutput" | awk '{gsub("/n","'"$iname"'",$0); gsub("/e","'"$iext"'",$0); print $0}')"
                echo "$(awk '{if($0!="'"$workin"'" && $0!="") {print $0}}' ./ffmpegconverting.txt)" > ./ffmpegconverting.txt
                echo "$(awk '{if($0!="'"$workout"'" && $0!="") {print $0}}' ./ffmpegprosessing.txt)" > ./ffmpegprosessing.txt
            fi
        done
    fi

    donefiles=""
    if [[ -f ./ffmpegfinished.txt ]]
    then
        donefiles="$(awk '{print $0}' ./ffmpegfinished.txt)"
    fi

    nicefiles=""
    for i in $allfiles
    do
        if [[ $i != "" ]]
        then
            Found=0
            for j in $donefiles
            do
                if [[ $j == $i ]]
                then
                    Found=1
                    break
                fi
            done
            if [[ $Found == 0 ]]
            then
                nicefiles="$nicefiles"$'\n'"$i"
            fi
        fi
    done
    echo "$nicefiles" | awk '{if($0!="") {print $0}}' > ./ffmpegtodo.txt

    if [[ -f ./ffmpegtodo.txt && ! $(awk '{if($0!="") {print $0}}' ./ffmpegtodo.txt) ]]
    then
        rm ./ffmpegtodo.txt
        restart=0
        echo "All files are allready converted, delete ffmpegfinished.txt to redo the files"
    fi

    if [[ $restart == 1 ]]
    then
        xdg-open ./ffmpegtodo.txt 2>/dev/null &
    else
        echo "------"
        echo "Using path: $rundir"
        echo "Using ffmpeg command: ffmpeg" $fstart $ibefore "FILEIN" $cvideo $cvquality $caudio $caquality $eextra "FILEOUT"
        echo "------"

        for i in $nicefiles
        do
            nicefiles="$(awk '{print $0}' ./ffmpegtodo.txt 2>/dev/null)"
            if [[ $(echo "$nicefiles" | awk '{if($0=="'"$i"'") {print $0}}') ]] && [[ -f "$i" ]]
            then
                echo "---"
                echo "Converting: $rundir/$i"
                echo "---"
                nicefiles="$(echo "$nicefiles" | awk '{if($0!="'"$i"'" && $0!="") {print $0}}')"
                iext=".${i##*.}"
                iname=$(basename $i $iext)
                workin="$(echo "$finput" | awk '{gsub("/n","'"$iname"'",$0); gsub("/e","'"$iext"'",$0); print $0}')"
                workout="$(echo "$foutput" | awk '{gsub("/n","'"$iname"'",$0); gsub("/e","'"$iext"'",$0); print $0}')"
                echo "$nicefiles" | awk '{if($0!="") {print $0}}' > ./ffmpegtodo.txt
                echo "$workin" | awk '{if($0!="") {print $0}}' >> ./ffmpegconverting.txt
                echo "$workout" | awk '{if($0!="") {print $0}}' >> ./ffmpegprosessing.txt
                mycmd=("ffmpeg")
                IFS=$'\n'
                for r in $(echo "$fstart"$'\n'"$ibefore")
                do
                    mycmd+=("$r")
                done
                mycmd+=("$workin")
                for r in $(echo "$cvideo"$'\n'"$cvquality"$'\n'"$caudio"$'\n'"$caquality"$'\n'"$eextra")
                do
                    mycmd+=("$r")
                done
                IFS=$'\n'
                mycmd+=("$workout")
                #echo ${mycmd[*]}
                "${mycmd[@]}"
                hasworked=$?
                if [[ $hasworked -gt 0 ]]
                then
                    echo "The ffmpeg coversion has incoutered an error "$'\n'"Exiting"
                    echo "$workin"$'\n'"$nicefiles" | awk '{if($0!="") {print $0}}' > ./ffmpegtodo.txt
                    echo "$(awk '{if($0!="'"$workin"'" && $0!="") {print $0}}' ./ffmpegconverting.txt)" > ./ffmpegconverting.txt
                    echo "$(awk '{if($0!="'"$workout"'" && $0!="") {print $0}}' ./ffmpegprosessing.txt)" > ./ffmpegprosessing.txt
                    break
                elif [[ ! -f ./ffmpegtodo.txt ]]
                then
                    echo "ToDoFile was deleted"$'\n'"Exiting and Receating file"
                    echo "$workin"$'\n'"$nicefiles" | awk '{if($0!="") {print $0}}' > ./ffmpegtodo-temp.txt
                    echo "$(awk '{if($0!="'"$workin"'" && $0!="") {print $0}}' ./ffmpegconverting.txt)" > ./ffmpegconverting.txt
                    echo "$(awk '{if($0!="'"$workout"'" && $0!="") {print $0}}' ./ffmpegprosessing.txt)" > ./ffmpegprosessing.txt
                    break
                fi
                echo "$workin" | awk '{if($0!="") {print $0}}' >> ./ffmpegfinished.txt
                echo "$workout" | awk '{if($0!="") {print $0}}' >> ./ffmpegfinished.txt
                echo "$(awk '{if($0!="'"$workin"'" && $0!="") {print $0}}' ./ffmpegconverting.txt)" > ./ffmpegconverting.txt
                echo "$(awk '{if($0!="'"$workout"'" && $0!="") {print $0}}' ./ffmpegprosessing.txt)" > ./ffmpegprosessing.txt
            fi
        done
    fi

    if [[ -f ./ffmpegtodo.txt && ! $(awk '{if($0!="") {print $0}}' ./ffmpegtodo.txt) ]]
    then
        rm ./ffmpegtodo.txt
    fi

    if [[ -f ./ffmpegtodo-temp.txt && ! $(awk '{if($0!="") {print $0}}' ./ffmpegtodo-temp.txt) ]]
    then
        rm ./ffmpegtodo-temp.txt
    fi

    if [[ -f ./ffmpegconverting.txt && ! $(awk '{if($0!="") {print $0}}' ./ffmpegconverting.txt) ]]
    then
        rm ./ffmpegconverting.txt
    fi

    if [[ -f ./ffmpegprosessing.txt && ! $(awk '{if($0!="") {print $0}}' ./ffmpegprosessing.txt) ]]
    then
        rm ./ffmpegprosessing.txt
    fi
done
