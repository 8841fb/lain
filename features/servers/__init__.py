from typing import TYPE_CHECKING

from .servers import Servers

if TYPE_CHECKING:
    from tools.lain import lain


async def setup(bot: "lain") -> None:
    await bot.add_cog(Servers(bot))
