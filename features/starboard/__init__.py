from typing import TYPE_CHECKING

from .starboard import Starboard

if TYPE_CHECKING:
    from tools.lain import lain


async def setup(bot: "lain") -> None:
    await bot.add_cog(Starboard(bot))
