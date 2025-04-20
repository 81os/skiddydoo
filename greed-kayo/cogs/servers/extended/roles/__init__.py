from .auto import AutoRoles
from .reaction import ReactionRoles


class Roles(AutoRoles, ReactionRoles): ...


__all__ = ("Roles",)
