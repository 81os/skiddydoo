import orjson
import aiohttp
import datetime
import tls_client

from models import Cache
from fastapi import HTTPException
from typing import Optional, Dict

from bs4 import BeautifulSoup

class Requests:
    async def post_request(
        self, url: str, headers: dict, params: Optional[dict] = None
    ):
        async with aiohttp.ClientSession(headers=headers) as cs:
            async with cs.post(url, params=params) as r:
                if r.status != 204:
                    return r.status, await r.json()
                else:
                    return r.status

    async def get_request(self, url: str, headers: dict, params: Optional[dict] = None):
        async with aiohttp.ClientSession(headers=headers) as cs:
            async with cs.get(url, params=params) as r:
                if r.status != 204:
                    return r.status, await r.json()
                else:
                    return r.status

    async def get_json(
        self, url: str, headers: Optional[dict] = None, params: Optional[dict] = None
    ):
        async with aiohttp.ClientSession(headers=headers) as cs:
            async with cs.get(url, params=params) as r:
                if r.status == 200:
                    return await r.json()
                else:
                    return None

    async def text(self, url: str, headers: Optional[dict] = None):
        async with aiohttp.ClientSession(headers=headers) as cs:
            async with cs.get(url) as r:
                if r.status == 200:
                    return await r.text()
                else:
                    return None

class Snap:
    def __init__(self):
        self.requests = Requests()
        self.headers = {
            "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 13_2_3 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/13.0.3 Mobile/15E148 Safari/604.1"
        }
    
    async def get_story(self, user: str):
        result = await self.requests.text(
            f"https://story.snapchat.com/add/{user}", headers=self.headers
        )
        soup = BeautifulSoup(result, "html.parser")
        data = soup.find("script", {"id": "__NEXT_DATA__"})
        story = orjson.loads(data.text)["props"]["pageProps"].get("story")
        if not story:
            raise HTTPException(
                status_code=404, detail="Account not found or story not found"
            )

        stories = []
        for lol in story["snapList"]:
            stories.append(
                {
                    "url": lol["snapUrls"]["mediaUrl"],
                    "timestamp": lol["timestampInSec"]["value"],
                    "mediatype": "png" if lol["snapMediaType"] == 0 else "mp4",
                }
            )

        return {"stories": stories, "count": len(stories)}

    async def get_user(self, username: str):
        result = await self.requests.text(
            f"https://story.snapchat.com/add/{username}", headers=self.headers
        )

        soup = BeautifulSoup(result, "html.parser")
        data = soup.find("script", id="__NEXT_DATA__")
        user = orjson.loads(data.text)["props"]["pageProps"].get("userProfile")

        if not user:
            raise HTTPException(status_code=404, detail="Account not found")

        if user["$case"] == "publicProfileInfo":
            user = user["publicProfileInfo"]
            display_name = user["title"]
            snapcode = user["snapcodeImageUrl"].replace("&type=SVG", "&type=PNG")
            bio = user["bio"]
            avatar = user["profilePictureUrl"]

        elif user["$case"] == "userInfo":
            user = user["userInfo"]
            display_name = user["displayName"]
            snapcode = user["snapcodeImageUrl"].replace("&type=SVG", "&type=PNG")
            avatar = user["bitmoji3d"]["avatarImage"]["fallbackUrl"]
            bio = None

        return {
            "status": "success",
            "display_name": display_name,
            "username": username,
            "snapcode": snapcode,
            "bio": bio,
            "avatar": avatar,
            "url": f"https://story.snapchat.com/add/{username}",
        }

