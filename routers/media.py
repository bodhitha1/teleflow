import logging
from pathlib import Path
from typing import Optional
from fastapi import APIRouter, Request, Depends, HTTPException

from core.state import AppState, get_current_state, get_safe_output_dir, task_queue
from models.schemas import ClearMediaRequest, DownloadSelectedRequest
from database.media_db import get_media_db
from services.media_service import thumbnail_service, stream_service, download_selected_task
from services.cleaner_service import cleaner_service

logger = logging.getLogger("web_app")
router = APIRouter(prefix="/api", tags=["Media"])

@router.get("/media")
async def api_media(
    category: str = "all",
    source: str = "all",
    channel: Optional[str] = None,
    search: Optional[str] = None,
    sort: str = "newest",
    limit: int = 25,
    offset: int = 0,
    state: AppState = Depends(get_current_state)
):
    limit = min(max(1, limit), 100)
    output_dir = getattr(state, "current_output_dir", "./downloads")
    db = get_media_db(state.phone, output_dir)
    in_memory = list(state.pending_media) if hasattr(state, "pending_media") and state.pending_media else None
    return db.query_media(
        in_memory_items=in_memory,
        category=category,
        source=source,
        channel=channel,
        search=search,
        sort=sort,
        limit=limit,
        offset=offset
    )

@router.get("/media/summary")
async def api_media_summary(source: str = "all", state: AppState = Depends(get_current_state)):
    output_dir = getattr(state, "current_output_dir", "./downloads")
    db = get_media_db(state.phone, output_dir)
    in_memory = list(state.pending_media) if hasattr(state, "pending_media") and state.pending_media else None
    return db.get_summary(in_memory_items=in_memory, source=source)

@router.post("/media/clear")
async def api_clear_media(
    req: ClearMediaRequest,
    state: AppState = Depends(get_current_state)
):
    output_dir = getattr(state, "current_output_dir", "./downloads")
    db = get_media_db(state.phone, output_dir)
    deleted_count = db.clear_media(
        source=req.source,
        category=req.category,
        channel=req.channel,
        ids=req.ids
    )

    # Clean from in-memory pending_media
    if hasattr(state, "pending_media") and state.pending_media:
        if req.ids:
            id_set = set(req.ids)
            state.pending_media = [m for m in state.pending_media if m.get("id") not in id_set]
        else:
            def should_keep(m):
                if req.source and req.source != "all" and (m.get("source") or "daemon").lower() == req.source.lower():
                    return False
                if req.category and req.category != "all" and (m.get("type") or "others").lower() == req.category.lower():
                    return False
                if req.channel and req.channel != "all" and m.get("channel_name") == req.channel:
                    return False
                if (not req.source or req.source == "all") and (not req.category or req.category == "all") and (not req.channel or req.channel == "all"):
                    return False
                return True
            state.pending_media = [m for m in state.pending_media if should_keep(m)]

    logger.info(f"Cleared {deleted_count} detected media entries for {state.phone}.")
    return {
        "status": "success",
        "message": f"Successfully cleared {deleted_count} media items.",
        "deleted_count": deleted_count
    }

@router.get("/thumbnail/{message_id}")
async def get_thumbnail(message_id: int, chat_id: Optional[int] = None, state: AppState = Depends(get_current_state)):
    return await thumbnail_service.get_thumbnail(message_id, state, chat_id=chat_id)

@router.get("/stream/{message_id}")
async def stream_media(message_id: int, request: Request, chat_id: Optional[int] = None, download: bool = False, state: AppState = Depends(get_current_state)):
    return await stream_service.stream(message_id, request, state, chat_id=chat_id, download=download)

@router.post("/download_selected")
async def api_download_selected(req: DownloadSelectedRequest, state: AppState = Depends(get_current_state)):
    if state.status == "scraping":
        raise HTTPException(status_code=400, detail="Scraper is currently active")

    task_queue.put_nowait((download_selected_task, (req, state), {}))
    return {"status": "success", "message": "Manual downloading started"}

@router.post("/system/clean_cache")
async def api_clean_cache(force: bool = False, state: AppState = Depends(get_current_state)):
    output_dir = getattr(state, "current_output_dir", "./downloads")
    try:
        safe_dir = get_safe_output_dir(output_dir, state.phone)
    except Exception:
        safe_dir = Path("./downloads") / state.phone

    max_age = 0 if force else 1800
    res = cleaner_service.cleanup_junk_and_cache(safe_dir, max_age_seconds=max_age)
    return {
        "status": "success",
        "message": f"Cleaned {res['files_deleted']} temporary/junk files ({res['human_freed']} freed).",
        "stats": res
    }
