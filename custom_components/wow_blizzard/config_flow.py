"""Config flow: one entry per game version, characters as subentries."""
import logging
from types import MappingProxyType
from typing import Any, Dict, List, Optional

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntry, ConfigSubentry, ConfigSubentryFlow, SubentryFlowResult
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResult, section
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import selector
from homeassistant.helpers.config_entry_oauth2_flow import LocalOAuth2Implementation
from yarl import URL

from .const import (
    DOMAIN,
    CONF_CLIENT_ID,
    CONF_CLIENT_SECRET,
    CONF_REGION,
    CONF_REALM,
    CONF_CHARACTER_NAME,
    CONF_CHARACTER_KEY,
    CONF_ENABLE_SERVER_STATUS,
    CONF_ENABLE_PVP,
    CONF_ENABLE_RAIDS,
    CONF_ENABLE_MYTHIC_PLUS,
    CONF_ENABLE_HALL_OF_FAME,
    CONF_ENABLE_CHARACTER_DETAILS,
    CONF_ENABLE_COLLECTIONS,
    CONF_ENABLE_GUILD,
    CONF_ENABLE_REGION_DATA,
    CONF_ENABLE_MYTHIC_LEADERBOARD,
    CONF_ENABLE_PVP_LEADERBOARD,
    CONF_AUCTION_ITEMS,
    CONF_ACCOUNT_TOKEN,
    FEATURE_DEFAULTS,
    FEATURE_VERSIONS,
    OAUTH_AUTHORIZE_URLS,
    OAUTH_AUTHORIZE_URL_DEFAULT,
    OAUTH_TOKEN_URLS,
    OAUTH_TOKEN_URL_DEFAULT,
    OAUTH_SCOPE,
    DEFAULT_REGION,
    CONF_GAME_VERSION,
    CONF_LOCALE,
    CONF_NAMESPACE_SUFFIX,
    CONF_RULESET_ID,
    GAME_VERSIONS,
    SUBENTRY_CHARACTER,
    CONF_ENTRY_TYPE,
    ENTRY_TYPE_ACCOUNT,
)
from .api_client import WoWBlizzardAPIClient, InvalidCredentials, UserTokenExpired
from .entries import (
    account_entry_for,
    account_title,
    character_title,
    is_account,
    character_unique_id,
    entries_for,
    entry_characters,
    entry_game_version,
    entry_title,
    entry_unique_id,
    game_version_label,
    new_character_key,
)
from .parsers import parse_account_characters

OAUTH_REDIRECT_URL = "https://my.home-assistant.io/redirect/oauth"

_LOGGER = logging.getLogger(__name__)

FEATURE_KEYS = [
    CONF_ENABLE_SERVER_STATUS,
    CONF_ENABLE_PVP,
    CONF_ENABLE_RAIDS,
    CONF_ENABLE_MYTHIC_PLUS,
    CONF_ENABLE_HALL_OF_FAME,
    CONF_ENABLE_CHARACTER_DETAILS,
    CONF_ENABLE_COLLECTIONS,
    CONF_ENABLE_GUILD,
    CONF_ENABLE_REGION_DATA,
    CONF_ENABLE_MYTHIC_LEADERBOARD,
    CONF_ENABLE_PVP_LEADERBOARD,
]

# Entry data copied into the entries of other game versions (Battle.net import)
SHARED_KEYS = [CONF_CLIENT_ID, CONF_CLIENT_SECRET, CONF_REGION, CONF_LOCALE, *FEATURE_KEYS, CONF_AUCTION_ITEMS]

# The profile API only knows characters from this level on
MIN_API_LEVEL = 10

# Game versions whose account characters can be imported after a Battle.net login
ACCOUNT_GAME_VERSIONS = ["retail", "classic", "classicann", "classic1x", "forever"]

