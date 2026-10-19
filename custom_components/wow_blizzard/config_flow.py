"""Config flow realm selector"""
import logging
import voluptuous as vol
from typing import Dict, Any, List, Optional

from homeassistant import config_entries
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResult
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
    CONF_CHARACTERS,
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
    CONF_AUCTION_ITEMS,
    CONF_ACCOUNT_TOKEN,
    FEATURE_DEFAULTS,
    OAUTH_AUTHORIZE_URLS,
    OAUTH_AUTHORIZE_URL_DEFAULT,
    OAUTH_TOKEN_URLS,
    OAUTH_TOKEN_URL_DEFAULT,
    OAUTH_SCOPE,
    DEFAULT_REGION,
    CONF_GAME_VERSION,
    CONF_LOCALE,
    CONF_NAMESPACE_SUFFIX,
    GAME_VERSIONS,
)
from .api_client import WoWBlizzardAPIClient, InvalidCredentials, UserTokenExpired
from .parsers import parse_account_characters

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
]

# Game versions whose account characters can be imported after a Battle.net login
ACCOUNT_GAME_VERSIONS = ["retail", "classic", "classicann", "classic1x"]

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_CLIENT_ID): str,
        vol.Required(CONF_CLIENT_SECRET): str,
        vol.Required(CONF_REGION, default=DEFAULT_REGION): selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=[
                    {"value": "us", "label": "Americas (US)"},
                    {"value": "eu", "label": "Europe (EU)"},
                    {"value": "kr", "label": "Korea (KR)"},
                    {"value": "tw", "label": "Taiwan (TW)"},
                    {"value": "cn", "label": "China (CN)"},
                ],
                mode=selector.SelectSelectorMode.DROPDOWN,
                translation_key="regions",
            )
        ),
        vol.Required(CONF_LOCALE, default="en_US"): selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=[
                    {"value": "en_US", "label": "English (United States)"},
                    {"value": "es_MX", "label": "Spanish (Mexico)"},
                    {"value": "pt_BR", "label": "Portuguese"},
                    {"value": "de_DE", "label": "German"},
                    {"value": "en_GB", "label": "English (Great Britain)"},
                    {"value": "es_ES", "label": "Spanish (Spain)"},
                    {"value": "fr_FR", "label": "French"},
                    {"value": "it_IT", "label": "Italian"},
                    {"value": "ru_RU", "label": "Russian"},
                    {"value": "ko_KR", "label": "Korean"},
                    {"value": "zh_TW", "label": "Chinese (Traditional)"},
                    {"value": "zh_CN", "label": "Chinese (Simplified)"},
                ],
                mode=selector.SelectSelectorMode.DROPDOWN,
                translation_key="locales",
            )
        ),
    }
)

def features_schema(current: Dict[str, Any]) -> vol.Schema:
    """Feature toggles plus the item IDs whose auction prices are tracked."""
    schema = {
        vol.Optional(key, default=current.get(key, FEATURE_DEFAULTS[key])): bool
        for key in FEATURE_KEYS
    }
    schema[vol.Optional(CONF_AUCTION_ITEMS, default=current.get(CONF_AUCTION_ITEMS, ""))] = str
    return vol.Schema(schema)

STEP_GAME_VERSION_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_GAME_VERSION, default="retail"): selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=[
                    {"value": "retail", "label": "Retail"},
                    {"value": "classic", "label": "Classic Progression (e.g. Mists of Pandaria)"},
                    {"value": "classic1x", "label": "Classic Era (Vanilla)"},
                    {"value": "classicann", "label": "Classic Anniversary (Burning Crusade)"},
                    {"value": "forever", "label": "WoW Forever"},
                ],
                mode=selector.SelectSelectorMode.DROPDOWN,
                translation_key="game_versions",
            )
        ),
    }
)


