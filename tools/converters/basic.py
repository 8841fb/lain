from datetime import datetime, timedelta
from typing import Optional

import aiohttp
import dateparser
import discord
import humanize  # type: ignore
from discord import Color, Emoji, Member, ThreadMember, User
from discord.ext.commands import (
    BadArgument,
    CommandError,
    Converter,
    EmojiNotFound,
    MemberConverter,
    MessageNotFound,
    MessageConverter,
    MemberNotFound,
    RoleConverter,
    RoleNotFound,
)

from tools.managers import regex
from tools.managers.context import Context
from tools.utilities import human_join

regions = [
    "brazil",
    "hongkong",
    "india",
    "japan",
    "rotterdam",
    "russia",
    "singapore",
    "south-korea",
    "southafrica",
    "sydney",
    "us-central",
    "us-east",
    "us-south",
    "us-west",
]


class SynthEngine(Converter):
    async def convert(self, ctx: Context, argument: str) -> str:
        voices = dict(
            male="en_au_002",
            ghostface="en_us_ghostface",
            chewbacca="en_us_chewbacca",
            stormtrooper="en_us_stormtrooper",
            stitch="en_us_stitch",
            narrator="en_male_narration",
            peaceful="en_female_emotional",
            glorious="en_female_ht_f08_glorious",
            chipmunk="en_male_m2_xhxs_m03_silly",
            chipmunks="en_male_m2_xhxs_m03_silly",
        )

        if voice := voices.get(argument.lower()):
            return voice

        raise CommandError(f"Synth engine **{argument}** not found")


def time(value: timedelta, short: bool = False):
    value = (
        humanize.precisedelta(value, format="%0.f")
        .replace("ago", "")
        .replace("from now", "")
    )
    if value.endswith("s") and value[:-1].isdigit() and int(value[:-1]) == 1:
        value = value[:-1]

    if short:
        value = " ".join(value.split(" ", 2)[:2])
        if value.endswith(","):
            value = value[:-1]
        return value

    return value


class Time:
    def __init__(self, seconds: int):
        self.seconds: int = seconds
        self.minutes: int = (self.seconds % 3600) // 60
        self.hours: int = (self.seconds % 86400) // 3600
        self.days: int = self.seconds // 86400
        self.weeks: int = self.days // 7
        self.delta: timedelta = timedelta(seconds=self.seconds)
        self.from_now: datetime = discord.utils.utcnow() + self.delta

    def __str__(self):
        return time(self.delta)


class TimeConverter(Converter):
    def _convert(self, argument: str):
        argument = str(argument)
        units = dict(
            s=1,
            m=60,
            h=3600,
            d=86400,
            w=604800,
        )
        if matches := regex.TIME.findall(argument):
            seconds = 0
            for time, unit in matches:
                try:
                    seconds += units[unit] * int(time)
                except KeyError:
                    raise CommandError(f"Invalid time unit `{unit}`")

            return seconds

    async def convert(self, ctx: Context, argument: str):
        if seconds := self._convert(argument):
            return Time(seconds)
        else:
            raise CommandError("Please **specify** a valid time - `1h 30m`")


class Location(Converter):
    async def convert(self, ctx: Context, argument: str) -> str:
        async with ctx.typing():
            async with aiohttp.ClientSession() as session:
                response = await session.get(
                    f"https://api.weatherapi.com/v1/timezone.json",
                    params=dict(key="0c5b47ed5774413c90b155456223004", q=argument),
                )
                if response.status == 200:
                    data = await response.json()
                    return data.get("location")
                else:
                    raise CommandError(f"Location **{argument}** not found")


class Emoji:
    def __init__(self, name: str, url: str, **kwargs):
        self.name: str = name
        self.url: str = url
        self.id: int = int(kwargs.get("id", 0))
        self.animated: bool = kwargs.get("animated", False)

    async def read(self):
        async with aiohttp.ClientSession() as session:
            async with session.get(self.url) as response:
                return await response.read()

    def __str__(self):
        if self.id:
            return f"<{'a' if self.animated else ''}:{self.name}:{self.id}>"
        else:
            return self.name

    def __repr__(self):
        return f"<name={self.name!r} url={self.url!r}>"


