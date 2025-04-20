from logging import getLogger

from asyncpg import UniqueViolationError
from discord import Embed, HTTPException, Message
from discord import Thread as ThreadChannel
from discord.ext.commands import Cog, group, has_permissions

from tools import CompositeMetaClass, MixinMeta
from tools.client import Context
from tools.formatter import plural
from tools.paginator import Paginator

log = getLogger("zyn/watcher")


class Thread(MixinMeta, metaclass=CompositeMetaClass):
    """
    Watch threads to prevent them from being archived.
    """

    @Cog.listener()
    async def on_thread_update(
        self,
        before: ThreadChannel,
        after: ThreadChannel,
    ) -> None:
        """
        Watch threads to prevent them from being archived.
        """

        if not after.archived:
            return

        watched = await self.bot.db.fetch(
            """
            SELECT *
            FROM thread
            WHERE thread_id = $1
            """,
            after.id,
        )
        if not watched:
            return

        try:
            await after.edit(
                archived=False,
                auto_archive_duration=10080,
                reason="Thread is being watched",
            )
        except HTTPException:
            log.warning(
                "Failed to unarchive thread %s (%s) in guild %s (%s).",
                after,
                after.id,
                after.guild,
                after.guild.id,
            )
            await self.bot.db.execute(
                """
                DELETE FROM thread
                WHERE thread_id = $1
                """,
                after.id,
            )
        else:
            log.info(
                "Unarchived thread %s (%s) in guild %s (%s).",
                after,
                after.id,
                after.guild,
                after.guild.id,
            )

    @group(
        aliases=["watcher"], invoke_without_command=True, description="manage channels"
    )
    @has_permissions(manage_channels=True)
    async def thread(self, ctx: Context) -> Message:
        """
        Manage thread watching and management.
        """

        return await ctx.send_help(ctx.command)

    @thread.command(
        name="add",
        aliases=["create", "watch"],
        description="manage channels",
        usage="<thread>",
        brief="#devs-thread",
    )
    @has_permissions(manage_channels=True)
    async def thread_add(self, ctx: Context, *, thread: ThreadChannel) -> Message:
        """
        Add a thread to be watched.
        """

        try:
            await self.bot.db.execute(
                """
                INSERT INTO thread (
                    guild_id,
                    thread_id
                )
                VALUES ($1, $2)
                """,
                ctx.guild.id,
                thread.id,
            )
        except UniqueViolationError:
            return await ctx.warn(f"Already watching thread {thread.mention}!")

        return await ctx.approve(f"Now watching thread {thread.mention} for archival")

    @thread.command(
        name="remove",
        aliases=[
            "unwatch",
        ],
        description="manage channels",
        usage="<thread>",
        brief="#devs-thread",
    )
    @has_permissions(manage_channels=True)
    async def thread_remove(self, ctx: Context, *, thread: ThreadChannel) -> Message:
        """
        Remove a thread from being watched.
        """

        result = await self.bot.db.execute(
            """
                DELETE FROM thread
                WHERE guild_id = $1
                AND thread_id = $2
                """,
            ctx.guild.id,
            thread.id,
        )
        if result == "DELETE 0":
            return await ctx.warn(f"Thread {thread.mention} isn't being watched!")

        return await ctx.approve(
            f"No longer watching thread {thread.mention} for archival"
        )

    @thread.command(
        name="clear",
        aliases=["clean", "reset"],
        description="manage channels",
    )
    @has_permissions(manage_channels=True)
    async def thread_clear(self, ctx: Context) -> Message:
        """
        Stop watching all threads.
        """

        await ctx.prompt(
            "Are you sure you want to stop watching all threads?",
        )

        result = await self.bot.db.execute(
            """
            DELETE FROM thread
            WHERE guild_id = $1
            """,
            ctx.guild.id,
        )
        if result == "DELETE 0":
            return await ctx.warn("No threads are being watched!")

        return await ctx.approve(f"No longer watching {plural(result, md='`'):thread}")

    @thread.command(name="list", aliases=["ls"], description="manage threads")
    @has_permissions(manage_channels=True)
    async def thread_list(self, ctx: Context) -> Message:
        """
        View all threads being watched.
        """

        channels = [
            f"{thread.mention} (`{thread.id}`)"
            for record in await self.bot.db.fetch(
                """
                SELECT thread_id
                FROM thread
                WHERE guild_id = $1
                """,
                ctx.guild.id,
            )
            if (thread := ctx.guild.get_thread(record["thread_id"]))
        ]
        if not channels:
            return await ctx.warn("No threads are being watched!")

        paginator = Paginator(
            ctx,
            entries=channels,
            embed=Embed(
                title="Threads being watched",
            ),
        )
        return await paginator.start()

    @thread.command(
        name="lock",
        aliases=["archive"],
        description="manage threads",
        usage="[thread]",
        brief="#devs-thread",
    )
    @has_permissions(manage_threads=True)
    async def thread_lock(
        self, ctx: Context, *, thread: ThreadChannel = None
    ) -> Message:
        """
        Lock a thread.
        If no thread is mentioned, it will lock the thread executed in.
        """

        if not thread:
            thread = ctx.channel

        try:
            await thread.edit(
                locked=True,
                archived=True,
                auto_archive_duration=10080,
                reason="Thread is being locked",
            )
        except HTTPException:
            log.warning(
                "Failed to archive thread %s (%s) in guild %s (%s).",
                thread,
                thread.id,
                ctx.guild,
                ctx.guild.id,
            )
            return await ctx.warn(f"Failed to lock thread {thread.mention}!")

        return await ctx.approve(f"Locked thread {thread.mention}!")

    @thread.command(
        name="unlock",
        aliases=["unarchive"],
        description="manage threads",
        usage="[thread]",
        brief="#devs-thread",
    )
    @has_permissions(manage_threads=True)
    async def thread_unlock(
        self, ctx: Context, *, thread: ThreadChannel = None
    ) -> Message:
        """
        Unlock a thread.
        If no thread is mentioned, it will unlock the thread executed in.
        """

        if not thread:
            thread = ctx.channel

        try:
            await thread.edit(
                archived=False,
                auto_archive_duration=10080,
                reason="Thread is being unlocked",
            )
        except HTTPException:
            log.warning(
                "Failed to unarchive thread %s (%s) in guild %s (%s).",
                thread,
                thread.id,
                ctx.guild,
                ctx.guild.id,
            )
            return await ctx.warn(f"Failed to unlock thread {thread.mention}!")

        return await ctx.approve(f"Unlocked thread {thread.mention}!")

    @thread.command(
        name="rename",
        aliases=["name"],
        description="manage threads",
        usage="<thread> <name>",
        brief="#devs-thread devs",
    )
    @has_permissions(manage_threads=True)
    async def thread_rename(
        self, ctx: Context, thread: ThreadChannel, *, name: str
    ) -> Message:
        """
        Rename a thread.
        """

        try:
            await thread.edit(
                name=name,
                reason="Thread is being renamed",
            )
        except HTTPException:
            log.warning(
                "Failed to rename thread %s (%s) in guild %s (%s).",
                thread,
                thread.id,
                ctx.guild,
                ctx.guild.id,
            )
            return await ctx.warn(f"Failed to rename thread {thread.mention}!")

        return await ctx.approve(f"Renamed thread {thread.mention} to {name}!")

    @thread.command(
        name="delete",
        aliases=["del"],
        description="manage threads",
        usage="<thread>",
        brief="#devs",
    )
    @has_permissions(manage_threads=True)
    async def thread_delete(self, ctx: Context, thread: ThreadChannel) -> Message:
        """
        Delete a thread.
        """

        try:
            await thread.delete()
        except HTTPException:
            log.warning(
                "Failed to delete thread %s (%s) in guild %s (%s).",
                thread,
                thread.id,
                ctx.guild,
                ctx.guild.id,
            )
            return await ctx.warn(f"Failed to delete thread {thread.mention}!")

        return await ctx.approve(f"Deleted thread {thread.mention}!")
