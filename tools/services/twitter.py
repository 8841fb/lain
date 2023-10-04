# Cache results from FXTwitter API returning a model

from datetime import timedelta

from discord.ext.commands import CommandError

from tools.managers import ClientSession, cache
from tools.managers.regex import TWITTER_URL
from tools.models import TwitterAssets, TwitterPost, TwitterStatistics, TwitterUser


@cache(ttl=timedelta(minutes=5), key="{url}")
async def get_tweet(session: ClientSession, url: str) -> TwitterPost:
    """Get a tweet from the API."""

    if not (match := TWITTER_URL.match(url)):
        return

    data = await session.request(
        "GET",
        f"https://api.fxtwitter.com/{match.group('screen_name')}/status/{match.group('id')}",
        raise_for={
            500: "Could not fetch that tweet, possible explicit content.",
        },
    )

    return TwitterPost(
        id=data.tweet.id,
        url=data.tweet.url,
        text=data.tweet.text,
        statistics=TwitterStatistics(
            likes=data.tweet.likes,
            replies=data.tweet.replies,
        ),
        user=TwitterUser(
            url=f"https://twitter.com/{data.tweet.author.screen_name}",
            name=data.tweet.author.name,
            screen_name=data.tweet.author.screen_name,
            avatar=data.tweet.author.avatar_url,
        ),
        assets=TwitterAssets(
            images=[image.url for image in data.tweet.media.photos]
            if data.tweet.media and data.tweet.media.photos
            else None,
            video=data.tweet.media.videos[0].url
            if data.tweet.media and data.tweet.media.videos
            else None,
        ),
    )
