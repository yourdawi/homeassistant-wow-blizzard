"""Support for WoW Blizzard API sensors with all features."""
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional

from homeassistant.components.sensor import (
    SensorEntity,
    SensorEntityDescription,
    SensorDeviceClass,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.device_registry import DeviceEntryType
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
    UpdateFailed,
)

from .const import (
    DOMAIN,
    CONF_CLIENT_ID,
    CONF_CLIENT_SECRET,
    CONF_REGION,
    CONF_CHARACTERS,
    CONF_ENABLE_SERVER_STATUS,
    CONF_ENABLE_PVP,
    CONF_ENABLE_RAIDS,
    CONF_ENABLE_MYTHIC_PLUS,
    CONF_ENABLE_HALL_OF_FAME,
    CONF_LOCALE,
    ALL_SENSOR_TYPES,
    BASIC_SENSOR_TYPES,
    SERVER_SENSOR_TYPES,
    PVP_SENSOR_TYPES,
    RAID_SENSOR_TYPES,
    MYTHICPLUS_SENSOR_TYPES,
    HOF_SENSOR_TYPES,
    DEFAULT_SCAN_INTERVAL,
    FAST_SCAN_INTERVAL,
    SLOW_SCAN_INTERVAL,
    PVP_BRACKETS,
    CURRENT_RAIDS,
    CLASS_COLORS,
    get_sensor_types_for_version,
)
from .api_client import WoWBlizzardAPIClient

_LOGGER = logging.getLogger(__name__)