class EmojiFinder(Converter):
    async def convert(self, ctx: Context, argument: str):
        argument = str(argument)
        if match := regex.DISCORD_EMOJI.match(argument):
            return Emoji(
                match.group("name"),
                "https://cdn.discordapp.com/emojis/"
                + match.group("id")
                + (".gif" if match.group("animated") else ".png"),
                id=int(match.group("id")),
                animated=bool(match.group("animated")),
            )
        else:
            characters = list()
            for character in argument:
                characters.append(str(hex(ord(character)))[2:])
            if len(characters) == 2:
                if "fe0f" in characters:
                    characters.remove("fe0f")
            if "20e3" in characters:
                characters.remove("20e3")

            hexcode = "-".join(characters)
            url = "https://cdn.notsobot.com/twemoji/512x512/" + hexcode + ".png"
            response = await ctx.bot.session.request(
                "GET", url, raise_for={404: ((f"I wasn't able to find that **emoji**"))}
            )
            return Emoji(argument, url)

        raise EmojiNotFound(argument)


LANGUAGES = {
    "afrikaans": "af",
    "albanian": "sq",
    "amharic": "am",
    "arabic": "ar",
    "armenian": "hy",
    "azerbaijani": "az",
    "basque": "eu",
    "belarusian": "be",
    "bengali": "bn",
    "bosnian": "bs",
    "bulgarian": "bg",
    "catalan": "ca",
    "cebuano": "ceb",
    "chichewa": "ny",
    "chinese": "zh-cn",
    "chinese (simplified)": "zh-cn",
    "chinese (traditional)": "zh-tw",
    "corsican": "co",
    "croatian": "hr",
    "czech": "cs",
    "danish": "da",
    "dutch": "nl",
    "english": "en",
    "esperanto": "eo",
    "estonian": "et",
    "filipino": "tl",
    "finnish": "fi",
    "french": "fr",
    "frisian": "fy",
    "galician": "gl",
    "georgian": "ka",
    "german": "de",
    "greek": "el",
    "gujarati": "gu",
    "haitian creole": "ht",
    "hausa": "ha",
    "hawaiian": "haw",
    "hebrew": "he",
    "hindi": "hi",
    "hmong": "hmn",
    "hungarian": "hu",
    "icelandic": "is",
    "igbo": "ig",
    "indonesian": "id",
    "irish": "ga",
    "italian": "it",
    "japanese": "ja",
    "javanese": "jw",
    "kannada": "kn",
    "kazakh": "kk",
    "khmer": "km",
    "korean": "ko",
    "kurdish (kurmanji)": "ku",
    "kyrgyz": "ky",
    "lao": "lo",
    "latin": "la",
    "latvian": "lv",
    "lithuanian": "lt",
    "luxembourgish": "lb",
    "macedonian": "mk",
    "malagasy": "mg",
    "malay": "ms",
    "malayalam": "ml",
    "maltese": "mt",
    "maori": "mi",
    "marathi": "mr",
    "mongolian": "mn",
    "myanmar (burmese)": "my",
    "nepali": "ne",
    "norwegian": "no",
    "odia": "or",
    "pashto": "ps",
    "persian": "fa",
    "polish": "pl",
    "portuguese": "pt",
    "punjabi": "pa",
    "romanian": "ro",
    "russian": "ru",
    "samoan": "sm",
    "scots gaelic": "gd",
    "serbian": "sr",
    "sesotho": "st",
    "shona": "sn",
    "sindhi": "sd",
    "sinhala": "si",
    "slovak": "sk",
    "slovenian": "sl",
    "somali": "so",
    "spanish": "es",
    "sundanese": "su",
    "swahili": "sw",
    "swedish": "sv",
    "tajik": "tg",
    "tamil": "ta",
    "telugu": "te",
    "thai": "th",
    "turkish": "tr",
    "ukrainian": "uk",
    "urdu": "ur",
    "uyghur": "ug",
    "uzbek": "uz",
    "vietnamese": "vi",
    "welsh": "cy",
    "xhosa": "xh",
    "yiddish": "yi",
    "yoruba": "yo",
    "zulu": "zu",
}


