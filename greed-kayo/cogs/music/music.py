from pomice import NodePool, Node, Track, TrackInvalidPosition, TrackLoadError, Playlist
from discord import (
    Attachment,
    TextChannel,
    Embed,
    HTTPException,
    Message,
    Member,
    VoiceState,
    VoiceChannel,
    File,
)

from discord.ext.commands import hybrid_command, Cog, hybrid_group
from asyncio import TimeoutError
from async_timeout import timeout
from pomice.enums import SearchType, TrackType
from humanize import naturaltime
from .player import Player
from typing import Optional
from main import zyn
from tools.client import Context
from tools.paginator import Paginator
from logging import getLogger
from time import time
import random
from io import BytesIO
from tools.conversion import Duration

log = getLogger("cogs/pomice")


class Music(Cog):
    def __init__(self, bot: zyn) -> None:
        self.bot = bot
        self.bot.loop.create_task(self.start_nodes())

    async def start_nodes(self) -> Node:
        await self.bot.wait_until_ready()

        await NodePool().create_node(
            bot=self.bot,
            host="127.0.0.1",
            port=6742,
            password="whatguyisnt",
            identifier=f"zyn{str(time())}",
            spotify_client_id="c5ea934dfe2a47a68047629dba9e6aaf",
            spotify_client_secret="536dac49c02c4de4bc210a2c29ebb547",
        )

    async def cog_check(self, ctx: Context) -> bool:
        if not ctx.author.voice or not ctx.author.voice.channel:
            await ctx.warn("You need to be in a voice channel to use this command.")
            return False

        player: Player = ctx.voice_client
        if player is None or not player.is_connected:
            if ctx.command.name in ["play", "join"]:
                return True
            await ctx.warn("I am not connected to a voice channel.")
            return False

        if ctx.author.voice.channel != player.channel:
            await ctx.warn(
                f"You must be connected to {player.channel.mention} to use this command."
            )
            return False

        return True

    @Cog.listener()
    async def on_pomice_track_end(self, player: Player, track: Track, _):
        await player.do_next()

    @Cog.listener()
    async def on_voice_state_update(
        self, member: Member, before: VoiceState, after: VoiceState
    ) -> VoiceChannel:
        if member == self.bot.user or after.channel is not None:
            return
        voice_client: Player = member.guild.voice_client
        if voice_client and before.channel == voice_client.channel:
            if not any(not m.bot for m in before.channel.members):
                await voice_client.destroy()

    @hybrid_command(name="join", aliases=["joi", "j", "summon", "su", "con", "connect"])
    async def join(self, ctx: Context, *, channel: VoiceChannel = None) -> None:
        """
        join voicechannel with bot
        """
        if not channel:
            channel = getattr(ctx.author.voice, "channel", None)
            if not channel:
                return await ctx.warn(
                    "You must be in a voice channel to use this command"
                )
        await ctx.author.voice.channel.connect(cls=Player)
        player: Player = ctx.voice_client
        player.invoke = ctx.channel
        await ctx.approve(f"Joined the voice channel `{channel.name}`")

    @hybrid_command(
        name="play",
        aliases=["pla", "p"],
        usage="[search|url|playlist]",
        brief="Good Days SZA",
    )
    async def play(self, ctx: Context, *, search: Optional[str] = None) -> Message:
        """
        Play or insert a song in queue
        """

        if not (player := ctx.voice_client):
            player = await ctx.author.voice.channel.connect(cls=Player, self_deaf=True)

            player.invoke = ctx.channel
        if not search and ctx.message.attachments:

            search: Attachment = ctx.message.attachments[0].url

        if not search:
            await ctx.warn("Please provide a song name or URL.")
            return

        try:
            result = await player.get_tracks(
                search, ctx=ctx, search_type=SearchType.ytmsearch
            )

        except TrackLoadError:
            await ctx.warn("No tracks were found for that query.")
            return

        if not result:
            await ctx.warn("No tracks were found for that query.")
            return

        if isinstance(result, Playlist):
            for track in result.tracks:
                await player.insert(track)
            await ctx.approve(
                f"Added **{result.track_count} tracks** from [{result}]({result.uri}) to the queue."
            )
        else:
            track = result[0]
            await player.insert(track)
            if player.is_playing:
                await ctx.approve(f"Added [{track}]({track.uri}) to the queue.")
            else:
                await player.do_next()

    @hybrid_command(aliases=["pau", "pa"])
    async def pause(self, ctx: Context) -> Message:
        player: Player = ctx.voice_client
        if player.is_paused or not player.is_connected:
            return
        await ctx.approve(f"Player has been paused by {ctx.author.mention}.")
        return await player.set_pause(True)

    @hybrid_command(name="seek", usage="[time]", brief="2:30")
    async def seek(self, ctx: Context, time: float) -> Message:
        """
        Seeks to a specific time in the currently playing track.
        """
        player: Player = ctx.voice_client
        if not player or not player.is_playing():
            await ctx.send("No track is currently playing.")
            return
        try:
            if time < 0:
                raise ValueError("Time must be a positive number.")
            await player.seek(time * 1000)
            await ctx.approve(f"Seeked to {time} second(s) in the track.")
        except ValueError as ve:
            await ctx.send(str(ve))
        except TrackInvalidPosition:
            await ctx.warn(f"cannot seek track to {time}")
        except Exception as e:
            await ctx.warn(str(e))

    @hybrid_command(aliases=["res"])
    async def resume(self, ctx: Context) -> Message:
        """
        resume music player
        """
        player: Player = ctx.voice_client

        if not player.is_paused or not player.is_connected:
            return
        return await player.set_pause(False)

    @hybrid_command(aliases=["nex", "next", "sk"])
    async def skip(self, ctx: Context) -> Message:
        """
        skip song in music player
        """
        player: Player = ctx.voice_client
        if not player.is_connected:
            return
        else:
            await player.stop()
            await ctx.message.add_reaction("✅")

    @hybrid_command()
    async def stop(self, ctx: Context) -> Message:
        player: Player = ctx.voice_client

        if not player.is_connected:
            return
        await player.destroy()
        await ctx.message.add_reaction("✅")

    @hybrid_group(name="queue", aliases=["q"], invoke_without_command=True)
    async def queue(self, ctx: Context) -> Message:
        """
        View all tracks in the queue.
        """
        player: Player = ctx.voice_client

        if not player.queue:
            if not (track := player.current):
                return await ctx.neutral("There isn't a track playing")

            return await ctx.send(
                embed=Embed(
                    title="Currently Playing",
                    description=(
                        f"[{track}]({track.uri})"
                        + (
                            f"\n> **{track.author}**"
                            if track.track_type != TrackType.YOUTUBE
                            else ""
                        )
                    ),
                )
            )
        tracks = [f"[{track.title}]({track.uri})" for track in player.queue._queue]

        embed = Embed(
            description=(
                (
                    f"Playing [{track.title}]({track.uri}) "
                    + (
                        f"by **{track.author}** "
                        if track.track_type != TrackType.YOUTUBE
                        else ""
                    )
                    + f"`{Duration.natural_duration(player.position)}`/`{Duration.natural_duration(track.length)}`"
                )
                if (track := player.current)
                else ""
            ),
        )
        if track := player.current:
            if track.track_type != TrackType.YOUTUBE:
                embed.set_thumbnail(url=track.thumbnail)
            else:
                embed.set_thumbnail(url=track.thumbnail)
        paginator = Paginator(
            ctx,
            entries=tracks,
            embed=embed,
        )
        return await paginator.start()

    @queue.command(name="nowplaying", aliases=["np"])
    async def now_playing(self, ctx: Context) -> Message:
        """
        Checks the currently playing song in queue
        """
        player: Player = ctx.voice_client
        if player is None or not player.is_playing:
            return await ctx.send("There is no track currently playing.")

        current_track = player.current
        if current_track is None:
            return await ctx.warn("There is no track currently playing.")

        position = Duration().convert(ctx, str(player.position))
        length = Duration().convert(ctx, str(current_track.length))
        url = "https://imagination.squareweb.app/nowplaying"
        params = {
            "title": current_track.title or "",
            "artist": current_track.author or "",
            "artwork": current_track.thumbnail or "",
            "length": str(length) or "",
            "position": str(position) or "",
            "volume": player.volume,
            "key": "urnanscloset",
            "vertical": "1",
        }

        async with self.bot.session.get(url, params=params) as response:
            if response.status != 200:
                return await ctx.warn("Failed to fetch now playing cover.")

            image_url = str(response.url)

        async with self.bot.session.get(image_url) as image_response:
            if image_response.status != 200:
                return await ctx.warn("Failed to download now playing cover.")

            image_data = await image_response.read()
            image_buffer = BytesIO(image_data)
            image_buffer.seek(0)

        file = File(image_buffer, filename="zyn-nowplaying.png")
        embed = Embed(title="Now Playing")
        embed.set_image(url="attachment://zyn-nowplaying.png")
        await ctx.send(embed=embed, file=file)

    @queue.command(aliases=["mix", "shuf"])
    async def shuffle(self, ctx: Context) -> Message:
        """
        shuffle the music queue
        """
        player: Player = ctx.voice_client
        if not player.is_connected:
            return
        if player.queue.is_empty():
            await ctx.warn("Queue is empty.")
        player.queue.shuffle()
        return await ctx.message.add_reaction("✅")

    @queue.command(name="clear", aliases=["c"])
    async def clear(self, ctx: Context) -> Message:
        """
        clears music player queue
        """
        player: Player = ctx.voice_client
        if player.is_playing:
            player.clear_queue()
            await ctx.approve("Successfully cleared the music queue")

    @queue.command(name="loop", aliases=["l"])
    async def loop(self, ctx: Context) -> Message:
        """
        loops the track in player
        """
        player: Player = ctx.voice_client
        if player.is_playing:
            player.toggle_loop()
            await ctx.approve("Successfully looped the track")
        else:
            return await ctx.message.add_reaction("❌")

    @queue.command(aliases=["rmv", "rm"], usage="<index>", brief="3")
    async def remove(self, ctx: Context, index: int) -> Message:
        player: Player = ctx.voice_client

        queue = player.queue._queue
        if index < 1 or index > len(queue):
            return await ctx.warn(f"Track doesn't exist at position `{index}`")

        track = queue[index - 1]
        del queue[index - 1]
        return await ctx.approve(
            f"Removed [{track.title}]({track.uri}) from the queue."
        )

    @queue.command(name="jump", aliases=["qjump", "qj"], usage="[index]", brief="2")
    async def jump(self, ctx: Context, index: int) -> Message:
        player: Player = ctx.voice_client
        if not player.is_playing and not player.queue.get_queue():
            return await ctx.warn("There are no tracks playing in the queue.")
        queue = player.queue._queue
        if not (0 <= index < len(queue)):
            return await ctx.warn(
                "Invalid index. Please provide a valid index within the range of the queue."
            )
        track = queue[index]
        player.queue.jump(item=track)
        await ctx.message.add_reaction("✅")

    @hybrid_command(aliases=["v", "vol"], usage="[volume]", brief="80")
    async def volume(self, ctx: Context, *, vol: int) -> Message:
        player: Player = ctx.voice_client

        if not 0 < vol < 101:
            return await ctx.warn("Please enter a value between 1 and 100.")
        await player.set_volume(vol)
        await ctx.approve(f"Set the volume to **{vol}**%")
