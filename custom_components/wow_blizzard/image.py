"""Support for WoW Blizzard character image entities."""
from __future__ import annotations

import logging
import re
from typing import Any

from homeassistant.components.image import ImageEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import DOMAIN, CONF_REALM, CONF_CHARACTER_NAME, CONF_GAME_VERSION, CONF_ENABLE_GUILD
from .crest import compose_crest
from .sensor import WoWDataUpdateCoordinator, _game_version_label

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up WoW Blizzard image entities based on a config entry."""
    coordinator: WoWDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]

    entities: list[ImageEntity] = [
        WoWCharacterRenderImage(
            coordinator,
            character["key"],
            character[CONF_CHARACTER_NAME],
            character[CONF_REALM],
            character[CONF_GAME_VERSION],
        )
        for character in coordinator.characters
    ]

    # One crest per guild, on the device of the first character in it
    if coordinator.features.get(CONF_ENABLE_GUILD, False):
        crests = (coordinator.data or {}).get("guild_crests") or {}
        seen = set()
        for character in coordinator.characters:
            char_data = (coordinator.data or {}).get(character["key"]) or {}
            guild_key = char_data.get("guild_key")
            if not guild_key or guild_key in seen or guild_key not in crests:
                continue
            seen.add(guild_key)
            entities.append(
                WoWGuildCrestImage(
                    coordinator,
                    guild_key,
                    character["key"],
                    character[CONF_CHARACTER_NAME],
                    character[CONF_REALM],
                    character[CONF_GAME_VERSION],
                )
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


class WoWGuildCrestImage(CoordinatorEntity, ImageEntity):
    """The guild crest (tabard), composed from Blizzard's emblem and border."""

    def __init__(
        self,
        coordinator: WoWDataUpdateCoordinator,
        guild_key: str,
        char_key: str,
        character_name: str,
        realm: str,
        game_version: str,
    ) -> None:
        """Initialize the image entity."""
        CoordinatorEntity.__init__(self, coordinator)
        ImageEntity.__init__(self, coordinator.hass)
        self._guild_key = guild_key
        self._character_name = character_name
        self._realm = realm
        self._game_version = game_version
        self._id_base = char_key.replace(f"{realm}-{character_name}", f"{realm}_{character_name}", 1)

        self._attr_has_entity_name = True
        self._attr_translation_key = "guild_crest"
        self._attr_unique_id = f"{DOMAIN}_guild_crest_{guild_key}"
        self._attr_icon = "mdi:shield-half-full"
        self._attr_content_type = "image/png"
        self._crest = self._current_crest()
        self._image: bytes | None = None
        self._attr_image_last_updated = dt_util.utcnow()

    def _current_crest(self) -> dict[str, Any]:
        return ((self.coordinator.data or {}).get("guild_crests") or {}).get(self._guild_key) or {}

    @callback
    def _handle_coordinator_update(self) -> None:
        """Compose the image again only when the guild changed its crest."""
        crest = self._current_crest()
        if crest and crest.get("source") != self._crest.get("source"):
            self._crest = crest
            self._image = None
            self._attr_image_last_updated = dt_util.utcnow()
        super()._handle_coordinator_update()

    async def _download(self, url: str) -> bytes | None:
        session = await self.coordinator.client._get_session()
        # The Classic CDN paths miss some images (403); the Retail path has the same IDs
        retail_url = re.sub(r"\.com/[a-z0-9]+-([a-z]{2})/guild/", r".com/\1/guild/", url)
        for candidate in dict.fromkeys((url, retail_url)):
            try:
                async with session.get(candidate) as response:
                    if response.status == 200:
                        return await response.read()
                    _LOGGER.debug("Guild crest image %s: HTTP %s", candidate, response.status)
            except Exception as err:  # noqa: BLE001 - shown as a missing image
                _LOGGER.debug("Could not load guild crest image %s: %s", candidate, err)
        return None

    async def async_image(self) -> bytes | None:
        """Return the composed crest (the plain emblem if Pillow is missing)."""
        if self._image is not None:
            return self._image
        crest = self._crest
        if not crest:
            return None
        emblem = await self._download(crest["emblem_url"])
        border = await self._download(crest["border_url"])
        if not emblem or not border:
            return None
        image = await self.hass.async_add_executor_job(
            compose_crest,
            emblem,
            border,
            tuple(crest.get("background_color") or (35, 35, 35)),
            tuple(crest.get("emblem_color") or (103, 103, 103)),
            tuple(crest.get("border_color") or (103, 103, 103)),
        )
        self._image = image or emblem
        return self._image

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra state attributes."""
        return {
            "emblem_url": self._crest.get("emblem_url"),
            "border_url": self._crest.get("border_url"),
            "emblem_color": self._crest.get("emblem_color"),
            "border_color": self._crest.get("border_color"),
            "background_color": self._crest.get("background_color"),
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
