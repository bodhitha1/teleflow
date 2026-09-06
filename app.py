import sys
import asyncio
import logging
from logging.handlers import RotatingFileHandler
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, Response
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from slowapi.errors import RateLimitExceeded
from slowapi import _rate_limit_exceeded_handler

# Ensure proper utf-8 console output on Windows
if sys.platform == "win32":
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        if hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# Configure Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        RotatingFileHandler("web_app.log", maxBytes=2*1024*1024, backupCount=1, encoding="utf-8"),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("web_app")

# Activate 170x faster native OpenSSL AES-NI hardware encryption for Telethon
from core.crypto_patch import apply_telethon_crypto_patch
apply_telethon_crypto_patch()

from config import STATIC_DIR
from core.security import limiter, SecurityHeadersMiddleware, JwtAuthMiddleware
from core.state import worker_loop
from services.cleaner_service import cleaner_service
from routers.websockets import telemetry_broadcast_loop
from routers.payments import order_repo

# Import Modular Routers
from routers.auth import router as auth_router
from routers.scraper import router as scraper_router
from routers.watcher import router as watcher_router
from routers.media import router as media_router
from routers.websockets import router as websockets_router
from routers.payments import router as payments_router

@asynccontextmanager
async def lifespan(app: FastAPI):
    loop = asyncio.get_running_loop()
    def _loop_exception_handler(current_loop, context):
        exc = context.get("exception")
        if isinstance(exc, (ConnectionResetError, ConnectionAbortedError)):
            return
        msg = str(context.get("message", ""))
        if "WinError 10054" in msg or (exc and "WinError 10054" in str(exc)):
            return
        current_loop.default_exception_handler(context)
    loop.set_exception_handler(_loop_exception_handler)

    await order_repo.init_db()
    worker_task = asyncio.create_task(worker_loop())
    telemetry_task = asyncio.create_task(telemetry_broadcast_loop())
    cleaner_task = asyncio.create_task(cleaner_service.start_background_loop())
    logger.info("TeleFlow Application & Daemons successfully started.")

    yield

    worker_task.cancel()
    telemetry_task.cancel()
    cleaner_task.cancel()
    logger.info("TeleFlow Application shutdown complete.")

app = FastAPI(title="TeleFlow Suite", lifespan=lifespan)

# Limiter & Handlers
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled exception: {exc}")
    return Response("Internal Server Error", status_code=500)

# Middlewares
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(JwtAuthMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include Routers
app.include_router(auth_router)
app.include_router(scraper_router)
app.include_router(watcher_router)
app.include_router(media_router)
app.include_router(websockets_router)
app.include_router(payments_router)

# Root route
@app.get("/", response_class=HTMLResponse)
async def serve_index():
    index_file = STATIC_DIR / "index.html"
    if index_file.exists():
        return FileResponse(
            index_file,
            headers={
                "Cache-Control": "no-cache, no-store, must-revalidate",
                "Pragma": "no-cache",
                "Expires": "0"
            }
        )
    return "<h3>Web Interface Loading... Please wait and reload.</h3>"

# Mount Static Files
app.mount("/", StaticFiles(directory=str(STATIC_DIR)), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=False)

