import logging
from pathlib import Path
from fastapi import APIRouter, HTTPException, Depends

from core.state import AppState, get_current_state, get_safe_output_dir, task_queue
from models.schemas import WatchRequest
from services.watcher_service import daemon_watcher
from telegrab import DownloadTracker, download_video, download_image

logger = logging.getLogger("web_app")
router = APIRouter(prefix="/api/watch", tags=["Watcher"])

@router.post("/start")
async def api_watch_start(req: WatchRequest, state: AppState = Depends(get_current_state)):
    return await daemon_watcher.start(req, state)

@router.post("/stop")
async def api_watch_stop(state: AppState = Depends(get_current_state)):
    return daemon_watcher.stop(state)

@router.post("/download/{message_id}")
async def api_watch_download(message_id: int, state: AppState = Depends(get_current_state)):
    item = next((m for m in state.pending_media if m["id"] == message_id), None)
    if not item:
        raise HTTPException(status_code=404, detail="Media not found in pending cache.")

    req = item.get("req")
    output_dir_str = req.output_dir if req else getattr(state, "current_output_dir", "./downloads")

    try:
        safe_output_dir = get_safe_output_dir(output_dir_str, state.phone)
        safe_output_dir.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    db_path = safe_output_dir / "download_history.db"
    tracker = DownloadTracker(db_path)

    async def _daemon_download_task(client, message, out_dir, trk, forward_target=None):
        try:
            chat_id = getattr(message, 'chat_id', 0)
            if hasattr(message.media, 'document'):
                await download_video(client, message, out_dir, trk, chat_id)
            elif hasattr(message.media, 'photo'):
                await download_image(client, message, out_dir, trk, chat_id)

            if forward_target:
                await client.forward_messages(forward_target, message)
        except Exception as e:
            logger.error(f"Daemon download failed: {e}")

    forward_target = req.forward_target if req else None
    msg_obj = item.get("message") or item.get("media_obj")
    await task_queue.put((_daemon_download_task, (state.client, msg_obj, safe_output_dir, tracker, forward_target), {}))
    return {"status": "success", "message": "Download queued."}
