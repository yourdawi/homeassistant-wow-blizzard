"""Guild activity (achievements, boss kills) as Home Assistant events."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.event import EventEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, CONF_REALM, CONF_CHARACTER_NAME, CONF_GAME_VERSION, CONF_ENABLE_GUILD
from .sensor import WoWDataUpdateCoordinator, _game_version_label

_LOGGER = logging.getLogger(__name__)

EVENT_TYPES = ["achievement", "encounter"]


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up one guild activity event entity per guild of the configured characters."""
    coordinator: WoWDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    if not coordinator.features.get(CONF_ENABLE_GUILD, False):
        return

    entities = []
    seen = set()
    for character in coordinator.characters:
        char_data = (coordinator.data or {}).get(character["key"]) or {}
        guild_key = char_data.get("guild_key")
        if not guild_key or guild_key in seen:
            continue
        seen.add(guild_key)
        # The entity sits on the device of the first character in that guild
        entities.append(
            WoWGuildActivityEvent(
                coordinator,
                guild_key,
                char_data.get("guild_name"),
                character["key"],
                character[CONF_CHARACTER_NAME],
                character[CONF_REALM],
                character[CONF_GAME_VERSION],
            )
        )
    async_add_entities(entities)


class WoWGuildActivityEvent(CoordinatorEntity, EventEntity):
    """Fires an event for every new guild achievement or boss kill."""

    _attr_event_types = EVENT_TYPES

    def __init__(
        self,
        coordinator: WoWDataUpdateCoordinator,
        guild_key: str,
        guild_name: str | None,
        char_key: str,
        character_name: str,
        realm: str,
        game_version: str,
    ) -> None:
        """Initialize the event entity."""
        super().__init__(coordinator)
        self._guild_key = guild_key
        self._guild_name = guild_name
        self._character_name = character_name
        self._realm = realm
        self._game_version = game_version
        # Same device/ID scheme as the character sensors
        self._id_base = char_key.replace(f"{realm}-{character_name}", f"{realm}_{character_name}", 1)

        self._attr_has_entity_name = True
        self._attr_translation_key = "guild_activity"
        self._attr_unique_id = f"{DOMAIN}_guild_activity_{guild_key}"
        self._attr_icon = "mdi:bullhorn"
        # Only activity newer than what was there at startup is reported
        self._last_timestamp = self._newest_timestamp()

    def _activities(self) -> list[dict[str, Any]]:
        if not self.coordinator.data:
            return []
        return (self.coordinator.data.get("guild_activity") or {}).get(self._guild_key) or []

    def _newest_timestamp(self) -> int:
        return max((a.get("timestamp") or 0 for a in self._activities()), default=0)

    @callback
    def _handle_coordinator_update(self) -> None:
        """Trigger an event for each activity newer than the last one seen, oldest first."""
        new = [a for a in self._activities() if (a.get("timestamp") or 0) > self._last_timestamp]
        for activity in sorted(new, key=lambda a: a.get("timestamp") or 0):
            if activity.get("type") not in EVENT_TYPES:
                continue
            self._trigger_event(
                activity["type"],
                {**{k: v for k, v in activity.items() if k != "type"}, "guild": self._guild_name},
            )
        if new:
            self._last_timestamp = max(a.get("timestamp") or 0 for a in new)
        super()._handle_coordinator_update()

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
