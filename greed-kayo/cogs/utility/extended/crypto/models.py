import re
from datetime import datetime
from typing import Optional

from aiohttp import ClientSession
from discord import Color
from discord.ext.commands import CommandError
from pydantic import BaseModel, Field
from typing_extensions import Self
from yarl import URL

from tools.client import Context

PATTERN = {
    "btc": r"^[0-9a-fA-F]{64}$",
    "eth": r"^0x[0-9a-fA-F]{64}$",
}


async def usd_price(session: ClientSession, currency: str) -> float:
    """
    Fetch the current USD price of a currency.
    """

    async with session.get(
        URL.build(
            scheme="https",
            host="min-api.cryptocompare.com",
            path="/data/price",
            query={
                "fsym": currency,
                "tsyms": "USD",
            },
        ),
    ) as response:
        data = await response.json()
        return data.get("USD", 0.0)


class Transaction(BaseModel):
    id: str = Field(..., alias="hash")
    currency: str
    created_at: datetime = Field(..., alias="received")
    confirmations: int
    from_address: str
    to_address: str
    amount: int
    fee: int

    @property
    def url(self) -> str:
        if self.currency == "LTC":
            return f"https://live.blockcypher.com/ltc/tx/{self.id}"

        return f"https://www.blockchain.com/explorer/transactions/{self.currency.lower()}/{self.id}"

    @property
    def color(self) -> Color:
        return Color.red() if self.confirmations <= 0 else Color.green()

    @classmethod
    async def fetch(
        cls,
        session: ClientSession,
        tx_type: str,
        id: str,
    ) -> Optional[Self]:
        """
        Fetch a transaction by its ID.
        """

        async with session.get(
            URL.build(
                scheme="https",
                host="api.blockcypher.com",
                path=f"/v1/{tx_type.lower()}/main/txs/{id}",
            ),
        ) as response:
            if not response.ok:
                return

            data = await response.json()
            return cls(
                **data,
                currency=tx_type.upper(),
                from_address=data["inputs"][0]["addresses"][0],
                to_address=data["outputs"][0]["addresses"][0],
                amount=data["total"],
                fee=data["fees"],
            )

    @classmethod
    async def convert(cls, ctx: Context, argument: str) -> Self:
        """
        Convert an argument into a transaction.
        """

        sliced = argument.split(":")
        if len(sliced) == 2:
            tx_type, id = sliced
            tx = await cls.fetch(
                ctx.bot.session,
                tx_type,
                id,
            )
            if tx:
                return tx

        for tx_type, pattern in PATTERN.items():
            if match := re.search(pattern, argument):
                tx = await cls.fetch(
                    ctx.bot.session,
                    tx_type,
                    match.group(),
                )
                if tx:
                    return tx

        raise CommandError("That doesn't look like a valid **transaction ID**!")
