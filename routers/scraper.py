import logging
from pathlib import Path
from fastapi import APIRouter, HTTPException, Depends

from core.state import AppState, get_current_state, get_safe_output_dir, task_queue
from database.media_db import get_db_stats
from models.schemas import StartScrapeRequest
from services.scraper_service import scraper_engine

logger = logging.getLogger("web_app")
router = APIRouter(prefix="/api", tags=["Scraper"])

@router.post("/start")
async def api_start(req: StartScrapeRequest, state: AppState = Depends(get_current_state)):
    if not state.client or not await state.client.is_user_authorized():
        raise HTTPException(status_code=400, detail="Telegram client is not authorized. Log in first.")
    if state.status == "scraping":
        raise HTTPException(status_code=400, detail="Scraper is already running.")

    try:
        output_dir = get_safe_output_dir(req.output_dir, state.phone)
        output_dir.mkdir(parents=True, exist_ok=True)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    state.current_output_dir = str(output_dir)
    task_queue.put_nowait((scraper_engine.run, (req, output_dir, state), {}))
    return {"status": "scraping", "message": "Scraper task started in the background."}

@router.post("/stop")
async def api_stop(state: AppState = Depends(get_current_state)):
    state.status = "idle"
    return {"status": "success", "message": "Scraping stopped"}

@router.get("/status")
async def api_status(state: AppState = Depends(get_current_state)):
    output_dir = getattr(state, "current_output_dir", "./downloads")
    db_stats = get_db_stats(output_dir, state.phone)
    return {
        "status": state.status,
        "error_message": state.error_message,
        "scanned": state.messages_scanned,
        "found": state.media_found + state.urls_found,
        "videos_found": state.videos_found,
        "images_found": state.images_found,
        "downloaded": state.media_downloaded + state.images_downloaded,
        "failed": state.media_failed,
        "urls_valid": state.urls_valid,
        "validation_current": state.validation_current,
        "validation_total": state.validation_total,
        "current_file": state.current_download_file,
        "current_progress": state.current_download_progress,
        "validation_status_msg": state.validation_status_msg,
        "is_watching": getattr(state, "is_watching", False),
        "db_total": db_stats["total"],
        "db_downloaded": db_stats["downloaded"],
        "db_failed": db_stats["failed"]
    }

@router.get("/links")
async def api_links(state: AppState = Depends(get_current_state)):
    return {"status": "success", "links": state.collected_links_list or []}
