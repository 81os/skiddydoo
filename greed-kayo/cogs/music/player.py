from pomice import Track, TrackType, Player as PomicePlayer
from collections import deque
from typing import TYPE_CHECKING
from time import time
from async_timeout import timeout
from asyncio import Queue as AsyncQueue, TimeoutError, sleep
from contextlib import suppress
from datetime import timedelta
import random
from discord import Embed, HTTPException

if TYPE_CHECKING:
    from discord.abc import MessageableChannel


class Duration:
    @staticmethod
    def natural_duration(value: float, ms: bool = True) -> str:
        num_seconds = int(value / 1000) if ms else int(value)
        hours = num_seconds // 3600
        minutes = (num_seconds % 3600) // 60
        seconds = num_seconds % 60
        formatted_time = f"{hours:02}:" if hours else ""
        formatted_time += f"{minutes:02}:" if minutes or hours else "00:"
        formatted_time += f"{seconds:02}" if seconds or minutes or hours else "00"
        return formatted_time

    @staticmethod
    def natural_timedelta(value: timedelta, suffix: bool = True, **kwargs) -> str:
        return (
            naturaltime(value, **kwargs)
            if suffix
            else naturaltime(value, **kwargs).removesuffix(" ago")
        )


class Queue(AsyncQueue):
    def __init__(self, maxlen=500):
        super().__init__()
        self._queue = deque(maxlen=maxlen)
        self.loops: Track | bool = False
        self.current_track: Track = None

    def __bool__(self):
        return bool(self._queue)

    def shuffle(self):
        random.shuffle(self._queue)

    async def put(self, item):
        if self.full():
            raise asyncio.QueueFull()
        self._queue.append(item)

    async def get(self):
        if not self._queue:
            return None
        item = self._queue.popleft()
        if self.loops and self.current_track:
            self._queue.appendleft(self.current_track)
        return item

    def full(self):
        return len(self._queue) == self._queue.maxlen

    def is_empty(self):
        return not self._queue

    def __len__(self):
        return len(self._queue)

    def clear(self):
        self._queue.clear()


class Player(PomicePlayer):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.queue = Queue()
        self.invoke: MessageableChannel = None
        self.waiting: bool = False

    async def insert(self, track: Track) -> Track:
        try:
            await self.queue.put(track)
        except asyncio.QueueFull:
            return None
        return track

    async def do_next(self) -> None:
        if self.waiting:
            return
        self.waiting = True
        track = None
        try:
            async with timeout(5):
                track: Track = await self.queue.get()
        except TimeoutError:
            await self.destroy()
            return
        finally:
            self.waiting = False

        if track is not None:
            self.queue.current_track = track
            await self.play(track)
            if self.invoke:
                embed = Embed(
                    title="Now Playing",
                    description=f"> [*`{track}`*]({track.uri})",
                )
                if track.track_type == TrackType.YOUTUBE:
                    embed.set_image(url=track.thumbnail)
                else:
                    embed.set_thumbnail(url=track.thumbnail)

                with suppress(HTTPException):
                    await self.invoke.send(embed=embed)

                if self.invoke.guild and self.invoke.guild.voice_client:
                    channel: VoiceChannel = self.invoke.guild.voice_client.channel
                    if channel:
                        await channel.edit(status=f"{track} by {track.author}")
                    if not self.is_playing:
                        await channel.edit(status=None)
        else:
            if self.queue.empty():
                async with timeout(30):
                    try:
                        await self.destroy()
                    except TimeoutError:
                        await self.destroy()

    async def destroy(self):
        if self.guild.id in self._node._players:
            await super().destroy()

    def toggle_loop(self):
        self.queue.loops = not self.queue.loops
        return self.queue.loops

    def clear_queue(self):
        self.queue.clear()
