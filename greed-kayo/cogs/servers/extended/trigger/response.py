from contextlib import suppress
from typing import Annotated

from asyncpg import UniqueViolationError
from discord import Embed, HTTPException, Message, Role
from discord.ext.commands import Cog, Range, flag, group, has_permissions
from xxhash import xxh64_hexdigest

from tools import CompositeMetaClass, MixinMeta
from tools.client import Context, FlagConverter
from tools.conversion import Status
from tools.conversion.discord import StrictRole
from tools.formatter import codeblock, plural, vowel
from tools.paginator import Paginator
from tools.parser import Script


class Flags(FlagConverter):
    strict: Annotated[bool, Status] = flag(
        description="Only respond to messages that match the trigger exactly.",
        default=False,
    )
    reply: Annotated[bool, Status] = flag(
        description="Reply to the message that triggered the response.",
        default=False,
    )
    delete: Annotated[bool, Status] = flag(
        description="Delete the message that triggered the response.",
        default=False,
    )
    delete_after: Range[int, 3, 120] = flag(
        aliases=["self_destruct"],
        description="Delete the response after a certain amount of time.",
        default=0,
    )
    role: Annotated[Role, StrictRole] = flag(
        aliases=["grant", "remove"],
        description="Grant or remove a role from the author of the message.",
        default=None,
    )


