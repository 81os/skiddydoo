PIPED_API: str = "pipedapi.adminforge.de"
WARP: str = "socks5://localhost:7483"


class DISCORD:
    """
    Discord authentication tokens and IDs.
    """

    TOKEN: str = (
        "MTI1NjU2MTc2NDIxNzI1ODA2Nw.GM7wWK._y8tOXzi8EHl8NPv9uGrg0J8yP8Hlj_FQv4yKQ"
    )
    PUBLIC_KEY: str = ""
    CLIENT_ID: str = ""
    CLIENT_SECRET: str = ""
    REDIRECT_URI: str = ""


class CLIENT:
    """
    Client settings for the bot.
    """

    PREFIX: str = ","
    DESCRIPTION: str | None = None
    OWNER_IDS: list[int] = [744806691396124673, 915350867438338058]  # yurrion # rico
    SUPPORT_SERVER: str = "https://discord.gg/qmuCXBCSpF"

    class COLORS:
        APPROVE: int = 0x48DB01
        NEUTRAL: int = 0x7291DF
        WARN: int = 0xFF3735


class LAVALINK:
    """
    Lavalink configuration
    """

    HOST: str = "127.0.0.1"
    PORT: int | None = None
    PASSWORD: str | None = "whatguyisnt"


class NETWORK:
    """
    Network configuration
    """

    HOST: str | None = None
    PORT: int | None = None


class DATABASE:
    DSN: str = "postgresql://postgres:A8dvF3h0K7qLnZ@localhost:5432/zyn"


class REDIS:
    DB: int = 0
    HOST: str = "localhost"
    PORT: int = 6377
    PASS: str = "X2z(Yv8?Rq3#BpK5"


class AUTHORIZATION:
    """
    AUTHORIZATION configuration
    """

    class SPOTIFY:
        CLIENT_ID: str = "908846bb106d4190b4cdf5ceb3d1e0e5"
        CLIENT_SECRET: str = "d08df8638ee44bdcbfe6057a5e7ffd78"

    class TWITCH:
        CLIENT_ID: str = "30guvrlrw4lvf3knqsbin99asxdg4t"
        CLIENT_SECRET: str = "pxfuxxo2mn5qebq5xrl8g31ryh91gz"

    class REDDIT:
        CLIENT_ID: str = "gM_QdMnswc2geCIvlbTkdQ"
        CLIENT_SECRET: str = "sMnPrsejKe5btrGPULuYrVOjMpAXkA"

    WEATHER: str = "0c5b47ed5774413c90b155456223004"
    FNBR: str = "20490584-82aa-4ac3-8831-73d411d7c3d2"
    LASTFM: list[str] = [
        "bc84a74e4b3cf9eb040fbeaab4071df5",
        "4210d59afeeb6c350442d7141747704c",
    ]
    GEMINI: str = "AIzaSyCjgGH83OyUblhY4JHMQFJ5j3UVH5ztkaA"
    WOLFRAM: str = "W95RJG-RRUXURP6XY"


class EMOJIS:
    class CONFIG:
        WARN: str = "<:warn:1256881957304926253>"
        APPROVE: str = "<:check:1256805627884339281>"
        DENY: str = "<:deny:1256805698663354428>"

    class BADGES:
        HYPESQUAD_BRILLIANCE: str = "<:hypesquad_brilliance:1256806729593786539>"
        BOOST: str = "<:boost:1256805619550130299>"
        STAFF: str = "<:staff:1256881930549334117>"
        VERIFIED_BOT_DEVELOPER: str = "<:verified_bot_developer:1256881948127920169>"
        SERVER_OWNER: str = "<:server_owner:1256881902376321094>"
        HYPESQUAD_BRAVERY: str = "<:hypesquad_bravery:1256806728310194247>"
        PARTNER: str = "<:partner:1256881626395443261>"
        HYPESQUAD_BALANCE: str = "<:hypesquad_balance:1256806726469025833>"
        EARLY_SUPPORTER: str = "<:early_supporter:1256805631399170130>"
        HYPESQUAD: str = "<:hypesquad:1256806372859838586>"
        BUG_HUNTER_LEVEL_2: str = "<:bug_hunter_level_2:1256805622360571935>"
        CERTIFIED_MODERATOR: str = "<:certified_moderator:1256805624268980244>"
        NITRO: str = "<:nitro:1256881625392746576>"
        BUG_HUNTER: str = "<:bug_hunter:1256805620754153522>"
        ACTIVE_DEVELOPER: str = "<:active_developer:1256805617889443940>"

    class PAGINATOR:
        NEXT: str = "<:next:1256806723176366102>"
        NAVIGATE: str = "<:navigate:1256806722383908935>"
        PREVIOUS: str = "<:previous:1256881628718829600>"
        CANCEL: str = "<:cancel:1256805623224467567>"

    class AUDIO:
        SKIP: str = "<:skip:1256881903588479017>"
        RESUME: str = "<:resume:1256881900199612457>"
        REPEAT: str = "<:repeat:1256881898341400607>"
        PREVIOUS: str = "<:previous_44:1256881629817733151>"
        PAUSE: str = "<:pause:1256881627401814048>"
        QUEUE: str = "<:queue:1256881630887411793>"
        REPEAT_TRACK: str = "<:repeat_track:1256881899154964500>"

    class VOICEMASTER:
        REJECT: str = "<:zynKick:1256806221906968576>"
        DELETE: str = "<:reject:1256881624365273178>"
        PLUS: str = "<:zynPlus:1256806316253384747>"
        MINUS: str = "<:zynMinus:1256806223542489148>"
        LOCK: str = "<:zynLock:1256806222737313853>"
        UNLOCK: str = "<:zynUnlock:1256806377360457871>"
        GHOST: str = "<:zynGhost:1256806176721469511>"
        UNGHOST: str = "<:zynUnghost:1256806376894632016>"
        INFO: str = "<:zynInfo:1256806220677779572>"
        CLAIM: str = "<:zynClaim:1256806179137519616>"
