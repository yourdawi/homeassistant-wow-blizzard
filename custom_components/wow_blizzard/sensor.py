"""Support for WoW Blizzard API sensors with all features."""
import asyncio
import logging
from datetime import timedelta
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
    ALL_SENSOR_TYPES,
    BASIC_SENSOR_TYPES,
    SERVER_SENSOR_TYPES,
    PVP_SENSOR_TYPES,
    RAID_SENSOR_TYPES,
    MYTHICPLUS_SENSOR_TYPES,
    DEFAULT_SCAN_INTERVAL,
    FAST_SCAN_INTERVAL,
    SLOW_SCAN_INTERVAL,
    PVP_BRACKETS,
    CURRENT_RAIDS,
    CLASS_COLORS,
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

        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=DEFAULT_SCAN_INTERVAL),
        )

    async def _fetch_basic_character_data(self, realm: str, character_name: str) -> Dict[str, Any]:
        """Fetch basic character data."""
        try:
            profile = await self.client.get_character_profile(realm, character_name)
            equipment = await self.client.get_character_equipment(realm, character_name)
            achievements = await self.client.get_character_achievements(realm, character_name)
            # Calculate average item level
            item_level = 0
            if equipment.get("equipped_items"):
                total_item_level = 0
                item_count = 0
                for item in equipment["equipped_items"]:
                    if "item_level" in item:
                        total_item_level += item["item_level"]
                        item_count += 1
                if item_count > 0:
                    item_level = round(total_item_level / item_count)

            # Get achievement points
            achievement_points = achievements.get("total_points", 0)

            # Get guild information
            guild_name = None
            if profile.get("guild"):
                guild_name = profile["guild"]["name"]

            return {
                "character_level": profile.get("level", 0),
                "character_item_level": item_level,
                "guild_name": guild_name,
                "achievement_points": achievement_points,
                "last_login_timestamp": profile.get("last_login_timestamp"),
                "character_class": profile.get("character_class", {}).get("name"),
                "character_race": profile.get("race", {}).get("name"),
                "realm": profile.get("realm", {}).get("name"),
                "faction": profile.get("faction", {}).get("name"),
                "gender": profile.get("gender", {}).get("name"),
                "spec": profile.get("active_spec", {}).get("name"),
            }

        except Exception as err:
            _LOGGER.error(f"Error fetching basic data for {character_name}-{realm}: {err}")
            return {}

    async def _fetch_server_data(self, realm: str) -> Dict[str, Any]:
        """Fetch server status data."""
        if not self.features.get(CONF_ENABLE_SERVER_STATUS, False):
            return {}

        try:
            realm_info = await self.client.get_realm_info(realm)
            connected_realm = await self.client.get_connected_realm(realm)

            status = "Unknown"
            population = "Unknown"
            queue_time = 0

            if realm_info:
                status = realm_info.get("status", {}).get("name", "Unknown")
                population = realm_info.get("population", {}).get("name", "Unknown")

            if connected_realm:
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

    async def _fetch_pvp_data(self, realm: str, character_name: str) -> Dict[str, Any]:
        """Fetch PvP data for a character."""
        if not self.features.get(CONF_ENABLE_PVP, False):
            return {}

        try:
            pvp_data = await self.client.get_all_pvp_data(realm, character_name)

            # Extract ratings and stats
            ratings_2v2 = 0
            ratings_3v3 = 0
            ratings_rbg = 0
            honor_level = 0
            wins_season = 0

            if pvp_data.get("summary"):
                honor_level = pvp_data["summary"].get("honor_level", 0)

            # Process bracket data
            for bracket, data in pvp_data.items():
                if bracket == "summary":
                    continue
                    
                if not data or "rating" not in data:
                    continue

                rating = data["rating"]
                season_wins = data.get("season_match_statistics", {}).get("won", 0)
                wins_season += season_wins

                if bracket == "2v2":
                    ratings_2v2 = rating
                elif bracket == "3v3":
                    ratings_3v3 = rating
                elif bracket == "rbg":
                    ratings_rbg = rating

            return {
                "pvp_2v2_rating": ratings_2v2,
                "pvp_3v3_rating": ratings_3v3,
                "pvp_rbg_rating": ratings_rbg,
                "pvp_honor_level": honor_level,
                "pvp_wins_season": wins_season,
            }

        except Exception as err:
            _LOGGER.error(f"Error fetching PvP data for {character_name}-{realm}: {err}")
            return {}

    async def _fetch_raid_data(self, realm: str, character_name: str) -> Dict[str, Any]:
        """Fetch raid progress data."""
        if not self.features.get(CONF_ENABLE_RAIDS, False):
            return {}

        try:
            encounters = await self.client.get_character_encounters_raids(realm, character_name)

            progress_lfr = 0
            progress_normal = 0
            progress_heroic = 0
            progress_mythic = 0
            total_kills = 0

            # Filter auf aktuelle Expansion "The War Within"
            if encounters and "expansions" in encounters:
                for expansion in encounters["expansions"]:
                    if expansion.get("expansion", {}).get("name") != "The War Within":
                        continue  # Nur aktuelle Expansion

                    for instance in expansion.get("instances", []):
                        for mode in instance.get("modes", []):
                            difficulty = mode.get("difficulty", {}).get("name", "")
                            progress = mode.get("progress", {})
                            completed = progress.get("completed_count", 0)
                            total_encounters = progress.get("total_count", 0)

                            if "raid finder" in difficulty.lower():
                                progress_lfr += completed
                            elif "normal" in difficulty.lower():
                                progress_normal += completed
                            elif "heroic" in difficulty.lower():
                                progress_heroic += completed
                            elif "mythic" in difficulty.lower():
                                progress_mythic += completed

                            total_kills += completed

            return {
                "raid_progress_lfr": progress_lfr,
                "raid_progress_normal": progress_normal,
                "raid_progress_heroic": progress_heroic,
                "raid_progress_mythic": progress_mythic,
                "raid_kills_total": total_kills,
            }

        except Exception as err:
            _LOGGER.error(f"Error fetching raid data for {character_name}-{realm}: {err}")
            return {}

    async def _fetch_mythicplus_data(self, realm: str, character_name: str) -> Dict[str, Any]:
        """Fetch Mythic+ data."""
        if not self.features.get(CONF_ENABLE_MYTHIC_PLUS, False):
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
                if best_runs:
                    # Get highest key level
                    best_run = max(run.get("keystone_level", 0) for run in best_runs)
                    runs_completed = len(best_runs)
                    runs_timed = sum(1 for run in best_runs if run.get("is_completed_within_time", False))

                # Calculate approximate score (simplified)
                score = sum(
                    run.get("keystone_level", 0) * (125 if run.get("is_completed_within_time") else 100)
                    for run in best_runs
                )

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
                char_key = f"{realm}-{name}"
                
                # Fetch all character data
                basic_data = await self._fetch_basic_character_data(realm, name)
                pvp_data = await self._fetch_pvp_data(realm, name)
                raid_data = await self._fetch_raid_data(realm, name)
                mythicplus_data = await self._fetch_mythicplus_data(realm, name)
                
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
            for realm in self.realms:
                realm_data = await self._fetch_server_data(realm)
                server_data[realm] = realm_data
                await asyncio.sleep(0.1)

            # Combine character and server data
            all_data["servers"] = server_data
            all_data["last_update"] = self.last_update_success

            return all_data

        except Exception as err:
            raise UpdateFailed(f"Error communicating with API: {err}")


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up WoW Blizzard sensors based on a config entry."""
    client_id = entry.data[CONF_CLIENT_ID]
    client_secret = entry.data[CONF_CLIENT_SECRET]
    region = entry.data[CONF_REGION]
    characters = entry.data.get(CONF_CHARACTERS, [])
    
    # Feature flags
    features = {
        CONF_ENABLE_SERVER_STATUS: entry.data.get(CONF_ENABLE_SERVER_STATUS, True),
        CONF_ENABLE_PVP: entry.data.get(CONF_ENABLE_PVP, True),
        CONF_ENABLE_RAIDS: entry.data.get(CONF_ENABLE_RAIDS, True),
        CONF_ENABLE_MYTHIC_PLUS: entry.data.get(CONF_ENABLE_MYTHIC_PLUS, True),
    }

    if not characters:
        _LOGGER.error("No characters configured")
        return

    client = WoWBlizzardAPIClient(client_id, client_secret, region)
    coordinator = WoWDataUpdateCoordinator(hass, client, characters, features)

    # Fetch initial data
    await coordinator.async_config_entry_first_refresh()

    # Create sensors
    entities = []
    
    # Character sensors
    for character in characters:
        realm = character["realm"]
        name = character["character_name"]
        char_key = f"{realm}-{name}"
        
        # Basic character sensors (always enabled)
        for sensor_type in BASIC_SENSOR_TYPES:
            entities.append(
                WoWCharacterSensor(coordinator, sensor_type, char_key, name, realm)
            )
        
        # PvP sensors
        if features[CONF_ENABLE_PVP]:
            for sensor_type in PVP_SENSOR_TYPES:
                entities.append(
                    WoWCharacterSensor(coordinator, sensor_type, char_key, name, realm)
                )
        
        # Raid sensors
        if features[CONF_ENABLE_RAIDS]:
            for sensor_type in RAID_SENSOR_TYPES:
                entities.append(
                    WoWCharacterSensor(coordinator, sensor_type, char_key, name, realm)
                )
        
        # Mythic+ sensors
        if features[CONF_ENABLE_MYTHIC_PLUS]:
            for sensor_type in MYTHICPLUS_SENSOR_TYPES:
                entities.append(
                    WoWCharacterSensor(coordinator, sensor_type, char_key, name, realm)
                )

    # Server sensors
    if features[CONF_ENABLE_SERVER_STATUS]:
        realms = set(char["realm"] for char in characters)
        for realm in realms:
            for sensor_type in SERVER_SENSOR_TYPES:
                entities.append(
                    WoWServerSensor(coordinator, sensor_type, realm)
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
        realm: str
    ):
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._sensor_type = sensor_type
        self._char_key = char_key
        self._character_name = character_name
        self._realm = realm
        
        sensor_config = ALL_SENSOR_TYPES[sensor_type]
        
        self._attr_name = f"{character_name} {sensor_config['name']}"
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
        return {
            "identifiers": {(DOMAIN, f"{self._realm}_{self._character_name}")},
            "name": f"{self._character_name} ({self._realm})",
            "manufacturer": "Blizzard Entertainment",
            "model": "World of Warcraft Character",
            "sw_version": "The War Within",
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
        
        self._attr_name = f"{realm.title()} {sensor_config['name']}"
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