class Percentage(Converter):
    async def convert(self, ctx: Context, argument: str):
        if argument.isdigit():
            argument = int(argument)
        elif match := regex.PERCENTAGE.match(argument):
            argument = int(match.group("percentage"))
        else:
            argument = 0

        if argument < 0 or argument > 100:
            raise CommandError("Please **specify** a valid percentage")

        return argument


def get_language(value: str):
    value = value.lower()
    if not value in LANGUAGES.keys():
        if not value in LANGUAGES.values():
            return None
        else:
            return value
    else:
        return LANGUAGES[value]


class Language(Converter):
    async def convert(self, ctx: Context, argument: str):
        argument = str(argument)
        if language := get_language(argument):
            return language
        else:
            raise CommandError(f"Language **{argument}** not found")


DANGEROUS_PERMISSIONS = [
    "administrator",
    "kick_members",
    "ban_members",
    "manage_guild",
    "manage_roles",
    "manage_channels",
    "manage_emojis",
    "manage_webhooks",
    "manage_nicknames",
    "mention_everyone",
]


class Role(RoleConverter):
    async def convert(self, ctx: Context, argument: str):
        role = None
        argument = str(argument)
        if match := regex.DISCORD_ID.match(argument):
            role = ctx.guild.get_role(int(match.group(1)))
        elif match := regex.DISCORD_ROLE_MENTION.match(argument):
            role = ctx.guild.get_role(int(match.group(1)))
        else:
            role = (
                discord.utils.find(
                    lambda r: r.name.lower() == argument.lower(), ctx.guild.roles
                )
                or discord.utils.find(
                    lambda r: argument.lower() in r.name.lower(), ctx.guild.roles
                )
                or discord.utils.find(
                    lambda r: r.name.lower().startswith(argument.lower()),
                    ctx.guild.roles,
                )
            )
        if not role or role.is_default():
            raise RoleNotFound(argument)
        return role

    async def manageable(self, ctx: Context, role: discord.Role, booster: bool = False):
        if role.managed and not booster:
            raise CommandError(f"You're unable to manage {role.mention}")
        elif not role.is_assignable() and not booster:
            raise CommandError(f"I'm unable to manage {role.mention}")
        elif role >= ctx.author.top_role and ctx.author.id != ctx.guild.owner.id:
            raise CommandError(f"You're unable to manage {role.mention}")

        return True

    async def dangerous(self, ctx: Context, role: discord.Role, _: str = "manage"):
        if (
            permissions := list(
                filter(
                    lambda permission: getattr(role.permissions, permission),
                    DANGEROUS_PERMISSIONS,
                )
            )
        ) and not ctx.author.id == ctx.guild.owner_id:
            raise CommandError(
                f"You're unable to {_} {role.mention} because it has the `{permissions[0]}` permission"
            )

        return False


class Roles(RoleConverter):
    async def convert(self, ctx: Context, argument: str):
        roles = []
        argument = str(argument)
        for role in argument.split(","):
            try:
                role = await Role().convert(ctx, role.strip())
                if role not in roles:
                    roles.append(role)
            except RoleNotFound:
                continue

        if not roles:
            raise RoleNotFound(argument)
        return roles

    async def manageable(
        self, ctx: Context, roles: list[discord.Role], booster: bool = False
    ):
        for role in roles:
            await Role().manageable(ctx, role, booster)

        return True

    async def dangerous(
        self, ctx: Context, roles: list[discord.Role], _: str = "manage"
    ):
        for role in roles:
            await Role().dangerous(ctx, role, _)


