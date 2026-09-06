from typing import Optional, Tuple
from telethon.tl.types import (
    MessageMediaDocument,
    DocumentAttributeVideo,
    DocumentAttributeFilename,
    MessageMediaPhoto,
    MessageMediaWebPage
)

from core.state import secure_filename

class MediaExtractor:
    """OOP Service for identifying media attributes and extracting metadata."""

    def extract(self, message) -> Tuple[Optional[str], Optional[str], Optional[str], int, int, Optional[int]]:
        """
        Analyzes a Telegram message and extracts:
        (media_type, file_name, resolution, file_size, duration, document_id)
        Supported types: 'video', 'image', 'msg', 'others'
        """
        if not message:
            return None, None, None, 0, 0, None

        # 1. Photos (Direct or attached)
        if hasattr(message.media, 'photo') and message.media.photo:
            file_name = f"image_{message.id}.jpg"
            return "image", file_name, "Unknown", 0, 0, getattr(message.media.photo, 'id', message.id)
        if hasattr(message, 'photo') and message.photo:
            file_name = f"image_{message.id}.jpg"
            return "image", file_name, "Unknown", 0, 0, getattr(message.photo, 'id', message.id)

        # 2. WebPage media preview or MessageMediaDocument
        document = None
        if isinstance(message.media, MessageMediaDocument):
            document = message.media.document
        elif hasattr(message.media, 'webpage') and message.media.webpage:
            wp = message.media.webpage
            if getattr(wp, 'document', None):
                document = wp.document
            elif getattr(wp, 'photo', None):
                return "image", f"image_{message.id}.jpg", "Unknown", 0, 0, getattr(wp.photo, 'id', message.id)

        if document:
            media_type = None
            resolution = "Unknown"
            file_name = f"media_{message.id}"
            file_size = getattr(document, 'size', 0) or 0
            duration = 0
            document_id = getattr(document, 'id', message.id)

            for attr in getattr(document, 'attributes', []):
                if isinstance(attr, DocumentAttributeVideo):
                    media_type = "video"
                    duration = attr.duration or 0
                    if attr.w and attr.h:
                        resolution = f"{attr.w}x{attr.h}"
                elif isinstance(attr, DocumentAttributeFilename):
                    file_name = attr.file_name
                elif hasattr(attr, 'voice') and attr.voice:
                    media_type = "others"
                    if not file_name.endswith(('.ogg', '.opus', '.mp3')):
                        file_name += ".ogg"

            if getattr(document, 'mime_type', None):
                if document.mime_type.startswith("video/"):
                    media_type = "video"
                elif document.mime_type.startswith("image/"):
                    media_type = "image"
                elif document.mime_type.startswith("audio/"):
                    media_type = "others"

            if not media_type:
                media_type = "others"

            # Default extension if missing
            if media_type == "video" and "." not in file_name:
                file_name += ".mp4"
            elif media_type == "image" and "." not in file_name:
                file_name += ".jpg"
            elif media_type == "others" and "." not in file_name:
                file_name += ".bin"

            file_name = secure_filename(file_name)
            # Never discard large files (>500MB) during detection!
            return media_type, file_name, resolution, file_size, duration, document_id

        # 3. Fallback for text messages or link cards
        if getattr(message, 'text', None) and message.text.strip():
            # If there is text and no heavy media, consider as text message
            if not message.media or isinstance(message.media, MessageMediaWebPage):
                return "msg", f"message_{message.id}.txt", "Text", 0, 0, None

        return None, None, None, 0, 0, None

media_extractor = MediaExtractor()
