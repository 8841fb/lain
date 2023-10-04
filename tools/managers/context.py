from io import BytesIO, StringIO
from contextlib import suppress
from copy import copy
from typing import TYPE_CHECKING, Any

from discord import Color, Embed, Guild, HTTPException, Message, File, NotFound, Member
from discord.ext.commands import CommandError
from discord.ext.commands import Context as BaseContext
from discord.ext.commands import UserInputError
from discord.utils import as_chunks, cached_property

import config
from tools.utilities.checks import donator
from tools.managers.cache import cache
from ..utilities.typing import Typing

from ..utilities.text import Plural, shorten
from . import views
from .paginator import Paginator

if TYPE_CHECKING:
    from tools.lain import lain


class Context(BaseContext):
    bot: "lain"
    guild: Guild

    @cached_property
    def parameters(self):
        data = {}
        if command := self.command:
            if parameters := command.parameters:
                for name, parameter in parameters.items():
                    data[name] = ParameterParser(self).get(name, **parameter)

        return data

    def typing(self) -> Typing:
        return Typing(self)

    @cache(ttl="1m", key="{self.message.id}", prefix="reskin")
    async def reskin(self):
        try:
            await donator().predicate(self)
        except:
            pass
        else:
            configuration = await self.bot.fetch_config(self.guild.id, "reskin") or {}
            if configuration.get("status"):
                if webhook_id := configuration["webhooks"].get(str(self.channel.id)):
                    reskin = await self.bot.db.fetchrow(
                        "SELECT username, avatar_url, colors, emojis FROM reskin WHERE user_id = $1",
                        self.author.id,
                    )
                    if reskin and (reskin.get("username") or reskin.get("avatar_url")):
                        webhook = await self.channel.reskin_webhook(webhook_id)
                        if not webhook:
                            del configuration["webhooks"][str(self.channel.id)]
                            await self.bot.update_config(
                                self.guild.id, "reskin", configuration
                            )
                        else:
                            return {
                                "username": reskin.get("username")
                                or self.bot.user.name,
                                "avatar_url": reskin.get("avatar_url")
                                or self.bot.user.display_avatar.url,
                                "colors": reskin.get("colors", {}),
                                "emojis": reskin.get("emojis", {}),
                                "webhook": webhook,
                            }

        return {}

    @cached_property
    def replied_message(self) -> Message:
        if (reference := self.message.reference) and isinstance(
            reference.resolved, Message
        ):
            return reference.resolved

    async def send(self, *args, **kwargs):
        reskin = await self.reskin()
        kwargs["files"] = kwargs.get("files") or []
        if file := kwargs.pop("file", None):
            kwargs["files"].append(file)

        if embed := kwargs.get("embed"):
            if not embed.color:
                embed.color = (
                    reskin.get("colors", {}).get("main") or config.Color.neutral
                )
            if (
                embed.title
                and not embed.author
                and not self.command.qualified_name in ("nowplaying", "createembed")
            ):
                embed.set_author(
                    name=self.author.display_name,
                    icon_url=self.author.display_avatar,
                )
            if embed.title:
                embed.title = shorten(embed.title, 256)
            if embed.description:
                embed.description = shorten(embed.description, 4096)
            for field in embed.fields:
                embed.set_field_at(
                    index=embed.fields.index(field),
                    name=field.name,
                    value=field.value[:1024],
                    inline=field.inline,
                )
            if hasattr(embed, "_attachments") and embed._attachments:
                for attachment in embed._attachments:
                    if isinstance(attachment, File):
                        kwargs["files"].append(
                            File(copy(attachment.fp), filename=attachment.filename)
                        )
                    elif isinstance(attachment, tuple):
                        response = await self.bot.session.get(attachment[0])
                        if response.status == 200:
                            kwargs["files"].append(
                                File(
                                    BytesIO(await response.read()),
                                    filename=attachment[1],
                                )
                            )

                # embed._attachments = []

        if embeds := kwargs.get("embeds"):
            for embed in embeds:
                if not embed.color:
                    embed.color = (
                        reskin.get("colors", {}).get("main") or config.Color.neutral
                    )
                if (
                    embed.title
                    and not embed.author
                    and not self.command.qualified_name in ("nowplaying", "createembed")
                ):
                    embed.set_author(
                        name=self.author.display_name,
                        icon_url=self.author.display_avatar,
                    )
                if embed.title:
                    embed.title = shorten(embed.title, 256)
                if embed.description:
                    embed.description = shorten(embed.description, 4096)
                for field in embed.fields:
                    embed.set_field_at(
                        index=embed.fields.index(field),
                        name=field.name,
                        value=field.value[:1024],
                        inline=field.inline,
                    )
                if hasattr(embed, "_attachments") and embed._attachments:
                    for attachment in embed._attachments:
                        if isinstance(attachment, File):
                            kwargs["files"].append(
                                File(copy(attachment.fp), filename=attachment.filename)
                            )
                        elif isinstance(attachment, tuple):
                            response = await self._state._get_client().session.get(
                                attachment[0]
                            )
                            if response.status == 200:
                                kwargs["files"].append(
                                    File(
                                        BytesIO(await response.read()),
                                        filename=attachment[1],
                                    )
                                )

                    # embed._attachments = []

        if content := (args[0] if args else kwargs.get("content")):
            content = str(content)
            if len(content) > 4000:
                kwargs[
                    "content"
                ] = f"Response too large to send (`{len(content)}/4000`)"
                kwargs["files"].append(
                    File(
                        StringIO(content),
                        filename=f"lainResult.txt",
                    )
                )
                if args:
                    args = args[1:]

        # Override the send function with a webhook for reskin..
        if reskin:
            webhook = reskin["webhook"]
            kwargs["username"] = reskin["username"]
            kwargs["avatar_url"] = reskin["avatar_url"]
            kwargs["wait"] = True

            delete_after = kwargs.pop("delete_after", None)
            kwargs.pop("stickers", None)
            kwargs.pop("reference", None)
            kwargs.pop("followup", None)

            try:
                message = await webhook.send(*args, **kwargs)
            except NotFound:
                reskin = await self.bot.fetch_config(self.guild.id, "reskin") or {}
                del reskin["webhooks"][str(self.channel.id)]
                await self.bot.update_config(self.guild.id, "reskin", reskin)
                await cache.delete_many(
                    f"reskin:channel:{self.channel.id}",
                    f"reskin:webhook:{self.channel.id}",
                )
            except HTTPException as error:
                raise error
            else:
                if delete_after:
                    await message.delete(delay=delete_after)

                return message

        return await super().send(*args, **kwargs)

    async def send_help(self):
        embed = Embed(
            description=(
                f"{self.command.short_doc or ''}\n>>> ```bf\nSyntax: {self.prefix}{self.command.qualified_name} {self.command.usage or ''}\nExample:"
                f" {self.prefix}{self.command.qualified_name} {self.command.example or ''}\n```"
            ),
        )
        embed.set_author(
            name=self.command.cog_name or "No category",
            icon_url=self.bot.user.display_avatar,
            url=f"https://discord.com",
        )

        await self.send(embed=embed)

    async def neutral(
        self: "Context",
        description: str,
        emoji: str = "",
        color=config.Color.neutral,
        **kwargs: Any,
    ) -> Message:
        """Send a neutral embed."""
        reskin = await self.reskin()
        color = reskin.get("colors", {}).get("main") or kwargs.pop(
            "color", config.Color.neutral
        )

        sign = "> " if not "\n>" in str(description) else ""
        embed = Embed(
            description=f"{sign} {emoji} {self.author.mention}: {description}",
            color=color,
            **kwargs,
        )

        if previous_load := getattr(self, "previous_load", None):
            cancel_load = kwargs.pop("cancel_load", False)
            result = await previous_load.edit(embed=embed, **kwargs)
            if cancel_load:
                delattr(self, "previous_load")
            return result

        return await self.send(embed=embed, **kwargs)

    async def approve(
        self: "Context",
        description: str,
        emoji: str = "",
        **kwargs: Any,
    ) -> Message:
        """Send an approve embed."""
        reskin = await self.reskin()
        color = reskin.get("colors", {}).get("main") or kwargs.pop(
            "color", config.Color.approval
        )

        sign = "> " if not "\n>" in str(description) else ""
        embed = Embed(
            description=f"{sign} {self.author.mention}: {description}",
            color=color,
            **kwargs,
        )
        if previous_load := getattr(self, "previous_load", None):
            cancel_load = kwargs.pop("cancel_load", False)
            result = await previous_load.edit(embed=embed, **kwargs)
            if cancel_load:
                delattr(self, "previous_load")
            return result

        return await self.send(embed=embed, **kwargs)

    async def error(
        self: "Context",
        description: str,
        **kwargs: Any,
    ) -> Message:
        """Send an error embed."""
        reskin = await self.reskin()
        color = reskin.get("colors", {}).get("main") or kwargs.pop(
            "color", config.Color.error
        )
        sign = "> " if "\n>" not in str(description) else ""
        embed = Embed(
            description=f"{sign} {self.author.mention}: {description}",
            color=color,
            **kwargs,
        )
        if previous_load := getattr(self, "previous_load", None):
            cancel_load = kwargs.pop("cancel_load", False)
            result = await previous_load.edit(embed=embed, **kwargs)
            if cancel_load:
                delattr(self, "previous_load")
            return result

        return await self.send(embed=embed, **kwargs)

    async def load(self, message: str, **kwargs):
        """Send a loading embed."""
        reskin = await self.reskin()
        color = reskin.get("colors", {}).get("load") or kwargs.pop(
            "color", config.Color.neutral
        )
        sign = "> " if not "\n>" in message else ""
        embed = Embed(
            color=color,
            description=f"{sign} {message}",
        )
        if not getattr(self, "previous_load", None):
            message = await self.send(embed=embed, **kwargs)
            setattr(self, "previous_load", message)
            return self.previous_load

        await self.previous_load.edit(embed=embed, **kwargs)
        return self.previous_load

    async def paginate(
        self,
        data: Embed | list[Embed | str],
        chunk_after: int = 10,
        entry_difference: int = 0,
        display_entries: bool = True,
        text: str = "entry|entries",
        of_text: str = None,
    ) -> Message:
        if isinstance(data, Embed):
            entries: int = 0
            temp_data: list[Embed] = []
            embed: Embed = data.copy()
            if description := data.description:
                for chunk in as_chunks(description, chunk_after):
                    _chunk = list()
                    for entry in chunk:
                        entries += 1
                        _chunk.append(
                            (f"`{entries}` " if display_entries else "") + entry
                        )

                    embed.description = "\n".join(_chunk)
                    temp_data.append(embed.copy())
            elif fields := data._fields:
                for chunk in as_chunks(fields, chunk_after):
                    embed._fields = list()
                    for field in chunk:
                        entries += 1
                        embed.add_field(**field)

                    temp_data.append(embed.copy())

            data = temp_data
        else:
            entries = len(data)

        if isinstance(data[0], Embed):
            if entry_difference:
                entries -= entry_difference

            for page, embed in enumerate(data):
                await self.style_embed(embed)
                if footer := embed.footer:
                    embed.set_footer(
                        text=(
                            (f"{footer.text} ∙ " if footer.text else "")
                            + f"Page {page + 1} of {len(data)} "
                        ),
                        icon_url=footer.icon_url,
                    )
                else:
                    embed.set_footer(
                        text=(
                            (f"{footer.text} ∙ " if footer.text else "")
                            + f"Page {page + 1} of {len(data)} "
                        ),
                    )

        paginator = Paginator(self, data)
        return await paginator.start()

    async def style_embed(self, embed: Embed) -> Embed:
        reskin = await self.reskin()

        if self.command and self.command.name == "createembed":
            if len(self.message.content.split()) > 1:
                return embed

        if not embed.color:
            embed.color = reskin.get("colors", {}).get("main") or config.Color.neutral

        if not embed.author and embed.title:
            embed.set_author(
                name=self.author.display_name,
                icon_url=self.author.display_avatar,
            )

        if embed.title:
            embed.title = shorten(embed.title, 256)

        if embed.description:
            embed.description = shorten(embed.description, 4096)

        for field in embed.fields:
            embed.set_field_at(
                index=embed.fields.index(field),
                name=field.name,
                value=shorten(field.value, 1024),
                inline=field.inline,
            )

        return embed

    async def react_check(self: "Context"):
        """React to the message"""

        await self.message.add_reaction("✅")

    async def check(self):
        return await self.send(content="👍🏾")

    async def prompt(self, message: str, member: Member = None, **kwargs):
        if member:
            view = views.ConfirmViewForUser(self, member)
            message = await self.send(
                embed=Embed(description=message), view=view, **kwargs
            )
            await view.wait()
            with suppress(HTTPException):
                await message.delete()
            if view.value is False:
                raise UserInputError("Prompt was denied.")

            return view.value
        else:
            view = views.ConfirmView(self)
            message = await self.send(
                embed=Embed(description=message), view=view, **kwargs
            )

            await view.wait()
            with suppress(HTTPException):
                await message.delete()

            if view.value is False:
                raise UserInputError("Prompt was denied.")
            return view.value


