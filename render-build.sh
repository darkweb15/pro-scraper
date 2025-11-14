#!/bin/bash
set -e

pip install -r requirements.txt

apt-get update
apt-get install -y wget ca-certificates
wget -q -O /tmp/chrome.deb https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb
apt-get install -y /tmp/chrome.deb
rm /tmp/chrome.deb
rm -rf /var/lib/apt/lists/*
