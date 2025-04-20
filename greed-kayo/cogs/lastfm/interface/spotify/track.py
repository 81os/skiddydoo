from __future__ import annotations

from typing import Optional, cast

from asyncspotify import Client, SimpleArtist
from pydantic import BaseModel

from tools.formatter import duration


class SpotifyTrack(BaseModel):
    id: str
    url: str
    name: str
    artist: str
    duration: Optional[str] = "0:00"

    def __str__(self) -> str:
        return self.url

    @property
    def _variable(self) -> str:
        return "spotify"

    @classmethod
    async def search(cls, client: Client, query: str) -> Optional["SpotifyTrack"]:
        """
        Search for a track on Spotify.
        """

        track = await client.search_track(query)
        if not track:
            return None

        artist = cast(SimpleArtist, track.artists[0])
        return cls(
            id=track.id,
            url=track.link,
            name=track.name,
            artist=artist.name,
            duration=duration(track.duration.total_seconds(), ms=False),
        )
