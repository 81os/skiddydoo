from json import dumps, loads
from logging import getLogger
from typing import Any, List, Optional, Union

from asyncpg import Connection, Pool, Record as DefaultRecord, create_pool

import config
from .settings import Settings

log = getLogger("/db")


def ENCODER(value: Any) -> str:
    return dumps(value)


def DECODER(value: bytes) -> Any:
    return loads(value)


class Record(DefaultRecord):
    def __getattr__(self, name: Union[str, Any]) -> Any:
        return self[name]

    def __setitem__(self, name: Union[str, Any], value: Any) -> None:
        super().__setitem__(name, value)

    def to_dict(self) -> dict[str, Any]:
        return dict(self)


class Database(Pool):
    async def execute(
        self,
        query: str,
        *args: Any,
        timeout: Optional[float] = None,
    ) -> str:
        return await super().execute(query, *args, timeout=timeout)

    async def fetch(
        self,
        query: str,
        *args: Any,
        timeout: Optional[float] = None,
    ) -> List[Record]:
        return await super().fetch(query, *args, timeout=timeout)

    async def fetchrow(
        self,
        query: str,
        *args: Any,
        timeout: Optional[float] = None,
    ) -> Optional[Record]:
        return await super().fetchrow(query, *args, timeout=timeout)

    async def fetchval(
        self,
        query: str,
        *args: Any,
        timeout: Optional[float] = None,
    ) -> Optional[Union[str, int]]:
        return await super().fetchval(query, *args, timeout=timeout)


async def init(connection: Connection):
    await connection.set_type_codec(
        "jsonb",
        schema="pg_catalog",
        encoder=ENCODER,
        decoder=DECODER,
        format="text",
    )

    with open("tools/client/database/schema.sql", "r", encoding="UTF-8") as buffer:
        schema = buffer.read()
        await connection.execute(schema)


async def connect() -> Database:
    pool = await create_pool(
        config.DATABASE.DSN,
        record_class=Record,
        init=init,
    )
    if not pool:
        raise RuntimeError("Connection to PostgreSQL server failed!")

    log.debug("Connection to PostgreSQL has been established.")
    return pool  # type: ignore


__all__ = ("Database", "Settings")
