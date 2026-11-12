"""Guild activity (achievements, boss kills, members joining or leaving) as Home Assistant events."""
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

ACTIVITY_EVENT_TYPES = ["achievement", "encounter"]
ROSTER_EVENT_TYPES = ["member_joined", "member_left"]
EVENT_TYPES = ACTIVITY_EVENT_TYPES + ROSTER_EVENT_TYPES


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up one guild activity event entity per guild of the configured characters."""
    coordinator: WoWDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    if not coordinator.features.get(CONF_ENABLE_GUILD, False):
        return

    entities = []
    seen = set()
    feeds = (coordinator.data or {}).get("guild_activity") or {}
    rosters = (coordinator.data or {}).get("guild_roster_events") or {}
    for character in coordinator.characters:
        char_data = (coordinator.data or {}).get(character["key"]) or {}
        guild_key = char_data.get("guild_key")
        # Only guilds with an activity feed or a roster (not every game version has both)
        if not guild_key or guild_key in seen or (guild_key not in feeds and guild_key not in rosters):
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
    """Fires an event for every new guild achievement, boss kill, join or leave."""

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
        # Only activity newer than what was there at startup is reported. Joins
        # and leaves carry the time of the roster check, which can be newer than
        # feed entries Blizzard publishes late, so both are tracked apart.
        self._last_timestamp = self._newest_timestamp(self._activities())
        self._last_roster_timestamp = self._newest_timestamp(self._roster_events())

    async def async_added_to_hass(self) -> None:
        """Start from the newest known activity instead of "unknown" when first created."""
        await super().async_added_to_hass()
        if self.state is not None:
            # Restored from before a restart
            return
        newest = next((a for a in self._activities() if a.get("type") in ACTIVITY_EVENT_TYPES), None)
        if newest:
            # Only when the entity is new, so no automation can react to this
            self._trigger_event(
                newest["type"],
                {**{k: v for k, v in newest.items() if k != "type"}, "guild": self._guild_name},
            )
            self.async_write_ha_state()

    def _activities(self) -> list[dict[str, Any]]:
        if not self.coordinator.data:
            return []
        return (self.coordinator.data.get("guild_activity") or {}).get(self._guild_key) or []

    def _roster_events(self) -> list[dict[str, Any]]:
        if not self.coordinator.data:
            return []
        return (self.coordinator.data.get("guild_roster_events") or {}).get(self._guild_key) or []

    @staticmethod
    def _newest_timestamp(events: list[dict[str, Any]]) -> int:
        return max((a.get("timestamp") or 0 for a in events), default=0)

    def _fire_new(self, events: list[dict[str, Any]], since: int, event_types: list[str]) -> int:
        """Trigger an event for each entry newer than since, oldest first; return the newest timestamp."""
        new = [a for a in events if (a.get("timestamp") or 0) > since]
        for activity in sorted(new, key=lambda a: a.get("timestamp") or 0):
            if activity.get("type") not in event_types:
                continue
            self._trigger_event(
                activity["type"],
                {**{k: v for k, v in activity.items() if k != "type"}, "guild": self._guild_name},
            )
        return max([since] + [a.get("timestamp") or 0 for a in new])

    @callback
    def _handle_coordinator_update(self) -> None:
        """Trigger events for new guild activity and roster changes."""
        self._last_timestamp = self._fire_new(self._activities(), self._last_timestamp, ACTIVITY_EVENT_TYPES)
        self._last_roster_timestamp = self._fire_new(
            self._roster_events(), self._last_roster_timestamp, ROSTER_EVENT_TYPES
        )
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