REGION_OPTIONS = [
    {"value": "us", "label": "Americas (US)"},
    {"value": "eu", "label": "Europe (EU)"},
    {"value": "kr", "label": "Korea (KR)"},
    {"value": "tw", "label": "Taiwan (TW)"},
    {"value": "cn", "label": "China (CN)"},
]
LOCALE_OPTIONS = [
    {"value": "en_us", "label": "English (United States)"},
    {"value": "es_mx", "label": "Spanish (Mexico)"},
    {"value": "pt_br", "label": "Portuguese"},
    {"value": "de_de", "label": "German"},
    {"value": "en_gb", "label": "English (Great Britain)"},
    {"value": "es_es", "label": "Spanish (Spain)"},
    {"value": "fr_fr", "label": "French"},
    {"value": "it_it", "label": "Italian"},
    {"value": "ru_ru", "label": "Russian"},
    {"value": "ko_kr", "label": "Korean"},
    {"value": "zh_tw", "label": "Chinese (Traditional)"},
    {"value": "zh_cn", "label": "Chinese (Simplified)"},
]
GAME_VERSION_OPTIONS = [
    {"value": "retail", "label": "Retail"},
    {"value": "classic", "label": "Classic Progression (e.g. Mists of Pandaria)"},
    {"value": "classic1x", "label": "Classic Era (Vanilla)"},
    {"value": "classicann", "label": "Classic Anniversary (Burning Crusade)"},
    {"value": "forever", "label": "WoW Forever"},
    # Not a game version: the entry that holds the Battle.net login
    {"value": ENTRY_TYPE_ACCOUNT, "label": "Battle.net Account"},
]


def user_schema(defaults: Dict[str, Any]) -> vol.Schema:
    """API credentials, prefilled from an existing entry so they need not be typed again."""
    return vol.Schema({
        vol.Required(CONF_CLIENT_ID, default=defaults.get(CONF_CLIENT_ID, vol.UNDEFINED)): str,
        vol.Required(CONF_CLIENT_SECRET, default=defaults.get(CONF_CLIENT_SECRET, vol.UNDEFINED)): str,
        vol.Required(CONF_REGION, default=defaults.get(CONF_REGION, DEFAULT_REGION)): selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=REGION_OPTIONS, mode=selector.SelectSelectorMode.DROPDOWN, translation_key="regions",
            )
        ),
        vol.Required(CONF_LOCALE, default=defaults.get(CONF_LOCALE, "en_us")): selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=LOCALE_OPTIONS, mode=selector.SelectSelectorMode.DROPDOWN, translation_key="locales",
            )
        ),
    })


def game_version_schema(available: List[str]) -> vol.Schema:
    """Game versions that have no entry yet in the region."""
    options = [o for o in GAME_VERSION_OPTIONS if o["value"] in available]
    return vol.Schema({
        vol.Required(CONF_GAME_VERSION, default=options[0]["value"]): selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=options, mode=selector.SelectSelectorMode.DROPDOWN, translation_key="game_versions",
            )
        ),
    })


def has_effect(feature: str, game_version: str) -> bool:
    """Whether a feature does anything in a game version (see FEATURE_VERSIONS)."""
    versions = FEATURE_VERSIONS.get(feature)
    return versions is None or game_version in versions


def features_schema(current: Dict[str, Any], game_version: str) -> vol.Schema:
    """Feature toggles plus the auction item IDs, only those with an effect in the game version."""
    schema = {
        vol.Optional(key, default=current.get(key, FEATURE_DEFAULTS[key])): bool
        for key in FEATURE_KEYS
        if has_effect(key, game_version)
    }
    if has_effect(CONF_AUCTION_ITEMS, game_version):
        schema[vol.Optional(CONF_AUCTION_ITEMS, default=current.get(CONF_AUCTION_ITEMS, ""))] = str
    return vol.Schema(schema)


def _selected_values(data: Any) -> List[str]:
    """All picked character keys from the nested version/realm sections."""
    if isinstance(data, dict):
        return [value for item in data.values() for value in _selected_values(item)]
    if isinstance(data, list):
        return [value for value in data if isinstance(value, str)]
    return []


def realm_display_name(realm: Dict[str, Any]) -> str:
    """Display name of a realm; the API may omit or not localize the name."""
    name = realm.get("name")
    if isinstance(name, str) and name:
        return name
    slug = realm.get("slug")
    if isinstance(slug, str) and slug:
        return slug.replace("-", " ").title()
    return str(realm.get("id", ""))


def is_realmless(game_version: str) -> bool:
    """WoW Forever has no realms; characters are found by first and last name."""
    return bool(GAME_VERSIONS.get(game_version, {}).get("realmless"))


def character_details_schema(realms_list: List[Dict[str, Any]], realmless: bool = False) -> vol.Schema:
    """Schema for realm + character name, with a searchable realm dropdown when realms are known."""
    if realmless:
        return vol.Schema({vol.Required(CONF_CHARACTER_NAME): str})
    realm_options = [
        {"value": realm["slug"], "label": realm_display_name(realm)}
        for realm in realms_list
        if isinstance(realm, dict) and isinstance(realm.get("slug"), str) and realm["slug"]
    ]
    realm_field: Any = str
    if realm_options:
        realm_field = selector.SelectSelector(selector.SelectSelectorConfig(
            options=realm_options, mode=selector.SelectSelectorMode.DROPDOWN, custom_value=True, sort=True,
        ))
    return vol.Schema({
        vol.Required(CONF_REALM): realm_field,
        vol.Required(CONF_CHARACTER_NAME): str,
    })