def game_version_label(game_version: str) -> str:
    """Human readable game version label."""
    return GAME_VERSIONS.get(game_version, {}).get("label", game_version)


def character_id(character: Dict[str, Any]) -> str:
    """Identifier of a configured character, unique per game version."""
    return f"{character.get(CONF_GAME_VERSION, 'retail')}:{character[CONF_REALM]}-{character[CONF_CHARACTER_NAME]}"


def entry_title(characters: List[Dict[str, Any]]) -> str:
    """Config entry title for the configured characters."""
    if len(characters) == 1:
        return characters[0]["display_name"]
    return f"WoW API ({len(characters)} characters)"


def realm_display_name(realm: Dict[str, Any]) -> str:
    """Display name of a realm; the API may omit or not localize the name."""
    name = realm.get("name")
    if isinstance(name, str) and name:
        return name
    slug = realm.get("slug")
    if isinstance(slug, str) and slug:
        return slug.replace("-", " ").title()
    return str(realm.get("id", ""))


def create_realm_selector_config(realm_options: List[Dict[str, str]]) -> selector.SelectSelectorConfig:
    """Create a searchable realm selector that also accepts typed realm names."""
    return selector.SelectSelectorConfig(
        options=realm_options,
        mode=selector.SelectSelectorMode.DROPDOWN,
        custom_value=True,
        sort=True,
    )


def character_details_schema(realms_list: List[Dict[str, Any]]) -> vol.Schema:
    """Schema for realm + character name, with a realm dropdown when realms are known."""
    realm_options = [
        {"value": realm["slug"], "label": realm_display_name(realm)}
        for realm in realms_list
        if isinstance(realm, dict) and isinstance(realm.get("slug"), str) and realm["slug"]
    ]
    realm_field: Any = str
    if realm_options:
        realm_field = selector.SelectSelector(create_realm_selector_config(realm_options))
    return vol.Schema({
        vol.Optional(CONF_REALM): realm_field,
        vol.Optional(CONF_CHARACTER_NAME): str,
    })


def _client_for(data: Dict[str, Any]) -> WoWBlizzardAPIClient:
    return WoWBlizzardAPIClient(
        data[CONF_CLIENT_ID],
        data[CONF_CLIENT_SECRET],
        data[CONF_REGION],
        locale=data.get(CONF_LOCALE),
    )


async def validate_api_credentials(hass: HomeAssistant, data: dict[str, Any]) -> dict[str, Any]:
    """Validate the API credentials by making a test call."""
    client = _client_for(data)

    try:
        realms = await client.get_all_realms()
        if not realms or "realms" not in realms:
            raise CannotConnect("Unable to fetch realms - API credentials may be invalid")
        return {"realms": realms["realms"]}
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
    API does not offer this game version (yet), e.g. WoW Forever before launch.
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
    hass: HomeAssistant,
    data: dict[str, Any],
    character: dict[str, str],
    game_version: str,
    namespace_suffix: Optional[str] = None,
) -> dict[str, Any]:
    """Validate that a character exists."""
    client = _client_for(data)
    if namespace_suffix is not None:
        client.set_namespace_suffix(game_version, namespace_suffix)

    try:
        character_data = await client.get_character_profile(
            character[CONF_REALM],
            character[CONF_CHARACTER_NAME],
            game_version=game_version
        )
    except Exception as e:
        raise CannotConnect(f"Cannot connect: {e}") from e
    finally:
        await client.close()

    if not character_data or "name" not in character_data:
        raise CharacterNotFound(f"Character {character[CONF_CHARACTER_NAME]} not found on {character[CONF_REALM]}")

    return {
        "name": character_data["name"],
        "level": character_data.get("level", "Unknown"),
        "character_class": character_data.get("character_class", {}).get("name", "Unknown"),
        "race": character_data.get("race", {}).get("name", "Unknown"),
        "realm": character_data.get("realm", {}).get("name", character[CONF_REALM]),
    }


