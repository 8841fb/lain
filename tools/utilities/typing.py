from asyncio import (
    AbstractEventLoop,
    CancelledError,
    Future,
    Task,
    ensure_future,
    sleep,
    wait_for,
)
from contextlib import suppress
from discord import Guild, HTTPException, Member, Message, TextChannel
from discord.ext.commands import Command, Context, Bot

from tools.managers.cache import cache

from .checks import donator


def _typing_done_callback(fut: Future) -> None:
    # just retrieve any exception and call it a day
    try:
        fut.exception()
    except (CancelledError, Exception):  # type: ignore
        pass


class Typing:
    def __init__(self, ctx: Context) -> None:
        self.loop: AbstractEventLoop = ctx._state.loop
        self.messageable: Message = ctx.message
        self.command: Command = ctx.command
        self.bot = ctx.bot
        self.guild: Guild = ctx.guild
        self.author: Member = ctx.author
        self.channel: TextChannel = ctx.channel

    async def is_reskin(self) -> bool:
        try:
            await donator().predicate(self)
        except:
            pass
        else:
            configuration = await self.bot.fetch_config(self.guild.id, "reskin") or {}
            if configuration.get("status"):
                if configuration["webhooks"].get(str(self.channel.id)):
                    reskin = await self.bot.db.fetchrow(
                        "SELECT username, avatar_url FROM reskin WHERE user_id = $1",
                        self.author.id,
                    )
                    if reskin and (reskin["username"] or reskin["avatar_url"]):
                        return True

        return False

    async def wrapped_typer(self) -> None:
        # if await self.is_reskin():
        #     with contextlib.suppress(discord.HTTPException):
        #         await self.messageable.add_reaction(self.bot.config["styles"]["load"].get("emoji"))
        #         return

        await self.channel._state.http.send_typing(self.channel.id)

    def __await__(self):
        return self.wrapped_typer().__await__()

    async def do_typing(self) -> None:
        typing = self.channel._state.http.send_typing

        while True:
            await sleep(5)
            await typing(self.channel.id)

    async def __aenter__(self) -> None:
        if await self.is_reskin():
            if self.command and not self.command.cog_name == "Last.fm Integration":
                with suppress(HTTPException):
                    await self.messageable.add_reaction("⚙️")
            return

        await self.channel._state.http.send_typing(self.channel.id)
        self.task: Task[None] = self.loop.create_task(self.do_typing())
        self.task.add_done_callback(_typing_done_callback)

    async def __aexit__(
        self,
        exc_type,
        exc,
        traceback,
    ) -> None:
        if hasattr(self, "task"):
            self.task.cancel()

        if await self.is_reskin():
            if self.command and not self.command.cog_name == "Last.fm Integration":
                with suppress(HTTPException):
                    await ensure_future(
                        self.messageable.remove_reaction(
                            "⚙️",
                            self.bot.user,
                        )
                    )
            return


async def configure_reskin(bot: Bot, channel: TextChannel, webhooks: dict):
    if not channel.permissions_for(channel.guild.me).manage_webhooks:
        return False

    if str(channel.id) in webhooks:  # We have to use str() because dicts are stupid
        try:
            await bot.fetch_webhook(webhooks[str(channel.id)])
        except:
            del webhooks[str(channel.id)]
            await cache.delete_many(
                f"reskin:channel:{channel.guild.id}:{channel.id}",
                f"reskin:webhook:{channel.id}",
            )
        else:
            return True

    try:
        webhook = await wait_for(
            channel.create_webhook(name="lain reskin"),
            timeout=5,
        )
    except:
        return False
    else:
        webhooks[str(channel.id)] = webhook.id
        try:
            await cache.delete(f"reskin:channel:{channel.guild.id}:{channel.id}")
            await cache.set(f"reskin:webhook:{channel.id}", webhook, expire="1h")
        except:
            pass
        return webhook
