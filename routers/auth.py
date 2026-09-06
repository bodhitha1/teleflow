import os
import re
import asyncio
import logging
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Optional
from fastapi import APIRouter, Request, Response, HTTPException, Depends
from telethon import TelegramClient, errors
from telethon.sessions import StringSession
from cryptography.fernet import Fernet
import jwt

from config import API_ID, API_HASH, JWT_SECRET
from core.state import AppState, session_manager, get_current_state
from core.security import limiter, derive_fernet_key
from models.schemas import ConnectRequest, VerifyRequest, ResetSessionRequest

logger = logging.getLogger("web_app")
router = APIRouter(prefix="/api", tags=["Auth"])

@router.post("/connect")
@limiter.limit("15/minute")
async def api_connect(req: ConnectRequest, request: Request, response: Response):
    phone = re.sub(r'[\s\-\(\)]', '', req.phone.strip())
    if phone.startswith('0') and len(phone) == 10:
        phone = '+94' + phone[1:]
    elif not phone.startswith('+'):
        phone = '+' + phone

    if not re.match(r'^\+[1-9]\d{6,14}$', phone):
        raise HTTPException(status_code=400, detail="Invalid phone number format. Please enter a valid number (e.g. +94771234567 or 0771234567).")

    allowed_env = os.getenv("ALLOWED_PHONE_NUMBERS", "")
    allowed_numbers = [p.strip() for p in allowed_env.split(",") if p.strip()]
    if allowed_numbers and phone not in allowed_numbers:
        raise HTTPException(status_code=403, detail="This phone number is not authorized on this server.")

    req.phone = phone
    state = session_manager.get_or_create(phone)

    if state.status == "scraping":
        raise HTTPException(status_code=400, detail="Cannot connect while scraping is running.")

    if state.client:
        try:
            await asyncio.wait_for(state.client.disconnect(), timeout=3.0)
        except Exception:
            pass
        state.client = None

    env_api_id = os.getenv("TG_API_ID", "").strip()
    env_api_hash = os.getenv("TG_API_HASH", "").strip()

    state.api_id = int(env_api_id) if env_api_id else (req.api_id or API_ID)
    state.api_hash = env_api_hash if env_api_hash else (req.api_hash.strip() if req.api_hash else API_HASH)

    if not state.api_id or not state.api_hash:
        raise HTTPException(status_code=400, detail="API ID and API Hash must be configured in .env or provided.")

    state.status = "authenticating"
    state.error_message = None

    session_path = Path(f"sessions/teleflow_{state.phone}.session.enc")
    if not session_path.exists():
        legacy_path = Path(f"sessions/telegrab_{state.phone}.session.enc")
        if legacy_path.exists():
            session_path = legacy_path
    session_path.parent.mkdir(exist_ok=True)

    state.fernet_key = derive_fernet_key(req.master_password)
    fernet = Fernet(state.fernet_key)

    session_string = ""
    if session_path.exists():
        try:
            enc_data = session_path.read_bytes()
            session_string = fernet.decrypt(enc_data).decode('utf-8')
        except Exception:
            state.status = "idle"
            raise HTTPException(
                status_code=401,
                detail="Incorrect Encryption Password for the existing session file. If you forgot your password, please click 'Reset Session' below to start fresh."
            )

    proxy = None
    if req.proxy_type and req.proxy_addr and req.proxy_port:
        try:
            import socks
            proxy_map = {"SOCKS5": socks.SOCKS5, "SOCKS4": socks.SOCKS4, "HTTP": socks.HTTP}
            if req.proxy_type in proxy_map:
                proxy = (proxy_map[req.proxy_type], req.proxy_addr, req.proxy_port)
        except ImportError:
            logger.warning("pysocks not installed, proxy will be ignored")

    try:
        logger.info(f"Initializing TelegramClient for {state.phone}...")
        state.client = TelegramClient(StringSession(session_string), state.api_id, state.api_hash, proxy=proxy)

        try:
            await asyncio.wait_for(state.client.connect(), timeout=20.0)
        except (errors.AuthKeyUnregisteredError, errors.SecurityError) as auth_err:
            logger.warning(f"Saved session was revoked or invalid for {state.phone}: {auth_err}. Starting fresh session.")
            try:
                await state.client.disconnect()
            except Exception:
                pass
            state.client = TelegramClient(StringSession(""), state.api_id, state.api_hash, proxy=proxy)
            await asyncio.wait_for(state.client.connect(), timeout=20.0)
        except asyncio.TimeoutError:
            state.status = "idle"
            raise HTTPException(status_code=504, detail="Telegram connection timed out. Telegram servers may be slow or unreachable. Please retry.")

        is_auth = False
        try:
            is_auth = await asyncio.wait_for(state.client.is_user_authorized(), timeout=10.0)
        except Exception as auth_check_err:
            logger.warning(f"is_user_authorized check failed: {auth_check_err}")
            is_auth = False

        if is_auth:
            state.status = "connected"
            me = await asyncio.wait_for(state.client.get_me(), timeout=10.0)

            session_str = state.client.session.save()
            enc_data = fernet.encrypt(session_str.encode('utf-8'))
            session_path.write_bytes(enc_data)

            jwt_secret = os.getenv("JWT_SECRET") or JWT_SECRET
            if not jwt_secret:
                raise HTTPException(status_code=500, detail="JWT_SECRET is not configured")

            payload = {
                "phone": state.phone,
                "exp": datetime.now(timezone.utc) + timedelta(days=30)
            }
            token = jwt.encode(payload, jwt_secret, algorithm="HS256")
            response.set_cookie(key="teleflow_jwt", value=token, httponly=True, max_age=30*24*60*60, samesite="lax")
            response.set_cookie(key="telegrab_jwt", value=token, httponly=True, max_age=30*24*60*60, samesite="lax")

            return {"status": "connected", "message": f"Already authorized as {me.first_name}.", "token": token}

        logger.info(f"Requesting Telegram verification code for {state.phone}...")
        try:
            res = await asyncio.wait_for(state.client.send_code_request(state.phone), timeout=25.0)
            state.phone_code_hash = res.phone_code_hash
            logger.info(f"Telegram code sent successfully to {state.phone}.")
            return {"status": "needs_code", "message": "Verification code has been sent to your Telegram account."}
        except asyncio.TimeoutError:
            state.status = "idle"
            raise HTTPException(status_code=504, detail="Timeout requesting verification code from Telegram. Please check your connection and retry.")

    except HTTPException:
        state.status = "idle"
        raise
    except errors.PhoneNumberInvalidError:
        state.status = "idle"
        raise HTTPException(status_code=400, detail="The phone number is invalid. Please double check the country code and number.")
    except errors.FloodWaitError as fwe:
        state.status = "idle"
        raise HTTPException(status_code=429, detail=f"Telegram flood wait triggered. Please wait {fwe.seconds} seconds before trying again.")
    except Exception as e:
        logger.error(f"Error connecting Telegram client: {e}", exc_info=True)
        state.status = "idle"
        state.error_message = str(e)
        raise HTTPException(status_code=400, detail=f"Telegram connection error: {str(e)}")

