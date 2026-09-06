#!/usr/bin/env python3
"""
TeleFlow CLI & Media Downloader Engine
=======================================
A production-ready asynchronous Python engine to download videos and media from Telegram
channels or groups using Telethon with AES-NI hardware acceleration.
"""

import os
import sys
import asyncio
import logging
from logging.handlers import RotatingFileHandler
import sqlite3
import argparse
from datetime import datetime
from pathlib import Path

# Try to load environment variables from .env if python-dotenv is installed
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

try:
    from PIL import Image
    import imagehash
    import hashlib
except ImportError:
    pass

try:
    from core.crypto_patch import apply_telethon_crypto_patch
    apply_telethon_crypto_patch()
except Exception:
    pass

# Telethon imports
try:
    from telethon import TelegramClient, errors
    from telethon.tl.types import MessageMediaDocument, DocumentAttributeVideo, DocumentAttributeFilename
except ImportError:
    print("Error: The 'telethon' library is required to run this script.", file=sys.stderr)
    print("Please install it using: pip install telethon python-dotenv", file=sys.stderr)
    sys.exit(1)

# Configure Logging
LOG_FILE = "telegrab.log"
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        RotatingFileHandler(LOG_FILE, maxBytes=2*1024*1024, backupCount=1, encoding="utf-8"),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("telegrab")

import magic
import re

ALLOWED_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.gif', '.webp', '.mp4', '.mkv', '.avi', '.mov', '.webm', '.m4v', '.ts', '.3gp', '.pdf', '.mp3', '.opus', '.flac', '.wav', '.heic'}
MAX_FILE_SIZE = int(os.getenv("MAX_FILE_SIZE_MB", 4000)) * 1024 * 1024

def secure_filename(filename: str) -> str:
    if not filename:
        return "unknown_file"
    filename = os.path.basename(filename)
    filename = re.sub(r'[^a-zA-Z0-9_.-]', '_', filename)
    filename = filename.strip('._')
    return filename or "unknown_file"

def verify_file_type(filepath: str) -> bool:
    try:
        mime = magic.from_file(filepath, mime=True)
        if mime and not mime.startswith(('image/', 'video/', 'audio/', 'application/pdf')):
            return False
        return True
    except Exception:
        return True

def calculate_file_hash(filepath: str, is_video: bool) -> str:
    try:
        if is_video:
            # Hash first 1MB
            hasher = hashlib.md5()
            with open(filepath, 'rb') as f:
                chunk = f.read(1024 * 1024)
                if not chunk:
                    return ""
                hasher.update(chunk)
            return hasher.hexdigest()
        else:
            # Perceptual hash for images
            img = Image.open(filepath)
            return str(imagehash.phash(img))
    except Exception as e:
        logger.error(f"Failed to calculate hash for {filepath}: {e}")
        return ""


