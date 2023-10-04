from datetime import timedelta

import aiohttp
from discord.ext.commands import CommandError

from tools.managers import ClientSession, cache
from tools.managers.regex import TIKTOK_DESKTOP_URL, TIKTOK_MOBILE_URL
from tools.models import (
    TikTokAssets,
    TikTokPost,
    TikTokStatistics,
    TikTokUser,
    TikTokProfile,
    TikTokProfileStatistics,
)

from datetime import timedelta
from yarl import URL


@cache(ttl=timedelta(minutes=10), key="tiktok:{url}")
async def get_post(url: str) -> TikTokPost:
    """Get a TikTok post from a URL."""

    mobile = TIKTOK_MOBILE_URL.match(url)
    desktop = TIKTOK_DESKTOP_URL.match(url)

    if not mobile and not desktop:
        raise ValueError("Invalid TikTok URL.")

    async with aiohttp.ClientSession() as session:
        if mobile:
            async with session.get(mobile.group(0)) as response:
                url = str(response.url)
                video_id = TIKTOK_DESKTOP_URL.match(url).group()
        else:
            video_id = desktop.group()

        video_id = video_id.split("/")[5]

        api_url = f"https://api16-normal-c-useast1a.tiktokv.com/aweme/v1/feed/?aweme_id={video_id}"
        async with session.get(api_url) as response:
            data = await response.json()

        video = data["aweme_list"][0]

        if video["aweme_id"] != video_id:
            raise CommandError("Invalid TikTok URL.")

        if "image_post_info" in video:
            images = [
                image["display_image"]["url_list"][0]
                for image in video["image_post_info"]["images"]
            ]
        else:
            images = []

        result = TikTokPost(
            id=video["aweme_id"],
            share_url=f'https://www.tiktok.com/@{video["author"]["unique_id"]}/video/{video["aweme_id"]}',
            caption=video["desc"],
            created_at=video["create_time"],
            user=TikTokUser(
                id=video["author"]["uid"],
                url=f'https://www.tiktok.com/@{video["author"]["unique_id"]}',
                username=video["author"]["unique_id"],
                nickname=video["author"]["nickname"],
                avatar=video["author"]["avatar_larger"]["url_list"][1],
            ),
            statistics=TikTokStatistics(
                plays=video["statistics"]["play_count"],
                likes=video["statistics"]["digg_count"],
                comments=video["statistics"]["comment_count"],
                shares=video["statistics"]["share_count"],
            ),
            assets=TikTokAssets(
                cover=video["video"]["cover"]["url_list"][0],
                dynamic_cover=video["video"]["dynamic_cover"]["url_list"][0],
                images=images,
                video=video["video"]["play_addr"]["url_list"][0]
                if video["video"]["play_addr"]
                else None,
            ),
        )

        return result
