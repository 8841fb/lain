import json
import logging
import os
import traceback
from contextlib import suppress
from pathlib import Path
from copy import copy
from typing import Any, Dict, Union
from asyncio import Lock

from asyncspotify import Client as SpotifyClient  # type: ignore
from asyncspotify import ClientCredentialsFlow as SpotifyClientCredentialsFlow  # type: ignore
from aiohttp.client_exceptions import ClientConnectorError, ContentTypeError
from asyncpg import Connection, Pool, create_pool
from discord import (
    AllowedMentions,
    Forbidden,
    HTTPException,
    Embed,
    Activity,
    ActivityType,
    Intents,
    Member,
    Message,
    MessageType,
    NotFound,
    Guild,
    TextChannel,
    VoiceChannel,
)
from discord.ext.commands import (
    AutoShardedBot,
    BadArgument,
    BadInviteArgument,
    BadLiteralArgument,
    BadUnionArgument,
    BotMissingPermissions,
    BucketType,
    ChannelNotFound,
    CheckFailure,
    Command,
    CommandError,
    CommandInvokeError,
    CommandNotFound,
    CommandOnCooldown,
)
from discord.ext.commands import Context as _Context
from discord.ext.commands import (
    CooldownMapping,
    DisabledCommand,
    EmojiNotFound,
    Group,
    GuildNotFound,
    MaxConcurrencyReached,
    MemberNotFound,
    MissingPermissions,
    MissingRequiredArgument,
    NotOwner,
    RoleNotFound,
    UserInputError,
    UserNotFound,
    when_mentioned_or,
)
from discord.ext.ipc import Server
from discord.ext.ipc.objects import ClientPayload
from discord.ext.ipc.server import Server
from discord.utils import utcnow
from pomice import Node

import config
from tools.managers.context import Context
from tools.managers.logging import Formatter
from tools.managers.network import ClientSession
from tools.managers.cache import cache
from tools.managers.regex import DISCORD_ID, URL
from tools.utilities import tuuid, catalogue


