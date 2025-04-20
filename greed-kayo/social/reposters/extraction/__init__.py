from logging import getLogger
from typing import Optional

from jishaku.functools import executor_function
from yt_dlp import DownloadError, YoutubeDL

import config
from tools import CACHE_ROOT

from .models import Information

log = getLogger("zyn/ydl")
log.setLevel("CRITICAL")


@executor_function
def download(url: str, options: dict = {}, **kwargs) -> Optional[Information]:
    if "download" not in kwargs:
        kwargs["download"] = False

    YDL_OPTS = {
        "logger": log,
        "quiet": True,
        "verbose": False,
        "no_warnings": True,
        "final_ext": "mp4",
        "age_limit": 18,
        "concurrent_fragment_downloads": 12,
        "outtmpl": str(CACHE_ROOT / "%(id)s.%(ext)s"),
        "cachedir": str(CACHE_ROOT / "ydl"),
        "noplaylist": True,
        "restrictfilenames": True,
        "cookiefile": "cookies.txt",
        **options,
    }
    if "youtu" in url:
        YDL_OPTS["format"] = "best"

    if config.WARP:
        YDL_OPTS["proxy"] = config.WARP

    with YoutubeDL(YDL_OPTS) as ydl:
        try:
            info = ydl.extract_info(url, **kwargs)
        except DownloadError:
            return

        if info:
            return Information(**info)
