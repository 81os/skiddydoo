from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from main import zyn


async def setup(bot: "zyn") -> None:
    from .utility import Utility

    await bot.add_cog(Utility(bot))
