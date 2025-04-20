from .reaction import Reaction
from .response import Response


class Trigger(Response, Reaction): ...


__all__ = ("Trigger",)
