"""Serve the dashboard cards that ship with the integration.

The cards are one JavaScript module in www/, built from cards/ in the
repository. It is served from the integration folder and loaded on every
frontend page, so users do not need to add a dashboard resource.
"""
from __future__ import annotations

import logging
from pathlib import Path

from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.core import HomeAssistant
from homeassistant.loader import async_get_integration

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

CARDS_FILE = Path(__file__).parent / "www" / "wow-cards.js"
CARDS_URL = f"/{DOMAIN}/wow-cards.js"
_REGISTERED = f"{DOMAIN}_cards_registered"


async def async_register_cards(hass: HomeAssistant) -> None:
    """Serve the card module and add it to the frontend, once per Home Assistant run."""
    if hass.data.get(_REGISTERED) or hass.http is None:
        return

    def _modified() -> int | None:
        return int(CARDS_FILE.stat().st_mtime) if CARDS_FILE.is_file() else None

    modified = await hass.async_add_executor_job(_modified)
    if modified is None:
        # A checkout from git without a build; releases always contain the file
        _LOGGER.warning("Dashboard cards are missing (%s); run 'npm run build' in cards/", CARDS_FILE)
        return

    await hass.http.async_register_static_paths(
        [StaticPathConfig(CARDS_URL, str(CARDS_FILE), cache_headers=True)]
    )
    integration = await async_get_integration(hass, DOMAIN)
    # The version busts the browser cache after an update; the file time after a local build
    add_extra_js_url(hass, f"{CARDS_URL}?v={integration.version}-{modified}")
    hass.data[_REGISTERED] = True
