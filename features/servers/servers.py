from asyncio import Lock, TimeoutError, gather
from contextlib import suppress
from random import choice
from typing import Literal

from discord import (
    AllowedMentions,
    Embed,
    Forbidden,
    HTTPException,
    Member,
    Message,
    TextChannel,
    Thread,
)
from discord.ext.commands import (
    BucketType,
    command,
    cooldown,
    group,
    has_permissions,
    max_concurrency,
)
from discord.ext.tasks import loop

import config
from tools.converters.basic import (
    Command,
    Emoji,
    EmojiFinder,
    ImageFinder,
    ImageFinderStrict,
    TimeConverter,
)
from tools.converters.color import Color
from tools.converters.embed import EmbedScript, EmbedScriptValidator
from tools.converters.role import Role
from tools.managers import cache, ratelimiter
from tools.managers.cog import Cog
from tools.managers.context import Context
from tools.managers.regex import STRING
from tools.utilities.checks import donator, require_boost
from tools.utilities.process import ensure_future
from tools.utilities.text import Plural, hash
from tools.utilities.typing import configure_reskin


class Servers(Cog):
    """Cog for Server commands."""

    async def cog_load(self: "Servers") -> None:
        self.poster_feed.start()

    @Cog.listener("on_user_message")
    async def gallery_channels(self: "Servers", message: Message) -> None:
        """Check if message is in a gallery channel"""
        if not message.guild:
            return

        # Check if the message is sent within a guild before accessing its attributes
        if await self.bot.db.fetchval(
            "SELECT COUNT(*) FROM gallery_channels WHERE guild_id = $1 AND channel_id = $2",
            message.guild.id,
            message.channel.id,
        ):
            if not message.attachments:
                return await message.delete()

    @Cog.listener("on_user_message")
    async def sticky_message_dispatcher(
        self: "Servers", ctx: Context, message: Message
    ):
        """Dispatch the sticky message event while waiting for the activity scheduler"""

        data = await self.bot.db.fetchrow(
            "SELECT * FROM sticky_messages WHERE guild_id = $1 AND channel_id = $2",
            message.guild.id,
            message.channel.id,
        )
        if not data:
            return

        if data["message_id"] == message.id:
            return

        key = hash(f"{message.guild.id}:{message.channel.id}")
        if not self.bot.sticky_locks.get(key):
            self.bot.sticky_locks[key] = Lock()
        bucket = self.bot.sticky_locks.get(key)

        async with bucket:
            try:
                await self.bot.wait_for(
                    "message",
                    check=lambda m: m.channel == message.channel,
                    timeout=data.get("schedule") or 2,
                )
            except TimeoutError:
                pass
            else:
                return

            with suppress(HTTPException):
                await message.channel.get_partial_message(data["message_id"]).delete()

            message = await ensure_future(
                EmbedScript(data["message"]).send(
                    message.channel,
                    bot=self.bot,
                    guild=message.guild,
                    channel=message.channel,
                    user=message.author,
                )
            )
            await self.bot.db.execute(
                "UPDATE sticky_messages SET message_id = $3 WHERE guild_id = $1 AND channel_id = $2",
                message.guild.id,
                message.channel.id,
                message.id,
            )

    @loop(seconds=30)
    async def poster_feed(self):
        """Send a selected avatar to all poster channels"""

        for selection in await self.bot.db.fetch("SELECT * FROM poster_channels"):
            if channel := self.bot.get_channel(selection.get("channel_id")):
                if not (images := getattr(self.bot.catalogue, selection.get("option"))):
                    await self.bot.db.execute(
                        "DELETE FROM poster_channels WHERE channel_id = $1",
                        selection.get("channel_id"),
                    )
                    continue

                await ensure_future(
                    channel.send(
                        embed=(
                            Embed(color=config.Color.neutral)
                            .set_image(url=(choice(images)))
                            .set_footer(text=f"{selection.get('option')} @ lain")
                        )
                    )
                )
            else:
                await self.bot.db.execute(
                    "DELETE FROM poster_channels WHERE channel_id = $1",
                    selection.get("channel_id"),
                )

    @poster_feed.before_loop
    async def poster_feed_before(self):
        await self.bot.wait_until_ready()

    @Cog.listener("on_message")
    async def gallery_channels(self: "Servers", message: Message):
        """Check if message is in a gallery channel"""

        if await self.bot.db.fetchval(
            "SELECT COUNT(*) FROM gallery_channels WHERE guild_id = $1 AND channel_id = $2",
            message.guild.id,
            message.channel.id,
        ):
            if not message.attachments:
                return await message.delete()

    @Cog.listener("on_user_message")  # RESPONSE TRIGGER
    async def response_trigger(self: "Servers", ctx: Context, message: Message):
        """Respond to trigger words"""

        if retry_after := ratelimiter(
            bucket=f"response_trigger:{message.author.id}",
            key=message.guild.id,
            rate=3,
            per=10,
        ):
            return

        if not message.content:
            return

        for row in await self.bot.db.fetch(
            "SELECT * FROM auto_responses WHERE guild_id = $1",
            message.guild.id,
        ):
            if not row.get("trigger").lower() in message.content.lower():
                continue
            if (
                not row.get("not_strict")
                and not row.get("trigger").lower() == message.content.lower()
            ):
                continue
            if not row.get("ignore_command_check") and ctx.command:
                continue
            await ensure_future(
                EmbedScript(row["response"]).send(
                    message.channel,
                    bot=self.bot,
                    guild=message.guild,
                    channel=message.channel,
                    user=message.author,
                    allowed_mentions=AllowedMentions(
                        everyone=True, users=True, roles=True, replied_user=False
                    ),
                    delete_after=row.get("self_destruct"),
                    reference=(message if row.get("reply") else None),
                )
            )

            if not row.get("reply") and row.get("delete"):
                with suppress(HTTPException):
                    await message.delete()

    @Cog.listener("on_member_agree")  # AUTOROLE GRANT
    async def autorole_assigning(self: "Servers", member: Member):
        """Assign roles to a member which joins the server"""

        roles = [
            member.guild.get_role(row.get("role_id"))
            for row in await self.bot.db.fetch(
                "SELECT role_id, humans, bots FROM autorole WHERE guild_id = $1",
                member.guild.id,
            )
            if member.guild.get_role(row.get("role_id"))
            and member.guild.get_role(row.get("role_id")).is_assignable()
            and (row.get("humans") is None or member.bot is False)
            and (row.get("bots") is None or row.get("bots") == member.bot)
        ]
        if roles:
            with suppress(HTTPException):
                await member.add_roles(*roles, reason="Role Assignment", atomic=False)

    @Cog.listener("on_user_message")
    async def reaction_trigger(self: "Servers", ctx: Context, message: Message):
        """React to trigger words"""

        if retry_after := ratelimiter(
            bucket=f"reaction_trigger:{message.author.id}",
            key=message.guild.id,
            rate=3,
            per=10,
        ):
            return

        if not message.content or ctx.command:
            return

        for row in await self.bot.db.fetch(
            "SELECT trigger, array_agg(emoji) AS emojis, strict FROM reaction_triggers WHERE guild_id = $1 GROUP BY trigger, strict",
            message.guild.id,
        ):
            if not row.get("trigger").lower() in message.content.lower():
                continue

            if (
                row.get("strict")
                and not row.get("trigger").lower() == message.content.lower()
            ):
                continue

            for emoji in row.get("emojis"):
                await ensure_future(message.add_reaction(emoji))

    @Cog.listener("on_member_boost")  # BOOST MESSAGE
    async def boost_message(self: "Servers", member: Member):
        """Send a boost message for a member which boosts the server"""

        for row in await self.bot.db.fetch(
            """
            SELECT * FROM boost_messages
            WHERE guild_id = $1;
            """,
            member.guild.id,
        ):
            channel: TextChannel
            if not (channel := member.guild.get_channel(row["channel_id"])):
                continue

            await ensure_future(
                EmbedScript(row["message"]).send(
                    channel,
                    bot=self.bot,
                    guild=member.guild,
                    channel=channel,
                    user=member,
                    allowed_mentions=AllowedMentions(
                        everyone=True, users=True, roles=True, replied_user=False
                    ),
                    delete_after=row.get("self_destruct"),
                )
            )

    @Cog.listener("on_member_agree")  # WELCOME MESSAGE
    async def welcome_message(self: "Servers", member: Member):
        """Send a welcome message for a member which joins the server"""

        for row in await self.bot.db.fetch(
            """
            SELECT * FROM join_messages
            WHERE guild_id = $1;
            """,
            member.guild.id,
        ):
            channel: TextChannel
            if not (channel := member.guild.get_channel(row["channel_id"])):
                continue

            await ensure_future(
                EmbedScript(row["message"]).send(
                    channel,
                    bot=self.bot,
                    guild=member.guild,
                    channel=channel,
                    user=member,
                    allowed_mentions=AllowedMentions(
                        everyone=True, users=True, roles=True, replied_user=False
                    ),
                    delete_after=row.get("self_destruct"),
                )
            )

    @Cog.listener("on_member_remove")
    async def send_join_message(self: "Servers", member: Member) -> None:
        for row in await self.bot.db.fetch(
            """
            SELECT * FROM leave_messages
            WHERE guild_id = $1;
            """,
            member.guild.id,
        ):
            channel: TextChannel
            if not (channel := member.guild.get_channel(row["channel_id"])):
                continue

            await ensure_future(
                EmbedScript(row["message"]).send(
                    channel,
                    bot=self.bot,
                    guild=member.guild,
                    channel=channel,
                    user=member,
                    allowed_mentions=AllowedMentions(
                        everyone=True, users=True, roles=True, replied_user=False
                    ),
                    delete_after=row.get("self_destruct"),
                )
            )

    @group(
        name="poster",
        usage="(subcommand) <args>",
        example="add #pfps female",
        aliases=["catalogue"],
        invoke_without_command=True,
    )
    @has_permissions(manage_channels=True)
    async def poster(self: "Servers", ctx: Context):
        """Set up automatic avatar posting"""

        await ctx.send_help()

    @poster.command(
        name="add",
        usage="(channel) (option)",
        example="#pfps female",
        aliases=["create"],
    )
    @has_permissions(manage_channels=True)
    async def poster_add(
        self,
        ctx: Context,
        channel: TextChannel | Thread,
        *,
        option: Literal["female", "male", "anime", "soft", "edgy", "banner"],
    ):
        """Add an avatar posting channel"""

        if (
            await self.bot.db.fetchval(
                "SELECT COUNT(*) FROM poster_channels WHERE guild_id = $1 AND channel_id = $2",
                ctx.guild.id,
                channel.id,
            )
        ) >= 2:
            return await ctx.error(
                f"You're only allowed to have **2 categories** per channel"
            )

        try:
            await self.bot.db.execute(
                "INSERT INTO poster_channels VALUES ($1, $2, $3)",
                ctx.guild.id,
                channel.id,
                option,
            )
        except:
            return await ctx.error(
                f"There is already an **avatar poster** for `{option}`"
            )

        return await ctx.approve(
            f"Now posting `{option}` avatars in {channel.mention}"
            if not option in ("banner")
            else f"Now posting `{option}s` in {channel.mention}"
        )

    @poster.command(
        name="remove",
        usage="(option)",
        example="female",
        aliases=["delete", "del", "rm"],
    )
    @has_permissions(manage_channels=True)
    async def poster_remove(
        self,
        ctx: Context,
        *,
        option: Literal["female", "male", "anime", "soft", "edgy", "banner"],
    ):
        """Remove an avatar posting channel"""

        if not await self.bot.db.fetchrow(
            "SELECT * FROM poster_channels WHERE guild_id = $1 AND option = $2",
            ctx.guild.id,
            option,
        ):
            return await ctx.error(f"There isn't an **avatar poster** for `{option}`")

        try:
            await self.bot.db.execute(
                "DELETE FROM poster_channels WHERE guild_id = $1 AND option = $2",
                ctx.guild.id,
                option,
            )
        except:
            return await ctx.error(f"There isn't an **avatar poster** for `{option}`")

        return await ctx.approve(
            f"No longer posting `{option}` avatars"
            if not option in ("banner")
            else f"No longer posting `{option}s`"
        )

    @poster.command(
        name="reset",
        aliases=["clear"],
    )
    @has_permissions(manage_channels=True)
    async def poster_reset(self: "Servers", ctx: Context):
        """Reset all avatar posting channels"""

        await ctx.prompt("Are you sure you want to remove all **avatar posters**?")

        try:
            await self.bot.db.execute(
                "DELETE FROM poster_channels WHERE guild_id = $1", ctx.guild.id
            )
        except:
            return await ctx.error("There are no **avatar posters**")

        return await ctx.approve("Removed all **avatar posters**")

    @poster.command(
        name="list",
        aliases=["show", "all"],
    )
    @has_permissions(manage_channels=True)
    async def poster_list(self: "Servers", ctx: Context):
        """View all avatar posting channels"""

        posters = [
            f"{channel.mention} - `{option}`"
            for row in await self.bot.db.fetch(
                "SELECT channel_id, option FROM poster_channels WHERE guild_id = $1",
                ctx.guild.id,
            )
            if (channel := ctx.guild.get_channel(row["channel_id"]))
            and (option := row["option"])
            and (getattr(self.bot.catalogue, option, None) is not None)
        ]
        if not posters:
            return await ctx.error("No **avatar posters** have been set up")

        await ctx.paginate(
            Embed(
                title="Avatar Posters",
                description=posters,
            )
        )

    @group(
        name="prefix",
        invoke_without_command=True,
        example="set ;",
        usage="(subcommand) <args>",
    )
    async def prefix(self: "Servers", ctx: Context) -> Message:
        """
        View guild prefix
        """

        prefix = (
            await self.bot.db.fetchval(
                """
            SELECT prefix FROM config
            WHERE guild_id = $1
            """,
                ctx.guild.id,
            )
            or config.prefix
        )

        return await ctx.neutral(f"Prefix: `{prefix}`")

    @prefix.command(
        name="set",
        usage="(prefix)",
        example="!",
        aliases=["add"],
    )
    @has_permissions(administrator=True)
    async def prefix_set(self: "Servers", ctx: Context, prefix: str) -> Message:
        """
        Set command prefix for guild
        """

        if len(prefix) > 12:
            return await ctx.error(
                "The **prefix** cannot be longer than **12 characters**!"
            )

        await self.bot.db.execute(
            """
            INSERT INTO config (
                guild_id,
                prefix
            ) VALUES ($1, $2)
            ON CONFLICT (guild_id)
            DO UPDATE SET
                prefix = EXCLUDED.prefix;
            """,
            ctx.guild.id,
            prefix.lower(),
        )

        return await ctx.approve(f"Set the **prefix** to `{prefix}`")

    @group(
        name="welcome",
        usage="(subcommand) <args>",
        example="add #chat Hi {user.mention} <3",
        aliases=["welc"],
        invoke_without_command=True,
    )
    @has_permissions(manage_guild=True)
    async def welcome(self: "Servers", ctx: Context):
        """Set up welcome messages in one or multiple channels"""

        await ctx.send_help()

    @welcome.command(
        name="add",
        usage="(channel) (message)",
        example="#chat Hi {user.mention} <3",
        parameters={
            "self_destruct": {
                "converter": int,
                "description": "The amount of seconds to wait before deleting the message",
                "minimum": 6,
                "maximum": 120,
                "aliases": ["delete_after", "delete"],
            }
        },
        aliases=["create"],
    )
    @has_permissions(manage_guild=True)
    async def welcome_add(
        self,
        ctx: Context,
        channel: TextChannel | Thread,
        *,
        message: EmbedScriptValidator,
    ):
        """Add a welcome message for a channel"""

        self_destruct = ctx.parameters.get("self_destruct")

        try:
            await self.bot.db.execute(
                """
                    INSERT INTO join_messages (
                    guild_id,
                    channel_id,
                    message,
                    self_destruct
                ) VALUES ($1, $2, $3, $4);""",
                ctx.guild.id,
                channel.id,
                str(message),
                self_destruct,
            )
        except:
            return await ctx.error(
                f"There is already a **welcome message** for {channel.mention}"
            )

        await ctx.approve(
            f"Created {message.type(bold=False)} **welcome message** for {channel.mention}"
            + (
                f"\n> Which will self destruct after {Plural(self_destruct, bold=True):second}"
                if self_destruct
                else ""
            )
        )

    @welcome.command(
        name="remove",
        usage="(channel)",
        example="#chat",
        aliases=["delete", "del", "rm"],
    )
    @has_permissions(manage_guild=True)
    async def welcome_remove(
        self: "Servers", ctx: Context, channel: TextChannel | Thread
    ):
        """Remove a welcome message for a channel"""

        try:
            await self.bot.db.execute(
                "DELETE FROM join_messages WHERE guild_id = $1 AND channel_id = $2",
                ctx.guild.id,
                channel.id,
            )
        except:
            return await ctx.error(
                f"There isn't a **welcome message** for {channel.mention}"
            )

        return await ctx.approve(
            f"Removed the **welcome message** for {channel.mention}"
        )

    @welcome.command(
        name="view",
        usage="(channel)",
        example="#chat",
        aliases=["check", "test", "emit"],
    )
    @has_permissions(manage_guild=True)
    async def welcome_view(
        self: "Servers", ctx: Context, channel: TextChannel | Thread
    ):
        """View a welcome message for a channel"""

        data = await self.bot.db.fetchrow(
            "SELECT message, self_destruct FROM join_messages WHERE guild_id = $1 AND channel_id = $2",
            ctx.guild.id,
            channel.id,
        )
        if not data:
            return await ctx.error(
                f"There isn't a **welcome message** for {channel.mention}"
            )

        message = data.get("message")
        self_destruct = data.get("self_destruct")

        await EmbedScript(message).send(
            ctx.channel,
            bot=self.bot,
            guild=ctx.guild,
            channel=ctx.channel,
            user=ctx.author,
            delete_after=self_destruct,
        )

    @welcome.command(
        name="reset",
        aliases=["clear"],
    )
    @has_permissions(manage_guild=True)
    async def welcome_reset(self: "Servers", ctx: Context):
        """Reset all welcome channels"""

        await ctx.prompt("Are you sure you want to remove all **welcome channels**?")

        try:
            await self.bot.db.execute(
                "DELETE FROM join_messages WHERE guild_id = $1", ctx.guild.id
            )
        except:
            return await ctx.error("No **welcome channels** have been set up")

        return await ctx.approve("Removed all **welcome channels**")

    @welcome.command(name="list")
    @has_permissions(manage_guild=True)
    async def welcome_list(self: "Servers", ctx: Context):
        """View all welcome channels"""

        channels = [
            self.bot.get_channel(row["channel_id"]).mention
            for row in await self.bot.db.fetch(
                "SELECT channel_id FROM join_messages WHERE guild_id = $1",
                ctx.guild.id,
            )
            if self.bot.get_channel(row["channel_id"])
        ]

        if not channels:
            return await ctx.error("No **welcome channels** have been set up")

        await ctx.paginate(Embed(title="Welcome Channels", description=channels))

    @group(
        name="goodbye",
        usage="(subcommand) <args>",
        example="add #chat Bye {user.mention} </3",
        aliases=["bye"],
        invoke_without_command=True,
    )
    @has_permissions(manage_guild=True)
    async def goodbye(self: "Servers", ctx: Context):
        """Set up goodbye messages in one or multiple channels"""

        await ctx.send_help()

    @goodbye.command(
        name="add",
        usage="(channel) (message)",
        example="#chat Bye {user.mention} </3",
        parameters={
            "self_destruct": {
                "converter": int,
                "description": "The amount of seconds to wait before deleting the message",
                "minimum": 6,
                "maximum": 120,
                "aliases": ["delete_after", "delete"],
            }
        },
        aliases=["create"],
    )
    @has_permissions(manage_guild=True)
    async def goodbye_add(
        self,
        ctx: Context,
        channel: TextChannel | Thread,
        *,
        message: EmbedScriptValidator,
    ):
        """Add a goodbye message for a channel"""

        self_destruct = ctx.parameters.get("self_destruct")

        try:
            await self.bot.db.execute(
                "INSERT INTO leave_messages VALUES($1, $2, $3, $4)",
                ctx.guild.id,
                channel.id,
                str(message),
                self_destruct,
            )
        except:
            return await ctx.error(
                f"There is already a **goodbye message** for {channel.mention}"
            )

        return await ctx.approve(
            f"Created {message.type(bold=False)} **goodbye message** for {channel.mention}"
            + (
                f"\n> Which will self destruct after {Plural(self_destruct, bold=True):second}"
                if self_destruct
                else ""
            )
        )

    @goodbye.command(
        name="remove",
        usage="(channel)",
        example="#chat",
        aliases=["delete", "del", "rm"],
    )
    @has_permissions(manage_guild=True)
    async def goodbye_remove(
        self: "Servers", ctx: Context, channel: TextChannel | Thread
    ):
        """Remove a goodbye message for a channel"""

        self_destruct = ctx.parameters.get("self_destruct")

        if not await self.bot.db.fetchrow(
            "SELECT * FROM leave_messages WHERE guild_id = $1 AND channel_id = $2",
            ctx.guild.id,
            channel.id,
        ):
            return await ctx.error(
                f"There isn't a **goodbye message** for {channel.mention}"
            )

        await self.bot.db.execute(
            "DELETE FROM leave_messages WHERE guild_id = $1 AND channel_id = $2",
            ctx.guild.id,
            channel.id,
        )

        return await ctx.approve(
            f"Removed the **goodbye message** for {channel.mention}"
        )

    @goodbye.command(
        name="view",
        usage="(channel)",
        example="#chat",
        aliases=["check", "test", "emit"],
    )
    @has_permissions(manage_guild=True)
    async def goodbye_view(
        self: "Servers", ctx: Context, channel: TextChannel | Thread
    ):
        """View a goodbye message for a channel"""

        data = await self.bot.db.fetchrow(
            "SELECT message, self_destruct FROM leave_messages WHERE guild_id = $1 AND channel_id = $2",
            ctx.guild.id,
            channel.id,
        )
        if not data:
            return await ctx.error(
                f"There isn't a **goodbye message** for {channel.mention}"
            )

        message = data.get("message")
        self_destruct = data.get("self_destruct")

        await EmbedScript(message).send(
            ctx.channel,
            bot=self.bot,
            guild=ctx.guild,
            channel=ctx.channel,
            user=ctx.author,
            delete_after=self_destruct,
        )

    @goodbye.command(
        name="reset",
        aliases=["clear"],
    )
    @has_permissions(manage_guild=True)
    async def goodbye_reset(self: "Servers", ctx: Context):
        """Reset all goodbye channels"""

        await ctx.prompt("Are you sure you want to remove all **goodbye channels**?")

        try:
            await self.bot.db.execute(
                "DELETE FROM leave_messages WHERE guild_id = $1", ctx.guild.id
            )
        except:
            return await ctx.error("No **goodbye channels** have been set up")

        return await ctx.approve("Removed all **goodbye channels**")

    @goodbye.command(name="list")
    @has_permissions(manage_guild=True)
    async def goodbye_list(self: "Servers", ctx: Context):
        """View all goodbye channels"""

        channels = [
            self.bot.get_channel(row["channel_id"]).mention
            for row in await self.bot.db.fetch(
                "SELECT channel_id FROM leave_messages WHERE guild_id = $1",
                ctx.guild.id,
            )
            if self.bot.get_channel(row["channel_id"])
        ]

        if not channels:
            return await ctx.error("No **goodbye channels** have been set up")

        await ctx.paginate(Embed(title="Goodbye Channels", description=channels))

    @group(
        name="boost",
        usage="(subcommand) <args>",
        example="add #chat Thx {user.mention} :3",
        aliases=["bst"],
        invoke_without_command=True,
    )
    @has_permissions(manage_guild=True)
    async def boost(self: "Servers", ctx: Context):
        """Set up boost messages in one or multiple channels"""

        await ctx.send_help()

    @boost.command(
        name="add",
        usage="(channel) (message)",
        example="#chat Thx {user.mention} :3",
        parameters={
            "self_destruct": {
                "converter": int,
                "description": "The amount of seconds to wait before deleting the message",
                "minimum": 6,
                "maximum": 120,
                "aliases": ["delete_after", "delete"],
            }
        },
        aliases=["create"],
    )
    @has_permissions(manage_guild=True)
    async def boost_add(
        self,
        ctx: Context,
        channel: TextChannel | Thread,
        *,
        message: EmbedScriptValidator,
    ):
        """Add a boost message for a channel"""

        self_destruct = ctx.parameters.get("self_destruct")

        try:
            await self.bot.db.execute(
                "INSERT INTO boost_messages VALUES($1, $2, $3, $4)",
                ctx.guild.id,
                channel.id,
                str(message),
                self_destruct,
            )
        except:
            return await ctx.error(
                f"There is already a **boost message** for {channel.mention}"
            )

        return await ctx.approve(
            f"Created {message.type(bold=False)} **boost message** for {channel.mention}"
            + (
                f"\n> Which will self destruct after {Plural(self_destruct, bold=True):second}"
                if self_destruct
                else ""
            )
        )

    @boost.command(
        name="remove",
        usage="(channel)",
        example="#chat",
        aliases=["delete", "del", "rm"],
    )
    @has_permissions(manage_guild=True)
    async def boost_remove(
        self: "Servers", ctx: Context, channel: TextChannel | Thread
    ):
        """Remove a boost message for a channel"""

        try:
            await self.bot.db.execute(
                "DELETE FROM boost_messages WHERE guild_id = $1 AND channel_id = $2",
                ctx.guild.id,
                channel.id,
            )
        except:
            return await ctx.error(
                f"There isn't a **boost message** for {channel.mention}"
            )

        return await ctx.approve(f"Removed the **boost message** for {channel.mention}")

    @boost.command(
        name="view",
        usage="(channel)",
        example="#chat",
        aliases=["check", "test", "emit"],
    )
    @has_permissions(manage_guild=True)
    async def boost_view(self: "Servers", ctx: Context, channel: TextChannel | Thread):
        """View a boost message for a channel"""

        data = await self.bot.db.fetchrow(
            "SELECT message, self_destruct FROM boost_messages WHERE guild_id = $1 AND channel_id = $2",
            ctx.guild.id,
            channel.id,
        )
        if not data:
            return await ctx.error(
                f"There isn't a **boost message** for {channel.mention}"
            )

        message = data.get("message")
        self_destruct = data.get("self_destruct")

        await EmbedScript(message).send(
            ctx.channel,
            bot=self.bot,
            guild=ctx.guild,
            channel=ctx.channel,
            user=ctx.author,
            delete_after=self_destruct,
        )

    @boost.command(
        name="reset",
        aliases=["clear"],
    )
    @has_permissions(manage_guild=True)
    async def boost_reset(self: "Servers", ctx: Context):
        """Reset all boost channels"""

        await ctx.prompt("Are you sure you want to remove all **boost channels**?")

        try:
            await self.bot.db.execute(
                "DELETE FROM boost_messages WHERE guild_id = $1", ctx.guild.id
            )
        except:
            return await ctx.error("No **boost channels** have been set up")

        return await ctx.approve("Removed all **boost channels**")

    @group(
        name="reaction",
        usage="(subcommand) <args>",
        example="add 🐐 caden",
        aliases=["reactiontrigger", "react", "rt"],
        invoke_without_command=True,
    )
    @has_permissions(manage_channels=True)
    async def reaction(self: "Servers", ctx: Context):
        """Set up reaction triggers"""

        await ctx.send_help()

    @reaction.command(
        name="add",
        usage="(emoji) (trigger)",
        example="🐐 caden",
        parameters={
            "strict": {
                "require_value": False,
                "description": "Only react to exact matches",
            }
        },
        aliases=["create"],
    )
    async def reaction_add(self: "Servers", ctx: Context, emoji: str, *, trigger: str):
        """Add a reaction trigger"""

        trigger = trigger.replace("-strict", "").strip()

        try:
            await ctx.message.add_reaction(emoji)
        except HTTPException:
            return await ctx.error(f"**{emoji}** is not a valid emoji")

        if (
            await self.bot.db.fetchval(
                "SELECT COUNT(*) FROM reaction_triggers WHERE guild_id = $1 AND trigger = $2",
                ctx.guild.id,
                trigger.lower(),
            )
        ) >= 3:
            return await ctx.error(
                f"You're only allowed to have **3** reactions per **trigger**"
            )

        try:
            await self.bot.db.execute(
                "INSERT INTO reaction_triggers VALUES ($1, $2, $3, $4)",
                ctx.guild.id,
                trigger,
                emoji,
                ctx.parameters.get("strict"),
            )
        except:
            return await ctx.error(
                f"There is already a **reaction trigger** for **{emoji}** on `{trigger}`"
            )

        return await ctx.approve(
            f"Added **{emoji}** as a **reaction trigger** on `{trigger}`"
            + (f" (strict match)" if ctx.parameters.get("strict") else "")
        )

    @reaction.command(
        name="remove",
        usage="(emoji) (trigger)",
        example="🐐 caden",
        aliases=["delete", "del", "rm"],
    )
    @has_permissions(manage_channels=True)
    async def reaction_remove(
        self,
        ctx: Context,
        emoji: str,
        *,
        trigger: str,
    ):
        """Remove a reaction trigger"""

        try:
            await self.bot.db.execute(
                "DELETE FROM reaction_triggers WHERE guild_id = $1 AND emoji = $3 AND trigger = $2",
                ctx.guild.id,
                trigger.lower(),
                emoji,
            )
        except:
            return await ctx.error(
                f"There isn't a **reaction trigger** for **{emoji}** on `{trigger}`"
            )

        await ctx.approve(
            f"Removed **reaction trigger** for **{emoji}** on `{trigger}`"
        )

    @reaction.command(
        name="reset",
        aliases=["clear"],
    )
    @has_permissions(manage_channels=True)
    async def reaction_reset(self: "Servers", ctx: Context):
        """Remove all reaction triggers"""

        await ctx.prompt("Are you sure you want to remove all **reaction triggers**?")

        try:
            await self.bot.db.execute(
                "DELETE FROM reaction_triggers WHERE guild_id = $1", ctx.guild.id
            )
        except:
            return await ctx.error("There are no **reaction triggers**")

        await ctx.approve("Removed all **reaction triggers**")

    @reaction.command(
        name="list",
        aliases=["show", "all"],
    )
    @has_permissions(manage_channels=True)
    async def reaction_list(self: "Servers", ctx: Context):
        """View all reaction triggers"""

        data = [
            f"**{row['trigger']}** - {', '.join(row['emojis'])} {'(strict)' if row['strict'] else ''}"
            for row in await self.bot.db.fetch(
                "SELECT trigger, array_agg(emoji) AS emojis, strict FROM reaction_triggers WHERE guild_id = $1 GROUP BY trigger, strict",
                ctx.guild.id,
            )
        ]
        if not data:
            return await ctx.error("There are no **reaction triggers**")

        await ctx.paginate(
            Embed(
                title="Reaction Triggers",
                description=data,
            )
        )

    @group(
        name="response",
        usage="(subcommand) <args>",
        example="add Hi, Hey {user} -reply",
        aliases=["autoresponder", "autoresponse", "ar"],
        invoke_without_command=True,
    )
    @has_permissions(manage_channels=True)
    async def response(self: "Servers", ctx: Context):
        """Set up automatic trigger responses"""

        await ctx.send_help()

    @response.command(
        name="add",
        usage="(trigger), (response)",
        example="Hi, Hey {user} -reply",
        parameters={
            "self_destruct": {
                "converter": int,
                "description": "The time in seconds to wait before deleting the response",
                "minimum": 1,
                "maximum": 120,
                "aliases": ["delete_after", "delete"],
            },
            "not_strict": {
                "require_value": False,
                "description": "Whether the trigger can be anywhere in the message",
            },
            "ignore_command_check": {
                "require_value": False,
                "description": "Whether to allow the trigger if it exists as a command",
                "aliases": ["ignore_command"],
            },
            "reply": {
                "require_value": False,
                "description": "Whether to reply to the trigger message",
                "aliases": ["reply_trigger"],
            },
            "delete": {
                "require_value": False,
                "description": "Whether to delete the trigger message",
                "aliases": ["delete_trigger"],
            },
        },
        aliases=["create"],
    )
    @has_permissions(manage_channels=True)
    async def response_add(
        self,
        ctx: Context,
        *,
        message: str,
    ):
        """Add a response trigger"""

        message = message.split(", ", 1)
        if len(message) != 2:
            return await ctx.error("You must specify a **trigger** and **response**")

        trigger = message[0].strip()
        response = message[1].strip()
        if not trigger:
            return await ctx.error("You must specify a **trigger**")
        elif not response:
            return await ctx.error("You must specify a **response**")

        if not (response := await EmbedScriptValidator().convert(ctx, response)):
            return

        try:
            await self.bot.db.execute(
                "INSERT INTO auto_responses (guild_id, trigger, response, self_destruct, not_strict, ignore_command_check, reply, delete) VALUES ($1,"
                " $2, $3, $4, $5, $6, $7, $8)",
                ctx.guild.id,
                trigger,
                str(response),
                ctx.parameters.get("self_destruct"),
                ctx.parameters.get("not_strict"),
                ctx.parameters.get("ignore_command_check"),
                ctx.parameters.get("reply"),
                ctx.parameters.get("delete"),
            )
        except:
            return await ctx.error(
                f"There is already a **response trigger** for `{trigger}`"
            )

        return await ctx.approve(
            f"Created {response.type(bold=False)} **response trigger** for `{trigger}` "
            + " ".join(
                f"({key.replace('_', ' ')})"
                for key, value in ctx.parameters.items()
                if value and key != "not_strict"
            )
            + (" (strict match)" if not ctx.parameters.get("not_strict") else "")
        )

    @response.command(
        name="remove",
        usage="(trigger)",
        example="Hi",
        aliases=["delete", "del", "rm"],
    )
    @has_permissions(manage_channels=True)
    async def response_remove(self: "Servers", ctx: Context, *, trigger: str):
        """Remove a response trigger"""

        try:
            await self.bot.db.execute(
                "DELETE FROM auto_responses WHERE guild_id = $1 AND lower(trigger) = $2",
                ctx.guild.id,
                trigger.lower(),
            )
        except:
            await ctx.error(f"There isn't a **response trigger** for `{trigger}`")
        else:
            await ctx.approve(f"Removed **response trigger** for `{trigger}`")

    @response.command(
        name="view",
        usage="(trigger)",
        example="Hi",
        aliases=["check", "test", "emit"],
    )
    @has_permissions(manage_channels=True)
    async def response_view(self: "Servers", ctx: Context, *, trigger: str):
        """View a response trigger"""

        data = await self.bot.db.fetchrow(
            "SELECT * FROM auto_responses WHERE guild_id = $1 AND lower(trigger) = $2",
            ctx.guild.id,
            trigger.lower(),
        )
        if not data:
            return await ctx.error(
                f"There isn't a **response trigger** for `{trigger}`"
            )

        await EmbedScript(data["response"]).send(
            ctx.channel,
            bot=self.bot,
            guild=ctx.guild,
            channel=ctx.channel,
            user=ctx.author,
        )

    @response.command(
        name="reset",
        aliases=["clear"],
    )
    @has_permissions(manage_channels=True)
    async def response_reset(self: "Servers", ctx: Context):
        """Remove all response triggers"""

        await ctx.prompt("Are you sure you want to remove all **response triggers**?")

        try:
            await self.bot.db.execute(
                "DELETE FROM auto_responses WHERE guild_id = $1", ctx.guild.id
            )
        except:
            return await ctx.error("There are no **response triggers**")

        return await ctx.approve("Removed all **response triggers**")

    @response.command(name="list", aliases=["show", "all"])
    @has_permissions(manage_channels=True)
    async def response_list(self: "Servers", ctx: Context):
        """View all response triggers"""

        data = await self.bot.db.fetch(
            "SELECT * FROM auto_responses WHERE guild_id = $1",
            ctx.guild.id,
        )
        if not data:
            return await ctx.error("There are no **response triggers**")

        await ctx.paginate(
            Embed(
                title="Response Triggers",
                description=list(
                    f"**{data['trigger']}** (strict: {'yes' if not data['not_strict'] else 'no'})"
                    for data in data
                ),
            )
        )

    @group(
        name="boosterrole",
        usage="(color) <name>",
        example="#BBAAEE 4PF",
        aliases=["boostrole", "br"],
        invoke_without_command=True,
    )
    @require_boost()
    @max_concurrency(1, BucketType.member)
    async def boosterrole(
        self,
        ctx: Context,
        color: Color,
        *,
        name: str = None,
    ):
        """Create your own color role"""

        base_role = ctx.guild.get_role(
            await self.bot.db.fetchval(
                "SELECT baserole FROM config WHERE guild_id = $1", ctx.guild.id
            )
        )
        if not base_role:
            return await ctx.error(
                f"The **base role** has not been set yet!\n> Use `{ctx.prefix}boosterrole base` to set it"
            )

        role_id = await self.bot.db.fetchval(
            "SELECT role_id FROM booster_roles WHERE guild_id = $1 AND user_id = $2",
            ctx.guild.id,
            ctx.author.id,
        )
        if not role_id or not ctx.guild.get_role(role_id):
            if len(ctx.guild.roles) >= 250:
                return await ctx.error("The **role limit** has been reached")

            role = await ctx.guild.create_role(
                name=(name[:100] if name else f"booster:{hash(ctx.author.id)}"),
                color=color,
            )
            await ctx.guild.edit_role_positions(
                {
                    role: base_role.position - 1,
                }
            )

            try:
                await ctx.author.add_roles(role, reason="Booster role")
            except Forbidden:
                await role.delete(reason="Booster role failed to assign")
                return await ctx.error(
                    "I don't have permission to **assign roles** to you"
                )

            await self.bot.db.execute(
                "INSERT INTO booster_roles (guild_id, user_id, role_id) VALUES ($1, $2, $3) ON CONFLICT (guild_id, user_id) DO UPDATE SET role_id"
                " = $3",
                ctx.guild.id,
                ctx.author.id,
                role.id,
            )
        else:
            role = ctx.guild.get_role(role_id)
            await role.edit(
                name=(name[:100] if name else role.name),
                color=color,
            )
            if not role in ctx.author.roles:
                try:
                    await ctx.author.add_roles(role, reason="Booster role")
                except Forbidden:
                    await role.delete(reason="Booster role failed to assign")
                    return await ctx.error(
                        "I don't have permission to **assign roles** to you"
                    )

        await ctx.neutral(
            f"Your **booster role color** has been set to `{color}`",
            emoji="🎨",
            color=color,
        )

    @boosterrole.command(
        name="baserole",
        usage="(role)",
        example="Booster",
        aliases=["base"],
    )
    @has_permissions(manage_roles=True)
    async def boosterrole_baserole(self: "Servers", ctx: Context, *, role: Role):
        """Set the base role for booster roles"""

        await Role().manageable(ctx, role, booster=True)

        await self.bot.db.execute(
            """
            INSERT INTO config (
                guild_id,
                baserole
            ) VALUES ($1, $2)
            ON CONFLICT (guild_id)
            DO UPDATE SET
                baserole = EXCLUDED.baserole;
            """,
            ctx.guild.id,
            role.id,
        )

        await ctx.approve(f"Set the **base role** to {role.mention}")

    @boosterrole.command(
        name="color",
        usage="(color)",
        example="#BBAAEE",
        aliases=["colour"],
    )
    @require_boost()
    async def boosterrole_color(self: "Servers", ctx: Context, *, color: Color):
        """Change the color of your booster role"""

        role_id = await self.bot.db.fetchval(
            "SELECT role_id FROM booster_roles WHERE guild_id = $1 AND user_id = $2",
            ctx.guild.id,
            ctx.author.id,
        )
        if not role_id or not ctx.guild.get_role(role_id):
            return await self.bot.get_command("boosterrole")(ctx, color=color)

        role = ctx.guild.get_role(role_id)
        await role.edit(
            color=color,
        )
        await ctx.neutral(
            f"Changed the **color** of your **booster role** to `{color}`", emoji="🎨"
        )

    @boosterrole.command(
        name="rename",
        usage="(name)",
        example="4PF",
        aliases=["name"],
    )
    @require_boost()
    async def boosterrole_rename(self: "Servers", ctx: Context, *, name: str):
        """Rename your booster role"""

        role_id = await self.bot.db.fetchval(
            "SELECT role_id FROM booster_roles WHERE guild_id = $1 AND user_id = $2",
            ctx.guild.id,
            ctx.author.id,
        )
        if not role_id or not ctx.guild.get_role(role_id):
            return await ctx.error("You don't have a **booster role** yet")

        role = ctx.guild.get_role(role_id)
        await role.edit(
            name=name[:100],
        )
        await ctx.approve(f"Renamed your **booster role** to **{name}**")

    @boosterrole.command(
        name="cleanup",
        parameters={
            "boosters": {
                "require_value": False,
                "description": "Whether to include boosters",
                "aliases": ["all"],
            }
        },
        aliases=["clean", "purge"],
    )
    @has_permissions(manage_roles=True)
    @cooldown(1, 60, BucketType.guild)
    @max_concurrency(1, BucketType.guild)
    async def boosterrole_cleanup(self: "Servers", ctx: Context):
        """Clean up booster roles which aren't boosting"""

        if ctx.parameters.get("boosters"):
            await ctx.prompt(
                "Are you sure you want to **remove all booster roles** in this server?\n> This includes members which are still **boosting** the"
                " server!"
            )

        async with ctx.typing():
            cleaned = []
            for row in await self.bot.db.fetch(
                "SELECT * FROM booster_roles WHERE guild_id = $1", ctx.guild.id
            ):
                member = ctx.guild.get_member(row["user_id"])
                role = ctx.guild.get_role(row["role_id"])
                if not role:
                    cleaned.append(row)
                    continue
                if ctx.parameters.get("boosters"):
                    with suppress(HTTPException):
                        await role.delete(reason=f"Booster role cleanup ({ctx.author})")

                    cleaned.append(row)
                elif not member or not member.premium_since:
                    with suppress(HTTPException):
                        await role.delete(reason="Member no longer boosting")

                    cleaned.append(row)
                elif member and not role in member.roles:
                    with suppress(HTTPException):
                        await role.delete(reason="Member doesn't have role")

                    cleaned.append(row)

            if cleaned:
                await self.bot.db.execute(
                    "DELETE FROM booster_roles WHERE guild_id = $1 AND user_id = ANY($2)",
                    ctx.guild.id,
                    [row["user_id"] for row in cleaned],
                )
                return await ctx.approve(
                    f"Cleaned up **{Plural(cleaned):booster role}**"
                )

        await ctx.error("There are no **booster roles** to clean up")

    @boosterrole.command(
        name="remove",
        aliases=["delete", "del", "rm"],
    )
    @require_boost()
    async def boosterrole_remove(self: "Servers", ctx: Context):
        """Remove your booster role"""

        role_id = await self.bot.db.fetchval(
            "SELECT role_id FROM booster_roles WHERE guild_id = $1 AND user_id = $2",
            ctx.guild.id,
            ctx.author.id,
        )
        if not role_id or not ctx.guild.get_role(role_id):
            return await ctx.error("You don't have a **booster role** yet")

        role = ctx.guild.get_role(role_id)
        await role.delete(reason="Booster role removed")
        await self.bot.db.execute(
            "DELETE FROM booster_roles WHERE guild_id = $1 AND user_id = $2",
            ctx.guild.id,
            ctx.author.id,
        )
        await ctx.approve("Removed your **booster role**")

    @boosterrole.command(
        name="icon",
        usage="(icon)",
        example="🦅",
        aliases=["emoji"],
    )
    @require_boost()
    async def boosterrole_icon(
        self,
        ctx: Context,
        *,
        icon: Literal["remove", "reset", "off"] | EmojiFinder | ImageFinder = None,
    ):
        """Change the icon of your booster role"""

        if "ROLE_ICONS" not in ctx.guild.features:
            return await ctx.error(
                "This server doesn't have enough **boosts** to use **role icons**"
            )
        if not icon:
            icon = await ImageFinder.search(ctx)
        elif isinstance(icon, str) and icon in ("remove", "reset", "off"):
            icon = None

        role_id = await self.bot.db.fetchval(
            "SELECT role_id FROM booster_roles WHERE guild_id = $1 AND user_id = $2",
            ctx.guild.id,
            ctx.author.id,
        )
        if not role_id or not ctx.guild.get_role(role_id):
            return await ctx.error("You don't have a **booster role** yet")

        role = ctx.guild.get_role(role_id)

        _icon = None
        if type(icon) in (Emoji, str):
            response = await self.bot.session.get(
                icon if not isinstance(icon, Emoji) else icon.url
            )
            _icon = await response.read()
        else:
            if not role.display_icon:
                return await ctx.error(
                    f"Your **booster role** doesn't have an **icon** yet"
                )

        await role.edit(
            display_icon=_icon,
        )
        if icon:
            return await ctx.approve(
                f"Changed the **icon** of your **booster role** to {f'{icon}' if isinstance(icon, Emoji) else f'[**image**]({icon})'}"
            )

        return await ctx.approve("Removed the **icon** of your **booster role**")

    @command(name="jaillog", usage="<channel>", example="#jail-log", aliases=["modlog"])
    @has_permissions(manage_guild=True)
    async def jaillog(
        self: "Servers", ctx: Context, *, channel: TextChannel | Thread = None
    ):
        """Set the moderation log channel"""

        if not channel:
            jail_log = await self.bot.db.fetchval(
                "SELECT jail_log FROM config WHERE guild_id = $1", ctx.guild.id
            )
            channel = self.bot.get_channel(jail_log)
            if not channel:
                return await ctx.send_help()
            else:
                await ctx.neutral(
                    f"The `jail-log` channel is bound to {channel.mention}"
                )
        else:
            await self.bot.db.execute(
                """
                INSERT INTO config (
                    guild_id,
                    jail_log
                ) VALUES ($1, $2)
                ON CONFLICT (guild_id)
                DO UPDATE SET
                    jail_log = EXCLUDED.jail_log;
                """,
                ctx.guild.id,
                channel.id,
            )
            await ctx.react_check()

    @command(
        name="resetcases",
        aliases=["resetcs"],
    )
    @has_permissions(manage_guild=True)
    async def resetcases(self: "Servers", ctx: Context):
        """Reset the all moderation cases"""

        if not await self.bot.db.fetchval(
            "SELECT COUNT(*) FROM cases WHERE guild_id = $1", ctx.guild.id
        ):
            return await ctx.error("There aren't any **moderation cases** to reset")

        await ctx.prompt("Are you sure you want to reset all **moderation cases**?")

        await self.bot.db.execute(
            "DELETE FROM cases WHERE guild_id = $1",
            ctx.guild.id,
        )

        return await ctx.approve("Reset all **moderation cases**")

    @group(
        name="invoke",
        usage="(command) (embed script)",
        example="ban 🚬 - {reason}",
        invoke_without_command=True,
    )
    @has_permissions(manage_guild=True)
    async def invoke(
        self: "Servers", ctx: Context, command: str, *, script: EmbedScriptValidator
    ):
        """Set a custom message for a moderation command"""

        _command = command.replace(".", " ")
        if command := self.bot.get_command(_command, "Moderation"):
            if command.qualified_name in ("role", "emoji"):
                return await ctx.error(
                    f"You must specify a **subcommand** for the `{command.qualified_name}` command"
                )
            elif command.qualified_name in (
                "audit",
                "role icon",
                "emoji list",
                "emoji remove duplicates",
                "sticker list",
            ) or command.qualified_name.startswith(
                ("purge", "lockdown ignore", "history", "slowmode")
            ):
                return await ctx.error(
                    f"You aren't allowed to set an **invoke message** for the `{command.qualified_name}` command"
                )

            configuration = await self.bot.fetch_config(ctx.guild.id, "invoke") or {}
            configuration[command.qualified_name.replace(" ", ".")] = str(script)
            await self.bot.update_config(ctx.guild.id, "invoke", configuration)

            await ctx.approve(
                f"Set the **{command.qualified_name}** invoke message to {script.type()}"
            )
        else:
            await ctx.error(f"Command `{_command}` doesn't exist")

    @invoke.command(
        name="reset",
        usage="(command)",
        example="ban",
        aliases=["remove"],
    )
    @has_permissions(manage_guild=True)
    async def invoke_reset(self: "Servers", ctx: Context, *, command: str):
        """Reset the custom message for a moderation command"""

        _command = command.replace(".", " ")
        if command := self.bot.get_command(_command, "Moderation"):
            if command.qualified_name == "role":
                return await ctx.error(
                    f"You must specify a **subcommand** for the `role` command"
                )

            configuration = await self.bot.fetch_config(ctx.guild.id, "invoke") or {}
            if command.qualified_name.replace(" ", ".") in configuration:
                del configuration[command.qualified_name.replace(" ", ".")]
                await self.bot.update_config(ctx.guild.id, "invoke", configuration)

                await ctx.approve(
                    f"Reset the **{command.qualified_name}** invoke message"
                )
            else:
                await ctx.error(
                    f"The **{command.qualified_name}** invoke message is not set"
                )
        else:
            await ctx.error(f"Command `{_command}` doesn't exist")

    @group(
        name="alias",
        usage="(subcommand) <args>",
        example="add deport ban",
        invoke_without_command=True,
    )
    @has_permissions(manage_guild=True)
    async def alias(self: "Servers", ctx: Context):
        """Set a custom alias for commands"""

        await ctx.send_help()

    @alias.command(
        name="add",
        usage="(alias) (command)",
        example="deport ban",
        aliases=["create"],
    )
    @has_permissions(manage_guild=True)
    async def alias_add(self: "Servers", ctx: Context, alias: str, *, command: str):
        """Add a custom alias for a command"""

        alias = alias.lower().replace(" ", "")
        if self.bot.get_command(alias):
            return await ctx.error(f"Command for alias `{alias}` already exists")

        _command = self.bot.get_command(STRING.match(command).group())
        if not _command:
            return await ctx.error(f"Command `{command}` does not exist")

        if not await self.bot.db.fetchval(
            "SELECT * FROM aliases WHERE guild_id = $1 AND alias = $2",
            ctx.guild.id,
            alias,
        ):
            await self.bot.db.execute(
                "INSERT INTO aliases (guild_id, alias, command, invoke) VALUES ($1, $2, $3, $4)",
                ctx.guild.id,
                alias,
                _command.qualified_name,
                command,
            )

            return await ctx.approve(f"Added alias `{alias}` for command `{_command}`")

        return await ctx.error(f"Alias `{alias}` already exists")

    @alias.command(
        name="remove",
        usage="(alias)",
        example="deport",
        aliases=["delete", "del", "rm"],
    )
    @has_permissions(manage_guild=True)
    async def alias_remove(self: "Servers", ctx: Context, alias: str):
        """Remove a bound alias"""

        alias = alias.lower().replace(" ", "")

        if not await self.bot.db.fetchval(
            "SELECT * FROM aliases WHERE guild_id = $1 AND alias = $2",
            ctx.guild.id,
            alias,
        ):
            return await ctx.error(f"Alias `{alias}` doesn't exist")

        await self.bot.db.execute(
            "DELETE FROM aliases WHERE guild_id = $1 AND alias = $2",
            ctx.guild.id,
            alias,
        )

        await ctx.approve(f"Removed alias `{alias}`")

    @alias.command(
        name="reset",
        usage="<command>",
        example="ban",
        aliases=["clear"],
    )
    @has_permissions(manage_guild=True)
    async def alias_reset(self: "Servers", ctx: Context, *, command: Command = None):
        """Remove every bound alias"""

        if not command:
            await ctx.prompt("Are you sure you want to remove all bound **aliases**?")
            await self.bot.db.execute(
                "DELETE FROM aliases WHERE guild_id = $1",
                ctx.guild.id,
            )
            return await ctx.approve(f"Reset all **aliases**")

        if not await self.bot.db.fetchval(
            "SELECT * FROM aliases WHERE guild_id = $1 AND command = $2",
            ctx.guild.id,
            command.qualified_name,
        ):
            return await ctx.error(f"There aren't any aliases for command `{command}`")

        await ctx.prompt(
            f"Are you sure you want to remove all bound **aliases** for `{command.qualified_name}`?"
        )

        await self.bot.db.execute(
            "DELETE FROM aliases WHERE guild_id = $1 AND command = $2",
            ctx.guild.id,
            command.qualified_name,
        )

        await ctx.approve(f"Reset all **aliases** for `{command.qualified_name}`")

    @alias.command(
        name="list",
        usage="<command>",
        example="ban",
        aliases=["show", "all"],
    )
    @has_permissions(manage_guild=True)
    async def alias_list(self: "Servers", ctx: Context, *, command: Command = None):
        """View all bound aliases"""

        if command:
            aliases = [
                f"`{row['alias']}` bound to `{row['command']}`"
                for row in await self.bot.db.fetch(
                    "SELECT alias, command FROM aliases WHERE guild_id = $1 AND command = $2",
                    ctx.guild.id,
                    command.qualified_name,
                )
                if not self.bot.get_command(row["alias"])
            ]
            if not aliases:
                return await ctx.error(
                    f"No aliases have been **assigned** to command `{command.qualified_name}`"
                )

        aliases = [
            f"`{row['alias']}` bound to `{row['command']}`"
            for row in await self.bot.db.fetch(
                "SELECT alias, command FROM aliases WHERE guild_id = $1",
                ctx.guild.id,
            )
            if self.bot.get_command(row["command"])
            and not self.bot.get_command(row["alias"])
        ]
        if not aliases:
            return await ctx.error(f"No aliases have been **assigned**")

        await ctx.paginate(Embed(title="Command Aliases", description=aliases))

    @group(
        name="reskin",
        usage="(subcommand) <args>",
        example="name Destroy Lonely",
        invoke_without_command=True,
    )
    async def reskin(self: "Servers", ctx: Context):
        """Customize the bot's appearance"""

        await ctx.send_help()

    @reskin.command(
        name="setup",
        aliases=["webhooks"],
    )
    @donator()
    @has_permissions(manage_guild=True)
    @cooldown(1, 600, BucketType.guild)
    async def reskin_setup(self: "Servers", ctx: Context):
        """Set up the reskin webhooks"""

        await ctx.prompt(
            "Are you sure you want to set up the **reskin webhooks**?\n> This will create a webhook in **every channel** in the server!"
        )

        configuration = await self.bot.fetch_config(ctx.guild.id, "reskin") or {}
        configuration["status"] = True
        webhooks = configuration.get("webhooks", {})

        async with ctx.typing():
            tasks = list()
            for channel in ctx.guild.text_channels:
                if any(
                    ext in channel.name.lower()
                    for ext in ("ticket", "log", "discrim", "bleed")
                ) or (
                    channel.category
                    and any(
                        ext in channel.category.name.lower()
                        for ext in (
                            "tickets",
                            "logs",
                            "pfps",
                            "pfp",
                            "icons",
                            "icon",
                            "banners",
                            "banner",
                        )
                    )
                ):
                    continue

                tasks.append(configure_reskin(self.bot, channel, webhooks))

            gathered = await gather(*tasks)
            created = [webhook for webhook in gathered if webhook]

        configuration["webhooks"] = webhooks
        await self.bot.update_config(ctx.guild.id, "reskin", configuration)

        if not created:
            return await ctx.error(
                "No **webhooks** were created"
                + (
                    str(gathered)
                    if ctx.author.id in self.bot.owner_ids and any(gathered)
                    else ""
                )
            )

        await ctx.approve(
            f"The **reskin webhooks** have been set across **{Plural(created):channel}**"
        )

    @reskin.command(
        name="disable",
    )
    @has_permissions(manage_guild=True)
    async def reskin_disable(self: "Servers", ctx: Context):
        """Disable the reskin webhooks"""

        configuration = await self.bot.fetch_config(ctx.guild.id, "reskin") or {}
        if not configuration.get("status"):
            return await ctx.error("Reskin webhooks are already **disabled**")

        configuration["status"] = False
        await self.bot.update_config(ctx.guild.id, "reskin", configuration)
        await ctx.approve("Disabled **reskin** across the server")

    @reskin.command(
        name="name",
        usage="(username)",
        example="Destroy Lonely",
        aliases=["username"],
    )
    @donator()
    async def reskin_name(self: "Servers", ctx: Context, *, username: str):
        """Change your personal reskin username"""

        configuration = await self.bot.fetch_config(ctx.guild.id, "reskin") or {}
        if not configuration.get("status"):
            return await ctx.error(
                f"Reskin webhooks are **disabled**\n> Use `{ctx.prefix}reskin setup` to set them up"
            )

        if len(username) > 32:
            return await ctx.error("Your name can't be longer than **32 characters**")

        await self.bot.db.execute(
            "INSERT INTO reskin (user_id, username) VALUES ($1, $2) ON CONFLICT (user_id) DO UPDATE SET username = $2",
            ctx.author.id,
            username,
        )
        await ctx.approve(f"Changed your **reskin username** to **{username}**")

    @reskin.command(
        name="avatar",
        usage="(image)",
        example="https://i.imgur.com/0X0X0X0.png",
        aliases=["icon", "av"],
    )
    @donator()
    async def reskin_avatar(
        self: "Servers", ctx: Context, *, image: ImageFinderStrict = None
    ):
        """Change your personal reskin avatar"""

        image = image or await ImageFinderStrict.search(ctx)

        configuration = await self.bot.fetch_config(ctx.guild.id, "reskin") or {}
        if not configuration.get("status"):
            return await ctx.error(
                f"Reskin webhooks are **disabled**\n> Use `{ctx.prefix}reskin setup` to set them up"
            )

        await self.bot.db.execute(
            "INSERT INTO reskin (user_id, avatar_url) VALUES ($1, $2) ON CONFLICT (user_id) DO UPDATE SET avatar_url = $2",
            ctx.author.id,
            image,
        )
        await ctx.approve(f"Changed your **reskin avatar** to [**image**]({image})")

    @reskin.group(
        name="color",
        usage="(option) (color)",
        example="main BBAAEE",
        aliases=["colour"],
        invoke_without_command=True,
    )
    @donator()
    async def reskin_color(
        self,
        ctx: Context,
        option: Literal["main", "approve", "error", "load", "all"],
        color: Color,
    ):
        """Change your personal reskin embed colors"""

        configuration = await self.bot.fetch_config(ctx.guild.id, "reskin") or {}
        if not configuration.get("status"):
            return await ctx.error(
                f"Reskin webhooks are **disabled**\n> Use `{ctx.prefix}reskin setup` to set them up"
            )

        colors = (
            await self.bot.db.fetchval(
                "SELECT colors FROM reskin WHERE user_id = $1", ctx.author.id
            )
            or {}
        )
        if option == "all":
            colors = {
                "main": color.value,
                "approve": color.value,
                "error": color.value,
                "load": color.value,
            }
        else:
            colors[option] = color.value

        await self.bot.db.execute(
            "INSERT INTO reskin (user_id, colors) VALUES ($1, $2) ON CONFLICT (user_id) DO UPDATE SET colors = $2",
            ctx.author.id,
            colors,
        )
        await ctx.approve(
            f"Changed your **reskin color** for "
            + (
                f"**{option}** to `{color}`"
                if option != "all"
                else f"all **embeds** to `{color}`"
            )
        )

    @reskin_color.command(
        name="reset",
        usage="(option)",
        example="all",
        aliases=["clear"],
    )
    @donator()
    async def reskin_color_reset(
        self,
        ctx: Context,
        option: Literal["main", "approve", "error", "load", "all"],
    ):
        """Reset your personal reskin embed colors"""

        configuration = await self.bot.fetch_config(ctx.guild.id, "reskin") or {}
        if not configuration.get("status"):
            return await ctx.error(
                f"Reskin webhooks are **disabled**\n> Use `{ctx.prefix}reskin setup` to set them up"
            )

        colors = (
            await self.bot.db.fetchval(
                "SELECT colors FROM reskin WHERE user_id = $1", ctx.author.id
            )
            or {}
        )
        if option == "all":
            colors = {}
        else:
            colors.pop(option, None)

        await self.bot.db.execute(
            "INSERT INTO reskin (user_id, colors) VALUES ($1, $2) ON CONFLICT (user_id) DO UPDATE SET colors = $2",
            ctx.author.id,
            colors,
        )
        await ctx.approve(
            f"Reset your **reskin color** for "
            + (f"**{option}**" if option != "all" else f"all **embeds**")
        )

    @reskin.command(
        name="remove",
        aliases=["delete", "reset"],
    )
    @donator()
    async def reskin_remove(self: "Servers", ctx: Context):
        """Remove your personal reskin"""

        if not await self.bot.db.fetchval(
            "SELECT * FROM reskin WHERE user_id = $1", ctx.author.id
        ):
            return await ctx.error("You don't have a **reskin** yet")

        await self.bot.db.execute(
            "DELETE FROM reskin WHERE user_id = $1", ctx.author.id
        )
        await ctx.approve("Removed your **reskin**")

    @group(
        name="autorole",
        usage="(subcommand) <args>",
        example="add @Member",
        aliases=["welcrole"],
        invoke_without_command=True,
    )
    @has_permissions(manage_roles=True)
    async def autorole(self: "Servers", ctx: Context):
        """Automatically assign roles to new members"""

        await ctx.send_help()

    @autorole.command(
        name="add",
        usage="(role)",
        example="@Member",
        parameters={
            "humans": {
                "require_value": False,
                "description": "Only assign the role to humans",
                "aliases": ["human"],
            },
            "bots": {
                "require_value": False,
                "description": "Only assign the role to bots",
                "aliases": ["bot"],
            },
        },
        aliases=["create"],
    )
    @has_permissions(manage_roles=True)
    async def autorole_add(self: "Servers", ctx: Context, role: Role):
        """Add a role to be assigned to new members"""

        if await self.bot.db.fetchval(
            "SELECT * FROM autorole WHERE guild_id = $1 AND role_id = $2",
            ctx.guild.id,
            role.id,
        ):
            return await ctx.error(
                f"The role {role.mention} is already being **assigned** to new members"
            )

        await Role().manageable(ctx, role)
        if not ctx.parameters.get("bots"):
            await Role().dangerous(ctx, role, "assign")

        await self.bot.db.execute(
            "INSERT INTO autorole (guild_id, role_id, humans, bots) VALUES ($1, $2, $3, $4)",
            ctx.guild.id,
            role.id,
            ctx.parameters.get("humans"),
            ctx.parameters.get("bots"),
        )

        return await ctx.approve(
            f"Now assigning {role.mention} to new members"
            + (f" (humans)" if ctx.parameters.get("humans") else "")
            + (f" (bots)" if ctx.parameters.get("bots") else "")
        )

    @autorole.command(
        name="remove",
        usage="(role)",
        example="@Member",
        aliases=["delete", "del", "rm"],
    )
    @has_permissions(manage_roles=True)
    async def autorole_remove(self: "Servers", ctx: Context, *, role: Role):
        """Remove a role from being assigned to new members"""

        if not await self.bot.db.fetchval(
            "SELECT * FROM autorole WHERE guild_id = $1 AND role_id = $2",
            ctx.guild.id,
            role.id,
        ):
            return await ctx.error(
                f"The role {role.mention} is not being **assigned** to new members"
            )

        await self.bot.db.execute(
            "DELETE FROM autorole WHERE guild_id = $1 AND role_id = $2",
            ctx.guild.id,
            role.id,
        )

        await ctx.approve(f"No longer assigning {role.mention} to new members")

    @autorole.command(name="reset", aliases=["clear"])
    @has_permissions(manage_roles=True)
    async def autorole_reset(self: "Servers", ctx: Context):
        """Remove every role which is being assigned to new members"""

        if not await self.bot.db.fetchval(
            "SELECT COUNT(*) FROM autorole WHERE guild_id = $1", ctx.guild.id
        ):
            return await ctx.error("No roles are being **assigned** to new members")

        await ctx.prompt("Are you sure you want to remove all **assigned roles**?")

        await self.bot.db.execute(
            "DELETE FROM autorole WHERE guild_id = $1",
            ctx.guild.id,
        )
        await ctx.approve("No longer **assigning** any roles to new members")

    @autorole.command(name="list", aliases=["show", "all"])
    @has_permissions(manage_roles=True)
    async def autorole_list(self: "Servers", ctx: Context):
        """View all the roles being assigned to new members"""

        roles = [
            ctx.guild.get_role(row.get("role_id")).mention
            + (f" (humans)" if row.get("humans") else "")
            + (f" (bots)" if row.get("bots") else "")
            for row in await self.bot.db.fetch(
                "SELECT role_id, humans, bots FROM autorole WHERE guild_id = $1",
                ctx.guild.id,
            )
            if ctx.guild.get_role(row.get("role_id"))
        ]
        if not roles:
            return await ctx.error("No roles are being **assigned** to new members")

        await ctx.paginate(
            Embed(
                title="Auto Roles",
                description=roles,
            )
        )

    @group(
        name="sticky",
        usage="(subcommand) <args>",
        example="add #selfie Oh look at me!",
        aliases=["stickymessage", "sm"],
        invoke_without_command=True,
    )
    @has_permissions(manage_guild=True)
    async def sticky(self: "Servers", ctx: Context):
        """Set up sticky messages in one or multiple channels"""

        await ctx.send_help()

    @sticky.command(
        name="add",
        usage="(channel) (message)",
        example="#selfie Oh look at me!",
        parameters={
            "schedule": {
                "converter": str,
                "description": "Waits until chat is inactive to repost the message",
                "aliases": ["timer", "time", "activity"],
            }
        },
        aliases=["create"],
    )
    @has_permissions(manage_guild=True)
    async def sticky_add(
        self,
        ctx: Context,
        channel: TextChannel | Thread,
        *,
        message: EmbedScriptValidator,
    ):
        """Add a sticky message for a channel"""

        if schedule := ctx.parameters.get("schedule"):
            schedule = await TimeConverter().convert(ctx, schedule)
            if schedule.seconds < 30 or schedule.seconds > 3600:
                return await ctx.error(
                    "The **activity schedule** must be between **30 seconds** and **1 hour**"
                )
        else:
            schedule = None

        _message = await message.send(
            channel,
            bot=self.bot,
            guild=ctx.guild,
            channel=channel,
            user=ctx.author,
        )

        try:
            await self.bot.db.execute(
                "INSERT INTO sticky_messages (guild_id, channel_id, message_id, message, schedule) VALUES ($1, $2, $3, $4, $5)",
                ctx.guild.id,
                channel.id,
                _message.id,
                str(message),
                schedule.seconds if schedule else None,
            )
        except:
            return await ctx.error(
                f"There is already a **sticky message** for {channel.mention}"
            )

        await ctx.approve(
            f"Created {message.type(bold=False)} [**sticky message**]({_message.jump_url}) for {channel.mention}"
            + (f" with an **activity schedule** of **{schedule}**" if schedule else "")
        )

    @sticky.command(
        name="remove",
        usage="(channel)",
        example="#selfie",
        aliases=["delete", "del", "rm"],
    )
    @has_permissions(manage_guild=True)
    async def sticky_remove(
        self: "Servers", ctx: Context, channel: TextChannel | Thread
    ):
        """Remove a sticky message for a channel"""

        if not await self.bot.db.fetchval(
            "SELECT * FROM sticky_messages WHERE guild_id = $1 AND channel_id = $2",
            ctx.guild.id,
            channel.id,
        ):
            return await ctx.error(
                f"There isn't a **sticky message** for {channel.mention}"
            )

        await self.bot.db.execute(
            "DELETE FROM sticky_messages WHERE guild_id = $1 AND channel_id = $2",
            ctx.guild.id,
            channel.id,
        )
        await ctx.approve(f"Removed the **sticky message** for {channel.mention}")

    @sticky.command(
        name="view",
        usage="(channel)",
        example="#selfie",
        aliases=["check", "test", "emit"],
    )
    @has_permissions(manage_guild=True)
    async def sticky_view(self: "Servers", ctx: Context, channel: TextChannel | Thread):
        """View a sticky message for a channel"""

        data = await self.bot.db.fetchrow(
            "SELECT message FROM sticky_messages WHERE guild_id = $1 AND channel_id = $2",
            ctx.guild.id,
            channel.id,
        )
        if not data:
            return await ctx.error(
                f"There isn't a **sticky message** for {channel.mention}"
            )

        message = data.get("message")

        await EmbedScript(message).send(
            ctx.channel,
            bot=self.bot,
            guild=ctx.guild,
            channel=ctx.channel,
            user=ctx.author,
        )

    @sticky.command(
        name="reset",
        aliases=["clear"],
    )
    @has_permissions(manage_guild=True)
    async def sticky_reset(self: "Servers", ctx: Context):
        """Reset all sticky messages"""

        if not await self.bot.db.fetchval(
            "SELECT COUNT(*) FROM sticky_messages WHERE guild_id = $1", ctx.guild.id
        ):
            return await ctx.error("No **sticky messages** have been set up")

        await ctx.prompt("Are you sure you want to remove all **sticky messages**?")

        await self.bot.db.execute(
            "DELETE FROM sticky_messages WHERE guild_id = $1",
            ctx.guild.id,
        )
        await ctx.approve("Removed all **sticky messages**")

    @sticky.command(
        name="list",
        aliases=["show", "all"],
    )
    @has_permissions(manage_guild=True)
    async def sticky_list(self: "Servers", ctx: Context):
        """View all sticky messages"""

        messages = [
            f"{channel.mention} - [`{row['message_id']}`]({channel.get_partial_message(row['message_id']).jump_url})"
            for row in await self.bot.db.fetch(
                "SELECT channel_id, message_id FROM sticky_messages WHERE guild_id = $1",
                ctx.guild.id,
            )
            if (channel := self.bot.get_channel(row.get("channel_id")))
        ]
        if not messages:
            return await ctx.error("No **sticky messages** have been set up")

        await ctx.paginate(
            Embed(
                title="Sticky Messages",
                description=messages,
            )
        )

    @group(
        name="fakepermissions",
        usage="(subcommand) <args>",
        example="grant @Moderator manage_messages",
        aliases=["fakeperms", "fp"],
        invoke_without_command=True,
    )
    @has_permissions(guild_owner=True)
    async def fakepermissions(self: "Servers", ctx: Context):
        """Set up fake permissions for roles"""

        await ctx.send_help()

    @fakepermissions.command(
        name="grant",
        usage="(role) (permission)",
        example="@Moderator manage_messages",
        aliases=["allow", "add"],
    )
    @has_permissions(guild_owner=True)
    async def fakepermissions_grant(
        self: "Servers", ctx: Context, role: Role, *, permission: str
    ):
        """Grant a role a fake permission"""

        permission = permission.replace(" ", "_").lower()
        if not permission in dict(ctx.author.guild_permissions):
            return await ctx.error(f"Permission `{permission}` doesn't exist")

        try:
            await self.bot.db.execute(
                "INSERT INTO fake_permissions (guild_id, role_id, permission) VALUES ($1, $2, $3)",
                ctx.guild.id,
                role.id,
                permission,
            )
        except:
            return await ctx.error(
                f"The role {role.mention} already has fake permission `{permission}`"
            )

        return await ctx.approve(
            f"Granted {role.mention} fake permission `{permission}`"
        )

    @fakepermissions.command(
        name="revoke",
        usage="(role) (permission)",
        example="@Moderator manage_messages",
        aliases=["remove", "delete", "del", "rm"],
    )
    @has_permissions(guild_owner=True)
    async def fakepermissions_revoke(
        self, ctx: Context, role: Role, *, permission: str
    ):
        """Revoke a fake permission from a role"""

        permission = permission.replace(" ", "_").lower()
        if not permission in dict(ctx.author.guild_permissions):
            return await ctx.error(f"Permission `{permission}` doesn't exist")

        if not await self.bot.db.fetchval(
            "SELECT COUNT(*) FROM fake_permissions WHERE guild_id = $1 AND role_id = $2 AND permission = $3",
            ctx.guild.id,
            role.id,
            permission,
        ):
            return await ctx.error(
                f"The role {role.mention} doesn't have fake permission `{permission}`"
            )

        await self.bot.db.execute(
            "DELETE FROM fake_permissions WHERE guild_id = $1 AND role_id = $2 AND permission = $3",
            ctx.guild.id,
            role.id,
            permission,
        )

        await ctx.approve(f"Revoked fake permission `{permission}` from {role.mention}")

    @fakepermissions.command(name="reset", aliases=["clear"])
    @has_permissions(guild_owner=True)
    async def fakepermissions_reset(self: "Servers", ctx: Context):
        """Remove every fake permission from every role"""

        await ctx.prompt("Are you sure you want to remove all **fake permissions**?")

        if not await self.bot.db.fetchval(
            "SELECT COUNT(*) FROM fake_permissions WHERE guild_id = $1", ctx.guild.id
        ):
            return await ctx.error("There aren't any **fake permissions** to remove")

        await self.bot.db.execute(
            "DELETE FROM fake_permissions WHERE guild_id = $1",
            ctx.guild.id,
        )
        await ctx.approve("Removed all **fake permissions**")

    @fakepermissions.command(name="list", aliases=["show", "all"])
    @has_permissions(guild_owner=True)
    async def fakepermissions_list(self: "Servers", ctx: Context):
        """View all roles with fake permissions"""

        roles = [
            f"{role.mention} - {', '.join([f'`{permission}`' for permission in permissions])}"
            for row in await self.bot.db.fetch(
                "SELECT role_id, array_agg(permission) AS permissions FROM fake_permissions WHERE guild_id = $1 GROUP BY role_id",
                ctx.guild.id,
            )
            if (role := ctx.guild.get_role(row["role_id"]))
            and (permissions := row["permissions"])
        ]
        if not roles:
            return await ctx.error("There aren't any roles with **fake permissions**")

        await ctx.paginate(
            Embed(
                title="Fake Permissions",
                description=roles,
            )
        )

    @group(
        name="ignore",
        usage="(subcommand) <args>",
        example="add caden",
        invoke_without_command=True,
    )
    @has_permissions(manage_guild=True)
    async def ignore(self: "Servers", ctx: Context):
        """Ignore commands from a member"""

        await ctx.send_help()

    @ignore.command(
        name="add",
        usage="(member or channel)",
        example="caden",
        aliases=["create"],
    )
    @has_permissions(manage_guild=True)
    async def ignore_add(
        self: "Servers", ctx: Context, *, target: Member | TextChannel
    ):
        """Add a member to be ignored"""

        if isinstance(target, Member):
            await Member().hierarchy(ctx, target)
            if target.guild_permissions.administrator:
                return await ctx.error(f"You can't ignore **administrators**")

        try:
            await self.bot.db.execute(
                "INSERT INTO commands.ignored VALUES ($1, $2)",
                ctx.guild.id,
                target.id,
            )
        except:
            return await ctx.error(
                f"The {'member' if isinstance(target, Member) else 'channel'} {target.mention} is already being **ignored**"
            )

        return await ctx.approve(
            f"Now ignoring commands {'from' if isinstance(target, Member) else 'in'} {target.mention}"
        )

    @ignore.command(
        name="remove",
        usage="(member or channel)",
        example="caden",
        aliases=["delete", "del", "rm"],
    )
    @has_permissions(manage_guild=True)
    async def ignore_remove(
        self: "Servers", ctx: Context, *, target: Member | TextChannel
    ):
        """Remove a member from being ignored"""

        if not await self.bot.db.fetchval(
            "SELECT * FROM commands.ignored WHERE guild_id = $1 AND target_id = $2",
            ctx.guild.id,
            target.id,
        ):
            return await ctx.error(
                f"The {'member' if isinstance(target, Member) else 'channel'} {target.mention} is not being **ignored**"
            )

        await self.bot.db.execute(
            "DELETE FROM commands.ignored WHERE guild_id = $1 AND target_id = $2",
            ctx.guild.id,
            target.id,
        )
        return await ctx.approve(
            f"No longer ignoring commands {'from' if isinstance(target, Member) else 'in'} {target.mention}"
        )

    @ignore.command(name="reset", aliases=["clear"])
    @has_permissions(manage_guild=True)
    async def ignore_reset(self: "Servers", ctx: Context):
        """Reset all ignored members"""

        if not await self.bot.db.fetchval(
            "SELECT COUNT(*) FROM commands.ignored WHERE guild_id = $1", ctx.guild.id
        ):
            return await ctx.error("No members are being **ignored**")

        await ctx.prompt("Are you sure you want to **reset** the ignore list?")

        await self.bot.db.execute(
            "DELETE FROM commands.ignored WHERE guild_id = $1",
            ctx.guild.id,
        )
        return await ctx.approve("No longer **ignoring** any members")

    @ignore.command(name="list", aliases=["show", "all"])
    @has_permissions(manage_guild=True)
    async def ignore_list(self: "Servers", ctx: Context):
        """View all ignored members"""

        ignored = [
            target.mention
            for row in await self.bot.db.fetch(
                "SELECT target_id FROM commands.ignored WHERE guild_id = $1",
                ctx.guild.id,
            )
            if (
                target := ctx.guild.get_member(row.get("target_id"))
                or ctx.guild.get_channel(row.get("target_id"))
            )
        ]
        if not ignored:
            return await ctx.error("No members are being **ignored**")

        await ctx.paginate(
            Embed(
                title="Ignored",
                description=ignored,
            )
        )

    @group(
        name="command",
        usage="(subcommand) <args>",
        example="disable #spam blunt",
        aliases=["cmd"],
        invoke_without_command=True,
    )
    @has_permissions(manage_guild=True)
    async def command(self: "Servers", ctx: Context):
        """Manage command usability"""

        await ctx.send_help()

    @command.group(
        name="enable",
        usage="(channel or 'all') (command)",
        example="all blunt",
        aliases=["unlock"],
    )
    @has_permissions(manage_guild=True)
    async def command_enable(
        self,
        ctx: Context,
        channel: TextChannel | Thread | Literal["all"],
        *,
        command: Command,
    ):
        """Enable a previously disabled command"""

        disabled_channels = await self.bot.db.fetch(
            "SELECT channel_id FROM commands.disabled WHERE guild_id = $1 AND command = $2",
            ctx.guild.id,
            command.qualified_name,
        )

        if channel == "all":
            try:
                await self.bot.db.execute(
                    "DELETE FROM commands.disabled WHERE guild_id = $1 AND command = $2",
                    ctx.guild.id,
                    command.qualified_name,
                )
            except:
                return await ctx.error(
                    f"Command `{command.qualified_name}` is already enabled in every channel"
                )
        else:
            try:
                await self.bot.db.execute(
                    "DELETE FROM commands.disabled WHERE guild_id = $1 AND channel_id = $2 AND command = $3",
                    ctx.guild.id,
                    channel.id,
                    command.qualified_name,
                )
            except:
                return await ctx.error(
                    f"Command `{command.qualified_name}` is already enabled in {channel.mention}"
                )

        await ctx.approve(
            f"Command `{command.qualified_name}` has been enabled in "
            + (
                f"**{Plural(len(disabled_channels)):channel}**"
                if channel == "all"
                else channel.mention
            )
        )

    @command.group(
        name="disable",
        usage="(channel or 'all') (command)",
        example="#spam blunt",
        aliases=["lock"],
        invoke_without_command=True,
    )
    @has_permissions(manage_guild=True)
    async def command_disable(
        self,
        ctx: Context,
        channel: TextChannel | Thread | Literal["all"],
        *,
        command: Command,
    ):
        """Disable a command in a channel"""

        if command.qualified_name.startswith("command"):
            return await ctx.error(f"You can't disable this **command**")

        disabled_channels = await self.bot.db.fetch(
            "SELECT channel_id FROM commands.disabled WHERE guild_id = $1 AND command = $2",
            ctx.guild.id,
            command.qualified_name,
        )

        if channel == "all":
            await self.bot.db.executemany(
                "INSERT INTO commands.disabled (guild_id, channel_id, command) VALUES($1, $2, $3) ON CONFLICT (guild_id, channel_id, command) DO"
                " NOTHING",
                [
                    (
                        ctx.guild.id,
                        _channel.id,
                        command.qualified_name,
                    )
                    for _channel in ctx.guild.text_channels
                ],
            )
        else:
            try:
                await self.bot.db.execute(
                    "INSERT INTO commands.disabled (guild_id, channel_id, command) VALUES($1, $2, $3)",
                    ctx.guild.id,
                    channel.id,
                    command.qualified_name,
                )
            except:
                return await ctx.error(
                    f"Command `{command.qualified_name}` is already disabled in {channel.mention}"
                )

        if channel == "all" and len(ctx.guild.text_channels) == len(disabled_channels):
            return await ctx.error(
                f"Command `{command.qualified_name}` is already disabled in every channel"
            )

        await ctx.approve(
            f"Command `{command.qualified_name}` has been disabled in "
            + (
                f"** {Plural(len(disabled_channels) - len(ctx.guild.text_channels)):channel}** "
                + (
                    f"(already disabled in {len(disabled_channels)})"
                    if disabled_channels
                    else ""
                )
                if channel == "all"
                else channel.mention
            )
        )

    @command_disable.command(
        name="list",
        aliases=["show", "view"],
    )
    @has_permissions(manage_guild=True)
    async def command_disable_list(self: "Servers", ctx: Context):
        """View all disabled commands"""

        commands = [
            f"`{row['command']}` - {self.bot.get_channel(row['channel_id']).mention}"
            for row in await self.bot.db.fetch(
                "SELECT channel_id, command FROM commands.disabled WHERE guild_id = $1",
                ctx.guild.id,
            )
            if self.bot.get_command(row["command"])
            and self.bot.get_channel(row["channel_id"])
        ]
        if not commands:
            return await ctx.error(f"No commands have been **disabled**")

        await ctx.paginate(
            Embed(
                title="Disabled Commands",
                description=commands,
            )
        )

    @command.group(
        name="restrict",
        usage="(role) (command)",
        example="Moderator snipe",
        aliases=["permit"],
        invoke_without_command=True,
    )
    @has_permissions(manage_guild=True)
    async def command_restrict(
        self: "Servers", ctx: Context, role: Role, *, command: Command
    ):
        """Restrict a command to certain roles"""

        if command.qualified_name.startswith("command"):
            return await ctx.error(f"You can't restrict this **command**")

        try:
            await self.bot.db.execute(
                "INSERT INTO commands.restricted (guild_id, role_id, command) VALUES($1, $2, $3)",
                ctx.guild.id,
                role.id,
                command.qualified_name,
            )
        except:
            await self.bot.db.execute(
                "DELETE FROM commands.restricted WHERE guild_id = $1 AND role_id = $2 AND command = $3",
                ctx.guild.id,
                role.id,
                command.qualified_name,
            )
            return await ctx.approve(
                f"Removed restriction for {role.mention} on `{command.qualified_name}`"
            )

        await ctx.approve(
            f"Allowing users with {role.mention} to use `{command.qualified_name}`"
        )

    @command_restrict.command(
        name="list",
        aliases=["show", "view"],
    )
    @has_permissions(manage_guild=True)
    async def command_restrict_list(self: "Servers", ctx: Context):
        """View all restricted commands"""

        commands = [
            f"`{row['command']}` - {ctx.guild.get_role(row['role_id']).mention}"
            for row in await self.bot.db.fetch(
                "SELECT role_id, command FROM commands.restricted WHERE guild_id = $1",
                ctx.guild.id,
            )
            if self.bot.get_command(row["command"])
            and ctx.guild.get_role(row["role_id"])
        ]
        if not commands:
            return await ctx.error(f"No commands have been **restricted**")

        await ctx.paginate(
            Embed(
                title="Restricted Commands",
                description=commands,
            )
        )

    @group(
        name="gallery",
        usage="(subcommand) <args>",
        example="add #selfie",
        aliases=["imageonly", "io"],
        invoke_without_command=True,
    )
    @has_permissions(manage_guild=True)
    async def gallery(self: "Servers", ctx: Context):
        """Set up image only channels"""

        await ctx.send_help()

    @gallery.command(
        name="add",
        usage="(channel)",
        example="#selfie",
        aliases=["create"],
    )
    @has_permissions(manage_guild=True)
    async def gallery_add(self: "Servers", ctx: Context, channel: TextChannel | Thread):
        """Add a channel to be image only"""

        if await self.bot.db.fetchval(
            "SELECT * FROM gallery_channels WHERE guild_id = $1 AND channel_id = $2",
            ctx.guild.id,
            channel.id,
        ):
            return await ctx.error(
                f"{channel.mention} is already a **gallery** channel"
            )

        await self.bot.db.execute(
            "INSERT INTO gallery_channels (guild_id, channel_id) VALUES ($1, $2)",
            ctx.guild.id,
            channel.id,
        )

        await ctx.approve(f"{channel.mention} is now a **gallery** channel")

    @gallery.command(
        name="remove",
        usage="(channel)",
        example="#selfie",
        aliases=["delete", "del", "rm"],
    )
    @has_permissions(manage_guild=True)
    async def gallery_remove(
        self: "Servers", ctx: Context, channel: TextChannel | Thread
    ):
        """Remove a channel from being image only"""

        if not await self.bot.db.fetchval(
            "SELECT * FROM gallery_channels WHERE guild_id = $1 AND channel_id = $2",
            ctx.guild.id,
            channel.id,
        ):
            return await ctx.error(f"{channel.mention} is not a **gallery** channel")

        await self.bot.db.execute(
            "DELETE FROM gallery_channels WHERE guild_id = $1 AND channel_id = $2",
            ctx.guild.id,
            channel.id,
        )

        await ctx.approve(f"{channel.mention} is no longer a **gallery** channel")

    @gallery.command(name="reset", aliases=["clear"])
    @has_permissions(manage_guild=True)
    async def gallery_reset(self: "Servers", ctx: Context):
        """Reset all image only channels"""

        if not await self.bot.db.fetchval(
            "SELECT COUNT(*) FROM gallery_channels WHERE guild_id = $1", ctx.guild.id
        ):
            return await ctx.error("No channels are set **gallery only**")

        await ctx.prompt("Are you sure you want to remove all **gallery** channels?")

        await self.bot.db.execute(
            "DELETE FROM gallery_channels WHERE guild_id = $1",
            ctx.guild.id,
        )
        await ctx.approve("No longer **gallery**")

    @gallery.command(name="list", aliases=["show", "all"])
    @has_permissions(manage_guild=True)
    async def gallery_list(self: "Servers", ctx: Context):
        """View all image only channels"""

        channels = [
            channel.mention
            for row in await self.bot.db.fetch(
                "SELECT channel_id FROM gallery_channels WHERE guild_id = $1",
                ctx.guild.id,
            )
            if (channel := self.bot.get_channel(row.get("channel_id")))
        ]
        if not channels:
            return await ctx.error("No channels are **gallery**")

        await ctx.paginate(
            Embed(
                title="Image Only Channels",
                description=channels,
            )
        )
