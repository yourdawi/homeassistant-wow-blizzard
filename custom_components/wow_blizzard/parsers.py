"""Parse Battle.net API documents into sensor values and attributes."""
import re
from urllib.parse import unquote
from typing import Any, Dict, Optional

from .api_client import WoWBlizzardAPIClient

# Achievement statistic IDs (stable across locales)
STATISTIC_TOTAL_DEATHS = 60
STATISTIC_QUESTS_COMPLETED = 98

HUNTER_CLASS_ID = 3

# Collection endpoints per collection sensor and the list key in the response
COLLECTION_ENDPOINTS = {
    "mounts_collected": ("collections/mounts", "mounts"),
    "pets_collected": ("collections/pets", "pets"),
    "toys_collected": ("collections/toys", "toys"),
    "heirlooms_collected": ("collections/heirlooms", "heirlooms"),
    "decor_collected": ("collections/decor", "decor_collected"),
}


def _guild_path(guild: Dict[str, Any]) -> Optional[str]:
    """Extract "{realmSlug}/{nameSlug}" from the guild link of a profile."""
    href = ((guild or {}).get("key") or {}).get("href") or ""
    match = re.search(r"/data/wow/guild/([^?]+)", href)
    return match.group(1) if match else None


def _stat_value(stats: Dict[str, Any], *keys: str) -> Optional[float]:
    """Highest percentage among rating stats such as melee/spell/ranged crit."""
    values = [
        (stats.get(key) or {}).get("value")
        for key in keys
        if isinstance(stats.get(key), dict)
    ]
    values = [v for v in values if isinstance(v, (int, float))]
    return round(max(values), 2) if values else None


def parse_statistics(stats: Dict[str, Any]) -> Dict[str, Any]:
    """Character stats endpoint to sensor values and attributes."""
    if not stats:
        return {}
    versatility = stats.get("versatility_damage_done_bonus")
    result = {
        "stat_health": stats.get("health"),
        "stat_crit": _stat_value(stats, "melee_crit", "spell_crit", "ranged_crit"),
        "stat_haste": _stat_value(stats, "melee_haste", "spell_haste", "ranged_haste"),
        "stat_mastery": _stat_value(stats, "mastery"),
        "stat_versatility": round(versatility, 2) if isinstance(versatility, (int, float)) else None,
    }
    attrs = {
        "power_type": (stats.get("power_type") or {}).get("name"),
        "power": stats.get("power"),
    }
    for key in ("strength", "agility", "intellect", "stamina", "spirit", "armor"):
        if isinstance(stats.get(key), dict):
            attrs[key] = stats[key].get("effective")
    for key in ("attack_power", "spell_power"):
        if key in stats:
            attrs[key] = stats[key]
    result["attrs"] = {"stat_health": attrs}
    return result


def parse_professions(data: Dict[str, Any]) -> Dict[str, Any]:
    """Professions endpoint: primary profession names, skill of the newest tier."""
    if not data:
        return {}
    professions = {}
    primary_names = []
    for kind in ("primaries", "secondaries"):
        for entry in data.get(kind) or []:
            name = (entry.get("profession") or {}).get("name")
            if not name:
                continue
            tiers = [t for t in entry.get("tiers") or [] if isinstance(t, dict)]
            newest = max(tiers, key=lambda t: (t.get("tier") or {}).get("id", 0), default={})
            professions[name] = {
                "type": "primary" if kind == "primaries" else "secondary",
                "tier": (newest.get("tier") or {}).get("name"),
                "skill_points": newest.get("skill_points"),
                "max_skill_points": newest.get("max_skill_points"),
            }
            if kind == "primaries":
                primary_names.append(name)
    return {
        "professions": ", ".join(primary_names) if primary_names else None,
        "attrs": {"professions": {"professions": professions}},
    }


def parse_reputations(data: Dict[str, Any]) -> Dict[str, Any]:
    """Reputations endpoint: number of known factions, standing per faction."""
    if not data:
        return {}
    factions = {}
    for entry in data.get("reputations") or []:
        name = (entry.get("faction") or {}).get("name")
        standing = entry.get("standing") or {}
        if not name:
            continue
        text = standing.get("name") or ""
        if standing.get("max"):
            text = f"{text} ({standing.get('value', 0)}/{standing['max']})".strip()
        factions[name] = text
    return {
        "reputations": len(factions),
        "attrs": {"reputations": {"factions": factions}},
    }


