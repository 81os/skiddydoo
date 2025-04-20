import json
import uuid
import base64 
import asyncpg 
import asyncio
import datetime
import tls_client
from pydantic import BaseModel
from fastapi import HTTPException
from typing import Literal, List, Optional, Any

class Record(asyncpg.Record): 
    def __getattr__(self, name: str): 
        return self[name]

class Threshold:
    def __init__(self):
        self.payload = {}

    def __repr__(self) -> str: 
        return str(self.payload)
    
    def __str__(self) -> str:
        return self.__repr__()
    
    async def do_expiration(self, key: str) -> None:
        await asyncio.sleep(60)
        self.remove(key)
    
    async def set(self, key: str):
        if not self.get(key): 
            self.payload[key] = [datetime.datetime.now()]
        else: 
            self.payload[key].append(datetime.datetime.now())

        asyncio.ensure_future(self.do_expiration(key))

    def get(self, key: str) -> int: 
        if cache := self.payload.get(key): 
            return len(cache)
        else: 
            return 0
    
    def remove(self, key: str):
        if self.get(key): 
            self.payload.get(key).pop()

class Cache:
    def __init__(self):
        self.payload = {}

    def __repr__(self) -> str:
        return str(self.payload)

    def __str__(self) -> str:
        return self.__repr__()

    async def do_expiration(self, key: str, expiration: int) -> None:
        await asyncio.sleep(expiration)
        self.payload.pop(key)

    def get(self, key: str) -> Any:
        return self.payload.get(key)

    async def set(self, key: str, object: Any, expiration: Optional[int] = None) -> Any:
        self.payload[key] = object

        if expiration:
            asyncio.ensure_future(self.do_expiration(key, expiration))

        return object

    def remove(self, key: str) -> None:
        return self.delete(key)

    def delete(self, key: str) -> None:
        if self.get(key):
            del self.payload[key]

        return None

class Worker: 
    def __init__(self): 
        self.tls_session = tls_client.Session(
            client_identifier="chrome_119",
            random_tls_extension_order=True
        )

    @property
    def properties(self) -> str: 
        payload = {
            "os": "Windows",
            "browser": "Discord Client",
            "release_channel": "stable",
            "client_version": "1.0.9024",
            "os_version": "10.0.19045",
            "os_arch":"x64",
            "app_arch":"ia32",
            "system_locale": "en",
            "browser_user_agent": "Mozilla/5.0 (Windows NT 10.0; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) discord/1.0.9024 Chrome/108.0.5359.215 Electron/22.3.26 Safari/537.36",
            "browser_version": "22.3.26",
            "client_build_number": 247929,
            "native_build_number": 40010,
            "client_event_source": None,
            "design_id": 0,
        }

        return base64.b64encode(json.dumps(payload).encode()).decode()
    
    def get_cookies(self) -> str:
        req = self.tls_session.get("https://discord.com")
        if req.status_code == 200: 
            return "; ".join([f"{cookie.name}={cookie.value}" for cookie in req.cookies]) + "; locale=en-US"
        
        return "__dcfduid=4e0a8d504a4411eeb88f7f88fbb5d20a; __sdcfduid=4e0a8d514a4411eeb88f7f88fbb5d20ac488cd4896dae6574aaa7fbfb35f5b22b405bbd931fdcb72c21f85b263f61400; __cfruid=f6965e2d30c244553ff3d4203a1bfdabfcf351bd-1699536665; _cfuvid=rNaPQ7x_qcBwEhO_jNgXapOMoUIV2N8FA_8lzPV89oM-1699536665234-0-604800000; locale=en-US" 

    def get_headers(self, token: str) -> dict:
        return {
            "Accept": "*/*",
            "Accept-language": "en",
            "Authorization": token,
            "Cookie": self.get_cookies(),
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) discord/1.0.9024 Chrome/108.0.5359.215 Electron/22.3.26 Safari/537.36",
            "X-Discord-Locale": "en-US",
            'X-Debug-Options': 'bugReporterEnabled',
            "X-Super-Properties": self.properties
        }
    
    def check_token(self, token: str) -> bool: 
        req = self.tls_session.get(
            "https://discord.com/api/v9/users/@me", 
            headers=self.get_headers(token)
        )

        return req.status_code == 200
    
    def join(self, token: str, invite: str): 
        if not self.check_token(token): 
            raise HTTPException(
                status_code=401, 
                detail="Bad token was provided"
            )
        
        payload = {
            "session_id": uuid.uuid4().hex
        }

        r = self.tls_session.post(
            f"https://canary.discord.com/api/v9/invites/{invite}",
            headers=self.get_headers(token),
            json=payload
        )

        return r.json()
    
    def fetch_user(self, user_id: int, token: str, guild_id: Optional[int] = None):
        params = {"guild_id": guild_id} if guild_id else None 

        r = self.tls_session.get(
            f"https://discord.com/api/v9/users/{user_id}/profile", 
            headers=self.get_headers(token),
            params=params
        )
        
        if r.status_code == 200:
            data = r.json()
            payload = {
                "username": data['user']['username'],
                "global_name": data['user']['global_name'],
                "user_id": data['user']['id'],
            }
    
            if guild_id: 
                payload['pronouns'] = data['guild_member_profile']['pronouns'] if data['guild_member_profile']['pronouns'] != '' else data['user_profile']['pronouns']
                payload['bio'] = data['guild_member']['bio'] if data['guild_member']['bio'] != '' else data['user']['bio']
                
                av = next(
                    (e for e in [data['guild_member']['avatar'], data['user']['avatar']] if e),
                    None
                )
    
                if not av:
                    payload['avatar'] = None
                else:
                    payload['avatar'] = f"https://cdn.discordapp.com/guilds/{guild_id}/users/{user_id}/avatars/{av}.{'gif' if 'a_' in av else 'png'}?size=1024" if av == data['guild_member']['avatar'] else f"https://cdn.discordapp.com/avatars/{user_id}/{av}.{'gif' if 'a_' in av else 'png'}?size=1024"
    
                banner = next(
                    (e for e in [data['guild_member']['banner'], data['user']['banner']] if e),
                    None
                )
    
                if not banner: 
                    payload['banner'] = None 
                else: 
                    payload['banner'] = f"https://cdn.discordapp.com/guilds/{guild_id}/users/{user_id}/banners/{banner}.{'gif' if 'a_' in banner else 'png'}?size=512" if banner == data['guild_member']['banner'] else f"https://cdn.discordapp.com/banners/{payload['user_id']}/{banner}.{'gif' if 'a_' in banner else 'png'}?size=512"
            else: 
                payload['pronouns'] = data['user_profile']['pronouns']
                payload['bio'] = data['user']['bio']
    
                if av := data['user'].get('avatar'):
                    payload['avatar'] = f"https://cdn.discordapp.com/avatars/{user_id}/{av}.{'gif' if 'a_' in av else 'png'}?size=1024"
                else:
                    payload['avatar'] = None 
    
                if banner := data['user'].get('banner'):
                    payload['banner'] = f"https://cdn.discordapp.com/banners/{user_id}/{banner}.{'gif' if 'a_' in banner else 'png'}"
                else: 
                    payload['banner'] = None 
    
            return payload 

