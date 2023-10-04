from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel


class YouTubeUser(BaseModel):
    id: str
    url: str
    name: str


class YouTubeStatistics(BaseModel):
    views: int


class YouTubeDownload(BaseModel):
    fps: int
    bitrate: int
    duration: int
    url: str


class YouTubePost(BaseModel):
    id: str
    url: str
    title: str
    thumbnail: str
    created_at: int
    user: YouTubeUser
    statistics: YouTubeStatistics
    download: YouTubeDownload
