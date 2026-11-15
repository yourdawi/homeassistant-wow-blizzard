"""Undocumented API data: Classic PvP leaderboards and 5v5, the Classic weekly
reset, experience, collection totals, the game build and realm details."""
from unittest.mock import AsyncMock, MagicMock

from homeassistant.core import HomeAssistant

from custom_components.wow_blizzard.api_client import WoWBlizzardAPIClient
from custom_components.wow_blizzard.const import get_sensor_types_for_version
from custom_components.wow_blizzard.parsers import (
    parse_connected_realm_search,
    parse_realm_lock,
    total_attributes,
)
from custom_components.wow_blizzard.sensor import WoWDataUpdateCoordinator

FEATURES = {
    "enable_server_status": True,
    "enable_pvp": True,
    "enable_character_details": True,
    "enable_collections": True,
    "enable_region_data": True,
    "enable_pvp_leaderboard": True,
}


def _coordinator(hass: HomeAssistant, game_version: str, client=None) -> WoWDataUpdateCoordinator:
    client = client or MagicMock()
    client.last_status = 200
    characters = [{
        "realm": "stormwind", "character_name": "Varian", "game_version": game_version,
        "key": "stormwind-Varian",
    }]
    return WoWDataUpdateCoordinator(hass, client, characters, dict(FEATURES), game_version=game_version)


def test_version_support():
    """5v5 in Classic Progression and Anniversary, RBG in Classic Progression, experience everywhere."""
    classic = get_sensor_types_for_version("classic")
    assert {"pvp_5v5_rating", "pvp_rbg_rating"} <= set(classic["pvp"])
    anniversary = get_sensor_types_for_version("classicann")
    assert "pvp_5v5_rating" in anniversary["pvp"]
    assert "pvp_rbg_rating" not in anniversary["pvp"]
    assert "pvp_5v5_rating" not in get_sensor_types_for_version("retail")["pvp"]
    for version in ("retail", "classic", "classicann", "classic1x", "forever"):
        assert "character_experience" in get_sensor_types_for_version(version)["basic"]


def test_parse_realm_lock():
    assert parse_realm_lock({"realm_locked_status": {
        "is_locked_for_pct": True, "is_locked_for_new_characters": False,
    }}) == {"locked_for_new_characters": False, "locked_for_transfers": True}
    assert parse_realm_lock({"id": 1}) == {}
    assert parse_realm_lock({}) == {}


def test_total_attributes():
    assert total_attributes("mounts_collected", 47, 141) == {"total": 141, "percent": 33.3}
    assert total_attributes("mounts_collected", None, 141) == {"total": 141}
    assert total_attributes("active_title", "Lord Varian", 696) == {"title_total": 696}
    # Empty indexes (e.g. Forever heirlooms) give no total
    assert total_attributes("heirlooms_collected", 0, 0) == {}
    assert total_attributes("mounts_collected", 3, None) == {}


def test_connected_realm_search_category_and_type():
    data = {"results": [{"data": {
        "id": 6113, "has_queue": False,
        "status": {"type": "UP", "name": {"en_US": "Up", "de_DE": "Verfügbar"}},
        "population": {"type": "LOW", "name": {"en_US": "Low"}},
        "realms": [{
            "slug": "stormwind", "timezone": "Europe/Paris", "locale": "enGB",
            "category": {"en_US": "Seasonal", "de_DE": "Saisonal"},
            "type": {"type": "PVP", "name": {"en_US": "PvP"}},
        }],
    }}]}
    realm = parse_connected_realm_search(data, "de_DE")["stormwind"]
    assert realm["realm_category"] == "Saisonal"
    assert realm["realm_type"] == "PVP"
    assert realm["realm_status"] == "Verfügbar"


async def test_game_build_from_namespace():
    client = WoWBlizzardAPIClient("id", "secret", "eu")
    client._make_request = AsyncMock(return_value={"power_types": [{"key": {
        "href": "https://eu.api.blizzard.com/data/wow/power-type/0?namespace=static-1.60.1_70399-forever-eu",
    }}]})
    assert await client.get_game_build("forever") == {"version": "1.60.1", "build": 70399}
    client._make_request = AsyncMock(return_value={})
    assert await client.get_game_build("forever") == {}


