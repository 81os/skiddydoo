from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from main import zyn


async def setup(bot: "zyn") -> None:
    from .social import Social

    await bot.add_cog(Social(bot))