class CharacterStepMixin:
    """Shared realm loading and character validation for config and options flows."""

    _realm_cache: Dict[str, Dict[str, Any]]

    async def _get_realms(self, data: Dict[str, Any], game_version: str) -> Dict[str, Any]:
        if game_version not in self._realm_cache:
            try:
                self._realm_cache[game_version] = await load_realms(data, game_version)
            except Exception as e:
                _LOGGER.error(f"Error loading realms for {game_version}: {e}")
                return {"suffix": GAME_VERSIONS[game_version]["namespaces"][0], "realms": [], "error": True}
        return self._realm_cache[game_version]

    async def _character_details(
        self,
        step_id: str,
        data: Dict[str, Any],
        game_version: str,
        existing: List[Dict[str, Any]],
        user_input: Optional[Dict[str, Any]],
    ):
        """Show or process the realm/name form.

        Returns a FlowResult to show, or a new character dict once validated.
        """
        realms = await self._get_realms(data, game_version)
        errors = {}
        placeholders = {"game_version": game_version_label(game_version)}

        if realms["suffix"] is None:
            errors["base"] = "game_version_unavailable"
        elif realms.get("error"):
            errors["base"] = "cannot_connect"

        if user_input is not None and not errors:
            character = {
                CONF_REALM: user_input[CONF_REALM],
                CONF_CHARACTER_NAME: user_input[CONF_CHARACTER_NAME],
                CONF_GAME_VERSION: game_version,
            }
            if character_id(character) in [character_id(c) for c in existing]:
                errors["base"] = "character_already_added"
            else:
                try:
                    info = await validate_character(self.hass, data, character, game_version, realms["suffix"])
                    return {
                        **character,
                        CONF_NAMESPACE_SUFFIX: realms["suffix"],
                        "display_name": f"{info['name']} - {info['realm']} ({game_version_label(game_version)})",
                        "level": info["level"],
                        "character_class": info["character_class"],
                        "race": info["race"],
                    }
                except CharacterNotFound:
                    errors["base"] = "character_not_found"
                except CannotConnect:
                    errors["base"] = "cannot_connect"
                except Exception:
                    _LOGGER.exception("Unexpected exception validating character")
                    errors["base"] = "unknown"

        return self.async_show_form(
            step_id=step_id,
            data_schema=character_details_schema(realms["realms"]),
            errors=errors,
            description_placeholders=placeholders,
        )


