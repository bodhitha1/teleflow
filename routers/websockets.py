import os
import asyncio
import logging
from pathlib import Path
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
import jwt

from config import JWT_SECRET
from core.state import session_manager, telemetry_manager
from database.media_db import get_db_stats

logger = logging.getLogger("web_app")
router = APIRouter(prefix="/api", tags=["WebSockets"])

@router.websocket("/watch/ws")
async def api_watch_ws(websocket: WebSocket):
    await websocket.accept()
    jwt_secret = os.getenv("JWT_SECRET") or JWT_SECRET
    token = websocket.cookies.get("teleflow_jwt") or websocket.cookies.get("telegrab_jwt") or websocket.query_params.get("token")
    if not token or not jwt_secret:
        await websocket.close(code=1008)
        return
    try:
        payload = jwt.decode(token, jwt_secret, algorithms=["HS256"])
        phone = payload.get("phone")
        state = session_manager.get(phone)
        if not state:
            await websocket.close(code=1008)
            return

        state.watch_websockets.append(websocket)
        try:
            while True:
                await websocket.receive_text()
        except (WebSocketDisconnect, ConnectionResetError, OSError):
            pass
        finally:
            if websocket in state.watch_websockets:
                state.watch_websockets.remove(websocket)
            try:
                await websocket.close()
            except Exception:
                pass
    except Exception:
        try:
            await websocket.close(code=1008)
        except Exception:
            pass

@router.websocket("/logs/ws")
async def websocket_logs(websocket: WebSocket):
    await websocket.accept()
    log_files = [p for p in [Path("web_app.log"), Path("teleflow.log"), Path("telegrab.log")] if p.exists() or p.name in ("web_app.log", "teleflow.log")]
    last_sizes = [0] * len(log_files)

    for i, log_file in enumerate(log_files):
        if log_file.exists():
            size = log_file.stat().st_size
            last_sizes[i] = size
            with open(log_file, "r", encoding="utf-8", errors="replace") as f:
                if size > 2048:
                    f.seek(size - 2048)
                    f.readline()
                await websocket.send_text(f.read())

    try:
        while True:
            for i, log_file in enumerate(log_files):
                if log_file.exists():
                    current_size = log_file.stat().st_size
                    if current_size > last_sizes[i]:
                        with open(log_file, "r", encoding="utf-8", errors="replace") as f:
                            f.seek(last_sizes[i])
                            new_data = f.read()
                            if new_data:
                                await websocket.send_text(new_data)
                        last_sizes[i] = current_size
            await asyncio.sleep(0.5)
    except (WebSocketDisconnect, ConnectionResetError, OSError, RuntimeError, asyncio.CancelledError):
        pass
    except Exception:
        pass

@router.websocket("/status/ws")
async def api_status_ws(websocket: WebSocket, output: str = "./downloads"):
    await websocket.accept()
    jwt_secret = os.getenv("JWT_SECRET") or JWT_SECRET
    token = websocket.cookies.get("teleflow_jwt") or websocket.cookies.get("telegrab_jwt") or websocket.query_params.get("token")

    phone = "anonymous"
    if token and jwt_secret:
        try:
            payload = jwt.decode(token, jwt_secret, algorithms=["HS256"])
            phone = payload.get("phone", "anonymous")
        except Exception:
            phone = "anonymous"

    if phone != "anonymous":
        state = session_manager.get_or_create(phone)
        state.current_output_dir = output

    await telemetry_manager.connect(websocket, phone)

    # Initial status
    if phone != "anonymous":
        st = session_manager.get(phone)
        if st:
            try:
                db_stats = get_db_stats(output, st.phone)
                await websocket.send_json({
                    "status": st.status,
                    "error_message": st.error_message,
                    "scanned": st.messages_scanned,
                    "found": st.media_found + st.urls_found,
                    "videos_found": st.videos_found,
                    "images_found": st.images_found,
                    "downloaded": st.media_downloaded + st.images_downloaded,
                    "failed": st.media_failed,
                    "urls_valid": st.urls_valid,
                    "validation_current": st.validation_current,
                    "validation_total": st.validation_total,
                    "current_file": st.current_download_file,
                    "current_progress": st.current_download_progress,
                    "validation_status_msg": st.validation_status_msg,
                    "is_watching": getattr(st, "is_watching", False),
                    "db_total": db_stats["total"],
                    "db_downloaded": db_stats["downloaded"],
                    "db_failed": db_stats["failed"]
                })
            except Exception:
                pass
    else:
        try:
            await websocket.send_json({
                "status": "idle",
                "scanned": 0,
                "found": 0,
                "videos_found": 0,
                "images_found": 0,
                "downloaded": 0,
                "failed": 0,
                "urls_valid": 0,
                "is_watching": False,
                "db_total": 0,
                "db_downloaded": 0,
                "db_failed": 0
            })
        except Exception:
            pass

    try:
        while True:
            await websocket.receive_text()
    except (WebSocketDisconnect, ConnectionResetError, OSError, asyncio.CancelledError):
        pass
    except Exception:
        pass
    finally:
        telemetry_manager.disconnect(websocket, phone)
        try:
            await websocket.close()
        except Exception:
            pass

async def telemetry_broadcast_loop():
    while True:
        try:
            for phone, websockets in list(telemetry_manager.active_connections.items()):
                if not websockets:
                    continue
                state = session_manager.get(phone)
                if not state:
                    continue

                output_dir = getattr(state, "current_output_dir", "./downloads")
                db_stats = get_db_stats(output_dir, state.phone)
                current_state = {
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

                state_str = str(current_state)
                state_hash = hash(state_str)
                counter = telemetry_manager.heartbeat_counters.get(phone, 0)

                if state_hash != telemetry_manager.last_hashes.get(phone) or counter >= 30:
                    await telemetry_manager.broadcast(phone, current_state)
                    telemetry_manager.last_hashes[phone] = state_hash
                    telemetry_manager.heartbeat_counters[phone] = 0
                else:
                    telemetry_manager.heartbeat_counters[phone] = counter + 1
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Telemetry broadcast loop error: {e}")
        try:
            await asyncio.sleep(1)
        except asyncio.CancelledError:
            break
