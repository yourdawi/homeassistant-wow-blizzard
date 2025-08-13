"""WoW Blizzard API Client"""
import asyncio
import aiohttp
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List

from .const import API_URLS, TOKEN_URLS, CURRENT_SEASON_ID, CURRENT_PVP_SEASON_ID, PVP_BRACKETS

_LOGGER = logging.getLogger(__name__)


class WoWBlizzardAPIClient:
    """Client for the WoW Blizzard API with all features."""

    # Locale mapping based on region
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
        
        # Use provided locale or auto-detect from region
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
        """Get a valid access token."""
        if (
            self._access_token
            and self._token_expires
            and datetime.now() < self._token_expires
        ):
            return self._access_token

        session = await self._get_session()
        
        data = {
            "grant_type": "client_credentials",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
        }

        try:
            async with session.post(self.token_url, data=data) as response:
                if response.status == 200:
                    token_data = await response.json()
                    self._access_token = token_data["access_token"]
                    expires_in = token_data.get("expires_in", 3600)
                    self._token_expires = datetime.now() + timedelta(seconds=expires_in - 60)
                    return self._access_token
                else:
                    _LOGGER.error(f"Failed to get access token: {response.status}")
                    raise Exception(f"Failed to get access token: {response.status}")
        except Exception as e:
            _LOGGER.error(f"Error getting access token: {e}")
            raise

    async def _rate_limit_check(self):
        """Simple rate limiting."""
        now = datetime.now()
        if (now - self._last_request_reset).total_seconds() >= 3600:
            self._request_count = 0
            self._last_request_reset = now
        
        if self._request_count >= 35000:  # Leave some buffer
            _LOGGER.warning("Approaching rate limit, waiting...")
            await asyncio.sleep(60)

    async def _make_request(self, endpoint: str, params: Dict[str, Any] = None) -> Dict[str, Any]:
        """Make an authenticated request to the API with rate limiting."""
        await self._rate_limit_check()
        
        access_token = await self._get_access_token()
        session = await self._get_session()
        
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        }
        
        url = f"{self.api_url}{endpoint}"
        
        # Add locale to params if not already present
        if params is None:
            params = {}
        if "locale" not in params:
            params["locale"] = self.locale
        
        try:
            async with session.get(url, headers=headers, params=params) as response:
                self._request_count += 1
                
                if response.status == 200:
                    return await response.json()
                elif response.status == 404:
                    # Not found - return empty dict
                    _LOGGER.debug(f"Resource not found: {endpoint}")
                    return {}
                elif response.status == 429:
                    # Rate limited - wait and retry
                    _LOGGER.warning("Rate limited by API, waiting 30 seconds")
                    await asyncio.sleep(30)
                    return await self._make_request(endpoint, params)
                else:
                    _LOGGER.error(f"API request failed: {response.status}")
                    response_text = await response.text()
                    _LOGGER.debug(f"Response: {response_text}")
                    return {}
        except asyncio.TimeoutError:
            _LOGGER.warning("API request timeout")
            return {}
        except Exception as e:
            _LOGGER.error(f"Error making API request: {e}")
            return {}

    # === Basic Character Methods ===
    
    async def get_character_profile(self, realm: str, character_name: str) -> Dict[str, Any]:
        """Get character profile data."""
        endpoint = f"/profile/wow/character/{realm.lower()}/{character_name.lower()}"
        params = {"namespace": f"profile-{self.region}"}
        return await self._make_request(endpoint, params)

    async def get_character_equipment(self, realm: str, character_name: str) -> Dict[str, Any]:
        """Get character equipment data."""
        endpoint = f"/profile/wow/character/{realm.lower()}/{character_name.lower()}/equipment"
        params = {"namespace": f"profile-{self.region}"}
        return await self._make_request(endpoint, params)

    async def get_character_achievements(self, realm: str, character_name: str) -> Dict[str, Any]:
        """Get character achievements data."""
        endpoint = f"/profile/wow/character/{realm.lower()}/{character_name.lower()}/achievements"
        params = {"namespace": f"profile-{self.region}"}
        return await self._make_request(endpoint, params)

    async def get_character_statistics(self, realm: str, character_name: str) -> Dict[str, Any]:
        """Get character statistics data."""
        endpoint = f"/profile/wow/character/{realm.lower()}/{character_name.lower()}/statistics"
        params = {"namespace": f"profile-{self.region}"}
        return await self._make_request(endpoint, params)

    # === Server Status Methods ===
    
    async def get_realm_info(self, realm: str) -> Dict[str, Any]:
        """Get realm information and status."""
        endpoint = f"/data/wow/realm/{realm.lower()}"
        params = {"namespace": f"dynamic-{self.region}"}
        return await self._make_request(endpoint, params)

    async def get_all_realms(self) -> Dict[str, Any]:
        """Get all realms in region."""
        endpoint = "/data/wow/realm/index"
        params = {"namespace": f"dynamic-{self.region}"}
        return await self._make_request(endpoint, params)

    async def get_connected_realm(self, realm: str) -> Dict[str, Any]:
        """Get connected realm info."""
        # First get realm ID
        realm_info = await self.get_realm_info(realm)
        if not realm_info or "id" not in realm_info:
            return {}
        
        endpoint = f"/data/wow/connected-realm/{realm_info['id']}"
        params = {"namespace": f"dynamic-{self.region}"}
        return await self._make_request(endpoint, params)

    # === PvP Methods ===
    
    async def get_character_pvp_bracket(self, realm: str, character_name: str, pvp_bracket: str) -> Dict[str, Any]:
        """Get character PvP bracket statistics."""
        endpoint = f"/profile/wow/character/{realm.lower()}/{character_name.lower()}/pvp-bracket/{pvp_bracket}"
        params = {"namespace": f"profile-{self.region}"}
        return await self._make_request(endpoint, params)

    async def get_character_pvp_summary(self, realm: str, character_name: str) -> Dict[str, Any]:
        """Get character PvP summary."""
        endpoint = f"/profile/wow/character/{realm.lower()}/{character_name.lower()}/pvp-summary"
        params = {"namespace": f"profile-{self.region}"}
        return await self._make_request(endpoint, params)

    async def get_pvp_season(self, season_id: int = None) -> Dict[str, Any]:
        """Get PvP season information."""
        season = season_id or CURRENT_PVP_SEASON_ID
        endpoint = f"/data/wow/pvp-season/{season}"
        params = {"namespace": f"dynamic-{self.region}"}
        return await self._make_request(endpoint, params)

    async def get_all_pvp_data(self, realm: str, character_name: str) -> Dict[str, Dict[str, Any]]:
        """Get all PvP data for a character."""
        results = {}
        
        # Get PvP summary first
        results["summary"] = await self.get_character_pvp_summary(realm, character_name)
        
        # Get bracket data
        for bracket_key, bracket_name in PVP_BRACKETS.items():
            results[bracket_name] = await self.get_character_pvp_bracket(
                realm, character_name, bracket_key.lower().replace("_", "-")
            )
        
        return results

    # === Raid Progress Methods ===
    
    async def get_character_encounters(self, realm: str, character_name: str) -> Dict[str, Any]:
        """Get character encounter statistics."""
        endpoint = f"/profile/wow/character/{realm.lower()}/{character_name.lower()}/encounters"
        params = {"namespace": f"profile-{self.region}"}
        return await self._make_request(endpoint, params)

    async def get_character_encounters_raids(self, realm: str, character_name: str) -> Dict[str, Any]:
        """Get character raid encounters."""
        endpoint = f"/profile/wow/character/{realm.lower()}/{character_name.lower()}/encounters/raids"
        params = {"namespace": f"profile-{self.region}"}
        return await self._make_request(endpoint, params)

    async def get_encounter_info(self, encounter_id: int) -> Dict[str, Any]:
        """Get encounter information."""
        endpoint = f"/data/wow/encounter/{encounter_id}"
        params = {"namespace": f"static-{self.region}"}
        return await self._make_request(endpoint, params)

    async def get_raid_info(self, raid_slug: str) -> Dict[str, Any]:
        """Get raid information."""
        endpoint = f"/data/wow/raid/{raid_slug}"
        params = {"namespace": f"static-{self.region}"}
        return await self._make_request(endpoint, params)

    # === Mythic+ Methods ===
    
    async def get_character_mythicplus_profile(self, realm: str, character_name: str) -> Dict[str, Any]:
        """Get character Mythic+ profile."""
        endpoint = f"/profile/wow/character/{realm.lower()}/{character_name.lower()}/mythic-keystone-profile"
        params = {"namespace": f"profile-{self.region}"}
        return await self._make_request(endpoint, params)

    async def get_character_mythicplus_season(self, realm: str, character_name: str, season_id: int = None) -> Dict[str, Any]:
        """Get character Mythic+ season data."""
        season = season_id or CURRENT_SEASON_ID
        endpoint = f"/profile/wow/character/{realm.lower()}/{character_name.lower()}/mythic-keystone-profile/season/{season}"
        params = {"namespace": f"profile-{self.region}"}
        return await self._make_request(endpoint, params)

    async def get_mythicplus_season_info(self, season_id: int = None) -> Dict[str, Any]:
        """Get Mythic+ season information."""
        season = season_id or CURRENT_SEASON_ID
        endpoint = f"/data/wow/mythic-keystone/season/{season}"
        params = {"namespace": f"dynamic-{self.region}"}
        return await self._make_request(endpoint, params)

    async def get_dungeon_info(self, dungeon_id: int) -> Dict[str, Any]:
        """Get dungeon information."""
        endpoint = f"/data/wow/mythic-keystone/dungeon/{dungeon_id}"
        params = {"namespace": f"dynamic-{self.region}"}
        return await self._make_request(endpoint, params)

    # === Guild Methods ===
    
    async def get_guild_info(self, realm: str, guild_name: str) -> Dict[str, Any]:
        """Get guild information."""
        endpoint = f"/data/wow/guild/{realm.lower()}/{guild_name.lower().replace(' ', '-')}"
        params = {"namespace": f"profile-{self.region}"}
        return await self._make_request(endpoint, params)

    async def get_guild_roster(self, realm: str, guild_name: str) -> Dict[str, Any]:
        """Get guild roster."""
        endpoint = f"/data/wow/guild/{realm.lower()}/{guild_name.lower().replace(' ', '-')}/roster"
        params = {"namespace": f"profile-{self.region}"}
        return await self._make_request(endpoint, params)

    async def get_guild_activity(self, realm: str, guild_name: str) -> Dict[str, Any]:
        """Get guild activity."""
        endpoint = f"/data/wow/guild/{realm.lower()}/{guild_name.lower().replace(' ', '-')}/activity"
        params = {"namespace": f"profile-{self.region}"}
        return await self._make_request(endpoint, params)

    async def get_guild_achievements(self, realm: str, guild_name: str) -> Dict[str, Any]:
        """Get guild achievements."""
        endpoint = f"/data/wow/guild/{realm.lower()}/{guild_name.lower().replace(' ', '-')}/achievements"
        params = {"namespace": f"profile-{self.region}"}
        return await self._make_request(endpoint, params)

    # === Multiple Characters Support ===
    
    async def get_multiple_character_data(self, characters: List[Dict[str, str]]) -> Dict[str, Dict[str, Any]]:
        """Get data for multiple characters."""
        results = {}
        
        for char in characters:
            realm = char["realm"]
            name = char["name"]
            char_key = f"{realm}-{name}"
            
            # Get basic data for each character
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
            
            # Small delay to avoid rate limiting
            await asyncio.sleep(0.1)
        
        return results

    async def close(self):
        """Close the session."""
        if self._session:
            await self._session.close()