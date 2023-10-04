import logging

from asyncio import Queue, TimeoutError
from contextlib import suppress
from typing import Literal, Optional

from async_timeout import timeout
from discord import (
    Attachment,
    Client,
    File,
    HTTPException,
    Member,
    Message,
    TextChannel,
    VoiceChannel,
    VoiceState,
)
from discord.ext.commands import CommandError, command
from pomice import NodePool, NoNodesAvailable
from pomice import Player as BasePlayer
from pomice import Playlist, Track

import config
from tools.converters.basic import Percentage, Position
from tools.managers.cog import Cog
from tools.managers.context import Context
from tools.utilities.text import Plural


class Player(BasePlayer):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.bound_channel: TextChannel = None
        self.message: Message = None
        self.track: Track = None
        self.queue: Queue = Queue()
        self.waiting: bool = False
        self.loop: str = False

    async def play(self, track: Track):
        await super().play(track)

    async def insert(self, track: Track, filter: bool = True, bump: bool = False):
        if filter and track.info.get("sourceName", "Spotify") == "youtube":
            response = await self.bot.session.get(
                "https://metadata-filter.vercel.app/api/youtube",
                params=dict(track=track.title),
            )
            data = await response.json()

            if data.get("status") == "success":
                track.title = data["data"].get("track")

        if bump:
            queue = self.queue._queue
            queue.insert(0, track)
        else:
            await self.queue.put(track)

        return True

    async def next_track(self, ignore_playing: bool = False):
        if not ignore_playing:
            if self.is_playing or self.waiting:
                return

        self.waiting = True
        if self.loop == "track" and self.track:
            track = self.track
        else:
            try:
                with timeout(300):
                    track = await self.queue.get()
                    if self.loop == "queue":
                        await self.queue.put(track)
            except TimeoutError:
                return await self.teardown()

        await self.play(track)
        self.track = track
        self.waiting = False
        if self.bound_channel and self.loop != "track":
            try:
                if self.message:
                    async for message in self.bound_channel.history(limit=15):
                        if message.id == self.message.id:
                            with suppress(HTTPException):
                                await message.delete()
                            break

                self.message = await track.ctx.neutral(
                    f"Now playing [**{track.title}**]({track.uri})"
                )
            except:
                self.bound_channel = None

        return track

    async def skip(self):
        if self.is_paused:
            await self.set_pause(False)

        return await self.stop()

    async def set_loop(self, state: str):
        self.loop = state

    async def teardown(self):
        try:
            self.queue._queue.clear()
            await self.reset_filters()
            await self.destroy()
        except:
            pass


logger = logging.getLogger(__name__)


