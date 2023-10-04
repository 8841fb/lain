from typing import List, Dict, Optional, Literal
from pydantic import BaseModel


class Song(BaseModel):
    """A song from Shazam"""

    title: str
    url: str
    artist: str
