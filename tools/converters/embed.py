import random
import urllib

import dateparser
from discord import Color, Embed, Member, Message, TextChannel, Webhook, ButtonStyle
from discord.ext.commands import CommandError, Converter
from discord.utils import escape_markdown, utcnow

from tools import tagscript
from discord.ui import Button, View  # type: ignore
from tools.managers.context import Context
from tools.managers.regex import IMAGE_URL, URL
from tools.utilities.humanize import comma, ordinal
from tools.utilities.text import hidden


class LinkButton(Button):
    def __init__(
        self, label: str, url: str, emoji: str, style: ButtonStyle = ButtonStyle.link
    ):
        super().__init__(style=style, label=label, url=url, emoji=emoji)


class LinkView(View):
    def __init__(self, links: list[LinkButton]):
        super().__init__(timeout=None)
        for button in links:
            self.add_item(button)


colors = {
    "aliceblue": "#f0f8ff",
    "antiquewhite": "#faebd7",
    "aqua": "#00ffff",
    "aquamarine": "#7fffd4",
    "azure": "#f0ffff",
    "beige": "#f5f5dc",
    "bisque": "#ffe4c4",
    "black": "#000000",
    "blanchedalmond": "#ffebcd",
    "blue": "#0000ff",
    "blueviolet": "#8a2be2",
    "brown": "#a52a2a",
    "burlywood": "#deb887",
    "cadetblue": "#5f9ea0",
    "chartreuse": "#7fff00",
    "chocolate": "#d2691e",
    "coral": "#ff7f50",
    "cornflowerblue": "#6495ed",
    "cornsilk": "#fff8dc",
    "crimson": "#dc143c",
    "cyan": "#00ffff",
    "darkblue": "#00008b",
    "darkcyan": "#008b8b",
    "darkgoldenrod": "#b8860b",
    "darkgray": "#a9a9a9",
    "darkgrey": "#a9a9a9",
    "darkgreen": "#006400",
    "darkkhaki": "#bdb76b",
    "darkmagenta": "#8b008b",
    "darkolivegreen": "#556b2f",
    "darkorange": "#ff8c00",
    "darkorchid": "#9932cc",
    "darkred": "#8b0000",
    "darksalmon": "#e9967a",
    "darkseagreen": "#8fbc8f",
    "darkslateblue": "#483d8b",
    "darkslategray": "#2f4f4f",
    "darkslategrey": "#2f4f4f",
    "darkturquoise": "#00ced1",
    "darkviolet": "#9400d3",
    "deeppink": "#ff1493",
    "deepskyblue": "#00bfff",
    "dimgray": "#696969",
    "dimgrey": "#696969",
    "dodgerblue": "#1e90ff",
    "firebrick": "#b22222",
    "floralwhite": "#fffaf0",
    "forestgreen": "#228b22",
    "fuchsia": "#ff00ff",
    "gainsboro": "#dcdcdc",
    "ghostwhite": "#f8f8ff",
    "gold": "#ffd700",
    "goldenrod": "#daa520",
    "gray": "#808080",
    "grey": "#808080",
    "green": "#008000",
    "greenyellow": "#adff2f",
    "honeydew": "#f0fff0",
    "hotpink": "#ff69b4",
    "indianred": "#cd5c5c",
    "indigo": "#4b0082",
    "ivory": "#fffff0",
    "khaki": "#f0e68c",
    "lavender": "#e6e6fa",
    "lavenderblush": "#fff0f5",
    "lawngreen": "#7cfc00",
    "lemonchiffon": "#fffacd",
    "lightblue": "#add8e6",
    "lightcoral": "#f08080",
    "lightcyan": "#e0ffff",
    "lightgoldenrodyellow": "#fafad2",
    "lightgray": "#d3d3d3",
    "lightgrey": "#d3d3d3",
    "lightgreen": "#90ee90",
    "lightpink": "#ffb6c1",
    "lightsalmon": "#ffa07a",
    "lightseagreen": "#20b2aa",
    "lightskyblue": "#87cefa",
    "lightslategray": "#778899",
    "lightslategrey": "#778899",
    "lightsteelblue": "#b0c4de",
    "lightyellow": "#ffffe0",
    "lime": "#00ff00",
    "limegreen": "#32cd32",
    "linen": "#faf0e6",
    "magenta": "#ff00ff",
    "maroon": "#800000",
    "mediumaquamarine": "#66cdaa",
    "mediumblue": "#0000cd",
    "mediumorchid": "#ba55d3",
    "mediumpurple": "#9370db",
    "mediumseagreen": "#3cb371",
    "mediumslateblue": "#7b68ee",
    "mediumspringgreen": "#00fa9a",
    "mediumturquoise": "#48d1cc",
    "mediumvioletred": "#c71585",
    "midnightblue": "#191970",
    "mintcream": "#f5fffa",
    "mistyrose": "#ffe4e1",
    "moccasin": "#ffe4b5",
    "navajowhite": "#ffdead",
    "navy": "#000080",
    "oldlace": "#fdf5e6",
    "olive": "#808000",
    "olivedrab": "#6b8e23",
    "orange": "#ffa500",
    "orangered": "#ff4500",
    "orchid": "#da70d6",
    "palegoldenrod": "#eee8aa",
    "palegreen": "#98fb98",
    "paleturquoise": "#afeeee",
    "palevioletred": "#db7093",
    "papayawhip": "#ffefd5",
    "peachpuff": "#ffdab9",
    "peru": "#cd853f",
    "pink": "#ffc0cb",
    "plum": "#dda0dd",
    "powderblue": "#b0e0e6",
    "purple": "#800080",
    "red": "#ff0000",
    "rosybrown": "#bc8f8f",
    "royalblue": "#4169e1",
    "saddlebrown": "#8b4513",
    "salmon": "#fa8072",
    "sandybrown": "#f4a460",
    "seagreen": "#2e8b57",
    "seashell": "#fff5ee",
    "sienna": "#a0522d",
    "silver": "#c0c0c0",
    "skyblue": "#87ceeb",
    "slateblue": "#6a5acd",
    "slategray": "#708090",
    "slategrey": "#708090",
    "snow": "#fffafa",
    "springgreen": "#00ff7f",
    "steelblue": "#4682b4",
    "tan": "#d2b48c",
    "teal": "#008080",
    "thistle": "#d8bfd8",
    "tomato": "#ff6347",
    "turquoise": "#40e0d0",
    "violet": "#ee82ee",
    "wheat": "#f5deb3",
    "white": "#ffffff",
    "whitesmoke": "#f5f5f5",
    "yellow": "#ffff00",
    "yellowgreen": "#9acd32",
}


