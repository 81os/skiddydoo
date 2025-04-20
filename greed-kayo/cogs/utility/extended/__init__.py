from tools import CompositeMetaClass

from .snipe import Snipe
from .crypto import Crypto
from .giveaway import Giveaway
from .fortnite import Fortnite
from .highlight import Highlight
from .leveling import Leveling


class Extended(
    Snipe,
    Crypto,
    Giveaway,
    Fortnite,
    Highlight,
    Leveling,
    metaclass=CompositeMetaClass,
):
    """
    Join all extended utility cogs into one.
    """
