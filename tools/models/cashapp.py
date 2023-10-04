from typing import Optional
from pydantic import BaseModel


class CashAppAvatar(BaseModel):
    image_url: Optional[str] = None
    accent_color: Optional[str] = None


class CashApp(BaseModel):
    url: str
    cashtag: str
    display_name: str
    country_code: str
    avatar_url: CashAppAvatar
    qr: str
