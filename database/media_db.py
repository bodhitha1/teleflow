import sqlite3
import logging
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any

from core.state import get_safe_output_dir

logger = logging.getLogger("web_app")

class MediaDatabaseManager:
    """OOP Manager for per-user SQLite database operations."""
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._initialized = False

    def init_db(self):
        """Initializes database schema, indexes and WAL mode."""
        if self._initialized and self.db_path.exists():
            return
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with sqlite3.connect(self.db_path, timeout=10) as conn:
                cursor = conn.cursor()
                cursor.execute("PRAGMA journal_mode=WAL;")
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS detected_media (
                        id INTEGER,
                        chat_id INTEGER,
                        channel_name TEXT,
                        file_name TEXT,
                        resolution TEXT,
                        size INTEGER,
                        duration INTEGER,
                        type TEXT,
                        text TEXT,
                        date TEXT,
                        status TEXT DEFAULT 'pending',
                        source TEXT DEFAULT 'daemon',
                        PRIMARY KEY(id, chat_id)
                    )
                """)
                try:
                    cursor.execute("ALTER TABLE detected_media ADD COLUMN source TEXT DEFAULT 'daemon';")
                except Exception:
                    pass
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_dm_type ON detected_media(type);")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_dm_channel ON detected_media(channel_name);")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_dm_date ON detected_media(date);")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_dm_source ON detected_media(source);")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_dm_filter ON detected_media(source, type, date DESC, id DESC);")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_dm_channel_type ON detected_media(channel_name, type, date DESC, id DESC);")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_dm_chat_msg ON detected_media(chat_id, id);")
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS channel_checkpoints (
                        chat_id INTEGER PRIMARY KEY,
                        channel_name TEXT,
                        last_message_id INTEGER,
                        last_updated TEXT
                    )
                """)
                conn.commit()
                self._initialized = True
        except Exception as e:
            logger.error(f"Error initializing media database at {self.db_path}: {e}")

    def save_media(self, item: dict):
        """Inserts or replaces a detected media entry."""
        try:
            self.init_db()
            with sqlite3.connect(self.db_path, timeout=10) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT OR REPLACE INTO detected_media (
                        id, chat_id, channel_name, file_name, resolution, size, duration, type, text, date, status, source
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    item["id"],
                    item.get("chat_id", 0),
                    item.get("channel_name", "Unknown"),
                    item.get("file_name") or item.get("filename", f"file_{item['id']}"),
                    item.get("resolution", "N/A"),
                    item.get("size", 0),
                    item.get("duration", 0),
                    item.get("type", "others"),
                    item.get("text", ""),
                    item.get("date", datetime.now(timezone.utc).isoformat()),
                    item.get("status", "pending"),
                    item.get("source", "daemon")
                ))
                conn.commit()
        except Exception as e:
            logger.error(f"Failed to save media entry to db: {e}")

    def save_media_batch(self, items: List[dict]):
        """Batch inserts or replaces detected media entries in a single transaction for high performance."""
        if not items:
            return
        try:
            self.init_db()
            now_iso = datetime.now(timezone.utc).isoformat()
            records = [
                (
                    item["id"],
                    item.get("chat_id", 0),
                    item.get("channel_name", "Unknown"),
                    item.get("file_name") or item.get("filename", f"file_{item['id']}"),
                    item.get("resolution", "N/A"),
                    item.get("size", 0),
                    item.get("duration", 0),
                    item.get("type", "others"),
                    item.get("text", ""),
                    item.get("date", now_iso),
                    item.get("status", "pending"),
                    item.get("source", "daemon")
                )
                for item in items
            ]
            with sqlite3.connect(self.db_path, timeout=15) as conn:
                cursor = conn.cursor()
                cursor.executemany("""
                    INSERT OR REPLACE INTO detected_media (
                        id, chat_id, channel_name, file_name, resolution, size, duration, type, text, date, status, source
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, records)
                conn.commit()
        except Exception as e:
            logger.error(f"Failed to batch save media entries: {e}")

    def update_checkpoint(self, chat_id: int, channel_name: str, message_id: int):
        """Updates last seen message ID checkpoint for a channel."""
        try:
            self.init_db()
            with sqlite3.connect(self.db_path, timeout=10) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT OR REPLACE INTO channel_checkpoints (chat_id, channel_name, last_message_id, last_updated)
                    VALUES (?, ?, ?, ?)
                """, (chat_id, channel_name, message_id, datetime.now(timezone.utc).isoformat()))
                conn.commit()
        except Exception as e:
            logger.error(f"Failed to update checkpoint: {e}")

    def get_checkpoint(self, chat_id: int) -> Optional[int]:
        """Retrieves checkpoint last message ID for a channel."""
        try:
            if not self.db_path.exists():
                return None
            with sqlite3.connect(self.db_path, timeout=10) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT last_message_id FROM channel_checkpoints WHERE chat_id = ?", (chat_id,))
                row = cursor.fetchone()
                return row[0] if row else None
        except Exception:
            return None

    def query_media(
        self,
        in_memory_items: list = None,
        category: str = "all",
        source: str = "all",
        channel: str = None,
        search: str = None,
        sort: str = "newest",
        limit: int = 25,
        offset: int = 0
    ) -> dict:
        """Queries detected media with filtering, search, sorting and pagination."""
        if in_memory_items:
            self.save_media_batch(in_memory_items)

        self.init_db()
        where_clauses = []
        params = []

        if category and category.lower() != "all":
            where_clauses.append("type = ?")
            params.append(category.lower())

        if source and source.strip().lower() != "all":
            where_clauses.append("source = ?")
            params.append(source.strip().lower())

        if channel and channel.strip() and channel.strip().lower() != "all":
            where_clauses.append("channel_name = ?")
            params.append(channel.strip())

        if search and search.strip():
            term = f"%{search.strip().lower()}%"
            where_clauses.append("(LOWER(file_name) LIKE ? OR LOWER(channel_name) LIKE ? OR LOWER(text) LIKE ?)")
            params.extend([term, term, term])

        where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

        sort_orders = {
            "newest": "date DESC, id DESC",
            "oldest": "date ASC, id ASC",
            "largest": "size DESC",
            "smallest": "size ASC"
        }
        order_sql = sort_orders.get(sort, "date DESC, id DESC")

        with sqlite3.connect(self.db_path, timeout=10) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            cursor.execute(f"SELECT COUNT(*) FROM detected_media {where_sql}", params)
            total = cursor.fetchone()[0]

            query_sql = f"""
                SELECT id, chat_id, channel_name, file_name, resolution, size, duration, type, text, date, status, source
                FROM detected_media {where_sql}
                ORDER BY {order_sql}
                LIMIT ? OFFSET ?
            """
            fetch_params = params + [limit, offset]
            cursor.execute(query_sql, fetch_params)
            rows = [dict(r) for r in cursor.fetchall()]

        return {
            "status": "success",
            "total": total,
            "limit": limit,
            "offset": offset,
            "media": rows
        }

    def get_summary(self, in_memory_items: list = None, source: str = "all") -> dict:
        """Generates counts per category, source, and unique channels list."""
        if in_memory_items:
            self.save_media_batch(in_memory_items)

        self.init_db()
        counts = {"all": 0, "video": 0, "image": 0, "msg": 0, "others": 0}
        sources = {"all": 0, "daemon": 0, "scraper": 0}
        total = 0

        with sqlite3.connect(self.db_path, timeout=10) as conn:
            cursor = conn.cursor()

            # Source counts
            cursor.execute("SELECT source, COUNT(*) FROM detected_media GROUP BY source")
            for row in cursor.fetchall():
                s_name, s_cnt = row[0] or "daemon", row[1]
                if s_name in sources:
                    sources[s_name] = s_cnt
                else:
                    sources["daemon"] += s_cnt
            cursor.execute("SELECT COUNT(*) FROM detected_media")
            sources["all"] = cursor.fetchone()[0]

            # Category counts
            if source and source.strip().lower() != "all":
                cursor.execute("SELECT type, COUNT(*) FROM detected_media WHERE source = ? GROUP BY type", (source.strip().lower(),))
            else:
                cursor.execute("SELECT type, COUNT(*) FROM detected_media GROUP BY type")

            for row in cursor.fetchall():
                m_type, cnt = row[0], row[1]
                if m_type in counts:
                    counts[m_type] = cnt
                else:
                    counts["others"] += cnt
                total += cnt
            counts["all"] = total

            # Channels
            if source and source.strip().lower() != "all":
                cursor.execute(
                    "SELECT DISTINCT channel_name FROM detected_media WHERE source = ? AND channel_name IS NOT NULL AND channel_name != '' ORDER BY channel_name ASC",
                    (source.strip().lower(),)
                )
            else:
                cursor.execute(
                    "SELECT DISTINCT channel_name FROM detected_media WHERE channel_name IS NOT NULL AND channel_name != '' ORDER BY channel_name ASC"
                )
            channels = [r[0] for r in cursor.fetchall()]

        return {
            "status": "success",
            "total": total,
            "counts": counts,
            "sources": sources,
            "channels": channels
        }

    def clear_media(
        self,
        source: Optional[str] = "all",
        category: Optional[str] = "all",
        channel: Optional[str] = None,
        ids: Optional[List[int]] = None
    ) -> int:
        """Deletes items matching criteria or IDs, returns count of deleted rows."""
        if not self.db_path.exists():
            return 0

        deleted_count = 0
        with sqlite3.connect(self.db_path, timeout=10) as conn:
            cursor = conn.cursor()
            if ids:
                placeholders = ",".join("?" for _ in ids)
                cursor.execute(f"DELETE FROM detected_media WHERE id IN ({placeholders})", ids)
                deleted_count = cursor.rowcount
            else:
                query = "DELETE FROM detected_media WHERE 1=1"
                params = []
                if source and source != "all":
                    query += " AND source = ?"
                    params.append(source)
                if category and category != "all":
                    query += " AND type = ?"
                    params.append(category)
                if channel and channel != "all":
                    query += " AND channel_name = ?"
                    params.append(channel)
                cursor.execute(query, params)
                deleted_count = cursor.rowcount
            conn.commit()
        return deleted_count

