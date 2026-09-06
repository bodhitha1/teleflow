import re
import sqlite3
import logging
import asyncio
from pathlib import Path
from typing import Optional
from fastapi import Request, Response, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from telethon import TelegramClient

from config import BASE_DOWNLOAD_DIR
from core.state import AppState, get_safe_output_dir, ensure_client_connected

logger = logging.getLogger("web_app")

async def get_telegram_message_safe(client: TelegramClient, chat_id: int, message_id: int, channel_name: Optional[str] = None):
    """Safely fetches a message by chat_id and message_id across channel variants."""
    if not client:
        return None

    try:
        if not client.is_connected():
            await ensure_client_connected(client)
    except Exception:
        pass

    # 1. Direct try
    try:
        res = await client.get_messages(chat_id, ids=message_id)
        msg = res if not isinstance(res, list) else (res[0] if res else None)
        if msg and msg.media:
            return msg
    except Exception:
        pass

    # 2. Try with -100 prefix if positive channel ID
    if chat_id > 0:
        try:
            res = await client.get_messages(int(f"-100{chat_id}"), ids=message_id)
            msg = res if not isinstance(res, list) else (res[0] if res else None)
            if msg and msg.media:
                return msg
        except Exception:
            pass

    try:
        input_ent = await client.get_input_entity(chat_id)
        res = await client.get_messages(input_ent, ids=message_id)
        msg = res if not isinstance(res, list) else (res[0] if res else None)
        if msg and msg.media:
            return msg
    except Exception:
        pass

    # 3. Try resolving by channel_name if provided
    if channel_name:
        try:
            res = await client.get_messages(channel_name, ids=message_id)
            msg = res if not isinstance(res, list) else (res[0] if res else None)
            if msg and msg.media:
                return msg
        except Exception:
            pass

    # 4. Dialogs search fallback
    try:
        async for d in client.iter_dialogs(limit=100):
            d_id = getattr(d, 'id', 0)
            ent_id = getattr(d.entity, 'id', 0) if hasattr(d, 'entity') else 0
            d_name = getattr(d, 'name', '') or getattr(d.entity, 'title', '')
            if (
                d_id == chat_id
                or ent_id == chat_id
                or (chat_id > 0 and d_id == int(f"-100{chat_id}"))
                or (channel_name and d_name and d_name.lower() == channel_name.lower())
            ):
                res = await client.get_messages(d.input_entity, ids=message_id)
                msg = res if not isinstance(res, list) else (res[0] if res else None)
                if msg and msg.media:
                    return msg
                break
    except Exception:
        pass

    return None

