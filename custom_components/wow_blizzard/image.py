"""Support for WoW Blizzard character image entities."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.image import ImageEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .sensor import WoWDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up WoW Blizzard image entities based on a config entry."""
    entry_data = hass.data[DOMAIN].get(entry.entry_id, {})
    coordinator: WoWDataUpdateCoordinator = entry_data.get("coordinator")
    if not coordinator:
        return

    entities = []
    for character in coordinator.characters:
        realm = character["realm"]
        name = character["character_name"]
        game_version = character.get("game_version", "retail")
        char_key = f"{realm}-{name}"

        entities.append(
            WoWCharacterRenderImage(coordinator, char_key, name, realm, game_version)
        )

    async_add_entities(entities)


class WoWCharacterRenderImage(CoordinatorEntity, ImageEntity):
    """Representation of a WoW character full-body render image entity."""

    def __init__(
        self,
        coordinator: WoWDataUpdateCoordinator,
        char_key: str,
        character_name: str,
        realm: str,
        game_version: str = "retail",
    ) -> None:
        """Initialize the image entity."""
        CoordinatorEntity.__init__(self, coordinator)
        ImageEntity.__init__(self, coordinator.hass)
        self._char_key = char_key
        self._character_name = character_name
        self._realm = realm
        self._game_version = game_version

        self._attr_has_entity_name = True
        self._attr_translation_key = "character_full_body_render"
        self._attr_unique_id = f"{DOMAIN}_{realm}_{character_name}_full_body_image"
        self._attr_icon = "mdi:account-box"

    @property
    def image_url(self) -> str | None:
        """Return the URL of the image."""
        if not self.coordinator.data or self._char_key not in self.coordinator.data:
            return None
        char_data = self.coordinator.data[self._char_key]
        return char_data.get("full_body_url") or char_data.get("avatar_url")

    @property
    def image_last_updated(self):
        """Return when the image was last updated."""
        return dt_util.utcnow()

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra state attributes."""
        if not self.coordinator.data or self._char_key not in self.coordinator.data:
            return {}
        char_data = self.coordinator.data[self._char_key]
        return {
            "character_name": self._character_name,
            "realm": self._realm,
            "character_class": char_data.get("character_class"),
            "character_race": char_data.get("character_race"),
            "character_level": char_data.get("character_level"),
            "faction": char_data.get("faction"),
            "spec": char_data.get("spec"),
            "game_version": self._game_version,
            "avatar_url": char_data.get("avatar_url"),
            "full_body_url": char_data.get("full_body_url"),
        }

    @property
    def device_info(self):
        """Return device info."""
        return {
            "identifiers": {(DOMAIN, f"{self._realm}_{self._character_name}")},
            "name": f"{self._character_name} ({self._realm})",
            "manufacturer": "Blizzard Entertainment",
            "model": "World of Warcraft Character",
        }
