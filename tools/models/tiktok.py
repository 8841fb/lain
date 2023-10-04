from datetime import *
from typing import *

from pydantic import *


class TikTokPostBasic(BaseModel):
    id: int
    url: str


class TikTokProfileStatistics(BaseModel):
    verified: Optional[bool] = False
    likes: Optional[str] = "0"
    followers: Optional[str] = "0"
    following: Optional[str] = "0"


class TikTokProfile(BaseModel):
    url: str
    username: str
    display_name: str
    description: Optional[str]
    avatar_url: str
    created_at: Optional[datetime] = None
    statistics: TikTokProfileStatistics = TikTokProfileStatistics()


class TikTokUser(BaseModel):
    id: Optional[int]
    url: str
    username: str
    nickname: str
    avatar: str


class TikTokStatistics(BaseModel):
    plays: int
    likes: int
    comments: int
    shares: int


class TikTokAssets(BaseModel):
    cover: str
    dynamic_cover: str
    images: Optional[List[str]]
    video: Optional[str]


class TikTokPost(BaseModel):
    id: int
    share_url: str
    caption: Optional[str]
    created_at: datetime
    user: TikTokUser
    statistics: TikTokStatistics
    assets: TikTokAssets
