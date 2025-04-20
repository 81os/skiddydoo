from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from main import zyn


async def setup(bot: "zyn") -> None:
    from .fun import Fun

    await bot.add_cog(Fun(bot))