class Member(MemberConverter):
    async def convert(self, ctx: Context, argument: str) -> Member:
        return await super().convert(ctx, argument)

    async def hierarchy(self, ctx: Context, user: Member, author: bool = False):
        if isinstance(user, User):
            return True
        elif ctx.guild.me.top_role <= user.top_role:
            raise CommandError(
                f"I'm unable to **{ctx.command.qualified_name}** {user.mention}"
            )
        elif ctx.author.id == user.id and not author:
            raise CommandError(
                f"You're unable to **{ctx.command.qualified_name}** yourself"
            )
        elif ctx.author.id == user.id and author:
            return True
        elif ctx.author.id == ctx.guild.owner_id:
            return True
        elif user.id == ctx.guild.owner_id:
            raise CommandError(
                f"You're unable to **{ctx.command.qualified_name}** the **server owner**"
            )
        elif ctx.author.top_role.is_default():
            raise CommandError(
                f"You're unable to **{ctx.command.qualified_name}** {user.mention} because your **highest role** is {ctx.guild.default_role.mention}"
            )
        elif ctx.author.top_role == user.top_role:
            raise CommandError(
                f"You're unable to **{ctx.command.qualified_name}** {user.mention} because they have the **same role** as you"
            )
        elif ctx.author.top_role < user.top_role:
            raise CommandError(
                f"You're unable to **{ctx.command.qualified_name}** {user.mention} because they have a **higher role** than you"
            )
        else:
            return True


class ImageFinder(Converter):
    async def convert(self, ctx: Context, argument: str):
        argument = str(argument)
        try:
            member = await Member().convert(ctx, argument)
            if member:
                return member.display_avatar.url
        except:
            pass

        if match := regex.DISCORD_ATTACHMENT.match(argument):
            if not match.group("mime") in ("png", "jpg", "jpeg", "webp", "gif"):
                raise CommandError(f"Invalid image format: **{match.group('mime')}**")
            return match.group()
        elif match := regex.IMAGE_URL.match(argument):
            return match.group()
        else:
            raise CommandError(f"Couldn't find an **image**")

    async def search(ctx: Context, history: bool = True):
        if message := ctx.replied_message:
            for attachment in message.attachments:
                if attachment.content_type.split("/", 1)[1] in (
                    "png",
                    "jpg",
                    "jpeg",
                    "webp",
                    "gif",
                ):
                    return attachment.url
            for embed in message.embeds:
                if image := embed.image:
                    if match := regex.DISCORD_ATTACHMENT.match(image.url):
                        if not match.group("mime") in (
                            "png",
                            "jpg",
                            "jpeg",
                            "webp",
                            "gif",
                        ):
                            raise CommandError(
                                f"Invalid image format: **{match.group('mime')}**"
                            )
                        return match.group()
                    elif match := regex.IMAGE_URL.match(image.url):
                        return match.group()
                elif thumbnail := embed.thumbnail:
                    if match := regex.DISCORD_ATTACHMENT.match(thumbnail.url):
                        if not match.group("mime") in (
                            "png",
                            "jpg",
                            "jpeg",
                            "webp",
                            "gif",
                        ):
                            raise CommandError(
                                f"Invalid image format: **{match.group('mime')}**"
                            )
                        return match.group()
                    elif match := regex.IMAGE_URL.match(thumbnail.url):
                        return match.group()

        if ctx.message.attachments:
            for attachment in ctx.message.attachments:
                if attachment.content_type.split("/", 1)[1] in (
                    "png",
                    "jpg",
                    "jpeg",
                    "webp",
                    "gif",
                ):
                    return attachment.url

        if history:
            async for message in ctx.channel.history(limit=50):
                if message.attachments:
                    for attachment in message.attachments:
                        if attachment.content_type.split("/", 1)[1] in (
                            "png",
                            "jpg",
                            "jpeg",
                            "webp",
                            "gif",
                        ):
                            return attachment.url
                if message.embeds:
                    for embed in message.embeds:
                        if image := embed.image:
                            if match := regex.DISCORD_ATTACHMENT.match(image.url):
                                if not match.group("mime") in (
                                    "png",
                                    "jpg",
                                    "jpeg",
                                    "webp",
                                    "gif",
                                ):
                                    raise CommandError(
                                        f"Invalid image format: **{match.group('mime')}**"
                                    )
                                return match.group()
                            elif match := regex.IMAGE_URL.match(image.url):
                                return match.group()
                        elif thumbnail := embed.thumbnail:
                            if match := regex.DISCORD_ATTACHMENT.match(thumbnail.url):
                                if not match.group("mime") in (
                                    "png",
                                    "jpg",
                                    "jpeg",
                                    "webp",
                                    "gif",
                                ):
                                    raise CommandError(
                                        f"Invalid image format: **{match.group('mime')}**"
                                    )
                                return match.group()
                            elif match := regex.IMAGE_URL.match(thumbnail.url):
                                return match.group()

        raise CommandError("Please **provide** an image")


