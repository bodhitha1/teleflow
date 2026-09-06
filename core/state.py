import os
import re
import asyncio
import logging
from pathlib import Path
from typing import Dict, List, Optional
from fastapi import Request, WebSocket, HTTPException
from telethon import TelegramClient

from config import BASE_DOWNLOAD_DIR, ALLOWED_EXTENSIONS

logger = logging.getLogger("web_app")

def secure_filename(filename: str) -> str:
    if not filename:
        return "unknown_file"
    filename = os.path.basename(filename)
    filename = re.sub(r'[^a-zA-Z0-9_.-]', '_', filename)
    filename = filename.strip('._')
    return filename or "unknown_file"

def verify_file_type(filepath: str) -> bool:
    try:
        import magic
        mime = magic.from_file(filepath, mime=True)
        if mime and not mime.startswith(('image/', 'video/', 'audio/', 'application/pdf')):
            return False
        return True
    except Exception:
        return True

def get_safe_output_dir(user_path: str, phone: str) -> Path:
    target_path = Path(user_path)
    
    # Absolute Path Handling with Security Controls
    if target_path.is_absolute():
        allowed_dirs_env = os.getenv("ALLOWED_OUTPUT_DIRS", "")
        if not allowed_dirs_env:
            raise ValueError("Absolute paths are disabled for security. Admin must set ALLOWED_OUTPUT_DIRS in .env")
            
        allowed_dirs = [Path(d.strip()).resolve() for d in allowed_dirs_env.split(",") if d.strip()]
        resolved = target_path.resolve()
        
        is_allowed = any(str(resolved).startswith(str(d)) for d in allowed_dirs)
        if not is_allowed:
            raise ValueError(f"Path not allowed. Absolute paths must be within one of: {allowed_dirs_env}")
            
        allow_shared = os.getenv("ALLOW_SHARED_OUTPUT", "false").lower() == "true"
        if not allow_shared:
            resolved = resolved / phone
            
        resolved.mkdir(parents=True, exist_ok=True)
        return resolved
        
    # Relative Path Handling (Always isolated)
    user_base_dir = (BASE_DOWNLOAD_DIR / phone).resolve()
    user_base_dir.mkdir(parents=True, exist_ok=True)
    
    cleaned_path = str(user_path).strip().replace('\\', '/').strip('./')
    if cleaned_path in ("", "downloads"):
        return user_base_dir
        
    safe_path = str(user_path).lstrip('/\\')
    if '..' in safe_path:
        raise ValueError("Directory traversal is not allowed for relative paths")
        
    resolved = (user_base_dir / safe_path).resolve()
    if not str(resolved).startswith(str(user_base_dir)):
        raise ValueError("Relative output directory must be within your user downloads folder")
        
    return resolved

class AppState:
    """Encapsulates per-user active Telegram session state."""
    def __init__(self):
        self.client: Optional[TelegramClient] = None
        self.api_id: Optional[int] = None
        self.api_hash: Optional[str] = None
        self.phone: Optional[str] = None
        self.fernet_key: Optional[bytes] = None
        self.phone_code_hash: Optional[str] = None
        
        # Daemon state
        self.is_watching: bool = False
        self.watcher_handler = None
        self.watch_websockets: list = []
        
        # Scraper state
        self.status = "idle"  # idle, authenticating, connected, scraping, validating
        self.error_message: Optional[str] = None
        self.status_message: Optional[str] = None
        self.current_output_dir: str = "./downloads"
        
        # Stats
        self.messages_scanned = 0
        self.media_found = 0
        self.videos_found = 0
        self.images_found = 0
        self.urls_found = 0
        self.media_downloaded = 0
        self.images_downloaded = 0
        self.media_failed = 0
        self.urls_valid = 0
        self.validation_current = 0
        self.validation_total = 0
        
        # Active download tracking
        self.current_download_file = ""
        self.current_download_size = 0
        self.current_download_progress = 0
        self.validation_status_msg: Optional[str] = None
        self.collected_links_list: list = []
        self.pending_media: list = []

    async def ensure_connected(self, max_retries: int = 3, retry_delay: float = 3.0) -> bool:
        """Ensures the Telegram client is connected, automatically reconnecting if connection dropped."""
        return await ensure_client_connected(self.client, max_retries=max_retries, retry_delay=retry_delay)

async def ensure_client_connected(client: Optional[TelegramClient], max_retries: int = 3, retry_delay: float = 3.0) -> bool:
    """Ensures the Telegram client is actively connected, automatically reconnecting if disconnected."""
    if not client:
        return False
    try:
        if client.is_connected():
            return True
    except Exception:
        pass

    logger.warning("Telegram client disconnected. Initiating automatic reconnection...")
    for attempt in range(1, max_retries + 1):
        try:
            await asyncio.wait_for(client.connect(), timeout=15.0)
            if client.is_connected():
                logger.info(f"Telegram client successfully reconnected (attempt {attempt}/{max_retries}).")
                return True
        except Exception as e:
            logger.warning(f"Reconnection attempt {attempt}/{max_retries} failed: {e}")
            if attempt < max_retries:
                await asyncio.sleep(retry_delay)
    return False

class SessionManager:
    """OOP Manager for user session storage and lifecycle."""
    def __init__(self):
        self.active_sessions: Dict[str, AppState] = {}

    def get_or_create(self, phone: str) -> AppState:
        if phone not in self.active_sessions:
            state = AppState()
            state.phone = phone
            self.active_sessions[phone] = state
        return self.active_sessions[phone]

    def get(self, phone: str) -> Optional[AppState]:
        return self.active_sessions.get(phone)

    def remove(self, phone: str):
        if phone in self.active_sessions:
            del self.active_sessions[phone]

    def all(self) -> Dict[str, AppState]:
        return self.active_sessions

session_manager = SessionManager()

def get_current_state(request: Request) -> AppState:
    phone = getattr(request.state, "user_phone", None)
    if not phone:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return session_manager.get_or_create(phone)

class TelemetryConnectionManager:
    """Manages WebSocket telemetry connections per user phone."""
    def __init__(self):
        self.active_connections: Dict[str, List[WebSocket]] = {}
        self.last_hashes: Dict[str, int] = {}
        self.heartbeat_counters: Dict[str, int] = {}

    async def connect(self, websocket: WebSocket, phone: str):
        if phone not in self.active_connections:
            self.active_connections[phone] = []
            self.last_hashes[phone] = None
            self.heartbeat_counters[phone] = 0
        self.active_connections[phone].append(websocket)

    def disconnect(self, websocket: WebSocket, phone: str):
        if phone in self.active_connections and websocket in self.active_connections[phone]:
            self.active_connections[phone].remove(websocket)
            if not self.active_connections[phone]:
                del self.active_connections[phone]
                self.last_hashes.pop(phone, None)
                self.heartbeat_counters.pop(phone, None)

    async def broadcast(self, phone: str, message: dict):
        if phone not in self.active_connections:
            return
        dead_connections = []
        for connection in self.active_connections[phone]:
            try:
                await connection.send_json(message)
            except Exception:
                dead_connections.append(connection)
        for dc in dead_connections:
            self.disconnect(dc, phone)

telemetry_manager = TelemetryConnectionManager()

task_queue = asyncio.Queue()

async def worker_loop():
    while True:
        task_func, args, kwargs = await task_queue.get()
        try:
            await task_func(*args, **kwargs)
        except Exception as e:
            logger.error(f"Worker task failed: {e}")
        finally:
            task_queue.task_done()
