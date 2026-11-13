// Labels the cards draw themselves. Everything else (names, classes, titles) comes
// from the integration. The languages match the integration's translations/.

const EN = {
  level: "Level",
  item_level: "Item level",
  item_level_short: "ilvl",
  mythic_score: "M+ rating",
  weekly_best: "Weekly best",
  achievement_points: "Achievements",
  honorable_kills: "Honorable kills",
  rating_2v2: "2v2",
  rating_3v3: "3v3",
  rating_rbg: "Rated BG",
  rating_shuffle: "Solo Shuffle",
  rating_blitz: "Blitz",
  raid: "Raid",
  last_login: "Last login",
  no_device: "Choose a character in the card settings.",
  not_found: "Character not found. Is the World of Warcraft integration set up?",
  no_data: "No data from Blizzard yet. The profile may be private or the character inactive.",
  device: "Character",
  show_render: "Show character render",
  show_stats: "Show stats",
  show_progress: "Show raid and Mythic+ progress",
  show_equipment: "Show equipment",
  card_name: "WoW Character",
  card_description: "A World of Warcraft character with render, stats and equipment.",
};

export type StringKey = keyof typeof EN;

// Every language must have every key; the type check fails otherwise
const STRINGS: Record<string, Record<StringKey, string>> = {
  en: EN,
  de: {
    level: "Stufe",
    item_level: "Gegenstandsstufe",
    item_level_short: "ilvl",
    mythic_score: "M+-Wertung",
    weekly_best: "Wochenbestes",
    achievement_points: "Erfolge",
    honorable_kills: "Ehrenhafte Siege",
    rating_2v2: "2v2",
    rating_3v3: "3v3",
    rating_rbg: "Gew. SF",
    rating_shuffle: "Solo-Shuffle",
    rating_blitz: "Blitz",
    raid: "Schlachtzug",
    last_login: "Zuletzt online",
    no_device: "Wähle in den Karteneinstellungen einen Charakter aus.",
    not_found: "Charakter nicht gefunden. Ist die World-of-Warcraft-Integration eingerichtet?",
    no_data: "Noch keine Daten von Blizzard. Das Profil ist evtl. privat oder der Charakter inaktiv.",
    device: "Charakter",
    show_render: "Charakterbild anzeigen",
    show_stats: "Werte anzeigen",
    show_progress: "Schlachtzug- und Mythisch+-Fortschritt anzeigen",
    show_equipment: "Ausrüstung anzeigen",
    card_name: "WoW-Charakter",
    card_description: "Ein World-of-Warcraft-Charakter mit Bild, Werten und Ausrüstung.",
  },
};

/** Language of the Home Assistant profile, for places without a hass object. */
export function uiLanguage(): string {
  const hass = (document.querySelector("home-assistant") as { hass?: { locale?: { language?: string } } } | null)?.hass;
  return hass?.locale?.language || document.documentElement.lang || navigator.language;
}

export function localize(language: string | undefined, key: StringKey): string {
  const lang = (language || "en").split("-")[0];
  return (STRINGS[lang] ?? EN)[key];
}
