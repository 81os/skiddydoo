from __future__ import annotations

from copy import copy
from string import Formatter
from typing import List, Optional, cast

from discord import Guild
from discord.ext.commands import BadArgument
from discord.ext.commands.view import ExpectedClosingQuoteError, StringView

from main import zyn
from tools.client import Context


class _TrackingFormatter(Formatter):
    def __init__(self):
        super().__init__()
        self.max = -1

    def get_value(self, key, args, kwargs):
        if isinstance(key, int):
            self.max = max((key, self.max))

        return super().get_value(key, args, kwargs)


class AliasEntry:
    """
    An object containing all required information about an alias.
    """

    name: str
    invoke: str
    command: str

    def __init__(
        self,
        name: str,
        *,
        invoke: str,
        command: str,
    ):
        self.name = name
        self.invoke = invoke
        self.command = command

    def extra_args(self, ctx: Context) -> List[str]:
        """
        When an alias is executed by a user in chat this function tries
            to get any extra arguments passed in with the call.
            Whitespace will be trimmed from both ends.
        """

        prefix = ctx.prefix or ctx.clean_prefix
        buffer = ctx.message.content[len(prefix) + len(self.name) :]

        args: List[str] = []
        view = StringView(buffer)
        view.skip_ws()

        while not view.eof:
            previous = view.index
            try:
                word = view.get_quoted_word()
            except ExpectedClosingQuoteError:
                break

            if not word:
                break

            elif view.index - previous > len(word):
                word = "".join(
                    (view.buffer[previous], word, view.buffer[view.index - 1])
                )

            args.append(word)
            view.skip_ws()

        return args

    async def __call__(self, ctx: Context) -> None:
        """
        Invoke an alias with a cloned message.
        """

        prefix = ctx.prefix or ctx.clean_prefix
        message = copy(ctx.message)
        try:
            args = self.extra_args(ctx)
        except BadArgument:
            return

        trackform = _TrackingFormatter()
        try:
            command = trackform.format(self.invoke, *args)
        except (ValueError, IndexError):
            return

        message.content = (
            f'{prefix}{command} {" ".join(args[trackform.max + 1:])}'.strip()
        )
        await ctx.bot.process_commands(message)

    @classmethod
    async def get(cls, guild: Guild, name: str) -> Optional[AliasEntry]:
        bot = cast(zyn, guild._state._get_client())

        record = await bot.db.fetchrow(
            """
            SELECT *
            FROM aliases
            WHERE guild_id = $1
            AND name = $2
            """,
            guild.id,
            name.lower(),
        )
        if not record:
            return

        return cls(
            record["name"],
            invoke=record["invoke"],
            command=record["command"],
        )
