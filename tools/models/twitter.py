from datetime import *
from typing import *

from pydantic import *


class TwitterUser(BaseModel):
    url: HttpUrl
    name: str
    screen_name: str
    avatar: Optional[HttpUrl]  # Make avatar field optional


class TwitterStatistics(BaseModel):
    likes: int
    replies: int


class TwitterAssets(BaseModel):
    images: Optional[List[str]]
    video: Optional[str]


class TwitterPost(BaseModel):
    id: int
    url: str
    text: Optional[str]
    user: TwitterUser
    statistics: TwitterStatistics
    assets: TwitterAssets
