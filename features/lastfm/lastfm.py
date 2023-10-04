from asyncio import TimeoutError, gather, sleep
from contextlib import suppress
from datetime import datetime
from random import choice
from typing import Literal, Optional, Union
from yarl import URL

from aiohttp import ClientTimeout
from discord import ActivityType, Color, Embed, HTTPException, Member, Message, Spotify
from discord.ext.commands import (
    BucketType,
    CommandError,
    command,
    cooldown,
    group,
    has_permissions,
    max_concurrency,
)
from discord.utils import format_dt, get

from tools.converters.basic import ChartSize, MemberStrict, State
from tools.converters.embed import EmbedScript, EmbedScriptValidator
from tools.managers.cog import Cog
from tools.managers.context import Context
from tools.utilities.humanize import percentage
from tools.utilities.text import Plural, format_uri, shorten


class lastfm(Cog, name="Last.fm Integration"):
    """Last.fm Integration"""

    def get_color(self, ctx: Context, config: dict):
        return config.get("color") if isinstance(config.get("color"), int) else (None)

    @Cog.listener("on_user_message")
    async def on_user_message(self, ctx: Context, message: Message):
        """Dispatch custom now playing commands"""

        if not message.content:
            return

        commands = await self.bot.db.fetch(
            "SELECT * FROM lastfm_commands WHERE guild_id = $1 AND command = $2",
            ctx.guild.id,
            message.content.split(" ")[0].lower(),
        )
        for command in commands:
            if not command.get("public") and ctx.author.id != command.get("user_id"):
                continue

            await ctx.invoke(self.nowplaying)
            break

    async def request(self, path: str, payload: dict):
        response = await self.bot.session.get(
            "https://fm.lains.life" + path,
            params=payload,
            timeout=ClientTimeout(total=None),
            headers=dict(
                Authorization="lainJIKASDN9qwikfa3sIOAWKF",
            ),
        )
        data = await response.json()

        if response.status == 503:
            raise CommandError(
                "**Last.fm:** Operation failed - The backend service didn't respond"
            )
        elif response.status == 429:
            raise CommandError("**Last.fm:** Operation failed - Rate limit exceeded")
        elif response.status == 404:
            if data["message"] == "User not found":
                raise CommandError(
                    f"[**{payload['username']}**](https://last.fm/user/{format_uri(payload['username'])}) is not a valid **Last.fm**"
                    " account"
                )
            elif data["message"] == "Artist not found":
                raise CommandError("Invalid artist according to **Last.fm**")
            elif data["message"] == "Album not found":
                raise CommandError("Invalid album according to **Last.fm**")
            elif data["message"] == "Track not found":
                raise CommandError("Invalid track according to **Last.fm**")
            return None
        elif response.status == 400:
            if data["message"] == "Collage size invalid":
                raise CommandError(
                    "Collage size **incorrectly formatted** - example: `6x6`"
                )
            elif data["message"] == "Collage size is too small":
                raise CommandError(
                    "Collage size **too small**\n> Minimum size is `1x1`"
                )
            elif data["message"] == "Collage size is too large":
                raise CommandError(
                    "Collage size **too large**\n> Maximum size is `10x10`"
                )
            elif (
                data["message"]
                == "The account does not have any scrobbles for the time period specified."
            ):
                return None

            if data["message"] == "Login: User required to be logged in":
                raise CommandError(
                    "I'm unable to view information for"
                    f" [**{payload['username']}**](https://last.fm/user/{format_uri(payload['username'])})\n> Check your privacy settings"
                    " on **Last.fm**"
                )
            elif data["message"] == "list index out of range":
                raise CommandError(
                    f"The **Last.fm** account [**{payload['username']}**](https://last.fm/user/{format_uri(payload['username'])}) doesn't"
                    " have any scrobbles"
                )
            raise CommandError(f"**Last.fm:** {data['message']}")

        return data

    async def get_username(self, ctx: Context, user: Member | str = None):
        user = user or ctx.author
        if not isinstance(user, str):
            data = await self.bot.db.fetchrow(
                "SELECT * FROM lastfm WHERE user_id = $1", user.id
            )
            if not data:
                raise CommandError(
                    f"You haven't set your **Last.fm** username yet\n> You can connect your **Last.fm** using `{ctx.prefix}lastfm set (username)`"
                    if user == ctx.author
                    else (
                        f"**{user}** hasn't set their **Last.fm** username yet\n> They can connect their **Last.fm** using `{ctx.prefix}lastfm set"
                        " (username)`"
                    )
                )

            username = data.get("username")
        else:
            username = user
            user = None

        if user != ctx.author:
            data = (
                await self.bot.db.fetchrow(
                    "SELECT * FROM lastfm WHERE user_id = $1", ctx.author.id
                )
                or {}
            )

        return username, data.get("config", {})

    async def execute_nowplaying(
        self,
        ctx: Context,
        username: str,
        member: Member,
        config: dict,
        previous: Message = None,
    ):
        """Execute the main aspects of the Now Playing command"""

        data = await self.request(
            "/nowplaying",
            payload=dict(
                username=username,
            ),
        )
        if not data and not previous:
            raise CommandError(
                f"[**{username}**](https://last.fm/user/{format_uri(username)}) is not listening to anything right now"
            )

        if script := config.get("embed"):
            data["artist"]["crown"] = bool(
                await self.bot.db.fetchrow(
                    "SELECT plays FROM lastfm_crowns WHERE guild_id = $1 AND user_id = $2 AND lower(artist) = $3",
                    ctx.guild.id,
                    member.id,
                    data["artist"]["name"].lower(),
                )
            )

            message = await EmbedScript(script).send(
                (previous or ctx),
                bot=self.bot,
                guild=ctx.guild,
                channel=ctx.channel,
                user=(member if isinstance(member, Member) else ctx.author),
                lastfm=data,
            )
        else:
            embed = Embed()
            embed.set_author(
                name=f"Last.fm: {data['user'].get('username')}",
                url=data["user"].get("url"),
                icon_url=data["user"].get("avatar"),
            )

            embed.add_field(
                name="Track",
                value=f"[{data.get('name')}]({data.get('url')})",
                inline=True,
            )
            embed.add_field(
                name="Artist",
                value=f"[{data['artist'].get('name')}]({data['artist'].get('url')})",
                inline=True,
            )
            if image := data.get("image"):
                embed.set_thumbnail(url=image["url"])
            if isinstance(config.get("color"), int):
                embed.color = Color(config.get("color"))

            embed.set_footer(
                text=(
                    f"Plays: {data.get('plays'):,} ∙ Scrobbles: {data['user']['library'].get('scrobbles'):,} ∙ Album:"
                    f" {shorten(data['album'].get('name')) if data.get('album') else 'N/A'}"
                )
            )
            if not previous:
                message = await ctx.reply(embed=embed)
            else:
                message = None

        if message and config.get("reactions") != False:
            with suppress(HTTPException):
                reactions = config.get("reactions", {})
                await message.add_reaction(reactions.get("upvote") or "👍🏾")
                await message.add_reaction(reactions.get("downvote") or "👎🏾")

        await self.bot.db.execute(
            "INSERT INTO lastfm_library.artists (user_id, username, artist, plays) VALUES ($1, $2, $3, $4) ON CONFLICT (user_id, artist) DO UPDATE"
            " SET plays = $4",
            member.id,
            username,
            data["artist"].get("name"),
            data["artist"].get("plays"),
        )
        if data.get("album"):
            await self.bot.db.execute(
                "INSERT INTO lastfm_library.albums (user_id, username, artist, album, plays) VALUES ($1, $2, $3, $4, $5) ON CONFLICT (user_id,"
                " artist, album) DO UPDATE SET plays = $5",
                member.id,
                username,
                data["artist"].get("name"),
                data["album"].get("name"),
                data["album"].get("plays"),
            )
        await self.bot.db.execute(
            "INSERT INTO lastfm_library.tracks (user_id, username, artist, track, plays) VALUES ($1, $2, $3, $4, $5) ON CONFLICT (user_id, artist,"
            " track) DO UPDATE SET plays = $5",
            member.id,
            username,
            data["artist"].get("name"),
            data.get("name"),
            data.get("plays"),
        )

        return data, message

    @command(
        name="nowplaying",
        usage="<member>",
        example="caden",
        aliases=["now", "np", "fm"],
    )
    async def nowplaying(self, ctx: Context, *, member: Member = None):
        """View your current song playing from Last.fm"""

        member = member or ctx.author
        username, config = await self.get_username(ctx, member)

        async with ctx.typing():
            track, message = await self.execute_nowplaying(
                ctx, username, member, config
            )

        if not track:
            return

        def check(before: Member, after: Member):
            if after.id != ctx.author.id:
                return False
            if after.guild.id != ctx.guild.id:
                return False

            spotify_status = get(after.activities, type=ActivityType.listening)
            if not isinstance(spotify_status, Spotify):
                return False

            return track["name"].lower() != spotify_status.title.lower()

        for _ in range(5):
            try:
                await self.bot.wait_for("presence_update", check=check, timeout=5)
            except TimeoutError:
                if _ == 5:
                    break
                continue

            await sleep(1.50)
            track, message = await self.execute_nowplaying(
                ctx, username, member, config, message
            )

    @group(
        name="lastfm",
        usage="(subcommand) <args>",
        example="set larplol",
        aliases=["lfm", "lf"],
        invoke_without_command=True,
    )
    async def lastfm(self, ctx: Context):
        """Interact with Last.fm through lain"""

        await ctx.send_help()

    @lastfm.group(
        name="command",
        usage="(substring)",
        example="now",
        parameters={
            "public": {
                "require_value": False,
                "description": "Allow other members to use the command",
                "aliases": ["p"],
            }
        },
        aliases=["customcommand", "cmd", "cc"],
        invoke_without_command=True,
    )
    async def lastfm_command(
        self,
        ctx: Context,
        substring: str,
    ):
        """Set a custom command for Last.fm now playing"""

        username, config = await self.get_username(ctx)

        substring = substring.lower().replace(" ", "")
        if len(substring) < 2:
            return await ctx.error(
                "Your **command** must contain at least **2 characters**"
            )

        if (
            ctx.parameters.get("public")
            and not ctx.author.guild_permissions.manage_guild
        ):
            return await ctx.error(
                "The **public** flag requires the `manage_guild` permission"
            )

        await self.bot.db.execute(
            "INSERT INTO lastfm_commands (guild_id, user_id, command, public) VALUES ($1, $2, $3, $4) ON CONFLICT (guild_id, user_id) DO UPDATE SET"
            " command = $3, public = $4",
            ctx.guild.id,
            ctx.author.id,
            substring,
            ctx.parameters.get("public") or False,
        )
        await ctx.approve(
            f"Your **now playing** command has been set to `{substring}`"
            + (" (public)" if ctx.parameters.get("public") else "")
        )

    @lastfm_command.command(
        name="public",
        usage="(substring) (on or off)",
        example="now off",
    )
    @has_permissions(manage_guild=True)
    async def lastfm_command_public(
        self, ctx: Context, substring: str, state: State = True
    ):
        """Toggle the public flag for a custom command"""

        substring = substring.lower().replace(" ", "")
        if len(substring) < 2:
            return await ctx.error(
                "Your **command** must be at least **2 characters** long"
            )

        command = await self.bot.db.fetchrow(
            "SELECT * FROM lastfm_commands WHERE guild_id = $1 AND command = $2",
            ctx.guild.id,
            substring,
        )
        if not command:
            return await ctx.error(f"No **custom command** found for `{substring}`")

        await self.bot.db.execute(
            "UPDATE lastfm_commands SET public = $3 WHERE guild_id = $1 AND command = $2",
            ctx.guild.id,
            substring,
            state,
        )
        await ctx.approve(
            f"{'Enabled' if state else 'Disabled'} the **public** flag for `{substring}`"
        )

    @lastfm_command.command(
        name="remove",
        usage="<substring or member>",
        example="lain",
        aliases=["delete", "del", "rm"],
    )
    async def lastfm_command_remove(
        self,
        ctx: Context,
        *,
        member: Member | str = None,
    ):
        """Remove a custom command for Last.fm now playing"""

        member = member or ctx.author

        if isinstance(member, Member):
            if member != ctx.author and not ctx.author.guild_permissions.manage_guild:
                return await ctx.error(
                    "You can only remove your own **custom command**"
                )

            try:
                await self.bot.db.execute(
                    "DELETE FROM lastfm_commands WHERE guild_id = $1 AND user_id = $2",
                    ctx.guild.id,
                    member.id,
                )
            except:
                await ctx.error(f"**{member}** doesn't have a **custom command**")
            else:
                await ctx.approve(
                    f"Removed {member.mention}'s **custom command**"
                    if member != ctx.author
                    else "Removed your **custom command**"
                )
        else:
            substring = member.lower().replace(" ", "")
            if len(substring) < 2:
                return await ctx.error(
                    "Your **command** must be at least **2 characters** long"
                )

            try:
                await self.bot.db.execute(
                    "DELETE FROM lastfm_commands WHERE guild_id = $1 AND command = $2",
                    ctx.guild.id,
                    substring,
                )
            except:
                return await ctx.error(f"No **custom command** found for `{substring}`")

            return await ctx.approve(
                f"Removed the **custom command** for `{substring}`"
            )

    @lastfm_command.command(
        name="list",
        aliases=["show", "all"],
    )
    @has_permissions(manage_guild=True)
    async def lastfm_command_list(self, ctx: Context):
        """View all custom commands for Last.fm now playing"""

        commands = [
            f"{command['command']} - **{ctx.guild.get_member(command['user_id']) or 'User Left'}** {'(public)' if command['public'] else ''}"
            for command in await self.bot.db.fetch(
                "SELECT * FROM lastfm_commands WHERE guild_id = $1",
                ctx.guild.id,
            )
        ]
        if not commands:
            return await ctx.error("No **custom commands** have been set")

        await ctx.paginate(
            Embed(
                title="Custom Commands",
                description=commands,
            )
        )

    @lastfm.command(
        name="set",
        usage="(username)",
        example="larplol",
        aliases=["connect", "login"],
    )
    @max_concurrency(1, BucketType.user)
    async def lastfm_set(self, ctx: Context, username: str):
        """Set your Last.fm username"""

        data = await self.request(
            "/profile",
            payload=dict(
                username=username,
            ),
        )

        if current_username := await self.bot.db.fetchval(
            "SELECT username FROM lastfm WHERE user_id = $1", ctx.author.id
        ):
            if current_username == data.get("username"):
                return await ctx.error(
                    "Your **Last.fm** username is already set as"
                    f" [**{current_username}**](https://last.fm/user/{format_uri(current_username)})"
                )
            else:
                if crowns := await self.bot.db.fetchrow(
                    "SELECT * FROM lastfm_crowns WHERE user_id = $1", ctx.author.id
                ):
                    await ctx.prompt(
                        "Are sure you want to change your **Last.fm** username?\n> You will lose"
                        f" **{Plural(len(crowns)):crown}** across every server!"
                    )
                    await self.bot.db.execute(
                        "DELETE FROM lastfm_crowns WHERE user_id = $1", ctx.author.id
                    )

        await ctx.load(
            f"Setting your **Last.fm** username to [**{data.get('username')}**](https://last.fm/user/{format_uri(data.get('username'))}).."
        )
        await self.bot.db.execute(
            "INSERT INTO lastfm (user_id, username) VALUES ($1, $2) ON CONFLICT (user_id) DO UPDATE SET username = $2",
            ctx.author.id,
            data.get("username"),
        )

        await ctx.load("Started **index** of your **Last.fm** library..")
        queries = [
            "DELETE FROM lastfm_library.artists WHERE user_id = $1;",
            "DELETE FROM lastfm_library.albums WHERE user_id = $1;",
            "DELETE FROM lastfm_library.tracks WHERE user_id = $1;",
        ]

        await gather(*[self.bot.db.execute(query, ctx.author.id) for query in queries])

        await ctx.load("Started **index** of your **Last.fm** artist library..")
        artists = await self.request(
            "/library/artists",
            payload=dict(
                username=data.get("username"),
            ),
        )
        if artists:
            await ctx.load("Saving **index** of your **Last.fm** artist library..")
            await self.bot.db.executemany(
                "INSERT INTO lastfm_library.artists (user_id, username, artist, plays) VALUES ($1, $2, $3, $4) ON CONFLICT (user_id, artist) DO"
                " UPDATE SET plays = $4",
                [
                    (
                        ctx.author.id,
                        data.get("username"),
                        artist.get("name"),
                        artist.get("plays"),
                    )
                    for artist in artists
                ],
            )
        else:
            await ctx.load("Aborting **index** of your **Last.fm** artist library..")

        await ctx.load("Started **index** of your **Last.fm** album library..")
        albums = await self.request(
            "/library/albums",
            payload=dict(
                username=data.get("username"),
            ),
        )
        if albums:
            await ctx.load("Saving **index** of your **Last.fm** album library..")
            await self.bot.db.executemany(
                "INSERT INTO lastfm_library.albums (user_id, username, artist, album, plays) VALUES ($1, $2, $3, $4, $5) ON CONFLICT (user_id,"
                " artist, album) DO UPDATE SET plays = $5",
                [
                    (
                        ctx.author.id,
                        data.get("username"),
                        album.get("artist"),
                        album.get("name"),
                        album.get("plays"),
                    )
                    for album in albums
                ],
            )
        else:
            await ctx.load("Aborting **index** of your **Last.fm** album library..")

        await ctx.load("Started **index** of your **Last.fm** track library..")
        tracks = await self.request(
            "/library/tracks",
            payload=dict(
                username=data.get("username"),
            ),
        )
        if tracks:
            await ctx.load("Saving **index** of your **Last.fm** track library..")
            await self.bot.db.executemany(
                "INSERT INTO lastfm_library.tracks (user_id, username, artist, track, plays) VALUES ($1, $2, $3, $4, $5) ON CONFLICT (user_id,"
                " artist, track) DO UPDATE SET plays = $5",
                [
                    (
                        ctx.author.id,
                        data.get("username"),
                        track.get("artist"),
                        track.get("name"),
                        track.get("plays"),
                    )
                    for track in tracks
                ],
            )
        else:
            await ctx.load("Aborting **index** of your **Last.fm** track library..")

        await ctx.approve(
            "Your **Last.fm** username has been set to"
            f" [**{data.get('username')}**](https://last.fm/user/{format_uri(data.get('username'))})"
        )

    @lastfm.command(
        name="update",
        aliases=["refresh", "reload", "index"],
    )
    @max_concurrency(1, BucketType.user)
    @cooldown(1, 60, BucketType.user)
    async def lastfm_update(self, ctx: Context):
        """Update your Last.fm library"""

        username, config = await self.get_username(ctx)

        await ctx.load("Started **index** of your **Last.fm** library..")
        queries = [
            "DELETE FROM lastfm_library.artists WHERE user_id = $1;",
            "DELETE FROM lastfm_library.albums WHERE user_id = $1;",
            "DELETE FROM lastfm_library.tracks WHERE user_id = $1;",
        ]
        await gather(*[self.bot.db.execute(query, ctx.author.id) for query in queries])

        await ctx.load("Started **index** of your **Last.fm** artist library..")
        artists = await self.request(
            "/library/artists",
            payload=dict(
                username=username,
            ),
        )
        if artists:
            await ctx.load("Saving **index** of your **Last.fm** artist library..")
            await self.bot.db.executemany(
                "INSERT INTO lastfm_library.artists (user_id, username, artist, plays) VALUES ($1, $2, $3, $4) ON CONFLICT (user_id, artist) DO"
                " UPDATE SET plays = $4",
                [
                    (
                        ctx.author.id,
                        username,
                        artist.get("name"),
                        artist.get("plays"),
                    )
                    for artist in artists
                ],
            )
        else:
            await ctx.load("Aborting **index** of your **Last.fm** artist library..")

        await ctx.load("Started **index** of your **Last.fm** album library..")
        albums = await self.request(
            "/library/albums",
            payload=dict(
                username=username,
            ),
        )
        if albums:
            await ctx.load("Saving **index** of your **Last.fm** album library..")
            await self.bot.db.executemany(
                "INSERT INTO lastfm_library.albums (user_id, username, artist, album, plays) VALUES ($1, $2, $3, $4, $5) ON CONFLICT (user_id,"
                " artist, album) DO UPDATE SET plays = $5",
                [
                    (
                        ctx.author.id,
                        username,
                        album.get("artist"),
                        album.get("name"),
                        album.get("plays"),
                    )
                    for album in albums
                ],
            )
        else:
            await ctx.load("Aborting **index** of your **Last.fm** album library..")

        await ctx.load("Started **index** of your **Last.fm** track library..")
        tracks = await self.request(
            "/library/tracks",
            payload=dict(
                username=username,
            ),
        )
        if tracks:
            await ctx.load("Saving **index** of your **Last.fm** track library..")
            await self.bot.db.executemany(
                "INSERT INTO lastfm_library.tracks (user_id, username, artist, track, plays) VALUES ($1, $2, $3, $4, $5) ON CONFLICT (user_id,"
                " artist, track) DO UPDATE SET plays = $5",
                [
                    (
                        ctx.author.id,
                        username,
                        track.get("artist"),
                        track.get("name"),
                        track.get("plays"),
                    )
                    for track in tracks
                ],
            )
        else:
            await ctx.load("Aborting **index** of your **Last.fm** track library..")

        await ctx.approve(f"Your **Last.fm library** has been updated!")

    @lastfm.command(
        name="claim",
    )
    @max_concurrency(1, BucketType.guild)
    @cooldown(1, 60, BucketType.user)
    async def lastfm_claim(self, ctx: Context):
        """Claim crowns for your Last.fm artists"""

        username, config = await self.get_username(ctx)

        await ctx.load("Started **index** of your **Last.fm** artists..")
        queries = [
            "DELETE FROM lastfm_library.artists WHERE user_id = $1;",
            "DELETE FROM lastfm_crowns WHERE user_id = $1;",
        ]
        await gather(*[self.bot.db.execute(query, ctx.author.id) for query in queries])

        artists = await self.request(
            "/library/artists",
            payload=dict(
                username=username,
            ),
        )
        if artists:
            await ctx.load("Saving **index** of your **Last.fm** artists..")
            await self.bot.db.executemany(
                "INSERT INTO lastfm_library.artists (user_id, username, artist, plays) VALUES ($1, $2, $3, $4) ON CONFLICT (user_id, artist) DO"
                " UPDATE SET plays = $4",
                [
                    (
                        ctx.author.id,
                        username,
                        artist.get("name"),
                        artist.get("plays"),
                    )
                    for artist in artists
                ],
            )

        else:
            return await ctx.error(
                "Aborting **index** of your **Last.fm** artists..",
            )

        await ctx.load("Starting **automatic claiming** of your **Last.fm** artists..")

        server_library = await self.bot.db.fetch(
            "SELECT * FROM lastfm_library.artists WHERE user_id = ANY($1::BIGINT[]) ORDER BY plays DESC",
            [
                member.id
                for member in ctx.guild.members
                if not member.id == ctx.author.id
            ],
        )

        artist_crowns = list()
        for artist in artists:
            if artist.get("plays") < 5:
                continue

            for server_artist in server_library:
                if not artist.get("name") == server_artist.get("artist"):
                    continue
                if artist.get("plays") <= server_artist.get("plays"):
                    break
                else:
                    artist_crowns.append(artist)
                    break

        if artist_crowns:
            await ctx.load("Claiming **crowns** for your **Last.fm** artists..")
            await self.bot.db.executemany(
                "INSERT INTO lastfm_crowns (guild_id, user_id, username, artist, plays) VALUES ($1, $2, $3, $4, $5) ON CONFLICT (guild_id, artist) DO"
                " UPDATE SET user_id = $2, username = $3, plays = $5",
                [
                    (
                        ctx.guild.id,
                        ctx.author.id,
                        username,
                        artist.get("name"),
                        artist.get("plays"),
                    )
                    for artist in artist_crowns
                ],
            )
        else:
            await ctx.load(
                "Aborting **automatic claiming** of your **Last.fm** artists.."
            )

        await ctx.approve(
            f"You now have **{Plural(artist_crowns):crown}** for this server"
        )

    @lastfm.command(
        name="mode",
        usage="(embed code or check/remove)",
        example="check",
        aliases=["embed"],
    )
    async def lastfm_mode(
        self,
        ctx: Context,
        *,
        mode: Union[
            Literal["check", "view", "raw", "remove", "reset", "clear", "none"],
            EmbedScriptValidator,
        ],
    ):
        """Set a custom embed for Last.fm now playing"""

        if not mode:
            return await ctx.send_help()

        username, config = await self.get_username(ctx)

        if isinstance(mode, EmbedScript) or mode in (
            "remove",
            "reset",
            "clear",
            "none",
        ):
            if isinstance(mode, EmbedScript):
                if not "{" in str(mode) or not "}" in str(mode):
                    return await ctx.error(f"**{mode}** isn't a recognized mode")

            config.update(
                {"embed": (str(mode) if isinstance(mode, EmbedScript) else None)}
            )

        if mode in ("check", "view", "raw"):
            if not config.get("embed"):
                return await ctx.error("You haven't set a **custom embed** yet")
            else:
                await ctx.neutral(
                    f"Your **custom embed** is set to\n```\n{config.get('embed')}```",
                    emoji="📜",
                )
        else:
            await self.bot.db.execute(
                "UPDATE lastfm SET config = $2 WHERE user_id = $1",
                ctx.author.id,
                config,
            )
            await ctx.approve(
                f"Your **custom embed** has been set to\n```\n{mode}```"
                if isinstance(mode, EmbedScript)
                else f"Your **custom embed** has been removed"
            )

    @lastfm.command(
        name="crowns",
        usage="<member>",
        example="caden",
        aliases=["crown", "c"],
    )
    async def lastfm_crowns(self, ctx: Context, *, member: Member = None):
        """View all of your crowns"""

        member = member or ctx.author
        username, config = await self.get_username(ctx, member)

        async with ctx.typing():
            crowns = await self.bot.db.fetch(
                "SELECT * FROM lastfm_crowns WHERE guild_id = $1 AND user_id = $2 ORDER BY plays DESC",
                ctx.guild.id,
                member.id,
            )

        if not crowns:
            return await ctx.error(
                f"You don't have any crowns\n> Use `{ctx.prefix}lastfm whoknows` to claim some"
                if member == ctx.author
                else f"**{member}** doesn't have any crowns"
            )

        await ctx.paginate(
            Embed(
                color=self.get_color(ctx, config),
                title=(
                    "Your crowns" if member == ctx.author else f"{member.name}'s crowns"
                ),
                description=list(
                    f"[**{shorten(crown.get('artist'))}**](https://last.fm/music/{format_uri(crown.get('artist'))})"
                    f" ({Plural(crown.get('plays')):play})"
                    for crown in crowns
                ),
            )
        )

    @lastfm.command(
        name="whois",
        usage="<member>",
        example="caden",
        aliases=["profile"],
    )
    async def lastfm_whois(
        self,
        ctx: Context,
        *,
        user: Member | str = None,
    ):
        """View Last.fm profile information"""

        username, config = await self.get_username(ctx, user)

        async with ctx.typing():
            data = await self.request(
                "/profile",
                payload=dict(username=username, library=1),
            )

        embed = Embed(
            color=self.get_color(ctx, config),
            url=data.get("url"),
            title=data.get("username"),
            description=(
                f"**Registered:** {format_dt(datetime.fromtimestamp(data['meta'].get('registered')), 'D')}\n**Scrobbles:**"
                f" {data['library'].get('scrobbles'):,}\n**Country:** {data['meta'].get('country') or 'Unknown'}"
            ),
        )

        statistics = list()
        if artist := data["library"].get("artist"):
            statistics.append(
                f"**Artist:** [{artist.get('name')}]({artist.get('url')}) ({Plural(artist.get('plays')):play})"
            )
        if album := data["library"].get("album"):
            statistics.append(
                f"**Album:** [{album.get('name')}]({album.get('url')}) ({Plural(album.get('plays')):play})"
            )
        if track := data["library"].get("track"):
            statistics.append(
                f"**Track:** [{track.get('name')}]({track.get('url')}) ({Plural(track.get('plays')):play})"
            )
        if statistics:
            embed.add_field(
                name="Statistics",
                value="\n".join(statistics),
                inline=True,
            )
        embed.set_thumbnail(url=data.get("avatar"))
        await ctx.send(embed=embed)

    @lastfm.command(
        name="whoknows",
        usage="<artist>",
        example="Lil Tracy",
        aliases=["wk"],
    )
    async def lastfm_whoknows(
        self,
        ctx: Context,
        *,
        artist: str = None,
    ):
        """View the top listeners for an artist"""

        username, config = await self.get_username(ctx)

        async with ctx.typing():
            if not artist:
                data = await self.request(
                    "/nowplaying",
                    payload=dict(
                        username=username,
                        simple=1,
                    ),
                )
                if not data:
                    return await ctx.error(
                        f"[**{username}**](https://last.fm/user/{format_uri(username)}) is not listening to anything right now"
                    )

                artist = data.get("artist")
            else:
                data = await self.request(
                    "/artist/search",
                    payload=dict(
                        username=username,
                        artist=artist,
                    ),
                )
                artist = data.get("name")

        data = [
            {
                "user": ctx.guild.get_member(row.get("user_id")),
                "username": row.get("username"),
                "url": f"https://last.fm/user/{format_uri(row.get('username'))}",
                "plays": row.get("plays"),
            }
            for row in await self.bot.db.fetch(
                "SELECT user_id, username, plays FROM lastfm_library.artists WHERE user_id = ANY($1::BIGINT[]) AND lower(artist) = $2 ORDER BY plays"
                " DESC",
                [member.id for member in ctx.guild.members],
                artist.lower(),
            )
            if (ctx.guild.get_member(row.get("user_id")) and row.get("plays") > 0)
        ]
        if not data:
            return await ctx.error(f"No one in this server knows **{artist}**")

        users = []
        new_crown = False
        for row in data:
            rank = len(users) + 1
            if rank == 1:
                rank = "👑"
                if len(data) > 1 and row.get("plays") > 5:
                    current_crown = await self.bot.db.fetchrow(
                        "SELECT * FROM lastfm_crowns WHERE guild_id = $1 AND artist = $2",
                        ctx.guild.id,
                        artist,
                    )
                    if not current_crown or row.get("plays") > current_crown.get(
                        "plays"
                    ):
                        await self.bot.db.execute(
                            "INSERT INTO lastfm_crowns (guild_id, user_id, username, artist, plays) VALUES ($1, $2, $3, $4, $5) ON CONFLICT"
                            " (guild_id, artist) DO UPDATE SET user_id = $2, username = $3, plays = $5",
                            ctx.guild.id,
                            row.get("user").id,
                            row.get("username"),
                            artist,
                            row.get("plays"),
                        )
                        if not current_crown:
                            new_crown = f"`{row.get('user')}` claimed the crown for **{artist}**!"
                        elif current_crown.get("user_id") != row.get("user").id:
                            new_crown = (
                                f"`{row.get('user')}` took the crown from"
                                f" `{self.bot.get_user(current_crown.get('user_id')) or current_crown.get('username')}` for **{artist}**!"
                            )
            else:
                rank = f"`{rank}`"

            users.append(
                f"{rank} **[{row.get('user')}]({row.get('url')})** has **{Plural(row.get('plays')):play}**"
            )

        embed = Embed(
            color=self.get_color(ctx, config),
            title=f"Top listeners for {artist}",
            description=users,
        )
        await ctx.paginate(embed, display_entries=False)
        if new_crown:
            await ctx.neutral(new_crown)

    @lastfm.command(
        name="wkalbum",
        usage="<artist> - <album>",
        example="Yung Lean - Starz",
        aliases=["wka", "whoknowsalbum"],
    )
    async def lastfm_whoknowsalbum(
        self,
        ctx: Context,
        *,
        album: str = None,
    ):
        """View the top listeners for an album"""

        username, config = await self.get_username(ctx)

        async with ctx.typing():
            if not album:
                data = await self.request(
                    "/nowplaying",
                    payload=dict(
                        username=username,
                        simple=1,
                    ),
                )
                if not data:
                    return await ctx.error(
                        f"[**{username}**](https://last.fm/user/{format_uri(username)}) is not listening to anything right now"
                    )
                if not data.get("album"):
                    return await ctx.error(
                        f"[**{username}**](https://last.fm/user/{format_uri(username)}) is not listening to an album right now"
                    )

                artist = data.get("artist")
                album = data.get("album")
            else:
                data = await self.request(
                    "/album/search",
                    payload=dict(
                        username=username,
                        album=album,
                    ),
                )

                artist = data.get("artist")
                album = data.get("name")

        data = [
            {
                "user": ctx.guild.get_member(row.get("user_id")),
                "username": row.get("username"),
                "url": f"https://last.fm/user/{format_uri(row.get('username'))}",
                "plays": row.get("plays"),
            }
            async for row in self.bot.db.fetchiter(
                "SELECT user_id, username, plays FROM lastfm_library.albums WHERE user_id = ANY($1::BIGINT[]) AND lower(artist) = $2 AND lower(album)"
                " = $3 ORDER BY plays DESC",
                [member.id for member in ctx.guild.members],
                artist.lower(),
                album.lower(),
            )
            if (ctx.guild.get_member(row.get("user_id")) and row.get("plays") > 0)
        ]

        if not data:
            return await ctx.error(f"No one in this server knows **{album}**")

        users = []
        for row in data:
            rank = len(users) + 1
            rank = f"`{rank}`"

            users.append(
                f"{rank} **[{row.get('user')}]({row.get('url')})** has **{Plural(row.get('plays')):play}**"
            )

        embed = Embed(
            color=self.get_color(ctx, config),
            title=f"Top listeners for {shorten(album)} by {shorten(artist)}",
            description=users,
        )
        await ctx.paginate(embed, display_entries=False)

    @lastfm.command(
        name="wktrack",
        usage="<artist> - <track>",
        example="Lil Tracy - R.I.P YUNG BRUH",
        aliases=["wkt", "whoknowstrack"],
    )
    async def lastfm_whoknowstrack(
        self,
        ctx: Context,
        *,
        track: str = None,
    ):
        """View the top listeners for a track"""

        username, config = await self.get_username(ctx)

        async with ctx.typing():
            if not track:
                data = await self.request(
                    "/nowplaying",
                    payload=dict(
                        username=username,
                        simple=1,
                    ),
                )
                if not data:
                    return await ctx.error(
                        f"[**{username}**](https://last.fm/user/{format_uri(username)}) is not listening to anything right now"
                    )

                artist = data.get("artist")
                track = data.get("name")
            else:
                data = await self.request(
                    "/track/search",
                    payload=dict(
                        username=username,
                        track=track,
                    ),
                )

                artist = data.get("artist")
                track = data.get("name")

        data = [
            {
                "user": ctx.guild.get_member(row.get("user_id")),
                "username": row.get("username"),
                "url": f"https://last.fm/user/{format_uri(row.get('username'))}",
                "plays": row.get("plays"),
            }
            for row in await self.bot.db.fetch(
                "SELECT user_id, username, plays FROM lastfm_library.tracks WHERE user_id = ANY($1::BIGINT[]) AND lower(artist) = $2 AND lower(track)"
                " = $3 ORDER BY plays DESC",
                [member.id for member in ctx.guild.members],
                artist.lower(),
                track.lower(),
            )
            if (ctx.guild.get_member(row.get("user_id")) and row.get("plays") > 0)
        ]

        if not data:
            return await ctx.error(
                f"No one in this server knows **{track}** by **{artist}**"
            )

        users = []
        for row in data:
            rank = len(users) + 1
            rank = f"`{rank}`"

            users.append(
                f"{rank} **[{row.get('user')}]({row.get('url')})** has **{Plural(row.get('plays')):play}**"
            )

        embed = Embed(
            color=self.get_color(ctx, config),
            title=f"Top listeners for {shorten(track)} by {shorten(artist)}",
            description=users,
        )
        await ctx.paginate(embed, display_entries=False)

    @lastfm.command(
        name="globalwhoknows",
        usage="<artist>",
        example="Lil Tracy",
        aliases=["globalwk", "gwk"],
    )
    @cooldown(1, 5, BucketType.member)
    async def lastfm_globalwhoknows(
        self,
        ctx: Context,
        *,
        artist: str = None,
    ):
        """View the top listeners for an artist globally"""

        username, config = await self.get_username(ctx)

        async with ctx.typing():
            if not artist:
                data = await self.request(
                    "/nowplaying",
                    payload=dict(
                        username=username,
                        simple=1,
                    ),
                )
                if not data:
                    return await ctx.error(
                        f"[**{username}**](https://last.fm/user/{format_uri(username)}) is not listening to anything right now"
                    )

                artist = data.get("artist")
            else:
                data = await self.request(
                    "/artist/search",
                    payload=dict(
                        username=username,
                        artist=artist,
                    ),
                )

                artist = data.get("name")

        data = [
            {
                "user": self.bot.get_user(row.get("user_id")),
                "username": row.get("username"),
                "url": f"https://last.fm/user/{format_uri(row.get('username'))}",
                "plays": row.get("plays"),
            }
            for row in await self.bot.db.fetch(
                "SELECT user_id, username, plays FROM lastfm_library.artists WHERE lower(artist) = $1 ORDER BY plays DESC",
                artist.lower(),
            )
            if (self.bot.get_user(row.get("user_id")) and row.get("plays") > 0)
        ]

        if not data:
            return await ctx.error(f"No one knows **{artist}**")

        users = []
        for row in data:
            rank = len(users) + 1
            rank = f"`{rank}`"

            users.append(
                f"{rank} **[{row.get('user')}]({row.get('url')})** has **{Plural(row.get('plays')):play}**"
            )

        embed = Embed(
            color=self.get_color(ctx, config),
            title=f"Top listeners for {artist}",
            description=users,
        )
        await ctx.paginate(embed, display_entries=False)

    @lastfm.command(
        name="globalwkalbum",
        usage="<artist> - <album>",
        example="Yung Lean - Starz",
        aliases=["globalwka", "gwka"],
    )
    @cooldown(1, 5, BucketType.member)
    async def lastfm_globalwkalbum(
        self,
        ctx: Context,
        *,
        album: str = None,
    ):
        """View the top listeners for an album globally"""

        username, config = await self.get_username(ctx)

        async with ctx.typing():
            if not album:
                data = await self.request(
                    "/nowplaying",
                    payload=dict(
                        username=username,
                        simple=1,
                    ),
                )
                if not data:
                    return await ctx.error(
                        f"[**{username}**](https://last.fm/user/{format_uri(username)}) is not listening to anything right now"
                    )

                artist = data.get("artist")
                album = data.get("album")
                if not album:
                    return await ctx.error(
                        f"No album is featured on **{data.get('name')}** by **{data.get('artist')}**"
                    )
            else:
                data = await self.request(
                    "/album/search",
                    payload=dict(
                        username=username,
                        album=album,
                    ),
                )

                artist = data.get("artist")
                album = data.get("name")

        data = [
            {
                "user": self.bot.get_user(row.get("user_id")),
                "username": row.get("username"),
                "url": f"https://last.fm/user/{format_uri(row.get('username'))}",
                "plays": row.get("plays"),
            }
            for row in await self.bot.db.fetch(
                "SELECT user_id, username, plays FROM lastfm_library.albums WHERE lower(album) = $1 AND lower(artist) = $2 ORDER BY plays DESC",
                album.lower(),
                artist.lower(),
            )
            if (self.bot.get_user(row.get("user_id")) and row.get("plays") > 0)
        ]

        if not data:
            return await ctx.error(f"No one knows **{album}** by **{artist}**")

        users = []
        for row in data:
            rank = len(users) + 1
            rank = f"`{rank}`"

            users.append(
                f"{rank} **[{row.get('user')}]({row.get('url')})** has **{Plural(row.get('plays')):play}**"
            )

        embed = Embed(
            color=self.get_color(ctx, config),
            title=f"Top listeners for {shorten(album)} by {shorten(artist)}",
            description=users,
        )
        await ctx.paginate(embed, display_entries=False)

    @lastfm.command(
        name="globalwktrack",
        usage="<artist> - <track>",
        example="Lil Tracy - R.I.P YUNG BRUH",
        aliases=["globalwkt", "gwkt"],
    )
    @cooldown(1, 5, BucketType.member)
    async def lastfm_globalwktrack(
        self,
        ctx: Context,
        *,
        track: str = None,
    ):
        """View the top listeners for a track globally"""

        username, config = await self.get_username(ctx)

        async with ctx.typing():
            if not track:
                data = await self.request(
                    "/nowplaying",
                    payload=dict(
                        username=username,
                        simple=1,
                    ),
                )
                if not data:
                    return await ctx.error(
                        f"[**{username}**](https://last.fm/user/{format_uri(username)}) is not listening to anything right now"
                    )

                artist = data.get("artist")
                track = data.get("name")
            else:
                data = await self.request(
                    "/track/search",
                    payload=dict(
                        username=username,
                        track=track,
                    ),
                )

                artist = data.get("artist")
                track = data.get("name")

        data = [
            {
                "user": self.bot.get_user(row.get("user_id")),
                "username": row.get("username"),
                "url": f"https://last.fm/user/{format_uri(row.get('username'))}",
                "plays": row.get("plays"),
            }
            for row in await self.bot.db.fetch(
                "SELECT user_id, username, plays FROM lastfm_library.tracks WHERE lower(track) = $1 AND lower(artist) = $2 ORDER BY plays DESC",
                track.lower(),
                artist.lower(),
            )
            if (self.bot.get_user(row.get("user_id")) and row.get("plays") > 0)
        ]

        if not data:
            return await ctx.error(f"No one knows **{track}** by **{artist}**")

        users = []
        for row in data:
            rank = len(users) + 1
            rank = f"`{rank}`"

            users.append(
                f"{rank} **[{row.get('user')}]({row.get('url')})** has ****{Plural(row.get('plays')):play}****"
            )

        embed = Embed(
            color=self.get_color(ctx, config),
            title=f"Top listeners for {shorten(track)} by {shorten(artist)}",
            description=users,
        )
        await ctx.paginate(embed, display_entries=False)

    @lastfm.command(
        name="mostcrowns",
        aliases=["allcrowns", "crownsall", "crownslb", "crownstop"],
    )
    async def lastfm_mostcrowns(self, ctx: Context):
        """View the highest crown holders"""

        username, config = await self.get_username(ctx)

        async with ctx.typing():
            users = [
                f"[**{ctx.guild.get_member(row.get('user_id'))}**](https://last.fm/user/{format_uri(row.get('username'))})"
                f" ({Plural(row.get('crowns')):crown})"
                for row in await self.bot.db.fetch(
                    "SELECT user_id, username, COUNT(*) AS crowns FROM lastfm_crowns WHERE guild_id = $1 GROUP BY user_id, username ORDER BY crowns"
                    " DESC",
                    ctx.guild.id,
                )
                if ctx.guild.get_member(row.get("user_id"))
            ]
            if not users:
                return await ctx.error("No one has any crowns")

        await ctx.paginate(
            Embed(
                color=self.get_color(ctx, config),
                title="Highest crown holders",
                description=users,
            )
        )

    @lastfm.command(
        name="recommendation",
        usage="<member>",
        example="caden",
        aliases=["recommend", "rec"],
    )
    async def lastfm_recommendation(self, ctx: Context, *, member: Member = None):
        """Recommend a random artist from your library"""

        member = member or ctx.author
        username, config = await self.get_username(ctx, member)

        async with ctx.typing():
            artists = await self.bot.db.fetch(
                "SELECT * FROM lastfm_library.artists WHERE user_id = $1 ORDER BY plays",
                member.id,
            )
            if not artists:
                return await ctx.error(
                    f"You don't have any **artists** in your library\n> Use `{ctx.prefix}lastfm update` to refresh your library"
                    if member == ctx.author
                    else f"**{member}** doesn't have any **artists** in their library"
                )

        artist = choice(artists)
        await ctx.neutral(
            f"I recommend [**{artist['artist']}**](https://last.fm/music/{format_uri(artist['artist'])})"
            f" ({Plural(artist['plays']):play})"
            + (f" to **{member}**" if member != ctx.author else ""),
            color=self.get_color(ctx, config),
            emoji="🎵",
        )

    @lastfm.command(
        name="compare",
        usage="(member)",
        example="caden",
        aliases=["taste", "mutual", "match"],
    )
    async def lastfm_compare(self, ctx: Context, *, member: Member):
        """Compare your top artists with another member"""

        if member == ctx.author:
            return await ctx.error("You can't **compare** with yourself")

        username, config = await self.get_username(ctx)
        target_username, target_config = await self.get_username(ctx, member)

        async with ctx.typing():
            artists = await self.bot.db.fetch(
                "SELECT * FROM lastfm_library.artists WHERE user_id = $1 ORDER BY plays",
                ctx.author.id,
            )
            target_artists = await self.bot.db.fetch(
                "SELECT * FROM lastfm_library.artists WHERE user_id = $1 ORDER BY plays",
                member.id,
            )

        if not artists:
            return await ctx.error(
                f"You don't have any **artists** in your library\n> Use `{ctx.prefix}lastfm update` to refresh your library"
            )
        if not target_artists:
            return await ctx.error(
                f"**{member}** doesn't have any **artists** in their library"
            )

        mutual_artists = list()
        for artist in sorted(artists, key=lambda artist: artist["plays"], reverse=True):
            for target_artist in target_artists:
                if artist["artist"] == target_artist["artist"]:
                    mutual_artists.append(
                        f"{shorten(artist['artist'])}{' ' * (21 - len(shorten(artist['artist'])))} {artist['plays']} {'=' if artist['plays'] == target_artist['plays'] else '>' if artist['plays'] > target_artist['plays'] else '<'} {target_artist['plays']}"
                    )

        if not mutual_artists:
            return await ctx.error(
                f"You and **{member}** don't have any **mutual artists**"
            )
        largest_library = (
            artists if len(artists) > len(target_artists) else target_artists
        )

        embed = Embed(
            color=self.get_color(ctx, config),
            title=f"{username} - {target_username}",
            description=(
                "You both have"
                f" **{Plural(mutual_artists):artist}** ({percentage(len(mutual_artists), len(largest_library))}) in"
                " common\n>>> ```\n"
                + "\n".join(artist for artist in mutual_artists[:10])
                + "```"
            ),
        )
        await ctx.send(embed=embed)

    @lastfm.command(
        name="plays",
        usage="<member> <artist>",
        example="caden Lil Tracy",
    )
    async def lastfm_plays(
        self,
        ctx: Context,
        member: Optional[MemberStrict] = None,
        *,
        artist: str = None,
    ):
        """Check how many plays you have for an artist"""

        member = member or ctx.author
        username, config = await self.get_username(ctx, member)

        async with ctx.typing():
            if not artist:
                data = await self.request(
                    "/nowplaying",
                    payload=dict(
                        username=username,
                        simple=1,
                    ),
                )
                if not data:
                    return await ctx.error(
                        f"[**{username}**](https://last.fm/user/{format_uri(username)}) is not listening to anything right now"
                    )

                artist = data.get("artist")

            data = await self.request(
                "/artist/search",
                payload=dict(
                    username=username,
                    artist=artist,
                ),
            )

        await ctx.neutral(
            f"You have **{Plural(data.get('plays')):play}** for **{data.get('name')}**"
            if ctx.author == member
            else f"**{member}** has **{Plural(data.get('plays')):play}** for **{data.get('name')}**",
            emoji="🎵",
            color=self.get_color(ctx, config),
        )

        await self.bot.db.execute(
            "INSERT INTO lastfm_library.artists (user_id, username, artist, plays) VALUES($1, $2, $3, $4) ON CONFLICT (user_id, artist) DO UPDATE"
            " SET plays = $4",
            member.id,
            username,
            data.get("name"),
            data.get("plays"),
        )

    @lastfm.command(
        name="playstrack",
        usage="<member> <artist> - <track>",
        example="caden Lil Tracy - R.I.P YUNG BRUH",
        aliases=["playst", "tplays"],
    )
    async def lastfm_playstrack(
        self,
        ctx: Context,
        member: Optional[MemberStrict] = None,
        *,
        track: str = None,
    ):
        """Check how many plays you have for a track"""

        member = member or ctx.author
        username, config = await self.get_username(ctx, member)

        async with ctx.typing():
            if not track:
                data = await self.request(
                    "/nowplaying",
                    payload=dict(
                        username=username,
                        simple=1,
                    ),
                )
                if not data:
                    return await ctx.error(
                        f"[**{username}**](https://last.fm/user/{format_uri(username)}) is not listening to anything right now"
                    )

                track = data.get("artist") + " - " + data.get("name")

            data = await self.request(
                "/track/search",
                payload=dict(
                    username=username,
                    track=track,
                ),
            )

        await ctx.neutral(
            f"You have **{Plural(data.get('plays')):play}** for **{data.get('name')}** by **{data.get('artist')}**"
            if ctx.author == member
            else f"**{member}** has **{Plural(data.get('plays')):play}** for **{data.get('name')}** by **{data.get('artist')}**",
            emoji="🎵",
            color=self.get_color(ctx, config),
        )

        await self.bot.db.execute(
            "INSERT INTO lastfm_library.tracks (user_id, username, artist, track, plays) VALUES($1, $2, $3, $4, $5) ON CONFLICT (user_id, artist,"
            " track) DO UPDATE SET plays = $5",
            member.id,
            username,
            data.get("artist"),
            data.get("name"),
            data.get("plays"),
        )

    @lastfm.command(
        name="playsalbum",
        usage="<member> <artist> - <album>",
        example="caden Yung Lean - Starz",
        aliases=["playsa", "aplays"],
    )
    async def lastfm_playsalbum(
        self,
        ctx: Context,
        member: Optional[MemberStrict] = None,
        *,
        album: str = None,
    ):
        """Check how many plays you have for an album"""

        member = member or ctx.author
        username, config = await self.get_username(ctx, member)

        async with ctx.typing():
            if not album:
                data = await self.request(
                    "/nowplaying",
                    payload=dict(
                        username=username,
                        simple=1,
                    ),
                )
                if not data:
                    return await ctx.error(
                        f"[**{username}**](https://last.fm/user/{format_uri(username)}) is not listening to anything right now"
                    )
                if not data.get("album"):
                    return await ctx.error(
                        f"[**{username}**](https://last.fm/user/{format_uri(username)}) is not listening to an album right now"
                    )

                album = data.get("artist") + " - " + data.get("album")

            data = await self.request(
                "/album/search",
                payload=dict(
                    username=username,
                    album=album,
                ),
            )

        await ctx.neutral(
            f"You have **{Plural(data.get('plays')):play}** for **{data.get('name')}** by **{data.get('artist')}**"
            if ctx.author == member
            else f"**{member}** has **{Plural(data.get('plays')):play}** for **{data.get('name')}** by **{data.get('artist')}**",
            emoji="🎵",
            color=self.get_color(ctx, config),
        )

        await self.bot.db.execute(
            "INSERT INTO lastfm_library.albums (user_id, username, artist, album, plays) VALUES($1, $2, $3, $4, $5) ON CONFLICT (user_id, artist,"
            " album) DO UPDATE SET plays = $5",
            member.id,
            username,
            data.get("artist"),
            data.get("name"),
            data.get("plays"),
        )

    @lastfm.command(
        name="collage",
        usage="<member> <size> <period>",
        example="caden 3x3 weekly",
        aliases=["chart", "col", "art"],
    )
    @max_concurrency(1, BucketType.member)
    async def lastfm_collage(
        self,
        ctx: Context,
        member: Optional[MemberStrict] = None,
        size: Optional[ChartSize] = "3x3",
        period: str = "overall",
    ):
        """View a collage of your most listened to albums"""

        username, config = await self.get_username(ctx, member)

        async with ctx.typing():
            data = await self.request(
                "/collage",
                payload=dict(
                    username=username,
                    size=size,
                    period=period,
                ),
            )

        if not data:
            return await ctx.error(
                f"Couldn't generate collage for [**{username}**](https://last.fm/user/{format_uri(username)})"
            )

        embed = Embed(
            color=self.get_color(ctx, config),
            title=f"{username}'s {data['period']} album collage",
        )

        embed.set_image(url=data["url"])
        await ctx.reply(embed=embed)

    @lastfm.command(
        name="topartists",
        usage="<member> <period>",
        example="caden monthly",
        aliases=["topartist", "artists", "artist", "tar", "ta"],
    )
    async def lastfm_topartists(
        self,
        ctx: Context,
        member: Optional[MemberStrict] = None,
        *,
        period: str = "overall",
    ):
        """View your most listened to artists"""

        username, config = await self.get_username(ctx, member)

        async with ctx.typing():
            data = await self.request(
                "/topartists",
                payload=dict(
                    username=username,
                    period=period,
                ),
            )
            if not data["artists"]:
                return await ctx.error(
                    f"[**{username}**](https://last.fm/user/{format_uri(username)}) doesn't have any **top artists**"
                )

        embed = Embed(
            color=self.get_color(ctx, config),
            title=f"{username}'s {data['period']} top artists",
            description=list(
                f"[**{shorten(artist.get('name'))}**]({artist.get('url')}) ({Plural(artist.get('plays')):play})"
                for artist in data["artists"]
            ),
        )
        await ctx.paginate(embed)

    @lastfm.command(
        name="topalbums",
        usage="<member> <period>",
        example="caden monthly",
        aliases=["topalbum", "albums", "album", "tab", "tl"],
    )
    async def lastfm_topalbums(
        self,
        ctx: Context,
        member: Optional[MemberStrict] = None,
        *,
        period: str = "overall",
    ):
        """View your most listened to albums"""

        member = member or ctx.author
        username, config = await self.get_username(ctx, member)

        ()
        data = await self.request(
            "/topalbums",
            payload=dict(
                username=username,
                period=period,
            ),
        )
        if not data["albums"]:
            return await ctx.error(
                f"[**{username}**](https://last.fm/user/{format_uri(username)}) doesn't have any **top albums**"
            )

        embed = Embed(
            color=self.get_color(ctx, config),
            title=f"{username}'s {data['period']} top albums",
            description=list(
                f"[**{shorten(album.get('name'))}**]({album.get('url')}) by **{album['artist'].get('name')}**"
                f" ({Plural(album.get('plays')):play})"
                for album in data["albums"]
            ),
        )
        await ctx.paginate(embed)

    @lastfm.command(
        name="toptracks",
        usage="<member> <period>",
        example="caden monthly",
        aliases=["toptrack", "tracks", "track", "ttr", "tt"],
    )
    async def lastfm_toptracks(
        self,
        ctx: Context,
        member: Optional[MemberStrict] = None,
        *,
        period: str = "overall",
    ):
        """View your most listened to tracks"""

        member = member or ctx.author
        username, config = await self.get_username(ctx, member)

        async with ctx.typing():
            data = await self.request(
                "/toptracks",
                payload=dict(
                    username=username,
                    period=period,
                ),
            )
            if not data["tracks"]:
                return await ctx.error(
                    f"[**{username}**](https://last.fm/user/{format_uri(username)}) doesn't have any **top tracks**"
                )

        embed = Embed(
            color=self.get_color(ctx, config),
            title=f"{username}'s {data['period']} top tracks",
            description=list(
                f"[**{shorten(track.get('name'))}**]({track.get('url')}) by **{track['artist'].get('name')}**"
                f" ({Plural(track.get('plays')):play})"
                for track in data["tracks"]
            ),
        )
        await ctx.paginate(embed)

    @lastfm.command(
        name="toptenalbums",
        usage="<member> <artist>",
        example="caden Lil Tracy",
        aliases=["tta"],
    )
    async def lastfm_toptenalbums(
        self,
        ctx: Context,
        member: Optional[MemberStrict] = None,
        *,
        artist: str = None,
    ):
        """View your top albums for an artist"""

        member = member or ctx.author
        username, config = await self.get_username(ctx, member)

        async with ctx.typing():
            if not artist:
                data = await self.request(
                    "/nowplaying",
                    payload=dict(
                        username=username,
                        simple=1,
                    ),
                )
                if not data:
                    return await ctx.error(
                        f"[**{username}**](https://last.fm/user/{format_uri(username)}) is not listening to anything right now"
                    )

                artist = data.get("artist")
            else:
                data = await self.request(
                    "/artist/search",
                    payload=dict(
                        username=username,
                        artist=artist,
                    ),
                )
                artist = data.get("name")

        albums = await self.bot.db.fetch(
            "SELECT album AS name, plays FROM lastfm_library.albums WHERE user_id = $1 AND artist = $2 ORDER BY plays DESC LIMIT 10",
            member.id,
            artist,
        )
        if not albums:
            return await ctx.error(
                f"You don't have any **albums** in your library for **{artist}**\n> Use `{ctx.prefix}lastfm update` to refresh your library"
                if member == ctx.author
                else f"**{member}** doesn't have any **albums** in their library for **{artist}**"
            )

        embed = Embed(
            color=self.get_color(ctx, config),
            title=f"{username}'s top ten albums for {artist}",
            description=list(
                f"[**{shorten(album.get('name'))}**](https://last.fm/music/{format_uri(artist)}/{format_uri(album.get('name'))})"
                f" ({Plural(album.get('plays')):play})"
                for album in albums
            ),
        )
        await ctx.paginate(embed)

    @lastfm.command(
        name="toptentracks",
        usage="<member> <artist>",
        example="caden Lil Tracy",
        aliases=["ttt"],
    )
    async def lastfm_toptentracks(
        self,
        ctx: Context,
        member: Optional[MemberStrict] = None,
        *,
        artist: str = None,
    ):
        """View your top tracks for an artist"""

        member = member or ctx.author
        username, config = await self.get_username(ctx, member)

        async with ctx.typing():
            if not artist:
                data = await self.request(
                    "/nowplaying",
                    payload=dict(
                        username=username,
                        simple=1,
                    ),
                )
                if not data:
                    return await ctx.error(
                        f"[**{username}**](https://last.fm/user/{format_uri(username)}) is not listening to anything right now"
                    )

                artist = data.get("artist")
            else:
                data = await self.request(
                    "/artist/search",
                    payload=dict(
                        username=username,
                        artist=artist,
                    ),
                )
                artist = data.get("name")

        tracks = await self.bot.db.fetch(
            "SELECT track AS name, plays FROM lastfm_library.tracks WHERE user_id = $1 AND artist = $2 ORDER BY plays DESC LIMIT 10",
            member.id,
            artist,
        )
        if not tracks:
            return await ctx.error(
                f"You don't have any **tracks** in your library for **{artist}**\n> Use `{ctx.prefix}lastfm update` to refresh your library"
                if member == ctx.author
                else f"**{member}** doesn't have any **tracks** in their library for **{artist}**"
            )

        embed = Embed(
            color=self.get_color(ctx, config),
            title=f"{username}'s top ten tracks for {artist}",
            description=list(
                f"[**{shorten(track.get('name'))}**](https://last.fm/music/{format_uri(artist)}/_/{format_uri(track.get('name'))})"
                f" ({Plural(track.get('plays')):play})"
                for track in tracks
            ),
        )
        await ctx.paginate(embed)

    @lastfm.command(
        name="overview",
        usage="<member> <artist>",
        example="caden Lil Tracy",
        aliases=["ov"],
    )
    async def lastfm_overview(
        self,
        ctx: Context,
        member: Optional[MemberStrict] = None,
        *,
        artist: str = None,
    ):
        """View your statistics for an artist"""

        member = member or ctx.author
        username, config = await self.get_username(ctx, member)

        async with ctx.typing():
            if not artist:
                data = await self.request(
                    "/nowplaying",
                    payload=dict(
                        username=username,
                        simple=1,
                    ),
                )
                if not data:
                    return await ctx.error(
                        f"[**{username}**](https://last.fm/user/{format_uri(username)}) is not listening to anything right now"
                    )

                artist = data.get("artist")

            artist = await self.request(
                "/artist/search",
                payload=dict(
                    username=username,
                    artist=artist,
                ),
            )
            if not artist.get("plays"):
                return await ctx.error(
                    f"You've never listened to **{artist.get('name')}**"
                    if member == ctx.author
                    else f"**{member}** has never listened to **{artist.get('name')}**"
                )

        albums = await self.bot.db.fetch(
            "SELECT ROW_NUMBER() OVER(ORDER BY plays DESC) AS index, album AS name, plays FROM lastfm_library.albums WHERE user_id = $1 AND artist ="
            " $2 ORDER BY plays DESC",
            member.id,
            artist.get("name"),
        )
        tracks = await self.bot.db.fetch(
            "SELECT ROW_NUMBER() OVER(ORDER BY plays DESC) AS index, track AS name, plays FROM lastfm_library.tracks WHERE user_id = $1 AND artist ="
            " $2 ORDER BY plays DESC",
            member.id,
            artist.get("name"),
        )

        embed = Embed(
            color=self.get_color(ctx, config),
            title=f"{username}'s overview for {artist.get('name')}",
            description=f"You have **{Plural(artist.get('plays')):play}** for [**{artist.get('name')}**]({artist.get('url')})",
        )

        if albums:
            embed.add_field(
                name=f"Albums ({len(albums)})",
                value="\n".join(
                    f"`{album.get('index')}`"
                    f" [**{shorten(album.get('name'), 16)}**](https://last.fm/music/{format_uri(artist.get('name'))}/{format_uri(album.get('name'))})"
                    f" ({Plural(album.get('plays')):play})"
                    for album in sorted(
                        albums, key=lambda album: album["plays"], reverse=True
                    )[:5]
                ),
            )
        if tracks:
            embed.add_field(
                name=f"Tracks ({len(tracks)})",
                value="\n".join(
                    f"`{track.get('index')}`"
                    f" [**{shorten(track.get('name'), 16)}**](https://last.fm/music/{format_uri(artist.get('name'))}/_/{format_uri(track.get('name'))})"
                    f" ({Plural(track.get('plays')):play})"
                    for track in sorted(
                        tracks, key=lambda track: track["plays"], reverse=True
                    )[:5]
                ),
            )
        embed.set_thumbnail(url=artist.get("image"))
        await ctx.send(embed=embed)

    @lastfm.command(
        name="reactions",
        usage="(upvote emoji) (downvote emoji)",
        example="🔥 🗑️",
        aliases=["reaction", "react", "cr"],
    )
    async def lastfm_reactions(
        self,
        ctx: Context,
        upvote: str,
        downvote: str = None,
    ):
        """Set custom reactions for Last.fm now playing"""

        username, config = await self.get_username(ctx)

        if upvote in (
            "disable",
            "none",
            "off",
        ):
            config.update(
                {
                    "reactions": False,
                }
            )
        else:
            if not downvote:
                return await ctx.send_help()

            try:
                await ctx.message.add_reaction(upvote)
                await ctx.message.add_reaction(downvote)
            except HTTPException:
                return await ctx.error(
                    "Invalid **emoji** provided for `upvote` or `downvote`"
                )

            config.update(
                {
                    "reactions": {
                        "upvote": upvote,
                        "downvote": downvote,
                    }
                }
            )

        await self.bot.db.execute(
            "UPDATE lastfm SET config = $2 WHERE user_id = $1", ctx.author.id, config
        )
        if config.get("reactions"):
            return await ctx.approve(
                f"Your **reactions** have been set to **{upvote}** and **{downvote}**"
            )

        return await ctx.approve("Your **reactions** have been **disabled**")

    @lastfm.command(
        name="favorites",
        usage="<member>",
        example="caden",
        aliases=["favs", "fav", "likes", "liked", "loved"],
    )
    async def lastfm_favorites(
        self,
        ctx: Context,
        *,
        member: Member | str = None,
    ):
        """View your favorite tracks"""

        username, config = await self.get_username(ctx, member)

        async with ctx.typing():
            data = await self.request(
                "/favorites",
                payload=dict(
                    username=username,
                    limit=100,
                ),
            )
            if not data["tracks"]:
                return await ctx.error(
                    f"[**{username}**](https://last.fm/user/{format_uri(username)}) doesn't have any **favorite tracks**"
                )

        await ctx.paginate(
            Embed(
                color=self.get_color(ctx, config),
                title=f"{username}'s favorite tracks",
                description=list(
                    f"[**{shorten(track.get('name'))}**]({track.get('url')}) by **{track['artist'].get('name')}**"
                    f" ({format_dt(datetime.fromtimestamp(track.get('date')), style='R')})"
                    for track in data["tracks"]
                ),
            )
        )

    @lastfm.command(
        name="recent",
        usage="<member>",
        example="caden",
        aliases=["recenttracks", "last", "lp"],
    )
    async def lastfm_recent(self, ctx: Context, *, member: Member | str = None):
        """View your recent tracks"""

        username, config = await self.get_username(ctx, member)

        async with ctx.typing():
            data = await self.request(
                "/recenttracks",
                payload=dict(
                    username=username,
                ),
            )
        if not data:
            return await ctx.error(
                f"[**{username}**](https://last.fm/user/{URL(username)}) hasn't listened to anything recently"
            )

        embed = Embed(
            color=self.get_color(ctx, config),
            title=f"{username}'s recent tracks",
            description=list(
                f"[**{shorten(track.get('name'))}**]({track.get('url')}) by **{track['artist'].get('name')}**"
                for track in data
            ),
        )
        await ctx.paginate(embed)
