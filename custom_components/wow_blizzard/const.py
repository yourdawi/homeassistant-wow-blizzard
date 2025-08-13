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
FAST_SCAN_INTERVAL = 60     # 1 minute for PvP/M+ data
SLOW_SCAN_INTERVAL = 900    # 15 minutes for server status

# Current expansion/season IDs (update these when new content releases)
CURRENT_EXPANSION_ID = 10  # Dragonflight
CURRENT_SEASON_ID = 12     # Current M+ season
CURRENT_PVP_SEASON_ID = 37 # Current PvP season

# Sensor types - Basic Character Data
BASIC_SENSOR_TYPES = {
    "character_level": {
        "name": "Level",
        "icon": "mdi:star",
        "unit": "level",
        "device_class": None,
    },
    "character_item_level": {
        "name": "Item Level",
        "icon": "mdi:sword",
        "unit": "ilvl",
        "device_class": None,
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
    },
    "character_money": {
        "name": "Gold",
        "icon": "mdi:gold",
        "unit": "gold",
        "device_class": None,
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
        "name": "Queue Time",
        "icon": "mdi:clock-outline",
        "unit": "minutes",
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
    },
    "pvp_3v3_rating": {
        "name": "3v3 Arena Rating", 
        "icon": "mdi:sword-cross",
        "unit": "rating",
        "device_class": None,
    },
    "pvp_rbg_rating": {
        "name": "RBG Rating",
        "icon": "mdi:flag",
        "unit": "rating",
        "device_class": None,
    },
    "pvp_honor_level": {
        "name": "Honor Level",
        "icon": "mdi:shield-star",
        "unit": "level",
        "device_class": None,
    },
    "pvp_wins_season": {
        "name": "PvP Wins (Season)",
        "icon": "mdi:trophy-award",
        "unit": "wins",
        "device_class": None,
    },
}

# Raid Progress Sensors  
RAID_SENSOR_TYPES = {
    "raid_progress_lfr": {
        "name": "LFR Progress",
        "icon": "mdi:castle",
        "unit": "bosses",
        "device_class": None,
    },
    "raid_progress_normal": {
        "name": "Normal Progress",
        "icon": "mdi:castle",
        "unit": "bosses", 
        "device_class": None,
    },
    "raid_progress_heroic": {
        "name": "Heroic Progress",
        "icon": "mdi:castle",
        "unit": "bosses",
        "device_class": None,
    },
    "raid_progress_mythic": {
        "name": "Mythic Progress",
        "icon": "mdi:castle",
        "unit": "bosses",
        "device_class": None,
    },
    "raid_kills_total": {
        "name": "Total Boss Kills",
        "icon": "mdi:skull",
        "unit": "kills",
        "device_class": None,
    },
}

# Mythic+ Sensors
MYTHICPLUS_SENSOR_TYPES = {
    "mythicplus_score": {
        "name": "M+ Score",
        "icon": "mdi:diamond-stone",
        "unit": "score",
        "device_class": None,
    },
    "mythicplus_best_run": {
        "name": "Best M+ Level",
        "icon": "mdi:trending-up",
        "unit": "level",
        "device_class": None,
    },
    "mythicplus_runs_completed": {
        "name": "M+ Runs Completed",
        "icon": "mdi:run-fast",
        "unit": "runs",
        "device_class": None,
    },
    "mythicplus_runs_timed": {
        "name": "M+ Runs Timed",
        "icon": "mdi:timer",
        "unit": "runs", 
        "device_class": None,
    },
    "mythicplus_weekly_best": {
        "name": "Weekly Best M+",
        "icon": "mdi:calendar-week",
        "unit": "level",
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
}

# Current raid tiers (update when new raids release)
CURRENT_RAIDS = {
    "aberrus-the-shadowed-crucible": {
        "name": "Aberrus, the Shadowed Crucible",
        "total_bosses": 9,
        "expansion": "dragonflight",
    },
    "amirdrassil-the-dreams-hope": {
        "name": "Amirdrassil, the Dream's Hope", 
        "total_bosses": 9,
        "expansion": "dragonflight",
    },
    "vault-of-the-incarnates": {
        "name": "Vault of the Incarnates",
        "total_bosses": 8,
        "expansion": "dragonflight",
    },
}

# PvP Bracket mappings
PVP_BRACKETS = {
    "ARENA_2v2": "2v2",
    "ARENA_3v3": "3v3", 
    "BATTLEGROUNDS": "rbg",
}

# Mythic+ dungeons for current season
CURRENT_MYTHICPLUS_DUNGEONS = [
    "temple-of-the-jade-serpent",
    "brackenhide-hollow",
    "halls-of-infusion", 
    "uldaman-legacy-of-tyr",
    "neltharus",
    "freehold",
    "underrot",
    "everbloom",
]

# Difficulty mappings
DIFFICULTY_MAPPING = {
    1: "Normal",
    2: "Heroic", 
    3: "Raid Finder",
    4: "Mythic",
    5: "Normal (Dungeon)",
    23: "Mythic (Dungeon)",
}

# Item quality colors for UI
ITEM_QUALITY_COLORS = {
    0: "#9D9D9D",  # Poor (Gray)
    1: "#FFFFFF",  # Common (White)
    2: "#1EFF00",  # Uncommon (Green)
    3: "#0070DD",  # Rare (Blue)
    4: "#A335EE",  # Epic (Purple)
    5: "#FF8000",  # Legendary (Orange)
    6: "#E6CC80",  # Artifact (Light Orange)
    7: "#00CCFF",  # Heirloom (Light Blue)
}

# Class colors for UI
CLASS_COLORS = {
    "Death Knight": "#C41F3B",
    "Demon Hunter": "#A330C9", 
    "Druid": "#FF7D0A",
    "Evoker": "#33937F",
    "Hunter": "#ABD473",
    "Mage": "#69CCF0",
    "Monk": "#00FF96",
    "Paladin": "#F58CBA",
    "Priest": "#FFFFFF",
    "Rogue": "#FFF569",
    "Shaman": "#0070DE",
    "Warlock": "#9482C9",
    "Warrior": "#C79C6E",
}

# API Rate limits
API_RATE_LIMIT_PER_SECOND = 36000
API_RATE_LIMIT_PER_HOUR = 36000

# Error codes that should trigger re-authentication
AUTH_ERROR_CODES = [401, 403]