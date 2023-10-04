from datetime import timedelta
from tools.managers import ClientSession, cache
from tools.models import MedalPost, MedalUser, MedalAsset, MedalPostStatistics
from tools.managers.regex import MEDAL_URL


@cache(ttl=timedelta(minutes=60), key="{url}")
async def clip(session: ClientSession, url: str) -> MedalPost:
    """Get a clip from Medal.tv, without the watermark."""

    match = MEDAL_URL.match(url)
    match = match.group(2)

    if not match:
        raise ValueError("Invalid Medal.tv URL.")

    data = await session.request("GET", f"https://medal.tv/api/content/{match}")

    if not data:
        raise ValueError("Clip not found.")

    return MedalPost(
        id=match,
        url=url,
        title=data.contentTitle or None,
        description=data.contentDescription or None,
        author=MedalUser(
            username=data.poster.userName,
            display_name=data.poster.displayName or None,
            avatar=data.poster.thumbnail or None,
            url=f"https://medal.tv/users/{data.poster.userName}",
        ),
        statistics=MedalPostStatistics(
            views=data.views,
            likes=data.likes,
            comments=data.comments,
        ),
        asset=MedalAsset(
            video_url=str(data.contentUrl),
        ),
    )
