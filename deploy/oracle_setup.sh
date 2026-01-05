#!/bin/bash
set -e

# Oracle Cloud Setup Script for Price Anomaly Detector
# Usage: ./oracle_setup.sh

echo "============================================"
echo "    Price Anomaly Detector - Server Setup   "
echo "============================================"

# 1. Update System
echo "[1/6] Updating system packages..."
sudo apt update && sudo apt upgrade -y

# 2. Install Dependencies
echo "[2/6] Installing system dependencies..."
sudo apt install -y python3.11 python3.11-venv python3-pip git cron

# Playwright dependencies for WebKit/Chromium
sudo apt install -y libnss3 libnspr4 libdbus-1-3 libatk1.0-0 libatk-bridge2.0-0 \
  libcups2 libdrm2 libxkbcommon0 libxcomposite1 libxdamage1 libxrandr2 \
  libgbm1 libpango-1.0-0 libcairo2 libasound2

# 3. Setup Python Environment
echo "[3/6] Setting up Python environment..."
if [ ! -d "venv" ]; then
    python3.11 -m venv venv
    echo "Virtual environment created."
fi

source venv/bin/activate

# 4. Install Python Libraries
echo "[4/6] Installing Python requirements..."
pip install --upgrade pip
if [ -f "requirements.txt" ]; then
    pip install -r requirements.txt
else
    echo "Warning: requirements.txt not found!"
fi

# 5. Install Playwright Browsers
echo "[5/6] Installing Playwright browsers..."
playwright install chromium

# 6. Cron Job Setup Helper
echo "[6/6] Setup Complete!"
echo ""
echo "============================================"
echo "To schedule the scrapers, run 'crontab -e' and add the following lines:"
echo "============================================"
PWD=$(pwd)
echo "# Amazon (Every hour at :00)"
echo "0 * * * * cd $PWD && $PWD/venv/bin/python run_anomaly_detector.py --site amazon --category components --pages 10 >> $PWD/logs/amazon.log 2>&1"
echo ""
echo "# Newegg (Every hour at :15)"
echo "15 * * * * cd $PWD && $PWD/venv/bin/python run_anomaly_detector.py --site newegg --category all --pages 3 >> $PWD/logs/newegg.log 2>&1"
echo ""
echo "# Canada Computers (Every hour at :30)"
echo "30 * * * * cd $PWD && $PWD/venv/bin/python run_anomaly_detector.py --site canadacomputers --category all --pages 3 >> $PWD/logs/cc.log 2>&1"
echo ""
echo "# Memory Express (Every hour at :45)"
echo "45 * * * * cd $PWD && $PWD/venv/bin/python run_anomaly_detector.py --site memoryexpress --category all --pages 3 >> $PWD/logs/mx.log 2>&1"
echo "============================================"
echo ""
echo "Don't forget to create the logs directory:"
echo "mkdir -p logs"
