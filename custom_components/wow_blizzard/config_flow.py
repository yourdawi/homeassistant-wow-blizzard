"""Config flow realm selector"""
import asyncio
import logging
import voluptuous as vol
from typing import Dict, Any, List

from homeassistant import config_entries
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import selector

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
    DEFAULT_REGION,
    CONF_GAME_VERSION,
)
from .api_client import WoWBlizzardAPIClient

_LOGGER = logging.getLogger(__name__)

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
            )
        ),
    }
)

STEP_FEATURES_DATA_SCHEMA = vol.Schema(
    {
        vol.Optional(CONF_ENABLE_SERVER_STATUS, default=True): bool,
        vol.Optional(CONF_ENABLE_PVP, default=True): bool,
        vol.Optional(CONF_ENABLE_RAIDS, default=True): bool,
        vol.Optional(CONF_ENABLE_MYTHIC_PLUS, default=True): bool,
    }
)

STEP_GAME_VERSION_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_GAME_VERSION, default="retail"): selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=[
                    {"value": "retail", "label": "Retail"},
                    {"value": "classic", "label": "Classic Progression (e.g. Cataclysm)"},
                    {"value": "classic1x", "label": "Classic Era (Vanilla)"},
                    {"value": "classicann", "label": "Classic Anniversary (Burning Crusade)"},
                ],
                mode=selector.SelectSelectorMode.DROPDOWN,
            )
        ),
    }
)

STEP_CHARACTER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_REALM): str,
        vol.Required(CONF_CHARACTER_NAME): str,
    }
)


def get_compatible_select_mode():
    """Get compatible select mode based on HA version."""
    try:
        # Try new COMBOBOX mode (HA 2024.2+)
        return selector.SelectSelectorMode.COMBOBOX
    except AttributeError:
        try:
            # Fallback to LIST mode with custom_value (HA 2023.8+)
            return selector.SelectSelectorMode.LIST
        except AttributeError:
            # Final fallback to DROPDOWN (older HA versions)
            return selector.SelectSelectorMode.DROPDOWN


def create_realm_selector_config(realm_options: List[Dict[str, str]]) -> selector.SelectSelectorConfig:
    """Create realm selector config compatible with current HA version."""
    try:
        # Try newest approach first (HA 2024.2+)
        return selector.SelectSelectorConfig(
            options=realm_options,
            mode=selector.SelectSelectorMode.COMBOBOX,
            custom_value=True,
            sort=True,
        )
    except AttributeError:
        try:
            # Try LIST mode with custom_value (HA 2023.8+)
            return selector.SelectSelectorConfig(
                options=realm_options,
                mode=selector.SelectSelectorMode.LIST,
                custom_value=True,
            )
        except AttributeError:
            # Fallback to basic DROPDOWN (older HA versions)
            _LOGGER.info("Using fallback DROPDOWN selector for realm selection")
            return selector.SelectSelectorConfig(
                options=realm_options,
                mode=selector.SelectSelectorMode.DROPDOWN,
            )


async def validate_api_credentials(hass: HomeAssistant, data: dict[str, any]) -> dict[str, any]:
    """Validate the API credentials by making a test call."""
    client = WoWBlizzardAPIClient(
        data[CONF_CLIENT_ID], 
        data[CONF_CLIENT_SECRET], 
        data[CONF_REGION]
    )

    try:
        # Get ALL realms (no limit!)
        realms = await client.get_all_realms()
        
        if not realms or "realms" not in realms:
            raise CannotConnect("Unable to fetch realms - API credentials may be invalid")
        
        # Sort realms alphabetically for better UX
        sorted_realms = sorted(realms.get("realms", []), key=lambda x: x.get("name", ""))
        
        _LOGGER.info(f"Loaded {len(sorted_realms)} realms for region {data[CONF_REGION]}")
        
        return {"realms": sorted_realms}
        
    except Exception as e:
        _LOGGER.error("Cannot connect to WoW API: %s", e)
        raise CannotConnect(f"Cannot connect: {e}")
    finally:
        await client.close()


