// Finds the entities of a World of Warcraft integration device.
//
// Entity IDs follow the user's language ("sensor.x_stufe"), so the cards look
// entities up by device and translation key, which never change.

import type { HassEntityState, HomeAssistant } from "./types";

export const DOMAIN = "wow_blizzard";

/** Device models of the integration (device_info "model"), one per kind of card. */
export const MODELS = {
  character: "World of Warcraft Character",
  account: "Battle.net Account",
  realm: "World of Warcraft Realm",
  region: "World of Warcraft Region",
  auction: "World of Warcraft Auction House",
  leaderboards: "World of Warcraft Leaderboards",
} as const;
export const CHARACTER_MODEL = MODELS.character;

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

/** All devices of the integration with a model, sorted by name. */
export function devicesOf(hass: HomeAssistant, model: string): Array<{ id: string; name: string }> {
  const ids = new Set(
    Object.values(hass.entities)
      .filter((e) => e.platform === DOMAIN && e.device_id)
      .map((e) => e.device_id as string),
  );
  return [...ids]
    .map((id) => hass.devices[id])
    .filter((d) => d && d.model === model)
    .map((d) => ({ id: d.id, name: deviceName(hass, d.id) }))
    .sort((a, b) => a.name.localeCompare(b.name));
}

/** All character devices of the integration, sorted by name. */
export function characterDevices(hass: HomeAssistant): Array<{ id: string; name: string }> {
  return devicesOf(hass, CHARACTER_MODEL);
}

/** "blackmoore" or "argent-dawn" as "Blackmoore", "Argent Dawn". */
export function realmTitle(slug: unknown): string {
  return String(slug ?? "")
    .replace(/-/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

export function deviceName(hass: HomeAssistant, deviceId: string): string {
  const device = hass.devices[deviceId];
  return device?.name_by_user || device?.name || deviceId;
}

/** All states of a device's wow_blizzard entities, also those without a translation key (auction items). */
export function deviceStates(hass: HomeAssistant, deviceId: string): HassEntityState[] {
  return Object.values(hass.entities)
    .filter((e) => e.device_id === deviceId && e.platform === DOMAIN && !e.hidden)
    .map((e) => hass.states[e.entity_id])
    .filter((s): s is HassEntityState => !!s)
    .sort((a, b) => a.entity_id.localeCompare(b.entity_id));
}

/** States of all wow_blizzard entities with a translation key, across devices. */
export function statesWithKey(hass: HomeAssistant, key: string): HassEntityState[] {
  return Object.values(hass.entities)
    .filter((e) => e.platform === DOMAIN && e.translation_key === key)
    .map((e) => hass.states[e.entity_id])
    .filter((s): s is HassEntityState => !!s)
    .sort((a, b) => a.entity_id.localeCompare(b.entity_id));
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

// --- Card sections -----------------------------------------------------------

/**
 * The parts of the character card, in their default order. A section is offered
 * when the character has at least one of its entities: a Classic character, for
 * example, has no Mythic+ entities and so no Mythic+ section.
 */
export const SECTIONS = {
  overview: ["achievement_points", "pvp_honorable_kills", "character_gold", "pvp_2v2_rating", "pvp_3v3_rating"],
  progress: ["raid_progress_lfr", "raid_progress_normal", "raid_progress_heroic", "raid_progress_mythic", "mythicplus_score"],
  equipment: ["character_equipment"],
  stats: ["stat_health", "stat_crit", "stat_haste", "stat_mastery", "stat_versatility"],
  talents: ["talents"],
  raids: ["raid_progress_lfr", "raid_progress_normal", "raid_progress_heroic", "raid_progress_mythic", "raid_kills_total"],
  mythic_plus: ["mythicplus_score", "mythicplus_best_run", "mythicplus_weekly_best", "mythicplus_runs_completed", "mythicplus_runs_timed"],
  pvp: [
    "pvp_2v2_rating", "pvp_3v3_rating", "pvp_rbg_rating", "pvp_shuffle_rating", "pvp_blitz_rating",
    "pvp_honor_level", "pvp_wins_season", "pvp_honorable_kills", "pvp_rank",
  ],
  professions: ["professions"],
  reputations: ["reputations"],
  collections: ["mounts_collected", "pets_collected", "toys_collected", "heirlooms_collected", "transmogs_collected", "decor_collected"],
  achievements: ["achievements_completed", "achievement_points", "character_achievements"],
  // character_status: every character has the last login, which this section shows
  activity: ["character_gold", "deaths", "quests_completed", "active_quests", "dungeons_completed", "character_status"],
  guild: ["guild_members", "guild_max_level_members", "guild_rank", "guild_achievements", "guild_crest", "guild_activity"],
  hunter_pet: ["hunter_pet"],
} as const;

export type SectionId = keyof typeof SECTIONS;
export const SECTION_IDS = Object.keys(SECTIONS) as SectionId[];
export const DEFAULT_SECTIONS: SectionId[] = ["overview", "progress"];

/** Whether the entity exists and the integration delivers it. */
export function hasValue(state: HassEntityState | undefined): state is HassEntityState {
  return !!state && state.state !== "unavailable";
}

/** The sections this character has entities for, in default order. */
export function availableSections(entities: CharacterEntities): SectionId[] {
  return SECTION_IDS.filter((id) => SECTIONS[id].some((key) => hasValue(entities.get(key))));
}