class DownloadTracker:
    """Manages the download history database to prevent duplicate downloads."""
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS downloads (
                    message_id INTEGER PRIMARY KEY,
                    channel_id INTEGER,
                    timestamp TEXT,
                    file_name TEXT,
                    resolution TEXT,
                    file_size INTEGER,
                    status TEXT,
                    error_reason TEXT
                )
            """)
            
            # Migration to add new columns if they don't exist
            cursor = conn.cursor()
            cursor.execute("PRAGMA table_info(downloads)")
            columns = [info[1] for info in cursor.fetchall()]
            
            if 'file_hash' not in columns:
                conn.execute("ALTER TABLE downloads ADD COLUMN file_hash TEXT")
            if 'message_text' not in columns:
                conn.execute("ALTER TABLE downloads ADD COLUMN message_text TEXT")
            if 'tags' not in columns:
                conn.execute("ALTER TABLE downloads ADD COLUMN tags TEXT")
            if 'media_type' not in columns:
                conn.execute("ALTER TABLE downloads ADD COLUMN media_type TEXT")
            
            conn.commit()

    def is_downloaded(self, message_id: int) -> bool:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT status FROM downloads WHERE message_id = ? AND status = 'Downloaded'", (message_id,))
            row = cursor.fetchone()
            return row is not None

    def is_hash_downloaded(self, file_hash: str) -> bool:
        if not file_hash:
            return False
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT status FROM downloads WHERE file_hash = ? AND status = 'Downloaded'", (file_hash,))
            row = cursor.fetchone()
            return row is not None

    def log_download(self, message_id: int, channel_id: int, timestamp: datetime, file_name: str, resolution: str, file_size: int, status: str, error_reason: str = None, file_hash: str = None, message_text: str = None, tags: str = None, media_type: str = None):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT OR REPLACE INTO downloads 
                (message_id, channel_id, timestamp, file_name, resolution, file_size, status, error_reason, file_hash, message_text, tags, media_type)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (message_id, channel_id, timestamp.isoformat(), file_name, resolution, file_size, status, error_reason, file_hash, message_text, tags, media_type))
            conn.commit()


def get_video_attributes(message):
    """
    Analyzes message media to check if it's a video and extracts attributes.
    Returns (is_video, file_name, resolution, file_size)
    """
    if not message.media or not isinstance(message.media, MessageMediaDocument):
        return False, None, None, 0

    document = message.media.document
    if not document:
        return False, None, None, 0

    is_video = False
    resolution = "Unknown"
    file_name = f"video_{message.id}.mp4"
    file_size = document.size

    # Look for video and filename attributes
    for attr in document.attributes:
        if isinstance(attr, DocumentAttributeVideo):
            is_video = True
            if attr.w and attr.h:
                resolution = f"{attr.w}x{attr.h}"
        elif isinstance(attr, DocumentAttributeFilename):
            file_name = attr.file_name

    # Double check mime type if resolution attributes wasn't found but it's video
    if document.mime_type and document.mime_type.startswith("video/"):
        is_video = True

    file_name = secure_filename(file_name)
    ext = Path(file_name).suffix.lower()
    
    if not is_video and ext in {'.mp4', '.mkv', '.avi', '.mov', '.webm', '.m4v', '.ts', '.3gp'}:
        is_video = True

    return is_video, file_name, resolution, file_size


class DownloadProgressBar:
    """A helper to print a nice text-based download progress bar."""
    def __init__(self, filename: str, total_bytes: int):
        self.filename = filename
        self.total_bytes = total_bytes
        self.last_percent = -1

    def callback(self, downloaded_bytes: int, total_bytes: int):
        if not total_bytes:
            total_bytes = self.total_bytes
        if not total_bytes:
            return

        percent = int((downloaded_bytes / total_bytes) * 100)
        if percent != self.last_percent:
            self.last_percent = percent
            bar_length = 30
            filled_length = int(bar_length * downloaded_bytes // total_bytes)
            bar = '█' * filled_length + '-' * (bar_length - filled_length)
            
            # Format size to human-readable
            dl_mb = downloaded_bytes / (1024 * 1024)
            tot_mb = total_bytes / (1024 * 1024)
            
            sys.stdout.write(f"\rDownloading: [{bar}] {percent}% ({dl_mb:.1f}/{tot_mb:.1f} MB) - {self.filename}")
            sys.stdout.flush()
            if downloaded_bytes == total_bytes:
                sys.stdout.write("\n")
                sys.stdout.flush()


async def download_video(client: TelegramClient, message, output_dir: Path, tracker: DownloadTracker, channel_id: int):
    """Downloads a single video message with error safety and progress tracking."""
    is_video, file_name, resolution, file_size = get_video_attributes(message)
    if not is_video:
        return

    # Check if already downloaded
    if tracker.is_downloaded(message.id):
        logger.info(f"Skipping Message ID {message.id} - Already downloaded: {file_name}")
        return

    # Ensure unique file name to avoid collisions
    dest_path = output_dir / f"{message.id}_{file_name}"
    
    logger.info(f"Starting download for Message ID {message.id} | Size: {file_size / (1024*1024):.2f} MB | Resolution: {resolution}")
    
    progress = DownloadProgressBar(file_name, file_size)

    # Retry parameters
    max_retries = 5
    backoff = 2

    for attempt in range(1, max_retries + 1):
        try:
            await client.download_media(
                message.media,
                file=str(dest_path),
                progress_callback=progress.callback
            )
            
            if not verify_file_type(str(dest_path)):
                logger.warning(f"File {file_name} failed MIME type verification. Deleting.")
                os.remove(dest_path)
                tracker.log_download(
                    message_id=message.id,
                    channel_id=channel_id,
                    timestamp=message.date,
                    file_name=file_name,
                    resolution=resolution,
                    file_size=file_size,
                    status="Failed_MIME"
                )
                return False
                
            # Success
            logger.info(f"Successfully downloaded: {dest_path.name}")
            tracker.log_download(
                message_id=message.id,
                channel_id=channel_id,
                timestamp=message.date,
                file_name=file_name,
                resolution=resolution,
                file_size=file_size,
                status="Downloaded"
            )
            return

        except errors.FloodWaitError as e:
            logger.warning(f"Rate limited (FloodWait). Must wait for {e.seconds} seconds.")
            # Standard Telegram recommendation is to sleep the requested duration plus a small buffer
            await asyncio.sleep(e.seconds + 5)
            logger.info("Resuming download after rate limit wait...")
            
        except (errors.RPCError, Exception) as e:
            logger.error(f"Attempt {attempt}/{max_retries} failed for Message ID {message.id}. Error: {str(e)}")
            if attempt < max_retries:
                sleep_time = backoff ** attempt
                logger.info(f"Retrying in {sleep_time} seconds...")
                await asyncio.sleep(sleep_time)
            else:
                logger.critical(f"Failed to download Message ID {message.id} after {max_retries} attempts.")
                tracker.log_download(
                    message_id=message.id,
                    channel_id=channel_id,
                    timestamp=message.date,
                    file_name=file_name,
                    resolution=resolution,
                    file_size=file_size,
                    status="Failed",
                    error_reason=str(e)
                )
                # Cleanup partial file if it exists
                if dest_path.exists():
                    try:
                        dest_path.unlink()
                    except Exception:
                        pass


async def download_image(client: TelegramClient, message, output_dir: Path, tracker: DownloadTracker, channel_id: int):
    """Downloads a single photo/image message with error safety, deduplication and tracking."""
    if not message.media:
        return False

    if tracker.is_downloaded(message.id):
        logger.info(f"Skipping Message ID {message.id} - Already downloaded")
        return False

    file_name = f"image_{message.id}.jpg"
    dest_path = output_dir / f"{message.id}_{file_name}"
    
    try:
        await client.download_media(message.media, file=str(dest_path))
        if dest_path.exists():
            file_size = dest_path.stat().st_size
            if not verify_file_type(str(dest_path)):
                logger.warning(f"File {file_name} failed MIME type verification. Deleting.")
                os.remove(dest_path)
                tracker.log_download(
                    message_id=message.id,
                    channel_id=channel_id,
                    timestamp=message.date,
                    file_name=file_name,
                    resolution="Image",
                    file_size=file_size,
                    status="Failed_MIME"
                )
                return False

            file_hash = calculate_file_hash(str(dest_path), is_video=False)
            if tracker.is_hash_downloaded(file_hash):
                logger.info(f"Duplicate image hash detected for {file_name}. Deleting.")
                os.remove(dest_path)
                tracker.log_download(
                    message_id=message.id,
                    channel_id=channel_id,
                    timestamp=message.date,
                    file_name=file_name,
                    resolution="Image",
                    file_size=file_size,
                    status="Duplicate_Hash",
                    file_hash=file_hash,
                    media_type="image",
                    message_text=message.text
                )
                return False

            tracker.log_download(
                message_id=message.id,
                channel_id=channel_id,
                timestamp=message.date,
                file_name=file_name,
                resolution="Image",
                file_size=file_size,
                status="Downloaded",
                file_hash=file_hash,
                media_type="image",
                message_text=message.text
            )
            logger.info(f"Successfully downloaded image: {dest_path.name}")
            return True
    except Exception as e:
        logger.error(f"Failed to download image Message ID {message.id}: {e}")
        if dest_path.exists():
            try:
                dest_path.unlink()
            except Exception:
                pass
        return False
