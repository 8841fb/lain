from datetime import datetime
from textwrap import dedent

import psutil  # type: ignore
import pytz
from discord import ClientUser
from discord import Color as DiscordColor
from discord import (
    Embed,
    Guild,
    Invite,
    User,
    Member,
    Message,
    NotificationLevel,
    Role,
    Status,
)
from discord.ext.commands import (
    BucketType,
    Command,
    Group,
    command,
    cooldown,
    group,
    has_permissions,
)
from discord.utils import format_dt, utcnow
from yarl import URL

import config
from tools import services
from tools.models.instagram import InstagramProfile
from tools.converters.basic import Color, Location, Date
from tools.managers.cog import Cog
from tools.managers.context import Context
from tools.utilities.humanize import comma, size, ordinal
from tools.utilities.text import Plural, shorten, hidden


class Information(Cog):
    """Cog for information commands."""

    @command(
        name="help",
        usage="<command or module>",
        example="userinfo",
        aliases=["h"],
    )
    async def _help(self: "Information", ctx: Context, *, command: str = None):
        """View information about a command"""

        if not command:
            return await ctx.neutral(
                f"Click [**here**](https://lains.life/commands) to view **{len(set(self.bot.walk_commands()))}** commands"
            )

        _command = command
        command: Command = self.bot.get_command(_command)

        if not command:
            return await ctx.error(f"Command `{_command}` doesn't exist")

        embed = Embed(
            description=command.short_doc or "No description provided",
            color=config.Color.neutral,
        )
        embed.description += (
            f"\n>>> ```bf\nSyntax: {ctx.prefix}{command.qualified_name} {command.usage or ''}\n"
            + (
                f"Example: {ctx.prefix}{command.qualified_name} {command.example}"
                if command.example
                else ""
            )
            + "```"
        )
        embed.set_author(
            name=command.cog_name or "No category",
            icon_url=self.bot.user.display_avatar,
            url=f"https://discord.com",
        )

        embed.add_field(
            name="Aliases",
            value=", ".join([f"`{alias}`" for alias in command.aliases]) or "`N/A`",
            inline=(False if len(command.aliases) >= 4 else True),
        )
        embed.add_field(
            name="Parameters",
            value=", ".join([f"`{param}`" for param in command.clean_params])
            or "`N/A`",
            inline=True,
        )
        embed.add_field(
            name="Permissions",
            value=", ".join(
                list(
                    map(
                        lambda p: "`" + p.replace("_", " ").title() + "`",
                        await command.permissions(),
                    )
                )
            )
            or "`N/A`",
            inline=True,
        )

        if command.parameters:
            embed.add_field(
                name="Optional Parameters",
                value="\n".join(
                    [
                        "`"
                        + ("--" if parameter.get("require_value", True) else "-")
                        + f"{parameter_name}` "
                        + (
                            (
                                ("(" if not parameter.get("default") else "[")
                                + " | ".join(
                                    [
                                        f"`{choice}`"
                                        for choice in parameter.get("choices", [])
                                    ]
                                )
                                + (")" if not parameter.get("default") else "]")
                            )
                            if parameter.get("choices")
                            else (
                                (
                                    "`"
                                    + str(parameter["converter"])
                                    .split("'", 1)[1]
                                    .split("'")[0]
                                    + "`"
                                    if parameter.get("converter")
                                    else ""
                                )
                            )
                            if parameter.get("converter")
                            and not getattr(parameter.get("converter"), "__name__", "")
                            in ("int")
                            else (
                                f"(`{parameter.get('minimum', 1)}`-`{parameter.get('maximum', 100)}`)"
                                if getattr(parameter.get("converter"), "__name__", "")
                                == "int"
                                else ""
                            )
                        )
                        + f"\n> {parameter['description']}"
                        for parameter_name, parameter in command.parameters.items()
                    ]
                ),
                inline=False,
            )

        await ctx.send(embed=embed)

    @command(name="ping", aliases=["latency"])
    async def ping(self: "Information", ctx: Context) -> None:
        """View the gateway latency"""
        await ctx.neutral(f"Gateway: `{self.bot.latency * 1000:.2f}ms`")

    @command(
        name="recentmembers",
        usage="<amount>",
        example="50",
        aliases=["recentusers", "recentjoins", "newmembers", "newusers"],
    )
    @has_permissions(manage_guild=True)
    async def recentmembers(self: "Information", ctx: Context, amount: int = 50):
        """View the most recent members to join the server"""

        await ctx.paginate(
            Embed(
                title="Recent Members",
                description=list(
                    f"**{member}** - {format_dt(member.joined_at, style='R')}"
                    for member in sorted(
                        ctx.guild.members,
                        key=lambda member: member.joined_at,
                        reverse=True,
                    )[:amount]
                ),
            )
        )

    @command(name="about", aliases=["botinfo", "system", "sys"])
    @cooldown(1, 5, BucketType.user)
    async def about(self, ctx: Context):
        """View system information about lain"""

        process = psutil.Process()

        embed = Embed(
            description=(
                f"Developed by **caden#0666**"
                + f"\n**Memory:** {size(process.memory_full_info().uss)}, **CPU:** {psutil.cpu_percent()}%"
            )
        )
        embed.set_author(
            name=self.bot.user.display_name,
            icon_url=self.bot.user.display_avatar,
        )

        embed.add_field(
            name="Members",
            value=(
                f"**Total:** {comma(len(self.bot.users))}"
                + f"\n**Unique:** {comma(len(list(filter(lambda m: not m.bot, self.bot.users))))}"
                + f"\n**Online:** {comma(len(list(filter(lambda m: not isinstance(m, ClientUser) and m.status is not Status.offline, self.bot.members))))}"
            ),
            inline=True,
        )
        embed.add_field(
            name="Channels",
            value=(
                f"**Total:** {comma(len(self.bot.channels))}"
                + f"\n**Text:** {comma(len(self.bot.text_channels))}"
                + f"\n**Voice:** {comma(len(self.bot.voice_channels))}"
            ),
            inline=True,
        )
        embed.add_field(
            name="Client",
            value=(
                f"**Servers:** {comma(len(self.bot.guilds))}"
                + f"\n**Commands:** {comma(len(set(self.bot.walk_commands())))}"
            )
            + f"\n**Latency:** {self.bot.latency * 1000:.2f}ms",
            inline=True,
        )
        await ctx.send(embed=embed)

    @command(
        name="membercount",
        usage="<server>",
        example="/lain",
        aliases=["members", "mc"],
    )
    async def membercount(
        self,
        ctx: Context,
        *,
        server: Guild | Invite = None,
    ):
        """View a server's member count"""

        if isinstance(server, Invite):
            invite = server
            server = server.guild

        server = server or ctx.guild

        embed = Embed()
        embed.set_author(
            name=server,
            icon_url=server.icon,
        )

        embed.add_field(
            name="Members",
            value=(
                comma(len(server.members))
                if isinstance(server, Guild)
                else comma(invite.approximate_member_count)
            ),
            inline=True,
        )
        if isinstance(server, Guild):
            embed.add_field(
                name="Humans",
                value=comma(len(list(filter(lambda m: not m.bot, server.members)))),
                inline=True,
            )
            embed.add_field(
                name="Bots",
                value=comma(len(list(filter(lambda m: m.bot, server.members)))),
                inline=True,
            )

        else:
            embed.add_field(
                name="Online",
                value=comma(invite.approximate_presence_count),
                inline=True,
            )

        await ctx.send(embed=embed)

    @command(
        name="icon",
        usage="<server>",
        example="/lain",
        aliases=["servericon", "sicon", "guildicon", "gicon"],
    )
    async def icon(
        self,
        ctx: Context,
        *,
        server: Invite | Invite = None,
    ):
        """View a server's icon"""

        if isinstance(server, Invite):
            server = server.guild

        server = server or ctx.guild

        if not server.icon:
            return await ctx.error(f"**{server}** doesn't have an **icon**")

        embed = Embed(url=server.icon, title=f"{server}'s icon")
        embed.set_image(url=server.icon)
        await ctx.send(embed=embed)

    @command(
        name="serverbanner",
        usage="<server>",
        example="/lain",
        aliases=["sbanner", "guildbanner", "gbanner"],
    )
    async def serverbanner(
        self,
        ctx: Context,
        *,
        server: Invite | Invite = None,
    ):
        """View a server's banner"""

        if isinstance(server, Invite):
            server = server.guild

        server = server or ctx.guild

        if not server.banner:
            return await ctx.error(f"**{server}** doesn't have a **banner**")

        embed = Embed(url=server.banner, title=f"{server}'s banner")
        embed.set_image(url=server.banner)
        await ctx.send(embed=embed)

    @command(
        name="serverinfo",
        usage="<server>",
        example="/lain",
        aliases=["sinfo", "guildinfo", "ginfo", "si", "gi"],
    )
    async def serverinfo(
        self,
        ctx: Context,
        *,
        server: Invite | Invite = None,
    ):
        """View information about a server"""

        if isinstance(server, Invite):
            _invite = server
            server = server.guild
            if not self.bot.get_guild(server.id):
                return await self.bot.get_command("inviteinfo")(ctx, server=_invite)

        server = self.bot.get_guild(server.id) if server else ctx.guild

        embed = Embed(
            description=(
                format_dt(server.created_at, "f")
                + " ("
                + format_dt(server.created_at, "R")
                + ")"
            )
        )
        embed.set_author(
            name=f"{server} ({server.id})",
            icon_url=server.icon,
        )
        embed.set_image(
            url=server.banner.with_size(1024).url if server.banner else None
        )

        embed.add_field(
            name="Information",
            value=(
                f">>> **Owner:** {server.owner or server.owner_id}"
                + f"\n**Shard ID:** {server.shard_id}"
                + f"\n**Verification:** {server.verification_level.name.title()}"
                + f"\n**Notifications:** {'Mentions' if server.default_notifications == NotificationLevel.only_mentions else 'All Messages'}"
            ),
            inline=True,
        )
        embed.add_field(
            name="Statistics",
            value=(
                f">>> **Members:** {server.member_count:,}"
                + f"\n**Text Channels:** {len(server.text_channels):,}"
                + f"\n**Voice Channels:** {len(server.voice_channels):,}"
                + f"\n**Nitro Boosts:** {server.premium_subscription_count:,} (`Level {server.premium_tier}`)"
            ),
            inline=True,
        )

        if server == ctx.guild and (roles := list(reversed(server.roles[1:]))):
            embed.add_field(
                name=f"Roles ({len(roles)})",
                value=">>> "
                + ", ".join([role.mention for role in roles[:7]])
                + (f" (+{comma(len(roles) - 7)})" if len(roles) > 7 else ""),
                inline=False,
            )

        await ctx.send(embed=embed)

    @command(
        name="inviteinfo",
        usage="<server>",
        example="/lain",
        aliases=["iinfo", "ii"],
    )
    async def inviteinfo(
        self,
        ctx: Context,
        *,
        server: Invite | Invite,
    ):
        """View information about an invite"""

        if isinstance(server, Guild):
            return await self.bot.get_command("serverinfo")(ctx, server=server)
        else:
            if self.bot.get_guild(server.guild.id):
                return await self.bot.get_command("serverinfo")(
                    ctx, server=server.guild
                )

        invite = server
        server = invite.guild

        embed = Embed(
            description=(
                format_dt(server.created_at, "f")
                + " ("
                + format_dt(server.created_at, "R")
                + ")"
            )
        )
        embed.set_author(
            name=f"{server} ({server.id})",
            icon_url=server.icon,
        )
        embed.set_image(
            url=server.banner.with_size(1024).url if server.banner else None
        )

        embed.add_field(
            name="Invite",
            value=(
                f">>> **Channel:** {('#' + invite.channel.name) if invite.channel else 'N/A'}"
                + f"\n**Inviter:** {invite.inviter or 'N/A'}"
            ),
            inline=True,
        )
        embed.add_field(
            name="Server",
            value=(
                f">>> **Members:** {invite.approximate_member_count:,}"
                + f"\n**Members Online:** {invite.approximate_presence_count:,}"
            ),
            inline=True,
        )

        await ctx.send(embed=embed)

    @command(
        name="userinfo",
        usage="<user>",
        example="caden",
        aliases=["whois", "uinfo", "ui", "user"],
    )
    async def userinfo(self, ctx: Context, *, user: Member | User = None):
        """View information about a user"""

        user = user or ctx.author

        embed = Embed()
        embed.set_author(
            name=f"{user} ({user.id})",
            icon_url=user.display_avatar,
        )
        embed.set_thumbnail(url=user.display_avatar)

        embed.add_field(
            name="Account created",
            value=format_dt(user.created_at, "D")
            + "\n> "
            + format_dt(user.created_at, "R"),
            inline=True,
        )
        if isinstance(user, Member):
            embed.add_field(
                name="Joined this server",
                value=format_dt(user.joined_at, "D")
                + "\n> "
                + format_dt(user.joined_at, "R"),
                inline=True,
            )
            if user.premium_since:
                embed.add_field(
                    name="Boosted this server",
                    value=format_dt(user.premium_since, "D")
                    + "\n> "
                    + format_dt(user.premium_since, "R"),
                    inline=True,
                )
        if isinstance(user, Member):
            if roles := list(reversed(user.roles[1:])):
                embed.add_field(
                    name=f"Roles ({len(roles)})",
                    value=">>> "
                    + ", ".join([role.mention for role in roles[:7]])
                    + (f" (+{comma(len(roles) - 7)})" if len(roles) > 7 else ""),
                    inline=False,
                )
                embed.set_footer(
                    text=f"Join position: {sorted(user.guild.members, key=lambda m: m.joined_at).index(user) + 1:,}"
                )

        mutual_guilds = (
            len(self.bot.guilds)
            if user.id == self.bot.user.id
            else len(user.mutual_guilds)
        )
        if footer := embed.footer.text:
            embed.set_footer(text=footer + f" ∙ {Plural(mutual_guilds):mutual server}")
        else:
            embed.set_footer(text=f"{Plural(mutual_guilds):mutual server}")

        await ctx.send(embed=embed)

    @command(
        name="avatar",
        usage="<user>",
        example="caden",
        aliases=["av", "ab", "ag", "avi", "pfp"],
    )
    async def avatar(self, ctx: Context, *, user: Member | User = None):
        """View a user's avatar"""

        user = user or ctx.author

        embed = Embed(url=user.display_avatar.url, title=f"{user.name}'s avatar")
        embed.set_image(url=user.display_avatar)
        await ctx.send(embed=embed)

    @command(
        name="serveravatar",
        usage="<user>",
        example="caden",
        aliases=["sav", "sab", "sag", "savi", "spfp"],
    )
    async def serveravatar(self, ctx: Context, *, user: Member = None):
        """View a user's server avatar"""

        user = user or ctx.author
        if not user.guild_avatar:
            return await ctx.error(
                "You don't have a **server avatar**"
                if user == ctx.author
                else f"**{user}** doesn't have a **server avatar**"
            )

        embed = Embed(url=user.guild_avatar.url, title=f"{user.name}'s server avatar")
        embed.set_image(url=user.guild_avatar)
        await ctx.send(embed=embed)

    @command(
        name="banner",
        usage="<user>",
        example="caden",
        aliases=["ub"],
    )
    async def banner(self, ctx: Context, *, user: Member | User = None):
        """View a user's banner"""

        user = user or ctx.author
        user = await self.bot.fetch_user(user.id)
        url = (
            user.banner.url
            if user.banner
            else (
                "https://singlecolorimage.com/get/"
                + str(user.accent_color or DiscordColor(0)).replace("#", "")
                + "/400x100"
            )
        )

        embed = Embed(url=url, title=f"{user.name}'s banner")
        embed.set_image(url=url)
        await ctx.send(embed=embed)

    @command(name="emojis", aliases=["emotes"])
    async def emojis(self, ctx: Context):
        """View all emojis in the server"""

        if not ctx.guild.emojis:
            return await ctx.error("No emojis are in this **server**")

        await ctx.paginate(
            Embed(
                title=f"Emojis in {ctx.guild.name}",
                description=list(
                    f"{emoji} (`{emoji.id}`)" for emoji in ctx.guild.emojis
                ),
            )
        )

    @command(name="stickers")
    async def stickers(self, ctx: Context):
        """View all stickers in the server"""

        if not ctx.guild.stickers:
            return await ctx.error("No stickers are in this **server**")

        await ctx.paginate(
            Embed(
                title=f"Stickers in {ctx.guild.name}",
                description=list(
                    f"[**{sticker.name}**]({sticker.url}) (`{sticker.id}`)"
                    for sticker in ctx.guild.stickers
                ),
            )
        )

    @command(name="roles")
    async def roles(self, ctx: Context):
        """View all roles in the server"""

        if not ctx.guild.roles[1:]:
            return await ctx.error("No roles are in this **server**")

        await ctx.paginate(
            Embed(
                title=f"Roles in {ctx.guild.name}",
                description=list(
                    f"{role.mention} (`{role.id}`)"
                    for role in reversed(ctx.guild.roles[1:])
                ),
            )
        )

    @command(name="inrole", usage="<role>", example="helper", aliases=["hasrole"])
    async def inrole(self, ctx: Context, *, role: Role = None):
        """View all members with a role"""

        role = role or ctx.author.top_role

        if not role.members:
            return await ctx.error(f"No members have {role.mention}")

        await ctx.paginate(
            Embed(
                title=f"Members with {role.name}",
                description=list(
                    f"**{member}** (`{member.id}`)" for member in role.members
                ),
            )
        )

    @command(
        name="boosters",
        aliases=["boosts"],
        invoke_without_command=True,
    )
    async def boosters(self, ctx: Context):
        """View all members boosting the server"""

        members = list(
            sorted(
                filter(
                    lambda m: m.premium_since,
                    ctx.guild.members,
                ),
                key=lambda m: m.premium_since,
                reverse=True,
            )
        )
        if not members:
            return await ctx.error("No members are **boosting**")

        await ctx.paginate(
            Embed(
                title="Boosters",
                description=list(
                    f"**{member}** boosted {format_dt(member.premium_since, style='R')}"
                    for member in members
                ),
            )
        )

    @group(
        name="timezone",
        usage="<member>",
        example="caden",
        aliases=["time", "tz"],
        invoke_without_command=True,
    )
    async def timezone(self, ctx: Context, *, member: Member = None):
        """View a member's timezone"""

        member = member or ctx.author

        location = await self.bot.db.fetchval(
            "SELECT location FROM timezone WHERE user_id = $1", member.id
        )
        if not location:
            return await ctx.error(
                f"Your **timezone** hasn't been set yet\n> Use `{ctx.prefix}timezone set (location)` to set it"
                if member == ctx.author
                else f"**{member}** hasn't set their **timezone**"
            )

        timestamp = utcnow().astimezone(pytz.timezone(location))
        await ctx.neutral(
            f"Your current time is **{timestamp.strftime('%b %d, %I:%M %p')}**"
            if member == ctx.author
            else f"**{member}**'s current time is **{timestamp.strftime('%b %d, %I:%M %p')}**",
            emoji=":clock"
            + str(timestamp.strftime("%-I"))
            + ("30" if int(timestamp.strftime("%-M")) >= 30 else "")
            + ":",
        )

    @timezone.command(name="set", usage="(location)", example="Los Angeles")
    async def timezone_set(self, ctx: Context, *, location: Location):
        """Set your timezone"""

        await self.bot.db.execute(
            "INSERT INTO timezone (user_id, location) VALUES ($1, $2) ON CONFLICT (user_id) DO UPDATE SET location = $2",
            ctx.author.id,
            location.get("tz_id"),
        )
        await ctx.approve(
            f"Your **timezone** has been set to `{location.get('tz_id')}`"
        )

    @timezone.command(name="list")
    async def timezone_list(self, ctx: Context):
        """View all member's timezones"""

        locations = [
            f"**{ctx.guild.get_member(row.get('user_id'))}** (`{row.get('location')}`)"
            for row in await self.bot.db.fetch(
                "SELECT user_id, location FROM timezone WHERE user_id = ANY($1::BIGINT[]) ORDER BY location ASC",
                [member.id for member in ctx.guild.members],
            )
        ]

        if not locations:
            return await ctx.error("No **timezones** have been set")

        await ctx.paginate(
            Embed(
                title="Member Timezones",
                description=list(locations),
            )
        )

    @command(
        name="github",
        usage="(user)",
        example="caden",
        aliases=["gh"],
    )
    async def github(self, ctx: Context, username: str):
        """Search for a user on GitHub"""

        response = await self.bot.session.request(
            "GET",
            f"https://api.github.com/users/{username}",
            raise_for={404: f"Couldn't find a profile for **{username}**"},
        )

        embed = Embed(
            url=response.html_url,
            title=(
                f"{response.name} (@{response.login})"
                if response.name
                else response.login
            ),
            description=response.bio,
        )

        if followers := response.followers:
            embed.add_field(name="Followers", value=f"{followers:,}", inline=True)

        if following := response.following:
            embed.add_field(name="Following", value=f"{following:,}", inline=True)

        if gists := response.gists:
            embed.add_field(name="Gists", value=f"{gists:,}", inline=True)

        information = ""
        if response.location:
            information += f"\n> 🌎 [{response.location}]({URL(f'https://maps.google.com/search?q={response.company}')})"
        if response.company:
            information += f"\n> 🏢 [{response.company}]({URL(f'https://google.com/search?q={response.company}')})"
        if response.twitter_username:
            information += f"\n> 🐦 **{response.twitter_username}**"

        if information:
            embed.add_field(name="Information", value=information, inline=False)

        if response.public_repos:
            repos = await self.bot.session.request("GET", response.repos_url)

            embed.add_field(
                name=f"Repositories ({len(repos)})",
                value="\n".join(
                    [
                        f"[`⭐ {repo.stargazers_count:,},"
                        f" {datetime.strptime(repo.created_at, '%Y-%m-%dT%H:%M:%SZ').strftime('%m/%d/%y')} {repo.name}`]({repo.html_url})"
                        for repo in sorted(
                            repos, key=lambda r: r.stargazers_count, reverse=True
                        )[:3]
                    ]
                ),
                inline=False,
            )

        embed.set_thumbnail(url=response.avatar_url)
        embed.set_footer(text="Created")
        embed.timestamp = datetime.strptime(response.created_at, "%Y-%m-%dT%H:%M:%SZ")
        await ctx.send(embed=embed)

    @command(
        name="roblox",
        usage="(username)",
        example="rxflipflop",
        aliases=["rblx"],
    )
    async def roblox(self, ctx: Context, username: str) -> Message:
        """View a Roblox profile"""

        async with ctx.typing():
            data = await services.roblox.profile(
                self.bot.session,
                username=username,
            )

        embed = Embed(
            url=data.url,
            title=(
                f"{data.display_name} (@{data.username})"
                if data.username != data.display_name
                else data.username
            ),
            description=data.description,
        )
        embed.set_thumbnail(url=data.avatar_url)

        embed.add_field(
            name="Created",
            value=format_dt(
                data.created_at,
                style="D",
            ),
            inline=True,
        )
        embed.add_field(
            name="Following",
            value=f"{data.statistics.following:,}",
            inline=True,
        )
        embed.add_field(
            name="Followers",
            value=f"{data.statistics.followers:,}",
            inline=True,
        )
        embed.add_field(
            name=f"Badges ({len(data.badges)})",
            value=", ".join(data.badges),
            inline=True,
        )
        return await ctx.send(embed=embed)

    @command(
        name="xbox",
        usage="(gamertag)",
        example="wuhkr",
        aliases=["xb", "xbl"],
    )
    async def xbox(self, ctx: Context, *, gamertag: str) -> Message:
        """View a Xbox profile"""

        data = await self.bot.session.request(
            "GET",
            f"https://playerdb.co/api/player/xbox/{gamertag}",
            raise_for={500: f"**{gamertag}** is an invalid **Xbox** gamertag"},
        )

        embed = Embed(
            url=URL(f"https://xboxgamertag.com/search/{gamertag}"),
            title=data.data.player.username,
        )
        embed.set_image(
            url=URL(
                f"https://avatar-ssl.xboxlive.com/avatar/{data.data.player.username}/avatar-body.png"
            )
        )

        embed.add_field(
            name="Tenure Level",
            value=f"{int(data.data.player.meta.tenureLevel):,}",
            inline=True,
        )
        embed.add_field(
            name="Gamerscore",
            value=f"{int(data.data.player.meta.gamerscore):,}",
            inline=True,
        )
        embed.add_field(
            name="Account Tier",
            value=data.data.player.meta.accountTier,
            inline=True,
        )

        return await ctx.send(embed=embed)

    @command(name="cashapp", usage="(username)", example="madeitsick", aliases=["ca"])
    async def cashapp(self, ctx: Context, username: str):
        """View a Cash App profile"""

        async with ctx.typing():
            account = await services.cashapp.profile(
                self.bot.session,
                username=username,
            )

            embed = Embed(
                color=Color.from_str(account.avatar_url.accent_color),
                url=account.url,
                title=f"{account.display_name} ({account.cashtag})",
            )

            embed.set_thumbnail(url=account.avatar_url.image_url)
            embed.set_image(url=account.qr)
            await ctx.send(embed=embed)

    @group(
        name="snapchat",
        usage="(username)",
        example="daviddobrik",
        aliases=["snap"],
        invoke_without_command=True,
    )
    async def snapchat(self, ctx: Context, username: str) -> Message:
        """View a Snapchat profile"""

        data = await services.snapchat.profile(
            self.bot.session,
            username=username,
        )

        embed = Embed(
            url=data.url,
            title=(
                (
                    f"{data.display_name} (@{data.username})"
                    if data.username != data.display_name
                    else data.username
                )
                + " on Snapchat"
            ),
            description=data.description,
        )
        if not data.bitmoji:
            embed.set_thumbnail(url=data.snapcode)
        else:
            embed.set_image(url=data.bitmoji)

        return await ctx.send(embed=embed)

    @snapchat.command(
        name="story",
        usage="(username)",
        example="daviddobrik",
    )
    async def snapchatstory(self, ctx: Context, username: str) -> Message:
        """View public Snapchat stories"""

        data = await services.snapchat.profile(
            self.bot.session,
            username=username,
        )

        if not data.stories:
            return await ctx.error(
                f"No **story results** found for [`{username}`]({URL(f'https://snapchat.com/add/{username}')})"
            )

        await ctx.paginate(
            [
                f"**@{data.username}** — ({index + 1}/{len(data.stories)}){hidden(story.url)}"
                for index, story in enumerate(data.stories)
            ]
        )

    @group(
        name="instagram",
        usage="(username)",
        example="snoopdogg",
        aliases=["ig"],
        invoke_without_command=True,
    )
    async def instagram(self, ctx: Context, username: str) -> Message:
        """View an Instagram profile"""

        async with ctx.typing():
            try:
                user: InstagramProfile = await services.instagram.profile(
                    session=self.bot.session,
                    username=username,
                )

            except:
                return await ctx.error(
                    f"[`{username}`]({URL(f'https:///instagram.com/{username}')}) is an invalid **Instagram** user"
                )

            embed = Embed(
                url=f"https://www.instagram.com/{user.username}",
                title=(
                    (
                        f"{user.display_name} (@{user.username}) "
                        if user.display_name != ""
                        else f"@{user.username} "
                    )
                    + ("☑️" if user.statistics.verified else "")
                ),
                description=user.description,
            )

            embed.add_field(
                name="Posts",
                value=f"{user.statistics.posts:,}",
                inline=True,
            )
            embed.add_field(
                name="Followers",
                value=f"{user.statistics.followers:,}",
                inline=True,
            )
            embed.add_field(
                name="Following",
                value=f"{user.statistics.following:,}",
                inline=True,
            )
            embed.set_thumbnail(url=user.avatar_url)
            await ctx.send(embed=embed)

    @instagram.command(
        name="story",
        usage="(username)",
        example="snoopdogg",
        aliases=["stories"],
    )
    async def instagram_story(self, ctx: Context, username: str) -> Message:
        """View an Instagram profile's story"""

        async with ctx.typing():
            try:
                user: InstagramProfile = await services.instagram.profile(
                    session=self.bot.session,
                    username=username,
                )
            except:
                return await ctx.error(
                    f"[`{username}`]({URL(f'https:///instagram.com/{username}')}) is an invalid **Instagram** user"
                )

            story = await services.instagram.reels(
                session=self.bot.session,
                username=username,
                user_id=user.id,
            )

            if not story:
                return await ctx.error(
                    f"[**{user.username}**](https://instagram.com/{user.username}) doesn't have an active **story**."
                )

            return await ctx.paginate(
                [
                    f"**@{user.username}** — <t:{x.taken}:R> ({i + 1}/{len(story.reels)}){hidden(x.media_url)}"
                    for i, x in enumerate(story.reels)
                ]
            )

    @group(
        name="birthday",
        usage="<member>",
        example="caden",
        aliases=["bday", "bd"],
        invoke_without_command=True,
    )
    async def birthday(self, ctx: Context, *, member: Member = None):
        """View a member's birthday"""

        member = member or ctx.author

        birthday = await self.bot.db.fetchval(
            "SELECT date FROM birthday WHERE user_id = $1", member.id
        )
        if not birthday:
            return await ctx.error(
                f"Your **birthday** hasn't been set yet\n> Use `{ctx.prefix}birthday set (date)` to set it"
                if member == ctx.author
                else f"**{member}** hasn't set their **birthday**"
            )

        location = await self.bot.db.fetchval(
            "SELECT location FROM timezone WHERE user_id = $1", member.id
        )
        if location:
            current = utcnow().astimezone(pytz.timezone(location))
        else:
            current = utcnow()

        next_birthday = current.replace(
            year=current.year + 1,
            month=birthday.month,
            day=birthday.day,
        )
        if next_birthday.day == current.day and next_birthday.month == current.month:
            phrase = "**today**, happy birthday! 🎊"
        elif (
            next_birthday.day + 1 == current.day
            and next_birthday.month == current.month
        ):
            phrase = "**tomorrow**, happy early birthday! 🎊"
        else:
            days_until_birthday = (next_birthday - current).days
            if days_until_birthday > 365:
                next_birthday = current.replace(
                    year=current.year,
                    month=birthday.month,
                    day=birthday.day,
                )
                days_until_birthday = (next_birthday - current).days

            phrase = (
                f"**{next_birthday.strftime('%B')} {ordinal(next_birthday.day)}**, that's in"
                f" **{Plural(days_until_birthday):day}**!"
            )

        await ctx.neutral(
            f"Your birthday is {phrase}"
            if member == ctx.author
            else f"**{member}**'s birthday is {phrase}",
            emoji="🎂",
        )

    @birthday.command(name="set", usage="(date)", example="December 5th")
    async def birthday_set(self, ctx: Context, *, birthday: Date):
        """Set your birthday"""

        await self.bot.db.execute(
            "INSERT INTO birthday (user_id, date) VALUES ($1, $2) ON CONFLICT (user_id) DO UPDATE SET date = $2",
            ctx.author.id,
            birthday,
        )
        await ctx.approve(
            f"Your **birthday** has been set to **{birthday.strftime('%B')} {ordinal(int(birthday.strftime('%-d')))}**"
        )

    @birthday.command(name="list", aliases=["all"])
    async def birthday_list(self, ctx: Context):
        """View all member birthdays"""

        birthdays = [
            f"**{member}** - {birthday.strftime('%B')} {ordinal(int(birthday.strftime('%-d')))}"
            for row in await self.bot.db.fetch(
                "SELECT * FROM birthday WHERE user_id = ANY($1::BIGINT[]) ORDER BY EXTRACT(MONTH FROM date), EXTRACT(DAY FROM date)",
                [member.id for member in ctx.guild.members],
            )
            if (member := ctx.guild.get_member(row.get("user_id")))
            and (birthday := row.get("date"))
        ]
        if not birthdays:
            return await ctx.error("No **birthdays** have been set")

        await ctx.paginate(
            Embed(
                title="Member Birthdays",
                description=birthdays,
            )
        )