class TikTok():
    def __init__(self):
        self.cache = Cache()
        self.requests = Requests()
        self.headers = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
            "Accept-Encoding": "gzip, deflate, utf-8",
            "Accept-Language": "en-US,en;q=0.9",
            "Cache-Control": "max-age=0",
            "Cookie": "_ttp=2PFDfhUFKlSOtRB27JI4p8QRY7y; ttwid=1%7C48rYTtcKZwCL5KJc73IOrioRyGsQdigZEqOjHzixy1E%7C1683549686%7C42acae242a08c38e7f4553d07fd5dc81eac4c7343e5f3a09fa47d4a1302de882; tiktok_webapp_theme=light; cookie-consent={%22ga%22:true%2C%22af%22:true%2C%22fbp%22:true%2C%22lip%22:true%2C%22bing%22:true%2C%22ttads%22:true%2C%22reddit%22:true%2C%22criteo%22:true%2C%22version%22:%22v9%22}; tt_chain_token=VzQXPjtTsE8goxvc3/3YqQ==; passport_csrf_token=8416a2e0da570a2c18c2ef31807fb635; passport_csrf_token_default=8416a2e0da570a2c18c2ef31807fb635; cmpl_token=AgQQAPPdF-RO0tRgRxPXuak5_jl02dGcf5h7YM_LBA; sid_guard=a61e5230bdd67b063dbfe3d12d045dc6%7C1684253778%7C15552000%7CSun%2C+12-Nov-2023+16%3A16%3A18+GMT; uid_tt=9e2544f6074fc21a71071c9da43d664901bf6115717056502ac415b3a21d552d; uid_tt_ss=9e2544f6074fc21a71071c9da43d664901bf6115717056502ac415b3a21d552d; sid_tt=a61e5230bdd67b063dbfe3d12d045dc6; sessionid=a61e5230bdd67b063dbfe3d12d045dc6; sessionid_ss=a61e5230bdd67b063dbfe3d12d045dc6; sid_ucp_v1=1.0.0-KGM2NzU0YzgwYjhiNDc2OGE3MzQxMTU0YzMwNDFmNGI1ZGZjMWUxZWMKIAiA4K38xbaqrwQQ0tiOowYYswsgDDDx4cyFBjgEQOoHEAMaBm1hbGl2YSIgYTYxZTUyMzBiZGQ2N2IwNjNkYmZlM2QxMmQwNDVkYzY; ssid_ucp_v1=1.0.0-KGM2NzU0YzgwYjhiNDc2OGE3MzQxMTU0YzMwNDFmNGI1ZGZjMWUxZWMKIAiA4K38xbaqrwQQ0tiOowYYswsgDDDx4cyFBjgEQOoHEAMaBm1hbGl2YSIgYTYxZTUyMzBiZGQ2N2IwNjNkYmZlM2QxMmQwNDVkYzY; store-idc=useast2a; store-country-code=ro; store-country-code-src=uid; tt-target-idc=useast2a; tt-target-idc-sign=CX8U_wPiKjHPvQczjTwASghoDyYBFG9QGXC9v31yV69O_uHyGbJFkzSol4g-XECEOU4CDfLUzAyA1o2p0Kvb6kpQNJp-PEh35DmlD-BcyRN1nJ9LHPml9v0lBTgiaGcnm8K02i5efytRvBYTO9OPU6gmKCvsM8l95Yaifjc-YpbAGNWt-NYqOaZ-1sMrDZzKNfyQEidYpK9bOds_1uMTImyIEdnP0pYWRHAsGL2DOe5rcJE8A0g6eem759tWHttPl3IwC_DGk1qyYcBszQYzIqp487nG3wn9cCFTpBdnItU7fyhgh4tZKPg0zFUVyhOBWiuIyr1_ijATKI2i6d-WjteFJrVrR-s3Kpaw_am7YBUbYBR9r2NJI4S94zIoaE2K4xKZ-iU9E10dtdycjmNfkt5QnvY8Wrrccdo1lKzPxLcwW1fdtJwb6b2DL9XNAcqaj2yM5G_PXe34ojhXUT9iFGYF-2Nfc_oTAUiWyHyq34B4tMFNM5n_C8_ujh_OIjyj; __tea_cache_tokens_1988={%22_type_%22:%22default%22%2C%22user_unique_id%22:%227230790793135605274%22%2C%22timestamp%22:1683549690785}; tt_csrf_token=IFpOeSJU-eWmdRZlLGrDx80QDGGiIOQ4WxBE; csrf_session_id=750806d8965c55630c8aafdc16a3e5fa; passport_fe_beating_status=false; odin_tt=c0d13f0bf27002d41e3eefe308a3499818bf51ccb8adbd72f1906dee1d6248dd01333862a56934810d82dc9f009e0045e7ef4260e35b6dcbb681eeb42f41ad56a2ae9a881dfc00ca6c0808f8a72c0829; ttwid=1%7C48rYTtcKZwCL5KJc73IOrioRyGsQdigZEqOjHzixy1E%7C1686139868%7Cd0c439c0b8593e4de47e6435544170bd41205e294a6b2becd02ec61acb8b56e7; s_v_web_id=verify_lilo54ni_Kx9WQPTc_st8d_4xS4_8wOQ_xrhhqHbxXpX6; msToken=pfUsotGs1GMXFTcbLiGtv--HEJ0yQ1UCjq8bX2DxH3SNR3_DtHAiL51QHvYgfLnuv8pRUWGUZApodU3mJ8AlpeyArnStmm_uQO3segFAgYA-LQ6iDK_Tbq9w59Qx0FM2DJZTw1mPsHvxKEjJjEg=; msToken=pfUsotGs1GMXFTcbLiGtv--HEJ0yQ1UCjq8bX2DxH3SNR3_DtHAiL51QHvYgfLnuv8pRUWGUZApodU3mJ8AlpeyArnStmm_uQO3segFAgYA-LQ6iDK_Tbq9w59Qx0FM2DJZTw1mPsHvxKEjJjEg=",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "same-origin",
            "Sec-Fetch-User": "?1",
            "Upgrade-Insecure-Requests": "1",
            "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 13_2_3 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/13.0.3 Mobile/15E148 Safari/604.1",
        }

    async def scrape(self, username: str):
        if cache := self.cache.get(f"tiktok-{username}"):
            return cache

        html = await self.requests.text(
            f"https://tiktok.com/@{username}", headers=self.headers
        )
        soup = BeautifulSoup(html, "html.parser")
        page = soup.find(
            "script", id="__UNIVERSAL_DATA_FOR_REHYDRATION__", type="application/json"
        )
        result = orjson.loads(page.get_text())

        if not result.get("__DEFAULT_SCOPE__"):
            raise HTTPException(status_code=404, detail="TikTok Account not found")

        result = result["__DEFAULT_SCOPE__"]["webapp.user-detail"]["userInfo"]
        user = result["user"]
        nickname = user["nickname"]
        avatar = user["avatarMedium"]
        bio = user["signature"]
        verified = user["verified"]
        private = user["privateAccount"]
        stats = result["stats"]
        followers = stats["followerCount"]
        following = stats["followingCount"]
        hearts = stats["heart"]
        videos = stats["videoCount"]
        friends = stats["friendCount"]

        payload = {
            "status": "success",
            "username": f"@{username}",
            "display": nickname,
            "avatar": avatar,
            "bio": bio,
            "verified": verified,
            "private": private,
            "url": f"https://tiktok.com/@{username}",
            "followers": followers,
            "following": following,
            "hearts": hearts,
            "friends": friends,
            "videoCount": videos,
        }

        await self.cache.set(f"tiktok-{username}", payload, 3600)
        return payload