class WoWBlizzardConfigFlow(CharacterStepMixin, config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for WoW Blizzard API."""

    VERSION = 2

    def __init__(self):
        """Initialize."""
        self.data = {}
        self.characters = []
        self.current_character = {}
        self._realm_cache = {}
        self._account_token = None
        self._account_error: Optional[str] = None
        self._account_characters: Dict[str, Dict[str, Any]] = {}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step - API credentials."""
        errors = {}

        if user_input is not None:
            try:
                await validate_api_credentials(self.hass, user_input)
                self.data.update(user_input)
                return await self.async_step_features()
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_DATA_SCHEMA,
            errors=errors,
            description_placeholders={
                "setup_url": "https://develop.battle.net/access/clients"
            }
        )

    async def async_step_features(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle feature selection step."""
        if user_input is None:
            return self.async_show_form(
                step_id="features",
                data_schema=features_schema({}),
                description_placeholders={
                    "region": self.data[CONF_REGION].upper()
                }
            )

        self.data.update(user_input)
        return await self.async_step_add_method()

    async def async_step_add_method(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Add a character by hand or import characters with a Battle.net login."""
        return self.async_show_menu(step_id="add_method", menu_options=["character", "account_login"])

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

    async def async_step_account_login(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
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

    async def async_step_account_failed(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Explain a failed login; nothing is lost, the user goes back and can add characters by hand."""
        if user_input is not None:
            if self.source == config_entries.SOURCE_RECONFIGURE:
                # The existing configuration stays as it is
                return self.async_abort(reason="account_login_skipped")
            return await self.async_step_add_method()
        return self.async_show_form(
            step_id="account_failed",
            data_schema=vol.Schema({}),
            errors={"base": self._account_error or "account_login_failed"},
        )

    async def async_step_account_select(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Pick characters of the logged-in account."""
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

        existing = {character_id(c) for c in self.characters}
        if user_input is not None:
            for value in user_input.get("characters", []):
                char = self._account_characters.get(value)
                if not char:
                    continue
                game_version = char[CONF_GAME_VERSION]
                new = {
                    CONF_REALM: char["realm_slug"],
                    CONF_CHARACTER_NAME: char["name"],
                    CONF_GAME_VERSION: game_version,
                }
                if character_id(new) in existing:
                    continue
                existing.add(character_id(new))
                self.characters.append({
                    **new,
                    CONF_NAMESPACE_SUFFIX: GAME_VERSIONS[game_version]["namespaces"][0],
                    "display_name": f"{char['name']} - {char['realm']} ({game_version_label(game_version)})",
                    "level": char.get("level"),
                    "character_class": char.get("class") or "Unknown",
                    "race": "",
                })
            if user_input.get("keep_login"):
                self.data[CONF_ACCOUNT_TOKEN] = self._account_token
            else:
                # Unticked: no account data (and no reminders about the login)
                self.data.pop(CONF_ACCOUNT_TOKEN, None)
            if self.source == config_entries.SOURCE_RECONFIGURE:
                entry = self._get_reconfigure_entry()
                return self.async_update_reload_and_abort(
                    entry,
                    title=entry_title(self.characters),
                    data={**self.data, CONF_CHARACTERS: self.characters},
                )
            return await self.async_step_character_menu()

        # Highest level first, characters that are already configured are hidden
        chars = sorted(self._account_characters.items(), key=lambda kv: -(kv[1].get("level") or 0))
        options = [
            {
                "value": key,
                "label": f"{c['name']} - {c['realm']} ({game_version_label(c[CONF_GAME_VERSION])}, Lv {c.get('level')}, {c.get('class')})",
            }
            for key, c in chars
            if character_id({CONF_REALM: c["realm_slug"], CONF_CHARACTER_NAME: c["name"], CONF_GAME_VERSION: c[CONF_GAME_VERSION]}) not in existing
        ]
        return self.async_show_form(
            step_id="account_select",
            data_schema=vol.Schema({
                vol.Optional("characters", default=[]): selector.SelectSelector(
                    selector.SelectSelectorConfig(options=options, mode=selector.SelectSelectorMode.LIST, multiple=True)
                ),
                # Preselected when renewing an existing login
                vol.Optional("keep_login", default=CONF_ACCOUNT_TOKEN in self.data): bool,
            }),
            description_placeholders={"character_count": len(options)},
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Log in with Battle.net again: import characters and refresh the account login."""
        entry = self._get_reconfigure_entry()
        self.data = dict(entry.data)
        self.characters = list(entry.data.get(CONF_CHARACTERS, []))
        return await self.async_step_account_login()

    async def async_step_character(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle character game version selection step."""
        if user_input is not None:
            self.current_character = {
                CONF_GAME_VERSION: user_input[CONF_GAME_VERSION]
            }
            return await self.async_step_character_details()

        return self.async_show_form(
            step_id="character",
            data_schema=STEP_GAME_VERSION_SCHEMA,
            description_placeholders={
                "character_count": len(self.characters),
            }
        )

    async def async_step_character_details(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle character details addition step."""
        # Submitting the form empty goes back to the menu
        if user_input is not None and not (user_input.get(CONF_REALM) and user_input.get(CONF_CHARACTER_NAME)):
            return await self.async_step_character_menu()

        result = await self._character_details(
            "character_details",
            self.data,
            self.current_character[CONF_GAME_VERSION],
            self.characters,
            user_input,
        )
        if CONF_REALM in result:
            self.characters.append(result)
            return await self.async_step_character_menu()
        return result

    async def async_step_character_menu(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Manage added characters list and actions."""
        if len(self.characters) == 0:
            return await self.async_step_add_method()

        if user_input is not None:
            action = user_input["action"]
            if action == "add":
                return await self.async_step_add_method()
            elif action == "remove":
                return await self.async_step_remove_character()
            elif action == "finish":
                return await self.async_step_final()

        char_list = "<br/>".join([f"- {c['display_name']} (Lv {c['level']})" for c in self.characters])

        menu_options = [
            {"value": "add", "label": "Add another character"},
            {"value": "remove", "label": "Remove a character"},
            {"value": "finish", "label": "Finish and save configuration"},
        ]

        schema = vol.Schema({
            vol.Required("action", default="finish"): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=menu_options,
                    mode=selector.SelectSelectorMode.LIST,
                    translation_key="character_menu_actions",
                )
            )
        })

        return self.async_show_form(
            step_id="character_menu",
            data_schema=schema,
            description_placeholders={
                "character_list": char_list,
                "character_count": len(self.characters),
            }
        )

    async def async_step_remove_character(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Remove a character in initial setup."""
        if user_input is not None:
            to_remove = user_input["characters_to_remove"]
            self.characters = [c for c in self.characters if character_id(c) not in to_remove]
            return await self.async_step_character_menu()

        options = [
            {"value": character_id(c), "label": c["display_name"]}
            for c in self.characters
        ]

        schema = vol.Schema({
            vol.Required("characters_to_remove"): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=options,
                    mode=selector.SelectSelectorMode.LIST,
                    multiple=True,
                )
            )
        })

        return self.async_show_form(
            step_id="remove_character",
            data_schema=schema,
            description_placeholders={
                "character_count": len(self.characters)
            }
        )

    async def async_step_final(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Final step - create the config entry."""
        if not self.characters:
            return self.async_abort(reason="no_characters")

        # Create unique ID from region and characters
        char_ids = [f"{c[CONF_REALM]}-{c[CONF_CHARACTER_NAME]}" for c in self.characters]
        unique_id = f"{self.data[CONF_REGION]}-{'-'.join(sorted(char_ids))}"

        await self.async_set_unique_id(unique_id)
        self._abort_if_unique_id_configured()

        self.data[CONF_CHARACTERS] = self.characters

        return self.async_create_entry(title=entry_title(self.characters), data=self.data)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        """Get options flow."""
        return WoWBlizzardOptionsFlowHandler()


class WoWBlizzardOptionsFlowHandler(CharacterStepMixin, config_entries.OptionsFlow):
    """Handle options flow."""

    def __init__(self):
        """Initialize options flow."""
        self._current_character = {}
        self._realm_cache = {}

    def _save_characters(self, characters: List[Dict[str, Any]]) -> FlowResult:
        """Store a new character list and finish, keeping the feature options."""
        new_data = dict(self.config_entry.data)
        new_data[CONF_CHARACTERS] = characters
        self.hass.config_entries.async_update_entry(
            self.config_entry,
            title=entry_title(characters),
            data=new_data,
        )
        # Creating the options entry reloads the integration
        return self.async_create_entry(title="", data=dict(self.config_entry.options))

    async def async_step_init(self, user_input=None):
        """Manage the options flow main menu."""
        if user_input is not None:
            action = user_input["action"]
            if action == "features":
                return await self.async_step_features()
            elif action == "add_character":
                return await self.async_step_add_character()
            elif action == "remove_character":
                return await self.async_step_remove_character()
            elif action == "remove_account":
                return await self.async_step_remove_account()

        current_characters = self.config_entry.data.get(CONF_CHARACTERS, [])
        options = [
            {"value": "add_character", "label": "Add a Character"},
            {"value": "features", "label": "Configure Features"},
        ]
        if len(current_characters) > 1:
            options.append({"value": "remove_character", "label": "Remove Character(s)"})
        if CONF_ACCOUNT_TOKEN in self.config_entry.data:
            options.append({"value": "remove_account", "label": "Remove Battle.net login"})

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                vol.Required("action", default="add_character"): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=options,
                        mode=selector.SelectSelectorMode.LIST,
                        translation_key="options_menu_actions",
                    )
                )
            }),
            description_placeholders={
                "character_count": len(current_characters),
            }
        )

    async def async_step_features(self, user_input=None):
        """Manage the options features toggles."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        current_characters = self.config_entry.data.get(CONF_CHARACTERS, [])
        options = self.config_entry.options
        data = self.config_entry.data

        return self.async_show_form(
            step_id="features",
            data_schema=features_schema({
                key: options.get(key, data.get(key, FEATURE_DEFAULTS.get(key, "")))
                for key in FEATURE_KEYS + [CONF_AUCTION_ITEMS]
            }),
            description_placeholders={
                "character_count": len(current_characters),
            }
        )

    async def async_step_remove_account(self, user_input=None):
        """Forget the Battle.net login; characters and all other data stay."""
        if user_input is not None:
            new_data = {k: v for k, v in self.config_entry.data.items() if k != CONF_ACCOUNT_TOKEN}
            self.hass.config_entries.async_update_entry(self.config_entry, data=new_data)
            # Creating the options entry reloads the integration
            return self.async_create_entry(title="", data=dict(self.config_entry.options))
        return self.async_show_form(step_id="remove_account", data_schema=vol.Schema({}))

    async def async_step_add_character(self, user_input=None):
        """Handle character game version selection step in options."""
        if user_input is not None:
            self._current_character = {
                CONF_GAME_VERSION: user_input[CONF_GAME_VERSION]
            }
            return await self.async_step_add_character_details()

        return self.async_show_form(
            step_id="add_character",
            data_schema=STEP_GAME_VERSION_SCHEMA,
            description_placeholders={}
        )

    async def async_step_add_character_details(self, user_input=None):
        """Handle character details addition step in options."""
        # Submitting the form empty goes back to the options menu
        if user_input is not None and not (user_input.get(CONF_REALM) and user_input.get(CONF_CHARACTER_NAME)):
            return await self.async_step_init()

        current_characters = list(self.config_entry.data.get(CONF_CHARACTERS, []))
        result = await self._character_details(
            "add_character_details",
            self.config_entry.data,
            self._current_character[CONF_GAME_VERSION],
            current_characters,
            user_input,
        )
        if CONF_REALM in result:
            return self._save_characters(current_characters + [result])
        return result

    async def async_step_remove_character(self, user_input=None):
        """Handle character removal in options flow."""
        current_characters = self.config_entry.data.get(CONF_CHARACTERS, [])

        if user_input is not None:
            to_remove = user_input["characters_to_remove"]
            new_characters = [c for c in current_characters if character_id(c) not in to_remove]

            # Enforce keeping at least 1 character
            if not new_characters:
                return self.async_abort(reason="no_characters")

            return self._save_characters(new_characters)

        options = [
            {"value": character_id(c), "label": c["display_name"]}
            for c in current_characters
        ]

        return self.async_show_form(
            step_id="remove_character",
            data_schema=vol.Schema({
                vol.Required("characters_to_remove"): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=options,
                        mode=selector.SelectSelectorMode.LIST,
                        multiple=True,
                    )
                )
            }),
            description_placeholders={
                "character_count": len(current_characters),
            }
        )


class CannotConnect(HomeAssistantError):
    """Error to indicate we cannot connect."""


class InvalidAuth(HomeAssistantError):
    """Error to indicate there is invalid auth."""


class CharacterNotFound(HomeAssistantError):
    """Error to indicate character was not found."""
