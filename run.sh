#!/bin/bash

deactivate > /dev/null 2>&1

if [ -d "./venv_image_browser/" ]; then
    . ./venv_image_browser/bin/activate
else
    . ./venv/bin/activate
fi

python main.py "$@"
