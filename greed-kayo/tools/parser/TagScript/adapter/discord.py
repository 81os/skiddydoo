from random import choice

import discord
from humanize import ordinal

from ..interface import Adapter
from ..utils import escape_content
from ..verb import Verb

__all__ = (
    "AttributeAdapter",
    "MemberAdapter",
    "ChannelAdapter",
    "GuildAdapter",
)


class AttributeAdapter(Adapter):
    __slots__ = ("object", "_attributes", "_methods")

    def __init__(self, base):
        self.object = base
        created_at = getattr(base, "created_at", None) or discord.utils.snowflake_time(
            base.id
        )
        self._attributes = {
            "id": base.id,
            "created_at": created_at,
            "created_at_timestamp": int(created_at.timestamp()),
            "name": getattr(base, "name", str(base)),
            "mention": getattr(base, "mention", str(base)),
        }
        self._methods = {}
        self.update_attributes()
        self.update_methods()

    def __repr__(self):
        return f"<{type(self).__qualname__} object={self.object!r}>"

    def update_attributes(self):
        pass

    def update_methods(self):
        pass

    def get_value(self, ctx: Verb) -> str:
        should_escape = False

        if ctx.parameter is None:
            return_value = str(self.object)
        else:
            try:
                value = self._attributes[ctx.parameter]
            except KeyError:
                if method := self._methods.get(ctx.parameter):
                    value = method()
                else:
                    return

            if isinstance(value, tuple):
                value, should_escape = value

            return_value = str(value) if value is not None else None

        return escape_content(return_value) if should_escape else return_value


class MemberAdapter(AttributeAdapter):
    """
    The ``{author}`` block with no parameters returns the tag invoker's full username
    and discriminator, but passing the attributes listed below to the block payload
    will return that attribute instead.

    **Aliases:** ``user``

    **Usage:** ``{author([attribute])``

    **Payload:** None

    **Parameter:** attribute, None
    """

    object: discord.Member

    def update_attributes(self):
        member = self.object
        join_pos = sorted(
            member.guild.members,
            key=lambda member: member.joined_at or member.created_at,
        ).index(member)
        joined_at = getattr(member, "joined_at", member.created_at)

        self._attributes.update(
            {
                "color": member.color,
                "colour": member.color,
                "nick": member.display_name,
                "display_name": member.display_name,
                "avatar": member.display_avatar.url,
                "joined_at": joined_at,
                "joined_at_timestamp": int(joined_at.timestamp()),
                "bot": member.bot,
                "booster": bool(member.premium_since),
                "boost": bool(member.premium_since),
                "boost_since": member.premium_since,
                "boost_since_timestamp": (
                    int(member.premium_since.timestamp())
                    if member.premium_since
                    else None
                ),
                "top_role": getattr(member, "top_role", ""),
                "join_position": join_pos,
                "join_position_suffix": ordinal(join_pos),
                "roles": ", ".join(r.name for r in reversed(member.roles)),
                "role_ids": ", ".join(str(r.id) for r in reversed(member.roles)),
            }
        )


class ChannelAdapter(AttributeAdapter):
    """
    The ``{channel}`` block with no parameters returns the channel's full name
    but passing the attributes listed below to the block payload
    will return that attribute instead.

    **Usage:** ``{channel([attribute])``

    **Payload:** None

    **Parameter:** attribute, None

    Attributes
    ----------
    id
        The channel's ID.
    name
        The channel's name.
    created_at
        The channel's creation date.
    timestamp
        The channel's creation date as a UTC timestamp.
    nsfw
        Whether the channel is nsfw.
    mention
        A formatted text that pings the channel.
    topic
        The channel's topic.
    """

    object: discord.TextChannel | discord.Thread

    def update_attributes(self):
        channel = self.object
        if isinstance(channel, discord.TextChannel):
            self._attributes.update(
                {
                    "nsfw": channel.nsfw,
                    "topic": channel.topic,
                    "position": channel.position,
                    "slowmode_delay": channel.slowmode_delay,
                    "slowmode": channel.slowmode_delay,
                }
            )

        self._attributes.update(
            {
                "type": channel.type.name,
                "category": channel.category.mention if channel.category else None,
                "category_id": channel.category.id if channel.category else None,
            }
        )


class GuildAdapter(AttributeAdapter):
    """
    The ``{server}`` block with no parameters returns the server's name
    but passing the attributes listed below to the block payload
    will return that attribute instead.

    **Aliases:** ``guild``

    **Usage:** ``{server([attribute])``

    **Payload:** None

    **Parameter:** attribute, None

    Attributes
    ----------
    id
        The server's ID.
    name
        The server's name.
    icon
        A link to the server's icon, which can be used in embeds.
    created_at
        The server's creation date.
    timestamp
        The server's creation date as a UTC timestamp.
    member_count
        The server's member count.
    bots
        The number of bots in the server.
    humans
        The number of humans in the server.
    description
        The server's description if one is set, or "No description".
    random
        A random member from the server.
    """

    object: discord.Guild

    def update_attributes(self):
        guild = self.object
        self._attributes.update(
            {
                "icon": guild.icon,
                "banner": guild.banner,
                "splash": guild.splash,
                "discovery": guild.discovery_splash,
                "owner_id": guild.owner_id,
                "shard": guild.shard_id,
                "description": guild.description,
                "count": len(guild.members),
                "emoji_count": len(guild.emojis),
                "role_count": len(guild.roles),
                "channels": ", ".join(c.mention for c in guild.channels),
                "channel_count": len(guild.channels),
                "text_channels": ", ".join(c.mention for c in guild.text_channels),
                "text_channel_count": len(guild.text_channels),
                "voice_channels": ", ".join(c.mention for c in guild.voice_channels),
                "voice_channel_count": len(guild.voice_channels),
                "category_channels": ", ".join(c.mention for c in guild.categories),
                "category_count": len(guild.categories),
                "boost_count": guild.premium_subscription_count,
                "boost_level": guild.premium_tier,
                "boost_tier": guild.premium_tier,
            }
        )

    def update_methods(self):
        additional_methods = {"random": self.random_member}
        self._methods.update(additional_methods)

    def random_member(self):
        return choice(self.object.members)