class Bitrate(Converter):
    async def convert(self, ctx: Context, argument: str) -> int:
        if argument.isdigit():
            argument = int(argument)

        elif match := regex.BITRATE.match(argument):
            argument = int(match.group(1))

        else:
            argument = 0

        if argument < 8:
            raise CommandError("**Bitrate** cannot be less than `8 kbps`!")

        elif argument > int(ctx.guild.bitrate_limit / 1000):
            raise CommandError(
                f"`{argument}kbps` cannot be **greater** than `{int(ctx.guild.bitrate_limit / 1000)}kbps`!"
            )

        return argument


class Region(Converter):
    async def convert(self, ctx: Context, argument: str) -> int:
        argument = argument.lower().replace(" ", "-")
        if not argument in regions:
            raise CommandError(
                "**Voice region** must be one of "
                + human_join([f"`{region}`" for region in regions])
            )

        return argument


class ChartSize(Converter):
    async def convert(self, ctx: Context, argument: str):
        argument = str(argument)
        if not "x" in argument:
            raise CommandError(
                "Collage size **incorrectly formatted** - example: `6x6`"
            )
        if not len(argument.split("x")) == 2:
            raise CommandError(
                "Collage size **incorrectly formatted** - example: `6x6`"
            )
        row, col = argument.split("x")
        if not row.isdigit() or not col.isdigit():
            raise CommandError(
                "Collage size **incorrectly formatted** - example: `6x6`"
            )
        if (int(row) + int(col)) < 2:
            raise CommandError("Collage size **too small**\n> Minimum size is `1x1`")
        elif (int(row) + int(col)) > 20:
            raise CommandError("Collage size **too large**\n> Maximum size is `10x10`")

        return row + "x" + col


class MemberStrict(MemberConverter):
    async def convert(self, ctx: Context, argument: str):
        member = None
        argument = str(argument)
        if match := regex.DISCORD_ID.match(argument):
            member = ctx.guild.get_member(int(match.group(1)))
        elif match := regex.DISCORD_USER_MENTION.match(argument):
            member = ctx.guild.get_member(int(match.group(1)))

        if not member:
            raise MemberNotFound(argument)
        return member


class Date(Converter):
    async def convert(self, ctx: Context, argument: str):
        argument = str(argument)
        if date := dateparser.parse(argument):
            return date
        else:
            raise CommandError("Date not recognized - Example: `December 5th`")


class Command(Converter):
    async def convert(self, ctx: Context, argument: str):
        argument = str(argument)

        if command := ctx.bot.get_command(argument):
            return command
        else:
            raise CommandError(f"Command `{argument}` doesn't exist")