def _client_for(data: Dict[str, Any]) -> WoWBlizzardAPIClient:
    return WoWBlizzardAPIClient(
        data[CONF_CLIENT_ID],
        data[CONF_CLIENT_SECRET],
        data[CONF_REGION],
        locale=data.get(CONF_LOCALE),
    )


async def validate_api_credentials(hass: HomeAssistant, data: dict[str, Any]) -> None:
    """Validate the API credentials by making a test call."""
    client = _client_for(data)
    try:
        realms = await client.get_all_realms()
        if not realms or "realms" not in realms:
            raise CannotConnect("Unable to fetch realms - API credentials may be invalid")
    except InvalidCredentials as e:
        raise InvalidAuth(str(e)) from e
    except CannotConnect:
        raise
    except Exception as e:
        _LOGGER.error("Cannot connect to WoW API: %s", e)
        raise CannotConnect(f"Cannot connect: {e}") from e
    finally:
        await client.close()


async def load_realms(data: Dict[str, Any], game_version: str) -> Dict[str, Any]:
    """Resolve the namespace for a game version and load its realm list.

    Returns {"suffix": str | None, "realms": [...]}. A suffix of None means the
    API does not offer this game version (yet).
    """
    client = _client_for(data)
    try:
        suffix = await client.resolve_namespace_suffix(game_version)
        if suffix is None:
            return {"suffix": None, "realms": []}
        realms_data = await client.get_all_realms(game_version=game_version)
        realms = sorted(
            (r for r in realms_data.get("realms", []) if isinstance(r, dict)),
            key=realm_display_name,
        )
        return {"suffix": suffix, "realms": realms}
    finally:
        await client.close()


async def validate_character(
    data: dict[str, Any],
    character: dict[str, str],
    game_version: str,
    namespace_suffix: Optional[str] = None,
) -> dict[str, Any]:
    """Validate that a character exists and return its details."""
    client = _client_for(data)
    if namespace_suffix is not None:
        client.set_namespace_suffix(game_version, namespace_suffix)
    try:
        character_data = await client.get_character_profile(
            character[CONF_REALM], character[CONF_CHARACTER_NAME], game_version=game_version
        )
    except Exception as e:
        raise CannotConnect(f"Cannot connect: {e}") from e
    finally:
        await client.close()

    if not character_data or "name" not in character_data:
        raise CharacterNotFound(f"Character {character[CONF_CHARACTER_NAME]} not found on {character[CONF_REALM]}")

    name = character_data["name"]
    if character_data.get("surname"):
        # WoW Forever: two-part names
        name = f"{name} {character_data['surname']}"
    ruleset = character_data.get("ruleset") or {}
    return {
        "name": name,
        "level": character_data.get("level", "Unknown"),
        "character_class": character_data.get("character_class", {}).get("name", "Unknown"),
        "race": character_data.get("race", {}).get("name", "Unknown"),
        # WoW Forever has rulesets (Normal, PvP, Role-play ...) instead of realms
        "realm": (character_data.get("realm") or {}).get("name") or ruleset.get("name") or character[CONF_REALM],
        "ruleset_id": ruleset.get("id"),
    }


def character_subentry(
    hass: HomeAssistant, game_version: str, character: Dict[str, Any], realm_name: Optional[str], taken: set
) -> Dict[str, Any]:
    """Subentry data (ConfigSubentryData) of a character; taken holds keys given out in this batch."""
    key = character.get(CONF_CHARACTER_KEY) or new_character_key(
        hass, character[CONF_REALM], character[CONF_CHARACTER_NAME], game_version
    )
    if key in taken:
        key = f"{character[CONF_REALM]}-{character[CONF_CHARACTER_NAME]}-{game_version}"
    taken.add(key)
    data = {
        CONF_REALM: character[CONF_REALM],
        CONF_CHARACTER_NAME: character[CONF_CHARACTER_NAME],
        CONF_CHARACTER_KEY: key,
        CONF_NAMESPACE_SUFFIX: character.get(CONF_NAMESPACE_SUFFIX, GAME_VERSIONS[game_version]["namespaces"][0]),
        "level": character.get("level"),
        "character_class": character.get("character_class"),
        "race": character.get("race", ""),
    }
    if character.get(CONF_RULESET_ID) is not None:
        data[CONF_RULESET_ID] = character[CONF_RULESET_ID]
    return {
        "data": data,
        "subentry_type": SUBENTRY_CHARACTER,
        "title": character_title(character[CONF_CHARACTER_NAME], realm_name),
        "unique_id": character_unique_id(character[CONF_REALM], character[CONF_CHARACTER_NAME]),
    }


