from pytube import YouTube  # type: ignore
from pytube.exceptions import VideoUnavailable, LiveStreamError  # type: ignore
from datetime import timedelta
from asyncio import to_thread

from discord.ext.commands import CommandError

from tools.managers import cache
from tools.managers.regex import (
    YOUTUBE_CLIP_URL,
    YOUTUBE_SHORT_URL,
    YOUTUBE_SHORTS_URL,
    YOUTUBE_URL,
)
from tools.models import YouTubeDownload, YouTubePost, YouTubeStatistics, YouTubeUser


@cache(ttl=timedelta(minutes=30), key="youtube:{url}")
async def get_post(url: str) -> YouTubePost:
    """Get a YouTube post from a URL."""

    matches = (
        YOUTUBE_URL.match(url),
        YOUTUBE_SHORT_URL.match(url),
        YOUTUBE_SHORTS_URL.match(url),
        YOUTUBE_CLIP_URL.match(url),
    )

    match = next((match for match in matches if match), None)

    if not match:
        raise CommandError("Invalid YouTube URL.")

    video_url, video_id = match.group(0), match.group(1)

    try:
        video = await to_thread(
            YouTube, video_url, use_oauth=False, allow_oauth_cache=True
        )
    except (VideoUnavailable, LiveStreamError):
        return

    stream = (
        video.streams.filter(
            progressive=True,
            file_extension="mp4",
            subtype="mp4",
        )
        .order_by("resolution")
        .desc()
        .first()
    )

    return YouTubePost(
        id=video_id,
        url=video_url,
        title=video.title,
        thumbnail=video.thumbnail_url,
        created_at=video.publish_date.timestamp(),
        user=YouTubeUser(
            id=video.channel_id,
            url=video.channel_url,
            name=video.author,
        ),
        statistics=YouTubeStatistics(
            views=video.views,
        ),
        download=YouTubeDownload(
            fps=stream.fps,
            bitrate=stream.bitrate,
            duration=video.length,
            url=stream.url,
        ),
    )