@router.post("/verify")
@limiter.limit("15/minute")
async def api_verify(req: VerifyRequest, request: Request, response: Response):
    phone = re.sub(r'[\s\-\(\)]', '', req.phone.strip())
    if phone.startswith('0') and len(phone) == 10:
        phone = '+94' + phone[1:]
    elif not phone.startswith('+'):
        phone = '+' + phone

    state = session_manager.get(phone) or session_manager.get(req.phone)
    if not state or state.status != "authenticating" or not state.client:
        raise HTTPException(status_code=400, detail="No active authentication process for this phone number. Please click Connect first.")

    clean_code = re.sub(r'[\s\-]', '', req.code.strip()) if req.code else ""

    try:
        if req.password:
            try:
                await asyncio.wait_for(state.client.sign_in(password=req.password), timeout=20.0)
            except Exception as e:
                logger.info(f"Direct password sign-in attempt: {e}, falling back to code verification")
                if clean_code:
                    try:
                        await asyncio.wait_for(state.client.sign_in(
                            phone=state.phone,
                            code=clean_code,
                            phone_code_hash=state.phone_code_hash
                        ), timeout=20.0)
                    except errors.SessionPasswordNeededError:
                        await asyncio.wait_for(state.client.sign_in(password=req.password), timeout=20.0)
                else:
                    raise
        else:
            try:
                await asyncio.wait_for(state.client.sign_in(
                    phone=state.phone,
                    code=clean_code,
                    phone_code_hash=state.phone_code_hash
                ), timeout=20.0)
            except errors.SessionPasswordNeededError:
                return {"status": "needs_password", "message": "Two-factor authentication (2FA) password required."}

        state.status = "connected"
        me = await asyncio.wait_for(state.client.get_me(), timeout=10.0)

        session_str = state.client.session.save()
        fernet = Fernet(state.fernet_key)
        enc_data = fernet.encrypt(session_str.encode('utf-8'))
        session_path = Path(f"sessions/teleflow_{state.phone}.session.enc")
        session_path.parent.mkdir(exist_ok=True)
        session_path.write_bytes(enc_data)

        jwt_secret = os.getenv("JWT_SECRET") or JWT_SECRET
        if not jwt_secret:
            raise HTTPException(status_code=500, detail="JWT_SECRET is not configured")

        payload = {
            "phone": state.phone,
            "exp": datetime.now(timezone.utc) + timedelta(days=30)
        }
        token = jwt.encode(payload, jwt_secret, algorithm="HS256")

        response.set_cookie(key="teleflow_jwt", value=token, httponly=True, max_age=30*24*60*60, samesite="lax")
        response.set_cookie(key="telegrab_jwt", value=token, httponly=True, max_age=30*24*60*60, samesite="lax")
        return {"status": "connected", "message": f"Successfully logged in as {me.first_name}.", "token": token}

    except HTTPException:
        raise
    except errors.PhoneCodeInvalidError:
        raise HTTPException(status_code=400, detail="Invalid verification code. Please check the code sent to Telegram.")
    except errors.PhoneCodeExpiredError:
        raise HTTPException(status_code=400, detail="Verification code has expired. Please click Connect to request a new code.")
    except errors.PasswordHashInvalidError:
        raise HTTPException(status_code=400, detail="Invalid 2FA Two-Step Verification password.")
    except Exception as e:
        state.error_message = str(e)
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/disconnect")
async def api_disconnect(state: AppState = Depends(get_current_state)):
    if state.status == "scraping":
        state.status = "connected"
        await asyncio.sleep(1)

    if state.client:
        try:
            await state.client.disconnect()
        except Exception:
            pass
        state.client = None

    state.status = "idle"
    return {"status": "idle", "message": "Disconnected and session closed."}

