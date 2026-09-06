import asyncio
import logging
from pathlib import Path
from datetime import datetime, timezone
from telethon import events
from fastapi import HTTPException

from core.state import AppState, get_safe_output_dir
from models.schemas import WatchRequest
from database.media_db import MediaDatabaseManager
from services.media_extractor import media_extractor

logger = logging.getLogger("web_app")

class DaemonWatcher:
    """OOP Service for real-time channel watching, gap catch-up sync, and live card broadcasting."""

    async def run_catchup_sync(self, client, entities, db_mgr: MediaDatabaseManager, state: AppState, req: WatchRequest):
        total_caught_up = 0
        for entity in entities:
            chat_id = getattr(entity, 'id', 0)
            channel_name = getattr(entity, 'title', None) or getattr(entity, 'username', None) or str(chat_id)
            last_id = db_mgr.get_checkpoint(chat_id)
            if not last_id:
                continue

            logger.info(f"Running catch-up sync for '{channel_name}' from Message ID {last_id}...")
            items_to_save = []
            try:
                async for message in client.iter_messages(entity, min_id=last_id, limit=300):
                    if not message:
                        continue
                    if message.id > last_id:
                        db_mgr.update_checkpoint(chat_id, channel_name, message.id)

                    media_t, fname, resol, fsize, dur, doc_id = media_extractor.extract(message)

                    if not media_t:
                        if message.media:
                            if hasattr(message.media, 'photo'):
                                media_t = "image"
                                fname = f"photo_{message.id}.jpg"
                            elif hasattr(message.media, 'document'):
                                media_t = "video"
                                fname = f"video_{message.id}.mp4"
                            elif message.text and message.text.strip():
                                media_t = "msg"
                                fname = f"message_{message.id}.txt"
                            else:
                                media_t = "others"
                                fname = f"doc_{message.id}"
                        elif message.text and message.text.strip():
                            media_t = "msg"
                            fname = f"message_{message.id}.txt"

                    if media_t == "video" and not req.scrape_videos:
                        continue
                    if media_t == "image" and not req.scrape_images:
                        continue
                    if media_t == "msg" and not getattr(req, "scrape_messages", True):
                        continue
                    if media_t == "others" and not getattr(req, "scrape_others", True):
                        continue

                    item = {
                        "id": message.id,
                        "chat_id": chat_id,
                        "channel_name": channel_name,
                        "file_name": fname,
                        "filename": fname,
                        "resolution": resol or "Unknown",
                        "size": fsize,
                        "duration": dur,
                        "type": media_t,
                        "text": message.text or "",
                        "date": message.date.isoformat() if message.date else datetime.now(timezone.utc).isoformat(),
                        "source": "daemon",
                        "media_obj": message.media
                    }
                    items_to_save.append(item)
                    state.pending_media.append(item)
                    if len(state.pending_media) > 500:
                        state.pending_media.pop(0)
                    total_caught_up += 1

                    if len(items_to_save) >= 200:
                        db_mgr.save_media_batch(items_to_save)
                        items_to_save.clear()

                if items_to_save:
                    db_mgr.save_media_batch(items_to_save)
                    items_to_save.clear()
            except Exception as e:
                logger.warning(f"Error during catch-up for {channel_name}: {e}")

        if total_caught_up > 0:
            logger.info(f"Catch-up completed: Ingested {total_caught_up} missed items across channels.")

    async def start(self, req: WatchRequest, state: AppState) -> dict:
        if not state.client or state.status != "connected":
            raise HTTPException(status_code=400, detail="Client not connected.")

        if state.is_watching:
            return {"status": "success", "message": "Already watching."}

        try:
            output_dir = get_safe_output_dir(req.output_dir, state.phone)
            db_mgr = MediaDatabaseManager(output_dir / "download_history.db")
            db_mgr.init_db()
        except Exception:
            db_mgr = MediaDatabaseManager(Path("./downloads") / state.phone / "download_history.db")
            db_mgr.init_db()

        try:
            target_str = (req.target or "ALL").strip()
            chats_filter = None
            entities_to_catchup = []

            if target_str != "ALL":
                if "," in target_str:
                    raw_targets = [t.strip() for t in target_str.split(",") if t.strip()]
                    resolved_entities = []
                    for t in raw_targets:
                        t_val = int(t) if t.lstrip("-").isdigit() else t
                        try:
                            ent = await state.client.get_entity(t_val)
                            resolved_entities.append(ent)
                        except Exception as ent_err:
                            logger.warning(f"Could not resolve watch entity '{t}': {ent_err}")
                    if resolved_entities:
                        chats_filter = resolved_entities
                        entities_to_catchup = resolved_entities
                    else:
                        raise HTTPException(status_code=400, detail="Could not resolve any of the selected channels.")
                else:
                    t_val = int(target_str) if target_str.lstrip("-").isdigit() else target_str
                    ent = await state.client.get_entity(t_val)
                    chats_filter = ent
                    entities_to_catchup = [ent]
            else:
                try:
                    async for dialog in state.client.iter_dialogs(limit=50):
                        if dialog.is_channel or dialog.is_group:
                            entities_to_catchup.append(dialog.entity)
                except Exception as e:
                    logger.warning(f"Could not list dialogs for catch-up: {e}")

            # Run gap catch-up sync before attaching listener
            if entities_to_catchup:
                asyncio.create_task(self.run_catchup_sync(state.client, entities_to_catchup, db_mgr, state, req))

            async def watcher_callback(event):
                if not getattr(event, "message", None):
                    return
                if not event.message.media and not event.message.message:
                    return

                try:
                    chat = await event.get_chat()
                    channel_name = getattr(chat, 'title', None) or getattr(chat, 'username', None) or str(getattr(event, "chat_id", "Direct Message"))
                except Exception:
                    channel_name = str(getattr(event, "chat_id", "Channel"))

                chat_id = getattr(event, "chat_id", 0)
                db_mgr.update_checkpoint(chat_id, channel_name, event.message.id)

                media_type = "msg"
                filename = f"message_{event.message.id}.txt"
                file_size = 0
                resolution = "Unknown"
                duration = 0

                if event.message.media:
                    media_t, fname, resol, fsize, dur, doc_id = media_extractor.extract(event.message)
                    if media_t:
                        media_type = media_t
                        filename = fname or filename
                        file_size = fsize
                        resolution = resol or resolution
                        duration = dur
                    else:
                        if hasattr(event.message.media, 'photo'):
                            media_type = "image"
                            filename = f"photo_{event.message.id}.jpg"
                        elif hasattr(event.message.media, 'document'):
                            media_type = "video"
                            filename = f"video_{event.message.id}.mp4"
                        elif event.message.message and event.message.message.strip():
                            media_type = "msg"
                            filename = f"message_{event.message.id}.txt"
                        else:
                            media_type = "others"
                            filename = f"doc_{event.message.id}"

                if media_type == "video" and not req.scrape_videos:
                    return
                if media_type == "image" and not req.scrape_images:
                    return
                if media_type == "msg" and not getattr(req, "scrape_messages", True):
                    return
                if media_type == "others" and not getattr(req, "scrape_others", True):
                    return

                card_payload = {
                    "type": "DAEMON_NEW_MEDIA",
                    "message_id": event.message.id,
                    "chat_id": chat_id,
                    "channel_name": channel_name,
                    "media_type": media_type,
                    "filename": filename,
                    "file_size": file_size,
                    "date": event.message.date.isoformat() if event.message.date else datetime.now(timezone.utc).isoformat(),
                    "text": event.message.message[:120] + "..." if event.message.message else ""
                }

                media_entry = {
                    "id": event.message.id,
                    "chat_id": chat_id,
                    "channel_name": channel_name,
                    "file_name": filename,
                    "filename": filename,
                    "resolution": resolution,
                    "size": file_size,
                    "duration": duration,
                    "type": media_type,
                    "text": event.message.message or "",
                    "date": event.message.date.isoformat() if event.message.date else datetime.now(timezone.utc).isoformat(),
                    "source": "daemon",
                    "media_obj": event.message.media
                }

                db_mgr.save_media(media_entry)
                state.pending_media.append(media_entry)

                if len(state.pending_media) > 500:
                    state.pending_media.pop(0)

                disconnected = []
                for ws in list(state.watch_websockets):
                    try:
                        await ws.send_json(card_payload)
                    except Exception:
                        disconnected.append(ws)
                for ws in disconnected:
                    if ws in state.watch_websockets:
                        state.watch_websockets.remove(ws)

            state.watcher_handler = watcher_callback

            if chats_filter:
                state.client.add_event_handler(state.watcher_handler, events.NewMessage(chats=chats_filter))
            else:
                state.client.add_event_handler(state.watcher_handler, events.NewMessage())

            state.is_watching = True
            return {"status": "success", "message": "Daemon started."}
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Failed to start watch: {e}")
            raise HTTPException(status_code=400, detail=str(e))

    def stop(self, state: AppState) -> dict:
        if state.watcher_handler and state.client:
            try:
                state.client.remove_event_handler(state.watcher_handler)
            except Exception as e:
                logger.warning(f"Error removing watcher handler: {e}")
        state.watcher_handler = None
        state.is_watching = False
        return {"status": "success", "message": "Daemon stopped."}

daemon_watcher = DaemonWatcher()