def parse_talents(data: Dict[str, Any]) -> Dict[str, Any]:
    """Specializations endpoint for Retail, Classic Progression and older Classic."""
    if not data:
        return {}
    active = data.get("active_specialization") or {}

    # Retail: specializations with loadouts and hero talents
    if data.get("active_hero_talent_tree") is not None or any(
        "loadouts" in s for s in data.get("specializations") or []
    ):
        hero = (data.get("active_hero_talent_tree") or {}).get("name")
        loadout_code = None
        for spec in data.get("specializations") or []:
            if (spec.get("specialization") or {}).get("id") != active.get("id"):
                continue
            for loadout in spec.get("loadouts") or []:
                if loadout.get("is_active"):
                    loadout_code = loadout.get("talent_loadout_code")
        return {
            "talents": hero or active.get("name"),
            "attrs": {"talents": {
                "specialization": active.get("name"),
                "hero_talent_tree": hero,
                "loadout_code": loadout_code,
            }},
        }

    # Classic Progression: one talent list per specialization plus glyphs
    if active:
        talents = []
        for spec in data.get("specializations") or []:
            if (spec.get("specialization") or {}).get("id") != active.get("id"):
                continue
            for talent in spec.get("talents") or []:
                name = ((talent.get("spell_tooltip") or {}).get("spell") or {}).get("name")
                if name:
                    talents.append(name)
        glyphs = []
        for group in data.get("specialization_groups") or []:
            if group.get("is_active"):
                glyphs = [g.get("name") for g in group.get("glyphs") or [] if g.get("name")]
        return {
            "talents": active.get("name"),
            "attrs": {"talents": {
                "specialization": active.get("name"),
                "talent_list": talents,
                "glyphs": glyphs,
            }},
        }

    # Classic Era / Anniversary: talent points per tree in the active group
    for group in data.get("specialization_groups") or []:
        if not group.get("is_active"):
            continue
        points = {
            spec.get("specialization_name"): spec.get("spent_points", 0)
            for spec in group.get("specializations") or []
            if spec.get("specialization_name")
        }
        if not points:
            return {}
        return {
            "talents": " / ".join(f"{name} {spent}" for name, spent in points.items()),
            "attrs": {"talents": {
                "specialization": max(points, key=points.get),
                "talent_points": points,
            }},
        }
    return {}


def parse_dungeons(data: Dict[str, Any]) -> Dict[str, Any]:
    """Dungeon encounters: dungeons completed in the newest expansion."""
    if not data:
        return {}
    expansions = data.get("expansions") or []
    current = max(expansions, key=lambda e: (e.get("expansion") or {}).get("id", 0), default=None)
    if current is None:
        # Valid answer without any dungeon (e.g. a new character)
        return {"dungeons_completed": 0}
    dungeons = {}
    for instance in current.get("instances") or []:
        name = (instance.get("instance") or {}).get("name")
        modes = [
            # Some completed modes come without a difficulty
            (mode.get("difficulty") or {}).get("type") or "OTHER"
            for mode in instance.get("modes") or []
            if (mode.get("status") or {}).get("type") == "COMPLETE"
        ]
        if name and modes:
            dungeons[name] = sorted(set(m.lower() for m in modes))
    return {
        "dungeons_completed": len(dungeons),
        "attrs": {"dungeons_completed": {
            "expansion": (current.get("expansion") or {}).get("name"),
            "dungeons": dungeons,
        }},
    }


def parse_achievement_statistics(data: Dict[str, Any]) -> Dict[str, Any]:
    """Pick total deaths and completed quests from the achievement statistics."""
    found = {}

    def walk(category):
        for stat in category.get("statistics") or []:
            found[stat.get("id")] = stat.get("quantity")
        for sub in category.get("sub_categories") or []:
            walk(sub)

    for category in (data or {}).get("categories") or []:
        walk(category)
    result = {}
    for key, stat_id in (("deaths", STATISTIC_TOTAL_DEATHS), ("quests_completed", STATISTIC_QUESTS_COMPLETED)):
        value = found.get(stat_id)
        if isinstance(value, (int, float)):
            result[key] = int(value)
    return result


