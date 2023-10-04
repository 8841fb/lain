from typing import TYPE_CHECKING

from .lastfm import lastfm

if TYPE_CHECKING:
    from tools.lain import lain


async def setup(bot: "lain") -> None:
    await bot.add_cog(lastfm(bot))