@router.post("/logout")
async def api_logout(response: Response, state: AppState = Depends(get_current_state)):
    try:
        if state.client:
            await state.client.log_out()
            await state.client.disconnect()
            state.client = None
    except Exception as e:
        logger.error(f"Error during logout: {e}")

    if state.phone:
        for p in [Path(f"sessions/teleflow_{state.phone}.session.enc"), Path(f"sessions/telegrab_{state.phone}.session.enc")]:
            if p.exists():
                try:
                    p.unlink()
                except Exception:
                    pass

    response.delete_cookie("teleflow_jwt")
    response.delete_cookie("telegrab_jwt")

    state.phone = None
    state.phone_code_hash = None
    state.status = "idle"
    state.error_message = None
    state.pending_media = []
    state.collected_links_list = []

    return {"status": "success", "message": "Logged out successfully."}

@router.post("/session/reset")
async def api_session_reset(req: ResetSessionRequest):
    phone = re.sub(r'[\s\-\(\)]', '', req.phone.strip())
    if phone.startswith('0') and len(phone) == 10:
        phone = '+94' + phone[1:]
    elif not phone.startswith('+'):
        phone = '+' + phone

    st = session_manager.get(phone)
    if st:
        if st.client:
            try:
                await asyncio.wait_for(st.client.disconnect(), timeout=3.0)
            except Exception:
                pass
            st.client = None
        st.status = "idle"
        session_manager.remove(phone)

    deleted = []
    for prefix in ["teleflow_", "telegrab_"]:
        for ext in [".session.enc", ".session", ".session-journal"]:
            p = Path(f"sessions/{prefix}{phone}{ext}")
            if p.exists():
                try:
                    p.unlink()
                    deleted.append(p.name)
                except Exception as e:
                    logger.warning(f"Could not delete {p}: {e}")

    logger.info(f"Reset session for {phone}. Removed files: {deleted}")
    return {"status": "success", "message": f"Saved session for {phone} has been reset. You can now connect fresh."}

@router.get("/dialogs")
async def api_dialogs(state: AppState = Depends(get_current_state)):
    if not state.client or not await state.client.is_user_authorized():
        raise HTTPException(status_code=400, detail="Telegram client is not authorized. Log in first.")

    try:
        dialogs = []
        async for dialog in state.client.iter_dialogs():
            if dialog.is_channel or dialog.is_group:
                dialogs.append({
                    "id": str(dialog.id),
                    "name": dialog.title or "Unknown",
                    "type": "channel" if dialog.is_channel else "group"
                })
        return {"status": "success", "dialogs": dialogs}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/avatar/{dialog_id}")
async def api_avatar(dialog_id: int, state: AppState = Depends(get_current_state)):
    if not state.client or not await state.client.is_user_authorized():
        raise HTTPException(status_code=401, detail="Telegram client is not authorized. Log in first.")

    try:
        file_bytes = await state.client.download_profile_photo(dialog_id, file=bytes)
        if file_bytes:
            return Response(content=file_bytes, media_type="image/jpeg")
        return Response(status_code=404)
    except Exception:
        return Response(status_code=404)
