#!/usr/bin/env bash
echo "======================================================="
echo "         TELEFLOW - HIGH PERFORMANCE SUITE             "
echo "======================================================="

# 1. Check Python
if ! command -v python3 &> /dev/null; then
    echo "[ERROR] Python 3 is not installed! Please install Python 3.10+."
    exit 1
fi

# 2. Virtual Environment
if [ ! -d "venv" ]; then
    echo "[*] Creating virtual environment (venv)..."
    python3 -m venv venv
fi

# 3. Activate
source venv/bin/activate

# 4. Requirements
python -c "import fastapi, telethon" &> /dev/null
if [ $? -ne 0 ]; then
    echo "[*] Installing dependencies..."
    pip install --upgrade pip
    pip install -r requirements.txt
fi

# 5. Check .env
if [ ! -f ".env" ]; then
    echo "[*] Copying .env.example to .env..."
    cp .env.example .env
    echo "======================================================="
    echo "[ACTION REQUIRED] Created .env file!"
    echo "Please open .env and set your TG_API_ID, TG_API_HASH, and JWT_SECRET."
    echo "======================================================="
    exit 1
fi

# 6. Launch
echo "[*] Launching TeleFlow on http://localhost:8000..."
python3 app.py
