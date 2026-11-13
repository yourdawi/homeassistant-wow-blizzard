"""Config entries per game version, with one subentry per character."""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from types import MappingProxyType

from homeassistant.config_entries import ConfigEntry, ConfigEntryState, ConfigSubentry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er

from .api_client import WoWBlizzardAPIClient
from .const import (
    CONF_CHARACTER_KEY,
    CONF_CHARACTER_NAME,
    CONF_ENTRY_TYPE,
    CONF_GAME_VERSION,
    CONF_REALM,
    CONF_REALM_KEYS,
    CONF_REGION,
    CONF_RULESET_ID,
    CONF_UNIQUE_BASE,
    DOMAIN,
    ENTRY_TYPE_ACCOUNT,
    GAME_VERSIONS,
    SUBENTRY_ACCOUNT,
    SUBENTRY_CHARACTER,
    SUBENTRY_REALMS,
)

_LOGGER = logging.getLogger(__name__)

# Order used to decide which game version keeps the plain realm key
VERSION_ORDER = list(GAME_VERSIONS)


def game_version_label(game_version: str) -> str:
    """Human readable game version label."""
    return GAME_VERSIONS.get(game_version, {}).get("label", game_version)


def entry_game_version(entry: ConfigEntry) -> str:
    """Game version of a config entry (one entry per game version)."""
    return entry.data.get(CONF_GAME_VERSION, "retail")


def entry_title(game_version: str, region: str) -> str:
    """Title of a config entry, e.g. "Retail (EU)"."""
    return f"{game_version_label(game_version)} ({region.upper()})"


def entry_unique_id(region: str, game_version: str) -> str:
    """One config entry per region and game version."""
    return f"{region.lower()}_{game_version}"


def unique_base(entry: ConfigEntry) -> str:
    """Base of the entry-bound unique IDs (region, account and auction sensors).

    Entries split off from a pre-subentry entry keep that entry's ID here, so
    their sensors keep their unique IDs and history.
    """
    return entry.data.get(CONF_UNIQUE_BASE) or entry.entry_id


def character_unique_id(realm: str, name: str) -> str:
    """Subentry unique ID of a character within its game version entry."""
    return f"{realm}-{name}".lower()


def entry_characters(entry: ConfigEntry) -> List[Dict[str, Any]]:
    """The characters of an entry, built from its character subentries.

    Each character carries its game version, its entity key and the ID of
    its subentry (entities are grouped below the subentry).
    """
    game_version = entry_game_version(entry)
    characters = []
    for subentry in entry.subentries.values():
        if subentry.subentry_type != SUBENTRY_CHARACTER:
            continue
        data = dict(subentry.data)
        key = data.get(CONF_CHARACTER_KEY) or f"{data[CONF_REALM]}-{data[CONF_CHARACTER_NAME]}"
        characters.append({
            **data,
            CONF_GAME_VERSION: game_version,
            "key": key,
            "subentry_id": subentry.subentry_id,
        })
    return characters


def _domain_entries(hass: HomeAssistant) -> List[ConfigEntry]:
    """All entries of the integration, game versions and the Battle.net account."""
    return list(hass.config_entries.async_entries(DOMAIN))


def is_account(entry: ConfigEntry) -> bool:
    """Whether an entry is the Battle.net account entry."""
    return entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_ACCOUNT


def new_character_key(hass: HomeAssistant, realm: str, name: str, game_version: str) -> str:
    """Entity key for a new character, unique across all entries.

    Keeps the historic "{realm}-{name}" form unless another game version
    already uses it (then the game version is appended, as before).
    """
    base = f"{realm}-{name}"
    used = {
        subentry.data.get(CONF_CHARACTER_KEY)
        for entry in _domain_entries(hass)
        for subentry in entry.subentries.values()
        if subentry.subentry_type == SUBENTRY_CHARACTER
    }
    return base if base not in used else f"{base}-{game_version}"