def parse_hunter_pets(data: Dict[str, Any]) -> Dict[str, Any]:
    """Hunter pets: summoned (or first active) pet as state, all pets as attribute."""
    pets = [p for p in (data or {}).get("hunter_pets") or [] if isinstance(p, dict)]
    if not pets:
        return {}
    current = next((p for p in pets if p.get("is_summoned")), None) or next(
        (p for p in pets if p.get("is_active")), None
    )
    return {
        "hunter_pet": (current or {}).get("name"),
        "attrs": {"hunter_pet": {"pets": [
            {
                "name": p.get("name"),
                "level": p.get("level"),
                "creature": (p.get("creature") or {}).get("name"),
                "slot": p.get("slot"),
                "active": bool(p.get("is_active")),
            }
            for p in pets
        ]}},
    }


def _merge(result: Dict[str, Any], part: Dict[str, Any]) -> None:
    """Merge parsed values into result, combining the per-sensor attributes."""
    for key, value in part.items():
        if key == "attrs":
            attrs = result.setdefault("attrs", {})
            for sensor, sensor_attrs in value.items():
                attrs[sensor] = {**(attrs.get(sensor) or {}), **sensor_attrs}
        else:
            result[key] = value


def bracket_slug(class_name_en: str, spec_name_en: str) -> str:
    """PvP bracket slug part for a spec, e.g. ("Death Knight", "Blood") -> "deathknight-blood"."""
    def slug(text: str) -> str:
        return re.sub(r"[^a-z]", "", (text or "").lower())
    return f"{slug(class_name_en)}-{slug(spec_name_en)}"


def parse_pvp_rewards(data: Dict[str, Any]) -> Dict[str, Any]:
    """Title rating cutoffs of a PvP season.

    Returns gladiator (3v3), hero per faction (rated battlegrounds) and the
    Solo Shuffle / Blitz legend cutoffs per specialization ID.
    """
    result: Dict[str, Any] = {"gladiator": None, "hero": {}, "shuffle": {}, "blitz": {}}
    for reward in (data or {}).get("rewards") or []:
        bracket = (reward.get("bracket") or {}).get("type")
        cutoff = reward.get("rating_cutoff")
        faction = ((reward.get("faction") or {}).get("type") or "").lower()
        spec_id = (reward.get("specialization") or {}).get("id")
        if bracket == "ARENA_3v3":
            result["gladiator"] = cutoff
        elif bracket == "BATTLEGROUNDS" and faction:
            result["hero"][faction] = cutoff
        elif bracket == "SHUFFLE" and spec_id:
            result["shuffle"][spec_id] = cutoff
        elif bracket == "BLITZ" and spec_id:
            # Blitz cutoffs are per faction; keep them apart
            result["blitz"].setdefault(spec_id, {})[faction or "all"] = cutoff
    return result


def parse_mythic_leaderboard(data: Dict[str, Any], characters: Dict[str, str]) -> Dict[str, Any]:
    """Weekly Mythic+ leaderboard of one dungeon on a connected realm.

    characters maps "realm-slug/name" (lower case) to a display name; their
    best ranking in this dungeon is reported.
    """
    groups = (data or {}).get("leading_groups") or []
    best = groups[0] if groups else {}
    own = {}
    for group in groups:
        for member in group.get("members") or []:
            profile = member.get("profile") or {}
            key = f"{(profile.get('realm') or {}).get('slug', '')}/{(profile.get('name') or '').lower()}"
            if key in characters and characters[key] not in own:
                own[characters[key]] = {
                    "ranking": group.get("ranking"),
                    "keystone_level": group.get("keystone_level"),
                }
    return {
        "dungeon": (data or {}).get("name") or ((data or {}).get("map") or {}).get("name"),
        "best_level": best.get("keystone_level"),
        "best_duration_min": round(best["duration"] / 60000, 1) if isinstance(best.get("duration"), int) else None,
        "runs": len(groups),
        "own": own,
        "affixes": [
            {
                "name": (affix.get("keystone_affix") or {}).get("name"),
                "id": (affix.get("keystone_affix") or {}).get("id"),
                "starting_level": affix.get("starting_level"),
            }
            for affix in (data or {}).get("keystone_affixes") or []
        ],
    }


