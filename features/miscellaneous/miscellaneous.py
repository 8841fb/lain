import logging
import os
from asyncio import create_subprocess_shell, gather, subprocess, wait_for
from base64 import b64decode
from contextlib import suppress
from datetime import datetime
from io import BytesIO
from json import JSONDecodeError, dumps, loads
from re import compile as re_compile
from sys import getsizeof
from tempfile import TemporaryDirectory
from time import time
from typing import Any, Dict, List, Optional, Set
import munch
from yarl import URL

from aiofiles import open as async_open
from aiohttp import ClientResponseError
from discord import (
    CategoryChannel,
    Embed,
    File,
    Forbidden,
    HTTPException,
    Member,
    Message,
    PartialMessage,
    Reaction,
    Status,
    TextChannel,
    User,
)
from discord.ext.commands import (
    BucketType,
    CommandError,
    command,
    cooldown,
    group,
    has_permissions,
    is_owner,
    max_concurrency,
)
from discord.ext.tasks import loop
from discord.utils import escape_markdown, escape_mentions, format_dt, utcnow

import config
from tools import services
from tools.converters.basic import Language, MediaFinder, SynthEngine, TimeConverter
from tools.converters.embed import EmbedScriptValidator
from tools.managers import cache
from tools.managers.cog import Cog
from tools.managers.context import Context
from tools.managers.regex import (
    DISCORD_MESSAGE,
    INSTAGRAM_URL,
    MEDIA_URL,
    PINTEREST_PIN_APP_URL,
    PINTEREST_PIN_URL,
    TIKTOK_DESKTOP_URL,
    TIKTOK_MOBILE_URL,
    TWITTER_URL,
    YOUTUBE_CLIP_URL,
    YOUTUBE_SHORT_URL,
    YOUTUBE_SHORTS_URL,
    YOUTUBE_URL,
    MEDAL_URL,
)
from tools.utilities import donator, require_dm, shorten
from tools.utilities.humanize import human_timedelta
from tools.utilities.image import collage
from tools.utilities.image import image_hash as _image_hash
from tools.utilities.text import Plural, hash