class ThumbnailService:
    """OOP Service for fast thumbnail generation, concurrency throttling and disk caching."""
    EMPTY_GIF = b'GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\xff\xff\xff!\xf9\x04\x01\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x01D\x00;'

    def __init__(self):
        self._semaphore = asyncio.Semaphore(8)

    async def get_thumbnail(self, message_id: int, state: AppState, chat_id: Optional[int] = None) -> Response:
        # 1. Fast disk cache check: 0ms response time
        thumb_dir = (BASE_DOWNLOAD_DIR / state.phone / ".thumbs").resolve()
        thumb_dir.mkdir(parents=True, exist_ok=True)
        cache_key = f"{chat_id}_{message_id}" if chat_id else str(message_id)
        cached_thumb = thumb_dir / f"{cache_key}.jpg"
        legacy_thumb = thumb_dir / f"{message_id}.jpg"

        if cached_thumb.exists() and cached_thumb.stat().st_size > 0:
            return FileResponse(
                path=str(cached_thumb),
                media_type="image/jpeg",
                headers={"Cache-Control": "public, max-age=604800, immutable"}
            )
        if legacy_thumb.exists() and legacy_thumb.stat().st_size > 0:
            return FileResponse(
                path=str(legacy_thumb),
                media_type="image/jpeg",
                headers={"Cache-Control": "public, max-age=604800, immutable"}
            )

        media = None
        if hasattr(state, "pending_media") and state.pending_media:
            if chat_id:
                media = next((m for m in state.pending_media if m.get("id") == message_id and m.get("chat_id") == chat_id), None)
            if not media:
                media = next((m for m in state.pending_media if m.get("id") == message_id), None)

        # Dynamic Telegram fallback if media not in memory
        if (not media or not media.get("media_obj")) and state.client:
            try:
                output_dir = getattr(state, "current_output_dir", "./downloads")
                db_path = get_safe_output_dir(output_dir, state.phone) / "download_history.db"
                if db_path.exists():
                    with sqlite3.connect(db_path, timeout=5) as conn:
                        cursor = conn.cursor()
                        if chat_id:
                            cursor.execute("SELECT chat_id, channel_name FROM detected_media WHERE id = ? AND chat_id = ?", (message_id, chat_id))
                        else:
                            cursor.execute("SELECT chat_id, channel_name FROM detected_media WHERE id = ?", (message_id,))
                        row = cursor.fetchone()
                        if row:
                            target_chat_id, ch_name = row[0], row[1]
                            msg = await get_telegram_message_safe(state.client, target_chat_id, message_id, channel_name=ch_name)
                            if msg and msg.media:
                                media = {"id": message_id, "chat_id": target_chat_id, "media_obj": msg.media}
            except Exception:
                pass

        if not media or not media.get("media_obj"):
            return Response(content=self.EMPTY_GIF, media_type="image/gif")

        try:
            async with self._semaphore:
                bytes_data = await state.client.download_media(media["media_obj"], thumb=-1, file=bytes)
                if not bytes_data:
                    return Response(content=self.EMPTY_GIF, media_type="image/gif")

                # Cache to disk for instant subsequent loads
                try:
                    cached_thumb.write_bytes(bytes_data)
                except Exception:
                    pass

                return Response(
                    content=bytes_data,
                    media_type="image/jpeg",
                    headers={"Cache-Control": "public, max-age=604800, immutable"}
                )
        except Exception:
            return Response(content=self.EMPTY_GIF, media_type="image/gif")

