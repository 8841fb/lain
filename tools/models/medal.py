from typing import List, Dict, Optional
from datetime import datetime
from pydantic import BaseModel


class MedalAsset(BaseModel):
    """Medal asset model"""

    video_url: str


class MedalPostStatistics(BaseModel):
    """Medal post statistics model"""

    views: Optional[int] = 0
    likes: Optional[int] = 0
    comments: Optional[int] = 0


class MedalUser(BaseModel):
    """Medal user model"""

    display_name: Optional[str] = None
    username: str
    avatar: Optional[str] = None
    url: str


class MedalPost(BaseModel):
    """Medal post model"""

    url: str
    id: str
    title: Optional[str] = None
    description: Optional[str] = None
    author: MedalUser
    asset: MedalAsset
    statistics: MedalPostStatistics