class Miscellaneous(Cog):
    """Cog for Miscellaneous commands."""

    async def sport_scores(self, sport: str):
        """Generate the embeds for the scores of a sport"""

        data = await self.bot.session.request(
            "GET", f"http://site.api.espn.com/apis/site/v2/sports/{sport}/scoreboard"
        )
        if not data.events:
            raise CommandError(
                f"There aren't any **{sport.split('/')[0].title()}** events!"
            )

        embeds = []
        for event in data["events"]:
            embed = Embed(
                url=f"https://www.espn.com/{sport.split('/')[1]}/game?gameId={event['id']}",
                title=event.name,
            )
            embed.set_author(
                name=event.competitions[0].competitors[0].team.displayName,
                icon_url=event.competitions[0].competitors[0].team.logo,
            )
            embed.set_thumbnail(url=event.competitions[0].competitors[1].team.logo)
            embed.add_field(
                name="Status",
                value=event.status.type.detail,
                inline=True,
            )
            embed.add_field(
                name="Teams",
                value=(
                    f"{event.competitions[0].competitors[1].team.abbreviation} -"
                    f" {event.competitions[0].competitors[0].team.abbreviation}"
                ),
                inline=True,
            )
            embed.add_field(
                name="Score",
                value=f"{event.competitions[0].competitors[1].score} - {event.competitions[0].competitors[0].score}",
                inline=True,
            )
            embed.timestamp
            embeds.append(embed)

        return embeds

    async def cog_load(self: "Miscellaneous") -> None:
        self.reminder.start()

    async def cog_unload(self: "Miscellaneous") -> None:
        self.reminder.stop()

    @Cog.listener("on_user_update")
    async def avatar_update(self, before: User, after: User):
        """Save past avatars to the upload bucket"""

        if (
            not self.bot.is_ready()
            or not after.avatar
            or str(before.display_avatar) == str(after.display_avatar)
        ):
            return

        channel = self.bot.get_channel(1139307011641720936)
        if not channel:
            return

        try:
            image = await after.avatar.read()
        except:
            return  # asset too new

        image_hash = await _image_hash(image)

        with suppress(HTTPException):
            message = await channel.send(
                file=File(
                    BytesIO(image),
                    filename=f"{image_hash}."
                    + ("png" if not before.display_avatar.is_animated() else "gif"),
                )
            )

            await self.bot.db.execute(
                "INSERT INTO metrics.avatars (user_id, avatar, hash, timestamp) VALUES ($1, $2, $3, $4) ON CONFLICT (user_id, hash) DO NOTHING",
                before.id,
                message.attachments[0].url,
                image_hash,
                int(utcnow().timestamp()),
            )
            logging.info(f"Saved asset {image_hash} for {before}")

    @Cog.listener("on_message")
    async def check_afk(self: "Miscellaneous", message: Message) -> None:
        if (ctx := await self.bot.get_context(message)) and ctx.command:
            return

        elif author_afk_since := await self.bot.db.fetchval(
            """
            DELETE FROM afk
            WHERE user_id = $1
            RETURNING date
            """,
            message.author.id,
        ):
            if "[afk]" in message.author.display_name.lower():
                with suppress(HTTPException, Forbidden):
                    await message.author.edit(
                        nick=message.author.display_name.replace("[afk]", "")
                    )

            await ctx.neutral(
                f"Welcome back, you were away for **{human_timedelta(author_afk_since, suffix=False)}**",
                emoji="👋🏾",
            )

        bucket = self.bot.buckets.get("afk").get_bucket(message)
        if bucket.update_rate_limit():
            return

        elif len(message.mentions) == 1 and (user := message.mentions[0]):
            if user_afk := await self.bot.db.fetchrow(
                """
                SELECT status, date FROM afk
                WHERE user_id = $1
                """,
                user.id,
            ):
                await ctx.neutral(
                    f"{user.mention} is AFK: **{user_afk['status']}** - {human_timedelta(user_afk['date'], suffix=False)}",
                    emoji="💤",
                )

    @Cog.listener("on_user_message")
    async def check_highlights(self: "Miscellaneous", ctx: Context, message: Message):
        """Check for highlights"""

        if not message.content:
            return

        highlights = [
            highlight
            for highlight in await self.bot.db.fetch(
                "SELECT DISTINCT on (user_id) * FROM highlight_words WHERE POSITION(word in $1) > 0",
                message.content.lower(),
            )
            if highlight["user_id"] != message.author.id
            and ctx.guild.get_member(highlight["user_id"])
            and ctx.channel.permissions_for(
                ctx.guild.get_member(highlight["user_id"])
            ).view_channel
        ]

        if highlights:
            bucket = self.bot.buckets.get("highlights").get_bucket(message)
            if bucket.update_rate_limit():
                return

            for highlight in highlights:
                if not highlight.get("word") in message.content.lower() or (
                    highlight.get("strict")
                    and not highlight.get("word") == message.content.lower()
                ):
                    continue
                if member := message.guild.get_member(highlight.get("user_id")):
                    self.bot.dispatch("highlight", message, highlight["word"], member)

    @Cog.listener()
    async def on_highlight(
        self: "Miscellaneous", message: Message, keyword: str, member: Member
    ):
        """Send a notification to the member for the keyword"""

        if member in message.mentions:
            return

        if blocked_entities := await self.bot.db.fetch(
            "SELECT entity_id FROM highlight_block WHERE user_id = $1", member.id
        ):
            if any(
                entity["entity_id"]
                in [message.author.id, message.channel.id, message.guild.id]
                for entity in blocked_entities
            ):
                return

        embed = Embed(
            url=message.jump_url,
            color=config.Color.neutral,
            title=f"Highlight in {message.guild}",
            description=f"Keyword **{escape_markdown(keyword)}** said in {message.channel.mention}\n>>> ",
        )
        embed.set_author(
            name=message.author.display_name,
            icon_url=message.author.display_avatar,
        )

        messages = list()
        try:
            async for ms in message.channel.history(limit=3, before=message):
                if ms.id == message.id:
                    continue
                if not ms.content:
                    continue

                messages.append(
                    f"[{format_dt(ms.created_at, 'T')}] {escape_markdown(str(ms.author))}:"
                    f" {shorten(escape_markdown(ms.content), 50)}"
                )

            messages.append(
                f"__[{format_dt(message.created_at, 'T')}]__ {escape_markdown(str(message.author))}:"
                f" {shorten(escape_markdown(message.content).replace(keyword, f'__{keyword}__'), 50)}"
            )

            async for ms in message.channel.history(limit=2, after=message):
                if ms.id == message.id:
                    continue
                if not ms.content:
                    continue

                messages.append(
                    f"[{format_dt(ms.created_at, 'T')}] {escape_markdown(str(ms.author))}:"
                    f" {shorten(escape_markdown(ms.content), 50)}"
                )

        except Forbidden:
            pass
        embed.description += "\n".join(messages)

        try:
            await member.send(embed=embed)
        except Forbidden:
            pass

    @Cog.listener("on_message_repost")
    async def medal_repost(self: "Miscellaneous", ctx: Context, url: str):
        """Repost a Medal clip using service reposter"""

        if not "medal.tv" in url:
            return

        if match := MEDAL_URL.match(url):
            url = match.group()

        _start = time()
        async with ctx.typing():
            clip = await services.medal.clip(self.bot.session, url)
            if not clip:
                return

            logging.info(f"Obtained clip {clip.id} ({time() - _start:.2f}s)")

            embed = Embed(
                title=clip.title or "Untitled",
                description=clip.description or None,
                url=clip.url,
            )
            embed.set_author(
                name=clip.author.display_name,
                icon_url=clip.author.avatar,
                url=clip.author.url,
            )
            embed.set_footer(
                text=f"❤️ {clip.statistics.likes:,} 💬 {clip.statistics.comments:,} 👁‍🗨 {clip.statistics.views:,}"
            )

            return await ctx.send(
                embed=embed,
                file=File(
                    fp=BytesIO(
                        await self.bot.session.request("GET", clip.asset.video_url)
                    ),
                    filename=f"lain{clip.id}.mp4",
                ),
            )

    @Cog.listener("on_message_repost")
    async def instagram_repost(self: "Miscellaneous", ctx: Context, argument: str):
        """Repost an Instagram post using service reposter"""

        if not "instagram" in argument:
            return

        async def download_media(media: str, filename: str) -> str | File:
            """Download media from a URL"""
            response = await self.bot.session.request("GET", str(media))
            return File(fp=BytesIO(response), filename=filename)

        _start = time()
        async with ctx.typing():
            post = await services.instagram.post(self.bot.session, argument)
            if not post:
                return

            logging.info(
                f"Obtained page {post.code} ({time() - _start:.2f}s) - {ctx.author} ({ctx.author.id})"
            )

            username = escape_markdown(post.profile.username)
            caption = f"**@{username}** <t:{post.taken}:d>"

            if post.caption:
                caption += f"\n" + shorten(escape_mentions(post.caption), 100)

            tasks = []

            for index, media in enumerate(post.media):
                ext = "mp4" if media.category == "VIDEO" else "jpg"
                filename = f"lain{post.code}_{index}.{ext}"
                tasks.append(download_media(media.url, filename))

            files = []
            results = await gather(*tasks)

            for result in results:
                if isinstance(result, File):
                    files.append(result)
                else:
                    caption += f"\n{result}"

            return await ctx.send(caption, files=files)

    @Cog.listener("on_message_repost")
    async def youtube_repost(self: "Miscellaneous", ctx: Context, argument: str):
        """Repost a YouTube video using service reposter"""

        if not "youtu" in argument:
            return

        if (
            match := YOUTUBE_URL.match(argument)
            or YOUTUBE_SHORT_URL.match(argument)
            or YOUTUBE_SHORTS_URL.match(argument)
            or YOUTUBE_CLIP_URL.match(argument)
        ):
            argument = match.group()

        else:
            return

        _start = time()
        async with ctx.typing():
            response = await services.youtube.get_post(argument)
            if not response:
                return

            if "error" in response:
                return
            elif response.download.duration > 360:
                return await ctx.error(
                    "The **video** is too long to be reposted (`max 6 minutes`)"
                )

            else:
                logging.info(
                    f"Obtained page {match.group(1)} ({time() - _start:.2f}s) - {ctx.author} ({ctx.author.id})"
                )

                embed = Embed(
                    url=response.url,
                    title=response.title,
                )
                embed.set_author(
                    name=response.user.name,
                    url=response.user.url,
                    icon_url=ctx.author.display_avatar,
                )

                video = await self.bot.session.request("GET", response.download.url)
                file = File(BytesIO(video), filename=f"lain{match.group(1)}.mp4")
                embed.set_footer(
                    text=f"👁‍🗨 {response.statistics.views:,} - {ctx.message.author}",
                )
                embed.timestamp = datetime.utcfromtimestamp(response.created_at)
                await ctx.send(embed=embed, file=file)

    @Cog.listener("on_message_repost")
    async def twitter_repost(self: "Miscellaneous", ctx: Context, argument: str):
        """Repost a tweet from Twitter using service reposter"""

        if not "twitter" in argument:
            return
        if match := TWITTER_URL.match(argument):
            argument = match.group()
        else:
            return

        _start = time()
        async with ctx.typing():
            try:
                data = await services.twitter.get_tweet(
                    self.bot.session,
                    url=argument,
                )
            except ClientResponseError:
                return await ctx.error(
                    "Couldn't find a **tweet** for that URL, could possibly be **explicit** content."
                )

            if not data:
                return await ctx.error("Couldn't find a **tweet** for that URL")

            logging.info(
                f"Obtained page {data.id} ({time() - _start:.2f}s) - {ctx.author} ({ctx.author.id})"
            )

            embed = Embed(url=data.url, description=data.text.split("https://t.co")[0])
            embed.set_author(
                name=data.user.name, url=data.user.url, icon_url=data.user.avatar
            )
            embed.set_footer(
                text=f"❤️ {data.statistics.likes:,} 💬 {data.statistics.replies:,} - {ctx.author}",
            )

            if images := data.assets.images:
                embeds = [(embed.copy().set_image(url=image)) for image in images]
                return await ctx.paginate(embeds)

            file = (
                await self.bot.session.request("GET", data.assets.video)
                if data.assets.video
                else None
            )
            file = File(BytesIO(file), filename=f"lain{data.id}.mp4") if file else None
            await ctx.send(embed=embed, file=file)

    @Cog.listener("on_message_repost")
    async def tiktok_repost(self: "Miscellaneous", ctx: Context, argument: str):
        """Reposts TikTok posts"""

        if not "tiktok" in argument:
            return

        if match := TIKTOK_DESKTOP_URL.match(argument) or TIKTOK_MOBILE_URL.match(
            argument
        ):
            argument = match.group()
        else:
            return

        _start = time()
        async with ctx.typing():
            data = await services.tiktok.get_post(url=argument)

            if not data:
                return

            logging.info(
                f"Obtained page {data.id} ({time() - _start:.2f}s) - {ctx.author} ({ctx.author.id})"
            )
            embed = Embed(
                url=data.share_url,
                description=data.caption.split("\n")[0] if data.caption else None,
            )
            embed.set_author(
                name=data.user.nickname, url=data.user.url, icon_url=data.user.avatar
            )
            embed.set_footer(
                text=f"❤️ {data.statistics.likes:,} 💬 {data.statistics.comments:,} 🎬 {data.statistics.plays:,} - {ctx.author}",
                icon_url="https://seeklogo.com/images/T/tiktok-icon-logo-1CB398A1BD-seeklogo.com.png",
            )

            embed.timestamp = data.created_at

            if images := data.assets.images:
                embeds = [(embed.copy().set_image(url=image)) for image in images]
                return await ctx.paginate(embeds)

            file = (
                await self.bot.session.request("GET", data.assets.video)
                if data.assets.video
                else None
            )
            if file:
                file = File(BytesIO(file), filename=f"lain{data.id}.mp4")

            await ctx.send(embed=embed, file=file)

    @Cog.listener("on_message_repost")
    async def pinterest_repost(self: "Miscellaneous", ctx: Context, argument: str):
        """Reposts Pinterest pins"""

        if not "pin" in argument:
            return

        if match := PINTEREST_PIN_URL.match(argument) or PINTEREST_PIN_APP_URL.match(
            argument
        ):
            argument = match.group()
        else:
            return

        _start = time()
        async with ctx.typing():
            data = await services.pinterest.get_pin(url=argument)

            if not data:
                logging.error(f"Couldn't find a **pin** for {argument}")

            logging.info(
                f"Obtained page {data.id} ({time() - _start:.2f}s) - {ctx.author} ({ctx.author.id})"
            )

            embed = Embed(url=data.url, description=data.title)
            embed.set_author(
                name=data.user.display_name,
                url=data.user.url,
                icon_url=data.user.avatar,
            )
            embed.set_footer(
                text=f"❤️ {data.statistics.saves:,} 💬 {data.statistics.comments:,} - {ctx.author}",
            )

            if data.media.type == "image":
                embed.set_image(url=data.media.url)
                return await ctx.send(embed=embed)

            response = await self.bot.session.request("GET", data.media.url)
            file = File(BytesIO(response), filename=f"lain{data.id}.mp4")
            await ctx.send(embed=embed, file=file)

    @Cog.listener("on_user_update")
    async def username_update(self: "Miscellaneous", before: User, after: User):
        """Save past names to the database"""

        if not self.bot.is_ready() or before.name == after.name:
            return

        await self.bot.db.execute(
            "INSERT INTO metrics.names (user_id, name, timestamp) VALUES ($1, $2, $3)",
            after.id,
            str(before),
            utcnow(),
        )

    @loop(seconds=30)
    async def reminder(self: "Miscellaneous"):
        """Notify users of their reminders"""

        for reminder in await self.bot.db.fetch("SELECT * FROM reminders"):
            if user := self.bot.get_user(reminder["user_id"]):
                if utcnow() >= reminder["timestamp"]:
                    with suppress(HTTPException):
                        await user.send(
                            f'u wanted me to remind u to {reminder["text"]}'
                        )
                        await self.bot.db.execute(
                            "DELETE FROM reminders WHERE user_id = $1 AND text = $2",
                            reminder["user_id"],
                            reminder["text"],
                        )

    @Cog.listener("on_user_message")
    async def message_repost(
        self: "Miscellaneous", ctx: Context, message: Message
    ) -> Embed | None:
        """Repost a message from a different channel."""

        if message.author.bot:
            return
        if not message.content:
            return
        if not "discord.com/channels" in message.content:
            return

        if match := DISCORD_MESSAGE.match(message.content):
            guild_id, channel_id, message_id = map(int, match.groups())
            channel = self.bot.get_channel(channel_id)
            if not channel:
                return
            if not channel.permissions_for(ctx.me).view_channel:
                return
            if not channel.permissions_for(ctx.author).view_channel:
                return
        else:
            return

        try:
            message = await channel.fetch_message(message_id)
        except HTTPException:
            return

        if message.embeds and not message.embeds[0].type == "image":
            embed = message.embeds[0]
            embed.description = embed.description or ""
        else:
            embed = Embed(
                color=(
                    message.author.color
                    if message.author.color.value
                    else config.Color.neutral
                ),
                description="",
            )
        embed.set_author(
            name=message.author,
            icon_url=message.author.display_avatar,
            url=message.jump_url,
        )

        if message.content:
            embed.description += f"\n{message.content}"

        if message.attachments and message.attachments[0].content_type.startswith(
            "image"
        ):
            embed.set_image(url=message.attachments[0].proxy_url)

        attachments = list()
        for attachment in message.attachments:
            if attachment.content_type.startswith("image"):
                continue
            if attachment.size > ctx.guild.filesize_limit:
                continue
            if not attachment.filename.endswith(
                ("mp4", "mp3", "mov", "wav", "ogg", "webm")
            ):
                continue

            attachments.append(await attachment.to_file())

        embed.set_footer(
            text=f"Posted @ #{message.channel}", icon_url=message.guild.icon
        )
        embed.timestamp = message.created_at

        await ctx.channel.send(embed=embed, files=attachments)

    @command(
        name="firstmessage",
        usage="<channel>",
        example="#chat",
        aliases=["firstmsg", "first"],
    )
    async def firstmessage(
        self: "Miscellaneous", ctx: Context, *, channel: TextChannel = None
    ):
        """View the first message in a channel"""

        channel = channel or ctx.channel

        async for message in channel.history(limit=1, oldest_first=True):
            break

        await ctx.neutral(
            f"Jump to the [**first message**]({message.jump_url}) by **{message.author}**",
            emoji="📝",
        )

    @command(
        name="google",
        usage="(query)",
        example="how to make a discord bot",
        aliases=["g", "search"],
    )
    async def google(self: "Miscellaneous", ctx: Context, *, query: str):
        """Search for something on Google"""

        async with ctx.typing():
            response = await self.bot.session.request(
                "GET",
                "https://notsobot.com/api/search/google",
                params=dict(
                    query=query.replace(" ", ""),
                    safe="true" if not ctx.channel.is_nsfw() else "false",
                ),
            )

            if not response.total_result_count:
                return await ctx.error(f"No results found for `{query}`")

            embed = Embed(title=f"Google Search: {query}")

            for entry in (
                response.results[:2] if response.cards else response.results[:3]
            ):
                embed.add_field(
                    name=entry.title,
                    value=f"{entry.cite}\n{entry.description}",
                    inline=False,
                )

            await ctx.send(embed=embed)

    @Cog.listener()
    async def on_message_delete(self: "Miscellaneous", message: Message) -> None:
        if not message.guild or message.author.bot:
            return

        key = f"snipe:{message.guild.id}:messages:{message.channel.id}"
        await cache.set_add(
            key,
            dumps(
                {
                    "author": {
                        "display_name": message.author.display_name,
                        "avatar_url": message.author.display_avatar.url,
                    },
                    "content": message.content,
                    "attachment_url": (
                        message.attachments[0].url if message.attachments else None
                    ),
                    "deleted_at": utcnow().timestamp(),
                }
            ),
            expire=7200,
        )

    @Cog.listener()
    async def on_message_edit(
        self: "Miscellaneous", message: Message, after: Message
    ) -> None:
        if not message.guild or message.author.bot:
            return

        key = f"snipe:{message.guild.id}:edits:{message.channel.id}"
        await cache.set_add(
            key,
            dumps(
                {
                    "author": {
                        "display_name": message.author.display_name,
                        "avatar_url": message.author.display_avatar.url,
                    },
                    "content": message.content,
                    "attachment_url": (
                        message.attachments[0].url if message.attachments else None
                    ),
                    "edited_at": utcnow().timestamp(),
                }
            ),
            expire=7200,
        )

    @Cog.listener()
    async def on_reaction_remove(
        self: "Miscellaneous", reaction: Reaction, member: Member
    ) -> None:
        if not member.guild or member.bot:
            return

        message = reaction.message
        key = f"snipe:{message.guild.id}:reactions:{message.channel.id}:{message.id}"
        await cache.set_add(
            key,
            dumps(
                {
                    "user": member.display_name,
                    "emoji": str(reaction),
                    "removed_at": utcnow().timestamp(),
                }
            ),
            expire=300,
        )

    @command(
        name="clearsnipe",
        aliases=[
            "clearsnipes",
            "cs",
        ],
    )
    @cooldown(1, 10, BucketType.guild)
    @has_permissions(manage_messages=True)
    async def clearsnipe(self: "Miscellaneous", ctx: Context) -> None:
        """
        Clears all results for reactions, edits and messages
        """

        await cache.delete_match(f"snipe:{ctx.guild.id}:*")
        await ctx.message.add_reaction("✅")

    @command(name="snipe", usage="<index>", example="3", aliases=["s"])
    async def snipe(self: "Miscellaneous", ctx: Context, index: int = 1) -> None:
        """
        Snipe the latest message that was deleted
        """

        if index < 1:
            return await ctx.send_help()

        key = f"snipe:{ctx.guild.id}:messages:{ctx.channel.id}"
        if not (messages := await cache.get(key)):
            return await ctx.error(
                "No **deleted messages** found in the last **2 hours**!"
            )

        if index > len(messages):
            return await ctx.error(f"No **snipe** found for `index {index}`")

        message = loads(
            sorted(
                messages,
                key=lambda m: loads(m)["deleted_at"],
                reverse=True,
            )[index - 1]
        )

        embed = Embed(
            description=message["content"],
        )
        embed.set_author(
            name=message["author"]["display_name"],
            icon_url=message["author"]["avatar_url"],
        )

        if attachment_url := message.get("attachment_url"):
            embed.set_image(url=attachment_url)

        embed.set_footer(
            text=f"Deleted {human_timedelta(datetime.fromtimestamp(message['deleted_at']))} ∙ {index}/{len(messages)} messages",
            icon_url=ctx.author.display_avatar,
        )

        return await ctx.send(embed=embed)

    @command(name="reactionsnipe", aliases=["rs"])
    async def reactionsnipe(self: "Miscellaneous", ctx: Context) -> None:
        """
        Snipe the latest reaction that was removed
        """

        key = f"snipe:{ctx.guild.id}:reactions:{ctx.channel.id}:*"
        messages: List[Set[int, Dict]] = []

        async for key in cache.get_match(key):
            reactions = key[1]
            sorted_reactions = sorted(
                reactions, key=lambda r: loads(r)["removed_at"], reverse=True
            )
            latest_reaction = loads(sorted_reactions[0])
            message_id = int(key[0].split(":")[-1])
            messages.append((message_id, latest_reaction))

        if not messages:
            return await ctx.error(
                "No **removed reactions** found in the last **5 minutes**!"
            )

        message_id, reaction = max(messages, key=lambda m: m[1]["removed_at"])
        message: PartialMessage = ctx.channel.get_partial_message(message_id)

        try:
            await ctx.channel.neutral(
                f"**{reaction['user']}** reacted with **{reaction['emoji']}** <t:{int(reaction['removed_at'])}:R>",
                reference=message,
            )
        except (HTTPException, Forbidden):
            await ctx.channel.neutral(
                f"**{reaction['user']}** reacted with **{reaction['emoji']}** on [message]({message.jump_url}) <t:{int(reaction['removed_at'])}:R>",
            )

    @command(
        name="reactionhistory",
        usage="<message link>",
        example="discordapp.com/channels/...",
        aliases=["rh"],
    )
    @has_permissions(manage_messages=True)
    async def reactionhistory(
        self: "Miscellaneous", ctx: Context, message: Message = None
    ) -> Message:
        """
        See logged reactions for a message
        """

        message = message or ctx.replied_message
        if not message:
            return await ctx.send_help()

        key = f"snipe:{ctx.guild.id}:reactions:{message.channel.id}:{message.id}"
        if not (
            reactions := [
                loads(reaction)
                for reaction in sorted(
                    await cache.get(key, []),
                    key=lambda r: loads(r)["removed_at"],
                    reverse=True,
                )
            ]
        ):
            return await ctx.error(
                f"No **removed reactions** found for [message]({message.jump_url})"
            )

        return await ctx.paginate(
            Embed(
                url=message.jump_url,
                title="Reaction history",
                description=[
                    f"**{reaction['user']}** added **{reaction['emoji']}** <t:{int(reaction['removed_at'])}:R>"
                    for reaction in reactions
                ],
            ),
            text="reaction",
        )

    @group(
        name="remind",
        usage="(duration) (text)",
        example="1h go to the gym",
        aliases=["reminder"],
        invoke_without_command=True,
    )
    @require_dm()
    async def remind(
        self: "Miscellaneous", ctx: Context, duration: TimeConverter, *, text: str
    ) -> Message:
        """Set a reminder"""

        if duration.seconds < 60:
            return await ctx.error("Duration must be at least **1 minute**")

        try:
            await self.bot.db.execute(
                "INSERT INTO reminders (user_id, text, jump_url, created_at, timestamp) VALUES ($1, $2, $3, $4, $5)",
                ctx.author.id,
                text,
                ctx.message.jump_url,
                ctx.message.created_at,
                ctx.message.created_at + duration.delta,
            )

        except:
            return await ctx.error(f"Already being reminded for **{text}**")

        await ctx.approve(
            f"I'll remind you {format_dt(ctx.message.created_at + duration.delta, style='R')}"
        )

    @remind.command(
        name="remove",
        usage="(text)",
        example="go to the gym",
        aliases=["delete", "del", "rm", "cancel"],
    )
    async def remove(self: "Miscellaneous", ctx: Context, *, text: str):
        """Remove a reminder"""

        try:
            await self.bot.db.execute(
                "DELETE FROM reminders WHERE user_id = $1 AND lower(text) = $2",
                ctx.author.id,
                text.lower(),
            )
        except:
            return await ctx.error(f"Coudn't find a reminder for **{text}**")

        return await ctx.approve(f"Removed reminder for **{text}**")

    @remind.command(
        name="list",
        aliases=["show", "view"],
    )
    async def reminders(self: "Miscellaneous", ctx: Context):
        """View your pending reminders"""

        reminders = await self.bot.db.fetch(
            "SELECT * FROM reminders WHERE user_id = $1", ctx.author.id
        )

        if not reminders:
            return await ctx.error("You don't have any **reminders**")

        await ctx.paginate(
            Embed(
                title="Reminders",
                description=list(
                    f"**{shorten(reminder['text'], 23)}** ({format_dt(reminder['timestamp'], style='R')})"
                    for reminder in reminders
                ),
            )
        )

    @group(
        name="highlight",
        usage="(subcommand) <args>",
        example="add caden",
        aliases=["hl", "snitch"],
        invoke_without_command=True,
    )
    async def highlight(self: "Miscellaneous", ctx: Context):
        """Notify you when a keyword is mentioned"""

        await ctx.send_help()

    @highlight.command(
        name="add",
        usage="(word)",
        example="caden",
        parameters={
            "strict": {
                "require_value": False,
                "description": "Whether the message should be a strict match",
            }
        },
        aliases=["create", "new"],
    )
    @require_dm()
    async def highlight_add(self: "Miscellaneous", ctx: Context, *, word: str):
        """Add a keyword to notify you about"""

        word = word.lower()

        if escape_mentions(word) != word:
            return await ctx.error("Your keyword can't contain mentions")
        elif len(word) < 2:
            return await ctx.error(
                "Your keyword must be at least **2 characters** long"
            )
        elif len(word) > 32:
            return await ctx.error(
                "Your keyword can't be longer than **32 characters**"
            )

        try:
            await self.bot.db.execute(
                "INSERT INTO highlight_words (user_id, word, strict) VALUES ($1, $2, $3)",
                ctx.author.id,
                word,
                ctx.parameters.get("strict"),
            )
        except:
            return await ctx.error(f"You're already being notified about `{word}`")

        await ctx.approve(
            f"You'll now be notified about `{word}` "
            + ("(strict)" if ctx.parameters.get("strict") else "")
        )

    @highlight.command(
        name="remove",
        usage="(word)",
        example="caden",
        aliases=["delete", "del", "rm"],
    )
    async def highlight_remove(self: "Miscellaneous", ctx: Context, *, word: str):
        """Remove a keyword to notify you about"""

        query = """
                DELETE FROM highlight_words
                WHERE user_id = $1 AND word = $2
                RETURNING 1;
            """

        if await self.bot.db.fetch(query, ctx.author.id, word.lower()):
            return await ctx.approve(f"You won't be notified about `{word}` anymore")

        await ctx.error(f"You're not being notified about `{word}`")

    @highlight.command(
        name="block",
        usage="(entity)",
        example="#chat",
        aliases=["ignore"],
    )
    async def highlight_block(
        self: "Miscellaneous",
        ctx: Context,
        *,
        entity: TextChannel | CategoryChannel | Member | User,
    ):
        """Block a channel or user from notifying you"""

        if entity.id == ctx.author.id:
            return await ctx.error("You can't ignore yourself")
        try:
            await self.bot.db.execute(
                "INSERT INTO highlight_block (user_id, entity_id) VALUES ($1, $2)",
                ctx.author.id,
                entity.id,
            )
        except:
            return await ctx.error(
                f"You're already ignoring [**{entity}**]({entity.jump_url if (isinstance(entity, TextChannel) or isinstance(entity, CategoryChannel)) else 'https://discord.gg/opp'})"
            )

        await ctx.approve(
            f"Ignoring [**{entity}**]({entity.jump_url if (isinstance(entity, TextChannel) or isinstance(entity, CategoryChannel)) else 'https://discord.gg/opp'})"
        )

    @highlight.command(
        name="unblock",
        usage="(entity)",
        example="#chat",
        aliases=["unignore"],
    )
    async def highlight_unblock(
        self: "Miscellaneous",
        ctx: Context,
        *,
        entity: TextChannel | CategoryChannel | Member | User,
    ):
        """Unignore a user or channel"""

        query = """
                DELETE FROM highlight_block
                WHERE user_id = $1 AND entity_id = $2
                RETURNING 1;
            """

        if await self.bot.db.fetch(query, ctx.author.id, entity.id):
            return await ctx.approve(
                f"No longer ignoring [**{entity}**]({entity.jump_url if (isinstance(entity, TextChannel) or isinstance(entity, CategoryChannel)) else 'https://discord.gg/opp'})"
            )

        await ctx.error(
            f"You're not ignoring [**{entity}**]({entity.jump_url if (isinstance(entity, TextChannel) or isinstance(entity, CategoryChannel)) else 'https://discord.gg/opp'})"
        )

    @highlight.command(
        name="list",
        aliases=["show", "view", "blocked"],
    )
    async def highlight_list(self: "Miscellaneous", ctx: Context):
        """View your highlighted keywords"""

        keywords = await self.bot.db.fetch(
            "SELECT word, strict FROM highlight_words WHERE user_id = $1", ctx.author.id
        )

        if not keywords:
            return await ctx.error("You don't have any **highlighted keywords**")

        await ctx.paginate(
            Embed(
                title="Highlighted Keywords",
                description=list(
                    f"**{keyword['word']}**"
                    + (" (strict)" if keyword["strict"] else "")
                    for keyword in keywords
                ),
            )
        )

    @group(
        name="namehistory",
        usage="<user>",
        example="lain",
        aliases=["names", "nh"],
        invoke_without_command=True,
    )
    async def namehistory(
        self: "Miscellaneous", ctx: Context, *, user: Member | User = None
    ):
        """View a user's name history"""

        user = user or ctx.author

        names = await self.bot.db.fetch(
            "SELECT name, timestamp FROM metrics.names WHERE user_id = $1 ORDER BY timestamp DESC",
            user.id,
        )
        if not names:
            return await ctx.error(
                "You don't have any **names** in the database"
                if user == ctx.author
                else f"**{user}** doesn't have any **names** in the database"
            )

        await ctx.paginate(
            Embed(
                title="Name History",
                description=list(
                    f"**{name['name']}** ({format_dt(name['timestamp'], style='R')})"
                    for name in names
                ),
            )
        )

    @namehistory.command(
        name="reset",
        aliases=["clear", "wipe", "delete", "del", "rm"],
    )
    @donator(booster=True)
    async def namehistory_reset(self: "Miscellaneous", ctx: Context):
        """Reset your name history"""

        await self.bot.db.execute(
            "DELETE FROM metrics.names WHERE user_id = $1", ctx.author.id
        )
        await ctx.approve("Cleared your **name history**")

    @command(
        name="image",
        usage="(query)",
        example="Clairo",
        aliases=["img", "im", "i"],
    )
    async def image(self: "Miscellaneous", ctx: Context, *, query: str):
        """Search Google for an image"""

        response = await self.bot.session.get(
            "https://notsobot.com/api/search/google/images",
            params=dict(
                query=query.replace(" ", ""),
                safe="true" if not ctx.channel.is_nsfw() else "false",
            ),
        )
        data = await response.json()

        if not data:
            return await ctx.error(f"Couldn't find any images for **{query}**")

        entries = [
            Embed(
                url=entry.get("url"),
                title=entry.get("header"),
                description=entry.get("description"),
            ).set_image(url=entry["image"]["url"])
            for entry in data
            if not entry.get("header") in ("TikTok", "Facebook", "Instagram")
        ]
        await ctx.paginate(entries)

    @command(
        name="urban",
        usage="(query)",
        example="self-projecting",
        aliases=["urbandictionary", "ud"],
    )
    async def urban(self: "Miscellaneous", ctx: Context, *, query: str):
        """Search for a definition on Urban Dictionary"""

        response = await self.bot.session.request(
            "GET", "http://api.urbandictionary.com/v0/define", params=dict(term=query)
        )

        if not response.list:
            return await ctx.error(f"Couldn't find any definitions for **{query}**")

        def repl(match):
            word = match.group(2)
            return f"[{word}](https://{word.replace(' ', '-')}.urbanup.com)"

        entries = [
            Embed(
                url=entry.permalink,
                title=entry.word,
                description=re_compile(r"(\[(.+?)\])").sub(repl, entry.definition),
            )
            .add_field(
                name="Example",
                value=re_compile(r"(\[(.+?)\])").sub(repl, entry.example),
                inline=False,
            )
            .set_footer(
                text=f"👍 {entry.thumbs_up:,} 👎 {entry.thumbs_down:,} - {entry.word}"
            )
            for entry in response.list
        ]
        await ctx.paginate(entries)

    @command(
        name="translate",
        usage="<language> (text)",
        example="Spanish Hello!",
        aliases=["tr"],
    )
    async def translate(
        self: "Miscellaneous",
        ctx: Context,
        language: Optional[Language] = "en",
        *,
        text: str,
    ):
        """Translate text to another language"""

        async with ctx.typing():
            response = await self.bot.session.request(
                "GET",
                "https://clients5.google.com/translate_a/single",
                params={
                    "dj": "1",
                    "dt": ["sp", "t", "ld", "bd"],
                    "client": "dict-chrome-ex",
                    "sl": "auto",
                    "tl": language,
                    "q": text,
                },
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/104.0.0.0 Safari/537.36"
                },
            )
            if not response:
                return await ctx.error("Couldn't **translate** the **text**")

            text = "".join(sentence.trans for sentence in response.sentences)
            if not text:
                return await ctx.error("Couldn't **translate** the **text**")

        if ctx.author.mobile_status != Status.offline:
            return await ctx.reply(text)

        embed = Embed(
            title="Google Translate",
            description=f"```{text[:4000]}```",
        )
        await ctx.reply(embed=embed)

    @command(
        name="wolfram",
        usage="(query)",
        example="integral of x^2",
        aliases=["wolframalpha", "wa", "w"],
    )
    async def wolfram(self: "Miscellaneous", ctx: Context, *, query: str):
        """Search a query on Wolfram Alpha"""

        async with ctx.typing():
            response = await self.bot.session.request(
                "GET",
                f"https://notsobot.com/api/search/wolfram-alpha",
                params=dict(query=query),
            )

            if not response.fields:
                return await ctx.error("Couldn't **understand** your input")

            embed = Embed(
                title=query,
                url=response.url,
            )

            for index, field in enumerate(response.fields[:4]):
                if index == 2:
                    continue

                embed.add_field(
                    name=field.name,
                    value=(">>> " if index == 3 else "")
                    + field.value.replace("( ", "(")
                    .replace(" )", ")")
                    .replace("(", "(`")
                    .replace(")", "`)"),
                    inline=(False if index == 3 else True),
                )
            embed.set_footer(
                text="Wolfram Alpha",
                icon_url="https://cdn.discordapp.com/emojis/1126333822405976174.webp?size=96&quality=lossless",
            )
        await ctx.send(embed=embed)

    @command(name="afk", usage="<status>", example="sleeping...(slart)")
    async def afk(
        self: "Miscellaneous", ctx: Context, *, status: str = "AFK"
    ) -> Message:
        """
        Set an AFK status for when you are mentioned
        """

        status = shorten(status, 100)
        await self.bot.db.execute(
            """
            INSERT INTO afk (
                user_id,
                status
            ) VALUES ($1, $2)
            ON CONFLICT (user_id)
            DO NOTHING;
            """,
            ctx.author.id,
            status,
        )

        await ctx.approve(f"You're now AFK with the status: **{status}**")

    @command(
        name="createembed",
        usage="(embed script)",
        example="{title: wow!}",
        aliases=["embed", "ce"],
    )
    async def createembed(
        self: "Miscellaneous", ctx: Context, *, script: EmbedScriptValidator
    ):
        """Send an embed to the channel"""

        await script.send(
            ctx,
            bot=self.bot,
            guild=ctx.guild,
            channel=ctx.channel,
            user=ctx.author,
        )

    @command(
        name="copyembed",
        usage="(message)",
        example="dscord.com/chnls/999/..",
        aliases=["embedcode", "ec"],
    )
    async def copyembed(self: "Miscellaneous", ctx: Context, message: Message):
        """Copy embed code for a message"""

        result = []
        if content := message.content:
            result.append(f"{{content: {content}}}")

        for embed in message.embeds:
            result.append("{embed}")
            if color := embed.color:
                result.append(f"{{color: {color}}}")

            if author := embed.author:
                _author = []
                if name := author.name:
                    _author.append(name)
                if icon_url := author.icon_url:
                    _author.append(icon_url)
                if url := author.url:
                    _author.append(url)

                result.append(f"{{author: {' && '.join(_author)}}}")

            if url := embed.url:
                result.append(f"{{url: {url}}}")

            if title := embed.title:
                result.append(f"{{title: {title}}}")

            if description := embed.description:
                result.append(f"{{description: {description}}}")

            for field in embed.fields:
                result.append(
                    f"{{field: {field.name} && {field.value} && {str(field.inline).lower()}}}"
                )

            if thumbnail := embed.thumbnail:
                result.append(f"{{thumbnail: {thumbnail.url}}}")

            if image := embed.image:
                result.append(f"{{image: {image.url}}}")

            if footer := embed.footer:
                _footer = []
                if text := footer.text:
                    _footer.append(text)
                if icon_url := footer.icon_url:
                    _footer.append(icon_url)

                result.append(f"{{footer: {' && '.join(_footer)}}}")

            if timestamp := embed.timestamp:
                result.append(f"{{timestamp: {str(timestamp)}}}")

        if not result:
            return await ctx.error(
                f"Message [`{message.id}`]({message.jump_url}) doesn't contain an embed"
            )

        result = "\n".join(result)
        return await ctx.approve(f"Copied the **embed code**\n```{result}```")

    @group(
        name="avatarhistory",
        usage="<user>",
        example="caden",
        aliases=["avatars", "avh", "avs", "ah"],
        invoke_without_command=True,
    )
    @max_concurrency(1, BucketType.user)
    @cooldown(3, 30, BucketType.user)
    async def avatarhistory(self, ctx: Context, *, user: Member | User = None):
        """View a user's avatar history"""

        user = user or ctx.author

        avatars = await self.bot.db.fetch(
            "SELECT avatar, timestamp FROM metrics.avatars WHERE user_id = $1 ORDER BY timestamp DESC",
            user.id,
        )
        if not avatars:
            return await ctx.error(
                "You don't have any **avatars** in the database"
                if user == ctx.author
                else f"**{user}** doesn't have any **avatars** in the database"
            )

        async with ctx.typing():
            image = await collage([row.get("avatar") for row in avatars[:35]])
            if not image or getsizeof(image.fp) > ctx.guild.filesize_limit:
                await ctx.neutral(
                    (
                        f"Click [**here**](https://lains.life/avatars/{user.id}) to view"
                        f" **{Plural(avatars):of your avatar}**"
                        if user == ctx.author
                        else (
                            f"Click [**here**](https://lains.life/avatars/{user.id})) to view"
                            f" **{Plural(avatars):avatar}** of **{user}**"
                        )
                    ),
                    emoji="🖼️",
                )
            else:
                embed = Embed(
                    title="Avatar History",
                    description=(
                        f"Showing `{len(avatars[:35])}` of up to `{len(avatars)}` {'changes' if len(avatars) != 1 else 'change'}\n> For the full list"
                        f" including GIFs click [**HERE**](https://lains.life/avatars/{user.id})"
                    ),
                )
                embed.set_author(
                    name=f"{user} ({user.id})",
                    icon_url=user.display_avatar.url,
                )

                embed.set_image(
                    url="attachment://collage.png",
                )
                await ctx.send(
                    embed=embed,
                    file=image,
                )

    @avatarhistory.command(
        name="statistics",
        aliases=["stats", "stat"],
    )
    @is_owner()
    async def avatarhistory_statistics(self, ctx: Context):
        """View the top avatar history users"""

        top_users = await self.bot.db.fetch(
            """
            SELECT user_id, COUNT(*) AS count
            FROM metrics.avatars
            GROUP BY user_id
            ORDER BY count DESC
            """
        )

        await ctx.paginate(
            Embed(
                title="Avatar History Statistics",
                description=list(
                    f"**{self.bot.get_user(user['user_id'])}** ({user['count']} changes)"
                    for user in top_users
                ),
            )
        )

    @avatarhistory.command(
        name="reset",
        aliases=["clear", "wipe", "delete", "del", "rm"],
    )
    @donator(booster=True)
    async def avatarhistory_reset(self, ctx: Context):
        """Reset your avatar history"""

        await self.bot.db.execute(
            "DELETE FROM metrics.avatars WHERE user_id = $1", ctx.author.id
        )
        await ctx.approve("Reset your **avatar history**")

    @command(
        name="synth",
        usage="<engine> (text)",
        example="ghostface hey mommy",
        aliases=["synthesizer", "synthesize", "tts"],
    )
    async def synth(self, ctx: Context, engine: Optional[SynthEngine], *, text: str):
        """Synthesize text into speech"""

        async with ctx.typing():
            response = await self.bot.session.post(
                "https://api16-normal-useast5.us.tiktokv.com/media/api/text/speech/invoke/",
                params=dict(
                    text_speaker=engine or "en_us_002",
                    req_text=text.replace("+", "plus")
                    .replace("-", "minus")
                    .replace("=", "equals")
                    .replace("/", "slash")
                    .replace("@", "at")[:300],
                    speaker_map_type=0,
                    aid=1233,
                ),
                headers={
                    "User-Agent": "com.zhiliaoapp.musically/2022600030 (Linux; U; Android 7.1.2; es_ES; SM-G988N; Build/NRD90M;tt-ok/3.12.13.1)",
                    "Cookie": "sessionid=" + "3797e14bf07c613de9b8b3663a6f2861",
                },
            )
            data = await response.json()

        if data["status_code"] != 0:
            return await ctx.error("Couldn't **synthesize** text")

        vstr: str = data["data"]["v_str"]
        _padding = len(vstr) % 4
        vstr = vstr + ("=" * _padding)

        decoded = b64decode(vstr)
        clean_data = BytesIO(decoded)
        clean_data.seek(0)

        file = File(fp=clean_data, filename=f"Synthesize.mp3")
        await ctx.reply(file=file)

    @command(
        name="shazam",
        usage="(video or audio)",
        example="dscord.com/chnls/999/..mp4",
        aliases=["identify"],
    )
    @cooldown(1, 10, BucketType.user)
    async def shazam(self, ctx: Context, *, media: MediaFinder = None):
        """Identify a song from audio"""

        media = media or await MediaFinder.search(ctx)

        async with ctx.typing():
            response = await self.bot.session.get(media)
            if getsizeof(response.content) > 26214400:
                return await ctx.warn("Media is too large to **identify** (max 25MB)")

            media = await response.read()

            with TemporaryDirectory() as temp_dir:
                temp_file = os.path.join(
                    temp_dir,
                    f"file{hash(str(response.url))}."
                    + MEDIA_URL.match(str(response.url)).group("mime"),
                )
                async with async_open(temp_file, "wb") as file:
                    await file.write(media)

                try:
                    songrec = await wait_for(
                        create_subprocess_shell(
                            f'songrec audio-file-to-recognized-song "{temp_file}"',
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE,
                        ),
                        timeout=7,
                    )
                    stdout, stderr = await songrec.communicate()
                except TimeoutError:
                    return await ctx.warn("Couldn't **recognize** the song - Timeout")

            try:
                output = loads(stdout.decode())
            except JSONDecodeError:
                return await ctx.warn("Couldn't **recognize** the song")

            if track := output.get("track", {}):
                return await ctx.neutral(
                    f"Found [**{track.get('title')}**]({track.get('url')}) by **{track.get('subtitle')}**",
                    emoji="🎵",
                )

            await ctx.error("Couldn't **recognize** the song")

    @command(
        name="valorant",
        usage="(username)",
        example="haley#uwu",
        aliases=["val"],
    )
    async def valorant(self, ctx: Context, *, username: str):
        """View information about a Valorant Player"""

        await ctx.load(f"Searching for `{username}`")

        account = await services.valorant.account(self.bot.session, username)

        embed = Embed(
            url=f"https://tracker.gg/valorant/profile/riot/{URL(account.username)}/overview",
            title=f"{account.region}: {account.username}",
            description=(
                f">>> **Account Level:** {account.level}\n**Rank & ELO:** {account.rank} &"
                f" {account.elo} (`{'+' if account.elo_change >= 1 else ''}{account.elo_change}`)"
            ),
        )

        if account.matches:
            embed.add_field(
                name="Competitive Matches",
                value="\n".join(
                    f"> {format_dt(match.started_at, 'd')} {match.status} (`{f'+{match.kills}' if match.kills >= match.deaths else f'-{match.deaths}'}`)"
                    for match in account.matches
                ),
            )

        embed.set_thumbnail(
            url=account.card,
        )

        embed.set_footer(
            text="Last Updated",
            icon_url="https://img.icons8.com/color/512/valorant.png",
        )

        embed.timestamp = account.updated_at
        await ctx.send(embed=embed)
        with suppress(HTTPException):
            await ctx.previous_load.delete()

    @command(
        name="nba",
    )
    async def nba(self, ctx: Context):
        """National Basketball Association Scores"""

        scores = await self.sport_scores("basketball/nba")
        await ctx.paginate(scores)

    @command(
        name="nfl",
    )
    async def nfl(self, ctx: Context):
        """National Football League Scores"""

        scores = await self.sport_scores("football/nfl")
        await ctx.paginate(scores)

    @command(
        name="mlb",
    )
    async def mlb(self, ctx: Context):
        """Major League Baseball Scores"""

        scores = await self.sport_scores("baseball/mlb")
        await ctx.paginate(scores)

    @command(
        name="nhl",
    )
    async def nhl(self, ctx: Context):
        """National Hockey League Scores"""

        scores = await self.sport_scores("hockey/nhl")
        await ctx.paginate(scores)

    @group(
        name="fortnite",
        usage="(subcommand) <args>",
        example="lookup Nog Ops",
        aliases=["fort", "fn"],
        invoke_without_command=True,
    )
    async def fortnite(self, ctx: Context):
        """Fortnite cosmetic commands"""

        await ctx.send_help()

    @fortnite.command(name="shop", aliases=["store"])
    async def fortnite_shop(self, ctx: Context):
        """View the current Fortnite item shop"""

        embed = Embed(
            title="Fortnite Item Shop",
        )

        embed.set_image(
            url=f"https://bot.fnbr.co/shop-image/fnbr-shop-{utcnow().strftime('%-d-%-m-%Y')}.png"
        )
        await ctx.send(embed=embed)

    @fortnite.command(
        name="lookup", usage="(cosmetic)", example="Nog Ops", aliases=["search", "find"]
    )
    async def fortnite_lookup(self, ctx: Context, *, cosmetic: str):
        """Search for a cosmetic with the last release dates"""

        response: Any = await self.bot.session.request(
            "GET",
            "https://fortnite-api.com/v2/cosmetics/br/search",
            raise_for={
                404: f"Couldn't find any cosmetics matching **{cosmetic}**\n> Search for a cosmetic [**here**](https://fnbr.co/list)"
            },
            params=dict(
                name=cosmetic,
                matchMethod="contains",
            ),
            headers=dict(Authorization="eb1db4b1-5f1e-4ec1-ba7c-802c3a69bfa1"),
        )

        cosmetic: munch.DefaultMunch = response.data

        embed: Embed = Embed(
            url=f"https://fnbr.co/{cosmetic.type.value}/{cosmetic.name.replace(' ', '-')}",
            title=cosmetic.name,
            description=f"{cosmetic.description}\n> {cosmetic.introduction.text.replace('Chapter 1, ', '')}",
        )
        embed.set_thumbnail(url=cosmetic.images.icon)

        if cosmetic.shopHistory:
            embed.add_field(
                name="Release Dates",
                value="\n".join(
                    f"{format_dt(datetime.fromisoformat(date.replace('Z', '+00:00').replace('T', ' ').split('.')[0].replace(' ', 'T')), style='D')} ({format_dt(datetime.fromisoformat(date.replace('Z', '+00:00').replace('T', ' ').split('.')[0].replace(' ', 'T')), style='R')})"
                    for date in list(reversed(cosmetic.shopHistory))[:5]
                ),
            )
        else:
            embed.add_field(
                name="Release Date",
                value=(
                    f"{format_dt(datetime.fromisoformat(cosmetic.added.replace('Z', '+00:00').replace('T', ' ').split('.')[0].replace(' ', 'T')), style='D')} ({format_dt(datetime.fromisoformat(cosmetic.added.replace('Z', '+00:00').replace('T', ' ').split('.')[0].replace(' ', 'T')), style='R')})"
                ),
                inline=False,
            )

        return await ctx.send(embed=embed)