class StreamService:
    """OOP Service for chunked HTTP Range video streaming."""

    async def stream(self, message_id: int, request: Request, state: AppState, chat_id: Optional[int] = None, download: bool = False):
        media = None
        if hasattr(state, "pending_media") and state.pending_media:
            if chat_id:
                media = next((m for m in state.pending_media if m.get("id") == message_id and m.get("chat_id") == chat_id), None)
            if not media:
                media = next((m for m in state.pending_media if m.get("id") == message_id), None)

        output_dir = getattr(state, "current_output_dir", "./downloads")
        try:
            db_path = get_safe_output_dir(output_dir, state.phone) / "download_history.db"
        except Exception:
            db_path = Path("./downloads") / state.phone / "download_history.db"

        target_chat_id = chat_id or (media.get("chat_id") if media else 0)
        f_name = media.get("file_name") or media.get("filename") if media else None
        m_type = media.get("type") if media else "video"
        f_size = media.get("size") if media else 0
        ch_name = media.get("channel_name") if media else None

        if db_path.exists():
            try:
                with sqlite3.connect(db_path, timeout=5) as conn:
                    cursor = conn.cursor()
                    if target_chat_id:
                        cursor.execute("SELECT chat_id, file_name, type, size, channel_name FROM detected_media WHERE id = ? AND chat_id = ?", (message_id, target_chat_id))
                    else:
                        cursor.execute("SELECT chat_id, file_name, type, size, channel_name FROM detected_media WHERE id = ?", (message_id,))
                    row = cursor.fetchone()
                    if row:
                        if not target_chat_id:
                            target_chat_id = row[0]
                        f_name = f_name or row[1]
                        m_type = row[2] or m_type
                        f_size = f_size or row[3]
                        ch_name = ch_name or row[4]
            except Exception:
                pass

        user_base = (BASE_DOWNLOAD_DIR / state.phone).resolve()
        content_type = "video/mp4" if m_type == "video" else ("image/jpeg" if m_type == "image" else "application/octet-stream")

        cache_key = f"{target_chat_id}_{message_id}" if target_chat_id else str(message_id)
        stream_cache_dir = (user_base / ".stream_cache").resolve()
        stream_cache_dir.mkdir(parents=True, exist_ok=True)
        cached_stream = stream_cache_dir / f"{cache_key}.mp4"
        legacy_stream = stream_cache_dir / f"{message_id}.mp4"

        def is_complete_file(p: Path) -> bool:
            if not p.exists() or not p.is_file():
                return False
            sz = p.stat().st_size
            if sz == 0:
                return False
            if f_size and f_size > 0:
                return sz >= f_size
            return True

        # 1. Local stream cache priority (must be complete file)
        valid_cache = None
        if is_complete_file(cached_stream):
            valid_cache = cached_stream
        elif is_complete_file(legacy_stream):
            valid_cache = legacy_stream

        if valid_cache:
            if download:
                return FileResponse(path=str(valid_cache), filename=f_name or f"media_{message_id}.mp4", media_type=content_type)
            return FileResponse(path=str(valid_cache), media_type=content_type)

        # 2. Local downloads folder search (excluding hidden folders like .thumbs and .stream_cache)
        local_file = None
        video_extensions = ('.mp4', '.mkv', '.avi', '.mov', '.webm', '.flv', '.wmv', '.m4v')
        image_extensions = ('.jpg', '.jpeg', '.png', '.webp', '.gif')

        def is_valid_local_candidate(p: Path) -> bool:
            try:
                rel = p.relative_to(user_base)
                if any(part.startswith('.') for part in rel.parts):
                    return False
            except Exception:
                if any(part.startswith('.') for part in p.parts):
                    return False
            if m_type == "video" and not p.name.lower().endswith(video_extensions):
                return False
            if m_type == "image" and not p.name.lower().endswith(image_extensions):
                return False
            if not p.is_file() or p.stat().st_size == 0:
                return False
            if f_size and f_size > 0:
                return p.stat().st_size >= f_size
            return True

        if f_name:
            for candidate in user_base.rglob(f_name):
                if is_valid_local_candidate(candidate):
                    local_file = candidate
                    break
        if not local_file:
            for candidate in user_base.rglob(f"*{message_id}*"):
                if is_valid_local_candidate(candidate):
                    local_file = candidate
                    break

        if local_file and local_file.exists():
            if download:
                return FileResponse(path=str(local_file), filename=f_name or local_file.name, media_type=content_type)
            return FileResponse(path=str(local_file), media_type=content_type)

        # 3. Dynamic Telegram fallback
        if (not media or not media.get("media_obj")) and state.client and (target_chat_id or ch_name):
            msg = await get_telegram_message_safe(state.client, target_chat_id, message_id, channel_name=ch_name)
            if msg and msg.media:
                media = {
                    "id": message_id,
                    "chat_id": target_chat_id,
                    "media_obj": msg.media,
                    "size": f_size or getattr(msg.media, "size", 0),
                    "type": m_type,
                    "filename": f_name or f"media_{message_id}.mp4"
                }

        if not media or not media.get("media_obj"):
            raise HTTPException(status_code=404, detail="Media not found or channel message not accessible.")

        file_size = media.get("size", 0) or f_size
        filename = media.get("filename") or media.get("file_name") or f_name or f"media_{message_id}.mp4"

        # HTTP Range header handling
        range_header = request.headers.get("range")
        start = 0
        end = (file_size - 1) if file_size else 0
        status_code = 200

        if range_header and file_size:
            range_match = re.match(r"bytes=(\d+)-(\d*)", range_header)
            if range_match:
                start = int(range_match.group(1))
                if range_match.group(2):
                    end = int(range_match.group(2))
                if start >= file_size or start > end:
                    return Response(status_code=416, headers={"Content-Range": f"bytes */{file_size}"})
                end = min(end, file_size - 1)
                status_code = 206

        content_length = (end - start) + 1 if file_size else 0

        headers = {
            "Accept-Ranges": "bytes",
            "Content-Type": content_type,
            "Cache-Control": "public, max-age=3600"
        }
        if status_code == 206:
            headers["Content-Range"] = f"bytes {start}-{end}/{file_size}"
        if content_length:
            headers["Content-Length"] = str(content_length)

        if download:
            headers["Content-Disposition"] = f'attachment; filename="{filename}"'

        async def chunk_generator():
            chunk_size = 512 * 1024  # 512KB chunks
            current_pos = start
            total_to_send = (end - start + 1) if (end is not None and file_size > 0) else None
            bytes_sent = 0

            part_file = None
            part_fp = None
            # Only cache when downloading full file from offset 0
            if download and start == 0 and file_size > 0:
                try:
                    part_file = stream_cache_dir / f"{cache_key}.mp4.part"
                    part_fp = open(part_file, "wb")
                except Exception:
                    part_fp = None

            stream_iter = None
            try:
                stream_iter = state.client.iter_download(
                    media["media_obj"],
                    offset=start,
                    request_size=chunk_size,
                    file_size=file_size or None
                )
                async for raw_chunk in stream_iter:
                    if not raw_chunk:
                        continue
                    chunk = bytes(raw_chunk) if not isinstance(raw_chunk, bytes) else raw_chunk

                    if total_to_send is not None:
                        remaining = total_to_send - bytes_sent
                        if remaining <= 0:
                            break
                        if len(chunk) > remaining:
                            chunk = chunk[:remaining]

                    if part_fp:
                        try:
                            part_fp.write(chunk)
                        except Exception:
                            pass

                    yield chunk
                    bytes_sent += len(chunk)

                    if total_to_send is not None and bytes_sent >= total_to_send:
                        break
            except (asyncio.CancelledError, GeneratorExit):
                pass
            except Exception as e:
                logger.warning(f"Streaming chunk error for msg {message_id}: {e}")
            finally:
                if stream_iter:
                    try:
                        await stream_iter.close()
                    except Exception:
                        pass
                if part_fp:
                    try:
                        part_fp.close()
                        if file_size > 0 and part_file and part_file.exists() and part_file.stat().st_size >= file_size:
                            part_file.replace(cached_stream)
                        elif part_file and part_file.exists():
                            part_file.unlink(missing_ok=True)
                    except Exception:
                        pass

        return StreamingResponse(chunk_generator(), status_code=status_code, headers=headers)