def parse_guild_activity(data: Dict[str, Any]) -> list:
    """Guild activity feed as a list of plain events, newest first."""
    events = []
    for entry in (data or {}).get("activities") or []:
        activity_type = ((entry.get("activity") or {}).get("type") or "").lower()
        timestamp = entry.get("timestamp")
        if "character_achievement" in entry:
            achievement = entry["character_achievement"]
            events.append({
                "type": "achievement",
                "timestamp": timestamp,
                "character": (achievement.get("character") or {}).get("name"),
                "achievement": (achievement.get("achievement") or {}).get("name"),
                "achievement_id": (achievement.get("achievement") or {}).get("id"),
            })
        elif "encounter_completed" in entry:
            encounter = entry["encounter_completed"]
            events.append({
                "type": "encounter",
                "timestamp": timestamp,
                "encounter": (encounter.get("encounter") or {}).get("name"),
                "encounter_id": (encounter.get("encounter") or {}).get("id"),
                "difficulty": (encounter.get("mode") or {}).get("type"),
                "difficulty_name": (encounter.get("mode") or {}).get("name"),
            })
        elif activity_type:
            events.append({"type": activity_type, "timestamp": timestamp})
    return sorted(events, key=lambda e: e.get("timestamp") or 0, reverse=True)


def roster_member_key(character: Dict[str, Any]) -> str:
    """Stable key of a roster member, the end of its profile path.

    "{realmSlug}/{name}", or "{first-last}" for WoW Forever, whose roster has
    no realm and only the first name in "name". Matches character_path().
    """
    href = (character.get("key") or {}).get("href") or ""
    match = re.search(r"/profile/wow/character/([^?]+)", href)
    if match:
        return unquote(match.group(1)).lower()
    realm = (character.get("realm") or {}).get("slug") or ""
    return f"{realm}/{(character.get('name') or '').lower()}"


def parse_guild_roster(data: Dict[str, Any], class_names: Dict[int, str]) -> Dict[str, Any]:
    """Members of a guild roster and member statistics for the guild sensors.

    Returns {"members": {key: member}, "sensors": {...}}. The roster has no
    rank names, only numbers (0 is the guild master).
    """
    members: Dict[str, Dict[str, Any]] = {}
    for entry in (data or {}).get("members") or []:
        character = entry.get("character") or {}
        if not character.get("name"):
            continue
        key = roster_member_key(character)
        members[key] = {
            # WoW Forever: full "First Last" from the profile path
            "name": character.get("name") if "/" in key else key.replace("-", " ").title(),
            "realm": (character.get("realm") or {}).get("slug"),
            "level": character.get("level"),
            "class_id": (character.get("playable_class") or {}).get("id"),
            "rank": entry.get("rank"),
        }
    if not members:
        return {}

    levels = [m["level"] for m in members.values() if isinstance(m["level"], int)]
    max_level = max(levels) if levels else None
    by_rank: Dict[int, int] = {}
    by_class: Dict[str, int] = {}
    by_class_max: Dict[str, int] = {}
    for member in members.values():
        if isinstance(member["rank"], int):
            by_rank[member["rank"]] = by_rank.get(member["rank"], 0) + 1
        class_name = class_names.get(member["class_id"]) or str(member["class_id"])
        by_class[class_name] = by_class.get(class_name, 0) + 1
        if max_level is not None and member["level"] == max_level:
            by_class_max[class_name] = by_class_max.get(class_name, 0) + 1

    guild_master = next((m for m in members.values() if m["rank"] == 0), None)
    return {"members": members, "sensors": {
        "guild_max_level_members": sum(by_class_max.values()) if max_level is not None else None,
        "attrs": {
            "guild_members": {
                "members_by_rank": dict(sorted(by_rank.items())),
                "members_by_class": dict(sorted(by_class.items(), key=lambda i: -i[1])),
                "guild_master": guild_master["name"] if guild_master else None,
            },
            "guild_max_level_members": {
                "max_level": max_level,
                "members_by_class": dict(sorted(by_class_max.items(), key=lambda i: -i[1])),
            },
        },
    }}


