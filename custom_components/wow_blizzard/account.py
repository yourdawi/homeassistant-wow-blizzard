"""The Battle.net account entry: login, gold and account collections."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .api_client import UserTokenExpired, WoWBlizzardAPIClient
from .const import (
    ACCOUNT_GOLD_VERSIONS,
    ACCOUNT_REFRESH_INTERVAL,
    CONF_ACCOUNT_TOKEN,
    CONF_ENTRY_TYPE,
    CONF_REGION,
    DOMAIN,
    ENTRY_TYPE_ACCOUNT,
    SLOW_REFRESH_INTERVAL,
)
from .parsers import ACCOUNT_COLLECTIONS, count_collection, parse_account_characters, parse_transmogs

_LOGGER = logging.getLogger(__name__)

# Account coordinators by region, for the gold sensors of the game version entries
ACCOUNTS = f"{DOMAIN}_accounts"


def is_account_entry(entry: ConfigEntry) -> bool:
    """Whether an entry is the Battle.net account entry (not a game version)."""
    return entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_ACCOUNT


def account_issue_id(entry_id: Optional[str]) -> str:
    """Repair issue shown while the Battle.net login is expired."""
    return f"account_login_expired_{entry_id}"


def account_store_key(store_id: str) -> str:
    """Storage key for the last account values."""
    return f"{DOMAIN}.{store_id}.account"


def gold_key(game_version: str, realm_slug: str, name: str) -> str:
    """Key of a character in the account data."""
    return f"{game_version}:{realm_slug}/{(name or '').lower()}"


def account_coordinator(hass: HomeAssistant, region: str) -> Optional["AccountCoordinator"]:
    """The loaded account coordinator of a region, if any."""
    return hass.data.get(ACCOUNTS, {}).get(region.lower())


def account_signal(region: str) -> str:
    """Dispatcher signal sent after the account data of a region changed."""
    return f"{DOMAIN}_account_updated_{region.lower()}"


async def async_gold_characters(hass: HomeAssistant, region: str) -> Optional[set]:
    """Characters with gold, for the gold sensors of the game version entries.

    From the loaded account entry, or (it may start after the game version
    entries) from its stored values. None if the region has no account entry.
    """
    from .entries import account_entry_for, unique_base  # avoid an import cycle

    account = account_coordinator(hass, region)
    if account is not None and account.data:
        return set((account.data.get("characters") or {}).keys())
    entry = account_entry_for(hass, region)
    if entry is None:
        return None
    stored = await Store(hass, 1, account_store_key(unique_base(entry))).async_load() or {}
    return set((stored.get("characters") or {}).keys())


class AccountCoordinator(DataUpdateCoordinator):
    """Gold per character, total gold and account collections while the login is valid.

    Blizzard hands out no refresh tokens, so the login expires after 24 hours.
    Afterwards the last values are kept (also across restarts) and a repair
    notice points to Reconfigure.
    """

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, client: WoWBlizzardAPIClient, store: Store) -> None:
        """Initialize."""
        self.client = client
        self.entry = entry
        self.region = entry.data[CONF_REGION].lower()
        self.token: Dict[str, Any] = entry.data.get(CONF_ACCOUNT_TOKEN) or {}
        self.expired = False
        self._store = store
        self._last: Dict[str, Any] = {}
        self._transmogs: Optional[Any] = None
        super().__init__(
            hass, _LOGGER, name=f"{DOMAIN}_account", config_entry=entry,
            update_interval=timedelta(seconds=ACCOUNT_REFRESH_INTERVAL),
        )

    async def async_load_last(self) -> None:
        """Values of the last run, shown while the login is expired."""
        self._last = await self._store.async_load() or {}

    async def _async_update_data(self) -> Dict[str, Any]:
        expires_at = self.token.get("expires_at") or 0
        token = self.token.get("access_token")

        def keep_last(login_valid: bool) -> Dict[str, Any]:
            # Last good values (also restored after a restart), never zeros
            return {**self._last, "account_login": expires_at * 1000, "login_valid": login_valid}

        if not token or datetime.now(timezone.utc).timestamp() >= expires_at:
            self.expired = True
            result = keep_last(False)
        else:
            try:
                fresh = await self._fetch(token, expires_at)
            except UserTokenExpired:
                # Rejected before the expiry time, e.g. after a password change
                self.expired = True
                fresh = None
                result = keep_last(False)
            except Exception as err:  # noqa: BLE001 - account data must never fail the entry
                _LOGGER.warning("Could not fetch Battle.net account data: %s", err)
                fresh = None
                result = keep_last(True)
            else:
                # None: temporary API problem, keep the last values
                result = fresh if fresh is not None else keep_last(True)
            if fresh is not None:
                self.expired = False
                self._last = {k: v for k, v in fresh.items() if k not in ("account_login", "login_valid")}
                await self._store.async_save(self._last)

        if self.expired:
            ir.async_create_issue(
                self.hass, DOMAIN, account_issue_id(self.entry.entry_id),
                is_fixable=False, severity=ir.IssueSeverity.WARNING,
                translation_key="account_login_expired",
            )
        else:
            ir.async_delete_issue(self.hass, DOMAIN, account_issue_id(self.entry.entry_id))
        return result

    async def _fetch(self, token: str, expires_at: int) -> Optional[Dict[str, Any]]:
        """Gold of the Retail characters, totals and collections."""
        result: Dict[str, Any] = {"characters": {}, "account_login": expires_at * 1000, "login_valid": True}
        total_gold = 0
        account_characters = 0
        for game_version in ACCOUNT_GOLD_VERSIONS:
            profile = await self.client.get_account_profile(token, game_version)
            if not profile:
                if game_version == "retail":
                    return None
                continue
            characters = [c for c in parse_account_characters(profile) if c.get("realm_id") and c.get("id")]
            if game_version == "retail":
                account_characters = len(characters)
            answers = await asyncio.gather(*(
                self.client.get_protected_character(token, c["realm_id"], c["id"], game_version) for c in characters
            ))
            for char, protected in zip(characters, answers):
                key = gold_key(game_version, char["realm_slug"], char["name"])
                money = protected.get("money")
                if not isinstance(money, int):
                    # No answer for this character: keep its last value so the total does not drop
                    last = (self._last.get("characters") or {}).get(key)
                    if last:
                        result["characters"][key] = last
                        if game_version == "retail":
                            total_gold += last.get("character_gold") or 0
                    continue
                gold = money // 10000
                if game_version == "retail":
                    total_gold += gold
                stats = protected.get("protected_stats") or {}
                result["characters"][key] = {
                    "character_gold": gold,
                    "attrs": {"character_gold": {
                        "total_gold_gained": (stats.get("total_gold_gained") or 0) // 10000,
                        "total_gold_lost": (stats.get("total_gold_lost") or 0) // 10000,
                        "total_deaths": stats.get("total_number_deaths"),
                        "location": ((protected.get("position") or {}).get("zone") or {}).get("name"),
                        "hearthstone": ((protected.get("bind_position") or {}).get("zone") or {}).get("name"),
                    }},
                }
        result["account_gold_total"] = total_gold
        result["account_characters"] = account_characters

        for sensor, (kind, list_keys) in ACCOUNT_COLLECTIONS.items():
            count = count_collection(await self.client.get_account_collection(token, kind), list_keys)
            if count is not None:
                result[sensor] = count
            elif sensor in self._last:
                result[sensor] = self._last[sensor]

        # Transmogs: up to 5 MB, so at most every few hours and off the event loop
        if self._transmogs and datetime.now() - self._transmogs[0] < timedelta(seconds=SLOW_REFRESH_INTERVAL):
            transmogs = self._transmogs[1]
        else:
            transmogs = parse_transmogs(await self.client.get_account_collection(token, "transmogs", parse_in_thread=True))
            if transmogs:
                self._transmogs = (datetime.now(), transmogs)
        if transmogs:
            result["account_transmogs"] = transmogs["transmogs_collected"]
            result["attrs"] = {"account_transmogs": transmogs["attrs"]["transmogs_collected"]}
        elif "account_transmogs" in self._last:
            result["account_transmogs"] = self._last["account_transmogs"]
            result["attrs"] = {"account_transmogs": (self._last.get("attrs") or {}).get("account_transmogs") or {}}
        return result


def reload_gold_entries(hass: HomeAssistant, region: str, linked: Optional[bool]) -> None:
    """Reload the game version entries with gold (Retail) so gold sensors appear or go.

    linked: only entries whose coordinator was (True) or was not (False)
    set up with the account entry; None reloads all of them.
    """
    from .entries import entries_for  # avoid an import cycle

    for game_version, entry in entries_for(hass, region).items():
        if game_version not in ACCOUNT_GOLD_VERSIONS or entry.state is not ConfigEntryState.LOADED:
            continue
        coordinator = (hass.data.get(DOMAIN, {}).get(entry.entry_id) or {}).get("coordinator")
        if linked is not None and coordinator is not None and getattr(coordinator, "account_linked", None) != linked:
            continue
        hass.config_entries.async_schedule_reload(entry.entry_id)
