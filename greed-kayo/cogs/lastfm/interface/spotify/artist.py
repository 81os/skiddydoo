from __future__ import annotations

from typing import Optional

from asyncspotify import Client
from pydantic import BaseModel


class SpotifyArtist(BaseModel):
    id: str
    url: str
    name: str
    genre: str
    followers: str

    def __str__(self) -> str:
        return self.url

    @property
    def _variable(self) -> str:
        return "spotify"

    @classmethod
    async def search(cls, client: Client, query: str) -> Optional["SpotifyArtist"]:
        """
        Search for an artist on Spotify.
        """

        artist = await client.search_artist(query)
        if not artist:
            return None

        return cls(
            id=artist.id,
            url=artist.link,
            name=artist.name,
            genre=artist.genres[0],
            followers=artist.follower_count,
        )
