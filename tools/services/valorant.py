from datetime import timedelta
from yarl import URL

from tools.managers import ClientSession, cache
from tools.models.valorant import ValorantAccount, ValorantMatch


@cache(ttl=timedelta(minutes=15), key="{username}")
async def account(session: ClientSession, username: str) -> dict:
    """Get a Valorant account statistics from a username"""

    sliced = username.split("#", 1)
    if len(sliced) != 2:
        raise ValueError("Invalid username.")

    username, tag = sliced

    account = await session.request(
        "GET",
        URL(f"https://api.henrikdev.xyz/valorant/v1/account/{username}/{tag}"),
        raise_for={
            404: f"Couldn't find an account for `{username}#{tag}`",
            429: "The **API** is currently **rate limited** - Try again later",
        },
        headers=dict(Authorization="HDEV-35f056ec-468d-4079-b2bd-7c3ad7d69c13"),
    )

    if not "data" in account:
        raise ValueError("Couldn't find an account for `{username}#{tag}`")
    
    mmr = await session.request(
        "GET",
        f"https://api.henrikdev.xyz/valorant/v2/mmr/{account.data.region}/{URL(username)}/{URL(tag)}",
        headers=dict(Authorization="HDEV-35f056ec-468d-4079-b2bd-7c3ad7d69c13"),
        raise_for={
            404: "Couldn't find an account for `{username}#{tag}`",
            429: "The **API** is currently **rate limited** - Try again later",
        },
    )

    matches = await session.request(
        "GET",
        f"https://api.henrikdev.xyz/valorant/v3/matches/{account.data.region}/{URL(username)}/{URL(tag)}",
        params=dict(filter="competitive"),
        headers=dict(Authorization="HDEV-35f056ec-468d-4079-b2bd-7c3ad7d69c13"),
        raise_for={
            404: "Couldn't find any matches for `{username}#{tag}`",
            429: "The **API** is currently **rate limited** - Try again later",
        },
    )

    account: dict = dict(
        region=account.data.region.upper(),
        username=f"{account.data.name}#{account.data.tag}",
        level=account.data.account_level,
        rank=mmr.data.current_data.currenttierpatched or "Unranked",
        elo=mmr.data.current_data.elo or 0,
        elo_change=mmr.data.current_data.mmr_change_to_last_game or 0,
        card=account.data.card.small,
        updated_at=account.data.last_update_raw,
    )

    matches: list = [
        ValorantMatch(
            map=match.metadata.map,
            rounds=match.metadata.rounds_played,
            status=("Victory" if match.teams.red.has_won else "Defeat"),
            kills=match.players.all_players[0].stats.kills,
            deaths=match.players.all_players[0].stats.deaths,
            started_at=match.metadata.game_start,
        )
        for match in matches.data
    ]

    return ValorantAccount(**account, matches=matches)
