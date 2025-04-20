from typing import TYPE_CHECKING, List, Optional, Union

from discord import Guild, Member, Role
from discord.abc import GuildChannel

import config
from tools.cache import cache

if TYPE_CHECKING:
    from main import zyn


class Settings:
    bot: "zyn"
    guild: Guild
    prefixes: List[str]
    reskin: bool
    reposter_prefix: bool
    reposter_delete: bool
    reposter_embed: bool
    welcome_removal: bool
    booster_role_base_id: Optional[int]
    booster_role_include_ids: List[int]
    lock_role_id: Optional[int]
    lock_ignore_ids: List[int]
    log_ignore_ids: List[int]
    reassign_ignore_ids: List[int]
    reassign_roles: bool
    invoke_kick: Optional[str]
    invoke_ban: Optional[str]
    invoke_unban: Optional[str]
    invoke_timeout: Optional[str]
    invoke_untimeout: Optional[str]

    def __init__(self, bot: "zyn", guild: Guild, record: dict):
        self.bot = bot
        self.guild = guild
        self.prefixes = record.get("prefixes", [config.CLIENT.PREFIX])
        self.reskin = record.get("reskin", False)
        self.reposter_prefix = record.get("reposter_prefix", True)
        self.reposter_delete = record.get("reposter_delete", False)
        self.reposter_embed = record.get("reposter_embed", True)
        self.welcome_removal = record.get("welcome_removal", False)
        self.booster_role_base_id = record.get("booster_role_base_id")
        self.booster_role_include_ids = record.get("booster_role_include_ids", [])
        self.lock_role_id = record.get("lock_role_id")
        self.lock_ignore_ids = record.get("lock_ignore_ids", [])
        self.log_ignore_ids = record.get("log_ignore_ids", [])
        self.reassign_ignore_ids = record.get("reassign_ignore_ids", [])
        self.reassign_roles = record.get("reassign_roles", False)
        self.invoke_kick = record.get("invoke_kick")
        self.invoke_ban = record.get("invoke_ban")
        self.invoke_unban = record.get("invoke_unban")
        self.invoke_timeout = record.get("invoke_timeout")
        self.invoke_untimeout = record.get("invoke_untimeout")

    @property
    def booster_role_base(self) -> Optional[Role]:
        if not self.booster_role_base_id:
            return None
        return self.guild.get_role(self.booster_role_base_id)

    @property
    def booster_role_include(self) -> List[Role]:
        return [
            role
            for role_id in self.booster_role_include_ids
            if (role := self.guild.get_role(role_id)) is not None
        ]

    @property
    def lock_role(self) -> Role:
        if not self.lock_role_id:
            return self.guild.default_role
        return self.guild.get_role(self.lock_role_id) or self.guild.default_role

    @property
    def lock_ignore(self) -> List[GuildChannel]:
        return [
            channel
            for channel_id in self.lock_ignore_ids
            if (channel := self.guild.get_channel(channel_id)) is not None
        ]

    @property
    def log_ignore(self) -> List[Union[GuildChannel, Member]]:
        return [
            target
            for target_id in self.log_ignore_ids
            if (target := self.guild.get_channel(target_id))
            or (target := self.guild.get_member(target_id))
        ]

    @property
    def reassign_ignore(self) -> List[Role]:
        return [
            role
            for role_id in self.reassign_ignore_ids
            if (role := self.guild.get_role(role_id)) is not None
        ]

    async def update(self, **kwargs):
        async with self.bot.db.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    """
                    UPDATE settings
                    SET
                        prefixes = $2,
                        reskin = $3,
                        reposter_prefix = $4,
                        reposter_delete = $5,
                        reposter_embed = $6,
                        welcome_removal = $7,
                        booster_role_base_id = $8,
                        booster_role_include_ids = $9,
                        lock_role_id = $10,
                        lock_ignore_ids = $11,
                        log_ignore_ids = $12,
                        reassign_ignore_ids = $13,
                        reassign_roles = $14,
                        invoke_kick = $15,
                        invoke_ban = $16,
                        invoke_unban = $17,
                        invoke_timeout = $18,
                        invoke_untimeout = $19
                    WHERE guild_id = $1
                    """,
                    self.guild.id,
                    kwargs.get("prefixes", self.prefixes),
                    kwargs.get("reskin", self.reskin),
                    kwargs.get("reposter_prefix", self.reposter_prefix),
                    kwargs.get("reposter_delete", self.reposter_delete),
                    kwargs.get("reposter_embed", self.reposter_embed),
                    kwargs.get("welcome_removal", self.welcome_removal),
                    kwargs.get("booster_role_base_id", self.booster_role_base_id),
                    kwargs.get(
                        "booster_role_include_ids", self.booster_role_include_ids
                    ),
                    kwargs.get("lock_role_id", self.lock_role_id),
                    kwargs.get("lock_ignore_ids", self.lock_ignore_ids),
                    kwargs.get("log_ignore_ids", self.log_ignore_ids),
                    kwargs.get("reassign_ignore_ids", self.reassign_ignore_ids),
                    kwargs.get("reassign_roles", self.reassign_roles),
                    kwargs.get("invoke_kick", self.invoke_kick),
                    kwargs.get("invoke_ban", self.invoke_ban),
                    kwargs.get("invoke_unban", self.invoke_unban),
                    kwargs.get("invoke_timeout", self.invoke_timeout),
                    kwargs.get("invoke_untimeout", self.invoke_untimeout),
                )

        for key, value in kwargs.items():
            setattr(self, key, value)

        self.fetch.invalidate_containing(self.guild.id)

    @classmethod
    @cache()
    async def fetch(cls, bot: "zyn", guild: Guild) -> "Settings":
        record = await bot.db.fetchrow(
            """
            INSERT INTO settings (guild_id)
            VALUES ($1)
            ON CONFLICT (guild_id)
            DO UPDATE
            SET guild_id = EXCLUDED.guild_id
            RETURNING *
            """,
            guild.id,
        )
        return cls(bot, guild, record)