def add_subentries(hass: HomeAssistant, entry: ConfigEntry, subentries: List[Dict[str, Any]]) -> int:
    """Add character subentries to an existing entry, skipping characters it already has."""
    existing = {s.unique_id for s in entry.subentries.values()}
    added = 0
    for sub in subentries:
        if sub["unique_id"] in existing:
            continue
        hass.config_entries.async_add_subentry(entry, ConfigSubentry(
            data=MappingProxyType(sub["data"]),
            subentry_type=sub["subentry_type"],
            title=sub["title"],
            unique_id=sub["unique_id"],
        ))
        existing.add(sub["unique_id"])
        added += 1
    return added


class CharacterFormMixin:
    """Realm loading and the realm/name form, shared by the config and subentry flows."""

    _realm_cache: Dict[str, Dict[str, Any]]

    async def _get_realms(self, data: Dict[str, Any], game_version: str) -> Dict[str, Any]:
        if game_version not in self._realm_cache:
            try:
                self._realm_cache[game_version] = await load_realms(data, game_version)
            except Exception as e:
                _LOGGER.error(f"Error loading realms for {game_version}: {e}")
                return {"suffix": GAME_VERSIONS[game_version]["namespaces"][0], "realms": [], "error": True}
        return self._realm_cache[game_version]

    async def _character_form(
        self,
        step_id: str,
        data: Dict[str, Any],
        game_version: str,
        existing_ids: set,
        user_input: Optional[Dict[str, Any]],
    ):
        """Show or process the realm/name form.

        Returns a form to show, or (character, realm name) once validated.
        """
        realms = await self._get_realms(data, game_version)
        errors = {}
        realmless = is_realmless(game_version)
        if realmless:
            # Own form text: first and last name instead of realm and name
            step_id = f"{step_id}_forever"
        if realms["suffix"] is None:
            errors["base"] = "game_version_unavailable"
        elif realms.get("error"):
            errors["base"] = "cannot_connect"

        if user_input is not None and not errors:
            character = {
                CONF_REALM: user_input.get(CONF_REALM, ""),
                CONF_CHARACTER_NAME: user_input[CONF_CHARACTER_NAME].strip(),
            }
            try:
                info = await validate_character(data, character, game_version, realms["suffix"])
                if realmless:
                    # The ruleset takes the place of the realm (device name, server status)
                    character[CONF_REALM] = WoWBlizzardAPIClient.realm_to_slug(info["realm"])
                    character[CONF_CHARACTER_NAME] = info["name"]
                    character[CONF_RULESET_ID] = info["ruleset_id"]
                if character_unique_id(character[CONF_REALM], character[CONF_CHARACTER_NAME]) in existing_ids:
                    errors["base"] = "character_already_added"
                else:
                    character.update({
                        CONF_NAMESPACE_SUFFIX: realms["suffix"],
                        "level": info["level"],
                        "character_class": info["character_class"],
                        "race": info["race"],
                    })
                    return character, info["realm"]
            except CharacterNotFound:
                errors["base"] = "character_not_found"
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected exception validating character")
                errors["base"] = "unknown"

        return self.async_show_form(
            step_id=step_id,
            data_schema=character_details_schema(realms["realms"], realmless),
            errors=errors,
            description_placeholders={"game_version": game_version_label(game_version)},
        )