class WoWDataUpdateCoordinator(DataUpdateCoordinator):
    """Class to manage fetching all WoW data from the API."""

    def __init__(
        self, 
        hass: HomeAssistant, 
        client: WoWBlizzardAPIClient,
        characters: List[Dict[str, str]],
        features: Dict[str, bool]
    ):
        """Initialize."""
        self.client = client
        self.characters = characters
        self.features = features
        self.realms = set(char["realm"] for char in characters)
        
        # Cache for dynamic raid discovery and Hall of Fame leaderboards
        self._cached_raids = None
        self._last_raids_fetch = None
        self._hof_cache = {}

        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=DEFAULT_SCAN_INTERVAL),
        )

    async def _fetch_basic_character_data(self, realm: str, character_name: str, game_version: str = "retail") -> Dict[str, Any]:
        """Fetch basic character data."""
        try:
            profile = await self.client.get_character_profile(realm, character_name, game_version=game_version)
            equipment = await self.client.get_character_equipment(realm, character_name, game_version=game_version)

            # Determine which sensors this version supports
            version_sensors = get_sensor_types_for_version(game_version)
            supported_basic = version_sensors["basic"]

            # Achievements: only fetch if supported by this version
            achievement_points = 0
            if "achievement_points" in supported_basic:
                try:
                    achievements = await self.client.get_character_achievements(realm, character_name, game_version=game_version)
                    achievement_points = achievements.get("total_points", 0)
                except Exception:
                    pass

            # Item level: only available in retail and classic (Cata)
            item_level = 0
            if "character_item_level" in supported_basic:
                item_level = profile.get("equipped_item_level", 0)

            # Get guild information
            guild_name = None
            if profile.get("guild"):
                guild_name = profile["guild"]["name"]

            # Fetch character media (portrait)
            avatar_url = None
            try:
                media = await self.client.get_character_media(realm, character_name, game_version=game_version)
                if media and "assets" in media:
                    for asset in media["assets"]:
                        if asset.get("key") == "avatar":
                            avatar_url = asset.get("value")
                            break
            except Exception as media_err:
                _LOGGER.debug(f"Could not fetch media for {character_name}-{realm}: {media_err}")

            result = {
                "character_level": profile.get("level", 0),
                "guild_name": guild_name,
                "last_login_timestamp": profile.get("last_login_timestamp"),
                "character_class": profile.get("character_class", {}).get("name"),
                "character_race": profile.get("race", {}).get("name"),
                "realm": profile.get("realm", {}).get("name"),
                "faction": profile.get("faction", {}).get("name"),
                "gender": profile.get("gender", {}).get("name"),
                "spec": profile.get("active_spec", {}).get("name"),
                "avatar_url": avatar_url,
            }

            # Only include values for sensors this version supports
            if "character_item_level" in supported_basic:
                result["character_item_level"] = item_level
            if "achievement_points" in supported_basic:
                result["achievement_points"] = achievement_points

            return result

        except Exception as err:
            _LOGGER.error(f"Error fetching basic data for {character_name}-{realm}: {err}")
            return {}

    async def _fetch_server_data(self, realm: str, game_version: str = "retail") -> Dict[str, Any]:
        """Fetch server status data."""
        if not self.features.get(CONF_ENABLE_SERVER_STATUS, False):
            return {}

        try:
            realm_info = await self.client.get_realm_info(realm, game_version=game_version)
            connected_realm = await self.client.get_connected_realm(realm, game_version=game_version)

            status = "Unknown"
            population = "Unknown"
            queue_time = 0

            if connected_realm:
                status = connected_realm.get("status", {}).get("name", "Unknown")
                population = connected_realm.get("population", {}).get("name", "Unknown")
                # Get queue information if available
                if connected_realm.get("has_queue"):
                    queue_time = connected_realm.get("queue_time", 0)

            return {
                "realm_status": status,
                "realm_population": population,
                "realm_queue": queue_time,
                "realm_timezone": realm_info.get("timezone", "Unknown"),
                "realm_locale": realm_info.get("locale", "Unknown"),
            }

        except Exception as err:
            _LOGGER.error(f"Error fetching server data for {realm}: {err}")
            return {}

    async def _fetch_pvp_data(self, realm: str, character_name: str, game_version: str = "retail") -> Dict[str, Any]:
        """Fetch PvP data for a character."""
        version_sensors = get_sensor_types_for_version(game_version)
        supported_pvp = version_sensors["pvp"]

        if not self.features.get(CONF_ENABLE_PVP, False) or not supported_pvp:
            return {}

        try:
            # Only fetch brackets that this version supports
            brackets_to_fetch = []
            if "pvp_2v2_rating" in supported_pvp:
                brackets_to_fetch.append("2v2")
            if "pvp_3v3_rating" in supported_pvp:
                brackets_to_fetch.append("3v3")
            if "pvp_rbg_rating" in supported_pvp:
                brackets_to_fetch.append("rbg")

            pvp_data = {}
            # Get PvP summary
            summary = await self.client.get_character_pvp_summary(realm, character_name, game_version)
            pvp_data["summary"] = summary

            for bracket in brackets_to_fetch:
                bracket_data = await self.client.get_character_pvp_bracket(realm, character_name, bracket, game_version)
                pvp_data[bracket] = bracket_data
                await asyncio.sleep(0.1)

            # Extract ratings and stats
            result = {}

            if "pvp_honor_level" in supported_pvp and pvp_data.get("summary"):
                result["pvp_honor_level"] = pvp_data["summary"].get("honor_level", 0)

            wins_season = 0
            for bracket, data in pvp_data.items():
                if bracket == "summary":
                    continue
                if not data or "rating" not in data:
                    continue

                rating = data["rating"]
                season_wins = data.get("season_match_statistics", {}).get("won", 0)
                wins_season += season_wins

                if bracket == "2v2" and "pvp_2v2_rating" in supported_pvp:
                    result["pvp_2v2_rating"] = rating
                elif bracket == "3v3" and "pvp_3v3_rating" in supported_pvp:
                    result["pvp_3v3_rating"] = rating
                elif bracket == "rbg" and "pvp_rbg_rating" in supported_pvp:
                    result["pvp_rbg_rating"] = rating

            if "pvp_wins_season" in supported_pvp:
                result["pvp_wins_season"] = wins_season

            return result

        except Exception as err:
            _LOGGER.error(f"Error fetching PvP data for {character_name}-{realm}: {err}")
            return {}

    async def _fetch_raid_data(self, realm: str, character_name: str, game_version: str = "retail") -> Dict[str, Any]:
        """Fetch raid progress data."""
        version_sensors = get_sensor_types_for_version(game_version)
        supported_raid = version_sensors["raid"]

        if not self.features.get(CONF_ENABLE_RAIDS, False) or not supported_raid:
            return {}

        try:
            encounters = await self.client.get_character_encounters_raids(realm, character_name, game_version=game_version)

            progress_lfr = 0
            progress_normal = 0
            progress_heroic = 0
            progress_mythic = 0
            total_kills = 0

            # Count boss kills only for difficulties this version supports
            if encounters and "expansions" in encounters:
                for expansion in encounters["expansions"]:
                    for instance in expansion.get("instances", []):
                        for mode in instance.get("modes", []):
                            difficulty = mode.get("difficulty", {}).get("name", "")
                            progress = mode.get("progress", {})
                            completed = progress.get("completed_count", 0)

                            if "raid finder" in difficulty.lower() and "raid_progress_lfr" in supported_raid:
                                progress_lfr += completed
                            elif "normal" in difficulty.lower() and "raid_progress_normal" in supported_raid:
                                progress_normal += completed
                            elif "heroic" in difficulty.lower() and "raid_progress_heroic" in supported_raid:
                                progress_heroic += completed
                            elif "mythic" in difficulty.lower() and "raid_progress_mythic" in supported_raid:
                                progress_mythic += completed

                            total_kills += completed

            result = {}
            if "raid_progress_lfr" in supported_raid:
                result["raid_progress_lfr"] = progress_lfr
            if "raid_progress_normal" in supported_raid:
                result["raid_progress_normal"] = progress_normal
            if "raid_progress_heroic" in supported_raid:
                result["raid_progress_heroic"] = progress_heroic
            if "raid_progress_mythic" in supported_raid:
                result["raid_progress_mythic"] = progress_mythic
            if "raid_kills_total" in supported_raid:
                result["raid_kills_total"] = total_kills

            return result

        except Exception as err:
            _LOGGER.error(f"Error fetching raid data for {character_name}-{realm}: {err}")
            return {}

    async def _fetch_mythicplus_data(self, realm: str, character_name: str, game_version: str = "retail") -> Dict[str, Any]:
        """Fetch Mythic+ data."""
        if not self.features.get(CONF_ENABLE_MYTHIC_PLUS, False) or game_version != "retail":
            return {}

        try:
            profile = await self.client.get_character_mythicplus_profile(realm, character_name)
            season_data = await self.client.get_character_mythicplus_season(realm, character_name)

            score = 0
            best_run = 0
            runs_completed = 0
            runs_timed = 0
            weekly_best = 0

            # Get current season data
            if season_data:
                best_runs = season_data.get("best_runs", [])
                all_runs = []
                # Collect all runs from all dungeons
                for run in best_runs:
                    if "members" in run:
                        all_runs.append(run)
                # If the API provides additional fields for all runs, add here
                if best_runs:
                    best_run = max(run.get("keystone_level", 0) for run in best_runs)
                # Total number of all runs and timed runs
                runs_completed = len(all_runs)
                runs_timed = sum(1 for run in all_runs if run.get("is_completed_within_time", False))

                # Use Blizzard score directly
                score = season_data.get("mythic_rating", {}).get("rating", 0)

            # Get weekly data if available
            if profile and "current_period" in profile:
                current_period = profile["current_period"]
                if "best_runs" in current_period:
                    weekly_runs = current_period["best_runs"]
                    if weekly_runs:
                        weekly_best = max(run.get("keystone_level", 0) for run in weekly_runs)

            return {
                "mythicplus_score": score,
                "mythicplus_best_run": best_run,
                "mythicplus_runs_completed": runs_completed,
                "mythicplus_runs_timed": runs_timed,
                "mythicplus_weekly_best": weekly_best,
            }

        except Exception as err:
            _LOGGER.error(f"Error fetching M+ data for {character_name}-{realm}: {err}")
            return {}

    async def _async_update_data(self):
        """Update data via library."""
        try:
            all_data = {}
            
            # Fetch data for each character
            for character in self.characters:
                realm = character["realm"]
                name = character["character_name"]
                game_version = character.get("game_version", "retail")
                char_key = f"{realm}-{name}"
                
                # Fetch all character data
                basic_data = await self._fetch_basic_character_data(realm, name, game_version=game_version)
                pvp_data = await self._fetch_pvp_data(realm, name, game_version=game_version)
                raid_data = await self._fetch_raid_data(realm, name, game_version=game_version)
                mythicplus_data = await self._fetch_mythicplus_data(realm, name, game_version=game_version)
                
                # Combine all character data
                character_data = {
                    **basic_data,
                    **pvp_data,
                    **raid_data,
                    **mythicplus_data,
                }
                
                all_data[char_key] = character_data
                
                # Small delay to avoid rate limiting
                await asyncio.sleep(0.1)

            # Fetch server data for each unique realm
            server_data = {}
            realm_versions = {char["realm"]: char.get("game_version", "retail") for char in self.characters}
            for realm in self.realms:
                game_version = realm_versions.get(realm, "retail")
                realm_data = await self._fetch_server_data(realm, game_version=game_version)
                server_data[realm] = realm_data
                await asyncio.sleep(0.1)

            # Fetch Hall of Fame leaderboards if enabled
            if self.features.get(CONF_ENABLE_HALL_OF_FAME, True):
                leaderboards = {}
                current_raids = await self._fetch_current_raids()
                for raid in current_raids:
                    raid_name = raid["name"]
                    raid_slug = raid["id"]
                    entries = await self._fetch_hall_of_fame_data(raid_slug)
                    leaderboards[raid_slug] = {
                        "entries": entries if entries else [],
                        "raid_name": raid_name,
                    }
                all_data["leaderboards"] = leaderboards

            # Combine character and server data
            all_data["servers"] = server_data
            all_data["last_update"] = self.last_update_success

            return all_data

        except Exception as err:
            raise UpdateFailed(f"Error communicating with API: {err}")

    @staticmethod
    def generate_raid_slugs(raid_name: str) -> List[str]:
        """Generate candidate slugs for a raid name."""
        # Variant 1: standard slug (spaces to hyphens, remove special characters except hyphens)
        slug1 = raid_name.strip().lower()
        for char in ["'", ",", "\"", "(", ")", ":", "."]:
            slug1 = slug1.replace(char, "")
        slug1 = slug1.replace(" ", "-")
        while "--" in slug1:
            slug1 = slug1.replace("--", "-")
        
        # Variant 2: remove all hyphens within words (e.g. Nerub-ar -> Nerubar)
        slug2 = raid_name.strip().lower()
        for char in ["'", ",", "\"", "(", ")", ":", ".", "-"]:
            slug2 = slug2.replace(char, "")
        slug2 = slug2.replace(" ", "-")
        while "--" in slug2:
            slug2 = slug2.replace("--", "-")
            
        candidates = [slug1]
        if slug2 != slug1:
            candidates.append(slug2)
        return candidates

    async def _fetch_current_raids(self) -> List[Dict[str, Any]]:
        """Fetch all available mythic raids for the latest expansion dynamically from GraphQL endpoint."""
        now = datetime.now()
        # Cache expansions/raids index for 24 hours
        if self._cached_raids is not None and self._last_raids_fetch is not None:
            if now - self._last_raids_fetch < timedelta(hours=24):
                return self._cached_raids

        try:
            data = await self.client.get_all_mythic_raids_graphql()
            if data and "data" in data:
                expansions_data = data["data"].get("MythicRaidLeaderboardExpansions", {})
                expansions = expansions_data.get("expansions", [])
                
                raids = []
                if expansions:
                    latest_exp = expansions[0]
                    _LOGGER.info(f"Latest expansion detected dynamically: {latest_exp.get('name')}")
                    for zone in latest_exp.get("zones", []):
                        raids.append({
                            "id": zone.get("slug"),  # use slug as ID
                            "name": zone.get("name"),
                            "expansion_name": latest_exp.get("name")
                        })
                
                if raids:
                    self._cached_raids = raids
                    self._last_raids_fetch = now
                    return raids
        except Exception as err:
            _LOGGER.error(f"Error fetching current raids via GraphQL: {err}")

        if self._cached_raids is not None:
            return self._cached_raids
        return []

    async def _fetch_hall_of_fame_data(self, raid_slug: str) -> Optional[List[Dict[str, Any]]]:
        """Fetch Hall of Fame data for a raid, using cache."""
        now = datetime.now()
        cache_key = raid_slug
        
        # Check cache. If it's already completed, we keep it indefinitely during runtime
        if cache_key in self._hof_cache:
            fetch_time, cached_data = self._hof_cache[cache_key]
            if cached_data is not None:
                # Completed check: >= 100 entries (older or unified global)
                if len(cached_data) >= 100:
                    return cached_data
                # Otherwise, cache for 2 hours during progression
                if now - fetch_time < timedelta(hours=2):
                    return cached_data
            else:
                # If cached value is None (not found), check it again after 2 hours
                if now - fetch_time < timedelta(hours=2):
                    return cached_data

        try:
            # We call get_hall_of_fame with faction='horde' (arbitrary, as the new client returns unified)
            hof_data = await self.client.get_hall_of_fame(raid_slug, "horde")
            if hof_data and "entries" in hof_data:
                entries = hof_data["entries"]
                self._hof_cache[cache_key] = (now, entries)
                return entries
            
            # Empty dictionary indicates 404/not found
            self._hof_cache[cache_key] = (now, None)
            return None
        except Exception as err:
            _LOGGER.debug(f"Could not retrieve Hall of Fame for {raid_slug}: {err}")
            self._hof_cache[cache_key] = (now, None)
            return None


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up WoW Blizzard sensors based on a config entry."""
    client_id = entry.data[CONF_CLIENT_ID]
    client_secret = entry.data[CONF_CLIENT_SECRET]
    region = entry.data[CONF_REGION]
    characters = entry.data.get(CONF_CHARACTERS, [])
    
    # Feature flags from options with data as fallback
    features = {
        CONF_ENABLE_SERVER_STATUS: entry.options.get(CONF_ENABLE_SERVER_STATUS, entry.data.get(CONF_ENABLE_SERVER_STATUS, True)),
        CONF_ENABLE_PVP: entry.options.get(CONF_ENABLE_PVP, entry.data.get(CONF_ENABLE_PVP, True)),
        CONF_ENABLE_RAIDS: entry.options.get(CONF_ENABLE_RAIDS, entry.data.get(CONF_ENABLE_RAIDS, True)),
        CONF_ENABLE_MYTHIC_PLUS: entry.options.get(CONF_ENABLE_MYTHIC_PLUS, entry.data.get(CONF_ENABLE_MYTHIC_PLUS, True)),
        CONF_ENABLE_HALL_OF_FAME: entry.options.get(CONF_ENABLE_HALL_OF_FAME, entry.data.get(CONF_ENABLE_HALL_OF_FAME, True)),
    }

    if not characters:
        _LOGGER.error("No characters configured")
        return

    locale = entry.data.get(CONF_LOCALE)
    client = WoWBlizzardAPIClient(client_id, client_secret, region, locale=locale)
    coordinator = WoWDataUpdateCoordinator(hass, client, characters, features)
    if isinstance(hass.data[DOMAIN].get(entry.entry_id), dict):
        hass.data[DOMAIN][entry.entry_id]["coordinator"] = coordinator

    # Fetch initial data
    await coordinator.async_config_entry_first_refresh()

    # Create sensors
    entities = []
    
    # Character sensors
    for character in characters:
        realm = character["realm"]
        name = character["character_name"]
        game_version = character.get("game_version", "retail")
        char_key = f"{realm}-{name}"
        
        # Get the sensor types applicable to this game version
        version_sensors = get_sensor_types_for_version(game_version)
        
        # Basic character sensors (version-filtered)
        for sensor_type in version_sensors["basic"]:
            entities.append(
                WoWCharacterSensor(coordinator, sensor_type, char_key, name, realm, game_version)
            )
        
        # PvP sensors (version-filtered)
        if features[CONF_ENABLE_PVP] and version_sensors["pvp"]:
            for sensor_type in version_sensors["pvp"]:
                entities.append(
                    WoWCharacterSensor(coordinator, sensor_type, char_key, name, realm, game_version)
                )
        
        # Raid sensors (version-filtered)
        if features[CONF_ENABLE_RAIDS] and version_sensors["raid"]:
            for sensor_type in version_sensors["raid"]:
                entities.append(
                    WoWCharacterSensor(coordinator, sensor_type, char_key, name, realm, game_version)
                )
        
        # Mythic+ sensors (version-filtered)
        if features[CONF_ENABLE_MYTHIC_PLUS] and version_sensors["mythicplus"]:
            for sensor_type in version_sensors["mythicplus"]:
                entities.append(
                    WoWCharacterSensor(coordinator, sensor_type, char_key, name, realm, game_version)
                )

    # Server sensors
    if features[CONF_ENABLE_SERVER_STATUS]:
        realms = set(char["realm"] for char in characters)
        for realm in realms:
            for sensor_type in SERVER_SENSOR_TYPES:
                entities.append(
                    WoWServerSensor(coordinator, sensor_type, realm)
                )

    # Hall of Fame Leaderboard sensors (Retail only)
    has_retail = any(char.get("game_version", "retail") == "retail" for char in characters)
    if features[CONF_ENABLE_HALL_OF_FAME] and has_retail:
        current_raids = coordinator._cached_raids or []
        for raid in current_raids:
            raid_name = raid["name"]
            raid_slug = raid["id"]
            entities.append(
                WoWLeaderboardSensor(coordinator, "hall_of_fame", raid_slug, raid_name)
            )

    async_add_entities(entities)


class WoWCharacterSensor(CoordinatorEntity, SensorEntity):
    """Representation of a WoW character sensor."""

    def __init__(
        self, 
        coordinator: WoWDataUpdateCoordinator,
        sensor_type: str,
        char_key: str,
        character_name: str,
        realm: str,
        game_version: str = "retail"
    ):
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._sensor_type = sensor_type
        self._char_key = char_key
        self._character_name = character_name
        self._realm = realm
        self._game_version = game_version
        
        sensor_config = ALL_SENSOR_TYPES[sensor_type]
        
        self._attr_has_entity_name = True
        self._attr_translation_key = sensor_type
        self._attr_unique_id = f"{DOMAIN}_{realm}_{character_name}_{sensor_type}"
        self._attr_icon = sensor_config["icon"]
        self._attr_native_unit_of_measurement = sensor_config.get("unit")
        self._attr_device_class = sensor_config.get("device_class")

    @property
    def native_value(self):
        """Return the state of the sensor."""
        if not self.coordinator.data or self._char_key not in self.coordinator.data:
            return None
        return self.coordinator.data[self._char_key].get(self._sensor_type)

    @property
    def entity_picture(self):
        """Return the entity picture."""
        if not self.coordinator.data or self._char_key not in self.coordinator.data:
            return None
        return self.coordinator.data[self._char_key].get("avatar_url")

    @property
    def extra_state_attributes(self):
        """Return additional state attributes."""
        if not self.coordinator.data or self._char_key not in self.coordinator.data:
            return {}
        
        char_data = self.coordinator.data[self._char_key]
        
        attributes = {
            "character_name": self._character_name,
            "realm": self._realm,
            "character_class": char_data.get("character_class"),
            "character_race": char_data.get("character_race"),
            "character_level": char_data.get("character_level"),
            "last_update": self.coordinator.last_update_success,
            "faction": char_data.get("faction"),
            "active_spec": char_data.get("spec"),
            "game_version": self._game_version,
        }
        
        # Add class color if available
        if char_data.get("character_class") in CLASS_COLORS:
            attributes["class_color"] = CLASS_COLORS[char_data["character_class"]]
        
        # Add specific attributes based on sensor type
        if self._sensor_type in PVP_SENSOR_TYPES:
            attributes["category"] = "pvp"
        elif self._sensor_type in RAID_SENSOR_TYPES:
            attributes["category"] = "raid"
        elif self._sensor_type in MYTHICPLUS_SENSOR_TYPES:
            attributes["category"] = "mythic_plus"
        else:
            attributes["category"] = "character"
            
        return attributes

    @property
    def device_info(self):
        """Return device info."""
        sw_version = "The War Within"
        if self._game_version == "classic":
            sw_version = "Cataclysm Classic"
        elif self._game_version == "classic1x":
            sw_version = "Classic Era"
        elif self._game_version == "classicann":
            sw_version = "Burning Crusade Classic (Anniversary)"

        return {
            "identifiers": {(DOMAIN, f"{self._realm}_{self._character_name}")},
            "name": f"{self._character_name} ({self._realm})",
            "manufacturer": "Blizzard Entertainment",
            "model": "World of Warcraft Character",
            "sw_version": sw_version,
        }


class WoWServerSensor(CoordinatorEntity, SensorEntity):
    """Representation of a WoW server sensor."""

    def __init__(
        self, 
        coordinator: WoWDataUpdateCoordinator,
        sensor_type: str,
        realm: str
    ):
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._sensor_type = sensor_type
        self._realm = realm
        
        sensor_config = ALL_SENSOR_TYPES[sensor_type]
        
        self._attr_has_entity_name = True
        self._attr_translation_key = sensor_type
        self._attr_unique_id = f"{DOMAIN}_server_{realm}_{sensor_type}"
        self._attr_icon = sensor_config["icon"]
        self._attr_native_unit_of_measurement = sensor_config.get("unit")
        self._attr_device_class = sensor_config.get("device_class")

    @property
    def native_value(self):
        """Return the state of the sensor."""
        if (not self.coordinator.data 
            or "servers" not in self.coordinator.data 
            or self._realm not in self.coordinator.data["servers"]):
            return None
        return self.coordinator.data["servers"][self._realm].get(self._sensor_type)

    @property
    def extra_state_attributes(self):
        """Return additional state attributes."""
        if (not self.coordinator.data 
            or "servers" not in self.coordinator.data 
            or self._realm not in self.coordinator.data["servers"]):
            return {}
        
        realm_data = self.coordinator.data["servers"][self._realm]
        
        return {
            "realm": self._realm,
            "category": "server",
            "timezone": realm_data.get("realm_timezone"),
            "locale": realm_data.get("realm_locale"),
            "last_update": self.coordinator.last_update_success,
        }

    @property
    def device_info(self):
        """Return device info."""
        return {
            "identifiers": {(DOMAIN, f"server_{self._realm}")},
            "name": f"{self._realm.title()} Server",
            "manufacturer": "Blizzard Entertainment",
            "model": "World of Warcraft Realm",
            "sw_version": "The War Within",
        }


class WoWLeaderboardSensor(CoordinatorEntity, SensorEntity):
    """Representation of a WoW Mythic Raid Hall of Fame leaderboard sensor."""

    def __init__(
        self,
        coordinator: WoWDataUpdateCoordinator,
        sensor_type: str,
        raid_slug: str,
        raid_name: str,
    ):
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._sensor_type = sensor_type
        self._raid_slug = raid_slug
        self._raid_name = raid_name
        
        sensor_config = HOF_SENSOR_TYPES[sensor_type]
        self._attr_has_entity_name = True
        self._attr_translation_key = sensor_type
        self._attr_unique_id = f"{DOMAIN}_{raid_slug}_hof"
        self._attr_icon = sensor_config["icon"]
        self._attr_native_unit_of_measurement = sensor_config.get("unit")
        self._attr_device_class = sensor_config.get("device_class")

    @property
    def name(self) -> str:
        """Return the name of the entity."""
        return self._raid_name

    @property
    def native_value(self):
        """Return the state of the sensor (name of the world first guild)."""
        if not self.coordinator.data or "leaderboards" not in self.coordinator.data:
            return None
        
        leaderboard = self.coordinator.data["leaderboards"].get(self._raid_slug)
        if not leaderboard:
            return None
        
        entries = leaderboard.get("entries", [])
        if len(entries) > 0:
            return entries[0].get("guild", {}).get("name")
        return "Pending"

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        """Return additional state attributes."""
        locale_url = self.coordinator.client.locale.replace("_", "-").lower() if self.coordinator.client.locale else "de-de"
        info_url = f"https://worldofwarcraft.blizzard.com/{locale_url}/game/hall-of-fame/mythic-raid/{self._raid_slug}"

        attributes = {
            "raid_name": self._raid_name,
            "faction": "Unified",
            "region": "Global",
            "completed": False,
            "info_url": info_url,
            "world_first_guild": None,
            "world_first_realm": None,
            "world_first_region": None,
            "world_first_timestamp": None,
            "world_first_timestamp_formatted": None,
            "last_guild_name": None,
            "last_guild_rank": None,
            "last_guild_timestamp": None,
            "last_guild_timestamp_formatted": None,
            "character_guild_ranks": {},
        }
        
        if not self.coordinator.data or "leaderboards" not in self.coordinator.data:
            return attributes
            
        leaderboard = self.coordinator.data["leaderboards"].get(self._raid_slug)
        if not leaderboard:
            return attributes
            
        entries = leaderboard.get("entries", [])
        total_entries = len(entries)
        
        # Unified global leaderboards have a cap of 200 entries; older regional factions have 100.
        attributes["completed"] = total_entries >= 200 if total_entries > 100 else total_entries >= 100
        
        if total_entries > 0:
            first_entry = entries[0]
            attributes["world_first_guild"] = first_entry.get("guild", {}).get("name")
            attributes["world_first_realm"] = first_entry.get("guild", {}).get("realm", {}).get("slug")
            attributes["world_first_region"] = str(first_entry.get("region", "")).upper()
            
            first_ts = first_entry.get("timestamp")
            attributes["world_first_timestamp"] = first_ts
            if first_ts:
                try:
                    from datetime import timezone
                    dt = datetime.fromtimestamp(float(first_ts) / 1000, timezone.utc)
                    attributes["world_first_timestamp_formatted"] = dt.strftime("%Y-%m-%d %H:%M:%S UTC")
                except Exception:
                    attributes["world_first_timestamp_formatted"] = None
            
            last_entry = entries[-1]
            attributes["last_guild_name"] = last_entry.get("guild", {}).get("name")
            attributes["last_guild_rank"] = last_entry.get("rank")
            
            last_ts = last_entry.get("timestamp")
            attributes["last_guild_timestamp"] = last_ts
            if last_ts:
                try:
                    from datetime import timezone
                    dt = datetime.fromtimestamp(float(last_ts) / 1000, timezone.utc)
                    attributes["last_guild_timestamp_formatted"] = dt.strftime("%Y-%m-%d %H:%M:%S UTC")
                except Exception:
                    attributes["last_guild_timestamp_formatted"] = None

        # Map configured retail characters to their guild rank
        char_ranks = {}
        for character in self.coordinator.characters:
            if character.get("game_version", "retail") != "retail":
                continue
            
            char_key = f"{character['realm']}-{character['character_name']}"
            char_data = self.coordinator.data.get(char_key, {})
            guild_name = char_data.get("guild_name")
            if not guild_name:
                continue
            
            char_realm_slug = self.coordinator.client.realm_to_slug(character["realm"])
            for entry in entries:
                entry_guild = entry.get("guild", {})
                entry_guild_name = entry_guild.get("name")
                entry_realm_slug = entry_guild.get("realm", {}).get("slug")
                
                if entry_guild_name and entry_guild_name.lower() == guild_name.lower():
                    if entry_realm_slug == char_realm_slug:
                        char_ranks[character["character_name"]] = entry.get("rank")
                        break
                        
        attributes["character_guild_ranks"] = char_ranks
        return attributes

    @property
    def device_info(self):
        """Return device info."""
        return {
            "identifiers": {(DOMAIN, "leaderboards")},
            "name": "WoW Leaderboards",
            "manufacturer": "Blizzard Entertainment",
            "model": "World of Warcraft Leaderboards",
            "entry_type": DeviceRegistryEntryType.SERVICE if 'DeviceRegistryEntryType' in globals() else DeviceEntryType.SERVICE,
        }