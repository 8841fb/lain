from typing import List

from discord import (
    Message,
    VoiceState,
    HTTPException,
    Member,
    Role,
    CategoryChannel,
    RateLimited,
)
from discord.ext.commands import (
    group,
    has_permissions,
    CommandError,
    cooldown,
    BucketType,
)


from tools.managers.cog import Cog
from tools.managers.context import Context
from tools.managers.ratelimit import ratelimiter
from tools.converters.basic import Region, Bitrate


class VoiceMaster(Cog):
    """Cog for VoiceMaster commands."""

    async def cog_load(self) -> None:
        schedule_deletion: List[int] = list()

        for row in await self.bot.db.fetch(
            """
            SELECT channel_id FROM voicemaster.channels
            """
        ):
            channel_id: int = row.get("channel_id")
            if channel := self.bot.get_channel(channel_id):
                if not channel.members:
                    try:
                        await channel.delete(reason="VoiceMaster Channel Cleanup")
                    except HTTPException:
                        pass

                    schedule_deletion.append(channel_id)

            else:
                schedule_deletion.append(channel_id)

        if schedule_deletion:
            for channel_id in schedule_deletion:
                await self.bot.db.execute(
                    """
                    DELETE FROM voicemaster.channels
                    WHERE channel_id = $1
                    """,
                    channel_id,
                )

    @Cog.listener("on_voice_state_update")
    async def create_channel(
        self, member: Member, before: VoiceState, after: VoiceState
    ) -> None:
        if not after.channel:
            return

        elif before and before.channel == after.channel:
            return

        elif not (
            configuration := await self.bot.db.fetchrow(
                """
                SELECT * FROM voicemaster.configuration
                WHERE guild_id = $1
                """,
                member.guild.id,
            )
        ):
            return

        elif configuration.get("channel_id") != after.channel.id:
            return

        if retry_after := ratelimiter(
            "voicemaster:create",
            key=member,
            rate=1,
            per=10,
        ):
            try:
                await member.move_to(None)
            except HTTPException:
                pass

            return

        channel = await member.guild.create_voice_channel(
            name=f"{member.display_name}'s channel",
            category=(
                member.guild.get_channel(configuration.get("category_id"))
                or after.channel.category
            ),
            bitrate=(
                (
                    bitrate := configuration.get(
                        "bitrate", int(member.guild.bitrate_limit)
                    )
                )
                and (
                    bitrate
                    if bitrate <= int(member.guild.bitrate_limit)
                    else int(member.guild.bitrate_limit)
                )
            ),
            rtc_region=configuration.get("region"),
            reason=f"VoiceMaster Creation: {member}",
        )

        try:
            await member.move_to(
                channel,
                reason=f"VoiceMaster Creation: {member}",
            )
        except HTTPException:
            return await channel.delete(
                reason=f"VoiceMaster Creation Failure: {member}"
            )

        await channel.set_permissions(
            member,
            read_messages=True,
            connect=True,
            reason=f"VoiceMaster Creation: {member}",
        )

        await self.bot.db.execute(
            """
            INSERT INTO voicemaster.channels (
                guild_id,
                channel_id,
                owner_id
            ) VALUES ($1, $2, $3)
            """,
            member.guild.id,
            channel.id,
            member.id,
        )

        if (
            role := member.guild.get_role(configuration.get("role_id"))
        ) and not role in member.roles:
            try:
                await member.add_roles(
                    role,
                    reason=f"VoiceMaster Default Role: {member}",
                )
            except Exception:
                pass

    @Cog.listener("on_voice_state_update")
    async def remove_channel(
        self, member: Member, before: VoiceState, after: VoiceState
    ) -> None:
        if not before.channel:
            return

        elif after and before.channel == after.channel:
            return

        if (
            (
                role_id := await self.bot.db.fetchval(
                    """
                SELECT role_id FROM voicemaster.configuration
                WHERE guild_id = $1
                """,
                    member.guild.id,
                )
            )
            and role_id in (role.id for role in member.roles)
        ):
            try:
                await member.remove_roles(
                    member.guild.get_role(role_id),
                    reason=f"VoiceMaster Default Role: {member}",
                )
            except Exception:
                pass

        if list(filter(lambda m: not m.bot, before.channel.members)):
            return

        elif not (
            owner_id := await self.bot.db.fetchval(
                """
                DELETE FROM voicemaster.channels
                WHERE channel_id = $1
                RETURNING owner_id
                """,
                before.channel.id,
            )
        ):
            return

        try:
            await before.channel.delete()
        except HTTPException:
            pass

    async def cog_check(self, ctx: Context) -> bool:
        if ctx.command.qualified_name in (
            "voicemaster",
            "voicemaster setup",
            "voicemaster reset",
            "voicemaster category",
            "voicemaster default role",
            "voicemaster default region",
            "voicemaster default bitrate",
            "voicemaster default name",
        ):
            return True

        if not ctx.author.voice:
            raise CommandError("You're not in a **voice channel**")

        elif not (
            owner_id := await ctx.bot.db.fetchval(
                """
            SELECT owner_id FROM voicemaster.channels
            WHERE channel_id = $1
            """,
                ctx.author.voice.channel.id,
            )
        ):
            raise CommandError("You're not in a **VoiceMaster** channel!")

        elif ctx.command.qualified_name == "voicemaster claim":
            if ctx.author.id == owner_id:
                raise CommandError(
                    "You're already the **owner** of this **voice channel**"
                )

            elif owner_id in (member.id for member in ctx.author.voice.channel.members):
                raise CommandError("This **voice channel** is already **claimed**")

            return True

        elif ctx.author.id != owner_id:
            raise CommandError("You're not in a **VoiceMaster channel**")

        return True

    @group(
        name="voicemaster",
        usage="(subcommand) <args>",
        example="setup",
        aliases=["voice", "vm", "vc"],
        invoke_without_command=True,
    )
    async def voicemaster(self, ctx: Context):
        """Make temporary voice channels"""

        await ctx.send_help()

    @voicemaster.command(name="setup")
    @has_permissions(manage_guild=True)
    @cooldown(1, 30, BucketType.guild)
    async def voicemaster_setup(self, ctx: Context) -> Message:
        """
        Setup the VoiceMaster configuration
        """

        if await self.bot.db.fetchrow(
            """
            SELECT * FROM voicemaster.configuration
            WHERE guild_id = $1
            """,
            ctx.guild.id,
        ):
            return await ctx.error(
                f"The **VoiceMaster** channels are already setup\n> Use `{ctx.prefix}voicemaster reset` to reset the configuration"
            )

        category = await ctx.guild.create_category("Voice Channels")
        channel = await category.create_voice_channel("Join to Create")

        await self.bot.db.execute(
            """
            INSERT INTO voicemaster.configuration (
                guild_id,
                category_id,
                channel_id
            ) VALUES ($1, $2, $3)
            """,
            ctx.guild.id,
            category.id,
            channel.id,
        )

        return await ctx.approve(
            "Finished creating the **VoiceMaster** channels\n> You can move or rename them as you wish"
        )

    @voicemaster.command(name="reset", aliases=["resetserver"])
    @has_permissions(manage_guild=True)
    @cooldown(1, 60, BucketType.guild)
    async def voicemaster_reset(self, ctx: Context) -> Message:
        """
        Reset server configuration for VoiceMaster
        """

        if channel_ids := await self.bot.db.fetchrow(
            """
            DELETE FROM voicemaster.configuration
            WHERE guild_id = $1
            RETURNING category_id, channel_id
            """,
            ctx.guild.id,
        ):
            for channel in (
                channel
                for channel_id in channel_ids
                if (channel := ctx.guild.get_channel(channel_id))
            ):
                await channel.delete()

            return await ctx.approve("Reset the **VoiceMaster** configuration")

        return await ctx.error(
            f"The **VoiceMaster** channels are not setup\n> Use `{ctx.prefix}voicemaster setup` to setup the configuration"
        )

    @voicemaster.command(
        name="category",
        usage="(channel)",
        example="Voice Channels",
    )
    @has_permissions(manage_guild=True)
    async def voicemaster_category(
        self, ctx: Context, *, channel: CategoryChannel
    ) -> Message:
        """
        Set the category for VoiceMaster channels
        """

        try:
            await self.bot.db.execute(
                """
                UPDATE voicemaster.configuration
                SET category_id = $2
                WHERE guild_id = $1
                """,
                ctx.guild.id,
                channel.id,
            )
        except Exception:
            return await ctx.error(
                "Server is not configured in the **database**, you need to run `voicemaster setup` to be able to run this command"
            )

        return await ctx.approve(
            f"Set **{channel}** as the default voice channel category"
        )

    @voicemaster.group(
        name="default",
        usage="(subcommand) <args>",
        example="region us-west",
        invoke_without_command=True,
    )
    @has_permissions(manage_guild=True)
    async def voicemaster_default(self, ctx: Context) -> Message:
        """
        Set default settings for VoiceMaster channels
        """

        await ctx.send_help()

    @voicemaster_default.command(
        name="name",
        usage="(name)",
        example="priv channel",
    )
    @has_permissions(manage_guild=True)
    async def voicemaster_defaultname(self, ctx: Context, *, name: str) -> Message:
        """
        Set the default name for VoiceMaster channels
        """

        try:
            await self.bot.db.execute(
                """
                UPDATE voicemaster.configuration
                SET name = $2
                WHERE guild_id = $1
                """,
                ctx.guild.id,
                name,
            )
        except Exception:
            return await ctx.error(
                f"The **VoiceMaster** channels are not setup\n> Use `{ctx.prefix}voicemaster setup` to setup the configuration"
            )

        return await ctx.approve(f"Set the **default name** to `{name}`")

    @voicemaster_default.command(
        name="role",
        usage="(role)",
        example="VoiceMaster",
    )
    async def voicemaster_defaultrole(self, ctx: Context, role: Role) -> Message:
        """
        Set the default role for VoiceMaster channels
        """

        try:
            await self.bot.db.execute(
                """
                UPDATE voicemaster.configuration
                SET role_id = $2
                WHERE guild_id = $1
                """,
                ctx.guild.id,
                role.id,
            )
        except Exception:
            return await ctx.error(
                f"The **VoiceMaster** channels are not setup\n> Use `{ctx.prefix}voicemaster setup` to setup the configuration"
            )

        return await ctx.approve(f"Set the **default role** to {role.mention}")

    @voicemaster_default.command(
        name="region",
        usage="(region)",
        example="us-west",
    )
    async def voicemaster_defaultregion(
        self, ctx: Context, *, region: Region
    ) -> Message:
        """Set the default region for VoiceMaster channels"""

        try:
            await self.bot.db.execute(
                """
                UPDATE voicemaster.configuration
                SET region = $2
                WHERE guild_id = $1
                """,
                ctx.guild.id,
                region,
            )
        except Exception:
            return await ctx.error(
                f"The **VoiceMaster** channels are not setup\n> Use `{ctx.prefix}voicemaster setup` to setup the configuration"
            )

        return await ctx.approve(
            f"Set the **default region** to `{(region or 'Automatic').replace('-', ' ').title().replace('Us', 'US')}`"
        )

    @voicemaster_default.command(
        name="bitrate",
        usage="(bitrate)",
        example="80kbps",
    )
    @has_permissions(manage_guild=True)
    async def voicemaster_defaultbitrate(
        self, ctx: Context, *, bitrate: Bitrate
    ) -> Message:
        """
        Edit default bitrate for new Voice Channels
        """

        try:
            await self.bot.db.execute(
                """
                UPDATE voicemaster.configuration
                SET bitrate = $2
                WHERE guild_id = $1
                """,
                ctx.guild.id,
                bitrate * 1000,
            )
        except Exception:
            return await ctx.error(
                f"The **VoiceMaster** channels are not setup\n> Use `{ctx.prefix}voicemaster setup` to setup the configuration"
            )

        return await ctx.approve(f"Set the **default bitrate** to `{bitrate}kbps`")

    @voicemaster.command(name="claim")
    async def voicemaster_claim(self, ctx: Context) -> Message:
        """
        Claim an inactive voice channel
        """

        await self.bot.db.execute(
            """
            UPDATE voicemaster.channels
            SET owner_id = $2
            WHERE channel_id = $1
            """,
            ctx.author.voice.channel.id,
            ctx.author.id,
        )

        if ctx.author.voice.channel.name.endswith("channel"):
            try:
                await ctx.author.voice.channel.edit(
                    name=f"{ctx.author.display_name}'s channel"
                )
            except Exception:
                pass

        return await ctx.approve(f"You're now the **owner** of this **voice channel**")

    @voicemaster.command(
        name="transfer",
        usage="(member)",
        example="caden",
    )
    async def voicemaster_transfer(self, ctx: Context, *, member: Member) -> Message:
        """
        Transfer ownership of your channel to another member
        """

        if member == ctx.author or member.bot:
            return await ctx.send_help()

        elif not member.voice or member.voice.channel != ctx.author.voice.channel:
            return await ctx.error(f"**{member}** is not in this **voice channel**")

        await self.bot.db.execute(
            """
            UPDATE voicemaster.channels
            SET owner_id = $2
            WHERE channel_id = $1
            """,
            ctx.author.voice.channel.id,
            member.id,
        )

        if ctx.author.voice.channel.name.endswith("channel"):
            try:
                await ctx.author.voice.channel.edit(
                    name=f"{member.display_name}'s channel"
                )
            except Exception:
                pass

        return await ctx.approve(
            f"Transferred **ownership** of this **voice channel** to {member.mention}"
        )

    @voicemaster.command(
        name="name",
        usage="(new name)",
        example="priv channel",
        aliases=["rename"],
    )
    async def voicemaster_name(self, ctx: Context, *, name: str) -> Message:
        """
        Rename your voice channel
        """

        if len(name) > 100:
            return await ctx.error(
                "Your channel's name cannot be longer than **100 characters**"
            )

        try:
            await ctx.author.voice.channel.edit(
                name=name,
                reason=f"VoiceMaster: {ctx.author} renamed voice channel",
            )
        except HTTPException:
            return await ctx.error("Voice channel name cannot contain **vulgar words**")
        except RateLimited:
            return await ctx.error("You're renaming your **voice channel** too fast")
        else:
            return await ctx.approve(f"Renamed your **voice channel** to `{name}`")

    @voicemaster.command(
        name="bitrate",
        usage="(bitrate)",
        example="80kbps",
        aliases=["quality"],
    )
    async def voicemaster_bitrate(self, ctx: Context, bitrate: Bitrate) -> Message:
        """
        Edit bitrate of your voice channel
        """

        await ctx.author.voice.channel.edit(
            bitrate=bitrate * 1000,
            reason=f"VoiceMaster: {ctx.author} edited voice channel bitrate",
        )

        return await ctx.approve(
            f"Your **voice channel**'s bitrate has been updated to `{bitrate} kbps`"
        )

    @voicemaster.command(
        name="limit",
        usage="(limit)",
        example="3",
        aliases=["userlimit"],
    )
    async def voicemaster_limit(self, ctx: Context, limit: int) -> Message:
        """
        Set the user limit for your voice channel
        """

        if limit < 0 or limit > 99:
            return await ctx.error("The **user limit** must be between `0` and `99`")

        await ctx.author.voice.channel.edit(
            user_limit=limit,
            reason=f"VoiceMaster Limit: {ctx.author}",
        )

        return await ctx.approve(
            f"Set the **user limit** of your **voice channel** to `{limit or 'unlimited'}"
        )

    @voicemaster.command(name="lock")
    async def voicemaster_lock(self, ctx: Context) -> Message:
        """
        Lock your voice channel
        """

        if (
            ctx.author.voice.channel.overwrites_for(ctx.guild.default_role).connect
            is False
        ):
            return await ctx.error("Your **voice channel** is already **locked**")

        await ctx.author.voice.channel.set_permissions(
            ctx.guild.default_role, connect=False
        )
        await ctx.approve("Your **voice channel** is now **locked**")

    @voicemaster.command(name="unlock")
    async def voicemaster_unlock(self, ctx: Context) -> Message:
        """
        Unlock your voice channel
        """

        if ctx.author.voice.channel.overwrites_for(ctx.guild.default_role).connect:
            return await ctx.error("Your **voice channel** is already **unlocked**")

        await ctx.author.voice.channel.set_permissions(
            ctx.guild.default_role, connect=None
        )
        await ctx.approve("Your **voice channel** is now **unlocked**")

    @voicemaster.command(name="hide", aliases=["private", "ghost"])
    async def voicemaster_hide(self, ctx: Context):
        """Hide your voice channel from members"""

        if (
            ctx.author.voice.channel.overwrites_for(ctx.guild.default_role).view_channel
            is False
        ):
            return await ctx.error("Your **voice channel** is already **hidden**")

        await ctx.author.voice.channel.set_permissions(
            ctx.guild.default_role, view_channel=False
        )
        await ctx.approve("Your **voice channel** is now **hidden**")

    @voicemaster.command(name="reveal", aliases=["visible", "unhide", "unghost"])
    async def voicemaster_reveal(self, ctx: Context):
        """Reveal your voice channel to members"""

        if (
            ctx.author.voice.channel.overwrites_for(ctx.guild.default_role).view_channel
            is not False
        ):
            return await ctx.error("Your **voice channel** is already **visible**")

        await ctx.author.voice.channel.set_permissions(
            ctx.guild.default_role, view_channel=None
        )
        await ctx.approve("Your **voice channel** is now **visible**")
