from __future__ import annotations

from discord.ext.commands import FlagConverter as OriginalFlagConverter
from typing_extensions import Self

from .context import Context, Embed, HelpCommand, Interaction
from .database import Database, Settings
from .logging import init_logging
from .redis import Redis


class FlagConverter(
    OriginalFlagConverter,
    case_insensitive=True,
    prefix="--",
    delimiter=" ",
):
    @property
    def values(self):
        return self.get_flags().values()

    async def convert(self, ctx: Context, argument: str):
        argument = argument.replace("—", "--")
        return await super().convert(ctx, argument)

    async def find(
        self,
        ctx: Context,
        argument: str,
        *,
        remove: bool = True,
    ) -> tuple[str, Self]:
        """
        Run the conversion and return the
        result with the remaining string.
        """

        argument = argument.replace("—", "--")
        flags = await self.convert(ctx, argument)

        if remove:
            for key, values in flags.parse_flags(argument).items():
                aliases = getattr(self.get_flags().get(key), "aliases", [])
                for _key in aliases:
                    argument = argument.replace(f"--{_key} {' '.join(values)}", "")

                argument = argument.replace(f"--{key} {' '.join(values)}", "")

        return argument.strip(), flags


__all__ = (
    "FlagConverter",
    "Context",
    "Database",
    "Settings",
    "Redis",
    "Embed",
    "HelpCommand",
    "init_logging",
    "Interaction",
)