class Response(MixinMeta, metaclass=CompositeMetaClass):
    """
    Send a message for a trigger.
    """

    @Cog.listener("on_message_without_command")
    async def response_listener(self, ctx: Context) -> None:
        """
        Automatically respond to a trigger.
        """

        record = await self.bot.db.fetchrow(
            """
            SELECT *
            FROM response_trigger
            WHERE guild_id = $1
            AND LOWER($2) LIKE '%' || LOWER(trigger) || '%'
            """,
            ctx.guild.id,
            ctx.message.content,
        )
        if not record:
            return

        elif (
            record["strict"]
            and record["trigger"].lower() != ctx.message.content.lower()
        ):
            return

        KEY = xxh64_hexdigest(f"responses:{ctx.author.id}")
        if await self.bot.redis.ratelimited(KEY, 1, 4):
            return

        script = Script(
            record["template"],
            [ctx.guild, ctx.author, ctx.channel],
        )

        with suppress(HTTPException):
            message = await script.send(
                ctx,
                reference=ctx.message if record["reply"] else None,
            )
            if record["delete"] and not message.reference:
                await ctx.message.delete()

            if record["delete_after"]:
                await message.delete(delay=record["delete_after"])

            if role := ctx.guild.get_role(record["role_id"]):
                if role not in ctx.author.roles:
                    await ctx.author.add_roles(
                        role,
                        reason=f"Granted by response trigger for {record['trigger']}",
                    )
                else:
                    await ctx.author.remove_roles(
                        role,
                        reason=f"Removed by response trigger for {record['trigger']}",
                    )

    @group(
        aliases=["autoresponse", "ar", "autoreply"],
        invoke_without_command=True,
    )
    @has_permissions(manage_messages=True)
    async def response(self, ctx: Context) -> None:
        """
        Automatically respond to messages.
        """

        await ctx.send_help(ctx.command)

    @response.command(
        name="add",
        aliases=["create"],
        description="manage messages",
        usage="<trigger> <script>",
        brief="LOL real.",
    )
    @has_permissions(manage_messages=True)
    async def response_add(
        self,
        ctx: Context,
        trigger: str,
        *,
        script: Script,
    ) -> Message:
        """
        Add a response trigger.
        If the trigger contains spaces, it needs to be enclosed in quotes.
        """

        if not trigger:
            return await ctx.send_help(ctx.command)

        template, flags = await Flags().find(ctx, script.template)
        if not template:
            return await ctx.warn("No template was provided")

        try:
            await self.bot.db.execute(
                """
                INSERT INTO response_trigger (
                    guild_id,
                    trigger,
                    template,
                    strict,
                    reply,
                    delete,
                    delete_after,
                    role_id
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                """,
                ctx.guild.id,
                trigger,
                template,
                flags.strict,
                flags.reply,
                flags.delete,
                flags.delete_after,
                flags.role.id if flags.role else None,
            )
        except UniqueViolationError:
            return await ctx.warn(
                f"A response trigger for **{trigger}** already exists"
            )

        return await ctx.approve(
            f"Now responding with {vowel(script.format)} message for **{trigger}**"
            + (
                " "
                + " ".join(
                    f"({flag.name})"
                    for flag in flags.values
                    if getattr(flags, flag.attribute)
                )
                if any(getattr(flags, flag.attribute) for flag in flags.values)
                else ""
            )
        )

    @response.command(
        name="edit",
        aliases=["modify"],
        description="manage messages",
        usage="<trigger> <script>",
        brief="LOL not real.",
    )
    @has_permissions(manage_messages=True)
    async def response_edit(
        self,
        ctx: Context,
        trigger: str,
        *,
        script: Script,
    ) -> Message:
        """
        Edit an existing response trigger.
        """

        template, flags = await Flags().find(ctx, script.template)
        if not template:
            return await ctx.warn("No template was provided")

        result = await self.bot.db.execute(
            """
            UPDATE response_trigger
            SET template = $3, strict = $4, reply = $5, delete = $6, delete_after = $7
            WHERE guild_id = $1
            AND trigger = $2
            """,
            ctx.guild.id,
            trigger,
            template,
            flags.strict,
            flags.reply,
            flags.delete,
            flags.delete_after,
        )
        if result == "UPDATE 0":
            return await ctx.warn(f"A response trigger for **{trigger}** doesn't exist")

        return await ctx.approve(
            f"Successfully  edited response trigger for **{trigger}**"
        )

    @response.command(
        name="remove",
        aliases=["delete", "del", "rm"],
        description="manage messages",
        usage="<trigger>",
        brief="LOL",
    )
    @has_permissions(manage_messages=True)
    async def response_remove(self, ctx: Context, *, trigger: str) -> Message:
        """
        Remove a response trigger.
        """

        result = await self.bot.db.execute(
            """
            DELETE FROM response_trigger
            WHERE guild_id = $1
            AND trigger = $2
            """,
            ctx.guild.id,
            trigger,
        )
        if result == "DELETE 0":
            return await ctx.warn(f"A response trigger for **{trigger}** doesn't exist")

        return await ctx.approve(f"Removed response trigger for **{trigger}**")

    @response.command(
        name="view",
        aliases=["show"],
        description="manage messages",
        usage="<trigger>",
        brief="LOL",
    )
    @has_permissions(manage_messages=True)
    async def response_view(self, ctx: Context, *, trigger: str) -> Message:
        """
        View an existing response trigger.
        """

        record = await self.bot.db.fetchrow(
            """
            SELECT template, strict, reply, delete, delete_after
            FROM response_trigger
            WHERE guild_id = $1
            AND trigger = $2
            """,
            ctx.guild.id,
            trigger,
        )
        if not record:
            return await ctx.warn(f"A response trigger for **{trigger}** doesn't exist")

        script = Script(record["template"], [ctx.guild, ctx.author, ctx.channel])
        embed = Embed(
            title="Response Trigger",
            description=codeblock(script.template),
        )
        embed.add_field(
            name="**Properties**",
            value="\n".join(
                f"> **{name}:** {value}"
                for name, value in record.items()
                if name != "template"
            ),
        )

        await ctx.reply(embed=embed)
        return await script.send(ctx.channel)

    @response.command(
        name="clear", aliases=["clean", "reset"], description="manage messages"
    )
    @has_permissions(manage_messages=True)
    async def response_clear(self, ctx: Context) -> Message:
        """
        Remove all response triggers.
        """

        await ctx.prompt(
            "Are you sure you want to remove all response triggers?",
        )

        result = await self.bot.db.execute(
            """
            DELETE FROM response_trigger
            WHERE guild_id = $1
            """,
            ctx.guild.id,
        )
        if result == "DELETE 0":
            return await ctx.warn("No response triggers exist for this server")

        return await ctx.approve(
            f"Successfully  removed {plural(result, md='`'):response trigger}"
        )

    @response.command(name="list", aliases=["ls"], description="manage messages")
    @has_permissions(manage_messages=True)
    async def response_list(self, ctx: Context) -> Message:
        """
        View all response triggers.
        """

        flags = ("strict", "reply", "delete", "delete_after")
        triggers = [
            f"**{record['trigger']}**"
            + (
                " (" + ", ".join(flag for flag in flags if record[flag]) + ")"
                if any(record[flag] for flag in flags)
                else ""
            )
            for record in await self.bot.db.fetch(
                """
                SELECT trigger, strict, reply, delete, delete_after
                FROM response_trigger
                WHERE guild_id = $1
                """,
                ctx.guild.id,
            )
        ]
        if not triggers:
            return await ctx.warn("No response triggers exist for this server")

        paginator = Paginator(
            ctx,
            entries=triggers,
            embed=Embed(
                title="Response Triggers",
            ),
        )
        return await paginator.start()
