"""Support for WoW Blizzard API sensors with all features."""
import asyncio
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, List, Optional

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.device_registry import DeviceEntryType
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.storage import Store
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
    CONF_REALM,
    CONF_CHARACTER_NAME,
    CONF_CHARACTERS,
    CONF_ENABLE_SERVER_STATUS,
    CONF_ENABLE_PVP,
    CONF_ENABLE_RAIDS,
    CONF_ENABLE_MYTHIC_PLUS,
    CONF_ENABLE_HALL_OF_FAME,
    CONF_ENABLE_CHARACTER_DETAILS,
    CONF_ENABLE_COLLECTIONS,
    CONF_ENABLE_GUILD,
    CONF_ENABLE_REGION_DATA,
    CONF_ENABLE_MYTHIC_LEADERBOARD,
    CONF_AUCTION_ITEMS,
    CONF_ACCOUNT_TOKEN,
    FEATURE_DEFAULTS,
    CONF_GAME_VERSION,
    CONF_LOCALE,
    CONF_NAMESPACE_SUFFIX,
    ALL_SENSOR_TYPES,
    SERVER_SENSOR_TYPES,
    PVP_SENSOR_TYPES,
    RAID_SENSOR_TYPES,
    MYTHICPLUS_SENSOR_TYPES,
    DETAIL_SENSOR_TYPES,
    COLLECTION_SENSOR_TYPES,
    GUILD_SENSOR_TYPES,
    REGION_SENSOR_TYPES,
    ACCOUNT_CHARACTER_SENSOR_TYPES,
    ACCOUNT_SENSOR_TYPES,
    REALM_LEADERBOARD_SENSOR_TYPES,
    AUCTION_SENSOR_TYPES,
    HOF_SENSOR_TYPES,
    DEFAULT_SCAN_INTERVAL,
    SLOW_REFRESH_INTERVAL,
    GUILD_REFRESH_INTERVAL,
    AUCTION_REFRESH_INTERVAL,
    LEADERBOARD_REFRESH_INTERVAL,
    PVP_SEASON_REFRESH_INTERVAL,
    ACCOUNT_REFRESH_INTERVAL,
    CLASS_COLORS,
    ITEM_QUALITY_COLORS,
    GAME_VERSIONS,
    get_sensor_types_for_version,
)
from .api_client import WoWBlizzardAPIClient, UserTokenExpired
from .parsers import (
    COLLECTION_ENDPOINTS,
    HUNTER_CLASS_ID,
    _guild_path,
    _merge,
    bracket_slug,
    parse_account_characters,
    parse_guild_activity,
    parse_mythic_leaderboard,
    parse_pvp_rewards,
    summarize_auctions,
    parse_achievement_statistics,
    parse_dungeons,
    parse_hunter_pets,
    parse_professions,
    parse_reputations,
    parse_statistics,
    parse_talents,
)

_LOGGER = logging.getLogger(__name__)

# Blizzard difficulty types (stable, unlike the localized difficulty names)
RAID_DIFFICULTY_SENSORS = {
    "LFR": "raid_progress_lfr",
    "NORMAL": "raid_progress_normal",
    "HEROIC": "raid_progress_heroic",
    "MYTHIC": "raid_progress_mythic",
}

# Hall of Fame list sizes: split faction lists hold 100 guilds, unified lists 200
HOF_FULL_SPLIT = 100
HOF_FULL_UNIFIED = 200