class Roblox():
    def __init__(self):
        self.cache = Cache()
        self.requests = Requests()
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Linux; Android 6.0; Nexus 5 Build/MRA58N) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Mobile Safari/537.36"
        }

    async def get_user_id(self, username: str) -> Optional[str]:
        """
        Get the roblox user id by username
        """

        params = {"username": username}

        async with aiohttp.ClientSession(headers=self.headers) as cs:
            async with cs.get(
                "https://www.roblox.com/users/profile", params=params
            ) as r:
                if r.ok:
                    return str(r.url)[len("https://www.roblox.com/users/") :].split(
                        "/"
                    )[0]

                return None

    async def get_user_stats(self, user_id: str) -> Dict[str, int]:
        payload = {}

        for statistic in ["friends", "followers", "followings"]:
            async with aiohttp.ClientSession(headers=self.headers) as cs:
                async with cs.get(
                    f"https://friends.roblox.com/v1/users/{user_id}/{statistic}/count"
                ) as r:
                    data = await r.json()
                    payload.update({statistic: data["count"]})

        return payload

    async def get_user_avatar(self, user_id: str):
        """
        Get the user's avatar
        """

        async with aiohttp.ClientSession(headers=self.headers) as cs:
            async with cs.get(f"https://www.roblox.com/users/{user_id}/profile") as r:
                html = await r.text()

        soup = BeautifulSoup(html, "html.parser")
        return soup.find("meta", property="og:image")["content"]

    async def get_user_profile(self, user_id: str) -> dict:
        """
        Get the user's profile by id
        """

        async with aiohttp.ClientSession(headers=self.headers) as cs:
            async with cs.get(f"https://users.roblox.com/v1/users/{user_id}") as r:
                return await r.json()

    async def scrape(self, username: str) -> dict:
        """
        Get details about a roblox profile by username
        """

        if cache := self.cache.get(f"roblox-{username.lower()}"):
            return cache

        if user_id := await self.get_user_id(username):
            profile_data = await self.get_user_profile(user_id)
            profile_stats = await self.get_user_stats(user_id)
            user_avatar = await self.get_user_avatar(user_id)

            payload = {
                "username": profile_data["name"],
                "display_name": profile_data["displayName"],
                "bio": profile_data["description"],
                "id": user_id,
                "created_at": datetime.datetime.strptime(
                    profile_data["created"].split(".")[0] + "Z", "%Y-%m-%dT%H:%M:%SZ"
                ).timestamp(),
                "banned": profile_data["isBanned"],
                "avatar_url": user_avatar,
                "url": f"https://www.roblox.com/users/{user_id}/profile",
            }
            payload.update(profile_stats)
            await self.cache.set(f"roblox-{username.lower()}", payload, 3600)
            return payload

        raise HTTPException(status_code=404, detail="User not found")