class lain(AutoShardedBot):
    def __init__(self, *args, **kwargs):
        super().__init__(
            command_prefix=self.get_prefix,
            help_command=None,
            strip_after_prefix=True,
            case_insensitive=True,
            owner_ids=config.owners,
            intents=Intents.all(),
            allowed_mentions=AllowedMentions(
                everyone=False,
                users=True,
                roles=False,
                replied_user=False,
            ),
            activity=Activity(
                type=ActivityType.competing,
                name="discord.gg/opp",
            ),
        )
        self.session: ClientSession
        self.buckets: dict = dict(
            guild_commands=dict(
                lock=Lock(),
                cooldown=CooldownMapping.from_cooldown(
                    12,
                    2.5,
                    BucketType.guild,
                ),
                blocked=set(),
            ),
            message_reposting=CooldownMapping.from_cooldown(3, 30, BucketType.user),
            highlights=CooldownMapping.from_cooldown(
                1,
                60,
                BucketType.member,
            ),
            afk=CooldownMapping.from_cooldown(1, 60, BucketType.member),
            reaction_triggers=CooldownMapping.from_cooldown(
                1,
                2.5,
                BucketType.member,
            ),
        )
        self.db: Pool
        self.node: Node
        self.catalogue: catalogue = catalogue
        self.ipc: Server = Server(
            self,
            secret_key="lain",
            standard_port=42069,
            do_multicast=False,
        )
        self.eightball_responses = {
            "As I see it, yes": True,
            "Better not tell you now": False,
            "Concentrate and ask again": False,
            "Don't count on it": False,
            "It is certain": True,
            "It is decidedly so": True,
            "Most likely": True,
            "My reply is no": False,
            "My sources say no": False,
            "Outlook good": True,
            "Outlook not so good": False,
            "Reply hazy, try again": False,
            "Signs point to yes": True,
            "Very doubtful": False,
            "Without a doub.": True,
            "Yes": True,
            "Yes, definitely": True,
            "You may rely on it": True,
            "Ask again later": False,
            "I can't predict now": False,
        }
        self.sticky_locks = dict()
        self.redis: cache = cache

    def run(self: "lain") -> None:
        os.system("clear")
        super().run(
            config.token, reconnect=True, log_formatter=Formatter(), root_logger=True
        )

    async def setup_hook(self: "lain") -> None:
        self.session = ClientSession()
        await self.create_pool()
        await self.ipc.start()
        self.check(self.command_cooldown)
        logging.info(f"Logging into {self.user}")

        for category in Path("features").iterdir():
            if not category.is_dir():
                continue
            if category.name in ("music"):
                continue
            try:
                await self.load_extension(f"features.{category.name}")
                logging.info(f"Loaded category {category.name}")
            except Exception as e:
                logging.exception(f"Failed to load category {category.name}: {e}")

        await self.load_extension("jishaku")

    def walk_commands(self) -> Union[Command, Group]:
        for command in super().walk_commands():
            if (
                (cog := command.cog_name)
                and cog.lower() in ("jishaku", "developer")
                or command.hidden
            ):
                continue

            yield command

    @Server.route(
        name="commands",
    )
    async def ipc_commands(self, payload: ClientPayload) -> Dict:
        output = "Documentation @ https://docs.lains.life\nDefault Prefix: , | () = Required, <> = Optional\n\n"

        for name, cog in sorted(self.cogs.items(), key=lambda cog: cog[0].lower()):
            if name.lower() in ("jishaku", "developer"):
                continue

            _commands = list()
            for command in cog.walk_commands():
                if command.hidden:
                    continue
                if command.cog_name.lower() in ("jishaku", "developer"):
                    continue

                usage = " " + command.usage if command.usage else ""
                aliases = (
                    "[" + "|".join(command.aliases) + "]" if command.aliases else ""
                )
                if isinstance(command, Group) and not command.root_parent:
                    _commands.append(
                        f"|    ├── {command.name}{aliases}: {command.short_doc or 'No description'}"
                    )
                elif not isinstance(command, Group) and command.root_parent:
                    _commands.append(
                        f"|    |   ├── {command.qualified_name}{aliases}{usage}: {command.short_doc or 'No description'}"
                    )
                elif isinstance(command, Group) and command.root_parent:
                    _commands.append(
                        f"|    |   ├── {command.qualified_name}{aliases}: {command.short_doc or 'No description'}"
                    )
                else:
                    _commands.append(
                        f"|    ├── {command.qualified_name}{aliases}{usage}: {command.short_doc or 'No description'}"
                    )

            if _commands:
                output += f"┌── {name}\n" + "\n".join(_commands) + "\n"

        return {
            "bot": {
                "name": self.user.name,
                "avatar": self.user.display_avatar.url,
            },
            "commands": output,
        }

    @Server.route(
        name="avatars",
    )
    async def ipc_avatars(self, payload: ClientPayload) -> Dict:
        if not DISCORD_ID.match(str(payload.user_id)):
            return {"error": "Invalid user ID"}

        avatars = await self.db.fetch(
            "SELECT avatar FROM metrics.avatars WHERE user_id = $1 ORDER BY timestamp DESC",
            int(payload.user_id),
        )
        if not avatars:
            return {"error": "User has no avatar history"}

        output = {
            "user_id": int(payload.user_id),
            "avatars": [avatar["avatar"] for avatar in avatars],
        }
        if user := self.get_user(int(payload.user_id)):
            output["user"] = {"name": user.name, "avatar": user.display_avatar.url}
        else:
            output["user"] = {
                "name": "Unknown User",
                "avatar": self.user.display_avatar.url,
            }

        return output

    async def on_guild_join(self, guild: Guild):
        if not guild.chunked:
            await guild.chunk(cache=True)

        if not await self.db.fetchrow(
            "SELECT * FROM whitelist WHERE guild_id = $1", guild.id
        ):
            with suppress(Forbidden):
                await guild.leave()
                return logging.info(f"Payment not found for guild {guild} ({guild.id})")

        return logging.info(f"Joined guild {guild} ({guild.id})")

    async def on_guild_remove(self, guild: Guild):
        logging.info(f"Left guild {guild} ({guild.id})")

    @property
    def members(self):
        return list(self.get_all_members())

    @property
    def channels(self):
        return list(self.get_all_channels())

    @property
    def text_channels(self):
        return list(
            filter(
                lambda channel: isinstance(channel, TextChannel),
                self.get_all_channels(),
            )
        )

    @property
    def voice_channels(self):
        return list(
            filter(
                lambda channel: isinstance(channel, VoiceChannel),
                self.get_all_channels(),
            )
        )

    async def create_pool(self) -> None:
        def encode_jsonb(value):
            return json.dumps(value)

        def decode_jsonb(value):
            return json.loads(value)

        async def init(connection: Connection) -> None:
            await connection.set_type_codec(
                "jsonb",
                schema="pg_catalog",
                format="text",
                encoder=encode_jsonb,
                decoder=decode_jsonb,
            )

        self.db = await create_pool(
            "postgres://%s:%s@%s/%s"
            % (
                config.Database.user,
                config.Database.password,
                config.Database.host,
                config.Database.name,
            ),
            init=init,
        )

    async def fetch_config(self, guild_id: int, key: str):
        return await self.db.fetchval(
            f"SELECT {key} FROM config WHERE guild_id = $1", guild_id
        )

    async def update_config(self, guild_id: int, key: str, value: str):
        await self.db.execute(
            f"INSERT INTO config (guild_id, {key}) VALUES ($1, $2) ON CONFLICT (guild_id) DO UPDATE SET {key} = $2",
            guild_id,
            value,
        )
        return await self.db.fetchrow(
            f"SELECT * FROM config WHERE guild_id = $1", guild_id
        )

    async def get_context(self: "lain", origin: Message, *, cls=None) -> Context:
        return await super().get_context(
            origin,
            cls=cls or Context,
        )

    def get_command(self, command: str, module: str = None):
        if command := super().get_command(command):
            if not command.cog_name:
                return command
            if command.cog_name.lower() in ("jishaku", "developer") or command.hidden:
                return None
            if module and command.cog_name.lower() != module.lower():
                return None
            return command

        return None

    async def get_prefix(self, message: Message) -> Any:
        if not message.guild:
            return when_mentioned_or(config.prefix)(self, message)

        prefix = (
            await self.db.fetchval(
                """
            SELECT prefix FROM config
            WHERE guild_id = $1
            """,
                message.guild.id,
            )
            or config.prefix
        )

        return when_mentioned_or(prefix)(self, message)

    async def on_command_error(self, ctx: _Context, error: CommandError):
        if type(error) in (
            NotOwner,
            CheckFailure,
            DisabledCommand,
            UserInputError,
            Forbidden,
            CommandOnCooldown,
        ):
            return

        if isinstance(error, CommandNotFound):
            try:
                command = await self.db.fetchval(
                    "SELECT command FROM aliases WHERE guild_id = $1 AND alias = $2",
                    ctx.guild.id,
                    ctx.invoked_with.lower(),
                )
                if command := self.get_command(command):
                    self.err = ctx
                    message = copy(ctx.message)
                    message.content = message.content.replace(
                        ctx.invoked_with, command.qualified_name
                    )
                    await self.process_commands(message)

            except Exception:
                return

        elif isinstance(error, MissingRequiredArgument):
            await ctx.send_help()
        elif isinstance(error, MissingPermissions):
            await ctx.error(
                f"You're **missing** the `{', '.join(error.missing_permissions)}` permission"
            )
        elif isinstance(error, BotMissingPermissions):
            await ctx.error(
                f"I'm **missing** the `{', '.join(error.missing_permissions)}` permission"
            )
        elif isinstance(error, GuildNotFound):
            if error.argument.isdigit():
                return await ctx.error(
                    f"I do not **share a server** with the ID `{error.argument}`"
                )
            else:
                return await ctx.error(
                    f"I do not **share a server** with the name `{error.argument}`"
                )
        elif isinstance(error, BadInviteArgument):
            return await ctx.error("Invalid **invite code** given")
        elif isinstance(error, ChannelNotFound):
            await ctx.error(f"I wasn't able to find that **channel**")
        elif isinstance(error, RoleNotFound):
            await ctx.error(f"I wasn't able to find that **role**")
        elif isinstance(error, MemberNotFound):
            await ctx.error(f"I wasn't able to find that **member**")
        elif isinstance(error, UserNotFound):
            await ctx.error(f"I wasn't able to find that **user**")
        elif isinstance(error, EmojiNotFound):
            await ctx.error(f"I wasn't able to find that **emoji**")
        elif isinstance(error, BadUnionArgument):
            parameter = error.param.name
            converters = list()
            for converter in error.converters:
                if name := getattr(converter, "__name__", None):
                    if name == "Literal":
                        converters.extend(
                            [f"`{literal}`" for literal in converter.__args__]
                        )
                    else:
                        converters.append(f"`{name}`")
            if len(converters) > 2:
                fmt = "{}, or {}".format(", ".join(converters[:-1]), converters[-1])
            else:
                fmt = " or ".join(converters)
            await ctx.error(f"Couldn't convert **{parameter}** into {fmt}")
        elif isinstance(error, BadLiteralArgument):
            parameter = error.param.name
            literals = [f"`{literal}`" for literal in error.literals]
            if len(literals) > 2:
                fmt = "{}, or {}".format(", ".join(literals[:-1]), literals[-1])
            else:
                fmt = " or ".join(literals)
            await ctx.error(f"Parameter **{parameter}** must be {fmt}")
        elif isinstance(error, BadArgument):
            await ctx.error(str(error))
        elif isinstance(error, MaxConcurrencyReached):
            return
        elif "*" in str(error) or "`" in str(error):
            return await ctx.error(str(error))
        elif isinstance(error, CommandInvokeError):
            if isinstance(error.original, HTTPException) or isinstance(
                error.original, NotFound
            ):
                if "Invalid Form Body" in error.original.text:
                    try:
                        parts = "\n".join(
                            [
                                part.split(".", 3)[2]
                                + ":"
                                + part.split(".", 3)[3]
                                .split(":", 1)[1]
                                .split(".", 1)[0]
                                for part in error.original.text.split("\n")
                                if "." in part
                            ]
                        )
                    except IndexError:
                        parts = error.original.text

                    if not parts:
                        parts = error.original.text
                    await ctx.error(f"Your **script** is malformed\n```{parts}\n```")
                elif "Cannot send an empty message" in error.original.text:
                    await ctx.error(f"Your **script** doesn't contain any **content**")
                elif "Must be 4000 or fewer in length." in error.original.text:
                    await ctx.error(f"Your **script** content is too **long**")
            elif isinstance(error.original, Forbidden):
                await ctx.error("I don't have **permission** to do that")
            elif isinstance(error.original, ClientConnectorError):
                await ctx.error("The **API** is currently **unavailable**")
            elif isinstance(error.original, ContentTypeError):
                await ctx.error(f"The **API** returned a **malformed response**")
            else:
                traceback_text = "".join(
                    traceback.format_exception(
                        type(error), error, error.__traceback__, 4
                    )
                )
                unique_id = tuuid.random()
                await self.db.execute(
                    "INSERT INTO traceback (id, command, guild_id, channel_id, user_id, traceback, timestamp) VALUES ($1, $2, $3, $4, $5, $6, $7)",
                    unique_id,
                    ctx.command.qualified_name,
                    ctx.guild.id,
                    ctx.channel.id,
                    ctx.author.id,
                    traceback_text,
                    utcnow(),
                )
                await ctx.error(
                    f"An unknown error occurred while running **{ctx.command.qualified_name}**\n> Please report error `{unique_id}` in the "
                    " [**Discord Server**](https://gg/opp)"
                )
        elif isinstance(error, CommandError):
            await ctx.error(str(error))
        else:
            await ctx.error("An unknown error occurred. Please try again later")

    @staticmethod
    async def command_cooldown(ctx: Context):
        if ctx.author.id == ctx.guild.owner_id:
            return True

        blocked = ctx.bot.buckets["guild_commands"]["blocked"]
        if not ctx.bot.get_guild(ctx.guild.id) or ctx.guild.id in blocked:
            print("blocked")
            return False

        bucket = ctx.bot.buckets["guild_commands"]["cooldown"].get_bucket(ctx.message)
        if retry_after := bucket.update_rate_limit():
            blocked.add(ctx.guild.id)
            lock = ctx.bot.buckets["guild_commands"]["lock"]
            async with lock:
                c = ctx.bot.get_user(1129559813144191096)
                await c.send(
                    f"lain is being flooded in {ctx.guild} (`{ctx.guild.id}`) owned by {ctx.guild.owner} (`{ctx.guild.owner_id}`)"
                )
                return False

        return True

    async def on_message_edit(self, before: Message, after: Message):
        if not self.is_ready() or not before.guild or before.author.bot:
            return

        if before.content == after.content or not after.content:
            return

        await self.process_commands(after)

    async def on_message(self: "lain", message: Message):
        if not self.is_ready() or not message.guild or message.author.bot:
            return

        if (
            message.guild.system_channel_flags.premium_subscriptions
            and message.type
            in (
                MessageType.premium_guild_subscription,
                MessageType.premium_guild_tier_1,
                MessageType.premium_guild_tier_2,
                MessageType.premium_guild_tier_3,
            )
        ):
            self.dispatch(
                "member_boost",
                message.author,
            )

        ctx = await self.get_context(message)
        if str(message.content).lower().startswith(f"{self.user.name} "):
            if match := URL.match(message.content.split(" ", 1)[1]):
                with suppress(HTTPException):
                    await message.delete()

                self.dispatch("message_repost", ctx, match.group())

        ctx = await self.get_context(message)
        if not ctx.command:
            self.dispatch("user_message", ctx, message)

        await self.process_commands(message)

    async def on_member_join(self, member: Member) -> None:
        if not member.pending:
            self.dispatch(
                "member_agree",
                member,
            )

    async def on_member_remove(self, member: Member) -> None:
        if member.premium_since:
            self.dispatch(
                "member_unboost",
                member,
            )

    async def on_member_update(self, before: Member, member: Member) -> None:
        if before.pending and not member.pending:
            self.dispatch(
                "member_agree",
                member,
            )

        if booster_role := member.guild.premium_subscriber_role:
            if (booster_role in before.roles) and not (booster_role in member.roles):
                self.dispatch(
                    "member_unboost",
                    before,
                )

            elif (
                system_flags := member.guild.system_channel_flags
            ) and system_flags.premium_subscriptions:
                return

            elif not (booster_role in before.roles) and (booster_role in member.roles):
                self.dispatch(
                    "member_boost",
                    member,
                )

    async def on_command(self, ctx: Context):
        logging.info(
            f"{ctx.author} ({ctx.author.id}): {ctx.command.qualified_name} in {ctx.guild} ({ctx.guild.id}) #{ctx.channel} ({ctx.channel.id})"
        )
        await self.db.execute(
            "INSERT INTO metrics.commands (guild_id, channel_id, user_id, command, timestamp) VALUES($1, $2, $3, $4, $5)",
            ctx.guild.id,
            ctx.channel.id,
            ctx.author.id,
            ctx.command.qualified_name,
            ctx.message.created_at,
        )
