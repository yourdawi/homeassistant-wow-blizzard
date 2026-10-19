"""Constants for the WoW Blizzard API integration"""

DOMAIN = "wow_blizzard"

# Config flow
CONF_CLIENT_ID = "client_id"
CONF_CLIENT_SECRET = "client_secret"
CONF_REGION = "region"
CONF_REALM = "realm"
CONF_CHARACTER_NAME = "character_name"
CONF_CHARACTERS = "characters"
CONF_ENABLE_SERVER_STATUS = "enable_server_status"
CONF_ENABLE_PVP = "enable_pvp"
CONF_ENABLE_RAIDS = "enable_raids"
CONF_ENABLE_MYTHIC_PLUS = "enable_mythic_plus"
CONF_ENABLE_HALL_OF_FAME = "enable_hall_of_fame"
CONF_ENABLE_CHARACTER_DETAILS = "enable_character_details"
CONF_ENABLE_COLLECTIONS = "enable_collections"
CONF_ENABLE_GUILD = "enable_guild"
CONF_ENABLE_REGION_DATA = "enable_region_data"
CONF_GAME_VERSION = "game_version"
CONF_LOCALE = "locale"

# API URLs
API_URLS = {
    "us": "https://us.api.blizzard.com",
    "eu": "https://eu.api.blizzard.com",
    "kr": "https://kr.api.blizzard.com",
    "tw": "https://tw.api.blizzard.com",
    "cn": "https://gateway.battlenet.com.cn",
}

TOKEN_URLS = {
    "us": "https://us.battle.net/oauth/token",
    "eu": "https://eu.battle.net/oauth/token",
    "kr": "https://kr.battle.net/oauth/token",
    "tw": "https://tw.battle.net/oauth/token",
    "cn": "https://www.battlenet.com.cn/oauth/token",
}

# Default values
DEFAULT_REGION = "us"
DEFAULT_SCAN_INTERVAL = 300  # 5 minutes
# Character details, collections and guilds change rarely. Character data is
# only updated by Blizzard on logout, so these are refetched when the last
# login changes, and otherwise at most this often.
SLOW_REFRESH_INTERVAL = 6 * 3600
GUILD_REFRESH_INTERVAL = 3600

# Game versions and their Blizzard API namespace suffixes.
# The namespace is built as "{type}{suffix}-{region}", e.g. "profile-classic1x-eu".
# Versions with more than one candidate are probed in order during setup and the
# first suffix that returns a realm index is stored with the character.
GAME_VERSIONS = {
    "retail": {"label": "Retail", "namespaces": [""]},
    "classic": {"label": "Classic Progression", "namespaces": ["-classic"]},
    "classic1x": {"label": "Classic Era", "namespaces": ["-classic1x"]},
    "classicann": {"label": "Classic Anniversary", "namespaces": ["-classicann"]},
    # WoW: Forever (launch 2026-11-04). Blizzard has not documented its API
    # namespace yet, so these are candidates; update once it is published.
    "forever": {"label": "WoW Forever", "namespaces": ["-forever", "-camelot"]},
}
CONF_NAMESPACE_SUFFIX = "namespace_suffix"

# Hall of Fame (public worldofwarcraft.blizzard.com GraphQL endpoint).
# Known persisted query hashes; if Blizzard rotates them, the client re-reads
# the current ones from the leaderboard JS bundle.
HOF_SITE_URL = "https://worldofwarcraft.blizzard.com"
HOF_QUERY_HASHES = {
    "GetAllMythicRaids": "b0c38f74f1ea2fcc1e6ac8e1a46b3f5606d6fcba7a9e41593808beb43fc41511",
    "GetMythicRaidLeaderboard": "f5e84323b0ee6f94b597ce503c186b07bc8c64303bc07476e058d3fd8a38ece1",
}
HOF_VARIANT = "worldsoul"
# The Hall of Fame is global; the site only serves it under the "us" path.
HOF_REGION = "us"
# Any existing raid page embeds the leaderboard bundle that holds the hashes.
HOF_PROBE_RAID = "nerubar-palace"

# Sensor types - Basic Character Data
BASIC_SENSOR_TYPES = {
    "character_level": {
        "name": "Level",
        "icon": "mdi:star",
        "unit": "level",
        "device_class": None,
        "state_class": "measurement",
    },
    "character_item_level": {
        "name": "Item Level",
        "icon": "mdi:sword",
        "unit": "ilvl",
        "device_class": None,
        "state_class": "measurement",
    },
    "guild_name": {
        "name": "Guild",
        "icon": "mdi:account-group",
        "unit": None,
        "device_class": None,
    },
    "achievement_points": {
        "name": "Achievement Points",
        "icon": "mdi:trophy",
        "unit": "points",
        "device_class": None,
        "state_class": "measurement",
    },
    "character_equipment": {
        "name": "Equipment Details",
        "icon": "mdi:shield-account",
        "unit": "items",
        "device_class": None,
    },
    "character_status": {
        "name": "Profile Status",
        "icon": "mdi:account-check",
        "unit": None,
        "device_class": "enum",
        "options": ["valid", "invalid", "not_found"],
    },
}

