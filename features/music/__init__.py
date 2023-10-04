from typing import TYPE_CHECKING

from .music import Music

if TYPE_CHECKING:
    from tools.lain import lain


async def setup(bot: "lain") -> None:
    await bot.add_cog(Music(bot))
