"""The WoW Blizzard API integration."""
import asyncio
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady

from .const import DOMAIN, CONF_CLIENT_ID, CONF_CLIENT_SECRET, CONF_REGION
from .api_client import WoWBlizzardAPIClient

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up WoW Blizzard API from a config entry."""
    hass.data.setdefault(DOMAIN, {})
    
    # Test the API connection before setting up platforms
    client = WoWBlizzardAPIClient(
        entry.data[CONF_CLIENT_ID],
        entry.data[CONF_CLIENT_SECRET], 
        entry.data[CONF_REGION]
    )
    
    try:
        # Test connection
        test_data = await client.get_all_realms()
        if not test_data:
            raise ConfigEntryNotReady("Unable to connect to Blizzard API")
    except Exception as err:
        _LOGGER.error("Failed to connect to Blizzard API: %s", err)
        raise ConfigEntryNotReady(f"Unable to connect to Blizzard API: {err}")
    finally:
        await client.close()

    # Store the config entry data for access by platforms
    hass.data[DOMAIN][entry.entry_id] = entry.data

    # Forward the setup to the sensor platform
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Set up options update listener
    entry.async_on_unload(entry.add_update_listener(update_listener))

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok


async def update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Update listener for options changes."""
    await hass.config_entries.async_reload(entry.entry_id)