# Server Status Sensors
SERVER_SENSOR_TYPES = {
    "realm_status": {
        "name": "Realm Status",
        "icon": "mdi:server",
        "unit": None,
        "device_class": None,
    },
    "realm_population": {
        "name": "Realm Population",
        "icon": "mdi:account-multiple",
        "unit": None,
        "device_class": None,
    },
    "realm_queue": {
        "name": "Queue",
        "icon": "mdi:clock-outline",
        "unit": None,
        "device_class": None,
    },
}

# PvP Sensors
PVP_SENSOR_TYPES = {
    "pvp_2v2_rating": {
        "name": "2v2 Arena Rating",
        "icon": "mdi:sword-cross",
        "unit": "rating",
        "device_class": None,
        "state_class": "measurement",
    },
    "pvp_3v3_rating": {
        "name": "3v3 Arena Rating", 
        "icon": "mdi:sword-cross",
        "unit": "rating",
        "device_class": None,
        "state_class": "measurement",
    },
    "pvp_rbg_rating": {
        "name": "RBG Rating",
        "icon": "mdi:flag",
        "unit": "rating",
        "device_class": None,
        "state_class": "measurement",
    },
    "pvp_honor_level": {
        "name": "Honor Level",
        "icon": "mdi:shield-star",
        "unit": "level",
        "device_class": None,
        "state_class": "measurement",
    },
    "pvp_wins_season": {
        "name": "PvP Wins (Season)",
        "icon": "mdi:trophy-award",
        "unit": "wins",
        "device_class": None,
        "state_class": "measurement",
    },
    "pvp_honorable_kills": {
        "name": "Honorable Kills",
        "icon": "mdi:sword",
        "unit": "kills",
        "device_class": None,
        "state_class": "total_increasing",
    },
    "pvp_rank": {
        "name": "PvP Rank",
        "icon": "mdi:chevron-triple-up",
        "unit": None,
        "device_class": None,
        "state_class": "measurement",
    },
}

# Raid Progress Sensors  
RAID_SENSOR_TYPES = {
    "raid_progress_lfr": {
        "name": "LFR Progress",
        "icon": "mdi:castle",
        "unit": "bosses",
        "device_class": None,
        "state_class": "measurement",
    },
    "raid_progress_normal": {
        "name": "Normal Progress",
        "icon": "mdi:castle",
        "unit": "bosses", 
        "device_class": None,
        "state_class": "measurement",
    },
    "raid_progress_heroic": {
        "name": "Heroic Progress",
        "icon": "mdi:castle",
        "unit": "bosses",
        "device_class": None,
        "state_class": "measurement",
    },
    "raid_progress_mythic": {
        "name": "Mythic Progress",
        "icon": "mdi:castle",
        "unit": "bosses",
        "device_class": None,
        "state_class": "measurement",
    },
    "raid_kills_total": {
        "name": "Total Boss Kills",
        "icon": "mdi:skull",
        "unit": "kills",
        "device_class": None,
        "state_class": "measurement",
    },
}

# Mythic+ Sensors
MYTHICPLUS_SENSOR_TYPES = {
    "mythicplus_score": {
        "name": "M+ Score",
        "icon": "mdi:diamond-stone",
        "unit": "score",
        "device_class": None,
        "state_class": "measurement",
    },
    "mythicplus_best_run": {
        "name": "Best M+ Level",
        "icon": "mdi:trending-up",
        "unit": "level",
        "device_class": None,
        "state_class": "measurement",
    },
    "mythicplus_runs_completed": {
        "name": "M+ Runs Completed",
        "icon": "mdi:run-fast",
        "unit": "runs",
        "device_class": None,
        "state_class": "measurement",
    },
    "mythicplus_runs_timed": {
        "name": "M+ Runs Timed",
        "icon": "mdi:timer",
        "unit": "runs", 
        "device_class": None,
        "state_class": "measurement",
    },
    "mythicplus_weekly_best": {
        "name": "Weekly Best M+",
        "icon": "mdi:calendar-week",
        "unit": "level",
        "device_class": None,
        "state_class": "measurement",
    },
}

