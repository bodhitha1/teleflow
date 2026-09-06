import os
import base64
import jwt
from datetime import datetime, timezone, timedelta
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from slowapi import Limiter
from slowapi.util import get_remote_address
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from config import JWT_SECRET

limiter = Limiter(key_func=get_remote_address)

def derive_fernet_key(password: str, salt: bytes = b'telegrab_salt') -> bytes:
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=100000,
    )
    return base64.urlsafe_b64encode(kdf.derive(password.encode()))

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        csp_directives = [
            "default-src 'self' 'unsafe-inline' 'unsafe-eval' https://fonts.googleapis.com https://fonts.gstatic.com https://unpkg.com https://cdn.jsdelivr.net",
            "script-src 'self' 'unsafe-inline' 'unsafe-eval' https://unpkg.com https://cdn.jsdelivr.net",
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://fonts.gstatic.com https://unpkg.com https://cdn.jsdelivr.net",
            "font-src 'self' data: https://fonts.gstatic.com https://unpkg.com https://cdn.jsdelivr.net",
            "img-src 'self' data: blob: https:",
            "media-src 'self' blob: data:",
            "connect-src 'self' ws: wss: https://fonts.googleapis.com https://fonts.gstatic.com https://unpkg.com https://cdn.jsdelivr.net"
        ]
        response.headers["Content-Security-Policy"] = "; ".join(csp_directives) + ";"
        
        # Ensure latest frontend scripts, service worker, and HTML are never served stale
        if request.url.path in ["/", "/index.html", "/app.js", "/style.css", "/sw.js", "/links.html", "/media.html"]:
            response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
            
        return response

class JwtAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        unprotected_paths = [
            "/api/connect", "/api/verify", "/api/session/reset",
            "/", "/index.html", "/media.html", "/store.html", "/links.html", 
            "/app.js", "/style.css", "/manifest.json", "/sw.js", "/favicon.ico"
        ]
        
        if request.url.path in unprotected_paths or request.url.path.startswith("/icons/"):
            return await call_next(request)
            
        secret = os.getenv("JWT_SECRET") or JWT_SECRET
        if not secret:
            return Response("JWT_SECRET not configured on server", status_code=500)
            
        token = request.cookies.get("teleflow_jwt") or request.cookies.get("telegrab_jwt")
        if not token:
            auth_header = request.headers.get("Authorization")
            if auth_header and auth_header.startswith("Bearer "):
                token = auth_header[7:]
                
        if not token:
            return Response("Unauthorized", status_code=401)
            
        try:
            payload = jwt.decode(token, secret, algorithms=["HS256"])
            request.state.user_phone = payload.get("phone")
        except jwt.ExpiredSignatureError:
            return Response("Token expired", status_code=401)
        except jwt.InvalidTokenError:
            return Response("Invalid token", status_code=401)
            
        return await call_next(request)
