"""The WoW Blizzard API integration."""
import logging
from types import MappingProxyType
from typing import Any, Dict, List

from homeassistant.config_entries import SOURCE_IMPORT, ConfigEntry, ConfigSubentry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import config_validation as cv, issue_registry as ir
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.storage import Store
from homeassistant.helpers.typing import ConfigType

from .const import (
    CONF_ACCOUNT_TOKEN,
    CONF_CHARACTER_KEY,
    CONF_CHARACTER_NAME,
    CONF_CHARACTERS,
    CONF_CLIENT_ID,
    CONF_CLIENT_SECRET,
    CONF_ENTRY_TYPE,
    CONF_GAME_VERSION,
    CONF_LOCALE,
    CONF_NAMESPACE_SUFFIX,
    CONF_REALM,
    CONF_REALM_KEYS,
    CONF_REGION,
    CONF_RULESET_ID,
    CONF_UNIQUE_BASE,
    DOMAIN,
    ENTRY_TYPE_ACCOUNT,
    SUBENTRY_CHARACTER,
)
from .api_client import WoWBlizzardAPIClient
from .entries import (
    VERSION_ORDER,
    async_cleanup_devices,
    ensure_group_subentries,
    unique_base,
    character_title,
    character_unique_id,
    entry_title,
    entry_unique_id,
    realm_title,
    store_forever_rulesets,
)
from .account import (
    ACCOUNTS,
    AccountCoordinator,
    account_signal,
    account_issue_id,
    account_store_key,
    is_account_entry,
    reload_gold_entries,
)
from .frontend import async_register_cards
from .sensor import assign_character_keys, assign_realm_keys, async_create_coordinator, cache_store_key

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.IMAGE, Platform.EVENT]
# The Battle.net account entry only has sensors
ACCOUNT_PLATFORMS: list[Platform] = [Platform.SENSOR]

# Set up from the UI only
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Make the dashboard cards available."""
    await async_register_cards(hass)
    return True


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


def _start_import(hass: HomeAssistant, data: Dict[str, Any]) -> None:
    """Create an entry (game version or account) through the import step."""
    hass.async_create_task(
        hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_IMPORT}, data=data)
    )


def _account_import_data(data: Dict[str, Any], base: str) -> Dict[str, Any]:
    """Import data of the Battle.net account entry from an entry with a login."""
    return {
        CONF_ENTRY_TYPE: ENTRY_TYPE_ACCOUNT,
        **{k: data[k] for k in (CONF_CLIENT_ID, CONF_CLIENT_SECRET, CONF_REGION, CONF_LOCALE) if k in data},
        CONF_ACCOUNT_TOKEN: data[CONF_ACCOUNT_TOKEN],
        # Account sensors and stored values keep their IDs
        CONF_UNIQUE_BASE: base,
    }


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Bring entries of older versions to one entry per game version plus an account entry.

    Version 2: all characters in one entry. It is split into one entry per
    game version (the entry keeps the main one, Retail if present; the others
    are created through the import step). Character keys, realm keys and the
    old entry ID go along, so all unique IDs (and the history) stay the same.

    Version 3: the Battle.net login was stored in the Retail and Classic Era
    entries. It moves to its own account entry.
    """
    if entry.version == 2 or entry.version == 1:
        _migrate_split(hass, entry)
    if entry.version == 3:
        if CONF_ACCOUNT_TOKEN in entry.data:
            _start_import(hass, _account_import_data(dict(entry.data), unique_base(entry)))
        if unique_base(entry) != entry.entry_id:
            # Account values of a game version entry other than the original
            # one (e.g. Classic Era); the account entry uses the original's
            await Store(hass, 1, account_store_key(entry.entry_id)).async_remove()
        hass.config_entries.async_update_entry(
            entry, data={k: v for k, v in entry.data.items() if k != CONF_ACCOUNT_TOKEN}, version=4
        )
    return True


