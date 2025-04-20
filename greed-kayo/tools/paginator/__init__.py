from __future__ import annotations

import asyncio
from contextlib import suppress
from math import ceil
from typing import TYPE_CHECKING, List, Optional, Union, cast

from discord import ButtonStyle, Color, Embed, HTTPException, Interaction, Message
from discord.utils import as_chunks

from config import EMOJIS
from tools import Button, View

if TYPE_CHECKING:
    from tools.client import Context


class Paginator(View):
    entries: List[Union[str, Embed]]
    message: Message
    index: int

    def __init__(
        self,
        ctx: Context,
        *,
        entries: List[Union[str, dict, Embed]],
        embed: Optional[Embed] = None,
        per_page: int = 10,
        counter: bool = True,
    ):
        super().__init__(timeout=60)
        self.ctx = ctx
        self.entries = self.prepare_entries(entries, embed, per_page, counter)
        self.message = None  # type: ignore
        self.index = 0
        self.add_buttons()

    async def interaction_check(self, interaction: Interaction) -> bool:
        if interaction.user != self.ctx.author:
            embed = Embed(
                description="You cannot interact with this paginator!",
                color=Color.dark_embed(),
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return False
        return True

    async def on_timeout(self) -> None:
        if self.message:
            with suppress(HTTPException):
                await self.message.edit(view=None)
        await super().on_timeout()

    def add_buttons(self):
        buttons = [
            Button(
                custom_id="previous",
                style=ButtonStyle.secondary,
                emoji=EMOJIS.PAGINATOR.PREVIOUS or "⬅",
            ),
            Button(
                custom_id="navigation",
                style=ButtonStyle.primary,
                emoji=EMOJIS.PAGINATOR.NAVIGATE or "🔢",
            ),
            Button(
                custom_id="next",
                style=ButtonStyle.secondary,
                emoji=EMOJIS.PAGINATOR.NEXT or "➡",
            ),
            Button(
                custom_id="cancel",
                style=ButtonStyle.primary,
                emoji=EMOJIS.PAGINATOR.CANCEL or "⏹",
            ),
        ]
        for button in buttons:
            self.add_item(button)

    def prepare_entries(
        self,
        entries: List[Union[str, dict, Embed]],
        embed: Optional[Embed],
        per_page: int,
        counter: bool,
    ) -> List[Union[str, Embed]]:
        compiled: List[Union[str, Embed]] = []
        pages = ceil(len(entries) / per_page)

        if not embed:
            for index, entry in enumerate(entries):
                if counter:
                    entry = f"({index + 1}/{len(entries)}) {entry}"
                compiled.append(entry)
        elif not entries:
            compiled.append(embed)
        elif isinstance(entries[0], str):
            offset = 0
            for chunk in as_chunks(entries, per_page):
                entry = embed.copy()
                entry.color = entry.color or self.ctx.color
                entry.description = f"{entry.description or ''}\n\n"
                for value in chunk:
                    offset += 1
                    entry.description += (
                        f"`{offset}` {value}\n" if counter else f"{value}\n"
                    )
                if pages > 1:
                    footer = entry.footer
                    footer_text = f"Page {len(compiled) + 1} of {pages:,}"
                    if footer and footer.text:
                        entry.set_footer(
                            text=f"{footer.text} • {footer_text}",
                            icon_url=footer.icon_url,
                        )
                    else:
                        entry.set_footer(text=footer_text)
                compiled.append(entry)
        elif isinstance(entries[0], Embed):
            pages = len(entries)
            for index, entry in enumerate(entries):
                entry.color = entry.color or self.ctx.color
                if pages > 1:
                    footer = entry.footer
                    footer_text = f"Page {len(compiled) + 1} of {pages}"
                    if footer and footer.text:
                        entry.set_footer(
                            text=f"{footer.text} • {footer_text}",
                            icon_url=footer.icon_url,
                        )
                    else:
                        entry.set_footer(text=footer_text)
                compiled.append(entry)

        return compiled

    async def start(self) -> Message:
        if not self.entries:
            raise ValueError("No entries were provided")

        page = self.entries[self.index]
        if len(self.entries) == 1:
            self.message = (
                await self.ctx.send(content=page)
                if isinstance(page, str)
                else await self.ctx.send(embed=page)
            )
        else:
            self.message = (
                await self.ctx.send(content=page, view=self)
                if isinstance(page, str)
                else await self.ctx.send(embed=page, view=self)
            )

        return self.message

    async def callback(self, interaction: Interaction, button: Button):
        await interaction.response.defer()

        if button.custom_id == "previous":
            self.index = (self.index - 1) % len(self.entries)
        elif button.custom_id == "next":
            self.index = (self.index + 1) % len(self.entries)
        elif button.custom_id == "navigation":
            await self.disable_buttons()
            await self.message.edit(view=self)
            embed = Embed(
                title="Page Navigation",
                description="Reply with the page number to skip to",
            )
            prompt = await interaction.followup.send(
                embed=embed, ephemeral=True, wait=True
            )
            response: Optional[Message] = None

            try:
                response = await self.ctx.bot.wait_for(
                    "message",
                    timeout=60,
                    check=lambda m: m.author == interaction.user
                    and m.channel == interaction.channel
                    and m.content.isdigit()
                    and 1 <= int(m.content) <= len(self.entries),
                )
            except asyncio.TimeoutError:
                pass
            else:
                self.index = int(response.content) - 1
            finally:
                for child in self.children:
                    child.disabled = False  # type: ignore
                with suppress(HTTPException):
                    await prompt.delete()
                    if response:
                        await response.delete()
        elif button.custom_id == "cancel":
            with suppress(HTTPException):
                await self.message.delete()
                await self.ctx.message.delete()
            self.stop()
            return

        page = self.entries[self.index]
        with suppress(HTTPException):
            if isinstance(page, str):
                await self.message.edit(content=page, view=self)
            else:
                await self.message.edit(embed=page, view=self)
