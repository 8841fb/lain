from datetime import datetime
from pydantic import BaseModel
from typing import List


class ValorantAccount(BaseModel):
    region: str
    username: str
    level: int
    rank: str
    elo: int
    elo_change: int
    card: str
    updated_at: datetime
    matches: List["ValorantMatch"]


class ValorantMatch(BaseModel):
    map: str
    status: str
    rounds: int
    kills: int
    deaths: int
    started_at: datetime
