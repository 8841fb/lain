from typing import Literal
from contextlib import suppress

from discord import (
    Embed,
    Message,
    Guild,
    Member,
    User,
    Permissions,
    HTTPException,
    Object,
    Invite,
)
from discord.ext.commands import command, group
from discord.utils import format_dt, utcnow, oauth_url
from datetime import timedelta

from tools.utilities import Plural

import config
from tools.managers.cog import Cog
from tools.managers.context import Context


class Developer(Cog):
    """Cog for Developer commands."""

    async def cog_check(self: "Developer", ctx: Context) -> bool:
        return super().cog_check(ctx) and ctx.author.id in config.owners

    # Listener to see if user is hardbanned
    @Cog.listener("on_member_join")
    async def hardban_listener(self, member: Member):
        if await self.bot.db.fetchval(
            "SELECT user_id FROM hardban WHERE user_id = $1", member.id
        ):
            await member.ban(reason="Hard banned by developer")

    @command(
        name="metrics",
        usage="<guild or user>",
        example="/cutest",
        aliases=["topcommands"],
    )
    async def metrics(
        self: "Developer", ctx: Context, target: Guild | Member | User = None
    ):
        """View command metrics"""

        if target:
            data = await self.bot.db.fetch(
                (
                    "SELECT command, COUNT(*) AS uses FROM metrics.commands WHERE guild_id = $1 GROUP BY command ORDER BY COUNT(*) DESC"
                    if isinstance(target, Guild)
                    else "SELECT command, COUNT(*) AS uses FROM metrics.commands WHERE user_id = $1 GROUP BY command ORDER BY COUNT(*) DESC"
                ),
                target.id,
            )
        else:
            data = await self.bot.db.fetch(
                "SELECT command, COUNT(*) AS uses FROM metrics.commands GROUP BY command ORDER BY COUNT(*) DESC"
            )

        if not data:
            return await ctx.error(
                f"There aren't any **command metrics** for `{target}`"
                if target
                else "There aren't any **command metrics**"
            )

        await ctx.paginate(
            Embed(
                title="Command Metrics" + (f" for {target}" if target else ""),
                description=list(
                    f"**{metric.get('command')}** has {Plural(metric.get('uses'), code=True):use}"
                    for metric in data
                ),
            )
        )

    @command(
        name="traceback",
        usage="(error id)",
        example="ADoMpww7GP6kp",
        aliases=["trace", "tb"],
    )
    async def traceback(self: "Developer", ctx: Context, id: str):
        """Get the traceback of an error"""

        error = await self.bot.db.fetchrow("SELECT * FROM traceback WHERE id = $1", id)
        if not error:
            return await ctx.error(f"Couldn't find an error for `{id}`")

        embed = Embed(
            title=f"Command: {error['command']}",
            description=(
                f"**Guild:** {self.bot.get_guild(error['guild_id']) or 'N/A'} (`{error['guild_id']}`)\n**User:**"
                f" {self.bot.get_user(error['user_id']) or 'N/A'} (`{error['user_id']}`)\n**Timestamp**:"
                f" {format_dt(error['timestamp'])}\n```py\n{error['traceback']}\n```"
            ),
        )

        await ctx.send(embed=embed)

    @command(
        name="me",
        usage="<amount>",
        example="all",
        aliases=["m"],
    )
    async def me(
        self: "Developer",
        ctx: Context,
        amount: int | Literal["all"] = 300,
    ):
        """Clean up your messages"""

        await ctx.message.delete()

        def check(message: Message):
            if message.created_at < (utcnow() - timedelta(days=14)):
                return False

            return message.author.id == ctx.author.id

        if amount == "all":
            await ctx.author.ban(
                delete_message_days=7,
            )
            return await ctx.guild.unban(
                ctx.author,
            )

        await ctx.channel.purge(
            limit=amount,
            check=check,
            before=ctx.message,
            bulk=True,
        )

    @group(
        name="blacklist",
        aliases=["block", "bl"],
        invoke_without_command=True,
    )
    async def blacklist(self: "Developer", ctx: Context):
        """Blacklist a user or guild"""

        await ctx.send_help()

    @blacklist.command(
        name="add",
        usage="(user)",
        example="@lain",
        aliases=["a", "append"],
    )
    async def blacklist_add(
        self: "Developer",
        ctx: Context,
        user: User | Member,
        *,
        reason: str = "No reason provided",
    ):
        """Blacklist a user"""

        try:
            await self.bot.db.execute(
                "INSERT INTO blacklist (user_id, reason) VALUES ($1, $2)",
                user.id,
                reason,
            )
        except Exception:
            return await ctx.error(f"**{user}** has already been blacklisted")

        await ctx.approve(f"Added **{user}** to the blacklist")

    @blacklist.command(
        name="remove",
        usage="(user)",
        example="lain",
        aliases=["delete", "del", "rm"],
    )
    async def blacklist_remove(self, ctx: Context, *, user: Member | User):
        """Remove a user from the blacklist"""

        try:
            await self.bot.db.execute(
                "DELETE FROM blacklist WHERE user_id = $1", user.id
            )
        except:
            return await ctx.error(f"**{user}** isn't blacklisted")

        return await ctx.approve(f"Removed **{user}** from the blacklist")

    @blacklist.command(
        name="check",
        usage="(user)",
        example="lain",
        aliases=["note"],
    )
    async def blacklist_check(self, ctx: Context, *, user: Member | User):
        """Check why a user is blacklisted"""

        note = await self.bot.db.fetchval(
            "SELECT reason FROM blacklist WHERE user_id = $1", user.id
        )
        if not note:
            return await ctx.error(f"**{user}** isn't blacklisted")

        await ctx.neutral(f"**{user}** is blacklisted for **{note}**")

    @group(
        name="donator",
        aliases=["d"],
        example="add @lain",
        invoke_without_command=True,
    )
    async def donator(self: "Developer", ctx: Context):
        """Manage the donators"""

        await ctx.send_help()

    @donator.command(
        name="add",
        usage="(user)",
        example="lain",
        aliases=["a", "append"],
    )
    async def donator_add(
        self: "Developer",
        ctx: Context,
        user: User | Member,
    ):
        """Add a donator"""

        try:
            await self.bot.db.execute(
                "INSERT INTO donators (user_id) VALUES ($1)", user.id
            )
        except Exception:
            return await ctx.error(f"**{user}** is already a **donator**")

        await ctx.approve(f"Added **{user}** to the **donators**")

    @donator.command(
        name="remove",
        usage="(user)",
        example="lain",
        aliases=["delete", "del", "rm"],
    )
    async def donator_remove(self, ctx: Context, *, user: Member | User):
        """Remove a donator"""

        if not await self.bot.db.fetchval(
            "SELECT user_id FROM donators WHERE user_id = $1", user.id
        ):
            return await ctx.error(f"**{user}** isn't a **donator**")

        await self.bot.db.execute("DELETE FROM donators WHERE user_id = $1", user.id)

        return await ctx.approve(f"Removed **{user}** from the **donators**")

    @donator.command(
        name="list",
        aliases=["l"],
    )
    async def donator_list(self, ctx: Context):
        """List all the donators"""

        donators = [
            f"**{await self.bot.fetch_user(row['user_id']) or 'Unknown User'}** (`{row['user_id']}`)"
            for row in await self.bot.db.fetch(
                "SELECT user_id FROM donators",
            )
        ]
        if not donators:
            return await ctx.error(f"There are no **donators**")

        await ctx.paginate(
            Embed(
                title="Donators",
                description=donators,
            )
        )

    @group(
        name="server",
        usage="(subcommand) <args>",
        example="add (user) (server id)",
        aliases=["whitelist", "wl", "payment", "pm"],
        invoke_without_command=True,
    )
    async def server(self, ctx: Context):
        """Manage the server whitelist"""

        await ctx.send_help()

    @server.command(
        name="add",
        usage="(user) (server id)",
        example="lain 100485716..",
        aliases=["create"],
    )
    async def server_add(
        self,
        ctx: Context,
        user: Member | User,
        server: Invite | int,
    ):
        """Add a server to the whitelist"""

        if isinstance(server, Invite):
            server = server.guild.id

        await self.bot.db.execute(
            "INSERT INTO whitelist (user_id, guild_id) VALUES ($1, $2)",
            user.id,
            server,
        )
        await ctx.approve(
            "Added whitelist for"
            f" [`{server}`]({oauth_url(self.bot.user.id, permissions=Permissions(8), guild=Object(server), disable_guild_select=True)})"
            f" under **{user}**"
        )

    @server.command(
        name="remove",
        usage="(server id)",
        example="100485716..",
        aliases=["delete", "del", "rm"],
    )
    async def server_remove(
        self,
        ctx: Context,
        server: Invite | int,
    ):
        """Remove a server from the whitelist"""

        if isinstance(server, Invite):
            server = server.guild.id

        try:
            await self.bot.db.execute(
                "DELETE FROM whitelist WHERE guild_id = $1", server
            )
        except:
            return await ctx.error(f"Couldn't find a whitelist for `{server}`")

        await ctx.approve(f"Removed whitelist for `{server}`")
        if guild := self.bot.get_guild(server):
            with suppress(HTTPException):
                await guild.leave()

    @server.command(
        name="transfer",
        usage="(user) (old id) (new id)",
        example="caden 100485716.. 108212487..",
        aliases=["move"],
    )
    async def server_transfer(
        self,
        ctx: Context,
        user: Member | User,
        old_server: Invite | int,
        server: Invite | int,
    ):
        """Transfer a server whitelist to another server"""

        if isinstance(old_server, Invite):
            old_server = old_server.guild.id
        if isinstance(server, Invite):
            server = server.guild.id

        try:
            await self.bot.db.execute(
                "UPDATE whitelist SET guild_id = $3 WHERE user_id = $1 AND guild_id = $2",
                user.id,
                old_server,
                server,
            )
        except:
            return await ctx.error(
                "Couldn't find a whitelist for"
                f" [`{old_server}`]({oauth_url(self.bot.user.id, permissions=Permissions(8), guild=Object(old_server), disable_guild_select=True)})"
                f" under **{user}**"
            )

        await ctx.approve(
            f"Transferred whitelist from `{old_server}` to"
            f" [`{server}`]({oauth_url(self.bot.user.id, permissions=Permissions(8), guild=Object(server), disable_guild_select=True)})"
        )
        if guild := self.bot.get_guild(old_server):
            with suppress(HTTPException):
                await guild.leave()

    @server.command(
        name="merge",
        usage="(old user) (user)",
        example="caden lain",
        aliases=["switch", "change"],
    )
    async def server_merge(
        self,
        ctx: Context,
        old_user: Member | User,
        user: Member | User,
    ):
        """Merge whitelists from one user to another"""

        try:
            await self.bot.db.execute(
                "UPDATE whitelist SET user_id = $2 WHERE user_id = $1",
                old_user.id,
                user.id,
            )
        except:
            return await ctx.error(f"Couldn't find any whitelists under **{old_user}**")

        return await ctx.approve(f"Merged whitelists from **{old_user}** to **{user}**")

    @server.command(
        name="check",
        usage="(server id)",
        example="100485716..",
        aliases=["view", "owner"],
    )
    async def server_check(
        self,
        ctx: Context,
        *,
        server: Invite | int,
    ):
        """Check who bought a server"""

        if isinstance(server, Invite):
            server = server.guild.id

        owner_id = await self.bot.db.fetchval(
            "SELECT user_id FROM whitelist WHERE guild_id = $1",
            server,
        )
        if not owner_id:
            return await ctx.error(f"Couldn't find a whitelist for `{server}`")

        await ctx.neutral(
            (f"**{guild}**" if (guild := self.bot.get_guild(server)) else f"`{server}`")
            + f" was purchased by **{self.bot.get_user(owner_id) or 'Unknown User'}** (`{owner_id}`)"
        )

    @server.command(
        name="list",
        usage="(user)",
        example="caden",
        aliases=["show", "all"],
    )
    async def server_list(
        self,
        ctx: Context,
        user: Member | User,
    ):
        """View whitelisted servers for a user"""

        servers = [
            f"[**{self.bot.get_guild(row['guild_id']) or 'Unknown Server'}**]({oauth_url(self.bot.user.id, permissions=Permissions(8), guild=Object(row['guild_id']), disable_guild_select=True)})"
            f" (`{row['guild_id']}`)"
            for row in await self.bot.db.fetch(
                "SELECT guild_id FROM whitelist WHERE user_id = $1",
                user.id,
            )
        ]
        if not servers:
            return await ctx.error(f"**{user}** doesn't have any whitelisted servers")

        await ctx.paginate(
            Embed(
                title="Whitelisted Servers",
                description=servers,
            )
        )

    @command(
        name="guilds",
        aliases=["servers"],
    )
    async def guilds(self, ctx: Context):
        """View all guilds lain is in"""

        await ctx.paginate(
            Embed(
                title="Guilds",
                description=list(
                    f"[**{guild}**]({oauth_url(self.bot.user.id, permissions=Permissions(8), guild=Object(guild.id), disable_guild_select=True)})"
                    f" (`{guild.id}`, `{guild.member_count:,}`)"
                    for guild in self.bot.guilds
                ),
            )
        )

    @group(
        name="hardban",
        usage="(user)",
        example="lain",
        aliases=["hb", "globalban", "gb", "global"],
        invoke_without_command=True,
    )
    async def hardban(self, ctx: Context, user: Member | User):
        """Hardban a user"""

        if await self.bot.db.fetchval(
            "SELECT user_id FROM hardban WHERE user_id = $1", user.id
        ):
            return await ctx.error(f"**{user}** is already hardbanned")

        await ctx.prompt(
            f"Are you sure you want to **hardban** {user.mention}?",
        )

        await self.bot.db.execute(
            "INSERT INTO hardban (user_id) VALUES ($1)",
            user.id,
        )

        for guild in self.bot.guilds:
            with suppress(Exception):
                await guild.ban(user, reason="Hard banned by developer")

        await ctx.message.add_reaction("✅")
        await ctx.message.add_reaction("✨")

    @hardban.command(
        name="remove",
        usage="(user)",
        example="lain",
        aliases=["delete", "del", "rm"],
    )
    async def hardban_remove(self, ctx: Context, *, user: Member | User):
        """Remove a hardban"""

        if not await self.bot.db.fetchval(
            "SELECT user_id FROM hardban WHERE user_id = $1", user.id
        ):
            return await ctx.error(f"**{user}** isn't hardbanned")

        await ctx.prompt(
            f"Are you sure you want to **remove** the hardban for **{user}**?",
        )

        await self.bot.db.execute(
            "DELETE FROM hardban WHERE user_id = $1",
            user.id,
        )

        await ctx.message.add_reaction("✅")
        await ctx.message.add_reaction("✨")

    @hardban.command(
        name="list",
        aliases=["l"],
    )
    async def hardban_list(self, ctx: Context):
        """List all the hardbanned users"""

        hardbans = [
            f"**{await self.bot.fetch_user(row['user_id']) or 'Unknown User'}** (`{row['user_id']}`)"
            for row in await self.bot.db.fetch(
                "SELECT user_id FROM hardban",
            )
        ]
        if not hardbans:
            return await ctx.error(f"There are no **hardbanned users**")

        await ctx.paginate(
            Embed(
                title="Hardbanned Users",
                description=hardbans,
            )
        )