# Character detail sensors (professions, stats, talents, ...)
DETAIL_SENSOR_TYPES = {
    "professions": {
        "name": "Professions",
        "icon": "mdi:hammer-wrench",
        "unit": None,
        "device_class": None,
    },
    "stat_health": {
        "name": "Health",
        "icon": "mdi:heart",
        "unit": "HP",
        "device_class": None,
        "state_class": "measurement",
    },
    "stat_crit": {
        "name": "Critical Strike",
        "icon": "mdi:target",
        "unit": "%",
        "device_class": None,
        "state_class": "measurement",
    },
    "stat_haste": {
        "name": "Haste",
        "icon": "mdi:run-fast",
        "unit": "%",
        "device_class": None,
        "state_class": "measurement",
    },
    "stat_mastery": {
        "name": "Mastery",
        "icon": "mdi:star-four-points",
        "unit": "%",
        "device_class": None,
        "state_class": "measurement",
    },
    "stat_versatility": {
        "name": "Versatility",
        "icon": "mdi:shield-sword",
        "unit": "%",
        "device_class": None,
        "state_class": "measurement",
    },
    "active_title": {
        "name": "Title",
        "icon": "mdi:card-account-details-star",
        "unit": None,
        "device_class": None,
    },
    "reputations": {
        "name": "Reputations",
        "icon": "mdi:handshake",
        "unit": "factions",
        "device_class": None,
        "state_class": "measurement",
    },
    "talents": {
        "name": "Talents",
        "icon": "mdi:file-tree",
        "unit": None,
        "device_class": None,
    },
    "dungeons_completed": {
        "name": "Dungeons Completed",
        "icon": "mdi:gate",
        "unit": "dungeons",
        "device_class": None,
        "state_class": "measurement",
    },
    "deaths": {
        "name": "Deaths",
        "icon": "mdi:grave-stone",
        "unit": "deaths",
        "device_class": None,
        "state_class": "total_increasing",
    },
    "quests_completed": {
        "name": "Quests Completed",
        "icon": "mdi:exclamation",
        "unit": "quests",
        "device_class": None,
        "state_class": "total_increasing",
    },
    "hunter_pet": {
        "name": "Hunter Pet",
        "icon": "mdi:paw",
        "unit": None,
        "device_class": None,
    },
}

# Collection sensors (Retail only)
COLLECTION_SENSOR_TYPES = {
    "mounts_collected": {
        "name": "Mounts",
        "icon": "mdi:horse",
        "unit": "mounts",
        "device_class": None,
        "state_class": "measurement",
    },
    "pets_collected": {
        "name": "Pets",
        "icon": "mdi:cat",
        "unit": "pets",
        "device_class": None,
        "state_class": "measurement",
    },
    "toys_collected": {
        "name": "Toys",
        "icon": "mdi:teddy-bear",
        "unit": "toys",
        "device_class": None,
        "state_class": "measurement",
    },
    "heirlooms_collected": {
        "name": "Heirlooms",
        "icon": "mdi:treasure-chest",
        "unit": "heirlooms",
        "device_class": None,
        "state_class": "measurement",
    },
}

# Guild sensors, shown on the character device
GUILD_SENSOR_TYPES = {
    "guild_members": {
        "name": "Guild Members",
        "icon": "mdi:account-group-outline",
        "unit": "members",
        "device_class": None,
        "state_class": "measurement",
    },
}

# Region-wide sensors (WoW Token, weekly reset)
REGION_SENSOR_TYPES = {
    "wow_token_price": {
        "name": "WoW Token Price",
        "icon": "mdi:gold",
        "unit": "g",
        "device_class": None,
        "state_class": "measurement",
    },
    "wow_token_price_classic": {
        "name": "WoW Token Price (Classic)",
        "icon": "mdi:gold",
        "unit": "g",
        "device_class": None,
        "state_class": "measurement",
    },
    "weekly_reset": {
        "name": "Weekly Reset",
        "icon": "mdi:calendar-refresh",
        "unit": None,
        "device_class": "timestamp",
    },
}

# Hall of Fame Leaderboard Sensors
HOF_SENSOR_TYPES = {
    "hall_of_fame": {
        "name": "Hall of Fame",
        "icon": "mdi:crown",
        "unit": None,
        "device_class": None,
    },
}

# Combine all sensor types
ALL_SENSOR_TYPES = {
    **BASIC_SENSOR_TYPES,
    **SERVER_SENSOR_TYPES,
    **PVP_SENSOR_TYPES,
    **RAID_SENSOR_TYPES,
    **MYTHICPLUS_SENSOR_TYPES,
    **DETAIL_SENSOR_TYPES,
    **COLLECTION_SENSOR_TYPES,
    **GUILD_SENSOR_TYPES,
    **REGION_SENSOR_TYPES,
    **HOF_SENSOR_TYPES,
}

