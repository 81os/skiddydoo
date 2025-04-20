from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from main import zyn


async def setup(bot: "zyn") -> None:
    from .servers import Servers

    await bot.add_cog(Servers(bot))
