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
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.dispatcher import async_dispatcher_connect
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
    CONF_ENABLE_PVP_LEADERBOARD,
    CONF_AUCTION_ITEMS,
    FEATURE_DEFAULTS,
    CONF_GAME_VERSION,
    CONF_LOCALE,
    CONF_NAMESPACE_SUFFIX,
    CONF_RULESET_ID,
    ALL_SENSOR_TYPES,
    SERVER_SENSOR_TYPES,
    PVP_SENSOR_TYPES,
    RAID_SENSOR_TYPES,
    MYTHICPLUS_SENSOR_TYPES,
    DETAIL_SENSOR_TYPES,
    COLLECTION_SENSOR_TYPES,
    GUILD_SENSOR_TYPES,
    REGION_SENSOR_TYPES,
    ACCOUNT_SENSOR_TYPES,
    SUBENTRY_REALMS,
    REALM_LEADERBOARD_SENSOR_TYPES,
    AUCTION_SENSOR_TYPES,
    HOF_SENSOR_TYPES,
    DEFAULT_SCAN_INTERVAL,
    SLOW_REFRESH_INTERVAL,
    GUILD_REFRESH_INTERVAL,
    AUCTION_REFRESH_INTERVAL,
    LEADERBOARD_REFRESH_INTERVAL,
    PVP_SEASON_REFRESH_INTERVAL,
    CLASS_COLORS,
    ITEM_QUALITY_COLORS,
    GAME_VERSIONS,
    get_sensor_types_for_version,
    NO_VALUE_TEXT,
    no_value_text,
)
from .api_client import WoWBlizzardAPIClient
from .entries import entry_characters, entry_game_version, group_subentry_id, realm_keys, unique_base
from .account import (
    AccountCoordinator,
    account_coordinator,
    account_signal,
    async_gold_characters,
    gold_key,
    is_account_entry,
)
from .parsers import (
    COLLECTION_ENDPOINTS,
    HUNTER_CLASS_ID,
    _guild_path,
    _merge,
    bracket_slug,
    parse_guild_achievements,
    parse_guild_activity,
    parse_guild_roster,
    roster_changes,
    parse_mythic_leaderboard,
    ACCOUNT_COLLECTIONS,
    parse_active_quests,
    parse_character_achievements,
    parse_mythic_best_runs,
    parse_title_cutoffs,
    parse_connected_realm_search,
    with_render_fallback,
    parse_pvp_leaderboard,
    parse_transmogs,
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

# Delay before the cache is written, so several changes are saved together
CACHE_SAVE_DELAY = 60

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
        if GAME_VERSIONS.get(game_version, {}).get("realmless") and char.get(CONF_RULESET_ID) is None:
            # WoW Forever without a known game mode (e.g. imported while the
            # profile was unavailable): there is no realm to report on
            continue
        if (realm, game_version) in seen_pairs:
            continue
        seen_pairs.add((realm, game_version))
        key = realm if realm not in realms else f"{realm}-{game_version}"
        realms[key] = {"realm": realm, "game_version": game_version}
        if char.get(CONF_RULESET_ID) is not None:
            # WoW Forever: the ruleset carries the server status
            realms[key]["ruleset_id"] = char[CONF_RULESET_ID]
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
        game_version: Optional[str] = None,
        realms: Optional[Dict[str, Dict[str, Any]]] = None,
    ):
        """Initialize.

        Characters come with their entity key (see entries.entry_characters);
        without game_version the characters are keyed here (single mixed list).
        """
        self.client = client
        self.auction_items = list(auction_items or [])
        # Whether the region had a Battle.net account entry at setup, and the
        # characters with gold then (see async_gold_characters)
        self.account_linked = False
        self.gold_characters: Optional[set] = None
        self.characters = characters if all("key" in c for c in characters) else assign_character_keys(characters)
        self.features = features
        self.realms = realms if realms is not None else assign_realm_keys(self.characters)
        # One config entry per game version
        self.game_version = game_version or (self.characters[0][CONF_GAME_VERSION] if self.characters else "retail")
        self.has_retail = self.game_version == "retail"
        self.has_classic_progression = self.game_version == "classic"

        # Cache for dynamic raid discovery and Hall of Fame leaderboards
        self._cached_raids = None
        self._last_raids_fetch = None
        self._hof_cache = {}
        # Slowly changing data: char_key -> (last login, fetch time, data);
        # guild path -> (fetch time, data); current weekly period
        self._slow_cache: Dict[str, Any] = {}
        self._guild_cache: Dict[str, Any] = {}
        # Guild fetches in progress, shared by characters of the same guild
        self._guild_fetches: Dict[str, Any] = {}
        self._period: Dict[str, Any] = {}
        # Current PvP season with title cutoffs, English spec slugs per spec ID
        self._pvp_season: Dict[str, Any] = {}
        self._spec_slugs: Dict[int, str] = {}
        # Connected realm ID per (realm, game version); icons per (version, item ID)
        self._connected_realms: Dict[Any, int] = {}
        self._item_icons: Dict[Any, Optional[str]] = {}
        self._item_names: Dict[Any, Optional[Dict[str, Any]]] = {}
        # Item level per (version, item ID), for Classic, whose equipment has none
        self._item_levels: Dict[Any, int] = {}
        # Hourly data: (fetch time, data)
        self._leaderboard_cache: Optional[Any] = None
        self._auction_cache: Optional[Any] = None
        self._guild_activity: Dict[str, List[Dict[str, Any]]] = {}
        # Guild members per guild (to spot joins and leaves), the joins and
        # leaves of the last roster check, class names per game version
        self._guild_rosters: Dict[str, Dict[str, Any]] = {}
        self._guild_roster_events: Dict[str, List[Dict[str, Any]]] = {}
        self._class_names: Dict[str, Dict[int, str]] = {}
        # Classic PvP seasons per game version: {"fetched", "season", "titles"}
        self._classic_pvp_seasons: Dict[str, Dict[str, Any]] = {}
        # Guild crests per guild key, crest colors per game version
        self._guild_crests: Dict[str, Dict[str, Any]] = {}
        self._crest_colors: Dict[str, Dict[str, Dict[int, Any]]] = {}
        # Current Mythic+ season: {"fetched", "season"}
        self._mythic_season: Dict[str, Any] = {}
        # PvP leaderboards per "season:bracket": (fetch time, ranks by character ID)
        self._pvp_leaderboard_cache: Dict[str, Any] = {}
        # Item icons and slow character data across restarts and reloads
        self._cache_store: Optional[Store] = None
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
                # Missing renders (new characters, no logout since) fall back to a silhouette
                race_id = (profile.get("race") or {}).get("id")
                gender_type = (profile.get("gender") or {}).get("type")
                avatar_url = with_render_fallback(assets.get("avatar"), race_id, gender_type)
                full_body_url = with_render_fallback(
                    assets.get("main-raw") or assets.get("main") or assets.get("inset"), race_id, gender_type
                ) or avatar_url
            except Exception as media_err:
                _LOGGER.debug(f"Could not fetch media for {character_name}-{realm}: {media_err}")

            equipment = await self.client.get_character_equipment(realm, character_name, game_version=game_version)
            equipped_items_list = self._parse_equipment(equipment)
            icons = await asyncio.gather(*(self._item_icon(i.get("media_id"), game_version) for i in equipped_items_list))
            for item, icon in zip(equipped_items_list, icons):
                item["icon"] = icon
            # Classic equipment has no item level; the item itself has it
            missing = [i for i in equipped_items_list if i["item_level"] is None]
            levels = await asyncio.gather(*(self._item_level(i.get("item_id"), game_version) for i in missing))
            for item, level in zip(missing, levels):
                item["item_level"] = level

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
                "character_id": profile.get("id"),
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
                # Missing in Classic; filled in from the item afterwards
                "item_level": (item.get("level") or {}).get("value"),
                "quality": quality.get("name", quality_type.title()),
                "quality_color": ITEM_QUALITY_COLORS.get(quality_type, "#FFFFFF"),
                "stats": stats,
                # Transmogrified appearance, if any
                "transmog": ((item.get("transmog") or {}).get("item") or {}).get("name"),
            })
        return items

    async def _fetch_server_data(self, realm: str, game_version: str = "retail", ruleset_id: Optional[int] = None) -> Dict[str, Any]:
        """Fetch server status data."""
        if not self.features.get(CONF_ENABLE_SERVER_STATUS, False):
            return {}

        if ruleset_id is not None:
            # WoW Forever: no realms, the ruleset (Normal, PvP ...) has the status
            ruleset = await self.client.get_ruleset(ruleset_id, game_version)
            status = ruleset.get("status") or {}
            if not status:
                return {}
            return {
                "realm_status": status.get("name", "Unknown"),
                "realm_status_type": status.get("type"),
                "ruleset": ruleset.get("name"),
            }

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

    async def _fetch_all_server_data(self) -> Dict[str, Any]:
        """Realm status of all configured realms.

        One connected realm search per game version instead of two requests
        per realm; realms the search does not answer for are fetched one by one.
        """
        if not self.features.get(CONF_ENABLE_SERVER_STATUS, False):
            return {}
        found: Dict[str, Dict[str, Any]] = {}
        versions = {r["game_version"] for r in self.realms.values() if r.get("ruleset_id") is None}
        for game_version in sorted(versions):
            slugs = {
                self.client.realm_to_slug(r["realm"])
                for r in self.realms.values()
                if r["game_version"] == game_version and r.get("ruleset_id") is None
            } - {""}
            if not slugs:
                continue
            search = await self.client.search_connected_realms(sorted(slugs), game_version)
            for slug, data in parse_connected_realm_search(search, self.client.locale).items():
                found[f"{game_version}:{slug}"] = data

        server_data = {}
        for realm_key, realm in self.realms.items():
            game_version = realm["game_version"]
            data = found.get(f"{game_version}:{self.client.realm_to_slug(realm['realm'])}")
            if data:
                # Also spares the realm lookup for auctions and Mythic+ leaderboards
                if isinstance(data.get("connected_realm_id"), int):
                    self._connected_realms[(realm["realm"], game_version)] = data["connected_realm_id"]
                server_data[realm_key] = {k: v for k, v in data.items() if k != "connected_realm_id"}
            else:
                # WoW Forever rulesets, and realms the search missed
                server_data[realm_key] = await self._fetch_server_data(
                    realm["realm"], game_version=game_version, ruleset_id=realm.get("ruleset_id")
                )
        return server_data

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
            # Retail title cutoffs only for Retail; Classic seasons list several titles per bracket
            cutoffs = (self._pvp_season.get("cutoffs") or {}) if game_version == "retail" else {}
            title_cutoffs = (self._classic_pvp_seasons.get(game_version) or {}).get("titles") or {}
            faction = (basic.get("faction_type") or "").lower()

            wins_season = 0
            for sensor, bracket in brackets.items():
                data = await self.client.get_character_pvp_bracket(realm, character_name, bracket, game_version)
                if not data and self.client.last_status == 404:
                    # No rated games in this bracket: rating 0 instead of unknown
                    result[sensor] = 0
                    continue
                if not data or "rating" not in data:
                    continue
                season_id = (data.get("season") or {}).get("id")
                stale = current_season is not None and season_id != current_season
                season_stats = {} if stale else (data.get("season_match_statistics") or {})
                weekly_stats = {} if stale else (data.get("weekly_match_statistics") or {})
                result[sensor] = 0 if stale else data["rating"]
                wins_season += season_stats.get("won", 0)
                if not stale and current_season is not None and season_stats.get("played"):
                    # Played this season: look the character up on the leaderboard
                    result.setdefault("pvp_leaderboard_brackets", {})[sensor] = bracket

                attrs = {
                    "rating_season_id": season_id,
                    "last_season_rating": data["rating"] if stale else None,
                    "season_played": season_stats.get("played", 0),
                    "season_won": season_stats.get("won", 0),
                    "season_lost": season_stats.get("lost", 0),
                    "weekly_played": weekly_stats.get("played", 0),
                    "weekly_won": weekly_stats.get("won", 0),
                }
                classic_bracket = {"pvp_2v2_rating": "ARENA_2v2", "pvp_3v3_rating": "ARENA_3v3"}.get(sensor)
                if classic_bracket and title_cutoffs.get(classic_bracket):
                    attrs["title_cutoffs"] = title_cutoffs[classic_bracket]
                if sensor == "pvp_3v3_rating" and game_version == "retail":
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
                "attrs": {"mythicplus_best_run": {
                    "best_runs": parse_mythic_best_runs((season_data or {}).get("best_runs") or []),
                }},
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
            ("quests", parse_active_quests, {"active_quests"}),
            # 1 to 3 MB, decoded off the event loop
            ("achievements", parse_character_achievements, {"achievements_completed"}),
        ]
        if class_id == HUNTER_CLASS_ID:
            sources.append(("hunter-pets", parse_hunter_pets, {"hunter_pet"}))

        result: Dict[str, Any] = {}
        for resource, parser, sensors in sources:
            if not sensors & set(supported):
                continue
            data = await self.client.get_character_resource(
                realm, character_name, resource, game_version, parse_in_thread=resource == "achievements"
            )
            if not data and self.client.last_status == 404 and resource in ("reputations", "encounters/dungeons"):
                # Blizzard answers 404 when a character has none of these yet: that is 0, not unknown
                data = {"_links": {}}
            _merge(result, parser(data))

        # Retail lists all earned titles; the active one comes with the profile
        if game_version == "retail" and "active_title" in supported:
            titles = await self.client.get_character_resource(realm, character_name, "titles", game_version)
            if titles:
                result.setdefault("attrs", {})["active_title"] = {"title_count": len(titles.get("titles") or [])}
        return result

    async def _fetch_collections_data(self, realm: str, character_name: str, game_version: str) -> Dict[str, Any]:
        """Fetch the number of collected mounts, pets, toys, heirlooms, decor and transmogs."""
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
        if "transmogs_collected" in supported:
            # Up to 5 MB for big collections, decoded off the event loop
            data = await self.client.get_character_resource(
                realm, character_name, "collections/transmogs", game_version, parse_in_thread=True
            )
            _merge(result, parse_transmogs(data))
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
        self._schedule_cache_save()
        return data

    async def _fetch_guild_data(self, guild_path: Optional[str], game_version: str) -> Dict[str, Any]:
        """Fetch guild details, roster statistics and achievements, cached per guild.

        Characters are fetched in parallel; characters of the same guild share
        one fetch, so the roster is compared only once (joins and leaves).
        """
        if not self.features.get(CONF_ENABLE_GUILD, False) or not guild_path:
            return {}
        if not get_sensor_types_for_version(game_version)["guild"]:
            return {}

        cache_key = f"{game_version}:{guild_path}"
        cached = self._guild_cache.get(cache_key)
        if cached and datetime.now() - cached[0] < timedelta(seconds=GUILD_REFRESH_INTERVAL):
            return cached[1]
        running = self._guild_fetches.get(cache_key)
        if running is None:
            running = asyncio.ensure_future(self._fetch_guild_data_now(guild_path, game_version, cache_key))
            self._guild_fetches[cache_key] = running
            running.add_done_callback(lambda _: self._guild_fetches.pop(cache_key, None))
        return await asyncio.shield(running)

    async def _fetch_guild_data_now(self, guild_path: str, game_version: str, cache_key: str) -> Dict[str, Any]:
        """Fetch one guild (see _fetch_guild_data)."""
        now = datetime.now()
        cached = self._guild_cache.get(cache_key)

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
        if guild.get("crest"):
            # Shown as an image entity (not every game version has crests)
            await self._guild_crest(cache_key, guild["crest"], game_version)

        # Recent achievements and boss kills, shown as events
        activity = await self.client.get_guild_activity(guild_path, game_version)
        if "activities" in activity:
            # Some game versions (e.g. Anniversary, Forever) answer without a feed
            self._guild_activity[cache_key] = parse_guild_activity(activity)

        # Members by level, class and rank; joins and leaves since the last check
        roster = parse_guild_roster(
            await self.client.get_guild_roster(guild_path, game_version),
            await self._get_class_names(game_version),
        )
        if roster:
            _merge(data, roster["sensors"])
            previous_members = self._guild_rosters.get(cache_key)
            if previous_members is not None:
                self._guild_roster_events[cache_key] = roster_changes(
                    previous_members, roster["members"], int(now.timestamp() * 1000)
                )
            else:
                self._guild_roster_events.setdefault(cache_key, [])
            self._guild_rosters[cache_key] = roster["members"]
        elif cached and "guild_max_level_members" in cached[1]:
            # Keep the last roster values on API errors
            data["guild_max_level_members"] = cached[1]["guild_max_level_members"]

        # Completed guild achievements (versions without achievements answer 404)
        achievements = parse_guild_achievements(
            await self.client.get_guild_achievements(guild_path, game_version)
        )
        if achievements:
            _merge(data, achievements)
        elif cached and "guild_achievements" in cached[1]:
            data["guild_achievements"] = cached[1]["guild_achievements"]
        if cached:
            # Attributes of values that could not be refreshed
            fresh = data.setdefault("attrs", {})
            for key, attrs in (cached[1].get("attrs") or {}).items():
                fresh[key] = {**attrs, **(fresh.get(key) or {})}
        data["guild_key"] = cache_key
        self._guild_cache[cache_key] = (now, data)
        return data

    async def _get_class_names(self, game_version: str) -> Dict[int, str]:
        """Localized class names by class ID (the roster only has IDs)."""
        if game_version not in self._class_names:
            index = await self.client.get_playable_classes(game_version)
            names = {
                c.get("id"): c.get("name")
                for c in index.get("classes") or []
                if isinstance(c.get("id"), int) and c.get("name")
            }
            if not names:
                # Try again with the next roster refresh
                return {}
            self._class_names[game_version] = names
        return self._class_names[game_version]

    def _guild_rank(self, guild_key: Optional[str], realm: str, character_name: str, game_version: str) -> Optional[int]:
        """Rank of a character in its guild roster (0 = guild master)."""
        members = self._guild_rosters.get(guild_key or "")
        if not members:
            return None
        path = self.client.character_path(realm, character_name, game_version)
        member = members.get(path.removeprefix("/profile/wow/character/"))
        return member["rank"] if member else None

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
            self._schedule_cache_save()
        return self._item_icons[key]

    def _schedule_cache_save(self) -> None:
        """Store item icons and slow character data (written at most once a minute)."""
        if self._cache_store is not None:
            self._cache_store.async_delay_save(self._cache_data, CACHE_SAVE_DELAY)

    def _cache_data(self) -> Dict[str, Any]:
        return {
            "item_icons": {f"{k[0]}:{k[1]}": v for k, v in self._item_icons.items()},
            "item_levels": {f"{k[0]}:{k[1]}": v for k, v in self._item_levels.items()},
            "slow": {
                char_key: [last_login, fetched.isoformat(), data]
                for char_key, (last_login, fetched, data) in self._slow_cache.items()
            },
        }

    def load_cache(self, stored: Optional[Dict[str, Any]]) -> None:
        """Restore the cache of a previous run; data older than the refresh interval is fetched again."""
        if not stored:
            return
        for key, url in (stored.get("item_icons") or {}).items():
            flavor, _, media_id = key.partition(":")
            if media_id.isdigit():
                self._item_icons[(flavor, int(media_id))] = url
        for key, level in (stored.get("item_levels") or {}).items():
            version, _, item_id = key.partition(":")
            if item_id.isdigit() and isinstance(level, int):
                self._item_levels[(version, int(item_id))] = level
        known = {c["key"] for c in self.characters}
        for char_key, (last_login, fetched, data) in (stored.get("slow") or {}).items():
            if char_key in known:
                try:
                    self._slow_cache[char_key] = (last_login, datetime.fromisoformat(fetched), data)
                except (TypeError, ValueError):
                    continue

    async def _item_level(self, item_id: Optional[int], game_version: str) -> Optional[int]:
        """Item level of an item, cached across restarts (it is fixed per item in Classic)."""
        if not isinstance(item_id, int):
            return None
        key = (game_version, item_id)
        if key not in self._item_levels:
            item = await self.client.get_item(item_id, game_version)
            level = (item or {}).get("level")
            if not isinstance(level, int):
                # Do not cache failures, retry on the next update
                return None
            self._item_levels[key] = level
            self._schedule_cache_save()
        return self._item_levels[key]

    async def _item_info(self, item_id: int, game_version: str) -> Optional[Dict[str, Any]]:
        """Localized name, quality and media ID of an item, cached for the runtime."""
        key = (game_version, item_id)
        if key not in self._item_names:
            item = await self.client.get_item(item_id, game_version)
            if not item:
                return None
            self._item_names[key] = {
                "name": item.get("name"),
                "quality": ((item.get("quality") or {}).get("type") or "").upper() or None,
                "media_id": (item.get("media") or {}).get("id"),
            }
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

    async def _fetch_classic_pvp_seasons(self) -> None:
        """Current PvP seasons of Classic Progression and Anniversary with their title cutoffs."""
        if not self.features.get(CONF_ENABLE_PVP, False):
            return
        versions = {self.game_version} & {"classic", "classicann"}
        for game_version in sorted(versions):
            cached = self._classic_pvp_seasons.get(game_version) or {}
            fetched = cached.get("fetched")
            if fetched and datetime.now() - fetched < timedelta(seconds=PVP_SEASON_REFRESH_INTERVAL):
                continue
            season = await self.client.get_current_pvp_season(game_version)
            if not season:
                continue
            rewards = await self.client.get_pvp_rewards(season["id"], game_version)
            self._classic_pvp_seasons[game_version] = {
                "fetched": datetime.now(),
                "season": season,
                "titles": parse_title_cutoffs(rewards) if rewards else cached.get("titles", {}),
            }

    def _classic_pvp_region_data(self) -> Dict[str, Any]:
        """Region sensors for the Classic PvP seasons."""
        result: Dict[str, Any] = {"attrs": {}}
        for game_version, data in self._classic_pvp_seasons.items():
            season = data.get("season") or {}
            sensor = f"pvp_season_{game_version}"
            # Classic seasons have no name, only a number
            result[sensor] = season.get("season_name") or season.get("id")
            result["attrs"][sensor] = {
                "season_id": season.get("id"),
                "season_start": _format_timestamp(season.get("season_start_timestamp")),
                "title_cutoffs": {
                    bracket.lower(): tiers for bracket, tiers in (data.get("titles") or {}).items()
                },
            }
        return result if result["attrs"] else {}

    async def _guild_crest(self, guild_key: str, crest: Dict[str, Any], game_version: str) -> Optional[Dict[str, Any]]:
        """Image URLs and colors of a guild crest; colors without RGB come from the crest index."""
        emblem_id = (crest.get("emblem") or {}).get("id")
        border_id = (crest.get("border") or {}).get("id")
        if not isinstance(emblem_id, int) or not isinstance(border_id, int):
            return None

        async def color(part: str, group: str) -> Optional[list]:
            value = ((crest.get(part) or {}).get("color") or {})
            rgba = value.get("rgba")
            if not rgba and isinstance(value.get("id"), int):
                # Classic crests only carry color IDs
                if game_version not in self._crest_colors:
                    index = await self.client.get_guild_crest_index(game_version)
                    if not index.get("colors") and game_version != "retail":
                        # Era and Anniversary list no colors; their IDs are the Retail palette
                        index = await self.client.get_guild_crest_index("retail")
                    self._crest_colors[game_version] = {
                        name: {c.get("id"): c.get("rgba") for c in colors or []}
                        for name, colors in (index.get("colors") or {}).items()
                    }
                rgba = (self._crest_colors.get(game_version, {}).get(group) or {}).get(value["id"])
            return [rgba.get("r", 0), rgba.get("g", 0), rgba.get("b", 0)] if rgba else None

        async def image(kind: str, media_id: int) -> Optional[str]:
            media = await self.client.get_guild_crest_media(kind, media_id, game_version)
            return next((a.get("value") for a in media.get("assets") or [] if a.get("key") == "image"), None)

        previous = self._guild_crests.get(guild_key)
        if previous and previous.get("source") == crest:
            return previous
        parts = {
            "source": crest,
            "emblem_url": await image("emblem", emblem_id),
            "border_url": await image("border", border_id),
            "emblem_color": await color("emblem", "emblems"),
            "border_color": await color("border", "borders"),
            "background_color": await color("background", "backgrounds"),
        }
        if not (parts["emblem_url"] and parts["border_url"]):
            return previous
        self._guild_crests[guild_key] = parts
        return parts

    async def _fetch_pvp_season(self) -> None:
        """Current Retail PvP season and its title cutoffs, refreshed every few hours."""
        await self._fetch_classic_pvp_seasons()
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

    async def _mythic_season_region_data(self) -> Dict[str, Any]:
        """Region sensor for the current Mythic+ season, refreshed every few hours."""
        if not self.features.get(CONF_ENABLE_MYTHIC_PLUS, False) or not self.has_retail:
            return {}
        fetched = self._mythic_season.get("fetched")
        if not fetched or datetime.now() - fetched >= timedelta(seconds=PVP_SEASON_REFRESH_INTERVAL):
            season = await self.client.get_current_mythic_season()
            if season:
                self._mythic_season = {"fetched": datetime.now(), "season": season}
        season = self._mythic_season.get("season")
        if not season:
            return {}
        return {
            "mythicplus_season": season.get("season_name") or season.get("id"),
            "attrs": {"mythicplus_season": {
                "season_id": season.get("id"),
                "season_start": _format_timestamp(season.get("start_timestamp")),
                "season_end": _format_timestamp(season.get("end_timestamp")),
                "weeks": len(season.get("periods") or []),
            }},
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

    async def _apply_pvp_leaderboards(self, all_data: Dict[str, Any]) -> None:
        """Add the leaderboard rank to the rating sensors of the brackets a character played (opt-in, hourly).

        Each leaderboard holds the best ~5000 of the region and is downloaded
        once per hour, however many characters need it.
        """
        season_id = (self._pvp_season.get("season") or {}).get("id")
        if not self.features.get(CONF_ENABLE_PVP_LEADERBOARD, False) or not isinstance(season_id, int):
            return
        characters = [
            data for data in all_data.values()
            if isinstance(data, dict) and data.get("pvp_leaderboard_brackets")
        ]
        boards: Dict[str, Any] = {}
        for bracket in sorted({b for data in characters for b in data["pvp_leaderboard_brackets"].values()}):
            cache_key = f"{season_id}:{bracket}"
            cached = self._pvp_leaderboard_cache.get(cache_key)
            if not self._is_fresh(cached, LEADERBOARD_REFRESH_INTERVAL):
                board = parse_pvp_leaderboard(await self.client.get_pvp_leaderboard(season_id, bracket))
                # On errors keep the last board and wait an hour as well,
                # instead of downloading 2 MB on every update
                cached = (datetime.now(), board or (cached[1] if cached else {}))
                self._pvp_leaderboard_cache[cache_key] = cached
            if cached[1]:
                boards[bracket] = cached[1]

        for data in characters:
            # Copy, the attributes may still belong to the previous update
            data["attrs"] = dict(data.get("attrs") or {})
            for sensor, bracket in data["pvp_leaderboard_brackets"].items():
                board = boards.get(bracket)
                if not board:
                    continue
                _merge(data, {"attrs": {sensor: {
                    # None: not among the best of the region
                    "leaderboard_rank": board["ranks"].get(data.get("character_id")),
                    "leaderboard_entries": board["entries"],
                    "leaderboard_min_rating": board["min_rating"],
                }}})

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
                info = await self._item_info(item_id, game_version) or {}
                result[f"{game_version}:{item_id}"] = {
                    # Copper to gold, keeping silver and copper as decimals
                    "price": round(entry["min_price"] / 10000, 4) if entry["min_price"] is not None else None,
                    "quantity": entry["quantity"],
                    "auctions": entry["auctions"],
                    "sources": {
                        source: round(price / 10000, 4) if price is not None else None
                        for source, price in entry["sources"].items()
                    },
                    "item_name": info.get("name"),
                    "item_icon": await self._item_icon(info.get("media_id"), game_version),
                    "quality": info.get("quality"),
                }

        self._auction_cache = (datetime.now(), result)
        return result

    async def _fetch_character(self, character: Dict[str, Any]):
        """All data of one character: (key, data)."""
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
            return char_key, previous

        pvp_data, raid_data, mythicplus_data, slow_data, guild_data = await asyncio.gather(
            self._fetch_pvp_data(realm, name, game_version=game_version, basic=basic_data),
            self._fetch_raid_data(realm, name, game_version=game_version),
            self._fetch_mythicplus_data(realm, name, game_version=game_version),
            self._fetch_slow_character_data(char_key, realm, name, game_version, basic_data),
            self._fetch_guild_data(basic_data.get("guild_path"), game_version),
        )
        guild_rank = self._guild_rank(guild_data.get("guild_key"), realm, name, game_version)
        if guild_rank is not None:
            guild_data = {**guild_data, "guild_rank": guild_rank}

        # Per-sensor attributes are merged, not overwritten
        char_data = {**basic_data}
        _merge(char_data, pvp_data)
        _merge(char_data, raid_data)
        _merge(char_data, mythicplus_data)
        _merge(char_data, slow_data)
        _merge(char_data, guild_data)
        return char_key, char_data

    async def _async_update_data(self):
        """Update data via library."""
        try:
            all_data = {}

            # Needed by the PvP brackets to spot ratings from older seasons
            await self._fetch_pvp_season()

            # All characters at once; the client limits the requests in flight
            for char_key, char_data in await asyncio.gather(
                *(self._fetch_character(character) for character in self.characters)
            ):
                all_data[char_key] = char_data


            await self._apply_pvp_leaderboards(all_data)

            # Fetch server data for each unique realm and game version
            previous_servers = self._previous("servers")
            server_data = {
                realm_key: realm_data or previous_servers.get(realm_key, {})
                for realm_key, realm_data in (await self._fetch_all_server_data()).items()
            }

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
            _merge(region_data, self._classic_pvp_region_data())
            _merge(region_data, await self._mythic_season_region_data())

            leaderboards = await self._fetch_mythic_leaderboards()
            all_data["mythic_leaderboards"] = leaderboards.get("realms") or {}
            if leaderboards.get("affixes"):
                region_data["mythicplus_affixes"] = ", ".join(a["name"] for a in leaderboards["affixes"] if a.get("name"))
                region_data.setdefault("attrs", {})["mythicplus_affixes"] = {"affixes": leaderboards["affixes"]}
            all_data["region"] = region_data or self._previous("region")

            all_data["auctions"] = await self._fetch_auctions() or self._previous("auctions")
            all_data["guild_activity"] = dict(self._guild_activity)
            all_data["guild_roster_events"] = dict(self._guild_roster_events)
            all_data["guild_crests"] = dict(self._guild_crests)

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


def cache_store_key(entry_id: str) -> str:
    """Storage key for the item icons and slow character data of a config entry."""
    return f"{DOMAIN}.{entry_id}.cache"


def parse_item_ids(value: Any) -> List[int]:
    """Item IDs from a comma or space separated string, e.g. "210796, 224025"."""
    ids = []
    for part in re.split(r"[,;\s]+", str(value or "")):
        if part.isdigit() and int(part) not in ids:
            ids.append(int(part))
    return ids


async def async_create_coordinator(hass: HomeAssistant, entry: ConfigEntry) -> WoWDataUpdateCoordinator:
    """Create the shared coordinator for a config entry and fetch initial data."""
    characters = entry_characters(entry)

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
        game_version=entry_game_version(entry),
        realms=realm_keys(hass, entry, characters),
    )
    coordinator.entry_id = entry.entry_id
    # Gold sensors exist only while the region has a Battle.net account entry
    coordinator.gold_characters = await async_gold_characters(hass, entry.data[CONF_REGION])
    coordinator.account_linked = coordinator.gold_characters is not None
    # Icons and slow character data of the last run spare most requests after a reload
    coordinator._cache_store = Store(hass, 1, cache_store_key(entry.entry_id))
    coordinator.load_cache(await coordinator._cache_store.async_load())
    await coordinator.async_config_entry_first_refresh()
    return coordinator


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up WoW Blizzard sensors based on a config entry."""
    if is_account_entry(entry):
        _setup_account_sensors(hass, entry, async_add_entities)
        return
    coordinator: WoWDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    gold_characters = coordinator.gold_characters or set()
    entity_registry = er.async_get(hass)
    features = coordinator.features
    base = unique_base(entry)

    # Realm and region sensors (realms subentry); character sensors are
    # added below their character subentry
    entities = []
    by_subentry: Dict[Optional[str], list] = {}

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
        char_data = (coordinator.data or {}).get(char_key) or {}
        if features[CONF_ENABLE_GUILD] and char_data.get("guild_path"):
            # Guild sensors only for characters in a guild (reload after joining one);
            # roster and achievements only where the API answered for that guild
            sensor_types += [
                key for key in version_sensors["guild"]
                if key == "guild_members" or key in char_data
            ]
        by_subentry.setdefault(character.get("subentry_id"), []).extend(
            WoWCharacterSensor(coordinator, sensor_type, char_key, name, realm, game_version)
            for sensor_type in sensor_types
        )
        # Gold comes from the Battle.net account entry, only for characters of
        # that account (Blizzard has no gold for Classic Progression and Anniversary)
        key = gold_key(game_version, coordinator.client.realm_to_slug(realm), name)
        if key in gold_characters:
            by_subentry[character.get("subentry_id")].append(
                WoWCharacterGoldSensor(coordinator, key, char_key, name, realm, game_version)
            )
        else:
            # Login removed (or character not on the account): drop the old gold sensor
            id_base = char_key.replace(f"{realm}-{name}", f"{realm}_{name}", 1)
            stale = entity_registry.async_get_entity_id("sensor", DOMAIN, f"{DOMAIN}_{id_base}_character_gold")
            if stale:
                entity_registry.async_remove(stale)

    # Server sensors
    if features[CONF_ENABLE_SERVER_STATUS]:
        for realm_key, realm in coordinator.realms.items():
            for sensor_type in SERVER_SENSOR_TYPES:
                if "ruleset_id" in realm and sensor_type != "realm_status":
                    # WoW Forever rulesets only report their status
                    continue
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
            entities.append(WoWRegionSensor(coordinator, sensor_type, base))

    # Mythic+ season (Retail)
    if features[CONF_ENABLE_MYTHIC_PLUS] and coordinator.has_retail:
        entities.append(WoWRegionSensor(coordinator, "mythicplus_season", base))

    # PvP seasons of Classic Progression and Anniversary
    if features[CONF_ENABLE_PVP]:
        for game_version in sorted({coordinator.game_version} & {"classic", "classicann"}):
            entities.append(WoWRegionSensor(coordinator, f"pvp_season_{game_version}", base))

    # PvP season and title cutoffs (Retail)
    if features[CONF_ENABLE_PVP] and coordinator.has_retail:
        for sensor_type in ("pvp_season", "pvp_cutoff_gladiator", "pvp_cutoff_hero"):
            entities.append(WoWRegionSensor(coordinator, sensor_type, base))

    # Mythic+ leaderboards per Retail realm and the weekly affixes (opt-in)
    if features[CONF_ENABLE_MYTHIC_LEADERBOARD] and coordinator.has_retail:
        entities.append(WoWRegionSensor(coordinator, "mythicplus_affixes", base))
        for realm_key, realm in coordinator.realms.items():
            if realm["game_version"] == "retail":
                entities.append(
                    WoWRealmLeaderboardSensor(coordinator, "mythicplus_realm_best", realm_key, realm["realm"], "retail")
                )

    # Auction prices per tracked item
    for game_version, enabled in (("retail", coordinator.has_retail), ("classic", coordinator.has_classic_progression)):
        if enabled:
            for item_id in coordinator.auction_items:
                entities.append(WoWAuctionSensor(coordinator, game_version, item_id, base))

    async_add_entities(entities, config_subentry_id=group_subentry_id(entry, SUBENTRY_REALMS))
    for subentry_id, character_entities in by_subentry.items():
        if subentry_id is not None and subentry_id not in entry.subentries:
            # Character deleted while the entry was loading; the reload follows
            continue
        async_add_entities(character_entities, config_subentry_id=subentry_id)


def _setup_account_sensors(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    """Sensors of the Battle.net account entry (totals, collections, login)."""
    account: AccountCoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    data = account.data or {}
    collections = set(ACCOUNT_COLLECTIONS) | {"account_transmogs"}
    async_add_entities(
        WoWAccountSensor(account, sensor_type, unique_base(entry))
        for sensor_type in ACCOUNT_SENSOR_TYPES
        # Collections the API does not answer for (e.g. housing decor) are left out
        if not (data and sensor_type in collections and sensor_type not in data)
    )


def _game_version_label(game_version: str) -> str:
    """Human readable game version label."""
    return GAME_VERSIONS.get(game_version, {}).get("label", game_version)


class WoWCharacterSensor(CoordinatorEntity, SensorEntity):
    """Representation of a WoW character sensor."""

    # Gear details and other lists are large and change rarely; keep them out of the recorder
    _unrecorded_attributes = frozenset({
        "equipped_items", "equipped_items_list", "factions", "professions",
        "talent_list", "talent_points", "glyphs", "loadout_code", "dungeons", "pets",
        "categories", "recent_achievements", "quests", "appearances_per_slot", "best_runs",
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
        char_data = self._char_data
        value = char_data.get(self._sensor_type)
        if value is None and self._sensor_type in NO_VALUE_TEXT and "character_level" in char_data:
            # Profile loaded, but no title / no guild: say so instead of "unknown"
            return no_value_text(self._sensor_type, self.coordinator.client.locale)
        return value

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
            # Language-independent: "ALLIANCE", "HORDE" or "NEUTRAL"
            "faction_type": char_data.get("faction_type"),
            "active_spec": char_data.get("spec"),
            "gender": char_data.get("gender"),
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


class WoWCharacterGoldSensor(WoWCharacterSensor):
    """Gold of a character, from the Battle.net account entry."""

    def __init__(self, coordinator, key: str, char_key: str, name: str, realm: str, game_version: str):
        """Initialize the sensor."""
        super().__init__(coordinator, "character_gold", char_key, name, realm, game_version)
        self._region = coordinator.client.region
        self._gold_key = key

    @property
    def _account_data(self) -> Dict[str, Any]:
        account = account_coordinator(self.hass, self._region)
        return (account.data if account is not None else None) or {}

    @property
    def _gold(self) -> Dict[str, Any]:
        return (self._account_data.get("characters") or {}).get(self._gold_key) or {}

    async def async_added_to_hass(self) -> None:
        """Also update when the account entry has new values (it may load later)."""
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(self.hass, account_signal(self._region), self.async_write_ha_state)
        )

    @property
    def native_value(self):
        """Gold of the character."""
        return self._gold.get("character_gold")

    @property
    def extra_state_attributes(self):
        """Gold gained/lost, deaths and location, plus whether the login is valid."""
        attributes = dict(super().extra_state_attributes or {})
        attributes.update((self._gold.get("attrs") or {}).get("character_gold") or {})
        attributes["login_valid"] = self._account_data.get("login_valid", False)
        return attributes


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
        if self._realm_key != self._realm or GAME_VERSIONS.get(self._game_version, {}).get("realmless"):
            # Also for WoW Forever, whose "realm" is a ruleset such as "Normal"
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
            # One region device per game version entry; Retail keeps the plain name
            "name": f"WoW {self._region.upper()}" + (
                "" if self.coordinator.game_version == "retail"
                else f" ({_game_version_label(self.coordinator.game_version)})"
            ),
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
    def entity_picture(self) -> Optional[str]:
        """The item icon."""
        return self._auction.get("item_icon")

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
            "item_icon": auction.get("item_icon"),
            "quality": auction.get("quality"),
            "quality_color": ITEM_QUALITY_COLORS.get(auction.get("quality") or "", None),
            "category": "auction",
        }

    @property
    def device_info(self):
        """Return device info."""
        return {
            "identifiers": {(DOMAIN, f"auctions_{self._region}")},
            "name": f"WoW {self._region.upper()} Auction House" + (
                "" if self._game_version == "retail" else f" ({_game_version_label(self._game_version)})"
            ),
            "manufacturer": "Blizzard Entertainment",
            "model": "World of Warcraft Auction House",
            "entry_type": DeviceEntryType.SERVICE,
        }


class WoWAccountSensor(CoordinatorEntity, SensorEntity):
    """Account-wide sensor from the player's Battle.net login."""

    def __init__(self, coordinator: "AccountCoordinator", sensor_type: str, entry_id: str):
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
        return self.coordinator.data or {}

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
            **((self._account.get("attrs") or {}).get(self._sensor_type) or {}),
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