class ImageFinderStrict(Converter):
    async def convert(self, ctx: Context, argument: str):
        argument = str(argument)
        # try:
        #     member = await Member().convert(ctx, argument)
        #     if member and not member.display_avatar.is_animated():
        #         return member.display_avatar.url
        # except:
        #     pass

        if match := regex.DISCORD_ATTACHMENT.match(argument):
            if not match.group("mime") in ("png", "jpg", "jpeg", "webp"):
                raise CommandError(f"Invalid image format: **{match.group('mime')}**")
            return match.group()
        elif match := regex.IMAGE_URL.match(argument):
            if match.group("mime") == "gif":
                raise CommandError(f"Invalid image format: **{match.group('mime')}**")
            return match.group()
        else:
            raise CommandError(f"Couldn't find an **image**")

    async def search(ctx: Context, history: bool = True):
        if message := ctx.replied_message:
            for attachment in message.attachments:
                if attachment.content_type.split("/", 1)[1] in (
                    "png",
                    "jpg",
                    "jpeg",
                    "webp",
                ):
                    return attachment.url
            for embed in message.embeds:
                if image := embed.image:
                    if match := regex.DISCORD_ATTACHMENT.match(image.url):
                        if not match.group("mime") in (
                            "png",
                            "jpg",
                            "jpeg",
                            "webp",
                        ):
                            raise CommandError(
                                f"Invalid image format: **{match.group('mime')}**"
                            )
                        return match.group()
                    elif match := regex.IMAGE_URL.match(image.url):
                        if match.group("mime") == "gif":
                            continue
                        return match.group()
                elif thumbnail := embed.thumbnail:
                    if match := regex.DISCORD_ATTACHMENT.match(thumbnail.url):
                        if not match.group("mime") in (
                            "png",
                            "jpg",
                            "jpeg",
                            "webp",
                        ):
                            raise CommandError(
                                f"Invalid image format: **{match.group('mime')}**"
                            )
                        return match.group()
                    elif match := regex.IMAGE_URL.match(thumbnail.url):
                        if match.group("mime") == "gif":
                            continue
                        return match.group()

        if ctx.message.attachments:
            for attachment in ctx.message.attachments:
                if attachment.content_type.split("/", 1)[1] in (
                    "png",
                    "jpg",
                    "jpeg",
                    "webp",
                ):
                    return attachment.url

        if history:
            async for message in ctx.channel.history(limit=50):
                if message.attachments:
                    for attachment in message.attachments:
                        if attachment.content_type.split("/", 1)[1] in (
                            "png",
                            "jpg",
                            "jpeg",
                            "webp",
                        ):
                            return attachment.url
                if message.embeds:
                    for embed in message.embeds:
                        if image := embed.image:
                            if match := regex.DISCORD_ATTACHMENT.match(image.url):
                                if not match.group("mime") in (
                                    "png",
                                    "jpg",
                                    "jpeg",
                                    "webp",
                                ):
                                    continue
                                return match.group()
                            elif match := regex.IMAGE_URL.match(image.url):
                                if match.group("mime") == "gif":
                                    continue
                                return match.group()
                        elif thumbnail := embed.thumbnail:
                            if match := regex.DISCORD_ATTACHMENT.match(thumbnail.url):
                                if not match.group("mime") in (
                                    "png",
                                    "jpg",
                                    "jpeg",
                                    "webp",
                                ):
                                    continue
                                return match.group()
                            elif match := regex.IMAGE_URL.match(thumbnail.url):
                                if match.group("mime") == "gif":
                                    continue
                                return match.group()

        raise CommandError("Please **provide** an image")


class Position(Converter):
    async def convert(self, ctx: Context, argument: str) -> int:
        argument = argument.lower()
        player = ctx.voice_client
        ms: int = 0

        if ctx.invoked_with == "ff" and not argument.startswith("+"):
            argument = f"+{argument}"

        elif ctx.invoked_with == "rw" and not argument.startswith("-"):
            argument = f"-{argument}"

        if match := regex.Position.HH_MM_SS.fullmatch(argument):
            ms += (
                int(match.group("h")) * 3600000
                + int(match.group("m")) * 60000
                + int(match.group("s")) * 1000
            )

        elif match := regex.Position.MM_SS.fullmatch(argument):
            ms += int(match.group("m")) * 60000 + int(match.group("s")) * 1000

        elif (match := regex.Position.OFFSET.fullmatch(argument)) and player:
            ms += player.position + int(match.group("s")) * 1000

        elif match := regex.Position.HUMAN.fullmatch(argument):
            if m := match.group("m"):
                if match.group("s") and argument.endswith("m"):
                    raise CommandError(f"Position `{argument}` is not valid")

                ms += int(m) * 60000

            elif s := match.group("s"):
                if argument.endswith("m"):
                    ms += int(s) * 60000
                else:
                    ms += int(s) * 1000

        else:
            raise CommandError(f"Position `{argument}` is not valid")

        return ms