def get_color(value: str):
    if value.lower() in ("random", "rand", "r"):
        return Color.random()
    elif value.lower() in ("invisible", "invis"):
        return Color.from_str("#2B2D31")
    elif value.lower() in ("blurple", "blurp"):
        return Color.blurple()
    elif value.lower() in ("black", "negro"):
        return Color.from_str("#000001")

    value = colors.get(str(value).lower()) or value
    try:
        color = Color(int(value.replace("#", ""), 16))
    except ValueError:
        return None

    if not color.value > 16777215:
        return color
    else:
        return None


class EmbedScript:
    def __init__(self, script: str):
        self.script: str = script
        self._script: str = script
        self._type: str = "text"
        self.parser: tagscript.Parser = tagscript.Parser()
        self.embed_parser: tagscript.FunctionParser = tagscript.Parser()
        self.objects: dict = dict(
            content=None, embed=Embed(), embeds=list(), button=list()
        )

    async def resolve_variables(self, **kwargs):
        """Format the variables inside the script"""

        if guild := kwargs.get("guild"):
            self.script = (
                self.script.replace("{guild}", str(guild))
                .replace("{guild.id}", str(guild.id))
                .replace("{guild.name}", str(guild.name))
                .replace(
                    "{guild.icon}",
                    str(guild.icon or "https://cdn.discordapp.com/embed/avatars/1.png"),
                )
                .replace("{guild.banner}", str(guild.banner or "No banner"))
                .replace("{guild.splash}", str(guild.splash or "No splash"))
                .replace(
                    "{guild.discovery_splash}",
                    str(guild.discovery_splash or "No discovery splash"),
                )
                .replace("{guild.owner}", str(guild.owner))
                .replace("{guild.owner_id}", str(guild.owner_id))
                .replace("{guild.count}", str(comma(len(guild.members))))
                .replace("{guild.members}", str(comma(len(guild.members))))
                .replace("{len(guild.members)}", str(comma(len(guild.members))))
                .replace("{guild.channels}", str(comma(len(guild.channels))))
                .replace(
                    "{guild.channel_count}",
                    str(comma(len(guild.channels))),
                )
                .replace(
                    "{guild.category_channels}",
                    str(comma(len(guild.categories))),
                )
                .replace(
                    "{guild.category_channel_count}",
                    str(comma(len(guild.categories))),
                )
                .replace(
                    "{guild.text_channels}",
                    str(comma(len(guild.text_channels))),
                )
                .replace(
                    "{guild.text_channel_count}",
                    str(comma(len(guild.text_channels))),
                )
                .replace(
                    "{guild.voice_channels}",
                    str(comma(len(guild.voice_channels))),
                )
                .replace(
                    "{guild.voice_channel_count}",
                    str(comma(len(guild.voice_channels))),
                )
                .replace("{guild.roles}", str(comma(len(guild.roles))))
                .replace("{guild.role_count}", str(comma(len(guild.roles))))
                .replace("{guild.emojis}", str(comma(len(guild.emojis))))
                .replace("{guild.emoji_count}", str(comma(len(guild.emojis))))
                .replace(
                    "{guild.created_at}",
                    str(guild.created_at.strftime("%m/%d/%Y, %I:%M %p")),
                )
                .replace("{unix(guild.created_at)}", str(guild.created_at.timestamp()))
            )
        if channel := kwargs.get("channel"):
            if isinstance(channel, TextChannel):
                self.script = (
                    self.script.replace("{channel}", str(channel))
                    .replace("{channel.id}", str(channel.id))
                    .replace("{channel.mention}", str(channel.mention))
                    .replace("{channel.name}", str(channel.name))
                    .replace("{channel.topic}", str(channel.topic))
                    .replace("{channel.created_at}", str(channel.created_at))
                    .replace(
                        "{channel.created_at}",
                        str(channel.created_at.strftime("%m/%d/%Y, %I:%M %p")),
                    )
                    .replace(
                        "{unix(channel.created_at)}",
                        str(int(channel.created_at.timestamp())),
                    )
                )
        if role := kwargs.get("role"):
            self.script = (
                self.script.replace("{role}", str(role))
                .replace("{role.id}", str(role.id))
                .replace("{role.mention}", str(role.mention))
                .replace("{role.name}", str(role.name))
                .replace("{role.color}", str(role.color))
                .replace("{role.created_at}", str(role.created_at))
                .replace(
                    "{role.created_at}",
                    str(role.created_at.strftime("%m/%d/%Y, %I:%M %p")),
                )
                .replace(
                    "{unix(role.created_at)}", str(int(role.created_at.timestamp()))
                )
            )
        if roles := kwargs.get("roles"):
            self.script = self.script.replace(
                "{roles}", " ".join([str(role) for role in roles])
            )
        if user := kwargs.get("user"):
            self.script = self.script.replace("{member", "{user")
            self.script = (
                self.script.replace("{user}", str(user))
                .replace("{user.id}", str(user.id))
                .replace("{user.mention}", str(user.mention))
                .replace("{user.name}", str(user.name))
                .replace("{user.tag}", str(user.discriminator))
                .replace("{user.bot}", "Yes" if user.bot else "No")
                .replace("{user.color}", str(user.color))
                .replace("{user.avatar}", str(user.display_avatar))
                .replace("{user.nickname}", str(user.display_name))
                .replace("{user.nick}", str(user.display_name))
                .replace(
                    "{user.created_at}",
                    str(user.created_at.strftime("%m/%d/%Y, %I:%M %p")),
                )
                .replace(
                    "{unix(user.created_at)}", str(int(user.created_at.timestamp()))
                )
            )
            if isinstance(user, Member):
                self.script = (
                    self.script.replace(
                        "{user.joined_at}",
                        str(user.joined_at.strftime("%m/%d/%Y, %I:%M %p")),
                    )
                    .replace("{user.boost}", "Yes" if user.premium_since else "No")
                    .replace(
                        "{user.boosted_at}",
                        str(user.premium_since.strftime("%m/%d/%Y, %I:%M %p"))
                        if user.premium_since
                        else "Never",
                    )
                    .replace(
                        "{unix(user.boosted_at)}",
                        str(int(user.premium_since.timestamp()))
                        if user.premium_since
                        else "Never",
                    )
                    .replace(
                        "{user.boost_since}",
                        str(user.premium_since.strftime("%m/%d/%Y, %I:%M %p"))
                        if user.premium_since
                        else "Never",
                    )
                    .replace(
                        "{unix(user.boost_since)}",
                        str(int(user.premium_since.timestamp()))
                        if user.premium_since
                        else "Never",
                    )
                )
        if moderator := kwargs.get("moderator"):
            self.script = (
                self.script.replace("{moderator}", str(moderator))
                .replace("{moderator.id}", str(moderator.id))
                .replace("{moderator.mention}", str(moderator.mention))
                .replace("{moderator.name}", str(moderator.name))
                .replace("{moderator.tag}", str(moderator.discriminator))
                .replace("{moderator.bot}", "Yes" if moderator.bot else "No")
                .replace("{moderator.color}", str(moderator.color))
                .replace("{moderator.avatar}", str(moderator.display_avatar))
                .replace("{moderator.nickname}", str(moderator.display_name))
                .replace("{moderator.nick}", str(moderator.display_name))
                .replace(
                    "{moderator.created_at}",
                    str(moderator.created_at.strftime("%m/%d/%Y, %I:%M %p")),
                )
                .replace(
                    "{unix(moderator.created_at)}",
                    str(int(moderator.created_at.timestamp())),
                )
            )
            if isinstance(moderator, Member):
                self.script = (
                    self.script.replace(
                        "{moderator.joined_at}",
                        str(moderator.joined_at.strftime("%m/%d/%Y, %I:%M %p")),
                    )
                    .replace(
                        "{unix(moderator.joined_at)}",
                        str(int(moderator.joined_at.timestamp())),
                    )
                    .replace(
                        "{moderator.join_position}",
                        str(
                            (
                                sorted(guild.members, key=lambda m: m.joined_at).index(
                                    moderator
                                )
                                + 1
                            )
                        ),
                    )
                    .replace(
                        "{suffix(moderator.join_position)}",
                        str(
                            ordinal(
                                sorted(guild.members, key=lambda m: m.joined_at).index(
                                    moderator
                                )
                                + 1
                            )
                        ),
                    )
                    .replace(
                        "{moderator.boost}",
                        "Yes" if moderator.premium_since else "No",
                    )
                    .replace(
                        "{moderator.boosted_at}",
                        str(moderator.premium_since.strftime("%m/%d/%Y, %I:%M %p"))
                        if moderator.premium_since
                        else "Never",
                    )
                    .replace(
                        "{unix(moderator.boosted_at)}",
                        str(int(moderator.premium_since.timestamp()))
                        if moderator.premium_since
                        else "Never",
                    )
                    .replace(
                        "{moderator.boost_since}",
                        str(moderator.premium_since.strftime("%m/%d/%Y, %I:%M %p"))
                        if moderator.premium_since
                        else "Never",
                    )
                    .replace(
                        "{unix(moderator.boost_since)}",
                        str(int(moderator.premium_since.timestamp()))
                        if moderator.premium_since
                        else "Never",
                    )
                )
        if case_id := kwargs.get("case_id"):
            self.script = (
                self.script.replace("{case.id}", str(case_id))
                .replace("{case}", str(case_id))
                .replace("{case_id}", str(case_id))
            )
        if reason := kwargs.get("reason"):
            self.script = self.script.replace("{reason}", str(reason))
        if duration := kwargs.get("duration"):
            self.script = self.script.replace("{duration}", str(duration))
        if image := kwargs.get("image"):
            self.script = self.script.replace("{image}", str(image))
        if option := kwargs.get("option"):
            self.script = self.script.replace("{option}", str(option))
        if text := kwargs.get("text"):
            self.script = self.script.replace("{text}", str(text))
        if emoji := kwargs.get("emoji"):
            self.script = (
                self.script.replace("{emoji}", str(emoji))
                .replace("{emoji.id}", str(emoji.id))
                .replace("{emoji.name}", str(emoji.name))
                .replace("{emoji.animated}", "Yes" if emoji.animated else "No")
                .replace("{emoji.url}", str(emoji.url))
            )
        if emojis := kwargs.get("emojis"):
            self.script = self.script.replace("{emojis}", str(emojis))
        if sticker := kwargs.get("sticker"):
            self.script = (
                self.script.replace("{sticker}", str(sticker))
                .replace("{sticker.id}", str(sticker.id))
                .replace("{sticker.name}", str(sticker.name))
                .replace("{sticker.animated}", "Yes" if sticker.animated else "No")
                .replace("{sticker.url}", str(sticker.url))
            )
        if color := kwargs.get("color"):
            self.script = self.script.replace("{color}", str(color)).replace(
                "{colour}", str(color)
            )
        if name := kwargs.get("name"):
            self.script = self.script.replace("{name}", str(name))
        if "hoist" in kwargs:
            hoist = kwargs.get("hoist")
            self.script = self.script.replace("{hoisted}", "Yes" if hoist else "No")
            self.script = self.script.replace("{hoist}", "Yes" if hoist else "No")
        if "mentionable" in kwargs:
            mentionable = kwargs.get("mentionable")
            self.script = self.script.replace(
                "{mentionable}", "Yes" if mentionable else "No"
            )
        if lastfm := kwargs.get("lastfm"):
            self.script = (
                self.script.replace("{lastfm}", lastfm["user"]["username"])
                .replace("{lastfm.name}", lastfm["user"]["username"])
                .replace("{lastfm.url}", lastfm["user"]["url"])
                .replace("{lastfm.avatar}", lastfm["user"]["avatar"] or "")
                .replace(
                    "{lastfm.plays}",
                    comma(lastfm["user"]["library"]["scrobbles"]),
                )
                .replace(
                    "{lastfm.scrobbles}",
                    comma(lastfm["user"]["library"]["scrobbles"]),
                )
                .replace(
                    "{lastfm.library}",
                    comma(lastfm["user"]["library"]["scrobbles"]),
                )
                .replace(
                    "{lastfm.library.artists}",
                    comma(lastfm["user"]["library"]["artists"]),
                )
                .replace(
                    "{lastfm.library.albums}",
                    comma(lastfm["user"]["library"]["albums"]),
                )
                .replace(
                    "{lastfm.library.tracks}",
                    comma(lastfm["user"]["library"]["tracks"]),
                )
                .replace("{artist}", escape_markdown(lastfm["artist"]["name"]))
                .replace("{artist.name}", escape_markdown(lastfm["artist"]["name"]))
                .replace("{artist.url}", lastfm["artist"]["url"])
                .replace("{artist.image}", lastfm["artist"]["image"] or "")
                .replace("{artist.plays}", comma(lastfm["artist"]["plays"]))
                .replace(
                    "{album}",
                    escape_markdown(lastfm["album"]["name"])
                    if lastfm.get("album")
                    else "",
                )
                .replace(
                    "{album.name}",
                    escape_markdown(lastfm["album"]["name"])
                    if lastfm.get("album")
                    else "",
                )
                .replace(
                    "{album.url}",
                    lastfm["album"]["url"] if lastfm.get("album") else "",
                )
                .replace(
                    "{album.image}",
                    (lastfm["album"]["image"] or "") if lastfm.get("album") else "",
                )
                .replace(
                    "{album.cover}",
                    (lastfm["album"]["image"] or "") if lastfm.get("album") else "",
                )
                .replace(
                    "{album.plays}",
                    comma(lastfm["album"]["plays"]) if lastfm.get("album") else "",
                )
                .replace("{track}", escape_markdown(lastfm["name"]))
                .replace("{track.name}", escape_markdown(lastfm["name"]))
                .replace("{track.url}", lastfm["url"])
                .replace(
                    "{track.image}",
                    lastfm["image"]["url"] if lastfm["image"] else "",
                )
                .replace(
                    "{track.cover}",
                    lastfm["image"]["url"] if lastfm["image"] else "",
                )
                .replace("{track.plays}", comma(lastfm["plays"]))
                .replace(
                    "{lower(artist)}",
                    escape_markdown(lastfm["artist"]["name"].lower()),
                )
                .replace(
                    "{lower(artist.name)}",
                    escape_markdown(lastfm["artist"]["name"].lower()),
                )
                .replace(
                    "{lower(album)}",
                    escape_markdown(lastfm["album"]["name"].lower())
                    if lastfm.get("album")
                    else "",
                )
                .replace(
                    "{lower(album.name)}",
                    escape_markdown(lastfm["album"]["name"].lower())
                    if lastfm.get("album")
                    else "",
                )
                .replace("{lower(track)}", escape_markdown(lastfm["name"].lower()))
                .replace("{lower(track.name)}", escape_markdown(lastfm["name"].lower()))
                .replace(
                    "{upper(artist)}",
                    escape_markdown(lastfm["artist"]["name"].upper()),
                )
                .replace(
                    "{upper(artist.name)}",
                    escape_markdown(lastfm["artist"]["name"].upper()),
                )
                .replace(
                    "{upper(album)}",
                    escape_markdown(lastfm["album"]["name"].upper())
                    if lastfm.get("album")
                    else "",
                )
                .replace(
                    "{upper(album.name)}",
                    escape_markdown(lastfm["album"]["name"].upper())
                    if lastfm.get("album")
                    else "",
                )
                .replace("{upper(track)}", escape_markdown(lastfm["name"].upper()))
                .replace("{upper(track.name)}", escape_markdown(lastfm["name"].upper()))
                .replace(
                    "{title(artist)}",
                    escape_markdown(lastfm["artist"]["name"].title()),
                )
                .replace(
                    "{title(artist.name)}",
                    escape_markdown(lastfm["artist"]["name"].title()),
                )
                .replace(
                    "{title(album)}",
                    escape_markdown(lastfm["album"]["name"].title())
                    if lastfm.get("album")
                    else "",
                )
                .replace(
                    "{title(album.name)}",
                    escape_markdown(lastfm["album"]["name"].title())
                    if lastfm.get("album")
                    else "",
                )
                .replace("{title(track)}", escape_markdown(lastfm["name"].title()))
                .replace("{title(track.name)}", escape_markdown(lastfm["name"].title()))
            )
            if lastfm["artist"].get("crown"):
                self.script = self.script.replace("{artist.crown}", "👑")
            else:
                self.script = self.script.replace("`{artist.crown}`", "").replace(
                    "{artist.crown}", ""
                )
        if youtube := kwargs.get("youtube"):
            self.script = (
                self.script.replace("{youtube}", youtube["title"])
                .replace("{youtube.title}", youtube["title"])
                .replace("{youtube.url}", youtube["url"])
                .replace("{youtube.id}", youtube["id"])
                # .replace("{youtube.thumbnail}", youtube["thumbnail"])
                .replace("{youtube.channel}", youtube["channel"]["name"])
                .replace("{youtube.channel.name}", youtube["channel"]["name"])
                .replace("{youtube.channel.url}", youtube["channel"]["url"])
                .replace("{youtube.channel.id}", youtube["channel"]["id"])
            )

        return self.script

    async def resolve_objects(self, **kwargs):
        """Attempt to resolve the objects in the script"""

        # Initialize the parser methods

        if not self.parser.tags:

            @self.parser.method(
                name="lower",
                usage="(value)",
                aliases=["lowercase", "lowercase"],
            )
            async def lower(_: None, value: str):
                """Convert the value to lowercase"""

                return value.lower()

            @self.parser.method(
                name="upper",
                usage="(value)",
                aliases=["uppercase", "uppercase"],
            )
            async def upper(_: None, value: str):
                """Convert the value to uppercase"""

                return value.upper()

            @self.parser.method(
                name="hidden",
                usage="(value)",
                aliases=["hide"],
            )
            async def _hidden(_: None, value: str):
                """Hide the value"""

                return hidden(value)

            @self.parser.method(
                name="quote",
                usage="(value)",
                aliases=["http"],
            )
            async def quote(_: None, value: str):
                """Format the value for a URL"""

                return urllib.parse.quote(value, safe="")

            @self.parser.method(
                name="len",
                usage="(value)",
                aliases=["length", "size", "count"],
            )
            async def length(_: None, value: str):
                """Get the length of the value"""

                if ", " in value:
                    return len(value.split(", "))
                elif "," in value:
                    value = value.replace(",", "")
                    if value.isnumeric():
                        return int(value)
                return len(value)

            @self.parser.method(
                name="strip",
                usage="(text) (removal)",
                aliases=["remove"],
            )
            async def _strip(_: None, text: str, removal: str):
                """Remove a value from text"""

                return text.replace(removal, "")

            @self.parser.method(
                name="random",
                usage="(items)",
                aliases=["choose", "choice"],
            )
            async def _random(_: None, *items):
                """Chooses a random item"""

                return random.choice(items)

            @self.parser.method(
                name="if",
                usage="(condition) (value if true) (value if false)",
                aliases=["%"],
            )
            async def if_statement(_: None, condition, output, err=""):
                """If the condition is true, return the output, else return the error"""

                condition, output, err = str(condition), str(output), str(err)
                if output.startswith("{") and not output.endswith("}"):
                    output += "}"
                if err.startswith("{") and not err.endswith("}"):
                    err += "}"

                if "==" in condition:
                    condition = condition.split("==")
                    if condition[0].lower().strip() == condition[1].lower().strip():
                        return output
                    else:
                        return err
                elif "!=" in condition:
                    condition = condition.split("!=")
                    if condition[0].lower().strip() != condition[1].lower().strip():
                        return output
                    else:
                        return err
                elif ">=" in condition:
                    condition = condition.split(">=")
                    if "," in condition[0]:
                        condition[0] = condition[0].replace(",", "")
                    if "," in condition[1]:
                        condition[1] = condition[1].replace(",", "")
                    if int(condition[0].strip()) >= int(condition[1].strip()):
                        return output
                    else:
                        return err
                elif "<=" in condition:
                    condition = condition.split("<=")
                    if "," in condition[0]:
                        condition[0] = condition[0].replace(",", "")
                    if "," in condition[1]:
                        condition[1] = condition[1].replace(",", "")
                    if int(condition[0].strip()) <= int(condition[1].strip()):
                        return output
                    else:
                        return err
                elif ">" in condition:
                    condition = condition.split(">")
                    if "," in condition[0]:
                        condition[0] = condition[0].replace(",", "")
                    if "," in condition[1]:
                        condition[1] = condition[1].replace(",", "")
                    if int(condition[0].strip()) > int(condition[1].strip()):
                        return output
                    else:
                        return err
                elif "<" in condition:
                    condition = condition.split("<")
                    if "," in condition[0]:
                        condition[0] = condition[0].replace(",", "")
                    if "," in condition[1]:
                        condition[1] = condition[1].replace(",", "")
                    if int(condition[0].strip()) < int(condition[1]).strip():
                        return output
                    else:
                        return err
                else:
                    if not condition.lower().strip() in (
                        "null",
                        "no",
                        "false",
                        "none",
                        "",
                    ):
                        return output
                    else:
                        return err

            @self.parser.method(
                name="message",
                usage="(value)",
                aliases=["content", "msg"],
            )
            async def message(_: None, value: str):
                """Set the message content"""

                self.objects["content"] = value

            @self.embed_parser.method(
                name="color",
                usage="(value)",
                aliases=["colour", "c"],
            )
            async def embed_color(_: None, value: str):
                """Set the color of the embed"""

                self.objects["embed"].color = get_color(value)

            @self.parser.method(
                name="button",
                usage="(url) (label: optional) (emoji: optional)",
                aliases=["url"],
            )
            async def button(_: None, url: str, label: str = None, emoji: str = None):
                """Add a link to the message"""
                _label = None
                _emoji = None

                if label and label not in ("null", "none", "no", "false", "off"):
                    _label = label
                if emoji and emoji not in ("null", "none", "no", "false", "off"):
                    _emoji = emoji

                self.objects["button"].append(
                    {
                        "url": url,
                        "label": _label,
                        "emoji": _emoji,
                    }
                )

            @self.embed_parser.method(
                name="author",
                usage="(name) <icon url> <url>",
                aliases=["a"],
            )
            async def embed_author(
                _: None, name: str, icon_url: str = None, url: str = None
            ):
                """Set the author of the embed"""

                if str(icon_url).lower() in (
                    "off",
                    "no",
                    "none",
                    "null",
                    "false",
                    "disable",
                ):
                    icon_url = None
                elif match := URL.match(str(icon_url)) and not IMAGE_URL.match(
                    str(icon_url)
                ):
                    icon_url = None
                    url = match.group()

                self.objects["embed"].set_author(name=name, icon_url=icon_url, url=url)

            @self.embed_parser.method(
                name="url",
                usage="(value)",
                aliases=["uri", "u"],
            )
            async def embed_url(_: None, value: str):
                """Set the url of the embed"""

                self.objects["embed"].url = value

            @self.embed_parser.method(name="title", usage="(value)", aliases=["t"])
            async def embed_title(_: None, value: str):
                """Set the title of the embed"""

                self.objects["embed"].title = value

            @self.embed_parser.method(
                name="description", usage="(value)", aliases=["desc", "d"]
            )
            async def embed_description(_: None, value: str):
                """Set the description of the embed"""

                self.objects["embed"].description = value

            @self.embed_parser.method(
                name="field", usage="(name) (value) <inline>", aliases=["f"]
            )
            async def embed_field(_: None, name: str, value: str, inline: bool = True):
                """Add a field to the embed"""

                self.objects["embed"].add_field(name=name, value=value, inline=inline)

            @self.embed_parser.method(
                name="thumbnail",
                usage="(url)",
                aliases=["thumb", "t"],
            )
            async def embed_thumbnail(_: None, url: str = None):
                """Set the thumbnail of the embed"""

                self.objects["embed"].set_thumbnail(url=url)

            @self.embed_parser.method(
                name="image",
                usage="(url)",
                aliases=["img", "i"],
            )
            async def embed_image(_: None, url: str = None):
                """Set the image of the embed"""

                self.objects["embed"].set_image(url=url)

            @self.embed_parser.method(
                name="footer",
                usage="(text) <icon url>",
                aliases=["f"],
            )
            async def embed_footer(_: None, text: str, icon_url: str = None):
                """Set the footer of the embed"""

                self.objects["embed"].set_footer(text=text, icon_url=icon_url)

            @self.embed_parser.method(
                name="timestamp",
                usage="(value)",
                aliases=["t"],
            )
            async def embed_timestamp(_: None, value: str = "now"):
                """Set the timestamp of the embed"""

                if value.lower() in ("now", "current", "today", "now"):
                    self.objects["embed"].timestamp = utcnow()
                else:
                    self.objects["embed"].timestamp = dateparser.parse(str(value))

    async def compile(self, **kwargs):
        """Attempt to compile the script into an object"""

        await self.resolve_variables(**kwargs)
        await self.resolve_objects(**kwargs)
        try:
            self.script = await self.parser.parse(self.script)
            for script in self.script.split("{embed}"):
                if script := script.strip():
                    self.objects["embed"] = Embed()
                    await self.embed_parser.parse(script)
                    # if result := str(result).strip():
                    #     self.objects["content"] = result
                    if embed := self.objects.pop("embed", None):
                        self.objects["embeds"].append(embed)
            self.objects.pop("embed", None)
        except Exception as error:
            if kwargs.get("validate"):
                if type(error) == TypeError:
                    function = [
                        tag
                        for tag in self.embed_parser.tags
                        if tag.callback.__name__ == error.args[0].split("(")[0]
                    ][0].name
                    parameters = str(error).split("'")[1].split(", ")
                    raise CommandError(
                        f"The **{function}** method requires the `{parameters[0]}` parameter"
                    )
                else:
                    raise error

        validation = any(self.objects.values())
        if not validation:
            self.objects["content"] = self.script
        if kwargs.get("validate"):
            if self.objects.get("embeds"):
                self._type = "embed"
            self.objects: dict = dict(content=None, embeds=list(), stickers=list())
            self.script = self._script
        return validation

    async def send(self, bound: TextChannel, **kwargs):
        """Attempt to send the embed to the channel"""

        # Attempt to compile the script
        compiled = await self.compile(**kwargs)
        if not compiled:
            if not self.script:
                self.objects["content"] = self.script
        if embed := self.objects.pop("embed", None):
            self.objects["embeds"].append(embed)
        if button := self.objects.pop("button", None):
            self.objects["view"] = LinkView(
                links=[LinkButton(**data) for data in button]
            )
        if delete_after := kwargs.get("delete_after"):
            self.objects["delete_after"] = delete_after
        if allowed_mentions := kwargs.get("allowed_mentions"):
            self.objects["allowed_mentions"] = allowed_mentions
        if reference := kwargs.get("reference"):
            self.objects["reference"] = reference
        if isinstance(bound, Webhook) and (ephemeral := kwargs.get("ephemeral")):
            self.objects["ephemeral"] = ephemeral

        return await getattr(
            bound, ("send" if not isinstance(bound, Message) else "edit")
        )(
            **self.objects,
        )

    def replace(self, key: str, value: str):
        """Replace a key word in the script"""

        self.script = self.script.replace(key, value)
        return self

    def strip(self):
        """Strip the script"""

        self.script = self.script.strip()
        return self

    def type(self, suffix: bool = True, bold: bool = True):
        """Return the script type"""

        if self._type == "embed":
            return (
                "embed"
                if not suffix
                else "an **embed message**"
                if bold
                else "an embed"
            )
        else:
            return "text" if not suffix else "a **text message**" if bold else "a text"

    def __str__(self):
        return self.script

    def __repr__(self):
        return f"<length={len(self.script)}>"


class EmbedScriptValidator(Converter):
    async def convert(self, ctx: Context, argument: str):
        script = EmbedScript(argument)
        await script.compile(validate=True)
        return script
