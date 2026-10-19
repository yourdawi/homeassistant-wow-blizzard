"""WoW Blizzard API Client"""
import asyncio
import aiohttp
import logging
import base64
import re
import unicodedata
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List

from .const import (
    API_URLS,
    TOKEN_URLS,
    GAME_VERSIONS,
    HOF_SITE_URL,
    HOF_QUERY_HASHES,
    HOF_VARIANT,
    HOF_REGION,
    HOF_PROBE_RAID,
)

_LOGGER = logging.getLogger(__name__)

MAX_RATE_LIMIT_RETRIES = 2


class WoWBlizzardAPIClient:
    """API client"""

    @staticmethod
    def realm_to_slug(realm: str) -> str:
        """Convert realm name to slug for Blizzard API."""
        if not realm or not isinstance(realm, str):
            return ""
        slug = realm.strip().lower().replace("ß", "ss")
        slug = unicodedata.normalize("NFKD", slug).encode("ascii", "ignore").decode()
        slug = slug.replace("'", "").replace(" ", "-")
        return re.sub(r"-{2,}", "-", slug)

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
        self._owns_session = session is None
        self._access_token = None
        self._token_expires = None
        self._request_count = 0
        self._last_request_reset = datetime.now()
        # HTTP status of the last API request (None on network errors), lets
        # callers tell a 404 apart from other failures
        self.last_status: Optional[int] = None
        # Resolved namespace suffix per game version (see GAME_VERSIONS)
        self._namespace_suffixes: Dict[str, str] = {}
        # Hall of Fame persisted query hashes, refreshed from the site bundle on demand
        self._hof_hashes: Dict[str, str] = dict(HOF_QUERY_HASHES)

    def set_namespace_suffix(self, game_version: str, suffix: str) -> None:
        """Pin the namespace suffix for a game version (e.g. after probing)."""
        self._namespace_suffixes[game_version] = suffix

    def get_namespace(self, base_type: str, game_version: str = "retail") -> str:
        """Get the correct namespace based on game version and region."""
        suffix = self._namespace_suffixes.get(game_version)
        if suffix is None:
            suffix = GAME_VERSIONS.get(game_version, GAME_VERSIONS["retail"])["namespaces"][0]
        return f"{base_type}{suffix}-{self.region}"

    async def resolve_namespace_suffix(self, game_version: str) -> Optional[str]:
        """Find the namespace suffix that the API accepts for a game version.

        Probes the realm index with every candidate from GAME_VERSIONS and returns
        the first suffix that answers, or None if no candidate works (e.g. the
        game version is not available in the API yet).
        """
        candidates = GAME_VERSIONS.get(game_version, GAME_VERSIONS["retail"])["namespaces"]
        for suffix in candidates:
            params = {"namespace": f"dynamic{suffix}-{self.region}"}
            data = await self._make_request("/data/wow/realm/index", params)
            if data and data.get("realms"):
                self.set_namespace_suffix(game_version, suffix)
                return suffix
        return None

    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create aiohttp session."""
        if self._session is None or (self._owns_session and self._session.closed):
            self._owns_session = True
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
                if response.status in (400, 401):
                    error_text = await response.text()
                    _LOGGER.error(f"Token request rejected: {response.status} - {error_text}")
                    raise InvalidCredentials(f"Invalid client credentials: {response.status}")
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
 
    async def _make_request(self, endpoint: str, params: Dict[str, Any] = None, _retries: int = 0) -> Dict[str, Any]:
        """Make authenticated API request."""
        access_token = await self._get_access_token()
        session = await self._get_session()
        
        headers = {
            "Authorization": f"Bearer {access_token}",
            "User-Agent": "HomeAssistant-WoW-Integration/2025.8",
        }
        
        url = f"{self.api_url}{endpoint}"
        
        params = dict(params or {})
        if "locale" not in params:
            params["locale"] = self.locale
        
        try:
            async with session.get(url, headers=headers, params=params) as response:
                self._request_count += 1
                self.last_status = response.status

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
                    if _retries >= MAX_RATE_LIMIT_RETRIES:
                        _LOGGER.warning(f"Rate limited on {endpoint}, giving up for this update")
                        return {}
                    try:
                        retry_after = int(response.headers.get("Retry-After", 5))
                    except ValueError:
                        retry_after = 5
                    _LOGGER.warning(f"Rate limited, retrying in {retry_after} seconds")
                    await asyncio.sleep(min(retry_after, 30))
                    return await self._make_request(endpoint, params, _retries + 1)
                else:
                    error_text = await response.text()
                    _LOGGER.error(f"API Error {response.status}: {error_text}")
                    return {}
        except Exception as e:
            self.last_status = None
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

    async def get_character_media(self, realm: str, character_name: str, game_version: str = "retail") -> Dict[str, Any]:
        """Get character media data (portrait renders)."""
        realm_slug = self.realm_to_slug(realm)
        endpoint = f"/profile/wow/character/{realm_slug}/{character_name.lower()}/character-media"
        params = {"namespace": self.get_namespace("profile", game_version)}
        return await self._make_request(endpoint, params)

    async def get_character_resource(self, realm: str, character_name: str, resource: str, game_version: str = "retail") -> Dict[str, Any]:
        """Get a character sub-resource such as "status", "professions" or "collections/mounts"."""
        realm_slug = self.realm_to_slug(realm)
        endpoint = f"/profile/wow/character/{realm_slug}/{character_name.lower()}/{resource}"
        params = {"namespace": self.get_namespace("profile", game_version)}
        return await self._make_request(endpoint, params)

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

    async def get_connected_realm(self, realm: str, game_version: str = "retail", realm_info: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Get connected realm info (for server status)."""
        if realm_info is None:
            realm_info = await self.get_realm_info(realm, game_version)
        if not realm_info or "id" not in realm_info:
            return {}
        
        # Extract connected realm ID from href, e.g. "https://us.api.blizzard.com/data/wow/connected-realm/11?namespace=dynamic-us"
        connected_realm_href = realm_info.get("connected_realm", {}).get("href", "")
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

    async def get_character_mythicplus_season(self, realm: str, character_name: str, season_id: int = None, profile: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Get character Mythic+ season data. Uses the latest season from the keystone profile if no ID is given."""
        if season_id is None:
            if profile is None:
                profile = await self.get_character_mythicplus_profile(realm, character_name)
            season_ids = [
                s.get("id") for s in profile.get("seasons") or []
                if isinstance(s, dict) and isinstance(s.get("id"), int)
            ]
            if not season_ids:
                # No runs in any season, nothing to fetch
                return {}
            season_id = max(season_ids)
        realm_slug = self.realm_to_slug(realm)
        endpoint = f"/profile/wow/character/{realm_slug}/{character_name.lower()}/mythic-keystone-profile/season/{season_id}"
        params = {"namespace": f"profile-{self.region}"}
        return await self._make_request(endpoint, params)

    # === Guild Methods ===
    
    async def get_guild(self, guild_path: str, game_version: str = "retail") -> Dict[str, Any]:
        """Get guild information by its "{realmSlug}/{nameSlug}" path.

        The path is taken from the guild link in the character profile, since the
        guild's realm can differ from the character's (connected realms).
        """
        if not guild_path:
            return {}
        endpoint = f"/data/wow/guild/{guild_path}"
        params = {"namespace": self.get_namespace("profile", game_version)}
        return await self._make_request(endpoint, params)

    # === Region-wide data ===

    async def get_wow_token(self, game_version: str = "retail") -> Dict[str, Any]:
        """Get the current WoW Token price (in copper) for the region."""
        params = {"namespace": self.get_namespace("dynamic", game_version)}
        return await self._make_request("/data/wow/token/index", params)

    async def get_current_keystone_period(self) -> Dict[str, Any]:
        """Get the current weekly period (start and end of the reset week)."""
        params = {"namespace": self.get_namespace("dynamic", "retail")}
        index = await self._make_request("/data/wow/mythic-keystone/period/index", params)
        period_id = (index.get("current_period") or {}).get("id")
        if not isinstance(period_id, int):
            return {}
        return await self._make_request(f"/data/wow/mythic-keystone/period/{period_id}", params)

    # === Hall of Fame and expansions ===

    def _hof_locale(self) -> str:
        """Website locale for the Hall of Fame, e.g. 'en-us'."""
        return (self.locale or "en_US").replace("_", "-").lower()

    def hof_page_url(self, raid_slug: str) -> str:
        """Public Hall of Fame page for a raid."""
        url = f"{HOF_SITE_URL}/{self._hof_locale()}/{HOF_VARIANT}/{HOF_REGION}/leaderboards/hall-of-fame/mythic-raid"
        return f"{url}/{raid_slug}"

    async def _refresh_hof_hashes(self) -> bool:
        """Re-read the persisted query hashes from the Hall of Fame JS bundle.

        Blizzard only accepts allow-listed persisted queries on its GraphQL
        endpoint, and the hashes change whenever the site changes a query.
        """
        session = await self._get_session()
        headers = {"User-Agent": "Mozilla/5.0 (compatible; HomeAssistant-WoW-Integration)"}
        try:
            async with session.get(self.hof_page_url(HOF_PROBE_RAID), headers=headers) as response:
                if response.status != 200:
                    return False
                html = await response.text()
            bundles = re.findall(r'src="(https://[^"]+/mythic-raid-leaderboard\.[0-9a-f]+\.js)"', html)
            if not bundles:
                _LOGGER.debug("Hall of Fame bundle not found on page")
                return False
            async with session.get(bundles[0], headers=headers) as response:
                if response.status != 200:
                    return False
                script = await response.text()
        except Exception as e:
            _LOGGER.debug(f"Could not refresh Hall of Fame query hashes: {e}")
            return False

        found = False
        for operation in HOF_QUERY_HASHES:
            match = re.search(r'"%s"\)\s*,\s*\w+\.documentId\s*=\s*"([0-9a-f]{64})"' % operation, script)
            if match:
                self._hof_hashes[operation] = match.group(1)
                found = True
        if found:
            _LOGGER.info("Refreshed Hall of Fame query hashes from the website")
        return found

    async def _hof_graphql(self, operation: str, variables: Dict[str, Any], _retry: bool = True) -> Dict[str, Any]:
        """Run a persisted Hall of Fame query against the public GraphQL endpoint."""
        session = await self._get_session()
        url = f"{HOF_SITE_URL}/{self._hof_locale()}/graphql"
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (compatible; HomeAssistant-WoW-Integration)",
        }
        payload = {
            "operationName": operation,
            "variables": variables,
            "extensions": {"persistedQuery": {"version": 1, "sha256Hash": self._hof_hashes[operation]}},
        }

        try:
            async with session.post(url, json=payload, headers=headers) as response:
                status = response.status
                body = await response.json(content_type=None)
        except Exception as e:
            _LOGGER.error(f"Failed to fetch GraphQL {operation}: {e}")
            return {}

        body = body if isinstance(body, dict) else {}
        if status == 200 and body.get("data"):
            return body

        messages = [err.get("message", "") for err in body.get("errors") or []]
        # An unknown hash is answered with 400 "PersistedQueryNotSupported"
        if _retry and any("PersistedQuery" in m for m in messages):
            if await self._refresh_hof_hashes():
                return await self._hof_graphql(operation, variables, _retry=False)
        _LOGGER.warning(f"GraphQL {operation} failed: {status} {messages}")
        return {}

    async def get_all_mythic_raids_graphql(self) -> Dict[str, Any]:
        """Get all mythic raids and expansions from the public GraphQL endpoint."""
        return await self._hof_graphql(
            "GetAllMythicRaids",
            {"input": {"variant": HOF_VARIANT, "region": HOF_REGION}},
        )

    async def get_hall_of_fame_graphql(self, raid_slug: str) -> Dict[str, Any]:
        """Get Hall of Fame data using the public World of Warcraft GraphQL endpoint."""
        # The leaderboard is global; adding variant/region makes the endpoint error out
        return await self._hof_graphql(
            "GetMythicRaidLeaderboard",
            {"leaderboard": {"zoneSlug": raid_slug}},
        )

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
        unified = len(leaderboards) == 1
        if unified:
            # Unified leaderboard (one faction-less list with up to 200 entries)
            target_leaderboard = leaderboards[0]
        else:
            # Split leaderboards (Alliance and Horde)
            for lb in leaderboards:
                if (lb.get("factionEnum") or "").lower() == faction.lower() or (lb.get("factionName") or "").lower() == faction.lower():
                    target_leaderboard = lb
                    break

        if not target_leaderboard:
            return {}

        # Normalize entries to REST structure
        normalized_entries = []
        for entry in target_leaderboard.get("entries", []):
            guild = entry.get("guild") or {}
            realm = guild.get("realm") or {}

            # Guild URL looks like "/en_us/worldsoul/eu/armory/guild/tarren-mill/echo";
            # it is null for CN guilds, so fall back to slugifying the realm name
            guild_url = guild.get("url") or ""
            parts = [p for p in guild_url.split("/") if p]
            if "guild" in parts and parts.index("guild") + 1 < len(parts):
                realm_slug = parts[parts.index("guild") + 1]
            else:
                realm_slug = self.realm_to_slug(realm.get("name", ""))

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

        return {"entries": normalized_entries, "unified": unified}

    async def close(self):
        """Close the session if this client created it."""
        if self._session and self._owns_session:
            await self._session.close()
            self._session = None


class InvalidCredentials(Exception):
    """Raised when Battle.net rejects the client credentials."""