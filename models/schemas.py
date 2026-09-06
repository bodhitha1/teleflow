from typing import Optional, List
from pydantic import BaseModel

class ConnectRequest(BaseModel):
    api_id: Optional[int] = None
    api_hash: Optional[str] = None
    phone: str
    master_password: str
    proxy_type: Optional[str] = None
    proxy_addr: Optional[str] = None
    proxy_port: Optional[int] = None

class VerifyRequest(BaseModel):
    phone: str
    code: str
    password: Optional[str] = None

class ResetSessionRequest(BaseModel):
    phone: str

class StartScrapeRequest(BaseModel):
    target: str
    output_dir: str = "./downloads"
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    scrape_videos: bool = True
    scrape_images: bool = True
    scrape_messages: bool = True
    scrape_others: bool = True
    scrape_urls: bool = True
    forward_target: Optional[str] = "me"
    mirror_target: Optional[str] = None
    webhook_url: Optional[str] = None

class WatchRequest(BaseModel):
    target: str
    output_dir: str = "./downloads"
    scrape_videos: bool = True
    scrape_images: bool = True
    scrape_messages: bool = True
    scrape_others: bool = True
    scrape_urls: bool = True
    forward_target: Optional[str] = None

class DownloadSelectedRequest(BaseModel):
    target: Optional[str] = "target_channel"
    output_dir: str = "./downloads"
    selected_ids: List[int]

class ClearMediaRequest(BaseModel):
    source: Optional[str] = "all"
    category: Optional[str] = "all"
    channel: Optional[str] = None
    ids: Optional[List[int]] = None
