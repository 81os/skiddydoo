import logging.handlers
import pathlib
import sys
from datetime import datetime
from logging import LogRecord
from logging.handlers import RotatingFileHandler
from os import name, system
from typing import Dict, List, Optional, Tuple, cast

import rich
from discord.utils import setup_logging
from pygments.styles.monokai import MonokaiStyle  # DEP-WARN
from pygments.token import (
    Comment,
    Error,
    Keyword,
    Name,
    Number,
    Operator,
    String,
    Token,
)
from rich._log_render import LogRender  # DEP-WARN
from rich.console import Console, group
from rich.highlighter import NullHighlighter
from rich.logging import RichHandler
from rich.style import Style
from rich.syntax import ANSISyntaxTheme, PygmentsSyntaxTheme  # DEP-WARN
from rich.text import Text
from rich.theme import Theme
from rich.traceback import PathHighlighter, Traceback  # DEP-WARN

TokenType = Tuple[str, ...]
MAX_OLD_LOGS = 8

SYNTAX_THEME = {
    Token: Style(),
    Comment: Style(color="bright_black"),
    Keyword: Style(color="cyan", bold=True),
    Keyword.Constant: Style(color="bright_magenta"),
    Keyword.Namespace: Style(color="bright_red"),
    Operator: Style(bold=True),
    Operator.Word: Style(color="cyan", bold=True),
    Name.Builtin: Style(bold=True),
    Name.Builtin.Pseudo: Style(color="bright_red"),
    Name.Exception: Style(bold=True),
    Name.Class: Style(color="bright_green"),
    Name.Function: Style(color="bright_green"),
    String: Style(color="yellow"),
    Number: Style(color="cyan"),
    Error: Style(bgcolor="bright_blue"),
}


class FixedMonokaiStyle(MonokaiStyle):
    styles = {**MonokaiStyle.styles, Token: "#f8f8f2"}


class zynTraceback(Traceback):
    # DEP-WARN
    @group()
    def _render_stack(self, stack):
        for obj in super()._render_stack.__wrapped__(self, stack):
            if obj != "":
                yield obj


class zynLogRender(LogRender):
    def __call__(
        self,
        console: Console,
        renderables: List[Text],
        log_time: Optional[datetime] = None,
        time_format: Optional[str] = None,
        level: str = "",
        path: Optional[str] = None,
        line_no: Optional[int] = None,
        link_path: Optional[str] = None,
        logger_name: Optional[str] = None,
    ):
        output = Text()
        if self.show_time:
            log_time = log_time or console.get_datetime()
            log_time_display = log_time.strftime(time_format or self.time_format)  # type: ignore
            if log_time_display == self._last_time:
                output.append(" " * (len(log_time_display) + 1))
            else:
                output.append(f"{log_time_display} ", style="log.time")
                self._last_time = log_time_display  # type: ignore
        if self.show_level:
            output.append(level)
            output.append(" " * (8 - len(level)))
        if logger_name:
            logger_name = logger_name.removeprefix("discord.")

            output.append(f"[{logger_name}] ", style="#BBAAEE")
            output.append(" " * (14 - len(logger_name)))

        output.append(*renderables)  # type: ignore
        if self.show_path and path:
            path_text = Text()
            path_text.append(
                path, style=f"link file://{link_path}" if link_path else ""
            )
            if line_no:
                path_text.append(f":{line_no}")
            output.append(path_text)
        return output


