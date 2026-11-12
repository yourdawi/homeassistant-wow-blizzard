"""The WoW Blizzard API integration."""
import logging
from types import MappingProxyType
from typing import Any, Dict, List

from homeassistant.config_entries import SOURCE_IMPORT, ConfigEntry, ConfigSubentry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.storage import Store

from .const import (
    ACCOUNT_GOLD_VERSIONS,
    CONF_ACCOUNT_TOKEN,
    CONF_CHARACTER_KEY,
    CONF_CHARACTER_NAME,
    CONF_CHARACTERS,
    CONF_CLIENT_ID,
    CONF_CLIENT_SECRET,
    CONF_GAME_VERSION,
    CONF_LOCALE,
    CONF_NAMESPACE_SUFFIX,
    CONF_REALM,
    CONF_REALM_KEYS,
    CONF_REGION,
    CONF_RULESET_ID,
    CONF_UNIQUE_BASE,
    DOMAIN,
    SUBENTRY_CHARACTER,
)
from .api_client import WoWBlizzardAPIClient
from .entries import (
    VERSION_ORDER,
    async_cleanup_devices,
    ensure_group_subentries,
    entry_game_version,
    character_title,
    character_unique_id,
    entry_title,
    entry_unique_id,
    realm_title,
)
from .sensor import assign_character_keys, assign_realm_keys, async_create_coordinator, account_issue_id, account_store_key

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.IMAGE, Platform.EVENT]


def _strip_cached_realms(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Remove realm lists that older versions stored in the config entry."""
    stale = [k for k in entry.data if k == "available_realms" or k.startswith("realms_")]
    if stale:
        new_data = {k: v for k, v in entry.data.items() if k not in stale}
        hass.config_entries.async_update_entry(entry, data=new_data)
        _LOGGER.debug("Removed cached realm lists from config entry: %s", stale)


def _subentry_data(character: Dict[str, Any]) -> Dict[str, Any]:
    """ConfigSubentryData of a character from the old character list."""
    data = {
        CONF_REALM: character[CONF_REALM],
        CONF_CHARACTER_NAME: character[CONF_CHARACTER_NAME],
        # The old entity key, so unique and entity IDs stay the same
        CONF_CHARACTER_KEY: character["key"],
        CONF_NAMESPACE_SUFFIX: character.get(CONF_NAMESPACE_SUFFIX),
        "level": character.get("level"),
        "character_class": character.get("character_class"),
        "race": character.get("race", ""),
    }
    if character.get(CONF_RULESET_ID) is not None:
        data[CONF_RULESET_ID] = character[CONF_RULESET_ID]
    # "Thrall - Stormrage (Retail)" -> "Thrall - Stormrage"
    display = (character.get("display_name") or "").rsplit(" (", 1)[0]
    return {
        "data": data,
        "subentry_type": SUBENTRY_CHARACTER,
        "title": display or character_title(character[CONF_CHARACTER_NAME], realm_title(character[CONF_REALM])),
        "unique_id": character_unique_id(character[CONF_REALM], character[CONF_CHARACTER_NAME]),
    }


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Split an entry with characters of several game versions into one entry per version.

    The entry keeps the main game version (Retail if present); the others are
    created through the import step. Character keys, realm keys and the old
    entry ID go along, so all unique IDs (and the history) stay the same.
    """
    if entry.version >= 3:
        return True

    region = entry.data[CONF_REGION]
    characters = assign_character_keys(entry.data.get(CONF_CHARACTERS) or [])
    old_realms = assign_realm_keys(characters)
    by_version: Dict[str, List[Dict[str, Any]]] = {}
    for character in characters:
        by_version.setdefault(character["game_version"], []).append(character)
    versions = [v for v in VERSION_ORDER if v in by_version] or ["retail"]
    main = versions[0]

    def realm_keys_for(game_version: str) -> Dict[str, str]:
        return {r["realm"]: key for key, r in old_realms.items() if r["game_version"] == game_version}

    base = {k: v for k, v in entry.data.items() if k != CONF_CHARACTERS}
    base[CONF_UNIQUE_BASE] = entry.entry_id

    data = {**base, CONF_GAME_VERSION: main, CONF_REALM_KEYS: realm_keys_for(main)}
    if main not in ACCOUNT_GOLD_VERSIONS:
        data.pop(CONF_ACCOUNT_TOKEN, None)
    unique_id = entry_unique_id(region, main)
    taken = any(e.unique_id == unique_id for e in hass.config_entries.async_entries(DOMAIN) if e.entry_id != entry.entry_id)
    hass.config_entries.async_update_entry(
        entry,
        data=data,
        title=entry_title(main, region),
        unique_id=entry.unique_id if taken else unique_id,
        version=3,
    )
    for character in by_version.get(main, []):
        sub = _subentry_data(character)
        hass.config_entries.async_add_subentry(entry, ConfigSubentry(
            data=MappingProxyType(sub["data"]),
            subentry_type=sub["subentry_type"],
            title=sub["title"],
            unique_id=sub["unique_id"],
        ))

    for game_version in versions[1:]:
        import_data = {
            **base,
            CONF_GAME_VERSION: game_version,
            CONF_REALM_KEYS: realm_keys_for(game_version),
            "subentries": [_subentry_data(c) for c in by_version[game_version]],
            "options": dict(entry.options),
        }
        if game_version not in ACCOUNT_GOLD_VERSIONS:
            import_data.pop(CONF_ACCOUNT_TOKEN, None)
        hass.async_create_task(
            hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_IMPORT}, data=import_data)
        )
    _LOGGER.info(
        "Split the World of Warcraft entry into one entry per game version: %s",
        ", ".join(f"{v} ({len(by_version.get(v, []))})" for v in versions),
    )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up one game version from a config entry."""
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
        test_data = await client.get_all_realms()
    except Exception as err:
        _LOGGER.error("Failed to connect to Blizzard API: %s", err)
        raise ConfigEntryNotReady(f"Unable to connect to Blizzard API: {err}") from err
    if not test_data:
        raise ConfigEntryNotReady("Unable to connect to Blizzard API")

    # Realms and account get their own subentries, like the characters
    ensure_group_subentries(
        hass, entry, with_account=CONF_ACCOUNT_TOKEN in entry.data and entry_game_version(entry) == "retail"
    )

    # One coordinator feeds all platforms (sensor, image, event)
    coordinator = await async_create_coordinator(hass, entry)
    hass.data[DOMAIN][entry.entry_id] = {"config": entry.data, "coordinator": coordinator}

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Characters moved between entries leave their old entry linked to the device
    await async_cleanup_devices(hass, entry.entry_id)

    # Reload on option and subentry (character) changes
    entry.async_on_unload(entry.add_update_listener(update_listener))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Delete stored account values and the login notice when the entry is removed."""
    await Store(hass, 1, account_store_key(entry.entry_id)).async_remove()
    ir.async_delete_issue(hass, DOMAIN, account_issue_id(entry.entry_id))


async def update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload after option or character changes."""
    await hass.config_entries.async_reload(entry.entry_id)
