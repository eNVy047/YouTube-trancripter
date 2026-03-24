#!/bin/bash
set -e

# Update package index
apt-get update

# Install system dependencies required by faster-whisper and yt-dlp
apt-get install -y \
    ffmpeg \
    libsndfile1 \
    build-essential \
    python3-dev

echo "System dependencies installed successfully"
