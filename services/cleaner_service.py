import time
import asyncio
import logging
from pathlib import Path
from datetime import datetime

from config import CLEANER_INTERVAL_SECONDS, CACHE_EXPIRE_HOURS
from core.state import session_manager

logger = logging.getLogger("web_app")

class AutoCleanerService:
    """OOP Service for automated background junk and cache cleanup."""

    def cleanup_junk_and_cache(self, base_dir: Path, max_age_seconds: int = 1800) -> dict:
        now = datetime.now().timestamp()
        files_deleted = 0
        bytes_freed = 0
        sessions_pruned = 0

        # Clean .stream_cache and temp folders
        if base_dir.exists():
            for stream_dir in base_dir.rglob(".stream_cache"):
                if stream_dir.is_dir():
                    for f in stream_dir.glob("*.mp4"):
                        try:
                            mtime = f.stat().st_mtime
                            if (now - mtime) >= max_age_seconds:
                                size = f.stat().st_size
                                f.unlink(missing_ok=True)
                                files_deleted += 1
                                bytes_freed += size
                        except Exception:
                            pass

        # Clean temporary download fragments
        for pattern in ["*.temp", "*.part", "*.download", "*.tmp"]:
            try:
                for temp_file in base_dir.rglob(pattern):
                    try:
                        mtime = temp_file.stat().st_mtime
                        if (now - mtime) >= max_age_seconds:
                            size = temp_file.stat().st_size
                            temp_file.unlink(missing_ok=True)
                            files_deleted += 1
                            bytes_freed += size
                    except Exception:
                        pass
            except Exception:
                pass

        # Clean rotated log files (.1, .2, etc.)
        log_files = [Path("web_app.log"), Path("telegrab.log")]
        for lf in log_files:
            for rot_path in Path(".").glob(f"{lf.name}.*"):
                if rot_path.is_file() and rot_path.name != lf.name:
                    try:
                        mtime = rot_path.stat().st_mtime
                        if (now - mtime) >= max_age_seconds:
                            size = rot_path.stat().st_size
                            rot_path.unlink(missing_ok=True)
                            files_deleted += 1
                            bytes_freed += size
                    except Exception:
                        pass

        # Clean empty directories
        downloads_dir = Path("./downloads").resolve()
        if downloads_dir.exists():
            try:
                for d in sorted(downloads_dir.rglob("*"), key=lambda p: len(str(p)), reverse=True):
                    if d.is_dir() and not any(d.iterdir()):
                        try:
                            d.rmdir()
                        except Exception:
                            pass
            except Exception:
                pass

        # Prune in-memory session caches
        try:
            for phone, state in list(session_manager.all().items()):
                if hasattr(state, "pending_media") and state.pending_media:
                    orig_len = len(state.pending_media)
                    if orig_len > 1000:
                        state.pending_media = state.pending_media[-500:]
                        sessions_pruned += (orig_len - len(state.pending_media))

                if hasattr(state, "collected_links_list") and len(state.collected_links_list) > 200:
                    if state.status == "idle" and not getattr(state, "is_watching", False):
                        state.collected_links_list = state.collected_links_list[-100:]
        except Exception as e:
            logger.warning(f"Error while pruning active sessions in-memory cache: {e}")

        logger.info(f"🧹 [Auto-Cleanup 30m] Cleaned {files_deleted} junk files ({(bytes_freed / (1024 * 1024)):.2f} MB freed). Trimmed {sessions_pruned} memory cache entries.")
        return {
            "files_deleted": files_deleted,
            "bytes_freed": bytes_freed,
            "sessions_pruned": sessions_pruned,
            "human_freed": f"{(bytes_freed / (1024 * 1024)):.2f} MB"
        }

    async def start_background_loop(self):
        logger.info(f"Auto Cache & Junk Cleaner daemon started (Interval: {CLEANER_INTERVAL_SECONDS}s).")
        while True:
            try:
                await asyncio.sleep(CLEANER_INTERVAL_SECONDS)
                self.cleanup_junk_and_cache(Path("./downloads").resolve(), max_age_seconds=CLEANER_INTERVAL_SECONDS)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Auto cache cleaner loop error: {e}")

cleaner_service = AutoCleanerService()
