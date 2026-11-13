// Finds the entities of a World of Warcraft integration device.
//
// Entity IDs follow the user's language ("sensor.x_stufe"), so the cards look
// entities up by device and translation key, which never change.

import type { HassEntityState, HomeAssistant } from "./types";

export const DOMAIN = "wow_blizzard";
export const CHARACTER_MODEL = "World of Warcraft Character";

export type CharacterEntities = Map<string, HassEntityState>;

/** The states of a device's wow_blizzard entities, keyed by translation key. */
export function deviceEntities(hass: HomeAssistant, deviceId: string): CharacterEntities {
  const result: CharacterEntities = new Map();
  for (const entry of Object.values(hass.entities)) {
    if (entry.device_id !== deviceId || entry.platform !== DOMAIN || !entry.translation_key) continue;
    const state = hass.states[entry.entity_id];
    if (state) result.set(entry.translation_key, state);
  }
  return result;
}

/** All character devices of the integration, sorted by name. */
export function characterDevices(hass: HomeAssistant): Array<{ id: string; name: string }> {
  const ids = new Set(
    Object.values(hass.entities)
      .filter((e) => e.platform === DOMAIN && e.device_id)
      .map((e) => e.device_id as string),
  );
  return [...ids]
    .map((id) => hass.devices[id])
    .filter((d) => d && d.model === CHARACTER_MODEL)
    .map((d) => ({ id: d.id, name: d.name_by_user || d.name || d.id }))
    .sort((a, b) => a.name.localeCompare(b.name));
}

// The integration shows these instead of "unknown" when a character has no title.
// Keep in sync with NO_VALUE_TEXT["active_title"] in custom_components/wow_blizzard/const.py.
const NO_TITLE = new Set([
  "Kein Titel", "No title", "Sin título", "Aucun titre", "Nessun titolo", "Sem título", "Нет звания", "칭호 없음", "无头衔",
]);

/** The active title, or undefined when the character has none. */
export function titleOf(state: HassEntityState | undefined, characterName?: string): string | undefined {
  const title = state?.state;
  if (!title || title === "unknown" || title === "unavailable" || NO_TITLE.has(title)) return undefined;
  return title === characterName ? undefined : title;
}

/** A number from an entity state, or undefined when it is missing or not numeric. */
export function numericState(state: HassEntityState | undefined): number | undefined {
  if (!state) return undefined;
  const value = Number(state.state);
  return state.state === "" || Number.isNaN(value) ? undefined : value;
}

export type Faction = "alliance" | "horde" | "neutral";

/** The faction from faction_type ("ALLIANCE", "HORDE", "NEUTRAL"). */
export function factionOf(type: unknown): Faction {
  const value = String(type ?? "").toLowerCase();
  return value === "alliance" || value === "horde" ? value : "neutral";
}

export interface EquippedItem {
  slot: string;
  slot_type: string;
  name: string;
  item_level: number | null;
  quality: string;
  quality_color: string;
  icon?: string | null;
  transmog?: string | null;
}

/** Paper doll layout: left column, right column, weapons below. */
export const SLOTS_LEFT = ["HEAD", "NECK", "SHOULDER", "BACK", "CHEST", "SHIRT", "TABARD", "WRIST"];
export const SLOTS_RIGHT = ["HANDS", "WAIST", "LEGS", "FEET", "FINGER_1", "FINGER_2", "TRINKET_1", "TRINKET_2"];
export const SLOTS_WEAPONS = ["MAIN_HAND", "OFF_HAND", "RANGED"];
