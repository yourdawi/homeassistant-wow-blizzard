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

    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create aiohttp session."""
        if self._session is None:
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
    
    async def get_character_profile(self, realm: str, character_name: str) -> Dict[str, Any]:
        """Get character profile data."""
        realm_slug = self.realm_to_slug(realm)
        endpoint = f"/profile/wow/character/{realm_slug}/{character_name.lower()}"
        params = {"namespace": f"profile-{self.region}"}
        profile = await self._make_request(endpoint, params)
        
        if profile:
            _LOGGER.info(f"Got profile for {character_name}-{realm}: Level {profile.get('level', 'Unknown')}")
        else:
            _LOGGER.warning(f"No profile data for {character_name}-{realm}")
            
        return profile

    async def get_character_equipment(self, realm: str, character_name: str) -> Dict[str, Any]:
        """Get character equipment data."""
        realm_slug = self.realm_to_slug(realm)
        endpoint = f"/profile/wow/character/{realm_slug}/{character_name.lower()}/equipment"
        params = {"namespace": f"profile-{self.region}"}
        return await self._make_request(endpoint, params)

    async def get_character_achievements(self, realm: str, character_name: str) -> Dict[str, Any]:
        """Get character achievements data."""
        realm_slug = self.realm_to_slug(realm)
        endpoint = f"/profile/wow/character/{realm_slug}/{character_name.lower()}/achievements"
        params = {"namespace": f"profile-{self.region}"}
        return await self._make_request(endpoint, params)

    async def get_character_statistics(self, realm: str, character_name: str) -> Dict[str, Any]:
        """Get character statistics (DEPRECATED - kept for compatibility)."""
        _LOGGER.warning("Character statistics endpoint is deprecated")
        realm_slug = self.realm_to_slug(realm)
        return {}

    # === Realm/Server Methods ===
    
    async def get_realm_info(self, realm: str) -> Dict[str, Any]:
        """Get realm information."""
        realm_slug = self.realm_to_slug(realm)
        endpoint = f"/data/wow/realm/{realm_slug}"
        params = {"namespace": f"dynamic-{self.region}"}
        return await self._make_request(endpoint, params)

    async def get_all_realms(self) -> Dict[str, Any]:
        """Get all realms in region."""
        endpoint = "/data/wow/realm/index"
        params = {"namespace": f"dynamic-{self.region}"}
        return await self._make_request(endpoint, params)

    async def get_connected_realm(self, realm: str) -> Dict[str, Any]:
        """Get connected realm info (for server status)."""
        realm_slug = self.realm_to_slug(realm)
        realm_info = await self.get_realm_info(realm_slug)
        if not realm_info or "id" not in realm_info:
            return {}
        
        endpoint = f"/data/wow/connected-realm/{realm_info['id']}"
        params = {"namespace": f"dynamic-{self.region}"}
        return await self._make_request(endpoint, params)

    # === PvP Methods ===
    
    async def get_character_pvp_summary(self, realm: str, character_name: str) -> Dict[str, Any]:
        """Get character PvP summary."""
        realm_slug = self.realm_to_slug(realm)
        endpoint = f"/profile/wow/character/{realm_slug}/{character_name.lower()}/pvp-summary"
        params = {"namespace": f"profile-{self.region}"}
        return await self._make_request(endpoint, params)

    async def get_character_pvp_bracket(self, realm: str, character_name: str, bracket: str) -> Dict[str, Any]:
        """Get character PvP bracket statistics."""
        realm_slug = self.realm_to_slug(realm)
        endpoint = f"/profile/wow/character/{realm_slug}/{character_name.lower()}/pvp-bracket/{bracket}"
        params = {"namespace": f"profile-{self.region}"}
        return await self._make_request(endpoint, params)

    async def get_all_pvp_data(self, realm: str, character_name: str) -> Dict[str, Dict[str, Any]]:
        """Get all PvP data for character."""
        results = {}
        
        # Get PvP summary
        summary = await self.get_character_pvp_summary(realm, character_name)
        results["summary"] = summary
        
        # Get bracket data
        brackets = ["2v2", "3v3", "rbg"]
        for bracket in brackets:
            bracket_data = await self.get_character_pvp_bracket(realm, character_name, bracket)
            results[bracket] = bracket_data
            await asyncio.sleep(0.1)  # Rate limiting
        
        return results

    # === Raid Methods ===
    
    async def get_character_encounters_raids(self, realm: str, character_name: str) -> Dict[str, Any]:
        """Get character raid encounters."""
        realm_slug = self.realm_to_slug(realm)
        endpoint = f"/profile/wow/character/{realm_slug}/{character_name.lower()}/encounters/raids"
        params = {"namespace": f"profile-{self.region}"}
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
                # Nimm die höchste ID als aktuelle Season
                season_id = max(s.get("id", 0) for s in seasons)
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
            char_key = f"{realm}-{name}"
            
            try:
                profile = await self.get_character_profile(realm, name)
                equipment = await self.get_character_equipment(realm, name)
                achievements = await self.get_character_achievements(realm, name)
                
                results[char_key] = {
                    "profile": profile,
                    "equipment": equipment, 
                    "achievements": achievements,
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
                    "realm": realm,
                    "name": name,
                    "error": str(e)
                }
        
        return results

    async def close(self):
        """Close the session."""
        if self._session:
            await self._session.close()