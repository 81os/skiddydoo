from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from main import zyn


async def setup(bot: "zyn") -> None:
    from .voicemaster import VoiceMaster

    await bot.add_cog(VoiceMaster(bot))
