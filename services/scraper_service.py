import re
import random
import asyncio
import logging
from pathlib import Path
from datetime import datetime, timezone
from typing import List, Set
from telethon import TelegramClient, errors
from telethon.tl.functions.messages import CheckChatInviteRequest
from telethon.errors import InviteHashExpiredError, InviteHashInvalidError

from config import TELEGRAM_LINK_REGEX
from core.state import AppState
from models.schemas import StartScrapeRequest
from database.media_db import MediaDatabaseManager
from services.media_extractor import media_extractor

logger = logging.getLogger("web_app")

class ScraperEngine:
    """OOP Service for executing sequential channel scraping and link validation."""

    async def validate_and_forward_links(self, links: Set[str], client: TelegramClient, forward_target: str, state: AppState):
        valid_links = []
        state.validation_total = len(links)
        state.validation_current = 0
        state.urls_valid = 0

        for i, link in enumerate(links):
            if state.status != "validating":
                break

            state.validation_current = i + 1

            try:
                if "+" in link or "joinchat" in link:
                    hash_match = re.search(r'(?:\+|joinchat/)([\w-]+)', link)
                    if hash_match:
                        invite_hash = hash_match.group(1)
                        await client(CheckChatInviteRequest(invite_hash))
                        valid_links.append(link)
                        state.urls_valid += 1
                else:
                    username_match = re.search(r't\.me/([\w_]+)', link)
                    if username_match:
                        username = username_match.group(1)
                        await client.get_entity(username)
                        valid_links.append(link)
                        state.urls_valid += 1
            except (InviteHashExpiredError, InviteHashInvalidError, ValueError):
                logger.info(f"Invalid or expired link skipped: {link}")
            except errors.FloodWaitError as e:
                wait_time = e.seconds + 2
                logger.warning(f"Rate limit hit during validation. Waiting {wait_time}s.")
                state.validation_status_msg = f"Rate Limited! Waiting {wait_time}s..."
                await asyncio.sleep(wait_time)
                state.validation_status_msg = None
            except Exception as e:
                logger.warning(f"Error checking link {link}: {e}")

            await asyncio.sleep(2.5)

            if (i + 1) % 10 == 0:
                logger.info("Batch of 10 links checked. Pausing for 10 seconds...")
                await asyncio.sleep(10)

        if valid_links and state.status == "validating":
            chunk_size = 50
            for i in range(0, len(valid_links), chunk_size):
                chunk = valid_links[i:i + chunk_size]
                msg_text = "🎯 **Valid Telegram Links Extracted:**\n\n" + "\n".join(f"{j+1}. {l}" for j, l in enumerate(chunk, i))
                try:
                    try:
                        await client.send_message(forward_target, msg_text)
                    except Exception as e:
                        logger.warning(f"Failed to forward to target ({e}), falling back to Saved Messages.")
                        await client.send_message("me", msg_text)
                    await asyncio.sleep(2)
                except Exception as e:
                    logger.error(f"Failed to forward links: {e}")

    async def run(self, req: StartScrapeRequest, output_dir: Path, state: AppState):
        state.status = "scraping"
        state.messages_scanned = 0
        state.media_found = 0
        state.videos_found = 0
        state.images_found = 0
        state.urls_found = 0
        state.media_downloaded = 0
        state.media_failed = 0
        state.images_downloaded = 0
        state.error_message = None
        state.collected_links_list = []
        state.pending_media = []

        # Automatically clear media entries before scraper runs so the media tab starts completely fresh
        try:
            db_mgr = MediaDatabaseManager(output_dir / "download_history.db")
            db_mgr.init_db()
            clear_source = "scraper" if getattr(state, "is_watching", False) else "all"
            deleted_count = db_mgr.clear_media(source=clear_source)
            logger.info(f"Auto-cleared {deleted_count} previous media entries ({clear_source}) before starting new scrape.")
        except Exception as e:
            logger.warning(f"Could not auto-clear previous media entries: {e}")
            db_mgr = MediaDatabaseManager(output_dir / "download_history.db")
            db_mgr.init_db()

        start_dt = None
        if req.start_date:
            try:
                start_dt = datetime.strptime(req.start_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            except Exception:
                pass

        end_dt = None
        if req.end_date:
            try:
                end_dt = datetime.strptime(req.end_date, "%Y-%m-%d").replace(hour=23, minute=59, second=59, tzinfo=timezone.utc)
            except Exception:
                pass

        try:
            entities_to_scrape = []
            if req.target.strip().upper() == "ALL":
                state.status_message = "Fetching all channels..."
                async for dialog in state.client.iter_dialogs():
                    if dialog.is_channel or dialog.is_group:
                        entities_to_scrape.append(dialog.entity)
                logger.info(f"Found {len(entities_to_scrape)} channels/groups to scrape.")
                state.status_message = f"Scraping {len(entities_to_scrape)} channels..."
            else:
                raw_targets = [t.strip() for t in req.target.split(",") if t.strip()]
                for raw_t in raw_targets:
                    target_val = raw_t
                    try:
                        target_val = int(target_val)
                    except ValueError:
                        pass
                    try:
                        entity = await state.client.get_entity(target_val)
                        entities_to_scrape.append(entity)
                    except Exception as e:
                        logger.warning(f"Could not resolve target '{raw_t}': {e}")
                if not entities_to_scrape:
                    raise ValueError("No valid channel or group could be resolved from the provided target(s).")

            collected_links = set()
            downloaded_document_ids = set()

            db_mgr = MediaDatabaseManager(output_dir / "download_history.db")
            db_mgr.init_db()

            batch_buffer = []
            for i, entity in enumerate(entities_to_scrape):
                if state.status != "scraping":
                    logger.info("Scraping stopped by user request.")
                    break

                entity_name = getattr(entity, 'title', str(entity.id))
                logger.info(f"Scraping entity {i+1}/{len(entities_to_scrape)}: {entity_name}")

                if len(entities_to_scrape) > 1:
                    state.status_message = f"Scraping {i+1}/{len(entities_to_scrape)}: {entity_name}"

                # Ensure Telegram MTProto client is connected before each entity
                if not await state.ensure_connected(max_retries=3, retry_delay=2.0):
                    logger.error(f"Cannot scrape entity {entity_name}: Telegram client is disconnected and could not reconnect.")
                    continue

                async def process_msg(message) -> bool:
                    nonlocal batch_buffer
                    if not message:
                        return True

                    if start_dt and message.date and message.date < start_dt:
                        return False

                    state.messages_scanned += 1

                    # URL Extraction
                    if req.scrape_urls and message.text:
                        urls = TELEGRAM_LINK_REGEX.findall(message.text)
                        for u in urls:
                            u = re.sub(r'[*\])}.,!?"\'\s]+$', '', u)
                            if re.search(r'bot(?:\?|$)', u, re.IGNORECASE):
                                continue
                            collected_links.add(u)
                        state.urls_found = len(collected_links)

                    # Media Extraction
                    media_type, file_name, resolution, file_size, duration, document_id = media_extractor.extract(message)

                    if not media_type:
                        if message.media:
                            if hasattr(message.media, 'photo') or hasattr(message, 'photo'):
                                media_type = "image"
                                file_name = f"photo_{message.id}.jpg"
                            elif hasattr(message.media, 'document'):
                                media_type = "video"
                                file_name = f"video_{message.id}.mp4"
                            elif message.text and message.text.strip():
                                media_type = "msg"
                                file_name = f"message_{message.id}.txt"
                            else:
                                media_type = "others"
                                file_name = f"doc_{message.id}"
                        elif message.text and message.text.strip():
                            media_type = "msg"
                            file_name = f"message_{message.id}.txt"

                    should_download = False
                    if media_type == "video" and req.scrape_videos:
                        if duration and duration < 5:
                            return True
                        if document_id and document_id in downloaded_document_ids:
                            return True
                        if document_id:
                            downloaded_document_ids.add(document_id)
                        should_download = True
                        state.media_found += 1
                        state.videos_found += 1
                    elif media_type == "image" and req.scrape_images:
                        should_download = True
                        state.media_found += 1
                        state.images_found += 1
                    elif media_type == "msg" and getattr(req, "scrape_messages", True):
                        if message.text and message.text.strip():
                            should_download = True
                            state.media_found += 1
                    elif media_type == "others" and getattr(req, "scrape_others", True):
                        should_download = True
                        state.media_found += 1

                    if should_download:
                        item_entry = {
                            "id": message.id,
                            "chat_id": getattr(entity, 'id', 0),
                            "channel_name": entity_name,
                            "file_name": file_name,
                            "filename": file_name,
                            "resolution": resolution,
                            "size": file_size,
                            "duration": duration,
                            "type": media_type,
                            "text": message.text or "",
                            "date": message.date.isoformat() if message.date else datetime.now(timezone.utc).isoformat(),
                            "source": "scraper",
                            "media_obj": message.media
                        }
                        batch_buffer.append(item_entry)
                        state.pending_media.append(item_entry)
                        if len(state.pending_media) > 300:
                            state.pending_media.pop(0)

                        if len(batch_buffer) >= 200:
                            db_mgr.save_media_batch(batch_buffer)
                            batch_buffer.clear()
                            db_mgr.update_checkpoint(getattr(entity, 'id', 0), entity_name, message.id)

                        if req.mirror_target:
                            try:
                                await state.client.forward_messages(req.mirror_target, message.id, entity)
                                await asyncio.sleep(1)
                            except Exception as e:
                                logger.error(f"Failed to mirror message {message.id}: {e}")

                    return True

                try:
                    async for message in state.client.iter_messages(entity, offset_date=end_dt):
                        if state.status != "scraping":
                            break
                        if not await process_msg(message):
                            logger.info(f"Reached start_date limit for {entity_name}.")
                            break

                    if batch_buffer:
                        db_mgr.save_media_batch(batch_buffer)
                        batch_buffer.clear()
                        db_mgr.update_checkpoint(getattr(entity, 'id', 0), entity_name, getattr(entity, 'id', 0))
                except Exception as e:
                    err_str = str(e).lower()
                    if "disconnected" in err_str or "connection" in err_str:
                        logger.warning(f"Connection lost while scraping {entity_name}: {e}. Reconnecting...")
                        if await state.ensure_connected(max_retries=3, retry_delay=2.0):
                            logger.info(f"Successfully reconnected! Resuming scrape for {entity_name}...")
                            try:
                                async for message in state.client.iter_messages(entity, offset_date=end_dt):
                                    if state.status != "scraping":
                                        break
                                    if not await process_msg(message):
                                        break
                                if batch_buffer:
                                    db_mgr.save_media_batch(batch_buffer)
                                    batch_buffer.clear()
                            except Exception as retry_e:
                                logger.error(f"Retry scraping entity {entity_name} failed: {retry_e}")
                    else:
                        logger.error(f"Error scraping entity {entity_name}: {e}")

                if req.target == "ALL" and state.status == "scraping" and i < len(entities_to_scrape) - 1:
                    await asyncio.sleep(random.uniform(2.0, 5.0))

            state.status = "validating"
            logger.info("Scraping finished. Starting link validation...")

            if req.scrape_urls and collected_links and state.status == "validating":
                state.collected_links_list = list(collected_links)
                logger.info(f"Starting validation of {len(collected_links)} links...")
                await self.validate_and_forward_links(collected_links, state.client, req.forward_target, state)

            state.status = "connected"
            state.current_download_file = ""
            state.current_download_progress = 0

            if req.webhook_url:
                import httpx
                try:
                    summary = {
                        "status": "completed",
                        "media_found": state.media_found,
                        "urls_found": state.urls_found,
                        "urls_valid": state.urls_valid
                    }
                    async with httpx.AsyncClient() as client:
                        await client.post(req.webhook_url, json=summary)
                except Exception as e:
                    logger.error(f"Webhook failed: {e}")

        except Exception as e:
            logger.exception("Scraper task failed with exception")
            state.status = "connected"
            state.error_message = str(e)

scraper_engine = ScraperEngine()