# Character sensor groups, keyed by the group names used per game version
CHARACTER_SENSOR_GROUPS = {
    "basic": BASIC_SENSOR_TYPES,
    "pvp": PVP_SENSOR_TYPES,
    "raid": RAID_SENSOR_TYPES,
    "mythicplus": MYTHICPLUS_SENSOR_TYPES,
    "details": DETAIL_SENSOR_TYPES,
    "collections": COLLECTION_SENSOR_TYPES,
    "guild": GUILD_SENSOR_TYPES,
}

# Character sensors per game version, verified against the live API (EU, 2026-10).
# None means every sensor of the group is available.
VERSION_SENSOR_SUPPORT = {
    "retail": {
        "basic": None,
        "pvp": {"pvp_2v2_rating", "pvp_3v3_rating", "pvp_rbg_rating", "pvp_honor_level",
                "pvp_wins_season", "pvp_honorable_kills"},
        "raid": None,
        "mythicplus": None,
        "details": None,
        "collections": None,
        "guild": None,
    },
    # Classic Progression (currently Mists of Pandaria): no professions, titles
    # list, dungeon encounters or collections endpoints; no versatility stat
    "classic": {
        "basic": None,
        "pvp": {"pvp_2v2_rating", "pvp_3v3_rating", "pvp_wins_season", "pvp_honorable_kills"},
        "details": {"stat_health", "stat_crit", "stat_haste", "stat_mastery", "active_title",
                    "reputations", "talents", "deaths", "quests_completed", "hunter_pet"},
        "guild": None,
    },
    # Classic Anniversary (Burning Crusade): no achievements
    "classicann": {
        "basic": {"character_level", "character_item_level", "guild_name", "character_equipment",
                  "character_status"},
        "pvp": {"pvp_2v2_rating", "pvp_3v3_rating", "pvp_wins_season", "pvp_honorable_kills"},
        "details": {"stat_health", "stat_crit", "stat_haste", "active_title", "reputations",
                    "talents", "hunter_pet"},
        "guild": None,
    },
    # Classic Era (Vanilla): no achievements, no arenas, but the old PvP rank
    "classic1x": {
        "basic": {"character_level", "character_item_level", "guild_name", "character_equipment",
                  "character_status"},
        "pvp": {"pvp_honorable_kills", "pvp_rank"},
        "details": {"stat_health", "stat_crit", "active_title", "reputations", "talents",
                    "hunter_pet"},
        "guild": None,
    },
    # WoW Forever: API coverage is unknown until launch, so only the
    # profile-based basics are exposed. Missing values stay unknown.
    "forever": {
        "basic": None,
    },
}

# Item quality colors for UI, keyed by the API's quality type
ITEM_QUALITY_COLORS = {
    "POOR": "#9D9D9D",
    "COMMON": "#FFFFFF",
    "UNCOMMON": "#1EFF00",
    "RARE": "#0070DD",
    "EPIC": "#A335EE",
    "LEGENDARY": "#FF8000",
    "ARTIFACT": "#E6CC80",
    "HEIRLOOM": "#00CCFF",
}

# Class colors for UI, keyed by playable class ID (names are localized by the API)
CLASS_COLORS = {
    1: "#C79C6E",   # Warrior
    2: "#F58CBA",   # Paladin
    3: "#ABD473",   # Hunter
    4: "#FFF569",   # Rogue
    5: "#FFFFFF",   # Priest
    6: "#C41F3B",   # Death Knight
    7: "#0070DE",   # Shaman
    8: "#69CCF0",   # Mage
    9: "#9482C9",   # Warlock
    10: "#00FF96",  # Monk
    11: "#FF7D0A",  # Druid
    12: "#A330C9",  # Demon Hunter
    13: "#33937F",  # Evoker
}


def get_sensor_types_for_version(game_version: str) -> dict:
    """Return the character sensor groups applicable for a given game version.

    Returns a dict with keys: basic, pvp, raid, mythicplus, details, collections, guild.
    Each value is a dict of sensor_type -> config (subset of the group's sensors);
    groups a version does not support are empty. Unknown versions get the basics.
    """
    support = VERSION_SENSOR_SUPPORT.get(game_version, VERSION_SENSOR_SUPPORT["forever"])
    result = {}
    for group, sensors in CHARACTER_SENSOR_GROUPS.items():
        if group not in support:
            result[group] = {}
            continue
        allowed = support[group]
        result[group] = {
            key: config for key, config in sensors.items()
            if allowed is None or key in allowed
        }
    return result
