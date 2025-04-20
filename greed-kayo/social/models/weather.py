import os
from aiohttp import ClientSession
import discord
from discord.ext.commands import Converter, BadArgument
from pydantic import BaseModel
import datetime

from tools.client import Context
from main import zyn


class Weather(BaseModel):
    place: str
    country: str
    temp_c: float
    temp_f: float
    wind_mph: float
    wind_kph: float
    humidity: float
    condition: str
    condition_image: str
    time: datetime.datetime


class WeatherLocation(Converter):
    async def convert(self, ctx: Context, argument: str) -> Weather:
        url = "http://api.weatherapi.com/v1/current.json"
        params = {"key": "64581e6f1d7d49ae834142709230804", "q": argument}
        headers = {
            "User-Agent": f"zyn (DISCORD BOT/{zyn.version})",
            "Content-Type": "application/json",
        }
        try:
            async with ClientSession(headers=headers) as session:
                async with session.get(url, params=params) as response:
                    if response.status != 200:
                        raise BadArgument("The location provided is not valid.")

                    data = await response.json()
                    weather = Weather(
                        place=data["location"]["name"],
                        country=data["location"]["country"],
                        temp_c=data["current"]["temp_c"],
                        temp_f=data["current"]["temp_f"],
                        wind_mph=data["current"]["wind_mph"],
                        wind_kph=data["current"]["wind_kph"],
                        humidity=data["current"]["humidity"],
                        condition=data["current"]["condition"]["text"],
                        condition_image=f"http:{data['current']['condition']['icon']}",
                        time=datetime.datetime.fromtimestamp(
                            data["current"]["last_updated_epoch"]
                        ),
                    )
                    return weather
        except Exception as e:
            raise BadArgument(f"Error fetching weather data: {str(e)}")
