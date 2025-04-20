from discord import ButtonStyle, Interaction, TextStyle
from discord.ui import Button, View, TextInput, Modal, button
from main import Context
from tools.parser import Script


class EmbedModal(Modal):
    def __init__(self, title: str, script: Script, field: str):
        super().__init__(title=title)
        self.script = script
        self.field = field

        self.text_input = TextInput(
            label=f"Enter {field}",
            style=TextStyle.paragraph,
            placeholder=f"Type your {field} here...",
            required=True,
        )
        self.add_item(self.text_input)

    async def on_submit(self, interaction: Interaction):
        value = self.text_input.value
        self.script.template += f"{{{self.field}: {value}}}"
        self.script.compile()
        await interaction.response.edit_message(embed=self.script.embed)


class EmbedBuilding(View):
    def __init__(self, ctx: Context):
        self.ctx = ctx
        self.script = Script("")
        super().__init__(timeout=None)

    async def interaction_check(self, interaction: Interaction) -> bool:
        if interaction.user.id != self.ctx.author.id:
            await interaction.response.send_message(
                "You are **not** the author of this embed", ephemeral=True
            )
            return False
        return True

    @button(label="Content", style=ButtonStyle.primary)
    async def content_embed(self, interaction: Interaction, button: Button):
        await interaction.response.send_modal(
            EmbedModal("Content", self.script, "content")
        )

    @button(label="Author", style=ButtonStyle.primary)
    async def author_embed(self, interaction: Interaction, button: Button):
        await interaction.response.send_modal(
            EmbedModal("Author Info", self.script, "author")
        )

    @button(label="Title", style=ButtonStyle.primary)
    async def title_embed(self, interaction: Interaction, button: Button):
        await interaction.response.send_modal(EmbedModal("Title", self.script, "title"))

    @button(label="Description", style=ButtonStyle.primary)
    async def description_embed(self, interaction: Interaction, button: Button):
        await interaction.response.send_modal(
            EmbedModal("Description", self.script, "description")
        )

    @button(label="Footer", style=ButtonStyle.primary)
    async def footer_embed(self, interaction: Interaction, button: Button):
        await interaction.response.send_modal(
            EmbedModal("Footer Text", self.script, "footer")
        )

    @button(label="Image", style=ButtonStyle.primary)
    async def embed_images(self, interaction: Interaction, button: Button):
        await interaction.response.send_modal(
            EmbedModal("Image URL", self.script, "image")
        )

    @button(label="Thumbnail", style=ButtonStyle.primary)
    async def thumbnail_embed(self, interaction: Interaction, button: Button):
        await interaction.response.send_modal(
            EmbedModal("Thumbnail URL", self.script, "thumbnail")
        )

    @button(label="Save", style=ButtonStyle.green)
    async def save_embed(self, interaction: Interaction, button: Button):
        await interaction.response.edit_message(
            content=f"```{self.script.template}```", embed=None, view=None
        )
