from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional, Tuple, Type

from discord.ext import commands

if TYPE_CHECKING:
    from tools.lain import lain


__all__: Tuple[str, ...] = ("Cog",)


class Cog(commands.Cog):
    if TYPE_CHECKING:
        emoji: Optional[str]
        brief: Optional[str]
        hidden: bool

    __slots__: Tuple[str, ...] = ("bot", "hidden", "brief", "emoji")

    def __init_subclass__(cls: Type[Cog], **kwargs: Any) -> None:
        cls.emoji = kwargs.pop("emoji", None)
        cls.brief = kwargs.pop("brief", None)
        cls.hidden = kwargs.pop("hidden", False)
        return super().__init_subclass__(**kwargs)

    def __init__(self, bot: lain, *args: Any, **kwargs: Any) -> None:
        self.bot: lain = bot
        super().__init__(*args, **kwargs)