async def test_classic_5v5_and_leaderboard(hass: HomeAssistant) -> None:
    """Classic brackets get title cutoffs and the leaderboard rank of the current season."""
    client = MagicMock()
    client.get_character_pvp_summary = AsyncMock(return_value={"honorable_kills": 10})

    async def bracket(realm, name, slug, game_version):
        if slug == "5v5":
            return {"rating": 1850, "season": {"id": 14},
                    "season_match_statistics": {"played": 20, "won": 12, "lost": 8},
                    "weekly_match_statistics": {"played": 2, "won": 1}}
        client.last_status = 404
        return {}

    client.get_character_pvp_bracket = AsyncMock(side_effect=bracket)
    client.get_pvp_leaderboard = AsyncMock(return_value={"entries": [
        {"character": {"id": 7}, "rank": 3, "rating": 2400},
        {"character": {"id": 99}, "rank": 1, "rating": 2600},
    ]})
    coordinator = _coordinator(hass, "classic", client)
    coordinator._classic_pvp_seasons = {"classic": {"season": {"id": 14}, "titles": {
        "ARENA_5v5": [{"title": "Gladiator", "rating": 2500}],
    }}}

    # 3v3 was last played in an older season
    original = client.get_character_pvp_bracket.side_effect

    async def with_old_season(realm, name, slug, game_version):
        if slug == "3v3":
            return {"rating": 2100, "season": {"id": 13}, "season_match_statistics": {"played": 50, "won": 30}}
        return await original(realm, name, slug, game_version)

    client.get_character_pvp_bracket = AsyncMock(side_effect=with_old_season)
    result = await coordinator._fetch_pvp_data("stormwind", "Varian", "classic", {"faction_type": "ALLIANCE"})
    assert result["pvp_3v3_rating"] == 0
    assert result["attrs"]["pvp_3v3_rating"]["last_season_rating"] == 2100
    assert result["pvp_5v5_rating"] == 1850
    assert result["pvp_rbg_rating"] == 0
    assert result["pvp_wins_season"] == 12
    assert result["attrs"]["pvp_5v5_rating"]["title_cutoffs"] == [{"title": "Gladiator", "rating": 2500}]
    assert "hero_cutoff" not in result["attrs"].get("pvp_rbg_rating", {})
    assert result["pvp_leaderboard_brackets"] == {"pvp_5v5_rating": "5v5"}

    all_data = {"stormwind-Varian": {**result, "character_id": 7}}
    await coordinator._apply_pvp_leaderboards(all_data)
    client.get_pvp_leaderboard.assert_awaited_once_with(14, "5v5", "classic")
    attrs = all_data["stormwind-Varian"]["attrs"]["pvp_5v5_rating"]
    assert attrs["leaderboard_rank"] == 3
    assert attrs["leaderboard_entries"] == 2
    assert attrs["leaderboard_min_rating"] == 2400


async def test_classic_region_data(hass: HomeAssistant) -> None:
    """Classic Progression gets the weekly reset and every version the game build."""
    client = MagicMock()
    client.get_wow_token = AsyncMock(return_value={"price": 1_000_000, "last_updated_timestamp": 0})
    client.get_current_keystone_period = AsyncMock(return_value={
        "id": 1089, "start_timestamp": 1794369600000, "end_timestamp": 1794974399000,
    })
    client.get_game_build = AsyncMock(return_value={"version": "5.5.4", "build": 67732})
    coordinator = _coordinator(hass, "classic", client)

    result = await coordinator._fetch_region_data()
    client.get_current_keystone_period.assert_awaited_once_with("classic")
    assert result["weekly_reset"] == 1794974400000
    assert result["wow_token_price_classic"] == 100
    assert result["game_build"] == "5.5.4"
    assert result["attrs"]["game_build"] == {"build": 67732, "full_version": "5.5.4.67732"}

    # The build is cached for an hour
    await coordinator._fetch_region_data()
    client.get_game_build.assert_awaited_once()


