"""Support for WoW Blizzard character image entities."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.image import ImageEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import DOMAIN, CONF_REALM, CONF_CHARACTER_NAME, CONF_GAME_VERSION
from .sensor import WoWDataUpdateCoordinator, _game_version_label

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up WoW Blizzard image entities based on a config entry."""
    coordinator: WoWDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]

    async_add_entities(
        WoWCharacterRenderImage(
            coordinator,
            character["key"],
            character[CONF_CHARACTER_NAME],
            character[CONF_REALM],
            character[CONF_GAME_VERSION],
        )
        for character in coordinator.characters
    )


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
        # Same device/ID scheme as the character sensors
        self._id_base = char_key.replace(f"{realm}-{character_name}", f"{realm}_{character_name}", 1)

        self._attr_has_entity_name = True
        self._attr_translation_key = "character_full_body_render"
        self._attr_unique_id = f"{DOMAIN}_{self._id_base}_full_body_image"
        self._attr_icon = "mdi:account-box"
        self._attr_image_url = self._current_url()
        self._attr_image_last_updated = dt_util.utcnow()

    @property
    def _char_data(self) -> dict[str, Any]:
        if not self.coordinator.data:
            return {}
        return self.coordinator.data.get(self._char_key) or {}

    def _current_url(self) -> str | None:
        char_data = self._char_data
        return char_data.get("full_body_url") or char_data.get("avatar_url")

    @callback
    def _handle_coordinator_update(self) -> None:
        """Only invalidate the cached image when the render URL changes."""
        url = self._current_url()
        if url != self._attr_image_url:
            self._attr_image_url = url
            self._cached_image = None
            self._attr_image_last_updated = dt_util.utcnow()
        super()._handle_coordinator_update()

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra state attributes."""
        char_data = self._char_data
        if not char_data:
            return {}
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
            "identifiers": {(DOMAIN, self._id_base)},
            "name": f"{self._character_name} ({self._realm})",
            "manufacturer": "Blizzard Entertainment",
            "model": "World of Warcraft Character",
            "sw_version": _game_version_label(self._game_version),
        }