class APIForm(BaseModel): 
    user_id: int 
    role: Literal['master', 'bot_developer', 'premium', 'pro', 'basic']

class APIKey(BaseModel):
    key: str 
    user_id: int 
    role: Literal['master', 'bot_developer', 'premium', 'pro', 'basic']

    def __str__(self): 
        return self.key
    
class UwuModel(BaseModel): 
    message: str

class JoinerModel(BaseModel): 
    token: str 
    invite: str

class ShardsModel(BaseModel): 
    shard_id: int
    is_ready: bool
    server_count: int
    member_count: int
    uptime: str
    latency: float
    last_updated: str

class ShardsModelFull(BaseModel):
    shards: List[ShardsModel]

class DiscordUserProfile(BaseModel):
    token: str 

class DiscordUserProfileModel(BaseModel):
    username: str 
    global_name: str 
    user_id: int 
    pronouns: str 
    bio: str 
    avatar: Optional[str]
    banner: Optional[str]

class ShardInfo(BaseModel):
    shard_id: int
    is_ready: bool
    server_count: int
    member_count: int
    uptime: float
    latency: float
    last_updated: str

class DiscordAvatarPost(BaseModel):
    url: str 
    type: Literal['png', 'gif']
    userid: str 
    name: str

class IsNsfw(BaseModel):
    is_nsfw: bool

class ChatgptResponse(BaseModel):
    response: str

class SpotifySong(BaseModel): 
    artist: str 
    title: str 
    image: str 
    download_url: str

class SnapChatUserModel(BaseModel):
    status: Literal['success']
    display_name: str 
    username: str 
    snapcode: str
    bio: Optional[str]
    avatar: str 
    url: str

class SnapStory(BaseModel): 
    url: str 
    timestamp: int 
    mediatype: Literal['mp4', 'png']

class SnapChatStoryModel(BaseModel):
    stories: List[SnapStory]
    count: int

class TikTokModel(BaseModel):
    status: Literal['success']
    username: str 
    nickname: Optional[str]
    avatar: str 
    bio: str 
    verified: bool 
    private: bool
    url: str 
    followers: int
    following: int
    hearts: int 
    friends: int 
    videoCount: int 

class RobloxModel(BaseModel): 
    username: str 
    display_name: str 
    bio: str 
    id: str 
    created_at: int 
    banned: bool 
    avatar_url: str 
    url: str
    friends: int 
    followers: int 
    followings: int
    
class PfpModel(BaseModel):
    type: str 
    category: str 
    url: str

class ScreenshotModel(BaseModel): 
    website_url: str 
    screenshot_url: str

class TransparentModel(BaseModel):
    image_url: str

class LastFmAlbumPlays(BaseModel):
    album_name: str 
    artist_name: str 
    plays: int
    tracks: int 
    url: str 
    listeners: int

class LastFmTrack(BaseModel):
    name: str 
    artist: str 
    image: Optional[str]
    album: str 
    url: str

class LastFmRecent(BaseModel):
    tracks: List[LastFmTrack]

class InstagramUser(BaseModel):
    username: str 
    full_name: str 
    bio: str 
    profile_pic: str 
    pronouns: List[str]
    highlights: int 
    posts: int 
    followers: int 
    following: int
    id: int
    url: str

class InstagramStory(BaseModel):
    expiring_at: int 
    taken_at: int 
    type: Literal['video', 'image']
    url: str

class InstagramStories(BaseModel):
    user: InstagramUser 
    stories: List[InstagramStory]

class OauthSetupForm(BaseModel): 
    bot_id: int 
    client_secret: str 
    bot_token: str 

class URLModel(BaseModel):
    url: str

class CaptchaResponse(BaseModel): 
    image_url: str 
    response: str