async def test_collection_totals(hass: HomeAssistant) -> None:
    """Totals come from the static indexes, once a day and again on a new build."""
    lists = {
        "/data/wow/mount/index": {"mounts": [{}] * 141},
        "/data/wow/pet/index": {"pets": [{}] * 110},
        "/data/wow/toy/index": {"toys": [{}] * 13},
        # Forever answers without heirlooms
        "/data/wow/heirloom/index": {"_links": {}},
        "/data/wow/achievement/index": {"achievements": [{}] * 176},
    }
    client = MagicMock()
    client.get_static_index = AsyncMock(side_effect=lambda path, version, parse_in_thread=False: lists[path])
    coordinator = _coordinator(hass, "forever", client)

    totals = await coordinator._fetch_collection_totals()
    assert totals == {
        "mounts_collected": 141, "pets_collected": 110, "toys_collected": 13,
        "heirlooms_collected": 0, "achievements_completed": 176,
    }
    # No titles for Forever (its characters list none), no transmog index
    assert {call.args[0] for call in client.get_static_index.await_args_list} == set(lists)

    client.get_static_index.reset_mock()
    await coordinator._fetch_collection_totals()
    client.get_static_index.assert_not_awaited()

    # A new game build fetches them again
    coordinator._game_build = (coordinator._collection_totals["fetched"], {"version": "1.60.2", "build": 70500})
    await coordinator._fetch_collection_totals()
    assert client.get_static_index.await_count == len(lists)

    # Stored across restarts
    restored = _coordinator(hass, "forever", MagicMock())
    restored.load_cache(coordinator._cache_data())
    assert restored._collection_totals["totals"] == coordinator._collection_totals["totals"]
    assert restored._collection_totals["build"] == 70500


async def test_era_realm_lock(hass: HomeAssistant) -> None:
    """Classic Era realms report whether they are locked, from the connected realm."""
    client = MagicMock()
    client.realm_to_slug = WoWBlizzardAPIClient.realm_to_slug
    client.locale = "en_US"
    client.search_connected_realms = AsyncMock(return_value={"results": [{"data": {
        "id": 6113, "status": {"type": "UP", "name": "Up"}, "population": {"type": "LOW", "name": "Low"},
        "realms": [{"slug": "stormwind", "category": "Seasonal", "type": {"type": "PVP"}}],
    }}]})
    client.get_connected_realm_by_id = AsyncMock(return_value={
        "id": 6113, "realm_locked_status": {"is_locked_for_pct": True, "is_locked_for_new_characters": True},
    })
    coordinator = _coordinator(hass, "classic1x", client)

    servers = await coordinator._fetch_all_server_data()
    realm = next(iter(servers.values()))
    assert realm["realm_category"] == "Seasonal"
    assert realm["realm_type"] == "PVP"
    assert realm["locked_for_new_characters"] is True
    assert realm["locked_for_transfers"] is True
    client.get_connected_realm_by_id.assert_awaited_once_with(6113, "classic1x")

    # Cached for an hour
    await coordinator._fetch_all_server_data()
    client.get_connected_realm_by_id.assert_awaited_once()


async def test_achievement_rewards(hass: HomeAssistant) -> None:
    """Recent achievements carry their reward; rewards are cached and stored."""
    client = MagicMock()

    async def resource(realm, name, kind, game_version, parse_in_thread=False):
        if kind == "achievements":
            return {"total_quantity": 2, "total_points": 0, "recent_events": [
                {"achievement": {"id": 62041, "name": "Rank 3"}, "timestamp": 2},
                {"achievement": {"id": 62000, "name": "Level 10"}, "timestamp": 1},
            ]}
        return {}

    client.get_character_resource = AsyncMock(side_effect=resource)
    client.get_achievement = AsyncMock(side_effect=lambda achievement_id, game_version: {
        62041: {"id": 62041, "reward_description": "Earn 1 Legacy Point."},
        62000: {"id": 62000},
    }[achievement_id])
    coordinator = _coordinator(hass, "forever", client)

    result = await coordinator._fetch_details_data("forever", "Varian Wrynn", "forever", None)
    recent = result["attrs"]["achievements_completed"]["recent_achievements"]
    assert recent[0] == {"achievement": "Rank 3", "achievement_id": 62041, "timestamp": 2,
                         "reward": "Earn 1 Legacy Point."}
    assert "reward" not in recent[1]

    await coordinator._fetch_details_data("forever", "Varian Wrynn", "forever", None)
    assert client.get_achievement.await_count == 2

    restored = _coordinator(hass, "forever", MagicMock())
    restored.load_cache(coordinator._cache_data())
    assert restored._achievement_rewards == {("forever", 62041): "Earn 1 Legacy Point.", ("forever", 62000): ""}
