import re
from datetime import timedelta
from typing import Sequence, Set

from boltons.iterutils import remap
from discord.utils import remove_markdown

S_1 = re.compile("([A-Z][a-z]+)")
S_2 = re.compile("([A-Z]+)")


class plural:
    value: str | int | list
    markdown: str

    def __init__(self, value: str | int | list, md: str = ""):
        self.value = value
        self.markdown = md

    def __format__(self, format_spec: str) -> str:
        v = self.value
        if isinstance(v, str):
            v = (
                int(v.split(" ", 1)[-1])
                if v.startswith(("CREATE", "DELETE"))
                else int(v)
            )

        elif isinstance(v, list):
            v = len(v)

        singular, sep, plural = format_spec.partition("|")
        plural = plural or f"{singular}s"
        return (
            f"{self.markdown}{v:,}{self.markdown} {plural}"
            if abs(v) != 1
            else f"{self.markdown}{v:,}{self.markdown} {singular}"
        )


def vowel(value: str) -> str:
    return ("an" if value[0].lower() in "aeiou" else "a") + " " + value


def duration(value: float, ms: bool = True) -> str:
    h = int((value / (1000 * 60 * 60)) % 24) if ms else int((value / (60 * 60)) % 24)
    m = int((value / (1000 * 60)) % 60) if ms else int((value / 60) % 60)
    s = int((value / 1000) % 60) if ms else int(value % 60)

    result = ""
    if h:
        result += f"{h}:"

    result += f"{m}:" if m else "00:"
    result += f"{str(s).zfill(2)}" if s else "00"

    return result


def human_join(seq: Sequence[str], delim: str = ", ", final: str = "or") -> str:
    size = len(seq)
    if size == 0:
        return ""

    if size == 1:
        return seq[0]

    if size == 2:
        return f"{seq[0]} {final} {seq[1]}"

    return delim.join(seq[:-1]) + f" {final} {seq[-1]}"


def codeblock(text: str, lang: str = "") -> str:
    return f"```{lang}\n{text}\n```"


def shorten(value: str, length: int = 24) -> str:
    if len(value) > length:
        value = value[: length - 2] + (".." if len(value) > length else "").strip()

    BROKEN_HYPERLINK = ["[", "]", "(", ")"]
    for char in BROKEN_HYPERLINK:
        value = value.replace(char, "")

    return remove_markdown(value)


def snake_cased(s) -> str:
    return "_".join(
        S_1.sub(r" \1", S_2.sub(r" \1", s.replace("-", " "))).split()
    ).lower()


def snake_cased_dict(
    obj: dict,
    remove_nulls: bool = True,
    all_nulls: bool = False,
    discard_keys: Set[str] = set(),
) -> dict:
    def _visit(p, k, v):
        k = snake_cased(str(k))
        if k in discard_keys or (remove_nulls and ((not v and all_nulls) or v == "")):
            return False
        return (k, v)

    return remap(obj, visit=_visit)


def short_timespan(num_seconds: float | timedelta, max_units=3, delim: str = "") -> str:
    if isinstance(num_seconds, timedelta):
        num_seconds = num_seconds.total_seconds()

    units = [
        ("y", 60 * 60 * 24 * 365),
        ("w", 60 * 60 * 24 * 7),
        ("d", 60 * 60 * 24),
        ("h", 60 * 60),
        ("m", 60),
        ("s", 1),
    ]

    parts = []
    for unit, div in units:
        if num_seconds >= div:
            val = int(num_seconds // div)
            num_seconds %= div
            parts.append(f"{val}{unit}")
            if len(parts) == max_units:
                break

    return delim.join(parts)