def _migrate_split(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Version 2 to 3: one entry per game version (see async_migrate_entry)."""
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

    base = {k: v for k, v in entry.data.items() if k not in (CONF_CHARACTERS, CONF_ACCOUNT_TOKEN)}
    base[CONF_UNIQUE_BASE] = entry.entry_id

    unique_id = entry_unique_id(region, main)
    taken = any(e.unique_id == unique_id for e in hass.config_entries.async_entries(DOMAIN) if e.entry_id != entry.entry_id)
    # The login stays for now; the version 3 step moves it to the account entry
    data = {**base, CONF_GAME_VERSION: main, CONF_REALM_KEYS: realm_keys_for(main)}
    if CONF_ACCOUNT_TOKEN in entry.data:
        data[CONF_ACCOUNT_TOKEN] = entry.data[CONF_ACCOUNT_TOKEN]
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
        _start_import(hass, {
            **base,
            CONF_GAME_VERSION: game_version,
            CONF_REALM_KEYS: realm_keys_for(game_version),
            "subentries": [_subentry_data(c) for c in by_version[game_version]],
            "options": dict(entry.options),
        })
    _LOGGER.info(
        "Split the World of Warcraft entry into one entry per game version: %s",
        ", ".join(f"{v} ({len(by_version.get(v, []))})" for v in versions),
    )


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up a game version or the Battle.net account from a config entry."""
    hass.data.setdefault(DOMAIN, {})
    _strip_cached_realms(hass, entry)

    client = WoWBlizzardAPIClient(
        entry.data[CONF_CLIENT_ID],
        entry.data[CONF_CLIENT_SECRET],
        entry.data[CONF_REGION],
        locale=entry.data.get(CONF_LOCALE),
        session=async_get_clientsession(hass),
    )

    if is_account_entry(entry):
        region = entry.data[CONF_REGION].lower()
        account = AccountCoordinator(hass, entry, client, Store(hass, 1, account_store_key(unique_base(entry))))
        await account.async_load_last()
        await account.async_config_entry_first_refresh()
        hass.data[DOMAIN][entry.entry_id] = {"config": entry.data, "coordinator": account}
        hass.data.setdefault(ACCOUNTS, {})[region] = account
        await hass.config_entries.async_forward_entry_setups(entry, ACCOUNT_PLATFORMS)
        # Gold sensors of the game version entries follow the account data
        signal = account_signal(region)
        entry.async_on_unload(account.async_add_listener(lambda: async_dispatcher_send(hass, signal)))
        async_dispatcher_send(hass, signal)
        # Game version entries set up while there was no account entry get their gold sensors
        reload_gold_entries(hass, region, linked=False)
        await async_cleanup_devices(hass, entry.entry_id)
        entry.async_on_unload(entry.add_update_listener(update_listener))
        return True

    # Test the API connection before setting up platforms
    try:
        test_data = await client.get_all_realms()
    except Exception as err:
        _LOGGER.error("Failed to connect to Blizzard API: %s", err)
        raise ConfigEntryNotReady(f"Unable to connect to Blizzard API: {err}") from err
    if not test_data:
        raise ConfigEntryNotReady("Unable to connect to Blizzard API")

    # Realm and region devices get their own subentry, like the characters
    ensure_group_subentries(hass, entry)

    # One coordinator feeds all platforms (sensor, image, event)
    coordinator = await async_create_coordinator(hass, entry)
    hass.data[DOMAIN][entry.entry_id] = {"config": entry.data, "coordinator": coordinator}

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Characters moved between entries leave their old devices behind
    await async_cleanup_devices(hass, entry.entry_id)

    # Reload on option and subentry (character) changes
    entry.async_on_unload(entry.add_update_listener(update_listener))
    # WoW Forever characters whose profile was unavailable at setup: store
    # their game mode once it is known (the subentry update reloads the entry)
    entry.async_on_unload(coordinator.async_add_listener(
        lambda: store_forever_rulesets(hass, entry, coordinator.data or {})
    ))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    platforms = ACCOUNT_PLATFORMS if is_account_entry(entry) else PLATFORMS
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, platforms):
        hass.data[DOMAIN].pop(entry.entry_id)
        if is_account_entry(entry):
            hass.data.get(ACCOUNTS, {}).pop(entry.data[CONF_REGION].lower(), None)
    return unload_ok


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Delete stored values; removing the account also removes the gold sensors."""
    if is_account_entry(entry):
        await Store(hass, 1, account_store_key(unique_base(entry))).async_remove()
        ir.async_delete_issue(hass, DOMAIN, account_issue_id(entry.entry_id))
        reload_gold_entries(hass, entry.data[CONF_REGION], linked=True)
    else:
        await Store(hass, 1, cache_store_key(entry.entry_id)).async_remove()


async def update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload after option or character changes."""
    await hass.config_entries.async_reload(entry.entry_id)