def assign_character_keys(characters: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Give every configured character a unique data/entity key.

    The first character with a given realm and name keeps the historic
    "{realm}-{name}" key so existing entity IDs stay stable. A later character
    with the same realm and name in another game version (e.g. "Mograine" in
    Classic Era and Anniversary) gets the game version appended.
    """
    seen = set()
    result = []
    for char in characters:
        game_version = char.get(CONF_GAME_VERSION, "retail")
        base = f"{char[CONF_REALM]}-{char[CONF_CHARACTER_NAME]}"
        key = base if base not in seen else f"{base}-{game_version}"
        seen.add(base)
        result.append({**char, CONF_GAME_VERSION: game_version, "key": key})
    return result


def assign_realm_keys(characters: List[Dict[str, Any]]) -> Dict[str, Dict[str, str]]:
    """Map a unique key to every (realm, game version) pair, first one unsuffixed."""
    realms: Dict[str, Dict[str, str]] = {}
    seen_pairs = set()
    for char in characters:
        realm = char[CONF_REALM]
        game_version = char[CONF_GAME_VERSION]
        if (realm, game_version) in seen_pairs:
            continue
        seen_pairs.add((realm, game_version))
        key = realm if realm not in realms else f"{realm}-{game_version}"
        realms[key] = {"realm": realm, "game_version": game_version}
    return realms


def _format_timestamp(timestamp_ms: Optional[int]) -> Optional[str]:
    """Format a Blizzard millisecond timestamp as UTC string."""
    if not timestamp_ms:
        return None
    try:
        dt = datetime.fromtimestamp(float(timestamp_ms) / 1000, timezone.utc)
        return dt.strftime("%Y-%m-%d %H:%M:%S UTC")
    except (TypeError, ValueError, OverflowError):
        return None


class WoWDataUpdateCoordinator(DataUpdateCoordinator):
    """Class to manage fetching all WoW data from the API."""

    def __init__(
        self,
        hass: HomeAssistant,
        client: WoWBlizzardAPIClient,
        characters: List[Dict[str, Any]],
        features: Dict[str, bool],
        auction_items: Optional[List[int]] = None,
        account_token: Optional[Dict[str, Any]] = None,
    ):
        """Initialize."""
        self.client = client
        self.auction_items = list(auction_items or [])
        # Player's Battle.net login ({"access_token", "expires_at"}), optional
        self.account_token = account_token or {}
        self.characters = assign_character_keys(characters)
        self.features = features
        self.realms = assign_realm_keys(self.characters)
        self.has_retail = any(c[CONF_GAME_VERSION] == "retail" for c in self.characters)
        self.has_classic_progression = any(c[CONF_GAME_VERSION] == "classic" for c in self.characters)

        # Cache for dynamic raid discovery and Hall of Fame leaderboards
        self._cached_raids = None
        self._last_raids_fetch = None
        self._hof_cache = {}
        # Slowly changing data: char_key -> (last login, fetch time, data);
        # guild path -> (fetch time, data); current weekly period
        self._slow_cache: Dict[str, Any] = {}
        self._guild_cache: Dict[str, Any] = {}
        self._period: Dict[str, Any] = {}
        # Current PvP season with title cutoffs, English spec slugs per spec ID
        self._pvp_season: Dict[str, Any] = {}
        self._spec_slugs: Dict[int, str] = {}
        # Connected realm ID per (realm, game version); icons per (version, item ID)
        self._connected_realms: Dict[Any, int] = {}
        self._item_icons: Dict[Any, Optional[str]] = {}
        self._item_names: Dict[Any, Optional[str]] = {}
        # Hourly data: (fetch time, data)
        self._leaderboard_cache: Optional[Any] = None
        self._auction_cache: Optional[Any] = None
        self._account_cache: Optional[Any] = None
        self._guild_activity: Dict[str, List[Dict[str, Any]]] = {}
        self.account_expired = False
        # Last good account values and where they are kept across restarts
        self._account_last: Dict[str, Any] = {}
        self._account_store = None
        self.entry_id: Optional[str] = None

        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=DEFAULT_SCAN_INTERVAL),
        )

    def _previous(self, key: str) -> Dict[str, Any]:
        """Last successfully fetched data for a key."""
        if self.data and isinstance(self.data.get(key), dict):
            return self.data[key]
        return {}

    async def _fetch_basic_character_data(self, realm: str, character_name: str, game_version: str = "retail") -> Dict[str, Any]:
        """Fetch basic character data."""
        try:
            profile = await self.client.get_character_profile(realm, character_name, game_version=game_version)
            if not profile:
                # API hiccup or character temporarily unavailable: do not report 0
                return {}

            # Determine which sensors this version supports
            version_sensors = get_sensor_types_for_version(game_version)
            supported_basic = version_sensors["basic"]

            # Get guild information
            guild_name = None
            guild_path = None
            if profile.get("guild"):
                guild_name = profile["guild"].get("name")
                guild_path = _guild_path(profile["guild"])

            # Fetch character media (avatar & full-body render)
            avatar_url = None
            full_body_url = None
            try:
                media = await self.client.get_character_media(realm, character_name, game_version=game_version)
                assets = {
                    asset.get("key"): asset.get("value")
                    for asset in (media or {}).get("assets") or []
                    if isinstance(asset, dict)
                }
                avatar_url = assets.get("avatar")
                full_body_url = assets.get("main-raw") or assets.get("main") or assets.get("inset") or avatar_url
            except Exception as media_err:
                _LOGGER.debug(f"Could not fetch media for {character_name}-{realm}: {media_err}")

            equipment = await self.client.get_character_equipment(realm, character_name, game_version=game_version)
            equipped_items_list = self._parse_equipment(equipment)
            for item in equipped_items_list:
                item["icon"] = await self._item_icon(item.get("media_id"), game_version)

            character_class = profile.get("character_class") or {}
            result = {
                "character_status": "valid",
                "character_level": profile.get("level"),
                "guild_name": guild_name,
                "guild_path": guild_path,
                # Titles are templates like "%s, Liberator of Orgrimmar"
                "active_title": (
                    ((profile.get("active_title") or {}).get("name") or "").replace("%s", profile.get("name") or "").strip()
                    or None
                ),
                "last_login_timestamp": profile.get("last_login_timestamp"),
                "character_class": character_class.get("name"),
                "character_class_id": character_class.get("id"),
                "character_race": (profile.get("race") or {}).get("name"),
                "realm": (profile.get("realm") or {}).get("name"),
                "faction": (profile.get("faction") or {}).get("name"),
                "gender": (profile.get("gender") or {}).get("name"),
                "spec": (profile.get("active_spec") or {}).get("name"),
                "spec_id": (profile.get("active_spec") or {}).get("id"),
                "faction_type": (profile.get("faction") or {}).get("type"),
                "avatar_url": avatar_url,
                "full_body_url": full_body_url,
                "character_equipment": len(equipped_items_list),
                "equipped_items": {item["slot_type"].lower(): item for item in equipped_items_list},
                "equipped_items_list": equipped_items_list,
            }

            # Only include values for sensors this version supports
            if "character_item_level" in supported_basic:
                result["character_item_level"] = profile.get("equipped_item_level")
            if "achievement_points" in supported_basic:
                # The profile carries the total; the achievements endpoint is >1 MB
                result["achievement_points"] = profile.get("achievement_points")

            return result

        except Exception as err:
            _LOGGER.error(f"Error fetching basic data for {character_name}-{realm}: {err}")
            return {}

    @staticmethod
    def _parse_equipment(equipment: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Flatten the equipment endpoint into one entry per slot."""
        items = []
        for item in (equipment or {}).get("equipped_items") or []:
            if not isinstance(item, dict):
                continue
            slot = item.get("slot") or {}
            quality = item.get("quality") or {}
            slot_type = slot.get("type", "UNKNOWN")
            quality_type = (quality.get("type") or "").upper()

            stats = {}
            for stat in item.get("stats") or []:
                if isinstance(stat, dict):
                    stat_type = (stat.get("type") or {}).get("name") or (stat.get("type") or {}).get("type")
                    if stat_type:
                        stats[stat_type] = stat.get("value", 0)

            items.append({
                "slot": slot.get("name", slot_type.title()),
                "slot_type": slot_type,
                "name": item.get("name", "Unknown Item"),
                "item_id": (item.get("item") or {}).get("id"),
                "media_id": (item.get("media") or {}).get("id"),
                "item_level": (item.get("level") or {}).get("value", 0),
                "quality": quality.get("name", quality_type.title()),
                "quality_color": ITEM_QUALITY_COLORS.get(quality_type, "#FFFFFF"),
                "stats": stats,
            })
        return items

    async def _fetch_server_data(self, realm: str, game_version: str = "retail") -> Dict[str, Any]:
        """Fetch server status data."""
        if not self.features.get(CONF_ENABLE_SERVER_STATUS, False):
            return {}

        try:
            realm_info = await self.client.get_realm_info(realm, game_version=game_version)
            if not realm_info:
                return {}
            connected_realm = await self.client.get_connected_realm(realm, game_version=game_version, realm_info=realm_info)
            if not connected_realm:
                return {}

            status = connected_realm.get("status") or {}
            population = connected_realm.get("population") or {}

            return {
                "realm_status": status.get("name", "Unknown"),
                "realm_status_type": status.get("type"),
                "realm_population": population.get("name", "Unknown"),
                "realm_population_type": population.get("type"),
                # The API only exposes whether a queue exists, not its length
                "realm_queue": bool(connected_realm.get("has_queue", False)),
                "realm_timezone": realm_info.get("timezone", "Unknown"),
                "realm_locale": realm_info.get("locale", "Unknown"),
            }

        except Exception as err:
            _LOGGER.error(f"Error fetching server data for {realm}: {err}")
            return {}

    async def _spec_bracket_slug(self, spec_id: Optional[int]) -> Optional[str]:
        """English "class-spec" slug for Solo Shuffle and Blitz brackets, cached per spec."""
        if not isinstance(spec_id, int):
            return None
        if spec_id not in self._spec_slugs:
            spec = await self.client.get_specialization_en(spec_id)
            if not spec:
                return None
            self._spec_slugs[spec_id] = bracket_slug(
                (spec.get("playable_class") or {}).get("name"), spec.get("name")
            )
        return self._spec_slugs[spec_id]

    async def _fetch_pvp_data(self, realm: str, character_name: str, game_version: str = "retail", basic: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Fetch PvP data for a character."""
        version_sensors = get_sensor_types_for_version(game_version)
        supported_pvp = version_sensors["pvp"]

        if not self.features.get(CONF_ENABLE_PVP, False) or not supported_pvp:
            return {}
        basic = basic or {}

        try:
            # Sensor -> bracket, only for brackets this version supports
            brackets = {
                "pvp_2v2_rating": "2v2",
                "pvp_3v3_rating": "3v3",
                "pvp_rbg_rating": "rbg",
            }
            if {"pvp_shuffle_rating", "pvp_blitz_rating"} & set(supported_pvp):
                # Solo Shuffle and Blitz are rated per specialization
                spec_slug = await self._spec_bracket_slug(basic.get("spec_id"))
                if spec_slug:
                    brackets["pvp_shuffle_rating"] = f"shuffle-{spec_slug}"
                    brackets["pvp_blitz_rating"] = f"blitz-{spec_slug}"
            brackets = {s: b for s, b in brackets.items() if s in supported_pvp}

            summary = await self.client.get_character_pvp_summary(realm, character_name, game_version) or {}

            result: Dict[str, Any] = {}
            if "pvp_honor_level" in supported_pvp and summary:
                result["pvp_honor_level"] = summary.get("honor_level", 0)
            if "pvp_honorable_kills" in supported_pvp and summary:
                result["pvp_honorable_kills"] = summary.get("honorable_kills", 0)
            if "pvp_rank" in supported_pvp and summary:
                # Classic Era honor rank (0 = no rank)
                result["pvp_rank"] = summary.get("pvp_rank", 0)

            # Brackets report the last season the character played; older
            # seasons count as 0 for the current one (Retail only)
            current_season = (self._pvp_season.get("season") or {}).get("id") if game_version == "retail" else None
            cutoffs = self._pvp_season.get("cutoffs") or {}
            faction = (basic.get("faction_type") or "").lower()

            wins_season = 0
            for sensor, bracket in brackets.items():
                data = await self.client.get_character_pvp_bracket(realm, character_name, bracket, game_version)
                await asyncio.sleep(0.1)
                if not data or "rating" not in data:
                    continue
                season_id = (data.get("season") or {}).get("id")
                stale = current_season is not None and season_id != current_season
                season_stats = {} if stale else (data.get("season_match_statistics") or {})
                weekly_stats = {} if stale else (data.get("weekly_match_statistics") or {})
                result[sensor] = 0 if stale else data["rating"]
                wins_season += season_stats.get("won", 0)

                attrs = {
                    "rating_season_id": season_id,
                    "last_season_rating": data["rating"] if stale else None,
                    "season_played": season_stats.get("played", 0),
                    "season_won": season_stats.get("won", 0),
                    "season_lost": season_stats.get("lost", 0),
                    "weekly_played": weekly_stats.get("played", 0),
                    "weekly_won": weekly_stats.get("won", 0),
                }
                if sensor == "pvp_3v3_rating":
                    attrs["gladiator_cutoff"] = cutoffs.get("gladiator")
                elif sensor == "pvp_rbg_rating":
                    attrs["hero_cutoff"] = (cutoffs.get("hero") or {}).get(faction)
                elif sensor == "pvp_shuffle_rating":
                    attrs["legend_cutoff"] = (cutoffs.get("shuffle") or {}).get(basic.get("spec_id"))
                elif sensor == "pvp_blitz_rating":
                    blitz = (cutoffs.get("blitz") or {}).get(basic.get("spec_id")) or {}
                    attrs["legend_cutoff"] = blitz.get(faction) or blitz.get("all")
                result.setdefault("attrs", {})[sensor] = attrs

            if "pvp_wins_season" in supported_pvp:
                result["pvp_wins_season"] = wins_season

            return result

        except Exception as err:
            _LOGGER.error(f"Error fetching PvP data for {character_name}-{realm}: {err}")
            return {}

    async def _fetch_raid_data(self, realm: str, character_name: str, game_version: str = "retail") -> Dict[str, Any]:
        """Fetch raid progress data.

        Difficulty sensors count bosses defeated in the raids of the current
        (newest) expansion. raid_kills_total counts bosses defeated across all
        raids the character has ever entered.
        """
        version_sensors = get_sensor_types_for_version(game_version)
        supported_raid = version_sensors["raid"]

        if not self.features.get(CONF_ENABLE_RAIDS, False) or not supported_raid:
            return {}

        try:
            encounters = await self.client.get_character_encounters_raids(realm, character_name, game_version=game_version)
            if not encounters:
                return {}

            expansions = encounters.get("expansions", [])
            current = max(
                expansions,
                key=lambda e: (e.get("expansion") or {}).get("id", 0),
                default=None,
            )

            progress = {sensor: 0 for sensor in RAID_DIFFICULTY_SENSORS.values()}
            totals = {sensor: 0 for sensor in RAID_DIFFICULTY_SENSORS.values()}
            raids_detail = {}
            # Current raids are listed twice (their expansion and the
            # "Current Season" group), so count each raid/difficulty once
            kills_by_mode = {}

            for expansion in expansions:
                is_current = expansion is current
                for instance in expansion.get("instances", []):
                    instance_name = (instance.get("instance") or {}).get("name")
                    instance_id = (instance.get("instance") or {}).get("id", instance_name)
                    for mode in instance.get("modes", []):
                        difficulty_type = (mode.get("difficulty") or {}).get("type", "")
                        mode_progress = mode.get("progress") or {}
                        completed = mode_progress.get("completed_count", 0)
                        mode_key = (instance_id, difficulty_type)
                        kills_by_mode[mode_key] = max(kills_by_mode.get(mode_key, 0), completed)

                        sensor = RAID_DIFFICULTY_SENSORS.get(difficulty_type)
                        if not is_current or sensor is None:
                            continue
                        progress[sensor] += completed
                        totals[sensor] += mode_progress.get("total_count", 0)
                        if instance_name:
                            raids_detail.setdefault(instance_name, {})[difficulty_type.lower()] = (
                                f"{completed}/{mode_progress.get('total_count', 0)}"
                            )

            result = {}
            for sensor in RAID_DIFFICULTY_SENSORS.values():
                if sensor in supported_raid:
                    result[sensor] = progress[sensor]
            if "raid_kills_total" in supported_raid:
                result["raid_kills_total"] = sum(kills_by_mode.values())
            result["raid_expansion"] = ((current or {}).get("expansion") or {}).get("name")
            result["raid_total_bosses"] = totals
            result["raid_details"] = raids_detail

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
            season_data = await self.client.get_character_mythicplus_season(realm, character_name, profile=profile)

            score = 0
            best_run = 0
            runs_completed = 0
            runs_timed = 0
            weekly_best = 0

            # Get current season data
            if season_data:
                # The API only returns the best run per dungeon (and affix week)
                best_runs = season_data.get("best_runs", [])
                if best_runs:
                    best_run = max(run.get("keystone_level", 0) for run in best_runs)
                runs_completed = len(best_runs)
                runs_timed = sum(1 for run in best_runs if run.get("is_completed_within_time", False))

                # Use Blizzard score directly
                score = season_data.get("mythic_rating", {}).get("rating", 0)
            elif profile:
                score = profile.get("current_mythic_rating", {}).get("rating", 0)

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

    async def _fetch_character_status(self, realm: str, character_name: str, game_version: str) -> Optional[str]:
        """Check why a profile is missing: "not_found", "invalid" or None (API hiccup)."""
        status = await self.client.get_character_resource(realm, character_name, "status", game_version)
        if status:
            return "valid" if status.get("is_valid", True) else "invalid"
        if self.client.last_status == 404:
            return "not_found"
        return None

    async def _fetch_details_data(self, realm: str, character_name: str, game_version: str, class_id: Optional[int]) -> Dict[str, Any]:
        """Fetch professions, stats, titles, reputations, talents, dungeons and more."""
        supported = get_sensor_types_for_version(game_version)["details"]
        if not self.features.get(CONF_ENABLE_CHARACTER_DETAILS, False) or not supported:
            return {}

        # (endpoint, parser, sensors that need it)
        sources = [
            ("statistics", parse_statistics, {"stat_health", "stat_crit", "stat_haste", "stat_mastery", "stat_versatility"}),
            ("professions", parse_professions, {"professions"}),
            ("reputations", parse_reputations, {"reputations"}),
            ("specializations", parse_talents, {"talents"}),
            ("encounters/dungeons", parse_dungeons, {"dungeons_completed"}),
            ("achievements/statistics", parse_achievement_statistics, {"deaths", "quests_completed"}),
        ]
        if class_id == HUNTER_CLASS_ID:
            sources.append(("hunter-pets", parse_hunter_pets, {"hunter_pet"}))

        result: Dict[str, Any] = {}
        for resource, parser, sensors in sources:
            if not sensors & set(supported):
                continue
            data = await self.client.get_character_resource(realm, character_name, resource, game_version)
            _merge(result, parser(data))
            await asyncio.sleep(0.1)

        # Retail lists all earned titles; the active one comes with the profile
        if game_version == "retail" and "active_title" in supported:
            titles = await self.client.get_character_resource(realm, character_name, "titles", game_version)
            if titles:
                result.setdefault("attrs", {})["active_title"] = {"title_count": len(titles.get("titles") or [])}
        return result

    async def _fetch_collections_data(self, realm: str, character_name: str, game_version: str) -> Dict[str, Any]:
        """Fetch the number of collected mounts, pets, toys and heirlooms."""
        supported = get_sensor_types_for_version(game_version)["collections"]
        if not self.features.get(CONF_ENABLE_COLLECTIONS, False) or not supported:
            return {}
        result = {}
        for sensor, (resource, list_key) in COLLECTION_ENDPOINTS.items():
            if sensor not in supported:
                continue
            data = await self.client.get_character_resource(realm, character_name, resource, game_version)
            if data:
                result[sensor] = len(data.get(list_key) or [])
            await asyncio.sleep(0.1)
        return result

    async def _fetch_slow_character_data(self, char_key: str, realm: str, character_name: str, game_version: str, basic: Dict[str, Any]) -> Dict[str, Any]:
        """Details and collections, refetched after a new login or every few hours."""
        last_login = basic.get("last_login_timestamp")
        now = datetime.now()
        cached = self._slow_cache.get(char_key)
        if cached and cached[0] == last_login and now - cached[1] < timedelta(seconds=SLOW_REFRESH_INTERVAL):
            return cached[2]

        data: Dict[str, Any] = {}
        _merge(data, await self._fetch_details_data(realm, character_name, game_version, basic.get("character_class_id")))
        _merge(data, await self._fetch_collections_data(realm, character_name, game_version))
        if not data and cached:
            # Everything failed, keep the old values and retry next update
            return cached[2]
        self._slow_cache[char_key] = (last_login, now, data)
        return data

    async def _fetch_guild_data(self, guild_path: Optional[str], game_version: str) -> Dict[str, Any]:
        """Fetch guild member count and achievement points, cached per guild."""
        if not self.features.get(CONF_ENABLE_GUILD, False) or not guild_path:
            return {}
        if not get_sensor_types_for_version(game_version)["guild"]:
            return {}

        cache_key = f"{game_version}:{guild_path}"
        now = datetime.now()
        cached = self._guild_cache.get(cache_key)
        if cached and now - cached[0] < timedelta(seconds=GUILD_REFRESH_INTERVAL):
            return cached[1]

        guild = await self.client.get_guild(guild_path, game_version)
        if not guild:
            return cached[1] if cached else {}
        data = {
            "guild_members": guild.get("member_count"),
            "attrs": {"guild_members": {
                "guild": guild.get("name"),
                "guild_realm": (guild.get("realm") or {}).get("name"),
                "guild_faction": (guild.get("faction") or {}).get("name"),
                "guild_achievement_points": guild.get("achievement_points"),
                "guild_created": _format_timestamp(guild.get("created_timestamp")),
            }},
        }
        # Recent achievements and boss kills, shown as events
        activity = await self.client.get_guild_activity(guild_path, game_version)
        if activity:
            self._guild_activity[cache_key] = parse_guild_activity(activity)
        data["guild_key"] = cache_key
        self._guild_cache[cache_key] = (now, data)
        return data

    async def _fetch_region_data(self) -> Dict[str, Any]:
        """Fetch WoW Token prices and the weekly reset for the region."""
        if not self.features.get(CONF_ENABLE_REGION_DATA, False):
            return {}
        result: Dict[str, Any] = {}
        for sensor, game_version, enabled in (
            ("wow_token_price", "retail", self.has_retail),
            ("wow_token_price_classic", "classic", self.has_classic_progression),
        ):
            if not enabled:
                continue
            token = await self.client.get_wow_token(game_version)
            if isinstance(token.get("price"), int):
                # Price is in copper: 1 gold = 100 silver = 10,000 copper
                result[sensor] = token["price"] // 10000
                result.setdefault("attrs", {})[sensor] = {
                    "last_updated": _format_timestamp(token.get("last_updated_timestamp")),
                }

        if self.has_retail:
            now_ms = datetime.now(timezone.utc).timestamp() * 1000
            if not self._period or now_ms > (self._period.get("end_timestamp") or 0):
                self._period = await self.client.get_current_keystone_period() or self._period
            end = self._period.get("end_timestamp")
            if isinstance(end, int):
                # The period ends one second before the reset
                result["weekly_reset"] = end + 1000
                result.setdefault("attrs", {})["weekly_reset"] = {
                    "period_id": self._period.get("id"),
                    "period_start": _format_timestamp(self._period.get("start_timestamp")),
                }
        return result

    async def _item_icon(self, media_id: Optional[int], game_version: str) -> Optional[str]:
        """Icon URL of an item, cached for the runtime (icons only change with patches)."""
        if not isinstance(media_id, int):
            return None
        key = ("retail" if game_version == "retail" else "classic", media_id)
        if key not in self._item_icons:
            media = await self.client.get_item_media(media_id, game_version)
            if not media:
                # Do not cache failures, retry on the next update
                return None
            assets = {a.get("key"): a.get("value") for a in media.get("assets") or [] if isinstance(a, dict)}
            self._item_icons[key] = assets.get("icon")
        return self._item_icons[key]

    async def _item_name(self, item_id: int, game_version: str) -> Optional[str]:
        """Localized item name, cached for the runtime."""
        key = (game_version, item_id)
        if key not in self._item_names:
            item = await self.client.get_item(item_id, game_version)
            if not item:
                return None
            self._item_names[key] = item.get("name")
        return self._item_names[key]

    async def _connected_realm(self, realm: str, game_version: str) -> Optional[int]:
        """Connected realm ID of a realm, cached for the runtime."""
        key = (realm, game_version)
        if key not in self._connected_realms:
            realm_info = await self.client.get_realm_info(realm, game_version=game_version)
            connected_realm_id = self.client.connected_realm_id(realm_info)
            if connected_realm_id is None:
                return None
            self._connected_realms[key] = connected_realm_id
        return self._connected_realms[key]

    @staticmethod
    def _is_fresh(cache: Optional[Any], seconds: int) -> bool:
        return cache is not None and datetime.now() - cache[0] < timedelta(seconds=seconds)

    async def _fetch_pvp_season(self) -> None:
        """Current Retail PvP season and its title cutoffs, refreshed every few hours."""
        if not self.features.get(CONF_ENABLE_PVP, False) or not self.has_retail:
            return
        fetched = self._pvp_season.get("fetched")
        if fetched and datetime.now() - fetched < timedelta(seconds=PVP_SEASON_REFRESH_INTERVAL):
            return
        season = await self.client.get_current_pvp_season()
        if not season:
            return
        rewards = await self.client.get_pvp_rewards(season["id"])
        self._pvp_season = {
            "fetched": datetime.now(),
            "season": season,
            "cutoffs": parse_pvp_rewards(rewards) if rewards else self._pvp_season.get("cutoffs", {}),
        }

    def _pvp_region_data(self) -> Dict[str, Any]:
        """Region sensors for the PvP season and its title cutoffs."""
        season = self._pvp_season.get("season")
        if not season:
            return {}
        cutoffs = self._pvp_season.get("cutoffs") or {}
        hero = cutoffs.get("hero") or {}
        return {
            "pvp_season": season.get("season_name") or season.get("id"),
            "pvp_cutoff_gladiator": cutoffs.get("gladiator"),
            "pvp_cutoff_hero": max(hero.values()) if hero else None,
            "attrs": {
                "pvp_season": {
                    "season_id": season.get("id"),
                    "season_start": _format_timestamp(season.get("season_start_timestamp")),
                },
                "pvp_cutoff_hero": {f"{faction}_cutoff": cutoff for faction, cutoff in hero.items()},
            },
        }

    async def _fetch_mythic_leaderboards(self) -> Dict[str, Any]:
        """Weekly Mythic+ leaderboards of the configured Retail realms (opt-in, hourly)."""
        if not self.features.get(CONF_ENABLE_MYTHIC_LEADERBOARD, False) or not self.has_retail:
            return {}
        if self._is_fresh(self._leaderboard_cache, LEADERBOARD_REFRESH_INTERVAL):
            return self._leaderboard_cache[1]

        # Configured Retail characters by "realm-slug/name"
        own = {
            f"{self.client.realm_to_slug(c[CONF_REALM])}/{c[CONF_CHARACTER_NAME].lower()}": c[CONF_CHARACTER_NAME]
            for c in self.characters if c[CONF_GAME_VERSION] == "retail"
        }
        result: Dict[str, Any] = {"realms": {}, "affixes": None}
        done: Dict[int, Dict[str, Any]] = {}
        for realm_key, realm in self.realms.items():
            if realm["game_version"] != "retail":
                continue
            connected_realm_id = await self._connected_realm(realm["realm"], "retail")
            if connected_realm_id is None:
                continue
            if connected_realm_id not in done:
                index = await self.client.get_mythic_leaderboard_index(connected_realm_id)
                dungeons = {}
                for board in index.get("current_leaderboards") or []:
                    match = re.search(r"mythic-leaderboard/(\d+)/period/(\d+)", (board.get("key") or {}).get("href", ""))
                    if not match:
                        continue
                    data = await self.client.get_mythic_leaderboard(connected_realm_id, int(match.group(1)), int(match.group(2)))
                    if data:
                        parsed = parse_mythic_leaderboard(data, own)
                        dungeons[parsed["dungeon"] or board.get("name")] = parsed
                    await asyncio.sleep(0.1)
                done[connected_realm_id] = dungeons
            dungeons = done[connected_realm_id]
            if not dungeons:
                continue
            levels = [d["best_level"] for d in dungeons.values() if isinstance(d.get("best_level"), int)]
            own_runs: Dict[str, Dict[str, Any]] = {}
            for name, dungeon in dungeons.items():
                for char, run in dungeon["own"].items():
                    own_runs.setdefault(char, {})[name] = run
            result["realms"][realm_key] = {
                "mythicplus_realm_best": max(levels) if levels else None,
                "dungeons": {
                    name: {"best_level": d["best_level"], "best_duration_min": d["best_duration_min"], "runs": d["runs"]}
                    for name, d in dungeons.items()
                },
                "own_characters": own_runs,
            }
            if result["affixes"] is None:
                result["affixes"] = next((d["affixes"] for d in dungeons.values() if d["affixes"]), None)

        if not result["realms"] and self._leaderboard_cache:
            return self._leaderboard_cache[1]
        self._leaderboard_cache = (datetime.now(), result)
        return result

    async def _fetch_auctions(self) -> Dict[str, Any]:
        """Lowest auction price per tracked item (hourly; Retail and Classic Progression)."""
        if not self.auction_items:
            return {}
        if self._is_fresh(self._auction_cache, AUCTION_REFRESH_INTERVAL):
            return self._auction_cache[1]

        item_ids = set(self.auction_items)
        result: Dict[str, Any] = {}
        for game_version, enabled in (("retail", self.has_retail), ("classic", self.has_classic_progression)):
            if not enabled:
                continue
            found: Dict[int, Dict[str, Any]] = {}
            if game_version == "retail":
                # Stackable goods trade region-wide as commodities
                for item_id, entry in summarize_auctions(await self.client.get_commodities(), item_ids).items():
                    found[item_id] = {**entry, "sources": {"commodities": entry["min_price"]}}
            missing = item_ids - set(found) if game_version == "retail" else item_ids
            if missing:
                realms = {realm["realm"] for realm in self.realms.values() if realm["game_version"] == game_version}
                seen = set()
                for realm in sorted(realms):
                    connected_realm_id = await self._connected_realm(realm, game_version)
                    if connected_realm_id is None or connected_realm_id in seen:
                        continue
                    seen.add(connected_realm_id)
                    auctions = await self.client.get_realm_auctions(connected_realm_id, game_version)
                    for item_id, entry in summarize_auctions(auctions, missing).items():
                        total = found.setdefault(item_id, {"min_price": None, "quantity": 0, "auctions": 0, "sources": {}})
                        total["quantity"] += entry["quantity"]
                        total["auctions"] += entry["auctions"]
                        total["sources"][realm] = entry["min_price"]
                        if entry["min_price"] is not None and (total["min_price"] is None or entry["min_price"] < total["min_price"]):
                            total["min_price"] = entry["min_price"]

            for item_id in self.auction_items:
                entry = found.get(item_id) or {"min_price": None, "quantity": 0, "auctions": 0, "sources": {}}
                result[f"{game_version}:{item_id}"] = {
                    # Copper to gold, keeping silver and copper as decimals
                    "price": round(entry["min_price"] / 10000, 4) if entry["min_price"] is not None else None,
                    "quantity": entry["quantity"],
                    "auctions": entry["auctions"],
                    "sources": {
                        source: round(price / 10000, 4) if price is not None else None
                        for source, price in entry["sources"].items()
                    },
                    "item_name": await self._item_name(item_id, game_version),
                }

        self._auction_cache = (datetime.now(), result)
        return result

    async def _fetch_account_data(self) -> Dict[str, Any]:
        """Account data from the player's Battle.net login while it is valid (optional).

        Blizzard does not hand out refresh tokens, so the login expires after
        24 hours. The last values are kept afterwards and the user can log in
        again by reconfiguring the integration.
        """
        token = (self.account_token or {}).get("access_token")
        if not token:
            return {}
        if self._is_fresh(self._account_cache, ACCOUNT_REFRESH_INTERVAL):
            return self._account_cache[1]
        expires_at = self.account_token.get("expires_at") or 0

        def keep_last(login_valid: bool) -> Dict[str, Any]:
            # Last good values (also restored after a restart), never zeros
            return {**self._account_last, "account_login": expires_at * 1000, "login_valid": login_valid}

        if datetime.now(timezone.utc).timestamp() >= expires_at:
            self.account_expired = True
            return keep_last(False)

        try:
            result = await self._fetch_account_values(token, expires_at)
        except UserTokenExpired:
            # Rejected before the expiry time, e.g. after a password change
            self.account_expired = True
            return keep_last(False)
        except Exception as err:  # noqa: BLE001 - account data must never break the update
            _LOGGER.warning("Could not fetch Battle.net account data: %s", err)
            return keep_last(True)
        if result is None:
            # Temporary API problem: keep the last values, try again next update
            return keep_last(True)

        self.account_expired = False
        self._account_last = {k: v for k, v in result.items() if k not in ("account_login", "login_valid")}
        if self._account_store is not None:
            await self._account_store.async_save(self._account_last)
        self._account_cache = (datetime.now(), result)
        return result

    async def _fetch_account_values(self, token: str, expires_at: int) -> Optional[Dict[str, Any]]:
        """Gold and collections of the logged-in account; None if the API gave no answer."""
        result: Dict[str, Any] = {"characters": {}, "account_login": expires_at * 1000, "login_valid": True}
        versions = {c[CONF_GAME_VERSION] for c in self.characters} | {"retail"}
        total_gold = 0
        account_characters = 0
        for game_version in sorted(versions):
            if game_version == "forever":
                continue
            profile = await self.client.get_account_profile(token, game_version)
            if not profile and game_version == "retail":
                return None
            characters = parse_account_characters(profile)
            if game_version == "retail":
                account_characters = len(characters)
            for char in characters:
                if not (char.get("realm_id") and char.get("id")):
                    continue
                key = f"{game_version}:{char['realm_slug']}/{(char['name'] or '').lower()}"
                protected = await self.client.get_protected_character(token, char["realm_id"], char["id"], game_version)
                money = protected.get("money")
                if not isinstance(money, int):
                    # No answer for this character: keep its last value so the total does not drop
                    last = (self._account_last.get("characters") or {}).get(key)
                    if last:
                        result["characters"][key] = last
                        if game_version == "retail":
                            total_gold += last.get("character_gold") or 0
                    continue
                gold = money // 10000
                if game_version == "retail":
                    total_gold += gold
                stats = protected.get("protected_stats") or {}
                result["characters"][key] = {
                    "character_gold": gold,
                    "attrs": {"character_gold": {
                        "total_gold_gained": (stats.get("total_gold_gained") or 0) // 10000,
                        "total_gold_lost": (stats.get("total_gold_lost") or 0) // 10000,
                        "total_deaths": stats.get("total_number_deaths"),
                        "location": ((protected.get("position") or {}).get("zone") or {}).get("name"),
                        "hearthstone": ((protected.get("bind_position") or {}).get("zone") or {}).get("name"),
                    }},
                }
                await asyncio.sleep(0.05)
        result["account_gold_total"] = total_gold
        result["account_characters"] = account_characters
        for kind, sensor, list_key in (("mounts", "account_mounts", "mounts"), ("pets", "account_pets", "pets")):
            collection = await self.client.get_account_collection(token, kind)
            if collection:
                result[sensor] = len(collection.get(list_key) or [])
            elif sensor in self._account_last:
                result[sensor] = self._account_last[sensor]
        return result

    async def _async_update_data(self):
        """Update data via library."""
        try:
            all_data = {}

            # Needed by the PvP brackets to spot ratings from older seasons
            await self._fetch_pvp_season()

            # Fetch data for each character
            for character in self.characters:
                realm = character[CONF_REALM]
                name = character[CONF_CHARACTER_NAME]
                game_version = character[CONF_GAME_VERSION]
                char_key = character["key"]

                basic_data = await self._fetch_basic_character_data(realm, name, game_version=game_version)
                if not basic_data:
                    # Keep the last known values instead of dropping to 0,
                    # but report renamed, transferred or deleted characters
                    previous = dict(self._previous(char_key))
                    status = await self._fetch_character_status(realm, name, game_version)
                    if status:
                        previous["character_status"] = status
                    all_data[char_key] = previous
                    continue

                pvp_data = await self._fetch_pvp_data(realm, name, game_version=game_version, basic=basic_data)
                raid_data = await self._fetch_raid_data(realm, name, game_version=game_version)
                mythicplus_data = await self._fetch_mythicplus_data(realm, name, game_version=game_version)
                slow_data = await self._fetch_slow_character_data(char_key, realm, name, game_version, basic_data)
                guild_data = await self._fetch_guild_data(basic_data.get("guild_path"), game_version)

                # Combine all character data
                char_data = {
                    **basic_data,
                    **pvp_data,
                    **raid_data,
                    **mythicplus_data,
                }
                # Per-sensor attributes are merged, not overwritten
                _merge(char_data, slow_data)
                _merge(char_data, guild_data)
                all_data[char_key] = char_data

                # Small delay to avoid rate limiting
                await asyncio.sleep(0.1)

            # Fetch server data for each unique realm and game version
            server_data = {}
            previous_servers = self._previous("servers")
            for realm_key, realm in self.realms.items():
                realm_data = await self._fetch_server_data(realm["realm"], game_version=realm["game_version"])
                server_data[realm_key] = realm_data or previous_servers.get(realm_key, {})
                await asyncio.sleep(0.1)

            # Hall of Fame leaderboards are Retail-only
            if self.features.get(CONF_ENABLE_HALL_OF_FAME, True) and self.has_retail:
                leaderboards = {}
                current_raids = await self._fetch_current_raids()
                for raid in current_raids:
                    raid_slug = raid["id"]
                    hof = await self._fetch_hall_of_fame_data(raid_slug)
                    leaderboards[raid_slug] = {
                        "entries": hof["entries"] if hof else [],
                        "unified": hof["unified"] if hof else True,
                        "raid_name": raid["name"],
                    }
                all_data["leaderboards"] = leaderboards

            region_data = await self._fetch_region_data()
            _merge(region_data, self._pvp_region_data())

            leaderboards = await self._fetch_mythic_leaderboards()
            all_data["mythic_leaderboards"] = leaderboards.get("realms") or {}
            if leaderboards.get("affixes"):
                region_data["mythicplus_affixes"] = ", ".join(a["name"] for a in leaderboards["affixes"] if a.get("name"))
                region_data.setdefault("attrs", {})["mythicplus_affixes"] = {"affixes": leaderboards["affixes"]}
            all_data["region"] = region_data or self._previous("region")

            all_data["auctions"] = await self._fetch_auctions() or self._previous("auctions")
            all_data["guild_activity"] = dict(self._guild_activity)

            account = await self._fetch_account_data()
            if self.hass is not None:
                # Optional login: point to "Reconfigure" instead of failing the integration
                if self.account_token and self.account_expired:
                    ir.async_create_issue(
                        self.hass, DOMAIN, account_issue_id(self.entry_id),
                        is_fixable=False, severity=ir.IssueSeverity.WARNING,
                        translation_key="account_login_expired",
                    )
                else:
                    ir.async_delete_issue(self.hass, DOMAIN, account_issue_id(self.entry_id))
            if account:
                all_data["account"] = account
                for character in self.characters:
                    key = f"{character[CONF_GAME_VERSION]}:{self.client.realm_to_slug(character[CONF_REALM])}/{character[CONF_CHARACTER_NAME].lower()}"
                    if key in (account.get("characters") or {}) and character["key"] in all_data:
                        char_data = dict(all_data[character["key"]])
                        _merge(char_data, account["characters"][key])
                        all_data[character["key"]] = char_data

            # Combine character and server data
            all_data["servers"] = server_data
            all_data["last_update"] = self.last_update_success

            return all_data

        except Exception as err:
            raise UpdateFailed(f"Error communicating with API: {err}")

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
                expansions_data = data["data"].get("MythicRaidLeaderboardExpansions") or {}
                expansions = expansions_data.get("expansions", [])

                raids = []
                if expansions:
                    latest_exp = expansions[0]
                    _LOGGER.debug(f"Latest expansion detected dynamically: {latest_exp.get('name')}")
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

    async def _fetch_hall_of_fame_data(self, raid_slug: str) -> Optional[Dict[str, Any]]:
        """Fetch Hall of Fame data for a raid, using cache."""
        now = datetime.now()

        if raid_slug in self._hof_cache:
            fetch_time, cached = self._hof_cache[raid_slug]
            if cached is not None:
                # A full leaderboard no longer changes, keep it for the runtime
                full_size = HOF_FULL_UNIFIED if cached["unified"] else HOF_FULL_SPLIT
                if len(cached["entries"]) >= full_size:
                    return cached
            # Otherwise refresh every 2 hours during progression (or after a miss)
            if now - fetch_time < timedelta(hours=2):
                return cached

        try:
            # Faction is only used for old split leaderboards; unified lists ignore it
            hof_data = await self.client.get_hall_of_fame(raid_slug, "horde")
            if hof_data and "entries" in hof_data:
                self._hof_cache[raid_slug] = (now, hof_data)
                return hof_data

            # Empty dictionary indicates 404/not found
            self._hof_cache[raid_slug] = (now, None)
            return None
        except Exception as err:
            _LOGGER.debug(f"Could not retrieve Hall of Fame for {raid_slug}: {err}")
            self._hof_cache[raid_slug] = (now, None)
            return None


def account_issue_id(entry_id: Optional[str]) -> str:
    """Repair issue shown while the Battle.net login of a config entry is expired."""
    return f"account_login_expired_{entry_id}"


def account_store_key(entry_id: str) -> str:
    """Storage key for the last account values of a config entry."""
    return f"{DOMAIN}.{entry_id}.account"


def parse_item_ids(value: Any) -> List[int]:
    """Item IDs from a comma or space separated string, e.g. "210796, 224025"."""
    ids = []
    for part in re.split(r"[,;\s]+", str(value or "")):
        if part.isdigit() and int(part) not in ids:
            ids.append(int(part))
    return ids


async def async_create_coordinator(hass: HomeAssistant, entry: ConfigEntry) -> WoWDataUpdateCoordinator:
    """Create the shared coordinator for a config entry and fetch initial data."""
    characters = entry.data.get(CONF_CHARACTERS, [])

    # Feature flags from options with data as fallback
    features = {
        key: entry.options.get(key, entry.data.get(key, default))
        for key, default in FEATURE_DEFAULTS.items()
    }
    auction_items = parse_item_ids(entry.options.get(CONF_AUCTION_ITEMS, entry.data.get(CONF_AUCTION_ITEMS, "")))

    client = WoWBlizzardAPIClient(
        entry.data[CONF_CLIENT_ID],
        entry.data[CONF_CLIENT_SECRET],
        entry.data[CONF_REGION],
        locale=entry.data.get(CONF_LOCALE),
        session=async_get_clientsession(hass),
    )
    # Apply namespaces that were resolved while adding characters (e.g. WoW Forever)
    for character in characters:
        suffix = character.get(CONF_NAMESPACE_SUFFIX)
        if suffix is not None:
            client.set_namespace_suffix(character.get(CONF_GAME_VERSION, "retail"), suffix)

    coordinator = WoWDataUpdateCoordinator(
        hass, client, characters, features,
        auction_items=auction_items,
        account_token=entry.data.get(CONF_ACCOUNT_TOKEN),
    )
    coordinator.entry_id = entry.entry_id
    account_store = Store(hass, 1, account_store_key(entry.entry_id))
    if coordinator.account_token:
        # Gold etc. keep their last value across restarts while the login is expired
        coordinator._account_store = account_store
        coordinator._account_last = await account_store.async_load() or {}
    else:
        # Login removed: forget the stored account values
        await account_store.async_remove()
    await coordinator.async_config_entry_first_refresh()
    return coordinator


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up WoW Blizzard sensors based on a config entry."""
    coordinator: WoWDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    features = coordinator.features

    # Create sensors
    entities = []

    # Character sensors
    for character in coordinator.characters:
        realm = character[CONF_REALM]
        name = character[CONF_CHARACTER_NAME]
        game_version = character[CONF_GAME_VERSION]
        char_key = character["key"]

        # Get the sensor types applicable to this game version
        version_sensors = get_sensor_types_for_version(game_version)
        sensor_types = list(version_sensors["basic"])
        if features[CONF_ENABLE_PVP]:
            sensor_types += list(version_sensors["pvp"])
        if features[CONF_ENABLE_RAIDS]:
            sensor_types += list(version_sensors["raid"])
        if features[CONF_ENABLE_MYTHIC_PLUS]:
            sensor_types += list(version_sensors["mythicplus"])
        if features[CONF_ENABLE_CHARACTER_DETAILS]:
            char_data = (coordinator.data or {}).get(char_key) or {}
            sensor_types += [
                key for key in version_sensors["details"]
                # Only hunters have pets
                if key != "hunter_pet" or char_data.get("character_class_id") == HUNTER_CLASS_ID
            ]
        if features[CONF_ENABLE_COLLECTIONS]:
            sensor_types += list(version_sensors["collections"])
        if features[CONF_ENABLE_GUILD] and ((coordinator.data or {}).get(char_key) or {}).get("guild_path"):
            # Guild sensors only for characters in a guild (reload after joining one)
            sensor_types += list(version_sensors["guild"])
        if coordinator.account_token and game_version != "forever":
            # Gold needs the player's Battle.net login
            sensor_types += list(ACCOUNT_CHARACTER_SENSOR_TYPES)

        for sensor_type in sensor_types:
            entities.append(
                WoWCharacterSensor(coordinator, sensor_type, char_key, name, realm, game_version)
            )

    # Server sensors
    if features[CONF_ENABLE_SERVER_STATUS]:
        for realm_key, realm in coordinator.realms.items():
            for sensor_type in SERVER_SENSOR_TYPES:
                entities.append(
                    WoWServerSensor(coordinator, sensor_type, realm_key, realm["realm"], realm["game_version"])
                )

    # Hall of Fame Leaderboard sensors (Retail only)
    if features[CONF_ENABLE_HALL_OF_FAME] and coordinator.has_retail:
        for raid in coordinator._cached_raids or []:
            entities.append(
                WoWLeaderboardSensor(coordinator, "hall_of_fame", raid["id"], raid["name"])
            )

    # Region-wide sensors (WoW Token, weekly reset)
    if features[CONF_ENABLE_REGION_DATA]:
        region_sensors = []
        if coordinator.has_retail:
            region_sensors += ["wow_token_price", "weekly_reset"]
        if coordinator.has_classic_progression:
            region_sensors.append("wow_token_price_classic")
        for sensor_type in region_sensors:
            entities.append(WoWRegionSensor(coordinator, sensor_type, entry.entry_id))

    # PvP season and title cutoffs (Retail)
    if features[CONF_ENABLE_PVP] and coordinator.has_retail:
        for sensor_type in ("pvp_season", "pvp_cutoff_gladiator", "pvp_cutoff_hero"):
            entities.append(WoWRegionSensor(coordinator, sensor_type, entry.entry_id))

    # Mythic+ leaderboards per Retail realm and the weekly affixes (opt-in)
    if features[CONF_ENABLE_MYTHIC_LEADERBOARD] and coordinator.has_retail:
        entities.append(WoWRegionSensor(coordinator, "mythicplus_affixes", entry.entry_id))
        for realm_key, realm in coordinator.realms.items():
            if realm["game_version"] == "retail":
                entities.append(
                    WoWRealmLeaderboardSensor(coordinator, "mythicplus_realm_best", realm_key, realm["realm"], "retail")
                )

    # Auction prices per tracked item
    for game_version, enabled in (("retail", coordinator.has_retail), ("classic", coordinator.has_classic_progression)):
        if enabled:
            for item_id in coordinator.auction_items:
                entities.append(WoWAuctionSensor(coordinator, game_version, item_id, entry.entry_id))

    # Account-wide data from the Battle.net login
    if coordinator.account_token:
        for sensor_type in ACCOUNT_SENSOR_TYPES:
            entities.append(WoWAccountSensor(coordinator, sensor_type, entry.entry_id))

    async_add_entities(entities)


def _game_version_label(game_version: str) -> str:
    """Human readable game version label."""
    return GAME_VERSIONS.get(game_version, {}).get("label", game_version)


class WoWCharacterSensor(CoordinatorEntity, SensorEntity):
    """Representation of a WoW character sensor."""

    # Gear details and other lists are large and change rarely; keep them out of the recorder
    _unrecorded_attributes = frozenset({
        "equipped_items", "equipped_items_list", "factions", "professions",
        "talent_list", "talent_points", "glyphs", "loadout_code", "dungeons", "pets",
    })

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
        # char_key is "{realm}-{name}" unless disambiguated by game version
        self._id_base = char_key.replace(f"{realm}-{character_name}", f"{realm}_{character_name}", 1)

        sensor_config = ALL_SENSOR_TYPES[sensor_type]

        self._attr_has_entity_name = True
        self._attr_translation_key = sensor_type
        self._attr_unique_id = f"{DOMAIN}_{self._id_base}_{sensor_type}"
        self._attr_icon = sensor_config["icon"]
        self._attr_native_unit_of_measurement = sensor_config.get("unit")
        self._attr_device_class = sensor_config.get("device_class")
        self._attr_state_class = sensor_config.get("state_class")
        if "options" in sensor_config:
            self._attr_options = sensor_config["options"]

    @property
    def _char_data(self) -> Dict[str, Any]:
        if not self.coordinator.data:
            return {}
        return self.coordinator.data.get(self._char_key) or {}

    @property
    def native_value(self):
        """Return the state of the sensor."""
        return self._char_data.get(self._sensor_type)

    @property
    def entity_picture(self):
        """Return the entity picture."""
        return self._char_data.get("avatar_url")

    @property
    def extra_state_attributes(self):
        """Return additional state attributes."""
        char_data = self._char_data
        if not char_data:
            return {}

        attributes = {
            "character_name": self._character_name,
            "realm": self._realm,
            "character_class": char_data.get("character_class"),
            "character_race": char_data.get("character_race"),
            "character_level": char_data.get("character_level"),
            "guild": char_data.get("guild_name"),
            "last_update": self.coordinator.last_update_success,
            "last_login": _format_timestamp(char_data.get("last_login_timestamp")),
            "faction": char_data.get("faction"),
            "active_spec": char_data.get("spec"),
            "game_version": self._game_version,
            "avatar_url": char_data.get("avatar_url"),
            "full_body_url": char_data.get("full_body_url"),
        }

        if self._sensor_type == "character_equipment":
            attributes["equipped_items"] = char_data.get("equipped_items", {})
            attributes["equipped_items_list"] = char_data.get("equipped_items_list", [])

        # Add class color if available
        class_color = CLASS_COLORS.get(char_data.get("character_class_id"))
        if class_color:
            attributes["class_color"] = class_color

        # Add specific attributes based on sensor type
        if self._sensor_type in PVP_SENSOR_TYPES:
            attributes["category"] = "pvp"
        elif self._sensor_type in RAID_SENSOR_TYPES:
            attributes["category"] = "raid"
            attributes["expansion"] = char_data.get("raid_expansion")
            difficulty_sensors = {v: k for k, v in RAID_DIFFICULTY_SENSORS.items()}
            if self._sensor_type in difficulty_sensors:
                attributes["total_bosses"] = (char_data.get("raid_total_bosses") or {}).get(self._sensor_type)
                difficulty = difficulty_sensors[self._sensor_type].lower()
                attributes["raids"] = {
                    raid: modes[difficulty]
                    for raid, modes in (char_data.get("raid_details") or {}).items()
                    if difficulty in modes
                }
        elif self._sensor_type in MYTHICPLUS_SENSOR_TYPES:
            attributes["category"] = "mythic_plus"
        elif self._sensor_type in DETAIL_SENSOR_TYPES:
            attributes["category"] = "details"
        elif self._sensor_type in COLLECTION_SENSOR_TYPES:
            attributes["category"] = "collections"
        elif self._sensor_type in GUILD_SENSOR_TYPES:
            attributes["category"] = "guild"
        else:
            attributes["category"] = "character"

        # Sensor specific details, e.g. skill per profession or standing per faction
        attributes.update((char_data.get("attrs") or {}).get(self._sensor_type) or {})

        return attributes

    @property
    def device_info(self):
        """Return device info."""
        return {
            "identifiers": {(DOMAIN, self._id_base)},
            "name": f"{self._character_name} ({self._realm})",
            "manufacturer": "Blizzard Entertainment",
            "model": "World of Warcraft Character",
            "sw_version": _game_version_label(self._game_version),
        }


class WoWServerSensor(CoordinatorEntity, SensorEntity):
    """Representation of a WoW server sensor."""

    def __init__(
        self,
        coordinator: WoWDataUpdateCoordinator,
        sensor_type: str,
        realm_key: str,
        realm: str,
        game_version: str = "retail",
    ):
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._sensor_type = sensor_type
        self._realm_key = realm_key
        self._realm = realm
        self._game_version = game_version

        sensor_config = ALL_SENSOR_TYPES[sensor_type]

        self._attr_has_entity_name = True
        self._attr_translation_key = sensor_type
        self._attr_unique_id = f"{DOMAIN}_server_{realm_key}_{sensor_type}"
        self._attr_icon = sensor_config["icon"]
        self._attr_native_unit_of_measurement = sensor_config.get("unit")
        self._attr_device_class = sensor_config.get("device_class")
        self._attr_state_class = sensor_config.get("state_class")

    @property
    def _realm_data(self) -> Dict[str, Any]:
        if not self.coordinator.data:
            return {}
        return (self.coordinator.data.get("servers") or {}).get(self._realm_key) or {}

    @property
    def native_value(self):
        """Return the state of the sensor."""
        return self._realm_data.get(self._sensor_type)

    @property
    def extra_state_attributes(self):
        """Return additional state attributes."""
        realm_data = self._realm_data
        if not realm_data:
            return {}

        return {
            "realm": self._realm,
            "game_version": self._game_version,
            "category": "server",
            # Language-independent values for automations (e.g. "UP"/"DOWN", "HIGH")
            "status_type": realm_data.get("realm_status_type"),
            "population_type": realm_data.get("realm_population_type"),
            "timezone": realm_data.get("realm_timezone"),
            "locale": realm_data.get("realm_locale"),
            "last_update": self.coordinator.last_update_success,
        }

    @property
    def device_info(self):
        """Return device info."""
        realm_name = self._realm.replace("-", " ").title()
        if self._realm_key != self._realm:
            realm_name = f"{realm_name} ({_game_version_label(self._game_version)})"
        return {
            "identifiers": {(DOMAIN, f"server_{self._realm_key}")},
            "name": f"{realm_name} Server",
            "manufacturer": "Blizzard Entertainment",
            "model": "World of Warcraft Realm",
            "sw_version": _game_version_label(self._game_version),
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
        self._attr_unique_id = f"{DOMAIN}_{raid_slug}_hof"
        self._attr_name = raid_name
        self._attr_icon = sensor_config["icon"]
        self._attr_native_unit_of_measurement = sensor_config.get("unit")
        self._attr_device_class = sensor_config.get("device_class")

    @property
    def _leaderboard(self) -> Dict[str, Any]:
        if not self.coordinator.data:
            return {}
        return (self.coordinator.data.get("leaderboards") or {}).get(self._raid_slug) or {}

    @property
    def native_value(self):
        """Return the state of the sensor (name of the world first guild)."""
        leaderboard = self._leaderboard
        if not leaderboard:
            return None

        entries = leaderboard.get("entries", [])
        if len(entries) > 0:
            return entries[0].get("guild", {}).get("name")
        return "Pending"

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        """Return additional state attributes."""
        leaderboard = self._leaderboard
        unified = leaderboard.get("unified", True)
        attributes = {
            "raid_name": self._raid_name,
            "faction": "Unified" if unified else "Horde",
            "region": "Global",
            "completed": False,
            "total_entries": 0,
            "info_url": self.coordinator.client.hof_page_url(self._raid_slug),
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

        if not leaderboard:
            return attributes

        entries = leaderboard.get("entries", [])
        total_entries = len(entries)
        attributes["total_entries"] = total_entries
        attributes["completed"] = total_entries >= (HOF_FULL_UNIFIED if unified else HOF_FULL_SPLIT)

        if total_entries > 0:
            first_entry = entries[0]
            attributes["world_first_guild"] = first_entry.get("guild", {}).get("name")
            attributes["world_first_realm"] = first_entry.get("guild", {}).get("realm", {}).get("name")
            attributes["world_first_region"] = str(first_entry.get("region") or "").upper()
            attributes["world_first_timestamp"] = first_entry.get("timestamp")
            attributes["world_first_timestamp_formatted"] = _format_timestamp(first_entry.get("timestamp"))

            last_entry = entries[-1]
            attributes["last_guild_name"] = last_entry.get("guild", {}).get("name")
            attributes["last_guild_rank"] = last_entry.get("rank")
            attributes["last_guild_timestamp"] = last_entry.get("timestamp")
            attributes["last_guild_timestamp_formatted"] = _format_timestamp(last_entry.get("timestamp"))

        # Map configured retail characters to their guild rank
        char_ranks = {}
        client = self.coordinator.client
        for character in self.coordinator.characters:
            if character[CONF_GAME_VERSION] != "retail":
                continue

            char_data = self.coordinator.data.get(character["key"]) or {}
            guild_name = char_data.get("guild_name")
            if not guild_name:
                continue

            char_realm_slug = client.realm_to_slug(character[CONF_REALM])
            for entry in entries:
                entry_guild = entry.get("guild", {})
                entry_guild_name = entry_guild.get("name")
                entry_realm_slug = entry_guild.get("realm", {}).get("slug")

                if entry_guild_name and entry_guild_name.lower() == guild_name.lower():
                    if entry_realm_slug == char_realm_slug and entry.get("region") == client.region:
                        char_ranks[character[CONF_CHARACTER_NAME]] = entry.get("rank")
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
            "entry_type": DeviceEntryType.SERVICE,
        }


class WoWRegionSensor(CoordinatorEntity, SensorEntity):
    """Region-wide sensor such as the WoW Token price or the weekly reset."""

    def __init__(
        self,
        coordinator: WoWDataUpdateCoordinator,
        sensor_type: str,
        entry_id: str,
    ):
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._sensor_type = sensor_type
        self._region = coordinator.client.region

        sensor_config = REGION_SENSOR_TYPES[sensor_type]
        self._attr_has_entity_name = True
        self._attr_translation_key = sensor_type
        self._attr_unique_id = f"{DOMAIN}_{entry_id}_{sensor_type}"
        self._attr_icon = sensor_config["icon"]
        self._attr_native_unit_of_measurement = sensor_config.get("unit")
        self._attr_device_class = sensor_config.get("device_class")
        self._attr_state_class = sensor_config.get("state_class")

    @property
    def _region_data(self) -> Dict[str, Any]:
        if not self.coordinator.data:
            return {}
        return self.coordinator.data.get("region") or {}

    @property
    def native_value(self):
        """Return the state of the sensor."""
        value = self._region_data.get(self._sensor_type)
        if value is not None and self._sensor_type == "weekly_reset":
            return datetime.fromtimestamp(value / 1000, timezone.utc)
        return value

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        """Return additional state attributes."""
        return {
            "region": self._region.upper(),
            "category": "region",
            **((self._region_data.get("attrs") or {}).get(self._sensor_type) or {}),
        }

    @property
    def device_info(self):
        """Return device info."""
        return {
            "identifiers": {(DOMAIN, f"region_{self._region}")},
            "name": f"WoW {self._region.upper()}",
            "manufacturer": "Blizzard Entertainment",
            "model": "World of Warcraft Region",
            "entry_type": DeviceEntryType.SERVICE,
        }


class WoWRealmLeaderboardSensor(WoWServerSensor):
    """Best Mythic+ key of the week on a realm, from the realm leaderboards."""

    @property
    def _leaderboard(self) -> Dict[str, Any]:
        if not self.coordinator.data:
            return {}
        return (self.coordinator.data.get("mythic_leaderboards") or {}).get(self._realm_key) or {}

    @property
    def native_value(self):
        """Return the state of the sensor."""
        return self._leaderboard.get(self._sensor_type)

    @property
    def extra_state_attributes(self):
        """Return additional state attributes."""
        leaderboard = self._leaderboard
        return {
            "realm": self._realm,
            "game_version": self._game_version,
            "category": "mythic_plus",
            "dungeons": leaderboard.get("dungeons", {}),
            "own_characters": leaderboard.get("own_characters", {}),
        }


class WoWAuctionSensor(CoordinatorEntity, SensorEntity):
    """Lowest auction price of a tracked item."""

    _unrecorded_attributes = frozenset({"sources"})

    def __init__(self, coordinator: WoWDataUpdateCoordinator, game_version: str, item_id: int, entry_id: str):
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._key = f"{game_version}:{item_id}"
        self._item_id = item_id
        self._game_version = game_version
        self._region = coordinator.client.region

        sensor_config = AUCTION_SENSOR_TYPES["auction_price"]
        self._attr_has_entity_name = True
        self._attr_unique_id = f"{DOMAIN}_{entry_id}_auction_{game_version}_{item_id}"
        self._attr_icon = sensor_config["icon"]
        self._attr_native_unit_of_measurement = sensor_config["unit"]
        self._attr_state_class = sensor_config["state_class"]
        self._attr_suggested_display_precision = 2

    @property
    def _auction(self) -> Dict[str, Any]:
        if not self.coordinator.data:
            return {}
        return (self.coordinator.data.get("auctions") or {}).get(self._key) or {}

    @property
    def name(self):
        """Item name, falls back to the item ID."""
        name = self._auction.get("item_name") or f"Item {self._item_id}"
        return f"{name} (Classic)" if self._game_version == "classic" else name

    @property
    def native_value(self):
        """Return the lowest price per item in gold."""
        return self._auction.get("price")

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        """Return additional state attributes."""
        auction = self._auction
        return {
            "item_id": self._item_id,
            "game_version": self._game_version,
            "quantity": auction.get("quantity"),
            "auctions": auction.get("auctions"),
            "sources": auction.get("sources", {}),
            "category": "auction",
        }

    @property
    def device_info(self):
        """Return device info."""
        return {
            "identifiers": {(DOMAIN, f"auctions_{self._region}")},
            "name": f"WoW {self._region.upper()} Auction House",
            "manufacturer": "Blizzard Entertainment",
            "model": "World of Warcraft Auction House",
            "entry_type": DeviceEntryType.SERVICE,
        }


class WoWAccountSensor(CoordinatorEntity, SensorEntity):
    """Account-wide sensor from the player's Battle.net login."""

    def __init__(self, coordinator: WoWDataUpdateCoordinator, sensor_type: str, entry_id: str):
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._sensor_type = sensor_type
        self._entry_id = entry_id

        sensor_config = ACCOUNT_SENSOR_TYPES[sensor_type]
        self._attr_has_entity_name = True
        self._attr_translation_key = sensor_type
        self._attr_unique_id = f"{DOMAIN}_{entry_id}_{sensor_type}"
        self._attr_icon = sensor_config["icon"]
        self._attr_native_unit_of_measurement = sensor_config.get("unit")
        self._attr_device_class = sensor_config.get("device_class")
        self._attr_state_class = sensor_config.get("state_class")

    @property
    def _account(self) -> Dict[str, Any]:
        if not self.coordinator.data:
            return {}
        return self.coordinator.data.get("account") or {}

    @property
    def native_value(self):
        """Return the state of the sensor."""
        value = self._account.get(self._sensor_type)
        if value is not None and self._sensor_type == "account_login":
            # Shows when the login expires
            return datetime.fromtimestamp(value / 1000, timezone.utc)
        return value

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        """Return additional state attributes."""
        return {
            "category": "account",
            # False once the 24 hour login has expired; values are then the last known ones
            "login_valid": self._account.get("login_valid", False),
        }

    @property
    def device_info(self):
        """Return device info."""
        return {
            "identifiers": {(DOMAIN, f"account_{self._entry_id}")},
            "name": "Battle.net Account",
            "manufacturer": "Blizzard Entertainment",
            "model": "Battle.net Account",
            "entry_type": DeviceEntryType.SERVICE,
        }
