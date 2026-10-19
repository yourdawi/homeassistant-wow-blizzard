"""The WoW Blizzard API integration."""
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.storage import Store

from .const import DOMAIN, CONF_CLIENT_ID, CONF_CLIENT_SECRET, CONF_REGION, CONF_LOCALE
from .api_client import WoWBlizzardAPIClient
from .sensor import async_create_coordinator, account_issue_id, account_store_key

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.IMAGE, Platform.EVENT]


def _strip_cached_realms(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Remove realm lists that older versions stored in the config entry."""
    stale = [k for k in entry.data if k == "available_realms" or k.startswith("realms_")]
    if stale:
        new_data = {k: v for k, v in entry.data.items() if k not in stale}
        hass.config_entries.async_update_entry(entry, data=new_data)
        _LOGGER.debug("Removed cached realm lists from config entry: %s", stale)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up WoW Blizzard API from a config entry."""
    hass.data.setdefault(DOMAIN, {})
    _strip_cached_realms(hass, entry)

    # Test the API connection before setting up platforms
    client = WoWBlizzardAPIClient(
        entry.data[CONF_CLIENT_ID],
        entry.data[CONF_CLIENT_SECRET],
        entry.data[CONF_REGION],
        locale=entry.data.get(CONF_LOCALE),
        session=async_get_clientsession(hass),
    )

    try:
        # Test connection
        test_data = await client.get_all_realms()
    except Exception as err:
        _LOGGER.error("Failed to connect to Blizzard API: %s", err)
        raise ConfigEntryNotReady(f"Unable to connect to Blizzard API: {err}") from err
    if not test_data:
        raise ConfigEntryNotReady("Unable to connect to Blizzard API")

    # One coordinator feeds all platforms (sensor, image)
    coordinator = await async_create_coordinator(hass, entry)
    hass.data[DOMAIN][entry.entry_id] = {"config": entry.data, "coordinator": coordinator}

    # Forward the setup to the platforms
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Set up options update listener
    entry.async_on_unload(entry.add_update_listener(update_listener))

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Delete stored account values and the login notice when the integration is removed."""
    await Store(hass, 1, account_store_key(entry.entry_id)).async_remove()
    ir.async_delete_issue(hass, DOMAIN, account_issue_id(entry.entry_id))


async def update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Update listener for options changes."""
    await hass.config_entries.async_reload(entry.entry_id)
