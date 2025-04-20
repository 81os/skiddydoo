from contextlib import asynccontextmanager
from http.cookiejar import MozillaCookieJar
from logging import getLogger
from secrets import token_urlsafe
from typing import AsyncGenerator, Literal, Optional

from anyio import CapacityLimiter
from playwright.async_api import (
    Browser,
    BrowserContext,
    Page,
    Playwright,
    async_playwright,
)
from pydantic import BaseConfig, BaseModel

import config

log = getLogger("zyn/browser")
jar = MozillaCookieJar()
jar.load("cookies.txt")


class CookieModel(BaseModel):
    name: str
    value: str
    url: Optional[str] = None
    domain: Optional[str] = None
    path: Optional[str] = None
    expires: int = -1
    httpOnly: Optional[bool] = None
    secure: Optional[bool] = None
    sameSite: Optional[Literal["Lax", "None", "Strict"]] = None

    class Config(BaseConfig):
        orm_mode = True
        from_attributes = True


class BrowserHandler:
    limiter: CapacityLimiter
    playwright: Optional[Playwright] = None
    browser: Optional[Browser] = None
    context: Optional[BrowserContext] = None

    def __init__(self) -> None:
        self.limiter = CapacityLimiter(4)

    async def cleanup(self) -> None:
        if self.playwright:
            await self.playwright.stop()

        if self.browser:
            await self.browser.close()

    async def init(self) -> None:
        await self.cleanup()
        self.playwright = await async_playwright().start()
        self.browser = await self.playwright.chromium.launch(
            proxy=(
                {
                    "server": config.WARP,
                }
                if config.WARP
                else None
            ),
        )
        self.context = await self.browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/93.0.4577.63 Safari/537.36"
            ),
        )
        await self.context.add_cookies(
            [
                cookie.dict(exclude_unset=True)
                for _cookie in jar
                if (cookie := CookieModel.from_orm(_cookie))
            ]  # type: ignore
        )

    @asynccontextmanager
    async def borrow_page(self) -> AsyncGenerator[Page, None]:
        if not self.context:
            raise RuntimeError("Browser context is not initialized.")

        await self.limiter.acquire()
        identifier, page = token_urlsafe(12), await self.context.new_page()
        log.debug("Borrowing page ID %s.", identifier)
        try:
            yield page
        finally:
            self.limiter.release()
            await page.close()
            log.debug("Released page ID %s.", identifier)
