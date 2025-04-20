from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from main import zyn


async def setup(bot: "zyn") -> None:
    from .information import Information

    await bot.add_cog(Information(bot))
