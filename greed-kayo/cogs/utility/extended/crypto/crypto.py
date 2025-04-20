from contextlib import suppress
from logging import getLogger
from typing import List, Optional, cast

from asyncpg import UniqueViolationError
from discord import Embed, HTTPException, Message, TextChannel
from discord.ext.commands import group
from discord.ext.tasks import loop
from discord.utils import format_dt

from tools import CompositeMetaClass, MixinMeta
from tools.client import Context
from tools.formatter import plural, shorten
from tools.paginator import Paginator

from .models import Transaction, usd_price

log = getLogger("zyn/crypto")


class Crypto(MixinMeta, metaclass=CompositeMetaClass):
    """
    Various crypto utilities.
    """

    async def cog_load(self) -> None:
        self.check_transactions.start()
        return await super().cog_load()

    async def cog_unload(self) -> None:
        self.check_transactions.cancel()
        return await super().cog_unload()

    @loop(minutes=5)
    async def check_transactions(self):
        """
        Notify users when a transaction has been confirmed.
        """

        records = await self.bot.db.fetch("SELECT * FROM crypto")

        scheduled_deletion: List[int] = []
        for record in records:
            user = self.bot.get_user(record["user_id"])
            channel = cast(
                Optional[TextChannel],
                self.bot.get_channel(record["channel_id"]),
            )
            if not user or not channel:
                scheduled_deletion.append(record["transaction_id"])
                continue

            transaction = await Transaction.fetch(
                self.bot.session,
                record["transaction_type"],
                record["transaction_id"],
            )
            if not transaction:
                log.warning(
                    "%s transaction %r no longer exists",
                    record["transaction_type"],
                    record["transaction_id"],
                )
                scheduled_deletion.append(record["transaction_id"])
                continue

            if transaction.confirmations <= 0:
                continue

            embed = Embed(
                url=transaction.url,
                title=f"{transaction.currency} Transaction Confirmed",
                description=f"Your transaction has been confirmed with **{plural(transaction.confirmations):confirmation}**",
            )
            embed.set_footer(text=transaction.id)

            with suppress(HTTPException):
                await channel.send(user.mention, embed=embed)

            scheduled_deletion.append(record["transaction_id"])

        if scheduled_deletion:
            await self.bot.db.execute(
                """
                DELETE FROM crypto
                WHERE transaction_id = ANY($1::TEXT[])
                """,
                scheduled_deletion,
            )

    @group(
        aliases=[
            "btc",
            "eth",
            "txid",
        ],
        invoke_without_command=True,
    )
    async def crypto(self, ctx: Context, transaction: Transaction) -> Message:
        """
        View information about a transaction.
        """

        usd = await usd_price(self.bot.session, transaction.currency)

        embed = Embed(
            color=transaction.color,
            url=transaction.url,
            title=shorten(transaction.id, 32),
            description=(
                f"**{transaction.currency}** transaction with **{plural(transaction.confirmations):confirmation}**"
                + f"\n> {format_dt(transaction.created_at)} ({format_dt(transaction.created_at, 'R')})"
            ),
        )
        embed.add_field(
            name="**Amount**",
            value=f"{transaction.amount / 1e8:g} ({(transaction.amount / 1e8) * usd:,.2f} USD)",
        )
        embed.add_field(
            name="**Fee**",
            value=f"{transaction.fee / 1e8:g} ({(transaction.fee / 1e8) * usd:,.2f} USD)",
        )
        embed.add_field(name="**Sender**", value=transaction.from_address, inline=False)
        embed.add_field(name="**Receiver**", value=transaction.to_address, inline=False)

        return await ctx.send(embed=embed)

    @crypto.command(
        name="subscribe",
        aliases=[
            "sub",
            "watch",
            "notify",
        ],
        usage="<transaction>",
        brief="<transaction-id>",
    )
    async def crypto_subscribe(self, ctx: Context, transaction: Transaction) -> Message:
        """
        Receive a notification when a transaction has been confirmed.
        """

        if transaction.confirmations > 0:
            return await ctx.warn(
                f"Transaction [`{shorten(transaction.id, 12)}`]({transaction.url}) has already been confirmed"
            )

        try:
            await self.bot.db.execute(
                """
                INSERT INTO crypto (user_id, channel_id, transaction_id, transaction_type)
                VALUES ($1, $2, $3, $4)
                """,
                ctx.author.id,
                ctx.channel.id,
                transaction.id,
                transaction.currency,
            )
        except UniqueViolationError:
            return await ctx.warn(
                f"You're already subscribed to [`{shorten(transaction.id, 12)}`]({transaction.url})"
            )

        return await ctx.approve(
            f"You'll now be notified when [`{shorten(transaction.id, 12)}`]({transaction.url}) has been confirmed"
        )

    @crypto.command(
        name="cancel",
        aliases=["remove", "rm"],
        usage="[transaction]",
        brief="<transaction-id>",
    )
    async def crypto_cancel(self, ctx: Context, transaction: Transaction) -> Message:
        """
        Cancel a transaction subscription.
        """

        result = await self.bot.db.execute(
            """
            DELETE FROM crypto
            WHERE user_id = $1
            AND transaction_id = $2
            """,
            ctx.author.id,
            transaction.id,
        )
        if result == "DELETE 0":
            return await ctx.warn(
                f"You're not subscribed to [`{shorten(transaction.id, 12)}`]({transaction.url})"
            )

        return await ctx.approve(
            f"You'll no longer be notified when [`{shorten(transaction.id, 12)}`]({transaction.url}) has been confirmed"
        )

    @crypto.command(
        name="list",
        aliases=["ls"],
    )
    async def crypto_list(self, ctx: Context) -> Message:
        """
        View your transaction subscriptions.
        """

        channels = [
            f"{channel.mention} - [`{shorten(record['transaction_id'], 12)}`](https://www.blockchain.com/explorer/transactions/{record['transaction_type'].lower()}/{record['transaction_id']})"
            for record in await self.bot.db.fetch(
                """
                SELECT * FROM crypto
                WHERE user_id = $1
                """,
                ctx.author.id,
            )
            if (channel := self.bot.get_channel(record["channel_id"]))
            and isinstance(channel, TextChannel)
        ]
        if not channels:
            return await ctx.warn("You don't have any transaction subscriptions")

        paginator = Paginator(
            ctx,
            entries=channels,
            embed=Embed(title="Transaction Subscriptions"),
        )
        return await paginator.start()
