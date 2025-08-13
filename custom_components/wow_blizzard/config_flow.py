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


async def validate_character(hass: HomeAssistant, data: dict[str, any], character: dict[str, str]) -> dict[str, any]:
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
            character[CONF_CHARACTER_NAME]
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
        """Handle character addition step with COMPATIBLE realm selector."""
        if user_input is None:
            # Create realm selector from ALL available realms
            realm_options = []
            if "available_realms" in self.data:
                realm_options = [
                    {"value": realm["slug"], "label": realm["name"]}
                    for realm in self.data["available_realms"]  # ALL REALMS!
                ]
                
                _LOGGER.info(f"Showing {len(realm_options)} realms with compatible selector")
            
            if realm_options:
                # Use version-compatible selector
                try:
                    selector_config = create_realm_selector_config(realm_options)
                    schema = vol.Schema({
                        vol.Required(CONF_REALM): selector.SelectSelector(selector_config),
                        vol.Required(CONF_CHARACTER_NAME): str,
                    })
                    _LOGGER.info("Using enhanced realm selector")
                except Exception as e:
                    # Ultimate fallback to text input
                    _LOGGER.warning(f"Selector creation failed ({e}), using text input")
                    schema = STEP_CHARACTER_DATA_SCHEMA
            else:
                # Fallback to text input if no realms loaded
                schema = STEP_CHARACTER_DATA_SCHEMA
                _LOGGER.warning("No realms loaded, falling back to text input")

            return self.async_show_form(
                step_id="character",
                data_schema=schema,
                description_placeholders={
                    "character_count": len(self.characters),
                    "total_realms": len(self.data.get("available_realms", [])),
                    "help_text": "Select your realm from the list, or type manually if not found"
                }
            )

        errors = {}

        try:
            character_info = await validate_character(self.hass, self.data, user_input)
            
            # Check if character already exists
            char_key = f"{user_input[CONF_REALM]}-{user_input[CONF_CHARACTER_NAME]}"
            existing_chars = [
                f"{c[CONF_REALM]}-{c[CONF_CHARACTER_NAME]}" for c in self.characters
            ]
            
            if char_key in existing_chars:
                errors["base"] = "character_already_added"
            else:
                # Add character to list
                character_data = {
                    CONF_REALM: user_input[CONF_REALM],
                    CONF_CHARACTER_NAME: user_input[CONF_CHARACTER_NAME],
                    "display_name": f"{character_info['name']} - {character_info['realm']}",
                    "level": character_info["level"],
                    "character_class": character_info["character_class"],
                    "race": character_info["race"],
                }
                self.characters.append(character_data)
                return await self.async_step_character_confirm()
                
        except CharacterNotFound:
            errors["base"] = "character_not_found"
        except CannotConnect:
            errors["base"] = "cannot_connect"
        except Exception:
            _LOGGER.exception("Unexpected exception validating character")
            errors["base"] = "unknown"

        return self.async_show_form(
            step_id="character",
            data_schema=STEP_CHARACTER_DATA_SCHEMA,
            errors=errors,
            description_placeholders={
                "character_count": len(self.characters),
                "total_realms": len(self.data.get("available_realms", [])),
                "help_text": "Select your realm from the list, or type manually if not found"
            }
        )

    async def async_step_character_confirm(
        self, user_input: dict[str, any] | None = None
    ) -> FlowResult:
        """Confirm character addition and ask for more."""
        if user_input is None:
            current_char = self.characters[-1]
            
            return self.async_show_form(
                step_id="character_confirm",
                data_schema=vol.Schema({
                    vol.Optional("add_another", default=False): bool,
                }),
                description_placeholders={
                    "character_name": current_char["display_name"],
                    "character_level": current_char["level"],
                    "character_class": current_char["character_class"],
                    "character_race": current_char["race"],
                    "total_characters": len(self.characters),
                }
            )

        if user_input.get("add_another", False):
            return await self.async_step_character()
        else:
            return await self.async_step_final()

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
        self.config_entry = config_entry

    async def async_step_init(self, user_input=None):
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        current_characters = self.config_entry.data.get(CONF_CHARACTERS, [])
        
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                vol.Optional(
                    CONF_ENABLE_SERVER_STATUS,
                    default=self.config_entry.data.get(CONF_ENABLE_SERVER_STATUS, True)
                ): bool,
                vol.Optional(
                    CONF_ENABLE_PVP,
                    default=self.config_entry.data.get(CONF_ENABLE_PVP, True)
                ): bool,
                vol.Optional(
                    CONF_ENABLE_RAIDS,
                    default=self.config_entry.data.get(CONF_ENABLE_RAIDS, True)
                ): bool,
                vol.Optional(
                    CONF_ENABLE_MYTHIC_PLUS,
                    default=self.config_entry.data.get(CONF_ENABLE_MYTHIC_PLUS, True)
                ): bool,
            }),
            description_placeholders={
                "character_count": len(current_characters),
                "compatibility": "Using Home Assistant version-compatible selectors"
            }
        )


class CannotConnect(HomeAssistantError):
    """Error to indicate we cannot connect."""


class InvalidAuth(HomeAssistantError):
    """Error to indicate there is invalid auth."""


class CharacterNotFound(HomeAssistantError):
    """Error to indicate character was not found."""