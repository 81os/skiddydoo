import aiohttp
import discord
from discord.ext import commands
from pydantic import BaseModel
from bs4 import BeautifulSoup

from main import zyn


class Modal(BaseModel):
    name: str
    username: str
    bio: str
    repositories: int
    contributions: int


class Github:
    def __init__(self, bot: zyn):
        self.bot = bot

    async def scrape(self, username: str) -> Modal:
        url = f"https://github.com/{username}"
        async with self.bot.session.get(url) as response:
            if response.status != 200:
                raise Exception("Could not fetch profile data")

            html = await response.text()
            soup = BeautifulSoup(html, "html.parser")

            name = soup.find("span", class_="vcard-fullname")
            username = soup.find("span", class_="vcard-username")
            bio = soup.find("div", class_="p-note user-profile-bio")
            repositories = soup.find("span", class_="Counter")
            contributions = soup.find("h2", class_="f4 text-normal mb-2")

            return Modal(
                name=name.text.strip() if name else "N/A",
                username=username.text.strip() if username else "N/A",
                bio=bio.text.strip() if bio else "N/A",
                repositories=int(repositories.text.strip()) if repositories else 0,
                contributions=(
                    int(contributions.text.strip().split()[0].replace(",", ""))
                    if contributions
                    else 0
                ),
            )
