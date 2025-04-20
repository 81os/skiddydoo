from typing import List, Optional, cast

from aiohttp import ClientSession
from bs4 import BeautifulSoup, Tag
from discord.ext.commands import CommandError
from pydantic import BaseModel, Field
from typing_extensions import Self
from yarl import URL

import config


class SiteLink(BaseModel):
    url: str
    title: str
    snippet: Optional[str] = Field("...")


class TweetItem(BaseModel):
    url: str
    text: str
    footer: str


class Result(BaseModel):
    url: str
    title: str
    snippet: Optional[str] = Field("...")
    highlights: List[str] = Field(default_factory=list)
    extended_links: List[SiteLink] = Field(default_factory=list)
    tweets: List[TweetItem] = Field(default_factory=list)

    @classmethod
    def from_soup(cls, soup: BeautifulSoup) -> List[Self]:
        results: List[Self] = []
        for result in soup.find_all("div", class_="g"):
            if not (result.a and result.h3):
                continue

            url = cast(str, result.a["href"])
            if not url.startswith("http"):
                continue

            title = result.h3.text
            snippet = (
                description.text
                if (
                    description := result.select_one(".IsZvec")
                    or result.select_one(".VwiC3b")
                )
                else None
            )
            highlights = [highlight.text for highlight in result.find_all("em")]
            links = [
                SiteLink(
                    url=link.a["href"],
                    title=link.a.text,
                    snippet=link.div.text[len(link.a.text) :],
                )
                for link in result.find_all("div", class_="usJj9c")
            ]
            tweets: List[TweetItem] = []
            if not snippet:
                for tweet in result.select(".fy7gGf"):
                    if not tweet.a or any(tweet.a["href"] == t.url for t in tweets):
                        continue

                    tweet_text = tweet.find("div", role="heading")
                    if not tweet_text or not tweet_text.text.strip():
                        continue

                    tweets.append(
                        TweetItem(
                            url=tweet.a["href"],
                            text=tweet_text.text.strip(),
                            footer=tweet.select_one(".ZYHQ7e").text,  # type: ignore
                        )
                    )

            results.append(
                cls(
                    url=url,
                    title=title,
                    snippet=snippet,
                    highlights=highlights,
                    extended_links=links,
                    tweets=tweets,
                )
            )

        return results


class KnowledgeItem(BaseModel):
    name: str
    value: str

    @classmethod
    def from_soup(cls, soup: BeautifulSoup) -> List[Self]:
        items: List[Self] = []
        for item in soup.find_all("div", class_="wDYxhc"):
            name = item.find("span", class_="w8qArf")
            value = item.select_one(".kno-fv")
            if name and value:
                items.append(KnowledgeItem(name=name.text[:-2], value=value.text))  # type: ignore

        return items


class KnowledgeSource(BaseModel):
    url: str
    name: str


class KnowledgePanel(BaseModel):
    description: Optional[str] = None
    source: Optional[KnowledgeSource] = None
    items: List[KnowledgeItem] = Field(default_factory=list)

    @classmethod
    def from_soup(cls, soup: BeautifulSoup) -> Optional[Self]:
        panel = soup.find("div", class_="kno-rdesc")
        if not isinstance(panel, Tag):
            return None

        return cls(
            description=panel.span.text if panel.span else None,  # type: ignore
            source=(
                KnowledgeSource(
                    url=panel.a["href"],  # type: ignore
                    name=panel.a.text,  # type: ignore
                )
                if panel.a
                else None
            ),
            items=KnowledgeItem.from_soup(soup),
        )


class Google(BaseModel):
    header: Optional[str] = None
    description: Optional[str] = None
    panel: Optional[KnowledgePanel] = None
    results: List[Result] = Field(default_factory=list)

    @classmethod
    async def search(
        cls,
        session: ClientSession,
        query: str,
    ) -> Self:
        url = URL.build(
            scheme="https",
            host="www.google.com",
            path="/search",
        )
        async with session.get(
            url,
            params={"q": query},
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/119.0.0.0 Safari/537.36"
                )
            },
        ) as response:
            if not response.ok:
                raise CommandError(
                    "An error occurred while fetching the search results."
                    + f"\n> Please contact the developer in the [support server]({config.CLIENT.SUPPORT_SERVER})."
                )

            data = await response.text()
            soup = BeautifulSoup(data, "lxml")
            header = soup.find("div", class_="PZPZlf ssJ7i B5dxMb")
            description = soup.select_one(".iAIpCb")

            return cls(
                header=header.text if header else None,
                description=description.text if description else None,
                panel=KnowledgePanel.from_soup(soup),
                results=Result.from_soup(soup),
            )