class Music(Cog):
    """Cog for Music commands."""

    @Cog.listener()
    async def on_pomice_track_end(self, player: Player, track: Track, reason: str):
        await player.next_track()

    async def cog_load(self) -> None:
        if not hasattr(self.bot, "node") and hasattr(config, "Lavalink"):
            try:
                self.bot.node = await NodePool().create_node(
                    bot=self.bot,
                    identifier="lain",
                    host=config.Lavalink.host,
                    port=config.Lavalink.port,
                    password=config.Lavalink.password,
                    spotify_client_id=config.Authorization.Spotify.client_id,
                    spotify_client_secret=config.Authorization.Spotify.client_secret,
                    log_handler=logger,
                )
            except Exception as error:
                print("Failed to connect to the Lavalink node with error:", error)

    @Cog.listener()
    async def on_voice_state_update(
        self,
        member: Member,
        before: VoiceState,
        after: VoiceState,
    ):
        if member.id != self.bot.user.id:
            return

        if (
            not hasattr(self.bot, "node")
            or (player := self.bot.node.get_player(member.guild.id)) is None
        ):
            return

        if not after.channel:
            await player.destroy()

    async def get_player(self, ctx: Context, *, connect: bool = True):
        if not hasattr(self.bot, "node"):
            raise CommandError("The **Lavalink** node hasn't been **initialized** yet")

        if not ctx.author.voice:
            raise CommandError("You're not **connected** to a voice channel")

        if (
            ctx.guild.me.voice
            and ctx.guild.me.voice.channel != ctx.author.voice.channel
        ):
            raise CommandError("I'm **already** connected to another voice channel")

        if (
            player := self.bot.node.get_player(ctx.guild.id)
        ) is None or not ctx.guild.me.voice:
            if not connect:
                raise CommandError("I'm not **connected** to a voice channel")
            else:
                await ctx.author.voice.channel.connect(cls=Player, self_deaf=True)
                player = self.bot.node.get_player(ctx.guild.id)
                player.bound_channel = ctx.channel
                await player.set_volume(65)

        return player

    @command(
        name="play",
        usage="(query)",
        example="Penthouse Shordy",
        parameters={
            "bump": {
                "require_value": False,
                "description": "Bump the track to the front of the queue",
                "aliases": ["b", "next"],
            }
        },
        aliases=["queue", "p", "q"],
    )
    async def play(self: "Music", ctx: Context, *, query: str):
        """Queue a track."""

        if not query:
            raise CommandError("Please **provide** a query")

        player: Player = await self.get_player(ctx, connect=True)

        try:
            result: list[Track] | Playlist = await player.get_tracks(
                query=query, ctx=ctx
            )
        except Exception as error:
            return await ctx.error("No **results** were found")

        if not result:
            return await ctx.error("No **results** were found")

        if isinstance(result, Playlist):
            for track in result.tracks:
                await player.insert(
                    track, filter=False, bump=ctx.parameters.get("bump")
                )

            return await ctx.neutral(
                f"Added **{Plural(result.track_count):track}** from [**{result.name}**]({result.uri}) to the queue",
            )

        await player.insert(result[0], bump=ctx.parameters.get("bump"))
        if player.is_playing:
            return await ctx.neutral(
                f"Added [**{result[0].title}**]({result[0].uri}) to the queue"
            )

        if not player.is_playing:
            await player.next_track()

        if bound_channel := player.bound_channel:
            if bound_channel != ctx.channel:
                with suppress(HTTPException):
                    await ctx.react_check()

    @command(name="disconnect", aliases=["dc", "stop"])
    async def disconnect(self: "Music", ctx: Context):
        """Disconnect the music player"""

        player: Player = await self.get_player(ctx, connect=False)

        await player.teardown()
        return await ctx.message.add_reaction("👋🏾")

    @command(name="pause")
    async def pause(self: "Music", ctx: Context):
        """Pause the current track"""

        player: Player = await self.get_player(ctx, connect=False)

        if player.is_playing and not player.is_paused:
            await ctx.message.add_reaction("⏸️")
            return await player.set_pause(True)

        return await ctx.error("There isn't an active **track**")

    @command(name="resume", aliases=["rsm"])
    async def resume(self: "Music", ctx: Context):
        """Resume the current track"""

        player: Player = await self.get_player(ctx, connect=False)

        if player.is_playing and player.is_paused:
            await ctx.message.add_reaction("✅")
            return await player.set_pause(False)

        return await ctx.error("There isn't an active **track**")

    @command(
        name="volume",
        usage="<percentage>",
        example="75",
        aliases=["vol", "v"],
    )
    async def volume(self, ctx: Context, percentage: Percentage = None):
        """Set the player volume"""

        player: Player = await self.get_player(ctx, connect=False)

        if percentage is None:
            return await ctx.neutral(f"Current volume: `{player.volume}%`")

        if not 0 <= percentage <= 100:
            return await ctx.error("Please **provide** a **valid** percentage")

        await player.set_volume(percentage)
        await ctx.approve(f"Set **volume** to `{percentage}%`")

    @command(name="skip", aliases=["next", "sk"])
    async def skip(self, ctx: Context):
        """Skip the current track"""

        player: Player = await self.get_player(ctx, connect=False)

        if player.is_playing:
            await ctx.message.add_reaction("⏭️")
            return await player.skip()

        return await ctx.error("There isn't an active **track**")

    @command(
        name="seek",
        usage="(position)",
        example="+30s",
        aliases=[
            "ff",
            "rw",
        ],
    )
    async def seek(self, ctx: Context, position: Position) -> None:
        """
        Seek to a specific position
        """

        player: Player = await self.get_player(ctx)

        if not player.current:
            return await ctx.error("Nothing is **currently** playing!")

        await player.seek(max(0, min(position, player.current.length)))
        await ctx.message.add_reaction("✅")

    @command(
        name="loop",
        usage="(track, queue, or off)",
        example="queue",
        aliases=["repeat", "lp"],
    )
    async def loop(self, ctx: Context, option: Literal["track", "queue", "off"]):
        """Toggle looping for the current track or queue"""

        player: Player = await self.get_player(ctx, connect=False)

        if option == "off":
            if not player.loop:
                return await ctx.error("There isn't an active **loop**")
        elif option == "track":
            if not player.is_playing:
                return await ctx.error("There isn't an active **track**")
        elif option == "queue":
            if not player.queue._queue:
                return await ctx.error("There aren't any **tracks** in the queue")

        await ctx.message.add_reaction(
            "✅" if option == "off" else "🔂" if option == "track" else "🔁"
        )
        await player.set_loop(option if option != "off" else False)

    @command(
        name="remove",
        usage="(index)",
        example="3",
        aliases=["rmv"],
    )
    async def remove(self, ctx: Context, track: int):
        """Remove a track from the queue"""

        player: Player = await self.get_player(ctx, connect=False)
        queue = player.queue._queue

        if track < 1 or track > len(queue):
            return await ctx.error(
                f"Track position `{track}` is invalid (`1`/`{len(queue)}`)"
            )

        _track = queue[track - 1]
        del queue[track - 1]
        await ctx.approve(f"Removed [**{_track.title}**]({_track.uri}) from the queue")

    @command(
        name="move",
        usage="(from) (to)",
        example="6 2",
        aliases=["mv"],
    )
    async def move(self, ctx: Context, track: int, to: int):
        """Move a track to a different position"""

        player: Player = await self.get_player(ctx, connect=False)
        queue = player.queue._queue

        if track == to:
            return await ctx.error(f"Track position `{track}` is invalid")
        try:
            queue[track - 1]
            queue[to - 1]
        except IndexError:
            return await ctx.error(
                f"Track position `{track}` is invalid (`1`/`{len(queue)}`)"
            )

        _track = queue[track - 1]
        del queue[track - 1]
        queue.insert(to - 1, _track)
        await ctx.approve(
            f"Moved [**{_track.title}**]({_track.uri}) to position `{to}`"
        )