class Instagram():
    def __init__(self):
        self.cache = Cache()
        self.session = Requests()
        self.tls_session = tls_client.Session(
            client_identifier="chrome_119",
            random_tls_extension_order=True 
        )
        self.headers = None
    
    def get_headers(self, session_id: str) -> dict: 
        headers = {
            "User-Agent": 'Mozilla/5.0 (iPhone; CPU iPhone OS 12_3_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 Instagram 105.0.0.11.118 (iPhone11,8; iOS 12_3_1; en_US; en-US; scale=2.00; 828x1792; 165586599)',
        }

        req = self.tls_session.get("https://www.instagram.com", headers=headers)
        headers['Cookie'] = "; ".join([f"{cookie.name}={cookie.value}" for cookie in req.cookies]) + f"; sessionid={session_id}"
        self.headers = headers

    async def get_story(self, username: str):
        if cache := self.cache.get(f"instagram-story-{username}"):
            return cache 
        
        if not self.headers:
            self.get_headers("4188696743%3AHogQaUnmya14Sz%3A24%3AAYcc3RNfDmHisGTNxoJ7B5ppYvx_DguRBJXDOlHMxA")

        user = await self.get_user(username)
        user_id = user['id']

        params = {
            'reel_ids': user_id
        }   

        data = await self.session.get_json(
            "https://www.instagram.com/api/v1/feed/reels_media",
            headers=self.headers,
            params=params
        )

        if len(data['reels_media']) == 0: 
            await self.cache.set(
                f"instagram-story-{username}",
                404, 
                3600
            )
            return 404
        
        payload = {
            'user': user
        }

        stories = []

        for story in data['reels_media'][0]['items']:
            type = "video" if story.get("video_versions") else "image"

            if type == "video": 
                url = story['video_versions'][0]['url']
            else: 
                url = story['image_versions2']['candidates'][0]['url']

            stories.append(
                {
                    'expiring_at': story['expiring_at'],
                    'taken_at': story['taken_at'],
                    'type': type, 
                    'url': url
                }
            )
            
        payload.update({'stories': stories})
        await self.cache.set(
            f"instagram-story-{username}",
            payload,
            3600
        )
        return payload

    async def get_user(self, username: str):
        params = {
            "username": username
        }

        if cache := self.cache.get(f"instagram-{username}"):
            return cache 

        if not self.headers:
            self.get_headers("4188696743%3AHogQaUnmya14Sz%3A24%3AAYcc3RNfDmHisGTNxoJ7B5ppYvx_DguRBJXDOlHMxA")

        data = await self.session.get_json(
            "https://www.instagram.com/api/v1/users/web_profile_info",
            headers=self.headers, 
            params=params
        )
          
        if not data:
            await self.cache.set(
                f"instagram-{username}",
                404
            ) 
            return 404

        user = data['data']['user']

        payload = {
            "username": username, 
            "full_name": user['full_name'],
            "bio": user['biography'],
            "profile_pic": user['profile_pic_url_hd'].replace('\u0026', '&'),
            "pronouns": user['pronouns'],
            "highlights": user['highlight_reel_count'],
            "posts": user['edge_owner_to_timeline_media']['count'],
            "followers": user['edge_followed_by']['count'],
            "following": user['edge_follow']['count'],
            "id": user['id'],
            "url": f"https://instagram.com/{username}"
        } 

        await self.cache.set(
            f"instagram-{username}",
            payload,
            3600
        )

        return payload

class DiscordOauth():
    def __init__(
            self, 
            client_id: str, 
            client_secret: str,
            bot_token: str 
        ):
        self.api_endpoint = "https://discord.com/api/v10"
        self.client_id: client_id 
        self.client_secret = client_secret
        self.token = bot_token
    
    async def exchange_code(self, code: str) -> Optional[str]:
        data = {
            "grant_type": "authorization_code",
            "code": code, 
            "redirect_uri": "https://v1.pretend.best/callback", 
            "client_id": self.client_id,
            "client_secret": self.client_secret
        }

        headers = {
            "Content-Type": "application/x-www-form-urlencoded"
        }

        async with aiohttp.ClientSession(headers=headers) as cs: 
            async with cs.post(f"{self.api_endpoint}/oauth2/token", data=data) as r: 
                return (await r.json())['access_token'] if r.ok else None
    
    async def add_roles_for(self, user_id: str, guild_id: str): 
        pass

    async def get_user(self, access_token: str) -> Optional[dict]:
        headers = {
            "Authorization": f"Bearer {access_token}"
        }

        async with aiohttp.ClientSession(headers=headers) as cs: 
            async with cs.get(f"{self.api_endpoint}/users/@me") as r: 
                return await r.json() if r.ok else None
            
    async def get_user_guilds(self, access_token: str) -> Optional[dict]: 
        headers = {
            "Authorization": f"Bearer {access_token}"
        }

        async with aiohttp.ClientSession(headers=headers) as cs: 
            async with cs.get(f"{self.api_endpoint}/users/@me/guilds") as r:
                return await r.json() if r.ok else None

class Socials():
    def __init__(self):
        self.tiktok = TikTok()
        self.roblox = Roblox()
        self.snap = Snap()
        self.instagram = Instagram()