class WoWBlizzardConfigFlow(CharacterFormMixin, config_entries.ConfigFlow, domain=DOMAIN):
    """One config entry per region and game version."""

    VERSION = 4

    def __init__(self):
        """Initialize."""
        self.data: Dict[str, Any] = {}
        self._realm_cache = {}
        self._account_token = None
        self._account_error: Optional[str] = None
        self._account_selected: List[str] = []
        self._account_characters: Dict[str, Dict[str, Any]] = {}

    @classmethod
    @callback
    def async_get_supported_subentry_types(cls, config_entry: ConfigEntry) -> dict[str, type[ConfigSubentryFlow]]:
        """The "Add character" button (game version entries only)."""
        if is_account(config_entry):
            return {}
        return {SUBENTRY_CHARACTER: CharacterSubentryFlow}

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        """Get options flow."""
        return WoWBlizzardOptionsFlowHandler()

    @property
    def _game_version(self) -> str:
        return self.data.get(CONF_GAME_VERSION, "retail")

    @property
    def _is_account(self) -> bool:
        """Whether this flow sets up (or reconfigures) the Battle.net account entry."""
        return self.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_ACCOUNT

    # --- setup: credentials, game version, features ---------------------------------

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """API credentials (prefilled from an existing entry)."""
        errors = {}
        if user_input is not None:
            try:
                await validate_api_credentials(self.hass, user_input)
                self.data.update(user_input)
                return await self.async_step_game_version()
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"

        existing = self._async_current_entries()
        defaults = dict(existing[0].data) if existing else {}
        return self.async_show_form(
            step_id="user",
            data_schema=user_schema(user_input or defaults),
            errors=errors,
            description_placeholders={"setup_url": "https://develop.battle.net/access/clients"},
        )

    async def async_step_game_version(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Pick the game version of this entry (one entry per game version and region)."""
        region = self.data[CONF_REGION]
        configured = set(entries_for(self.hass, region))
        if account_entry_for(self.hass, region):
            configured.add(ENTRY_TYPE_ACCOUNT)
        available = [o["value"] for o in GAME_VERSION_OPTIONS if o["value"] not in configured]
        if not available:
            return self.async_abort(reason="all_versions_configured")
        if user_input is not None:
            if user_input[CONF_GAME_VERSION] == ENTRY_TYPE_ACCOUNT:
                # The account entry starts with the Battle.net login
                self.data[CONF_ENTRY_TYPE] = ENTRY_TYPE_ACCOUNT
                await self.async_set_unique_id(entry_unique_id(region, ENTRY_TYPE_ACCOUNT))
                self._abort_if_unique_id_configured()
                return await self.async_step_account_login()
            self.data[CONF_GAME_VERSION] = user_input[CONF_GAME_VERSION]
            await self.async_set_unique_id(entry_unique_id(region, self._game_version))
            self._abort_if_unique_id_configured()
            return await self.async_step_features()
        return self.async_show_form(
            step_id="game_version",
            data_schema=game_version_schema(available),
            description_placeholders={"region": self.data[CONF_REGION].upper()},
        )

    async def async_step_features(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Feature selection, preset from an existing entry of the region."""
        if user_input is not None:
            self.data.update(user_input)
            return await self.async_step_add_method()
        others = list(entries_for(self.hass, self.data[CONF_REGION]).values())
        current = {**others[0].data, **others[0].options} if others else {}
        return self.async_show_form(
            step_id="features",
            data_schema=features_schema(current, self._game_version),
            description_placeholders={
                "region": self.data[CONF_REGION].upper(),
                "game_version": game_version_label(self._game_version),
            },
        )

    async def async_step_add_method(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """First character by hand, import with a Battle.net login, or none yet."""
        return self.async_show_menu(
            step_id="add_method",
            menu_options=["character", "account_login", "finish"],
            description_placeholders={
                "redirect_url": OAUTH_REDIRECT_URL,
                "game_version": game_version_label(self._game_version),
            },
        )

    async def async_step_finish(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Create the entry without characters; they are added with "Add character"."""
        return self._create_entry([])

    async def async_step_character(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Realm and name of the first character."""
        result = await self._character_form("character", self.data, self._game_version, set(), user_input)
        if isinstance(result, tuple):
            character, realm_name = result
            return self._create_entry([character_subentry(self.hass, self._game_version, character, realm_name, set())])
        return result

    async def async_step_character_forever(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """WoW Forever variant of the character form (first and last name)."""
        return await self.async_step_character(user_input)

    def _create_entry(self, subentries: List[Dict[str, Any]]) -> FlowResult:
        return self.async_create_entry(
            title=entry_title(self._game_version, self.data[CONF_REGION]),
            data=self.data,
            subentries=subentries,
        )

    # --- import: entries created for other game versions (Battle.net import, migration) ---

    async def async_step_import(self, import_data: dict[str, Any]) -> FlowResult:
        """Create the entry of a game version with its characters.

        If the region already has an entry for that game version, the
        characters are added to it instead.
        """
        data = dict(import_data)
        if data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_ACCOUNT:
            return self._import_account(data)
        subentries = data.pop("subentries", [])
        options = data.pop("options", {})
        region, game_version = data[CONF_REGION], data[CONF_GAME_VERSION]
        existing = entries_for(self.hass, region).get(game_version)
        if existing:
            add_subentries(self.hass, existing, subentries)
            if CONF_ACCOUNT_TOKEN in data:
                self.hass.config_entries.async_update_entry(
                    existing, data={**existing.data, CONF_ACCOUNT_TOKEN: data[CONF_ACCOUNT_TOKEN]}
                )
            return self.async_abort(reason="already_configured")
        await self.async_set_unique_id(entry_unique_id(region, game_version))
        self._abort_if_unique_id_configured()
        return self.async_create_entry(
            title=entry_title(game_version, region), data=data, options=options, subentries=subentries,
        )

    def _import_account(self, data: Dict[str, Any]) -> FlowResult:
        """Create the account entry, or renew the login of the existing one."""
        existing = account_entry_for(self.hass, data[CONF_REGION])
        if existing:
            self.hass.config_entries.async_update_entry(
                existing, data={**existing.data, CONF_ACCOUNT_TOKEN: data[CONF_ACCOUNT_TOKEN]}
            )
            return self.async_abort(reason="already_configured")
        self._async_abort_entries_match({CONF_ENTRY_TYPE: ENTRY_TYPE_ACCOUNT, CONF_REGION: data[CONF_REGION]})
        return self.async_create_entry(title=account_title(data[CONF_REGION]), data=data)

    # --- Battle.net login: import characters of all game versions ------------------

    def _oauth_implementation(self) -> LocalOAuth2Implementation:
        region = self.data[CONF_REGION]
        return LocalOAuth2Implementation(
            self.hass,
            DOMAIN,
            self.data[CONF_CLIENT_ID],
            self.data[CONF_CLIENT_SECRET],
            OAUTH_AUTHORIZE_URLS.get(region, OAUTH_AUTHORIZE_URL_DEFAULT),
            OAUTH_TOKEN_URLS.get(region, OAUTH_TOKEN_URL_DEFAULT),
        )

    async def async_step_account_login(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Send the user to the Battle.net login and receive the code."""
        if user_input is None:
            try:
                url = await self._oauth_implementation().async_generate_authorize_url(self.flow_id)
            except RuntimeError:
                # No my.home-assistant.io and no browser request to build the redirect URL from
                self._account_error = "oauth_redirect_unavailable"
                return await self.async_step_account_failed()
            url = str(URL(url).update_query({"scope": OAUTH_SCOPE}))
            return self.async_external_step(step_id="account_login", url=url)

        self._account_token = None
        if "code" in user_input:
            client = _client_for(self.data)
            try:
                self._account_token = await client.exchange_authorization_code(
                    user_input["code"], user_input["state"]["redirect_uri"]
                )
            except Exception:
                _LOGGER.exception("Battle.net login failed")
            finally:
                await client.close()
        return self.async_external_step_done(next_step_id="account_select")

    async def async_step_account_failed(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Explain a failed login; nothing is lost."""
        if user_input is not None:
            if self.source == config_entries.SOURCE_RECONFIGURE or self._is_account:
                return self.async_abort(reason="account_login_skipped")
            return await self.async_step_add_method()
        return self.async_show_form(
            step_id="account_failed",
            data_schema=vol.Schema({}),
            errors={"base": self._account_error or "account_login_failed"},
            description_placeholders={"redirect_url": OAUTH_REDIRECT_URL},
        )

    def _configured_ids(self) -> set:
        """"version:realm-name" of every configured character in the region."""
        ids = set()
        for game_version, entry in entries_for(self.hass, self.data[CONF_REGION]).items():
            ids.update(
                f"{game_version}:{character_unique_id(c[CONF_REALM], c[CONF_CHARACTER_NAME])}"
                for c in entry_characters(entry)
            )
        return ids

    async def async_step_account_select(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Pick characters of the logged-in account (all game versions)."""
        if not self._account_token:
            self._account_error = "account_login_failed"
            return await self.async_step_account_failed()

        if not self._account_characters:
            client = _client_for(self.data)
            try:
                for game_version in ACCOUNT_GAME_VERSIONS:
                    try:
                        profile = await client.get_account_profile(self._account_token["access_token"], game_version)
                    except UserTokenExpired:
                        self._account_token = None
                        self._account_error = "account_login_failed"
                        return await self.async_step_account_failed()
                    for char in parse_account_characters(profile):
                        if char.get("realm_slug") and char.get("name"):
                            self._account_characters[f"{game_version}|{char['realm_slug']}|{char['name']}"] = {
                                **char, CONF_GAME_VERSION: game_version,
                            }
            finally:
                await client.close()

        configured = self._configured_ids()
        available = {
            key: c for key, c in self._account_characters.items()
            if f"{c[CONF_GAME_VERSION]}:{character_unique_id(c['realm_slug'], c['name'])}" not in configured
        }
        # Blizzard's profile API has no data for characters below level 10
        too_low = [key for key, c in available.items() if isinstance(c.get("level"), int) and c["level"] < MIN_API_LEVEL]
        for key in too_low:
            available.pop(key)

        if user_input is not None:
            self._account_selected = [key for key in _selected_values(user_input) if key in available]
            return await self.async_step_account_options()

        # Game version (foldable section) > realm (dropdown) > characters
        grouped: Dict[str, Dict[str, List[Any]]] = {}
        for key, c in available.items():
            grouped.setdefault(c[CONF_GAME_VERSION], {}).setdefault(c["realm"] or c["realm_slug"], []).append((key, c))

        schema: Dict[Any, Any] = {}
        for game_version in ACCOUNT_GAME_VERSIONS:
            realms = grouped.get(game_version)
            if not realms:
                continue
            realm_schema: Dict[Any, Any] = {}
            for realm in sorted(realms):
                chars = sorted(realms[realm], key=lambda kv: (-(kv[1].get("level") or 0), kv[1]["name"]))
                options = [
                    {"value": key, "label": f"{c['name']} (Lv {c.get('level')}, {c.get('class')})"}
                    for key, c in chars
                ]
                # HA does not nest sections; a dropdown keeps each realm folded until clicked
                realm_schema[vol.Optional(f"{realm} ({len(chars)})", default=[])] = selector.SelectSelector(
                    selector.SelectSelectorConfig(options=options, mode=selector.SelectSelectorMode.DROPDOWN, multiple=True)
                )
            schema[vol.Required(game_version)] = section(
                vol.Schema(realm_schema), {"collapsed": game_version != self._game_version}
            )

        return self.async_show_form(
            step_id="account_select",
            data_schema=vol.Schema(schema),
            description_placeholders={"character_count": str(len(available)), "hidden_count": str(len(too_low))},
        )

    async def async_step_account_options(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """After picking characters: keep the login for account data (optional)."""
        if user_input is None:
            keep = self._is_account or account_entry_for(self.hass, self.data[CONF_REGION]) is not None
            return self.async_show_form(
                step_id="account_options",
                data_schema=vol.Schema({vol.Optional("keep_login", default=keep): bool}),
                description_placeholders={"selected_count": str(len(self._account_selected))},
            )

        keep_login = bool(user_input.get("keep_login"))
        taken: set = set()
        by_version: Dict[str, List[Dict[str, Any]]] = {}
        for key in self._account_selected:
            char = self._account_characters[key]
            game_version = char[CONF_GAME_VERSION]
            character = {
                CONF_REALM: char["realm_slug"],
                CONF_CHARACTER_NAME: char["name"],
                "level": char.get("level"),
                "character_class": char.get("class") or "Unknown",
            }
            if char.get("ruleset_id"):
                character[CONF_RULESET_ID] = char["ruleset_id"]
            by_version.setdefault(game_version, []).append(
                character_subentry(self.hass, game_version, character, char.get("realm"), taken)
            )

        reconfigure = self.source == config_entries.SOURCE_RECONFIGURE
        own = [] if self._is_account else by_version.pop(self._game_version, [])
        self._distribute(by_version)

        if self._is_account:
            if reconfigure:
                entry = self._get_reconfigure_entry()
                if not keep_login:
                    return self.async_abort(reason="characters_imported")
                return self.async_update_reload_and_abort(entry, data={**entry.data, CONF_ACCOUNT_TOKEN: self._account_token})
            if not keep_login:
                return self.async_abort(reason="characters_imported")
            return self.async_create_entry(
                title=account_title(self.data[CONF_REGION]),
                data={
                    **{k: self.data[k] for k in (CONF_CLIENT_ID, CONF_CLIENT_SECRET, CONF_REGION, CONF_LOCALE)},
                    CONF_ENTRY_TYPE: ENTRY_TYPE_ACCOUNT,
                    CONF_ACCOUNT_TOKEN: self._account_token,
                },
            )

        if keep_login:
            self._store_login()
        if reconfigure:
            entry = self._get_reconfigure_entry()
            add_subentries(self.hass, entry, own)
            return self.async_abort(reason="reconfigure_successful")
        return self._create_entry(own)

    def _store_login(self) -> None:
        """Keep the login in the account entry of the region (created if missing)."""
        existing = account_entry_for(self.hass, self.data[CONF_REGION])
        if existing:
            # The update reloads the account entry
            self.hass.config_entries.async_update_entry(
                existing, data={**existing.data, CONF_ACCOUNT_TOKEN: self._account_token}
            )
            return
        self.hass.async_create_task(
            self.hass.config_entries.flow.async_init(
                DOMAIN, context={"source": config_entries.SOURCE_IMPORT}, data={
                    **{k: self.data[k] for k in (CONF_CLIENT_ID, CONF_CLIENT_SECRET, CONF_REGION, CONF_LOCALE)},
                    CONF_ENTRY_TYPE: ENTRY_TYPE_ACCOUNT,
                    CONF_ACCOUNT_TOKEN: self._account_token,
                },
            )
        )

    def _distribute(self, by_version: Dict[str, List[Dict[str, Any]]]) -> None:
        """Characters of other game versions go to their entries, created if missing."""
        region = self.data[CONF_REGION]
        entries = entries_for(self.hass, region)
        shared = {k: self.data[k] for k in SHARED_KEYS if k in self.data}
        for game_version, subentries in by_version.items():
            if game_version in entries:
                continue
            self.hass.async_create_task(
                self.hass.config_entries.flow.async_init(
                    DOMAIN, context={"source": config_entries.SOURCE_IMPORT},
                    data={**shared, CONF_GAME_VERSION: game_version, "subentries": subentries},
                )
            )
        for game_version, entry in entries.items():
            if entry.entry_id == self.context.get("entry_id"):
                continue
            add_subentries(self.hass, entry, by_version.get(game_version, []))

    async def async_step_reconfigure(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Log in with Battle.net again: import characters and refresh the account login."""
        entry = self._get_reconfigure_entry()
        self.data = dict(entry.data)
        return await self.async_step_account_login()


class CharacterSubentryFlow(CharacterFormMixin, ConfigSubentryFlow):
    """The "Add character" button of an entry."""

    def __init__(self):
        """Initialize."""
        self._realm_cache = {}

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        """Realm and name of the character (the entry decides the game version)."""
        entry = self._get_entry()
        game_version = entry_game_version(entry)
        existing = {s.unique_id for s in entry.subentries.values()}
        result = await self._character_form("user", dict(entry.data), game_version, existing, user_input)
        if isinstance(result, tuple):
            character, realm_name = result
            sub = character_subentry(self.hass, game_version, character, realm_name, set())
            return self.async_create_entry(title=sub["title"], data=sub["data"], unique_id=sub["unique_id"])
        return result

    async def async_step_user_forever(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        """WoW Forever variant of the character form (first and last name)."""
        return await self.async_step_user(user_input)


class WoWBlizzardOptionsFlowHandler(config_entries.OptionsFlow):
    """Features of an entry and the Battle.net login."""

    async def async_step_init(self, user_input=None):
        """Features of a game version; the account entry offers removing the login."""
        if is_account(self.config_entry):
            return await self.async_step_remove_account()
        return await self.async_step_features()

    async def async_step_features(self, user_input=None):
        """Feature toggles and auction items (those with an effect in the entry's game version)."""
        if user_input is not None:
            # Hidden features keep their value
            return self.async_create_entry(title="", data={**self.config_entry.options, **user_input})
        options = self.config_entry.options
        data = self.config_entry.data
        return self.async_show_form(
            step_id="features",
            data_schema=features_schema({
                key: options.get(key, data.get(key, FEATURE_DEFAULTS.get(key, "")))
                for key in FEATURE_KEYS + [CONF_AUCTION_ITEMS]
            }, entry_game_version(self.config_entry)),
            description_placeholders={"game_version": game_version_label(entry_game_version(self.config_entry))},
        )

    async def async_step_remove_account(self, user_input=None):
        """Forget the Battle.net login: the account entry is removed, characters stay."""
        if user_input is not None:
            self.hass.async_create_task(self.hass.config_entries.async_remove(self.config_entry.entry_id))
            return self.async_abort(reason="account_removed")
        return self.async_show_form(step_id="remove_account", data_schema=vol.Schema({}))


class CannotConnect(HomeAssistantError):
    """Error to indicate we cannot connect."""


class InvalidAuth(HomeAssistantError):
    """Error to indicate there is invalid auth."""


class CharacterNotFound(HomeAssistantError):
    """Error to indicate character was not found."""
