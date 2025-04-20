from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from main import zyn


async def setup(bot: "zyn") -> None:
    from .owner import Owner

    await bot.add_cog(Owner(bot))
