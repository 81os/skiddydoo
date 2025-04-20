from itertools import groupby
from typing import Optional, List

from discord import (
    Role,
    Spotify,
    Streaming,
    Colour,
    ActivityType,
    Embed,
    Message,
    Permissions,
    PartialInviteGuild,
    Invite,
    Member,
    User,
    Guild,
)
from discord.ext.commands import Cog, command, group, parameter, has_permissions
from discord.utils import format_dt, oauth_url, utcnow
from humanfriendly import format_size
from humanize import ordinal
from psutil import Process

import config
from config import EMOJIS
from main import zyn
from tools import dominant_color
from tools.client import Context
from tools.paginator import Paginator
from tools.formatter import human_join, plural, short_timespan


class Information(Cog):
    def __init__(self, bot: zyn):
        self.bot = bot
        self.process = Process()

    @Cog.listener("on_user_update")
    async def name_history_listener(self, before: User, after: User) -> None:
        if before.name == after.name and before.global_name == after.global_name:
            return

        await self.bot.db.execute(
            """
            INSERT INTO name_history (user_id, username)
            VALUES ($1, $2)
            """,
            after.id,
            (
                before.name
                if after.name != before.name
                else (before.global_name or before.name)
            ),
        )

    @Cog.listener()
    async def on_member_unboost(self, member: Member) -> None:
        if not member.premium_since:
            return

        await self.bot.db.execute(
            """
            INSERT INTO boosters_lost (guild_id, user_id, lasted_for)
            VALUES ($1, $2, $3)
            ON CONFLICT (guild_id, user_id) DO UPDATE
            SET lasted_for = EXCLUDED.lasted_for
            """,
            member.guild.id,
            member.id,
            utcnow() - member.premium_since,
        )

    @command(aliases=["latency"])
    async def ping(self, ctx: Context) -> Message:
        """
        View the bots current latency/ping.
        """

        return await ctx.reply(f"... `{round(self.bot.latency * 1000)}ms`")

    @command(aliases=["bi", "bot", "info", "about"])
    async def botinfo(self, ctx: Context) -> Message:
        """
        View information such as commands, guilds and amount of overall users for the bot.
        """

        embed = Embed(
            description=(
                f"Serving `{len(self.bot.guilds):,}` guilds"
                f" with `{sum(g.member_count for g in self.bot.guilds):,}` users"
            )
            + (
                f"\nUtilizing `{len(set(self.bot.walk_commands())):,}` commands"
                f" across `{len(self.bot.cogs):,}` cogs"
            )
        )

        embed.set_author(
            name=self.bot.user.name,
            icon_url=self.bot.user.display_avatar.url,
            url=config.CLIENT.SUPPORT_SERVER
            or oauth_url(self.bot.user.id, permissions=Permissions(permissions=8)),
        )

        process = Process()
        embed.add_field(
            name="**System**",
            value="\n".join(
                [
                    f"**CPU:** `{process.cpu_percent()}%`",
                    f"**Memory:** `{format_size(process.memory_info().rss)}`",
                    f"**Launched:** {self.bot.uptime}",
                ]
            ),
        )

        embed.set_footer(text=f"zyn/v{self.bot.version}")

        return await ctx.reply(embed=embed)

    @command(aliases=["inv"])
    async def invite(self, ctx: Context) -> Message:
        """
        Get an invite with necessary permissions to use the bot for your server.
        """

        invite_url = oauth_url(
            self.bot.user.id,
            permissions=Permissions(permissions=8),
        )
        return await ctx.reply(invite_url)

    @command(aliases=["discord"])
    async def support(self, ctx: Context) -> Message:
        """
        Get the link to the official support server.
        """

        return await ctx.neutral(config.CLIENT.SUPPORT_SERVER)

    @command(
        aliases=[
            "servericon",
            "sicon",
        ],
        usage="serverincon",
        brief="servericon",
    )
    async def icon(
        self,
        ctx: Context,
        *,
        invite: Optional[Invite],
    ) -> Message:
        """
        View the server's current icon if present.
        """

        guild = (
            invite.guild
            if isinstance(invite, Invite)
            and isinstance(invite.guild, PartialInviteGuild)
            else ctx.guild
        )
        if not guild.icon:
            return await ctx.warn(f"**{guild}** doesn't have an icon present")

        embed = Embed(
            url=guild.icon,
            title=f"{guild}'s icon",
        )
        embed.set_image(url=guild.icon)

        return await ctx.send(embed=embed)

    @command(aliases=["sbanner"])
    async def serverbanner(
        self,
        ctx: Context,
        *,
        invite: Optional[Invite],
    ) -> Message:
        """
        View the server's current banner if present.
        """

        guild = (
            invite.guild
            if isinstance(invite, Invite)
            and isinstance(invite.guild, PartialInviteGuild)
            else ctx.guild
        )
        if not guild.banner:
            return await ctx.warn(f"**{guild}** doesn't have a banner present")

        embed = Embed(
            url=guild.banner,
            title=f"{guild}'s banner",
        )
        embed.set_image(url=guild.banner)

        return await ctx.send(embed=embed)

    @command(name="serversplash")
    async def server_splash(self, ctx: Context) -> Message:
        """sends the serversplash of the server"""
        splash = ctx.guild.splash
        if splash:
            embed = Embed(title=f"{ctx.guild.name}'s Server Splash")
            embed.set_image(url=splash)
            await ctx.send(embed=embed)
        else:
            await ctx.send("This server doesn't have a splash set.")

    @command(
        aliases=[
            "pfp",
            "avi",
            "av",
        ],
        usage="[member]",
        brief="@yurrion",
    )
    async def avatar(
        self,
        ctx: Context,
        *,
        user: Member | User = parameter(
            default=lambda ctx: ctx.author,
        ),
    ) -> Message:
        """
        View mentioned or current user's avatar.
        """

        embed = Embed(
            url=user.avatar or user.default_avatar,
            title="Your avatar" if user == ctx.author else f"{user.name}'s avatar",
        )
        embed.set_image(url=user.avatar or user.default_avatar)

        return await ctx.send(embed=embed)

    @command(
        aliases=[
            "spfp",
            "savi",
            "sav",
        ],
        usage="[member]",
        brief="@yurrion",
    )
    async def serveravatar(
        self,
        ctx: Context,
        *,
        member: Member = parameter(
            default=lambda ctx: ctx.author,
        ),
    ) -> Message:
        """
        View mentioned or current user's server avatar
        """

        member = member or ctx.author
        if not member.guild_avatar:
            return await ctx.warn(
                "You don't have a server avatar present"
                if member == ctx.author
                else f"**{member}** doesn't have a server avatar present"
            )

        embed = Embed(
            url=member.guild_avatar,
            title=(
                "Your server avatar"
                if member == ctx.author
                else f"{member.name}'s server avatar"
            ),
        )
        embed.set_image(url=member.guild_avatar)

        return await ctx.send(embed=embed)

    @command(aliases=["userbanner", "ub"], usage="[member]", brief="@yurrion")
    async def banner(
        self,
        ctx: Context,
        *,
        user: Member | User = parameter(
            default=lambda ctx: ctx.author,
        ),
    ) -> Message:
        """
        View a user's banner if one is present.
        """

        if not isinstance(user, User):
            user = await self.bot.fetch_user(user.id)

        if not user.banner:
            return await ctx.warn(
                "You don't have a banner present"
                if user == ctx.author
                else f"**{user}** doesn't have a banner present"
            )

        embed = Embed(
            url=user.banner,
            title="Your banner" if user == ctx.author else f"{user.name}'s banner",
        )
        embed.set_image(url=user.banner)

        return await ctx.send(embed=embed)

    @command(aliases=["mc"])
    async def membercount(
        self,
        ctx: Context,
        *,
        guild: Optional[Guild],
    ) -> Message:
        """
        View the current detailed member count of a server.
        """

        guild = guild or ctx.guild
        embed = Embed()
        embed.set_author(
            name=guild,
            icon_url=guild.icon,
        )

        humans = list(list(filter(lambda member: not member.bot, guild.members)))
        bots = list(list(filter(lambda member: member.bot, guild.members)))

        embed.add_field(name="**Members**", value=f"{len(guild.members):,}")
        embed.add_field(name="**Humans**", value=f"{len(humans):,}")
        embed.add_field(name="**Bots**", value=f"{len(bots):,}")

        return await ctx.send(embed=embed)

    @command(aliases=["ii"], usage="<invite>", brief="discord.gg/zyn")
    async def inviteinfo(self, ctx: Context, *, invite: Invite) -> Message:
        """
        View information about a specific server's invite.
        """

        if not isinstance(invite.guild, PartialInviteGuild):
            return await ctx.warn("That invite is invalid or expired")

        guild = invite.guild
        embed = Embed(
            description=f"{format_dt(guild.created_at)} ({format_dt(guild.created_at, 'R')})"
        )
        embed.set_author(
            name=f"{guild.name} ({guild.id})",
            url=invite.url,
            icon_url=guild.icon,
        )
        if guild.icon:
            buffer = await guild.icon.read()
            embed.color = await dominant_color(buffer)

        embed.add_field(
            name="**Information**",
            value=(
                ">>> "
                f"**Inviter:** {invite.inviter or 'Vanity URL'}\n"
                f"**Channel:** {invite.channel or 'Unknown'}\n"
                f"**Created:** {format_dt(invite.created_at or guild.created_at)}"
            ),
        )
        embed.add_field(
            name="**Guild**",
            value=(
                ">>> "
                f"**Members:** {invite.approximate_member_count:,}\n"
                f"**Members Online:** {invite.approximate_presence_count:,}\n"
                f"**Verification Level:** {guild.verification_level.name.title()}"
            ),
        )

        return await ctx.send(embed=embed)

    @command(aliases=["sinfo", "si"], usage="[invite]", brief="discord.gg/zyn")
    async def serverinfo(
        self,
        ctx: Context,
        *,
        guild: Optional[Guild],
    ) -> Message:
        """
        View information about the current/given server.
        """

        guild = guild or ctx.guild
        embed = Embed(
            description=f"{format_dt(guild.created_at)} ({format_dt(guild.created_at, 'R')})"
        )
        embed.set_author(
            name=f"{guild.name} ({guild.id})",
            url=guild.vanity_url,
            icon_url=guild.icon,
        )
        if guild.icon:
            buffer = await guild.icon.read()
            embed.color = await dominant_color(buffer)

        embed.add_field(
            name="**Information**",
            value=(
                ">>> "
                f"**Owner:** {guild.owner or guild.owner_id}\n"
                f"**Verification:** {guild.verification_level.name.title()}\n"
                f"**Nitro Boosts:** {guild.premium_subscription_count:,} (`Level {guild.premium_tier}`)"
            ),
        )
        embed.add_field(
            name="**Statistics**",
            value=(
                ">>> "
                f"**Members:** {guild.member_count:,}\n"
                f"**Text Channels:** {len(guild.text_channels):,}\n"
                f"**Voice Channels:** {len(guild.voice_channels):,}\n"
            ),
        )

        if guild == ctx.guild and (roles := guild.roles[1:]):
            roles = list(reversed(roles))

            embed.add_field(
                name=f"**Roles ({len(roles)})**",
                value=(
                    ">>> "
                    + ", ".join(role.mention for role in roles[:5])
                    + (f" (+{len(roles) - 5})" if len(roles) > 5 else "")
                ),
                inline=False,
            )

        return await ctx.send(embed=embed)

    @group(
        aliases=["names", "nh"],
        invoke_without_command=True,
        usage="[member]",
        brief="@yurrion",
    )
    async def namehistory(
        self,
        ctx: Context,
        *,
        user: Member | User = parameter(
            default=lambda ctx: ctx.author,
        ),
    ) -> Message:
        """
        View a mentioned/current user's name history.
        """

        names = await self.bot.db.fetch(
            """
            SELECT *
            FROM name_history
            WHERE user_id = $1
            """
            + ("" if ctx.author.id in self.bot.owner_ids else "\nAND is_hidden = FALSE")
            + "\nORDER BY changed_at DESC",
            user.id,
        )
        if not names:
            return await ctx.warn(f"**{user}** doesn't have any name history")

        paginator = Paginator(
            ctx,
            entries=[
                f"**{record['username']}** ({format_dt(record['changed_at'], 'R')})"
                for record in names
            ],
            embed=Embed(title="Name History"),
        )
        return await paginator.start()

    @namehistory.command(
        name="clear",
        aliases=["clean", "reset"],
    )
    async def namehistory_clear(self, ctx: Context) -> Message:
        """
        Remove all your name history from being in our database.
        """

        await self.bot.db.execute(
            """
            UPDATE name_history
            SET is_hidden = TRUE
            WHERE user_id = $1
            """,
            ctx.author.id,
        )

        return await ctx.approve("Successfully cleared your name history")

    @command(aliases=["uinfo", "ui", "whois"], usage="[member]", brief="@yurrion")
    async def userinfo(
        self,
        ctx: Context,
        *,
        user: Member | User = parameter(
            default=lambda ctx: ctx.author,
        ),
    ) -> Message:
        """
        View information about a specific or current user.
        """

        embed = Embed(color=user.color if user.color != Colour.default() else ctx.color)
        title_suffix = " [BOT]" if user.bot else ""

        if user.id in self.bot.owner_ids:
            title_suffix += " [BOT DEVELOPER]"

        embed.title = f"{user}{title_suffix}"
        embed.description = ""
        embed.set_thumbnail(url=user.display_avatar)

        embed.add_field(
            name="**Created**",
            value=(
                format_dt(user.created_at, "D")
                + "\n> "
                + format_dt(user.created_at, "R")
            ),
        )

        if isinstance(user, Member) and user.joined_at:
            join_pos = sorted(
                user.guild.members,
                key=lambda member: member.joined_at or utcnow(),
            ).index(user)

            embed.add_field(
                name=f"**Joined ({ordinal(join_pos + 1)})**",
                value=(
                    format_dt(user.joined_at, "D")
                    + "\n> "
                    + format_dt(user.joined_at, "R")
                ),
            )

            if user.premium_since:
                embed.add_field(
                    name="**Boosted**",
                    value=(
                        format_dt(user.premium_since, "D")
                        + "\n> "
                        + format_dt(user.premium_since, "R")
                    ),
                )

            if roles := user.roles[1:]:
                embed.add_field(
                    name="**Roles**",
                    value=", ".join(role.mention for role in list(reversed(roles))[:5])
                    + (f" (+{len(roles) - 5})" if len(roles) > 5 else ""),
                    inline=False,
                )

            if (voice := user.voice) and voice.channel:
                members = len(voice.channel.members) - 1
                phrase = "Streaming inside" if voice.self_stream else "Inside"
                embed.description += f"🎙 {phrase} {voice.channel.mention} " + (
                    f"with {plural(members):other}" if members else "by themselves"
                )

            for activity_type, activities in groupby(
                user.activities,
                key=lambda activity: activity.type,
            ):
                activities = list(activities)
                if isinstance(activities[0], Spotify):
                    activity = activities[0]
                    embed.description += f"\n🎵 Listening to [**{activity.title}**]({activity.track_url}) by **{activity.artists[0]}**"

                elif isinstance(activities[0], Streaming):
                    embed.description += "\n🎥 Streaming " + human_join(
                        [
                            f"[**{activity.name}**]({activity.url})"
                            for activity in activities
                            if isinstance(activity, Streaming)
                        ],
                        final="and",
                    )

                elif activity_type == ActivityType.playing:
                    embed.description += "\n🎮 Playing " + human_join(
                        [f"**{activity.name}**" for activity in activities],
                        final="and",
                    )

                elif activity_type == ActivityType.watching:
                    embed.description += "\n📺 Watching " + human_join(
                        [f"**{activity.name}**" for activity in activities],
                        final="and",
                    )

                elif activity_type == ActivityType.competing:
                    embed.description += "\n🏆 Competing in " + human_join(
                        [f"**{activity.name}**" for activity in activities],
                        final="and",
                    )

        if not user.bot:
            badges: List[str] = []
            if user.id == ctx.guild.owner_id:
                badges.append(EMOJIS.BADGES.SERVER_OWNER)

            if isinstance(user, User) and user.banner:
                badges.extend([EMOJIS.BADGES.NITRO, EMOJIS.BADGES.BOOST])

            elif user.display_avatar.is_animated():
                badges.append(EMOJIS.BADGES.NITRO)

            if EMOJIS.BADGES.BOOST not in badges:
                for guild in user.mutual_guilds:
                    member = guild.get_member(user.id)
                    if not member:
                        continue

                    if member.premium_since:
                        if EMOJIS.BADGES.NITRO not in badges:
                            badges.append(EMOJIS.BADGES.NITRO)

                        badges.append(EMOJIS.BADGES.BOOST)
                        break

            for flag in user.public_flags:
                if flag[1] and (badge := getattr(EMOJIS.BADGES, flag[0].upper(), None)):
                    badges.append(badge)

            embed.title += " ".join(badges)
        return await ctx.send(embed=embed)

    @command()
    async def roles(self, ctx: Context) -> Message:
        """
        View the server roles.
        """

        roles = reversed(ctx.guild.roles[1:])
        if not roles:
            return await ctx.warn(f"**{ctx.guild}** doesn't have any roles")

        paginator = Paginator(
            ctx,
            entries=[f"{role.mention} (`{role.id}`)" for role in roles],
            embed=Embed(title=f"Roles in {ctx.guild}"),
        )
        return await paginator.start()

    @command(usage="<role>", brief="Server Admin")
    async def inrole(self, ctx: Context, *, role: Role) -> Message:
        """
        View members which have a role.
        """

        members = role.members
        if not members:
            return await ctx.warn(f"{role.mention} doesn't have any members")

        paginator = Paginator(
            ctx,
            entries=[f"{member.mention} (`{member.id}`)" for member in members],
            embed=Embed(title=f"Members with {role}"),
        )
        return await paginator.start()

    @group(invoke_without_command=True)
    async def boosters(self, ctx: Context) -> Message:
        """
        View server boosters.
        """

        members = list(
            filter(
                lambda member: member.premium_since is not None,
                ctx.guild.members,
            )
        )
        if not members:
            return await ctx.warn("No members are currently boosting")

        paginator = Paginator(
            ctx,
            entries=[
                f"{member.mention} - boosted {format_dt(member.premium_since or utcnow(), 'R')}"
                for member in sorted(
                    members,
                    key=lambda member: member.premium_since or utcnow(),
                    reverse=True,
                )
            ],
            embed=Embed(title="Boosters"),
        )
        return await paginator.start()

    @boosters.command(name="lost")
    async def boosters_lost(self, ctx: Context) -> Message:
        """
        View all lost boosters.
        """

        users = [
            f"{user.mention} stopped {format_dt(record['ended_at'], 'R')} (lasted {short_timespan(record['lasted_for'])})"
            for record in await self.bot.db.fetch(
                """
                SELECT *
                FROM boosters_lost
                WHERE guild_id = $1
                ORDER BY ended_at DESC
                """,
                ctx.guild.id,
            )
            if (user := self.bot.get_user(record["user_id"]))
        ]
        if not users:
            return await ctx.warn("No boosters have been lost")

        paginator = Paginator(
            ctx,
            entries=users,
            embed=Embed(title="Boosters Lost"),
        )
        return await paginator.start()

    @command()
    async def bots(self, ctx: Context) -> Message:
        """
        View all bots in the server.
        """

        members = list(
            filter(
                lambda member: member.bot,
                ctx.guild.members,
            )
        )
        if not members:
            return await ctx.warn(f"**{ctx.guild}** doesn't have any bots")

        paginator = Paginator(
            ctx,
            entries=[
                f"{member.mention} (`{member.id}`)"
                for member in sorted(
                    members,
                    key=lambda member: member.joined_at or utcnow(),
                    reverse=True,
                )
            ],
            embed=Embed(title=f"Bots in {ctx.guild}"),
        )
        return await paginator.start()

    @command(description="manage guild")
    @has_permissions(manage_guild=True)
    async def invites(self, ctx: Context) -> Message:
        """
        View all the server invites as well as information such as author and expire date.
        """

        invites = await ctx.guild.invites()
        if not invites:
            return await ctx.warn("No invites are currently present")

        paginator = Paginator(
            ctx,
            entries=[
                f"[{invite.code}]({invite.url}) by {invite.inviter.mention if invite.inviter else '**Unknown**'} expires {format_dt(invite.expires_at, 'R') if invite.expires_at else '**Never**'}"
                for invite in sorted(
                    invites,
                    key=lambda invite: invite.created_at or utcnow(),
                    reverse=True,
                )
            ],
            embed=Embed(title=f"Invites in {ctx.guild}"),
        )
        return await paginator.start()

    @command(aliases=["emotes"])
    async def emojis(self, ctx: Context) -> Message:
        """
        View all server emojis with names, id and emoji link.
        """

        emojis = ctx.guild.emojis
        if not emojis:
            return await ctx.warn(f"**{ctx.guild}** doesn't have any emojis")

        paginator = Paginator(
            ctx,
            entries=[f"{emoji} ([`{emoji.id}`]({emoji.url}))" for emoji in emojis],
            embed=Embed(title=f"Emojis in {ctx.guild}"),
        )
        return await paginator.start()

    @command()
    async def stickers(self, ctx: Context) -> Message:
        """
        View all server stickers with names, id and sticker link.
        """

        stickers = ctx.guild.stickers
        if not stickers:
            return await ctx.warn(f"**{ctx.guild}** doesn't have any stickers")

        paginator = Paginator(
            ctx,
            entries=[
                f"[{sticker.name}]({sticker.url}) (`{sticker.id}`)"
                for sticker in stickers
            ],
            embed=Embed(title=f"Stickers in {ctx.guild}"),
        )
        return await paginator.start()

    @command(aliases=["firstmsg"], usage="[channel]", brief="#general")
    async def firstmessage(self, ctx: Context) -> Message:
        """
        View the first message sent in current or specific channel.
        """

        message = [
            message async for message in ctx.channel.history(limit=1, oldest_first=True)
        ][0]
        return await ctx.neutral(
            f"Jump to the [`first message`]({message.jump_url}) sent by **{message.author}**"
        )

    @command(name="youngest", aliases=["young"])
    async def youngest(self, ctx: Context) -> Message:
        """
        View the youngest member to join discord in the server.
        """
        youngest = max(ctx.guild.members, key=lambda member: member.created_at)

        embed = Embed(title=f"**{youngest.name}**")
        embed.set_author(name=youngest.display_name, icon_url=youngest.avatar)
        embed.add_field(
            name="> Joined",
            value=format_dt(youngest.joined_at, style="R"),
            inline=False,
        )
        embed.add_field(
            name="> Created",
            value=format_dt(youngest.created_at, style="R"),
            inline=False,
        )
        embed.set_thumbnail(url=youngest.avatar)

        await ctx.send(embed=embed)

    @command(name="oldest", aliases=["old"])
    async def oldest(self, ctx: Context) -> Message:
        """
        View the oldest member to join discord in the server
        """
        oldest = min(ctx.guild.members, key=lambda member: member.created_at)

        embed = Embed(title=f"**{oldest.name}**")
        embed.set_author(name=oldest.display_name, icon_url=oldest.avatar)
        embed.add_field(
            name="> Joined", value=format_dt(oldest.joined_at, style="R"), inline=False
        )
        embed.add_field(
            name="> Created",
            value=format_dt(oldest.created_at, style="R"),
            inline=False,
        )
        embed.set_thumbnail(url=oldest.avatar)

        await ctx.send(embed=embed)
