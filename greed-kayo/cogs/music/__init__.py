from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from main import zyn


async def setup(bot: "zyn"):
    from .music import Music

    await bot.add_cog(Music(bot))
