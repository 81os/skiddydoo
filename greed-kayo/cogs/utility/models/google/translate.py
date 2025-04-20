from typing import List, TypedDict, Optional

from aiohttp import ClientSession
from discord.ext.commands import CommandError
from pydantic import BaseModel
from yarl import URL

from tools.client import Context

import config

LANGUAGES = {
    "af": "Afrikaans",
    "sq": "Albanian",
    "am": "Amharic",
    "ar": "Arabic",
    "hy": "Armenian",
    "az": "Azerbaijani",
    "eu": "Basque",
    "be": "Belarusian",
    "bn": "Bengali",
    "bs": "Bosnian",
    "bg": "Bulgarian",
    "ca": "Catalan",
    "ceb": "Cebuano",
    "ny": "Chichewa",
    "zh-cn": "Chinese (Simplified)",
    "zh-tw": "Chinese (Traditional)",
    "co": "Corsican",
    "hr": "Croatian",
    "cs": "Czech",
    "da": "Danish",
    "nl": "Dutch",
    "en": "English",
    "eo": "Esperanto",
    "et": "Estonian",
    "tl": "Filipino",
    "fi": "Finnish",
    "fr": "French",
    "fy": "Frisian",
    "gl": "Galician",
    "ka": "Georgian",
    "de": "German",
    "el": "Greek",
    "gu": "Gujarati",
    "ht": "Haitian Creole",
    "ha": "Hausa",
    "haw": "Hawaiian",
    "he": "Hebrew",
    "hi": "Hindi",
    "hmn": "Hmong",
    "hu": "Hungarian",
    "is": "Icelandic",
    "ig": "Igbo",
    "id": "Indonesian",
    "ga": "Irish",
    "it": "Italian",
    "ja": "Japanese",
    "jw": "Javanese",
    "kn": "Kannada",
    "kk": "Kazakh",
    "km": "Khmer",
    "ko": "Korean",
    "ku": "Kurdish (Kurmanji)",
    "ky": "Kyrgyz",
    "lo": "Lao",
    "la": "Latin",
    "lv": "Latvian",
    "lt": "Lithuanian",
    "lb": "Luxembourgish",
    "mk": "Macedonian",
    "mg": "Malagasy",
    "ms": "Malay",
    "ml": "Malayalam",
    "mt": "Maltese",
    "mi": "Maori",
    "mr": "Marathi",
    "mn": "Mongolian",
    "my": "Myanmar (Burmese)",
    "ne": "Nepali",
    "no": "Norwegian",
    "or": "Odia",
    "ps": "Pashto",
    "fa": "Persian",
    "pl": "Polish",
    "pt": "Portuguese",
    "pa": "Punjabi",
    "ro": "Romanian",
    "ru": "Russian",
    "sm": "Samoan",
    "gd": "Scots Gaelic",
    "sr": "Serbian",
    "st": "Sesotho",
    "sn": "Shona",
    "sd": "Sindhi",
    "si": "Sinhala",
    "sk": "Slovak",
    "sl": "Slovenian",
    "so": "Somali",
    "es": "Spanish",
    "su": "Sundanese",
    "sw": "Swahili",
    "sv": "Swedish",
    "tg": "Tajik",
    "ta": "Tamil",
    "te": "Telugu",
    "th": "Thai",
    "tr": "Turkish",
    "uk": "Ukrainian",
    "ur": "Urdu",
    "ug": "Uyghur",
    "uz": "Uzbek",
    "vi": "Vietnamese",
    "cy": "Welsh",
    "xh": "Xhosa",
    "yi": "Yiddish",
    "yo": "Yoruba",
    "zu": "Zulu",
}


class TranslatedSentence(TypedDict):
    trans: str
    orig: str


class GoogleTranslate(BaseModel):
    original: str
    translated: str
    source_language: str
    target_language: str

    @classmethod
    async def convert(cls, ctx: Context, argument: str) -> str:
        """Convert a language name or code to the corresponding language code."""
        if argument in LANGUAGES:
            return argument

        for code, language in LANGUAGES.items():
            if argument.lower() == language.lower():
                return code

        raise CommandError(f"Language `{argument}` not found!")

    @classmethod
    async def translate(
        cls,
        session: ClientSession,
        query: str,
        *,
        source: str = "auto",
        target: str = "en",
    ) -> "GoogleTranslate":
        """Translate text using Google Translate API."""
        url = URL.build(
            scheme="https",
            host="translate.google.com",
            path="/translate_a/single",
        )

        params = {
            "dj": "1",
            "dt": ["sp", "t", "ld", "bd"],
            "client": "dict-chrome-ex",
            "sl": source,
            "tl": target,
            "q": query,
        }

        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/104.0.0.0 Safari/537.36"
            )
        }

        async with session.get(url, params=params, headers=headers) as response:
            if not response.ok:
                raise CommandError(
                    "An error occurred while fetching the translation."
                    + f"\n> Please contact the developer in the [support server]({config.CLIENT.SUPPORT_SERVER})."
                )

            data = await response.json()
            sentences: List[TranslatedSentence] = data.get("sentences", [])
            if not sentences:
                raise RuntimeError(
                    "Google Translate returned no information, please try again later"
                )

            return cls(
                original="".join(sentence.get("orig", "") for sentence in sentences),
                translated="".join(sentence.get("trans", "") for sentence in sentences),
                source_language=LANGUAGES.get(data["src"], "Unknown"),
                target_language=LANGUAGES.get(target, "Unknown"),
            )
