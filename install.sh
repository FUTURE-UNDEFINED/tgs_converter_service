#!/usr/bin/env bash

set -euo pipefail

echo "Updating packages..."
sudo apt update

echo "Install python build dependencies"
sudo apt install -y software-properties-common build-essential \
    libssl-dev zlib1g-dev libbz2-dev libreadline-dev libsqlite3-dev \
    wget curl llvm libncursesw5-dev xz-utils tk-dev libxml2-dev libxmlsec1-dev \
    libffi-dev liblzma-dev

echo "Install deadsnake and python3.9"
sudo add-apt-repository -y ppa:deadsnakes/ppa
sudo apt update
sudo apt install -y python3.9 python3.9-venv python3.9-dev

echo "Install ffmpeg"
sudo apt install -y ffmpeg
ffmpeg -version

echo "Create venv"
python3.9 -m venv .venv

echo "Activating venv"
source .venv/bin/activate

if [ -f requirements.txt ]; then
    pip install --upgrade pip
    pip install -r requirements.txt
else
    echo "cannot find requirements.txt "
fi

echo "Installation complete."
