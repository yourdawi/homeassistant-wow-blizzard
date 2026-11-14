"""Storing the game mode (ruleset) of WoW Forever characters added without one."""
from datetime import timedelta
import logging
from types import MappingProxyType
from unittest.mock import AsyncMock

from homeassistant.config_entries import ConfigSubentryData
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.wow_blizzard.const import DOMAIN, SUBENTRY_CHARACTER
from custom_components.wow_blizzard.entries import store_forever_rulesets, track_forever_rulesets

_LOGGER = logging.getLogger(__name__)

# Character data as fetched by the coordinator, by character key
CHAR_DATA = {
    "forever-Jaina Proudmoore": {"ruleset_id": 2, "ruleset_name": "Normal", "faction_type": "ALLIANCE"},
    "normal-Arthas Menethil": {"ruleset_id": 2, "ruleset_name": "Normal"},
    "forever-Arthas Menethil": {"ruleset_id": 2, "ruleset_name": "Normal"},
    "forever-Nobody Here": {},
}


def _character(subentry_id: str, name: str, realm: str, title: str, unique_id: str, **data) -> ConfigSubentryData:
    return ConfigSubentryData(
        data=MappingProxyType({
            "realm": realm,
            "character_name": name,
            "key": f"{realm}-{name}",
            "namespace_suffix": "-forever",
            **data,
        }),
        subentry_id=subentry_id,
        subentry_type=SUBENTRY_CHARACTER,
        title=title,
        unique_id=unique_id,
    )


def _entry(hass: HomeAssistant, game_version: str = "forever") -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"game_version": game_version, "region": "eu"},
        subentries_data=[
            # Imported by login without a ruleset
            _character("imported", "Jaina Proudmoore", "forever", "Jaina Proudmoore", "forever-jaina proudmoore"),
            # Already known
            _character("known", "Arthas Menethil", "normal", "Arthas Menethil - Normal", "normal-arthas menethil", ruleset_id=2),
            # Imported as well: its ruleset realm is taken, and the user renamed it
            _character("twin", "Arthas Menethil", "forever", "My Arthas", "forever-arthas menethil"),
            # Profile not found
            _character("missing", "Nobody Here", "forever", "Nobody Here", "forever-nobody here"),
        ],
    )
    entry.add_to_hass(hass)
    return entry


async def test_store_forever_rulesets(hass: HomeAssistant) -> None:
    """Ruleset and realm are stored; titles of the user and taken unique IDs are kept."""
    entry = _entry(hass)

    assert store_forever_rulesets(hass, entry, CHAR_DATA) is True

    imported = entry.subentries["imported"]
    assert imported.data["ruleset_id"] == 2
    assert imported.data["realm"] == "normal"
    assert imported.data["key"] == "forever-Jaina Proudmoore"  # entity IDs stay the same
    assert imported.unique_id == "normal-jaina proudmoore"
    assert imported.title == "Jaina Proudmoore - Normal"

    twin = entry.subentries["twin"]
    assert twin.data["ruleset_id"] == 2
    assert twin.data["realm"] == "forever"
    assert twin.unique_id == "forever-arthas menethil"
    assert twin.title == "My Arthas"

    assert "ruleset_id" not in entry.subentries["missing"].data
    assert entry.subentries["known"].title == "Arthas Menethil - Normal"

    # Nothing left to store
    assert store_forever_rulesets(hass, entry, CHAR_DATA) is False


async def test_store_forever_rulesets_other_game_versions(hass: HomeAssistant) -> None:
    """Only WoW Forever has rulesets."""
    entry = _entry(hass, game_version="retail")
    assert store_forever_rulesets(hass, entry, CHAR_DATA) is False
    assert "ruleset_id" not in entry.subentries["imported"].data


async def test_track_forever_rulesets_after_setup(hass: HomeAssistant) -> None:
    """A profile that arrives after setup stores the ruleset and reloads the entry."""
    entry = _entry(hass)
    listener = AsyncMock()
    entry.add_update_listener(listener)
    coordinator = DataUpdateCoordinator(
        hass, _LOGGER, config_entry=entry, name="test", update_interval=timedelta(hours=1)
    )
    unsubscribe = track_forever_rulesets(hass, entry, coordinator)

    # First update: the profile was unavailable
    coordinator.async_set_updated_data({"forever-Jaina Proudmoore": {}})
    await hass.async_block_till_done()
    assert "ruleset_id" not in entry.subentries["imported"].data
    listener.assert_not_called()

    # Later update: the profile names the ruleset, the update listener reloads
    coordinator.async_set_updated_data(CHAR_DATA)
    await hass.async_block_till_done()
    assert entry.subentries["imported"].data["ruleset_id"] == 2
    listener.assert_called()

    # Stopped tracking: no more changes
    unsubscribe()
    listener.reset_mock()
    coordinator.async_set_updated_data(CHAR_DATA)
    await hass.async_block_till_done()
    listener.assert_not_called()
