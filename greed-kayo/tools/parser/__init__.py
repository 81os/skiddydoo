import re
from contextlib import suppress
from typing import List, Literal, Optional, Tuple, TypedDict

from discord import Embed, Member, Message, TextChannel, Thread, VoiceChannel, Webhook
from discord.ui import Button, View
from pydantic import BaseModel

from tools.client import Context
from tools.parser.variables import TARGET, parse

NODE = re.compile(r"\{(?P<name>.*?):\s*(?P<value>.*?)\}", re.DOTALL)
IMAGE = re.compile(r"(?:http\:|https\:)?\/\/.*\.(?P<mime>png|jpg|jpeg|webp|gif)")


class Node(BaseModel):
    name: str
    value: str
    start: int
    end: int

    @property
    def coordinates(self) -> Tuple[int, int]:
        return (self.start, self.end)

    def __repr__(self) -> str:
        return f"<Node name={self.name!r} value={self.value!r}>"


class Components:
    data: "ScriptData"

    def __init__(self, data: "ScriptData") -> None:
        self.data = data

    def __call__(self, node: Node) -> "ScriptData":
        try:
            name = node.name.replace(". ", "_")
            func = getattr(self, name)
        except AttributeError:
            return self.data

        func(node.value)
        return self.data

    @property
    def embed(self) -> Embed:
        if not self.data["embed"]:
            self.data["embed"] = Embed()

        return self.data["embed"]

    @property
    def view(self) -> View:
        if not self.data["view"]:
            self.data["view"] = View()

        return self.data["view"]

    def content(self, value: str) -> None:
        self.data["content"] = value

    def message(self, value: str) -> None:
        self.data["content"] = value

    def color(self, value: str) -> None:
        with suppress(ValueError):
            self.embed.color = int(value.replace("#", ""), 16)

    def url(self, value: str) -> None:
        self.embed.url = value

    def title(self, value: str) -> None:
        self.embed.title = value

    def description(self, value: str) -> None:
        self.embed.description = value

    def thumbnail(self, value: str) -> Embed:
        if value in {"none", "null", "false", ""}:
            return self.embed

        return self.embed.set_thumbnail(url=value)

    def image(self, value: str) -> Embed:
        if value in {"none", "null", "false", ""}:
            return self.embed

        return self.embed.set_image(url=value)

    def field(self, value: str) -> Optional[Embed]:
        parts = value.split("&&", 3)
        if len(parts) < 2:
            return

        name, value = map(str.strip, parts[:2])
        return self.embed.add_field(
            name=name,
            value=value,
            inline=len(parts) >= 3,
        )

    def footer(self, value: str) -> Optional[Embed]:
        parts = value.split("&&", 2)
        if not parts:
            return

        text = parts[0]
        icon_url = parts[1] if len(parts) >= 2 else None

        return self.embed.set_footer(
            text=text,
            icon_url=icon_url,
        )

    def author(self, value: str) -> Optional[Embed]:
        parts = value.split("&&", 3)
        if not parts:
            return

        name = parts[0]
        icon_url = parts[1] if len(parts) >= 2 else None
        url = parts[2] if len(parts) >= 3 else None

        if icon_url and icon_url.strip() in ("none", "null", "false"):
            icon_url = None

        # elif icon_url and not IMAGE.match(icon_url):
        #     url, icon_url = icon_url, None

        return self.embed.set_author(
            name=name,
            icon_url=icon_url,
            url=url,
        )

    def button(self, value: str) -> None:
        parts = value.split("&&", 3)
        if len(parts) < 2:
            return

        label = parts[0].strip()
        url = parts[1].strip()
        emoji = parts[2].strip() if len(parts) == 3 else None

        if label.startswith("<"):  # custom emoji
            label, emoji = None, label

        with suppress(ValueError):
            self.view.add_item(
                Button(
                    label=label,
                    url=url,
                    emoji=emoji,
                )
            )