thumbnail_service = ThumbnailService()
stream_service = StreamService()

async def download_selected_task(req, state: AppState):
    from telegrab import DownloadTracker, calculate_file_hash
    from services.media_extractor import media_extractor
    from core.state import secure_filename, verify_file_type
    import random
    from telethon import errors

    try:
        output_dir = get_safe_output_dir(req.output_dir, state.phone)
        output_dir.mkdir(parents=True, exist_ok=True)
    except ValueError as e:
        logger.error(f"Invalid output directory: {e}")
        state.status = "idle"
        state.error_message = str(e)
        return

    db_path = output_dir / "download_history.db"
    tracker = DownloadTracker(db_path)

    state.status = "scraping"
    state.status_message = "Starting manual downloads..."
    state.media_downloaded = 0

    try:
        items_by_id = {}
        try:
            with sqlite3.connect(db_path, timeout=5) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                placeholders = ",".join(["?"] * len(req.selected_ids))
                cursor.execute(f"SELECT id, chat_id, channel_name, file_name, type, text, size FROM detected_media WHERE id IN ({placeholders})", req.selected_ids)
                for r in cursor.fetchall():
                    items_by_id[r["id"]] = dict(r)
        except Exception:
            pass

        for m in state.pending_media:
            if m["id"] in req.selected_ids and m["id"] not in items_by_id:
                items_by_id[m["id"]] = m

        for mid in req.selected_ids:
            if state.status != "scraping":
                break
            meta = items_by_id.get(mid, {})
            group_name = meta.get("channel_name") or "General"
            safe_group_name = secure_filename(group_name)
            channel_id = meta.get("chat_id") or 0

            if meta.get("type") == "msg":
                text_content = meta.get("text", "")
                dynamic_dir = output_dir / safe_group_name / "messages"
                dynamic_dir.mkdir(parents=True, exist_ok=True)
                dest_path = dynamic_dir / f"{mid}.txt"
                with open(dest_path, "w", encoding="utf-8") as f:
                    f.write(f"Channel: {group_name}\nMessage ID: {mid}\n\n{text_content}\n")
                tracker.log_download(
                    message_id=mid,
                    channel_id=channel_id,
                    timestamp=datetime.now(timezone.utc),
                    file_name=f"{mid}.txt",
                    resolution="N/A",
                    file_size=len(text_content.encode("utf-8")),
                    status="Downloaded",
                    file_hash="",
                    media_type="msg",
                    message_text=text_content
                )
                state.media_downloaded += 1
                continue

            target_val = channel_id or req.target
            try:
                target_val = int(target_val)
            except (ValueError, TypeError):
                pass

            try:
                entity = await state.client.get_entity(target_val)
                msg_res = await state.client.get_messages(entity, ids=mid)
                message = msg_res if not isinstance(msg_res, list) else (msg_res[0] if msg_res else None)
            except Exception as e:
                logger.warning(f"Could not fetch message {mid}: {e}")
                continue
            if state.status != "scraping":
                break

            if not message or not message.media:
                continue

            media_type, file_name, resolution, file_size, duration, document_id = media_extractor.extract(message)

            if not file_name:
                continue

            if tracker.is_downloaded(message.id):
                state.media_downloaded += 1
                continue

            year_month = message.date.strftime('%Y-%m') if message.date else "Unknown_Date"
            dynamic_dir = output_dir / safe_group_name / year_month
            dynamic_dir.mkdir(parents=True, exist_ok=True)

            dest_path = dynamic_dir / f"{message.id}_{file_name}"

            existing_size = 0
            if dest_path.exists():
                existing_size = dest_path.stat().st_size
                if existing_size >= file_size:
                    logger.info(f"File {file_name} already fully downloaded on disk. Rescanning hash.")
                    file_hash = calculate_file_hash(str(dest_path), media_type == "video")
                    tracker.log_download(
                        message_id=message.id,
                        channel_id=channel_id,
                        timestamp=message.date,
                        file_name=file_name,
                        resolution=resolution,
                        file_size=file_size,
                        status="Downloaded",
                        file_hash=file_hash,
                        media_type=media_type,
                        message_text=message.text
                    )
                    state.media_downloaded += 1
                    continue

            state.current_download_file = file_name
            state.current_download_size = file_size

            try:
                logger.info(f"Downloading {file_name} (Resume offset: {existing_size})...")
                await asyncio.sleep(0.5)

                if existing_size < file_size:
                    chunk_size = 1048576  # 1MB max Telegram chunk
                    aligned_offset = (existing_size // chunk_size) * chunk_size

                    if dest_path.exists():
                        with open(dest_path, 'r+b') as f:
                            f.truncate(aligned_offset)

                    current_downloaded = aligned_offset
                    state.current_download_progress = int((current_downloaded / file_size) * 100) if file_size else 0

                    with open(dest_path, 'ab') as f:
                        async for chunk in state.client.iter_download(message.media, offset=aligned_offset, request_size=chunk_size):
                            f.write(chunk)
                            current_downloaded += len(chunk)
                            if file_size:
                                state.current_download_progress = int((current_downloaded / file_size) * 100)

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
                    state.media_failed += 1
                    continue

                file_hash = calculate_file_hash(str(dest_path), media_type == "video")
                if tracker.is_hash_downloaded(file_hash):
                    logger.info(f"Duplicate content detected for {file_name}. Deleting.")
                    os.remove(dest_path)
                    tracker.log_download(
                        message_id=message.id,
                        channel_id=channel_id,
                        timestamp=message.date,
                        file_name=file_name,
                        resolution=resolution,
                        file_size=file_size,
                        status="Duplicate_Hash",
                        file_hash=file_hash,
                        media_type=media_type,
                        message_text=message.text
                    )
                    continue

                tracker.log_download(
                    message_id=message.id,
                    channel_id=channel_id,
                    timestamp=message.date,
                    file_name=file_name,
                    resolution=resolution,
                    file_size=file_size,
                    status="Downloaded",
                    file_hash=file_hash,
                    media_type=media_type,
                    message_text=message.text
                )
                state.media_downloaded += 1

                if file_size > 10 * 1024 * 1024:
                    await asyncio.sleep(random.uniform(3.0, 7.0))

            except errors.FloodWaitError as e:
                logger.error(f"Flood wait during download. Sleeping for {e.seconds} seconds.")
                state.status_message = f"Flood Wait: {e.seconds}s"
                await asyncio.sleep(e.seconds)
            except Exception as e:
                logger.error(f"Failed to download {file_name}: {e}")
            finally:
                state.current_download_file = ""
                state.current_download_size = 0
                state.current_download_progress = 0
                state.status_message = ""

    except Exception as e:
        logger.error(f"Error during manual download task: {e}")
    finally:
        state.status = "idle"
        state.status_message = ""

