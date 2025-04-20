from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from main import zyn


async def setup(bot: "zyn") -> None:
    from .moderation import Moderation

    await bot.add_cog(Moderation(bot))
