"""WoW Blizzard API Client"""
import asyncio
import aiohttp
import logging
import base64
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List

from .const import API_URLS, TOKEN_URLS

_LOGGER = logging.getLogger(__name__)


class WoWBlizzardAPIClient:
    @staticmethod
    def realm_to_slug(realm: str) -> str:
        """Convert realm name to slug for Blizzard API."""
        if not realm or not isinstance(realm, str):
            return ""
        return realm.strip().lower().replace("'", "").replace(" ", "-").replace("ä", "a").replace("ö", "o").replace("ü", "u").replace("ß", "ss")
    """API client"""

    REGION_LOCALES = {
        "us": "en_US",
        "eu": "en_GB", 
        "kr": "ko_KR",
        "tw": "zh_TW",
        "cn": "zh_CN",
    }

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        region: str = "us",
        locale: Optional[str] = None,
        session: Optional[aiohttp.ClientSession] = None,
    ):
        """Initialize the API client."""
        self.client_id = client_id
        self.client_secret = client_secret
        self.region = region.lower()
        self.api_url = API_URLS.get(self.region)
        self.token_url = TOKEN_URLS.get(self.region)
        
        self.locale = locale or self.REGION_LOCALES.get(self.region, "en_US")
        
        self._session = session
        self._access_token = None
        self._token_expires = None
        self._request_count = 0
        self._last_request_reset = datetime.now()

    def get_namespace(self, base_type: str, game_version: str = "retail") -> str:
        """Get the correct namespace based on game version and region."""
        if game_version == "classic":
            return f"{base_type}-classic-{self.region}"
        elif game_version == "classic1x":
            return f"{base_type}-classic1x-{self.region}"
        elif game_version == "classicann":
            return f"{base_type}-classicann-{self.region}"
        return f"{base_type}-{self.region}"

    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create aiohttp session."""
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=30)
            self._session = aiohttp.ClientSession(timeout=timeout)
        return self._session

    async def _get_access_token(self) -> str:
        """Get access token using OAuth 2.0 (August 2025 version)."""
        if (
            self._access_token
            and self._token_expires
            and datetime.now() < self._token_expires
        ):
            return self._access_token

        session = await self._get_session()
        
        # OAuth 2.0 Client Credentials Grant (2025 Standard)
        credentials = base64.b64encode(f"{self.client_id}:{self.client_secret}".encode()).decode()
        
        headers = {
            "Authorization": f"Basic {credentials}",
            "Content-Type": "application/x-www-form-urlencoded",
        }
        
        data = {
            "grant_type": "client_credentials",
            "scope": "wow.profile",  # Required scope for character data
        }

        try:
            async with session.post(self.token_url, data=data, headers=headers) as response:
                if response.status == 200:
                    token_data = await response.json()
                    self._access_token = token_data["access_token"]
                    expires_in = token_data.get("expires_in", 3600)
                    self._token_expires = datetime.now() + timedelta(seconds=expires_in - 60)
                    _LOGGER.info("Successfully obtained access token")
                    return self._access_token
                else:
                    error_text = await response.text()
                    _LOGGER.error(f"Token request failed: {response.status} - {error_text}")
                    raise Exception(f"Failed to get access token: {response.status}")
        except Exception as e:
            _LOGGER.error(f"Error getting access token: {e}")
            raise
 
    async def _make_request(self, endpoint: str, params: Dict[str, Any] = None) -> Dict[str, Any]:
        """Make authenticated API request."""
        access_token = await self._get_access_token()
        session = await self._get_session()
        
        headers = {
            "Authorization": f"Bearer {access_token}",
            "User-Agent": "HomeAssistant-WoW-Integration/2025.8",
        }
        
        url = f"{self.api_url}{endpoint}"
        
        if params is None:
            params = {}
        if "locale" not in params:
            params["locale"] = self.locale
        
        try:
            async with session.get(url, headers=headers, params=params) as response:
                self._request_count += 1
                
                if response.status == 200:
                    data = await response.json()
                    _LOGGER.debug(f"API Success: {endpoint}")
                    return data
                elif response.status == 404:
                    _LOGGER.debug(f"Resource not found: {endpoint}")
                    return {}
                elif response.status == 403:
                    _LOGGER.warning(f"Access denied: {endpoint} - Check API permissions")
                    return {}
                elif response.status == 429:
                    _LOGGER.warning("Rate limited, waiting 60 seconds")
                    await asyncio.sleep(60)
                    return await self._make_request(endpoint, params)
                else:
                    error_text = await response.text()
                    _LOGGER.error(f"API Error {response.status}: {error_text}")
                    return {}
        except Exception as e:
            _LOGGER.error(f"Request failed for {endpoint}: {e}")
            return {}

    # === Character Profile Methods ===
    
    async def get_character_profile(self, realm: str, character_name: str, game_version: str = "retail") -> Dict[str, Any]:
        """Get character profile data."""
        realm_slug = self.realm_to_slug(realm)
        endpoint = f"/profile/wow/character/{realm_slug}/{character_name.lower()}"
        params = {"namespace": self.get_namespace("profile", game_version)}
        profile = await self._make_request(endpoint, params)
        
        if profile:
            _LOGGER.info(f"Got profile for {character_name}-{realm}: Level {profile.get('level', 'Unknown')}")
        else:
            _LOGGER.warning(f"No profile data for {character_name}-{realm}")
            
        return profile

    async def get_character_equipment(self, realm: str, character_name: str, game_version: str = "retail") -> Dict[str, Any]:
        """Get character equipment data."""
        realm_slug = self.realm_to_slug(realm)
        endpoint = f"/profile/wow/character/{realm_slug}/{character_name.lower()}/equipment"
        params = {"namespace": self.get_namespace("profile", game_version)}
        return await self._make_request(endpoint, params)

    async def get_character_achievements(self, realm: str, character_name: str, game_version: str = "retail") -> Dict[str, Any]:
        """Get character achievements data."""
        realm_slug = self.realm_to_slug(realm)
        endpoint = f"/profile/wow/character/{realm_slug}/{character_name.lower()}/achievements"
        params = {"namespace": self.get_namespace("profile", game_version)}
        return await self._make_request(endpoint, params)

    async def get_character_media(self, realm: str, character_name: str, game_version: str = "retail") -> Dict[str, Any]:
        """Get character media data (portrait renders)."""
        realm_slug = self.realm_to_slug(realm)
        endpoint = f"/profile/wow/character/{realm_slug}/{character_name.lower()}/character-media"
        params = {"namespace": self.get_namespace("profile", game_version)}
        return await self._make_request(endpoint, params)

    async def get_character_statistics(self, realm: str, character_name: str) -> Dict[str, Any]:
        """Get character statistics (DEPRECATED - kept for compatibility)."""
        _LOGGER.warning("Character statistics endpoint is deprecated")
        return {}

    # === Realm/Server Methods ===
    
    async def get_realm_info(self, realm: str, game_version: str = "retail") -> Dict[str, Any]:
        """Get realm information."""
        realm_slug = self.realm_to_slug(realm)
        endpoint = f"/data/wow/realm/{realm_slug}"
        params = {"namespace": self.get_namespace("dynamic", game_version)}
        return await self._make_request(endpoint, params)

    async def get_all_realms(self, game_version: str = "retail") -> Dict[str, Any]:
        """Get all realms in region."""
        endpoint = "/data/wow/realm/index"
        params = {"namespace": self.get_namespace("dynamic", game_version)}
        return await self._make_request(endpoint, params)

    async def get_connected_realm(self, realm: str, game_version: str = "retail") -> Dict[str, Any]:
        """Get connected realm info (for server status)."""
        realm_slug = self.realm_to_slug(realm)
        realm_info = await self.get_realm_info(realm_slug, game_version)
        if not realm_info or "id" not in realm_info:
            return {}
        
        # Extract connected realm ID from href, e.g. "https://us.api.blizzard.com/data/wow/connected-realm/11?namespace=dynamic-us"
        connected_realm_href = realm_info.get("connected_realm", {}).get("href", "")
        import re
        match = re.search(r"connected-realm/(\d+)", connected_realm_href)
        if match:
            connected_realm_id = int(match.group(1))
        else:
            connected_realm_id = realm_info["id"]
        
        endpoint = f"/data/wow/connected-realm/{connected_realm_id}"
        params = {"namespace": self.get_namespace("dynamic", game_version)}
        return await self._make_request(endpoint, params)

    # === PvP Methods ===
    
    async def get_character_pvp_summary(self, realm: str, character_name: str, game_version: str = "retail") -> Dict[str, Any]:
        """Get character PvP summary."""
        realm_slug = self.realm_to_slug(realm)
        endpoint = f"/profile/wow/character/{realm_slug}/{character_name.lower()}/pvp-summary"
        params = {"namespace": self.get_namespace("profile", game_version)}
        return await self._make_request(endpoint, params)

    async def get_character_pvp_bracket(self, realm: str, character_name: str, bracket: str, game_version: str = "retail") -> Dict[str, Any]:
        """Get character PvP bracket statistics."""
        realm_slug = self.realm_to_slug(realm)
        endpoint = f"/profile/wow/character/{realm_slug}/{character_name.lower()}/pvp-bracket/{bracket}"
        params = {"namespace": self.get_namespace("profile", game_version)}
        return await self._make_request(endpoint, params)

    async def get_all_pvp_data(self, realm: str, character_name: str, game_version: str = "retail") -> Dict[str, Dict[str, Any]]:
        """Get all PvP data for character."""
        results = {}
        
        # Get PvP summary
        summary = await self.get_character_pvp_summary(realm, character_name, game_version)
        results["summary"] = summary
        
        # Get bracket data
        brackets = ["2v2", "3v3", "rbg"]
        for bracket in brackets:
            bracket_data = await self.get_character_pvp_bracket(realm, character_name, bracket, game_version)
            results[bracket] = bracket_data
            await asyncio.sleep(0.1)  # Rate limiting
        
        return results

    # === Raid Methods ===
    
    async def get_character_encounters_raids(self, realm: str, character_name: str, game_version: str = "retail") -> Dict[str, Any]:
        """Get character raid encounters."""
        realm_slug = self.realm_to_slug(realm)
        endpoint = f"/profile/wow/character/{realm_slug}/{character_name.lower()}/encounters/raids"
        params = {"namespace": self.get_namespace("profile", game_version)}
        return await self._make_request(endpoint, params)

    # === Mythic+ Methods ===
    
    async def get_character_mythicplus_profile(self, realm: str, character_name: str) -> Dict[str, Any]:
        """Get character Mythic+ profile."""
        realm_slug = self.realm_to_slug(realm)
        endpoint = f"/profile/wow/character/{realm_slug}/{character_name.lower()}/mythic-keystone-profile"
        params = {"namespace": f"profile-{self.region}"}
        return await self._make_request(endpoint, params)

    async def get_character_mythicplus_season(self, realm: str, character_name: str, season_id: int = None) -> Dict[str, Any]:
        """Get character Mythic+ season data. Holt automatisch die aktuelle Season-ID aus dem Keystone-Profile."""
        if season_id is None:
            profile = await self.get_character_mythicplus_profile(realm, character_name)
            seasons = profile.get("seasons", [])
            if seasons:
                season_ids = [s.get("id") for s in seasons if isinstance(s, dict) and s.get("id") is not None]
                season_id = max(season_ids) if season_ids else 1
            else:
                # Fallback: Standard-Season-ID
                season_id = 1
        realm_slug = self.realm_to_slug(realm)
        endpoint = f"/profile/wow/character/{realm_slug}/{character_name.lower()}/mythic-keystone-profile/season/{season_id}"
        params = {"namespace": f"profile-{self.region}"}
        return await self._make_request(endpoint, params)

    # === Guild Methods ===
    
    async def get_guild_info(self, realm: str, guild_name: str) -> Dict[str, Any]:
        """Get guild information."""
        if not guild_name or not isinstance(guild_name, str):
            return {}
        realm_slug = self.realm_to_slug(realm)
        endpoint = f"/data/wow/guild/{realm_slug}/{guild_name.lower().replace(' ', '-')}"
        params = {"namespace": f"profile-{self.region}"}
        return await self._make_request(endpoint, params)

    # === Multi-character support ===
    
    async def get_multiple_character_data(self, characters: List[Dict[str, str]]) -> Dict[str, Dict[str, Any]]:
        """Get data for multiple characters."""
        results = {}
        
        for char in characters:
            realm = char["realm"]
            name = char["character_name"]  # Fixed key name
            game_version = char.get("game_version", "retail")
            char_key = f"{realm}-{name}"
            
            try:
                profile = await self.get_character_profile(realm, name, game_version=game_version)
                equipment = await self.get_character_equipment(realm, name, game_version=game_version)
                achievements = await self.get_character_achievements(realm, name, game_version=game_version)
                media = await self.get_character_media(realm, name, game_version=game_version)
                
                results[char_key] = {
                    "profile": profile,
                    "equipment": equipment, 
                    "achievements": achievements,
                    "media": media,
                    "realm": realm,
                    "name": name,
                }
                
                # Rate limiting between characters
                await asyncio.sleep(0.2)
                
            except Exception as e:
                _LOGGER.error(f"Error fetching data for {char_key}: {e}")
                results[char_key] = {
                    "profile": {},
                    "equipment": {},
                    "achievements": {},
                    "media": {},
                    "realm": realm,
                    "name": name,
                    "error": str(e)
                }
        
        return results

    # === Hall of Fame and expansions ===

    async def get_all_mythic_raids_graphql(self) -> Dict[str, Any]:
        """Get all mythic raids and expansions from the public GraphQL endpoint."""
        session = await self._get_session()
        url = "https://worldofwarcraft.blizzard.com/graphql"
        
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept-Language": self.locale.replace("_", "-"),
        }
        
        payload = {
            "operationName": "GetAllMythicRaids",
            "variables": {},
            "extensions": {
                "persistedQuery": {
                    "version": 1,
                    "sha256Hash": "453e0d84617011f2d0cb484f8ad5e4a2f7804adcea06c06c2b1ebb9d33b82c7c"
                }
            }
        }
        
        try:
            async with session.post(url, json=payload, headers=headers) as response:
                if response.status == 200:
                    return await response.json()
                else:
                    _LOGGER.error(f"GraphQL GetAllMythicRaids failed: {response.status}")
                    return {}
        except Exception as e:
            _LOGGER.error(f"Failed to fetch GraphQL GetAllMythicRaids: {e}")
            return {}

    async def get_hall_of_fame_graphql(self, raid_slug: str) -> Dict[str, Any]:
        """Get Hall of Fame data using the public World of Warcraft GraphQL endpoint."""
        session = await self._get_session()
        url = "https://worldofwarcraft.blizzard.com/graphql"
        
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept-Language": self.locale.replace("_", "-"),
        }
        
        payload = {
            "operationName": "GetMythicRaidLeaderboard",
            "variables": {
                "leaderboard": {
                    "zoneSlug": raid_slug
                }
            },
            "extensions": {
                "persistedQuery": {
                    "version": 1,
                    "sha256Hash": "f5e84323b0ee6f94b597ce503c186b07bc8c64303bc07476e058d3fd8a38ece1"
                }
            }
        }
        
        try:
            async with session.post(url, json=payload, headers=headers) as response:
                if response.status == 200:
                    return await response.json()
                else:
                    _LOGGER.error(f"GraphQL GetMythicRaidLeaderboard failed for {raid_slug}: {response.status}")
                    return {}
        except Exception as e:
            _LOGGER.error(f"Failed to fetch GraphQL GetMythicRaidLeaderboard for {raid_slug}: {e}")
            return {}

    async def get_hall_of_fame(self, raid_slug: str, faction: str) -> Dict[str, Any]:
        """Get Hall of Fame leaderboard data normalized from the public GraphQL endpoint."""
        graphql_data = await self.get_hall_of_fame_graphql(raid_slug)
        if not graphql_data or "data" not in graphql_data:
            return {}
            
        leaderboard_data = graphql_data["data"].get("MythicRaidLeaderboard")
        if not leaderboard_data:
            return {}
            
        leaderboards = leaderboard_data.get("leaderboards", [])
        if not leaderboards:
            return {}
            
        # Find the leaderboard matching the requested faction
        target_leaderboard = None
        if len(leaderboards) == 1:
            # Unified leaderboard (e.g. Horde containing top 200 global entries)
            target_leaderboard = leaderboards[0]
        else:
            # Split leaderboards (Alliance and Horde)
            for lb in leaderboards:
                if lb.get("factionEnum", "").lower() == faction.lower() or lb.get("factionName", "").lower() == faction.lower():
                    target_leaderboard = lb
                    break
                    
        if not target_leaderboard:
            return {}
            
        # Normalize entries to REST structure
        normalized_entries = []
        for entry in target_leaderboard.get("entries", []):
            guild = entry.get("guild", {})
            realm = guild.get("realm", {})
            
            # Parse realm slug from guild URL or fallback to slugification
            guild_url = guild.get("url") or ""
            parts = [p for p in guild_url.split("/") if p]
            if len(parts) >= 4 and parts[1] == "guild":
                realm_slug = parts[3]
            else:
                realm_slug = self.realm_to_slug(realm.get("name") or "")
                
            # Parse region slug
            region_val = entry.get("region")
            if isinstance(region_val, dict):
                region_slug = region_val.get("slug")
            else:
                region_slug = region_val or self.region
                
            normalized_entries.append({
                "rank": entry.get("rank"),
                "guild": {
                    "name": guild.get("name"),
                    "realm": {
                        "name": realm.get("name") or realm_slug.replace("-", " ").title(),
                        "slug": realm_slug,
                    }
                },
                "region": region_slug,
                "timestamp": entry.get("timestamp"),
            })
            
        return {"entries": normalized_entries}

    async def close(self):
        """Close the session."""
        if self._session and not self._session.closed:
            await self._session.close()
        self._session = None