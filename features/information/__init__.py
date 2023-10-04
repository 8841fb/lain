from typing import TYPE_CHECKING

from .information import Information

if TYPE_CHECKING:
    from tools.lain import lain


async def setup(bot: "lain") -> None:
    await bot.add_cog(Information(bot))