def realm_keys(hass: HomeAssistant, entry: ConfigEntry, characters: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Unique key per realm of an entry (server device and sensors).

    Migrated entries keep their stored keys. Otherwise a realm gets its plain
    name unless a game version earlier in VERSION_ORDER has the same realm,
    then the game version is appended.
    """
    game_version = entry_game_version(entry)
    stored = entry.data.get(CONF_REALM_KEYS) or {}
    earlier = set()
    for other in _domain_entries(hass):
        if is_account(other):
            continue
        other_version = entry_game_version(other)
        if other.entry_id == entry.entry_id or VERSION_ORDER.index(other_version) >= VERSION_ORDER.index(game_version):
            continue
        earlier.update(c[CONF_REALM] for c in entry_characters(other))

    realms: Dict[str, Dict[str, Any]] = {}
    for char in characters:
        realm = char[CONF_REALM]
        if GAME_VERSIONS.get(game_version, {}).get("realmless") and char.get(CONF_RULESET_ID) is None:
            # WoW Forever without a known game mode: no server to report on
            continue
        key = stored.get(realm) or (realm if realm not in earlier else f"{realm}-{game_version}")
        if key in realms:
            continue
        realms[key] = {"realm": realm, "game_version": game_version}
        if char.get(CONF_RULESET_ID) is not None:
            realms[key]["ruleset_id"] = char[CONF_RULESET_ID]
    return realms


def entries_for(hass: HomeAssistant, region: str) -> Dict[str, ConfigEntry]:
    """Existing game version entries of a region by game version (no account entry)."""
    return {
        entry_game_version(entry): entry
        for entry in _domain_entries(hass)
        if (entry.data.get(CONF_REGION) or "").lower() == region.lower() and not is_account(entry)
    }


def account_entry_for(hass: HomeAssistant, region: str) -> Optional[ConfigEntry]:
    """The Battle.net account entry of a region, if any."""
    return next(
        (e for e in _domain_entries(hass) if is_account(e) and (e.data.get(CONF_REGION) or "").lower() == region.lower()),
        None,
    )


def account_title(region: str) -> str:
    """Title of the Battle.net account entry, e.g. "Battle.net Account (EU)"."""
    return f"Battle.net Account ({region.upper()})"


def character_title(name: str, realm_name: Optional[str]) -> str:
    """Subentry title, e.g. "Thrall - Stormrage"."""
    return f"{name} - {realm_name}" if realm_name else name


def realm_title(realm_slug: str) -> str:
    """Readable realm name from a slug, for titles when the API gave none."""
    return realm_slug.replace("-", " ").title() if realm_slug else ""


def _device_entries(device: dr.DeviceEntry) -> set:
    """Config entries of a device.

    Newer Home Assistant versions link a device to one entry (config_entry_id) and
    deprecate config_entries, so that is only read on versions without the new field.
    """
    if hasattr(device, "config_entry_id"):
        return {device.config_entry_id} - {None}
    return set(device.config_entries)


async def async_cleanup_devices(hass: HomeAssistant, current_entry_id: str) -> None:
    """Remove our devices whose entities no entry provides any more.

    Characters that moved to another entry (migration, import) and realms
    that are gone leave such devices behind. Runs only once every entry of
    the integration is loaded, so no entry is still about to add entities;
    devices with disabled entities are kept.
    """
    entries = _domain_entries(hass)
    if any(
        entry.state is not ConfigEntryState.LOADED
        for entry in entries
        if entry.entry_id != current_entry_id and not entry.disabled_by
    ):
        # Another entry is still setting up (or failed): its entities may be missing
        return
    # Devices of disabled entries are left alone
    our_entries = {entry.entry_id for entry in entries if not entry.disabled_by}
    device_registry = dr.async_get(hass)
    entity_registry = er.async_get(hass)
    # Only devices of our entries; the registry is no longer read as a mapping
    devices = {
        device.id: device
        for entry_id in our_entries
        for device in dr.async_entries_for_config_entry(device_registry, entry_id)
    }
    for device in devices.values():
        linked = _device_entries(device)
        if not linked & our_entries or linked - our_entries & {e.entry_id for e in entries}:
            continue
        device_entities = er.async_entries_for_device(entity_registry, device.id, include_disabled_entities=True)
        if any(entity.disabled_by for entity in device_entities):
            continue
        live = [
            entity for entity in device_entities
            if (state := hass.states.get(entity.entity_id)) is not None and not state.attributes.get("restored")
        ]
        if not live:
            _LOGGER.debug("Removing device %s, no entry provides its entities any more", device.name)
            device_registry.async_remove_device(device.id)


# Titles of the subentries the integration creates itself
GROUP_TITLES = {SUBENTRY_REALMS: "Realms", SUBENTRY_ACCOUNT: "Battle.net Account"}


def group_subentry_id(entry: ConfigEntry, subentry_type: str) -> Optional[str]:
    """ID of the realms or account subentry of an entry (None if missing)."""
    return next((s.subentry_id for s in entry.subentries.values() if s.subentry_type == subentry_type), None)


def ensure_group_subentries(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Create the realms subentry (and drop the account subentry of older versions).

    Called before the entry's update listener is registered, so changing the
    subentries here does not reload the entry. A deleted realms subentry
    comes back on the next start. The account has its own entry.
    """
    wanted = {SUBENTRY_REALMS: True, SUBENTRY_ACCOUNT: False}
    for subentry_type, needed in wanted.items():
        existing = group_subentry_id(entry, subentry_type)
        if needed and existing is None:
            hass.config_entries.async_add_subentry(entry, ConfigSubentry(
                data=MappingProxyType({}),
                subentry_type=subentry_type,
                title=GROUP_TITLES[subentry_type],
                unique_id=subentry_type,
            ))
        elif not needed and existing is not None:
            # Login removed: the account devices go with the subentry
            hass.config_entries.async_remove_subentry(entry, existing)


def add_character_entities(entry: ConfigEntry, async_add_entities, items) -> None:
    """Add (character, entity) pairs, each below the subentry of its character.

    A character deleted while the entry was loading is skipped (adding to a
    removed subentry fails the whole platform); the reload follows anyway.
    """
    groups: Dict[Optional[str], list] = {}
    for character, entity in items:
        groups.setdefault(character.get("subentry_id"), []).append(entity)
    for subentry_id, entities in groups.items():
        if subentry_id is not None and subentry_id not in entry.subentries:
            continue
        async_add_entities(entities, config_subentry_id=subentry_id)


def slug(value: str) -> str:
    """Realm slug as the API uses it."""
    return WoWBlizzardAPIClient.realm_to_slug(value)