def roster_changes(old: Dict[str, Any], new: Dict[str, Any], timestamp: int) -> list:
    """Members who joined or left between two roster snapshots, as plain events."""
    events = []
    for key in sorted(new.keys() - old.keys()):
        member = new[key]
        events.append({"type": "member_joined", "timestamp": timestamp, "character": member["name"],
                       "character_realm": member["realm"], "level": member["level"]})
    for key in sorted(old.keys() - new.keys()):
        member = old[key]
        events.append({"type": "member_left", "timestamp": timestamp, "character": member["name"],
                       "character_realm": member["realm"], "level": member["level"]})
    return events


def parse_guild_achievements(data: Dict[str, Any]) -> Dict[str, Any]:
    """Completed guild achievements, progress per category and recent completions."""
    if not data or ("achievements" not in data and "total_quantity" not in data):
        return {}
    achievements = data.get("achievements") or []
    completed = data.get("total_quantity")
    if not isinstance(completed, int):
        completed = sum(1 for a in achievements if a.get("completed_timestamp"))

    categories = {
        (entry.get("category") or {}).get("name"): {
            "quantity": entry.get("quantity"),
            "points": entry.get("points"),
        }
        for entry in data.get("category_progress") or []
        if (entry.get("category") or {}).get("name")
    }
    recent = sorted(
        (
            {
                "achievement": (event.get("achievement") or {}).get("name"),
                "achievement_id": (event.get("achievement") or {}).get("id"),
                "timestamp": event.get("timestamp"),
            }
            for event in data.get("recent_events") or []
        ),
        key=lambda e: e.get("timestamp") or 0,
        reverse=True,
    )
    return {
        "guild_achievements": completed,
        "attrs": {"guild_achievements": {
            "total_points": data.get("total_points"),
            "categories": categories,
            "recent_achievements": recent[:10],
        }},
    }


def parse_pvp_leaderboard(data: Dict[str, Any]) -> Dict[str, Any]:
    """Rank per character ID of a PvP leaderboard, and the rating needed to be on it."""
    entries = (data or {}).get("entries") or []
    if not entries:
        return {}
    ranks = {
        (entry.get("character") or {}).get("id"): entry.get("rank")
        for entry in entries
        if isinstance((entry.get("character") or {}).get("id"), int)
    }
    ratings = [entry["rating"] for entry in entries if isinstance(entry.get("rating"), int)]
    return {"ranks": ranks, "entries": len(entries), "min_rating": min(ratings) if ratings else None}


def summarize_auctions(data: Dict[str, Any], item_ids: set) -> Dict[int, Dict[str, Any]]:
    """Lowest unit price (copper) and quantity per tracked item.

    Works for commodities (unit_price) and realm auctions (buyout for the
    whole stack, or a bid only).
    """
    result: Dict[int, Dict[str, Any]] = {}
    for auction in (data or {}).get("auctions") or []:
        item_id = (auction.get("item") or {}).get("id")
        if item_id not in item_ids:
            continue
        quantity = auction.get("quantity") or 1
        unit_price = auction.get("unit_price")
        if unit_price is None and auction.get("buyout"):
            unit_price = auction["buyout"] / quantity
        entry = result.setdefault(item_id, {"min_price": None, "quantity": 0, "auctions": 0})
        entry["quantity"] += quantity
        entry["auctions"] += 1
        if unit_price is not None and (entry["min_price"] is None or unit_price < entry["min_price"]):
            entry["min_price"] = unit_price
    return result


def parse_account_characters(data: Dict[str, Any]) -> list:
    """Characters of all WoW accounts of the logged-in player."""
    characters = []
    for account in (data or {}).get("wow_accounts") or []:
        for char in account.get("characters") or []:
            # WoW Forever: no realm but a ruleset, and a surname
            ruleset = char.get("ruleset") or {}
            realm = char.get("realm") or {
                "name": ruleset.get("name"),
                "slug": WoWBlizzardAPIClient.realm_to_slug(ruleset.get("name") or "forever"),
            }
            name = char.get("name")
            if name and char.get("surname"):
                name = f"{name} {char['surname']}"
            characters.append({
                "name": name,
                "ruleset_id": ruleset.get("id"),
                "id": char.get("id"),
                "realm": realm.get("name"),
                "realm_slug": realm.get("slug"),
                "realm_id": realm.get("id"),
                "level": char.get("level"),
                "class": (char.get("playable_class") or {}).get("name"),
                "faction": (char.get("faction") or {}).get("name"),
                "account_id": account.get("id"),
            })
    return characters
