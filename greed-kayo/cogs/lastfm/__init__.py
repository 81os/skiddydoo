from logging import getLogger
from random import choice
from typing import TYPE_CHECKING

from aiohttp import ClientSession as OriginalClientSession, ClientTimeout, TCPConnector
from colorama import Fore
from yarl import URL

from config import AUTHORIZATION

if TYPE_CHECKING:
    from main import zyn

log = getLogger("zyn/lastfm")

BASE_URL = URL.build(
    scheme="https",
    host="ws.audioscrobbler.com",
)


class AsyncClient(OriginalClientSession):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs, connector=TCPConnector(ssl=False))
        self.retry_attempts = 3

    async def _get(self, *args, **kwargs):
        kwargs["params"] = {
            "api_key": choice(AUTHORIZATION.LASTFM),
            "autocorrect": 1,
            "format": "json",
            **kwargs.get("params", {}),
        }
        log.debug(
            f"GET {Fore.LIGHTMAGENTA_EX}{kwargs['params'].get('method', 'unknown')}{Fore.RESET} with {Fore.LIGHTRED_EX}{kwargs['params']['api_key']}{Fore.RESET}."
        )
        return await super().get(*args, **kwargs)

    async def get(self, *args, **kwargs):
        attempt = 0
        while attempt < self.retry_attempts:
            try:
                response = await self._get(*args, **kwargs)
                if response.status == 429:
                    retry_after = response.headers.get("Retry-After", None)
                    delay = int(retry_after) if retry_after else (2**attempt)
                    log.warning(
                        f"Last.fm API rate limit exceeded, retrying after {delay} seconds..."
                    )
                    kwargs["params"]["api_key"] = choice(AUTHORIZATION.LASTFM)
                    await asyncio.sleep(delay)
                    attempt += 1
                    continue
                response.raise_for_status()
                log.debug(f"Received response: {response.status} from {response.url}")
                return response
            except ClientResponseError as e:
                log.error(
                    f"Response error occurred: {e.status} - {e.message} from {e.request_info.url}"
                )
                attempt += 1
                await asyncio.sleep(2**attempt)
            except ClientConnectionError as e:
                log.error(f"Connection error occurred: {e}")
                attempt += 1
                await asyncio.sleep(2**attempt)
            except ClientError as e:
                log.error(f"Client error occurred: {e}")
                attempt += 1
                await asyncio.sleep(2**attempt)
            except Exception as e:
                log.error(f"Unexpected error occurred: {e}")
                raise
        log.error(
            f"Failed to get a successful response after {self.retry_attempts} attempts"
        )
        raise Exception("Max retries exceeded")


http = AsyncClient(
    headers={
        "User-Agent": "zyn Last.fm Integration (DISCORD BOT)",
    },
    base_url=BASE_URL.human_repr(),
    timeout=ClientTimeout(total=20),
)


async def setup(bot: "zyn") -> None:
    from .lastfm import Lastfm

    await bot.add_cog(Lastfm(bot))