class Script:
    template: str
    fixed_template: str
    targets: List[TARGET | Tuple[TARGET, str]]
    nodes: List[Node]

    def __init__(
        self,
        template: str,
        targets: List[TARGET | Tuple[TARGET, str]] = [],
    ) -> None:
        self.fixed_template = ""
        self.nodes = []
        self.template = template
        self.targets = targets
        self.compile()

    def __repr__(self) -> str:
        return f"<Script template={self.template!r}>"

    def __str__(self) -> str:
        return self.template

    def __bool__(self) -> bool:
        return bool(self.content or self.embed)

    def compile(self) -> None:
        self.fixed_template = parse(self.template, self.targets)
        self.nodes = self.parse_nodes(self.fixed_template)

    def parse_nodes(self, template: str) -> List[Node]:
        return [
            Node(
                **match.groupdict(),
                start=match.start(),
                end=match.end(),
            )
            for match in NODE.finditer(template)
        ]

    @property
    def content(self) -> str:
        return self.data["content"] or ""

    @property
    def embed(self) -> Optional[Embed]:
        return self.data["embed"]

    @property
    def view(self) -> View:
        return self.data["view"]

    @property
    def data(self) -> "ScriptData":
        self.compile()
        data: ScriptData = {
            "content": "",
            "embed": None,
            "view": View(),
        }

        for node in self.nodes:
            data = Components(data)(node)

        if (
            not any(data.get(key) for key in ["content", "embed"])
            and not data["view"].children
        ):
            data["content"] = self.fixed_template

        return data

    async def send(
        self,
        channel: Context | VoiceChannel | TextChannel | Thread | Webhook | Member,
        **kwargs,
    ) -> Message:
        if isinstance(channel, Context):
            kwargs["no_reference"] = True

        if not self.embed:
            return await channel.send(content=self.content, view=self.view, **kwargs)  # type: ignore

        return await channel.send(
            content=self.content,
            embed=self.embed,
            view=self.view,  # type: ignore
            **kwargs,
        )

    async def edit(
        self,
        message: Message,
        **kwargs,
    ) -> Message:
        webhook: Optional[Webhook] = kwargs.pop("webhook", None)
        if webhook:
            return await webhook.edit_message(
                message.id,
                content=self.content,
                embed=self.embed,
                **kwargs,
            )

        if not self.embed:
            return await message.edit(content=self.content, view=self.view, **kwargs)

        return await message.edit(
            content=self.content,
            embed=self.embed,
            view=self.view,
            **kwargs,
        )

    @property
    def format(self) -> Literal["text", "embed"]:
        return "text" if not self.data["embed"] else "embed"

    @classmethod
    async def convert(cls, ctx: Context, argument: str) -> "Script":
        return cls(argument, [ctx.guild, ctx.author, ctx.channel])

    @classmethod
    def from_message(cls, message: Message) -> "Script":
        template: List[str] = []
        if message.system_content:
            template.append(f"{{content: {message.system_content}}}")

        if message.embeds:
            embed = message.embeds[0]
            template.extend(
                f"{{{item}: {getattr(value, 'url', value)}}}"
                for item, value in (
                    ("color", embed.color),
                    ("url", embed.url),
                    ("title", embed.title),
                    ("description", embed.description),
                    ("thumbnail", embed.thumbnail),
                    ("image", embed.image),
                )
                if value
            )

            for field in embed.fields:
                _field: List[str] = [field.name, field.value]  # type: ignore
                if field.inline:
                    _field.append("inline")

                template.append(f"{{field: {' && '.join(_field)}}}")

            if (footer := embed.footer) and footer.text:
                _footer: List[str] = [footer.text]
                if footer.icon_url:
                    _footer.append(footer.icon_url)

                template.append(f"{{footer: {' && '.join(_footer)}}}")

            if (author := embed.author) and author.name:
                _author: List[str] = [
                    author.name,
                    author.icon_url or "null",
                ]
                if author.url:
                    _author.append(author.url)

                template.append(f"{{author: {' && '.join(_author)}}}")

        return cls("\n".join(template))


class ScriptData(TypedDict):
    content: str
    embed: Optional[Embed]
    view: View