class ParameterParser:
    def __init__(self, ctx: "Context") -> None:
        self.context = ctx

    def get(self, parameter: str, **kwargs) -> Any:
        for parameter in (parameter, *kwargs.get("aliases", ())):
            sliced = self.context.message.content.split()

            if kwargs.get("require_value", True) is False:
                if f"-{parameter}" not in sliced:
                    return kwargs.get("default", None)

                return True

            try:
                index = sliced.index(f"--{parameter}")

            except ValueError:
                return kwargs.get("default", None)

            result = []
            for word in sliced[index + 1 :]:
                if word.startswith("-"):
                    break

                result.append(word)

            if not (result := " ".join(result).replace("\\n", "\n").strip()):
                return kwargs.get("default", None)

            if choices := kwargs.get("choices"):
                choice = tuple(
                    choice for choice in choices if choice.lower() == result.lower()
                )

                if not choice:
                    raise CommandError(f"Invalid choice for parameter `{parameter}`.")

                result = choice[0]

            if converter := kwargs.get("converter"):
                if hasattr(converter, "convert"):
                    result = self.context.bot.loop.create_task(
                        converter().convert(self.ctx, result)
                    )

                else:
                    try:
                        result = converter(result)

                    except Exception:
                        raise CommandError(
                            f"Invalid value for parameter `{parameter}`."
                        )

            if isinstance(result, int):
                if result < kwargs.get("minimum", 1):
                    raise CommandError(
                        f"The **minimum input** for parameter `{parameter}` is `{kwargs.get('minimum', 1)}`"
                    )

                if result > kwargs.get("maximum", 100):
                    raise CommandError(
                        f"The **maximum input** for parameter `{parameter}` is `{kwargs.get('maximum', 100)}`"
                    )

            return result

        return kwargs.get("default", None)