class State(Converter):
    async def convert(self, ctx: Context, argument: str):
        argument = str(argument)
        if argument.lower() in ("on", "yes", "true", "enable"):
            return True
        elif argument.lower() in ("off", "no", "none", "null", "false", "disable"):
            return False
        else:
            raise CommandError("Please **specify** a valid state - `on` or `off`")


class StickerFinder(Converter):
    async def convert(self, ctx: Context, argument: str):
        argument = str(argument)
        try:
            message = await MessageConverter().convert(ctx, argument)
        except MessageNotFound:
            pass
        else:
            if message.stickers:
                sticker = await message.stickers[0].fetch()
                if isinstance(sticker, discord.StandardSticker):
                    raise CommandError("Sticker **must** be a nitro sticker")
                return sticker
            else:
                raise CommandError(
                    f"[**Message**]({message.jump_url}) doesn't contain a sticker"
                )

        sticker = discord.utils.get(ctx.guild.stickers, name=argument)
        if not sticker:
            raise CommandError("That **sticker** doesn't exist in this server")
        return sticker

    async def search(ctx: Context):
        if ctx.message.stickers:
            sticker = await ctx.message.stickers[0].fetch()
        elif ctx.replied_message:
            if ctx.replied_message.stickers:
                sticker = await ctx.replied_message.stickers[0].fetch()
            else:
                raise CommandError(
                    f"[**Message**]({ctx.replied_message.jump_url}) doesn't contain a sticker"
                )
        else:
            raise CommandError("Please **specify** a sticker")

        if isinstance(sticker, discord.StandardSticker):
            raise CommandError("Sticker **must** be a nitro sticker")
        return sticker


class MediaFinder(Converter):
    async def convert(self, ctx: Context, argument: str):
        argument = str(argument)
        try:
            member = await Member().convert(ctx, argument)
            if member:
                return member.display_avatar.url
        except:
            pass

        if match := regex.DISCORD_ATTACHMENT.match(argument):
            if not match.group("mime") in (
                "mp3",
                "mp4",
                "mpeg",
                "mpga",
                "m4a",
                "wav",
                "mov",
                "webm",
                "quicktime",
            ):
                raise CommandError(f"Invalid media format: **{match.group('mime')}**")
            return match.group()
        elif match := regex.MEDIA_URL.match(argument):
            return match.group()
        else:
            raise CommandError(f"Couldn't find any **media**")

    async def search(ctx: Context, history: bool = True):
        if message := ctx.replied_message:
            for attachment in message.attachments:
                if attachment.content_type.split("/", 1)[1] in (
                    "mp3",
                    "mp4",
                    "mpeg",
                    "mpga",
                    "m4a",
                    "wav",
                    "mov",
                    "webp",
                    "quicktime",
                ):
                    return attachment.url

        if ctx.message.attachments:
            for attachment in ctx.message.attachments:
                if attachment.content_type.split("/", 1)[1] in (
                    "mp3",
                    "mp4",
                    "mpeg",
                    "mpga",
                    "m4a",
                    "wav",
                    "mov",
                    "webp",
                    "quicktime",
                ):
                    return attachment.url

        if history:
            async for message in ctx.channel.history(limit=50):
                if message.attachments:
                    for attachment in message.attachments:
                        if attachment.content_type.split("/", 1)[1] in (
                            "mp3",
                            "mp4",
                            "mpeg",
                            "mpga",
                            "m4a",
                            "wav",
                            "mov",
                            "webp",
                        ):
                            return attachment.url

        raise CommandError("Please **provide** a media file")