async def validate_character(hass: HomeAssistant, data: dict[str, any], character: dict[str, str], game_version: str) -> dict[str, any]:
    """Validate that a character exists."""
    client = WoWBlizzardAPIClient(
        data[CONF_CLIENT_ID], 
        data[CONF_CLIENT_SECRET], 
        data[CONF_REGION]
    )

    try:
        # Test connection by getting character profile
        character_data = await client.get_character_profile(
            character[CONF_REALM], 
            character[CONF_CHARACTER_NAME],
            game_version=game_version
        )
        
        if not character_data or "name" not in character_data:
            raise CharacterNotFound(f"Character {character[CONF_CHARACTER_NAME]} not found on {character[CONF_REALM]}")
            
        return {
            "name": character_data["name"],
            "level": character_data.get("level", "Unknown"),
            "character_class": character_data.get("character_class", {}).get("name", "Unknown"),
            "race": character_data.get("race", {}).get("name", "Unknown"),
            "realm": character_data.get("realm", {}).get("name", character[CONF_REALM]),
        }
        
    except Exception as e:
        if "not found" in str(e).lower():
            raise CharacterNotFound(f"Character not found: {e}")
        raise CannotConnect(f"Cannot connect: {e}")
    finally:
        await client.close()


class WoWBlizzardConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for WoW Blizzard API."""

    VERSION = 2
    CONNECTION_CLASS = config_entries.CONN_CLASS_CLOUD_POLL

    def __init__(self):
        """Initialize."""
        self.data = {}
        self.characters = []
        self.current_character = {}

    async def async_step_user(
        self, user_input: dict[str, any] | None = None
    ) -> FlowResult:
        """Handle the initial step - API credentials."""
        if user_input is None:
            return self.async_show_form(
                step_id="user",
                data_schema=STEP_USER_DATA_SCHEMA,
                description_placeholders={
                    "setup_url": "https://develop.battle.net/access/clients"
                }
            )

        errors = {}

        try:
            info = await validate_api_credentials(self.hass, user_input)
            self.data.update(user_input)
            self.data["available_realms"] = info.get("realms", [])
            return await self.async_step_features()
        except CannotConnect:
            errors["base"] = "cannot_connect"
        except InvalidAuth:
            errors["base"] = "invalid_auth"
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
        self, user_input: dict[str, any] | None = None
    ) -> FlowResult:
        """Handle feature selection step."""
        if user_input is None:
            return self.async_show_form(
                step_id="features",
                data_schema=STEP_FEATURES_DATA_SCHEMA,
                description_placeholders={
                    "region": self.data[CONF_REGION].upper()
                }
            )

        self.data.update(user_input)
        return await self.async_step_character()

    async def async_step_character(
        self, user_input: dict[str, any] | None = None
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
        self, user_input: dict[str, any] | None = None
    ) -> FlowResult:
        """Handle character details addition step."""
        game_version = self.current_character[CONF_GAME_VERSION]
        
        if user_input is not None:
            realm = user_input.get(CONF_REALM)
            char_name = user_input.get(CONF_CHARACTER_NAME)
            if not realm or not char_name:
                return await self.async_step_character_menu()

        if user_input is None:
            errors = {}
            realm_options = []
            
            # Cache realms on self.data to avoid repeated slow fetches
            cache_key = f"realms_{game_version}"
            if cache_key not in self.data:
                client = WoWBlizzardAPIClient(
                    self.data[CONF_CLIENT_ID],
                    self.data[CONF_CLIENT_SECRET],
                    self.data[CONF_REGION]
                )
                try:
                    realms_data = await client.get_all_realms(game_version=game_version)
                    if realms_data and "realms" in realms_data:
                        sorted_realms = sorted(realms_data["realms"], key=lambda x: x.get("name", ""))
                        self.data[cache_key] = sorted_realms
                    else:
                        self.data[cache_key] = []
                except Exception as e:
                    _LOGGER.error(f"Error loading realms for {game_version}: {e}")
                    errors["base"] = "cannot_connect"
                    self.data[cache_key] = []
                finally:
                    await client.close()
            
            realms_list = self.data.get(cache_key, [])
            if realms_list:
                realm_options = [
                    {"value": realm["slug"], "label": realm["name"]}
                    for realm in realms_list
                ]
            
            if realm_options:
                try:
                    selector_config = create_realm_selector_config(realm_options)
                    schema = vol.Schema({
                        vol.Optional(CONF_REALM): selector.SelectSelector(selector_config),
                        vol.Optional(CONF_CHARACTER_NAME): str,
                    })
                except Exception as e:
                    _LOGGER.warning(f"Selector creation failed ({e}), using text input")
                    schema = vol.Schema({
                        vol.Optional(CONF_REALM): str,
                        vol.Optional(CONF_CHARACTER_NAME): str,
                    })
            else:
                schema = vol.Schema({
                    vol.Optional(CONF_REALM): str,
                    vol.Optional(CONF_CHARACTER_NAME): str,
                })

            return self.async_show_form(
                step_id="character_details",
                data_schema=schema,
                errors=errors,
                description_placeholders={
                    "game_version": "Retail" if game_version == "retail" else ("Classic" if game_version == "classic" else ("Classic Era" if game_version == "classic1x" else "Classic Anniversary"))
                }
            )

        errors = {}

        try:
            character_info = await validate_character(self.hass, self.data, user_input, game_version)
            
            # Check if character already exists
            char_key = f"{user_input[CONF_REALM]}-{user_input[CONF_CHARACTER_NAME]}"
            existing_chars = [
                f"{c[CONF_REALM]}-{c[CONF_CHARACTER_NAME]}" for c in self.characters
            ]
            
            if char_key in existing_chars:
                errors["base"] = "character_already_added"
            else:
                # Add character to list
                version_label = "Retail" if game_version == "retail" else ("Classic" if game_version == "classic" else ("Classic Era" if game_version == "classic1x" else "Classic Anniversary"))
                character_data = {
                    CONF_REALM: user_input[CONF_REALM],
                    CONF_CHARACTER_NAME: user_input[CONF_CHARACTER_NAME],
                    CONF_GAME_VERSION: game_version,
                    "display_name": f"{character_info['name']} - {character_info['realm']} ({version_label})",
                    "level": character_info["level"],
                    "character_class": character_info["character_class"],
                    "race": character_info["race"],
                }
                self.characters.append(character_data)
                return await self.async_step_character_menu()
                
        except CharacterNotFound:
            errors["base"] = "character_not_found"
        except CannotConnect:
            errors["base"] = "cannot_connect"
        except Exception:
            _LOGGER.exception("Unexpected exception validating character")
            errors["base"] = "unknown"

        # Re-create selector schema on error
        cache_key = f"realms_{game_version}"
        realms_list = self.data.get(cache_key, [])
        realm_options = [
            {"value": realm["slug"], "label": realm["name"]}
            for realm in realms_list
        ]
        if realm_options:
            try:
                selector_config = create_realm_selector_config(realm_options)
                schema = vol.Schema({
                    vol.Optional(CONF_REALM): selector.SelectSelector(selector_config),
                    vol.Optional(CONF_CHARACTER_NAME): str,
                })
            except Exception:
                schema = vol.Schema({
                    vol.Optional(CONF_REALM): str,
                    vol.Optional(CONF_CHARACTER_NAME): str,
                })
        else:
            schema = vol.Schema({
                vol.Optional(CONF_REALM): str,
                vol.Optional(CONF_CHARACTER_NAME): str,
            })

        return self.async_show_form(
            step_id="character_details",
            data_schema=schema,
            errors=errors,
            description_placeholders={
                "game_version": "Retail" if game_version == "retail" else ("Classic" if game_version == "classic" else ("Classic Era" if game_version == "classic1x" else "Classic Anniversary"))
            }
        )

    async def async_step_character_menu(
        self, user_input: dict[str, any] | None = None
    ) -> FlowResult:
        """Manage added characters list and actions."""
        if len(self.characters) == 0:
            return await self.async_step_character()

        if user_input is not None:
            action = user_input["action"]
            if action == "add":
                return await self.async_step_character()
            elif action == "remove":
                return await self.async_step_remove_character()
            elif action == "finish":
                return await self.async_step_final()

        char_list = "<br>".join([f"• {c['display_name']} (Lv {c['level']})" for c in self.characters])

        menu_options = [
            {"value": "add", "label": "Add another character"},
            {"value": "finish", "label": "Finish and save configuration"},
        ]
        if len(self.characters) > 0:
            menu_options.insert(1, {"value": "remove", "label": "Remove a character"})

        schema = vol.Schema({
            vol.Required("action", default="finish"): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=menu_options,
                    mode=selector.SelectSelectorMode.LIST,
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
        self, user_input: dict[str, any] | None = None
    ) -> FlowResult:
        """Remove a character in initial setup."""
        if user_input is not None:
            to_remove = user_input["characters_to_remove"]
            self.characters = [c for c in self.characters if f"{c[CONF_REALM]}-{c[CONF_CHARACTER_NAME]}" not in to_remove]
            return await self.async_step_character_menu()

        options = [
            {"value": f"{c[CONF_REALM]}-{c[CONF_CHARACTER_NAME]}", "label": c["display_name"]}
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
        self, user_input: dict[str, any] | None = None
    ) -> FlowResult:
        """Final step - create the config entry."""
        if not self.characters:
            return self.async_abort(reason="no_characters")

        # Create title from characters
        if len(self.characters) == 1:
            title = self.characters[0]["display_name"]
        else:
            title = f"WoW API ({len(self.characters)} characters)"

        # Create unique ID from region and characters
        char_ids = [f"{c[CONF_REALM]}-{c[CONF_CHARACTER_NAME]}" for c in self.characters]
        unique_id = f"{self.data[CONF_REGION]}-{'-'.join(sorted(char_ids))}"
        
        await self.async_set_unique_id(unique_id)
        self._abort_if_unique_id_configured()

        # Store character data
        self.data[CONF_CHARACTERS] = self.characters

        return self.async_create_entry(title=title, data=self.data)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        """Get options flow."""
        return WoWBlizzardOptionsFlowHandler(config_entry)


class WoWBlizzardOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle options flow."""

    def __init__(self, config_entry):
        """Initialize options flow."""
        super().__init__()
        self._config_entry = config_entry
        self._current_character = {}

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

        current_characters = self.config_entry.data.get(CONF_CHARACTERS, [])
        options = [
            {"value": "add_character", "label": "Add a Character"},
            {"value": "features", "label": "Configure Features"},
        ]
        if len(current_characters) > 1:
            options.append({"value": "remove_character", "label": "Remove Character(s)"})

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                vol.Required("action", default="add_character"): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=options,
                        mode=selector.SelectSelectorMode.LIST,
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
        
        return self.async_show_form(
            step_id="features",
            data_schema=vol.Schema({
                vol.Optional(
                    CONF_ENABLE_SERVER_STATUS,
                    default=self.config_entry.options.get(
                        CONF_ENABLE_SERVER_STATUS,
                        self.config_entry.data.get(CONF_ENABLE_SERVER_STATUS, True)
                    )
                ): bool,
                vol.Optional(
                    CONF_ENABLE_PVP,
                    default=self.config_entry.options.get(
                        CONF_ENABLE_PVP,
                        self.config_entry.data.get(CONF_ENABLE_PVP, True)
                    )
                ): bool,
                vol.Optional(
                    CONF_ENABLE_RAIDS,
                    default=self.config_entry.options.get(
                        CONF_ENABLE_RAIDS,
                        self.config_entry.data.get(CONF_ENABLE_RAIDS, True)
                    )
                ): bool,
                vol.Optional(
                    CONF_ENABLE_MYTHIC_PLUS,
                    default=self.config_entry.options.get(
                        CONF_ENABLE_MYTHIC_PLUS,
                        self.config_entry.data.get(CONF_ENABLE_MYTHIC_PLUS, True)
                    )
                ): bool,
            }),
            description_placeholders={
                "character_count": len(current_characters),
            }
        )

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
        game_version = self._current_character[CONF_GAME_VERSION]
        
        if user_input is not None:
            realm = user_input.get(CONF_REALM)
            char_name = user_input.get(CONF_CHARACTER_NAME)
            if not realm or not char_name:
                return await self.async_step_init()

        if user_input is None:
            errors = {}
            realm_options = []
            
            cache_key = f"realms_{game_version}"
            if cache_key not in self.hass.data.setdefault(DOMAIN, {}):
                client = WoWBlizzardAPIClient(
                    self.config_entry.data[CONF_CLIENT_ID],
                    self.config_entry.data[CONF_CLIENT_SECRET],
                    self.config_entry.data[CONF_REGION]
                )
                try:
                    realms_data = await client.get_all_realms(game_version=game_version)
                    if realms_data and "realms" in realms_data:
                        sorted_realms = sorted(realms_data["realms"], key=lambda x: x.get("name", ""))
                        self.hass.data[DOMAIN][cache_key] = sorted_realms
                    else:
                        self.hass.data[DOMAIN][cache_key] = []
                except Exception as e:
                    _LOGGER.error(f"Error loading realms for {game_version}: {e}")
                    errors["base"] = "cannot_connect"
                    self.hass.data[DOMAIN][cache_key] = []
                finally:
                    await client.close()
            
            realms_list = self.hass.data[DOMAIN].get(cache_key, [])
            if realms_list:
                realm_options = [
                    {"value": realm["slug"], "label": realm["name"]}
                    for realm in realms_list
                ]
            
            if realm_options:
                try:
                    selector_config = create_realm_selector_config(realm_options)
                    schema = vol.Schema({
                        vol.Optional(CONF_REALM): selector.SelectSelector(selector_config),
                        vol.Optional(CONF_CHARACTER_NAME): str,
                    })
                except Exception as e:
                    schema = vol.Schema({
                        vol.Optional(CONF_REALM): str,
                        vol.Optional(CONF_CHARACTER_NAME): str,
                    })
            else:
                schema = vol.Schema({
                    vol.Optional(CONF_REALM): str,
                    vol.Optional(CONF_CHARACTER_NAME): str,
                })

            return self.async_show_form(
                step_id="add_character_details",
                data_schema=schema,
                errors=errors,
                description_placeholders={
                    "game_version": "Retail" if game_version == "retail" else ("Classic" if game_version == "classic" else ("Classic Era" if game_version == "classic1x" else "Classic Anniversary"))
                }
            )

        errors = {}

        try:
            character_info = await validate_character(self.hass, self.config_entry.data, user_input, game_version)
            
            # Check if character already exists
            char_key = f"{user_input[CONF_REALM]}-{user_input[CONF_CHARACTER_NAME]}"
            existing_chars = [
                f"{c[CONF_REALM]}-{c[CONF_CHARACTER_NAME]}" for c in self.config_entry.data.get(CONF_CHARACTERS, [])
            ]
            
            if char_key in existing_chars:
                errors["base"] = "character_already_added"
            else:
                # Add character to list and update config entry data
                version_label = "Retail" if game_version == "retail" else ("Classic" if game_version == "classic" else ("Classic Era" if game_version == "classic1x" else "Classic Anniversary"))
                character_data = {
                    CONF_REALM: user_input[CONF_REALM],
                    CONF_CHARACTER_NAME: user_input[CONF_CHARACTER_NAME],
                    CONF_GAME_VERSION: game_version,
                    "display_name": f"{character_info['name']} - {character_info['realm']} ({version_label})",
                    "level": character_info["level"],
                    "character_class": character_info["character_class"],
                    "race": character_info["race"],
                }
                
                new_data = dict(self.config_entry.data)
                new_characters = list(new_data.get(CONF_CHARACTERS, []))
                new_characters.append(character_data)
                new_data[CONF_CHARACTERS] = new_characters
                
                # Check if we should update entry title
                if len(new_characters) == 1:
                    title = new_characters[0]["display_name"]
                else:
                    title = f"WoW API ({len(new_characters)} characters)"
                
                self.hass.config_entries.async_update_entry(
                    self.config_entry,
                    title=title,
                    data=new_data
                )
                
                # Close the options flow and reload the integration
                return self.async_create_entry(title="", data={})
                
        except CharacterNotFound:
            errors["base"] = "character_not_found"
        except CannotConnect:
            errors["base"] = "cannot_connect"
        except Exception:
            _LOGGER.exception("Unexpected exception validating character")
            errors["base"] = "unknown"

        # Re-create selector schema on error
        cache_key = f"realms_{game_version}"
        realms_list = self.hass.data[DOMAIN].get(cache_key, [])
        realm_options = [
            {"value": realm["slug"], "label": realm["name"]}
            for realm in realms_list
        ]
        if realm_options:
            try:
                selector_config = create_realm_selector_config(realm_options)
                schema = vol.Schema({
                    vol.Optional(CONF_REALM): selector.SelectSelector(selector_config),
                    vol.Optional(CONF_CHARACTER_NAME): str,
                })
            except Exception:
                schema = vol.Schema({
                    vol.Optional(CONF_REALM): str,
                    vol.Optional(CONF_CHARACTER_NAME): str,
                })
        else:
            schema = vol.Schema({
                vol.Optional(CONF_REALM): str,
                vol.Optional(CONF_CHARACTER_NAME): str,
            })

        return self.async_show_form(
            step_id="add_character_details",
            data_schema=schema,
            errors=errors,
            description_placeholders={
                "game_version": "Retail" if game_version == "retail" else ("Classic" if game_version == "classic" else ("Classic Era" if game_version == "classic1x" else "Classic Anniversary"))
            }
        )

    async def async_step_remove_character(self, user_input=None):
        """Handle character removal in options flow."""
        current_characters = self.config_entry.data.get(CONF_CHARACTERS, [])

        if user_input is not None:
            to_remove = user_input["characters_to_remove"]
            
            # Enforce keeping at least 1 character
            if len(to_remove) >= len(current_characters):
                return self.async_abort(reason="no_characters")
                
            new_characters = [c for c in current_characters if f"{c[CONF_REALM]}-{c[CONF_CHARACTER_NAME]}" not in to_remove]
            new_data = dict(self.config_entry.data)
            new_data[CONF_CHARACTERS] = new_characters
            
            # Update title
            if len(new_characters) == 1:
                title = new_characters[0]["display_name"]
            else:
                title = f"WoW API ({len(new_characters)} characters)"
                
            self.hass.config_entries.async_update_entry(
                self.config_entry,
                title=title,
                data=new_data
            )
            return self.async_create_entry(title="", data={})

        options = [
            {"value": f"{c[CONF_REALM]}-{c[CONF_CHARACTER_NAME]}", "label": c["display_name"]}
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