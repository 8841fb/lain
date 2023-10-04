from datetime import *
from typing import *

from pydantic import *


class PinterestStatistics(BaseModel):
    comments: int
    saves: int


class PinterestMedia(BaseModel):
    type: Literal["image", "video"]
    url: str


class PinterestUserStatistics(BaseModel):
    pins: int
    followers: int
    following: int


class PinterestUser(BaseModel):
    url: str
    id: int
    username: str
    display_name: str
    avatar: str


class PinterestPin(BaseModel):
    url: str
    id: int
    title: str
    created_at: str
    media: PinterestMedia
    user: PinterestUser
    statistics: PinterestStatistics
