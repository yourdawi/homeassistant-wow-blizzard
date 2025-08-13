"""API Client endpoints and data extraction."""
import asyncio
import aiohttp
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List

from .const import API_URLS, TOKEN_URLS, CURRENT_SEASON_ID, CURRENT_PVP_SEASON_ID, PVP_BRACKETS

_LOGGER = logging.getLogger(__name__)


class WoWBlizzardAPIClient:
    """API client with endpoints and data extraction."""

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
        """Get a valid access token with proper header authentication."""
        if (
            self._access_token
            and self._token_expires
            and datetime.now() < self._token_expires
        ):
            return self._access_token

        session = await self._get_session()
        
        # Proper OAuth2 client credentials flow
        data = {
            "grant_type": "client_credentials",
        }
        
        #Use Basic Auth Header
        import base64
        credentials = base64.b64encode(f"{self.client_id}:{self.client_secret}".encode()).decode()
        headers = {
            "Authorization": f"Basic {credentials}",
            "Content-Type": "application/x-www-form-urlencoded",
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
                    _LOGGER.error(f"Failed to get access token: {response.status} - {error_text}")
                    raise Exception(f"Failed to get access token: {response.status}")
        except Exception as e:
            _LOGGER.error(f"Error getting access token: {e}")
            raise

    async def _make_request(self, endpoint: str, params: Dict[str, Any] = None) -> Dict[str, Any]:
        """Make an authenticated request to the API."""
        access_token = await self._get_access_token()
        session = await self._get_session()
        
        # Use Bearer token in header
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
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
                    return await response.json()
                elif response.status == 404:
                    _LOGGER.debug(f"Resource not found: {endpoint}")
                    return {}
                elif response.status == 429:
                    _LOGGER.warning("Rate limited by API, waiting 60 seconds")
                    await asyncio.sleep(60)
                    return await self._make_request(endpoint, params)
                else:
                    error_text = await response.text()
                    _LOGGER.error(f"API request failed: {response.status} - {error_text}")
                    return {}
        except Exception as e:
            _LOGGER.error(f"Error making API request to {endpoint}: {e}")
            return {}

    # Character Profile
    
    async def get_character_profile(self, realm: str, character_name: str) -> Dict[str, Any]:
        """Get character profile data."""
        endpoint = f"/profile/wow/character/{realm.lower()}/{character_name.lower()}"
        params = {"namespace": f"profile-{self.region}"}
        return await self._make_request(endpoint, params)

    def extract_character_gold(self, profile_data: Dict[str, Any]) -> int:
        """Extract gold from character profile (in gold, not copper)."""
        if not profile_data:
            return 0
            
        # Gold is stored in copper, convert to gold
        copper_amount = profile_data.get("money", 0)
        gold_amount = copper_amount // 10000  # 10000 copper = 1 gold
        
        _LOGGER.debug(f"Character has {copper_amount} copper = {gold_amount} gold")
        return gold_amount
    
    async def get_realm_info(self, realm: str) -> Dict[str, Any]:
        """Get realm information (needed to get connected realm ID)."""
        endpoint = f"/data/wow/realm/{realm.lower()}"
        params = {"namespace": f"dynamic-{self.region}"}
        return await self._make_request(endpoint, params)

    async def get_connected_realm_status(self, realm: str) -> Dict[str, Any]:
        """Get ACTUAL server status from connected realm."""
        realm_info = await self.get_realm_info(realm)
        if not realm_info or "id" not in realm_info:
            _LOGGER.warning(f"Could not find realm info for {realm}")
            return {}
        
        # Get connected realm info
        endpoint = f"/data/wow/connected-realm/{realm_info['id']}"
        params = {"namespace": f"dynamic-{self.region}"}
        connected_realm = await self._make_request(endpoint, params)
        
        if not connected_realm:
            return {}
        
        # Extract status information
        status_info = {
            "status": "Unknown",
            "population": "Unknown", 
            "queue_time": 0,
            "has_queue": False,
        }
        
        if "status" in connected_realm:
            status_info["status"] = connected_realm["status"].get("name", "Unknown")
        
        # Population is often not available in API
        if "population" in connected_realm:
            status_info["population"] = connected_realm["population"].get("name", "Unknown")
        
        # Queue information (rarely available)
        if connected_realm.get("has_queue", False):
            status_info["has_queue"] = True
            status_info["queue_time"] = connected_realm.get("queue_time", 0)
        
        _LOGGER.debug(f"Realm {realm} status: {status_info}")
        return status_info

    async def get_all_realms(self) -> Dict[str, Any]:
        """Get all realms in region."""
        endpoint = "/data/wow/realm/index"
        params = {"namespace": f"dynamic-{self.region}"}
        return await self._make_request(endpoint, params)

    
    async def get_character_pvp_summary(self, realm: str, character_name: str) -> Dict[str, Any]:
        """Get character PvP summary."""
        endpoint = f"/profile/wow/character/{realm.lower()}/{character_name.lower()}/pvp-summary"
        params = {"namespace": f"profile-{self.region}"}
        return await self._make_request(endpoint, params)

    async def get_character_pvp_bracket(self, realm: str, character_name: str, bracket: str) -> Dict[str, Any]:
        """Get character PvP bracket data."""
        bracket_map = {
            "2v2": "2v2",
            "3v3": "3v3", 
            "rbg": "rbg",
        }
        
        api_bracket = bracket_map.get(bracket.lower(), bracket)
        endpoint = f"/profile/wow/character/{realm.lower()}/{character_name.lower()}/pvp-bracket/{api_bracket}"
        params = {"namespace": f"profile-{self.region}"}
        return await self._make_request(endpoint, params)

    def extract_pvp_data(self, pvp_summary: Dict[str, Any], bracket_data: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
        """Extract PvP data with proper null handling."""
        pvp_info = {
            "pvp_2v2_rating": 0,
            "pvp_3v3_rating": 0,
            "pvp_rbg_rating": 0,
            "pvp_honor_level": 0,
            "pvp_wins_season": 0,
        }
        
        # Honor level from summary
        if pvp_summary and "honor_level" in pvp_summary:
            pvp_info["pvp_honor_level"] = pvp_summary["honor_level"]
        
        # Ratings from bracket data
        for bracket, data in bracket_data.items():
            if not data or "rating" not in data:
                continue
                
            rating = data["rating"]
            wins = data.get("season_match_statistics", {}).get("won", 0)
            pvp_info["pvp_wins_season"] += wins
            
            if bracket == "2v2":
                pvp_info["pvp_2v2_rating"] = rating
            elif bracket == "3v3":
                pvp_info["pvp_3v3_rating"] = rating
            elif bracket == "rbg":
                pvp_info["pvp_rbg_rating"] = rating
        
        _LOGGER.debug(f"Extracted PvP data: {pvp_info}")
        return pvp_info

    async def get_all_pvp_data(self, realm: str, character_name: str) -> Dict[str, Any]:
        """Get all PvP data for a character."""
        try:
            # Get PvP summary
            pvp_summary = await self.get_character_pvp_summary(realm, character_name)
            
            # Get bracket data
            bracket_data = {}
            for bracket in ["2v2", "3v3", "rbg"]:
                bracket_data[bracket] = await self.get_character_pvp_bracket(realm, character_name, bracket)
                await asyncio.sleep(0.1)  # Rate limiting
            
            return self.extract_pvp_data(pvp_summary, bracket_data)
            
        except Exception as e:
            _LOGGER.warning(f"Error getting PvP data for {character_name}-{realm}: {e}")
            return {
                "pvp_2v2_rating": 0,
                "pvp_3v3_rating": 0,
                "pvp_rbg_rating": 0,
                "pvp_honor_level": 0,
                "pvp_wins_season": 0,
            }

    async def get_character_equipment(self, realm: str, character_name: str) -> Dict[str, Any]:
        """Get character equipment data."""
        endpoint = f"/profile/wow/character/{realm.lower()}/{character_name.lower()}/equipment"
        params = {"namespace": f"profile-{self.region}"}
        return await self._make_request(endpoint, params)

    def calculate_item_level(self, equipment_data: Dict[str, Any]) -> int:
        """Calculate average item level correctly."""
        if not equipment_data or "equipped_items" not in equipment_data:
            return 0
        
        items = equipment_data["equipped_items"]
        if not items:
            return 0
        
        total_item_level = 0
        item_count = 0
        
        for item in items:
            # Skip items without item level (like tabards)
            if "item_level" in item:
                total_item_level += item["item_level"]
                item_count += 1
        
        if item_count == 0:
            return 0
        
        avg_ilvl = round(total_item_level / item_count, 1)
        _LOGGER.debug(f"Calculated item level: {avg_ilvl} from {item_count} items")
        return int(avg_ilvl)

    # === Character Statistics (for achievements only) ===
    
    async def get_character_achievements(self, realm: str, character_name: str) -> Dict[str, Any]:
        """Get character achievements data."""
        endpoint = f"/profile/wow/character/{realm.lower()}/{character_name.lower()}/achievements"
        params = {"namespace": f"profile-{self.region}"}
        return await self._make_request(endpoint, params)

    # === Raid Progress ===
    
    async def get_character_encounters_raids(self, realm: str, character_name: str) -> Dict[str, Any]:
        """Get character raid encounters."""
        endpoint = f"/profile/wow/character/{realm.lower()}/{character_name.lower()}/encounters/raids"
        params = {"namespace": f"profile-{self.region}"}
        return await self._make_request(endpoint, params)

    # === Mythic+ ===
    
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

    async def close(self):
        """Close the session."""
        if self._session:
            await self._session.close()