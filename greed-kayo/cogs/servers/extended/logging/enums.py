from typing import List

from discord.enums import Enum
from discord.ext.commands import BadArgument

from tools.client import Context


class LogType(Enum):
    MESSAGE = 1 << 0
    MEMBER = 1 << 1
    ROLE = 1 << 2
    CHANNEL = 1 << 3
    MODERATION = 1 << 4
    INVITE = 1 << 5
    VOICE = 1 << 6
    EMOJI = 1 << 7

    @classmethod
    def all(cls) -> List["LogType"]:
        """
        Returns all LogType enums.
        """

        return list(LogType)

    @classmethod
    def ALL(cls) -> int:
        """
        Returns the value of all LogType enums.
        """

        return sum(log_type.value for log_type in LogType)

    def __str__(self):
        return self.name.lower()

    @classmethod
    def from_value(cls, value: int) -> List["LogType"]:
        """
        Returns a list of LogType enums from a value.
        """

        return [log_type for log_type in LogType if log_type.value & value]

    @classmethod
    async def convert(cls, ctx: Context, argument: str) -> "LogType":
        """
        Converts a string to a LogType.
        """

        try:
            return cls[argument.upper()]
        except KeyError as exc:
            raise BadArgument(f"Not real `{argument}`.") from exc
