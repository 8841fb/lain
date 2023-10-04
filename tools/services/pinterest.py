from datetime import timedelta
from json import dumps

import aiohttp

from tools.managers import cache
from tools.managers.regex import PINTEREST_PIN_APP_URL, PINTEREST_PIN_URL
from tools.models import (
    PinterestMedia,
    PinterestPin,
    PinterestStatistics,
    PinterestUser,
    PinterestUserStatistics,
)


@cache(ttl=timedelta(minutes=15), key="{username}")
async def profile(
    username: str,
) -> PinterestUser:
    async with aiohttp.ClientSession() as session:
        async with session.get(
            f"https://www.pinterest.com/{username}/",
            params=dict(
                source_url=f"/{username}/",
                data=dumps(
                    {
                        "options": {
                            "field_set_key": "unauth_profile",
                            "username": username,
                            "is_mobile_fork": True,
                        },
                        "context": {},
                    }
                ),
            ),
        ) as response:
            if response.status != 200:
                raise ValueError("Invalid Pinterest username.")

            data = await response.json()

    user = data["resource_response"]["data"]["user"]

    output = PinterestUser(
        url=f"https://www.pinterest.com/{user['username']}/",
        id=int(user["id"]),
        username=user["username"],
        display_name=user["full_name"],
        avatar=user["image_xlarge_url"],
        bio=user["about"],
        statistics=PinterestUserStatistics(
            pins=user["pin_count"],
            followers=user["follower_count"],
            following=user["following_count"],
        ),
    )

    return output


@cache(ttl=timedelta(minutes=15), key="{url}")
async def get_pin(url: str) -> PinterestPin:
    """Get a pin from the API."""

    match = PINTEREST_PIN_URL.match(url) or PINTEREST_PIN_APP_URL.match(url)
    if not match:
        return

    async with aiohttp.ClientSession() as session:
        if PINTEREST_PIN_APP_URL.match(url):
            async with session.get(match.group()) as response:
                match = PINTEREST_PIN_URL.match(str(response.url))
                if not match:
                    raise ValueError("Invalid Pinterest URL.")

        async with session.get(
            "https://www.pinterest.com/resource/PinResource/get/",
            params=dict(
                source_url=match.group(),
                data=dumps(
                    {
                        "options": {
                            "id": match.group(1),
                            "field_set_key": "unauth_react_main_pin",
                            "add_connection_type": False,
                            "fetch_pin_join_by_default": True,
                        },
                        "context": {},
                    }
                ),
            ),
        ) as response:
            if response.status != 200:
                raise ValueError("Invalid Pinterest URL.")

            data = await response.json()

    pin = data["resource_response"]["data"]

    if videos := pin.get("videos"):
        video = videos["video_list"]["V_720P"]
        media = {
            "type": "video",
            "url": video["url"],
        }
    elif story_pin := pin.get("story_pin_data"):
        block = story_pin["pages"][0]["blocks"][0]
        if block["type"] == "story_pin_video_block":
            # Get first video from video.video_list dict using key
            video = list(block["video"]["video_list"].values())[0]
            media = {
                "type": "video",
                "url": video["url"],
            }
        elif block["type"] == "story_pin_image_block":
            image = block["images"]["orig"]
            media = {
                "type": "image",
                "url": image["url"],
            }

    elif images := pin.get("images"):
        image = images["orig"]
        media = {
            "type": "image",
            "url": image["url"],
        }

    output = PinterestPin(
        id=pin["id"],
        url=match.group(),
        title=pin["title"],
        created_at=pin["created_at"],
        media=PinterestMedia(
            type=media["type"],
            url=media["url"],
        ),
        user=PinterestUser(
            url=f"https://www.pinterest.com/{pin['pinner']['username']}/",
            id=pin["pinner"]["id"],
            username=pin["pinner"]["username"],
            display_name=pin["pinner"]["full_name"],
            avatar=pin["pinner"]["image_medium_url"],
        ),
        statistics=PinterestStatistics(
            comments=pin["aggregated_pin_data"]["comment_count"],
            saves=pin["aggregated_pin_data"]["aggregated_stats"]["saves"],
        ),
    )

    return output
