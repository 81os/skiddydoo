from .alias import Alias
from .boosterrole import BoosterRole
from .command import CommandManagement
from .disboard import Disboard
from .gallery import Gallery
from .logging import Logging
from .roles import Roles
from .sticky import Sticky
from .statistics import Statistics
from .system import System
from .trigger import Trigger
from .vanity import Vanity
from .webhook import Webhook
from .security import AntiNuke, AntiRaid
from .thread import Thread
from .timer import Timer
from .jail import Jail
from tools import CompositeMetaClass


class Extended(
    Alias,
    BoosterRole,
    CommandManagement,
    Disboard,
    Gallery,
    Jail,
    Logging,
    Roles,
    Sticky,
    Statistics,
    System,
    Trigger,
    Vanity,
    Webhook,
    AntiNuke,
    AntiRaid,
    Thread,
    Timer,
    metaclass=CompositeMetaClass,
):
    """
    Join all extended utility cogs into one.
    NOTE: These are sorted in alphabetical order.
    """
