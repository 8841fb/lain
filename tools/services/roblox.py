from datetime import timedelta

from discord.ext.commands import CommandError
from yarl import URL

from tools.managers import ClientSession, cache
from tools.models import RobloxProfile, RobloxStatistics


@cache(ttl=timedelta(minutes=60), key="{username}")
async def profile(
    session: ClientSession,
    username: str,
) -> RobloxProfile:
    data = await session.request(
        "POST",
        "https://users.roblox.com/v1/usernames/users",
        json={
            "usernames": [
                username,
            ],
        },
    )

    if not data.data:
        raise CommandError(
            f"No **roblox account** found for [`{username}`]({URL(f'https://www.roblox.com/search/users?keyword={username}')})"
        )

    user = await session.request(
        "GET", f"https://users.roblox.com/v1/users/{data.data[0].id}"
    )

    soup = await session.request(
        "GET",
        f"https://www.roblox.com/users/{user.id}/profile",
        raise_for={
            404: f"**Roblox account** [`{username}`]({URL(f'https://www.roblox.com/search/users?keyword={username}')}) is banned"
        },
    )

    badges = await session.request(
        "GET",
        "https://www.roblox.com/badges/roblox",
        params={
            "userId": user.id,
        },
    )

    return RobloxProfile(
        url=f"https://www.roblox.com/users/{user.id}/profile",
        id=user.id,
        username=user.name,
        display_name=user.displayName,
        description=user.description,
        avatar_url=(
            (meta.attrs["content"].replace("352", "420"))
            if (meta := soup.find("meta", property="og:image"))
            else None
        ),
        created_at=user.created,
        badges=[badge.Name for badge in getattr(badges, "RobloxBadges", [])],
        statistics=(
            RobloxStatistics(
                friends=int(statistics.get("data-friendscount")),
                followers=int(statistics.get("data-followerscount")),
                following=int(statistics.get("data-followingscount")),
            )
            if (
                statistics := (
                    header.attrs
                    if (
                        header := soup.find(
                            "div", {"profile-header-layout": "profileHeaderLayout"}
                        )
                    )
                    else None
                )
            )
            else {}
        ),
    )