def get_media_db(phone: str, output_dir: str = "./downloads") -> MediaDatabaseManager:
    """Helper to instantiate MediaDatabaseManager for given user phone."""
    try:
        db_path = get_safe_output_dir(output_dir, phone) / "download_history.db"
    except Exception:
        db_path = Path("./downloads") / phone / "download_history.db"
    return MediaDatabaseManager(db_path)

def get_db_stats(output_dir: str, phone: str) -> Dict[str, Any]:
    """Helper to get overall download statistics."""
    try:
        safe_dir = get_safe_output_dir(output_dir, phone)
    except ValueError:
        return {"total": 0, "downloaded": 0, "failed": 0}
    db_path = safe_dir / "download_history.db"
    if not db_path.exists():
        return {"total": 0, "downloaded": 0, "failed": 0}
    try:
        with sqlite3.connect(db_path, timeout=10) as conn:
            cursor = conn.cursor()
            cursor.execute('PRAGMA journal_mode=WAL;')
            cursor.execute("SELECT COUNT(*) FROM downloads")
            total = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM downloads WHERE status = 'Downloaded'")
            downloaded = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM downloads WHERE status = 'Failed'")
            failed = cursor.fetchone()[0]
            return {"total": total, "downloaded": downloaded, "failed": failed}
    except Exception:
        return {"total": 0, "downloaded": 0, "failed": 0}
