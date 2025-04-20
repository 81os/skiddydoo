from tools import CompositeMetaClass

from .twitch import TwitchAlerts


class Alerts(
    TwitchAlerts,
    metaclass=CompositeMetaClass,
):
    """
    Join all extended alert cogs into one.
    """
