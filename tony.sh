#!/usr/bin/env bash

source /env.sh
python3 /tony.py --username "$TONY_USERNAME" --password "$TONY_PASSWORD" --playlist "$TONY_PLAYLIST" --input-path "/mp3s" --pushover-userkey "$TONY_PUSHOVER_USERKEY" --pushover-apptoken "$TONY_PUSHOVER_APPTOKEN" --cache-path /tony_cache
