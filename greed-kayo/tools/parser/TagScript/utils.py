import re
from inspect import isawaitable
from typing import Any, Awaitable, Callable, T, TypeVar, Union

import discord

__all__ = ("escape_content", "maybe_await", "DPY2")

T = TypeVar("T")

DPY2 = discord.version_info >= (2, 0, 0, "alpha", 0)

pattern = re.compile(r"(?<!\\)([{():|}])")


def _sub_match(match: re.Match) -> str:
    return "\\" + match[1]


def escape_content(string: str) -> str:
    """
    Escapes given input to avoid tampering with engine/block behavior.

    Returns
    -------
    str
        The escaped content.
    """
    if string is None:
        return
    return pattern.sub(_sub_match, string)


async def maybe_await(
    func: Callable[..., Union[T, Awaitable[T]]], *args: Any, **kwargs: Any
) -> T:
    """
    Await the given function if it is awaitable or call it synchronously.

    Returns
    -------
    Any
        The result of the awaitable function.
    """
    value = func(*args, **kwargs)
    return await value if isawaitable(value) else value
