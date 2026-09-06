import os
import re
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# Telegram Credentials & Security (Configured via .env)
api_id_env = os.getenv("TG_API_ID") or os.getenv("TELEGRAM_API_ID") or ""
API_ID = int(api_id_env) if api_id_env.isdigit() else None
API_HASH = os.getenv("TG_API_HASH") or os.getenv("TELEGRAM_API_HASH") or None
JWT_SECRET = os.getenv("JWT_SECRET")
MASTER_PASSWORD = os.getenv("MASTER_PASSWORD")

# File Size & Extensions
MAX_FILE_SIZE_MB = int(os.getenv("MAX_FILE_SIZE_MB", 4000))
MAX_FILE_SIZE = MAX_FILE_SIZE_MB * 1024 * 1024

ALLOWED_EXTENSIONS = {
    '.jpg', '.jpeg', '.png', '.gif', '.webp', '.heic',
    '.mp4', '.mkv', '.avi', '.mov', '.webm', '.m4v', '.ts', '.3gp',
    '.pdf', '.mp3', '.opus', '.flac', '.wav', '.ogg'
}

VIDEO_EXTENSIONS = {'.mp4', '.mkv', '.avi', '.mov', '.webm', '.m4v', '.ts', '.3gp'}
IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.gif', '.webp', '.heic'}
AUDIO_EXTENSIONS = {'.mp3', '.opus', '.flac', '.wav', '.ogg', '.m4a'}

# Directories
BASE_DOWNLOAD_DIR = Path("./downloads").resolve()
SESSIONS_DIR = Path("./sessions").resolve()
STATIC_DIR = Path("./static").resolve()

BASE_DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
STATIC_DIR.mkdir(parents=True, exist_ok=True)

# Regex
TELEGRAM_LINK_REGEX = re.compile(r'(https?://(?:t\.me|telegram\.me)/[^\s]+)')

# Cache Cleaner Configuration
CLEANER_INTERVAL_SECONDS = 1800  # 30 minutes
CACHE_EXPIRE_HOURS = 0.5         # 30 minutes