class zynRichHandler(RichHandler):
    """Adaptation of Rich's RichHandler to manually adjust the path to a logger name"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._log_render = zynLogRender(
            show_time=self._log_render.show_time,
            show_level=self._log_render.show_level,
            show_path=self._log_render.show_path,
            level_width=self._log_render.level_width,
        )

    def get_level_text(self, record: LogRecord) -> Text:
        """Get the level name from the record.

        Args:
            record (LogRecord): LogRecord instance.

        Returns:
            Text: A tuple of the style and level name.
        """
        level_text = super().get_level_text(record)
        level_text.stylize("bold")
        return level_text

    def emit(self, record: LogRecord) -> None:
        """Invoked by logging."""
        path = pathlib.Path(record.pathname).name
        level = cast(str, self.get_level_text(record))
        message = self.format(record)
        time_format = None if self.formatter is None else self.formatter.datefmt
        log_time = datetime.fromtimestamp(record.created)

        traceback = None
        if (
            self.rich_tracebacks
            and record.exc_info
            and record.exc_info != (None, None, None)
        ):
            exc_type, exc_value, exc_traceback = record.exc_info
            assert exc_type is not None
            assert exc_value is not None
            traceback = zynTraceback.from_exception(
                exc_type,
                exc_value,
                exc_traceback,
                width=self.tracebacks_width,
                extra_lines=self.tracebacks_extra_lines,
                theme=self.tracebacks_theme,
                word_wrap=self.tracebacks_word_wrap,
                show_locals=self.tracebacks_show_locals,
                locals_max_length=self.locals_max_length,
                locals_max_string=self.locals_max_string,
                indent_guides=False,
            )
            message = record.getMessage()

        use_markup = (
            getattr(record, "markup") if hasattr(record, "markup") else self.markup
        )
        message_text = Text.from_markup(message) if use_markup else Text(message)
        if self.highlighter:
            message_text = self.highlighter(message_text)
        if self.KEYWORDS:
            message_text.highlight_words(self.KEYWORDS, "logging.keyword")

        self.console.print(
            self._log_render(
                self.console,
                [message_text],
                log_time=log_time,
                time_format=time_format,
                level=level,
                path=path,
                line_no=record.lineno,
                link_path=record.pathname if self.enable_link_path else None,
                logger_name=record.name,
            ),
            soft_wrap=True,
        )
        if traceback:
            self.console.print(traceback)


def init_logging(level: int) -> None:
    system("cls" if name == "nt" else "clear")

    rich_console = rich.get_console()
    rich.reconfigure(tab_size=4)
    rich_console.push_theme(
        Theme(
            {
                "log.time": Style(dim=True),
                "logging.level.warning": Style(color="yellow", bold=True),
                "logging.level.critical": Style(
                    color="white", bgcolor="red", bold=True
                ),
                "logging.level.verbose": Style(color="magenta", italic=True, dim=True),
                "logging.level.trace": Style(color="white", italic=True, dim=True),
                "repr.number": Style(color="cyan"),
                "repr.url": Style(
                    underline=True, italic=True, bold=False, color="cyan"
                ),
            }
        )
    )
    rich_console.file = sys.stdout
    PathHighlighter.highlights = []
    rich_formatter = logging.Formatter("{message}", datefmt="(%X)", style="{")

    stdout_handler = zynRichHandler(
        rich_tracebacks=True,
        show_path=False,
        highlighter=NullHighlighter(),
        tracebacks_extra_lines=0,
        tracebacks_show_locals=False,
        tracebacks_theme=(
            PygmentsSyntaxTheme(FixedMonokaiStyle)
            if rich_console.color_system == "truecolor"
            else ANSISyntaxTheme(cast(Dict[TokenType, Style], SYNTAX_THEME))
        ),
    )

    setup_logging(
        handler=stdout_handler,
        formatter=rich_formatter,
        level=logging.INFO,
        root=True,
    )

    logging.captureWarnings(True)

    # We want to disable excessive logging
    for module in ("discord", "httpx", "pylast", "websockets.server"):
        logger = logging.getLogger(module)
        logger.setLevel(logging.WARNING)

    # logging.getLogger("discord.http").setLevel(logging.DEBUG)
    logging.getLogger("asyncio").setLevel(logging.CRITICAL)
    handler = RotatingFileHandler(
        "zyn.log",
        encoding="utf-8",
        mode="w",
        maxBytes=32 * 1024 * 1024,
        backupCount=3,
    )
    log = logging.getLogger("discord.http")
    log.addHandler(handler)
