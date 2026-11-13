import { LitElement, css, html, nothing, type PropertyValues, type TemplateResult } from "lit";
import {
  CHARACTER_MODEL,
  DOMAIN,
  SLOTS_LEFT,
  SLOTS_RIGHT,
  SLOTS_WEAPONS,
  characterDevices,
  deviceEntities,
  factionOf,
  numericState,
  titleOf,
  type CharacterEntities,
  type EquippedItem,
} from "./data";
import { localize, uiLanguage, type StringKey } from "./i18n";
import { frameStyles } from "./styles";
import type { HassEntityState, HomeAssistant, LovelaceCardConfig } from "./types";

export const CARD_TYPE = "wow-character-card";

/** A URL as a CSS url() value; quotes and backslashes in it cannot end the string. */
function cssUrl(url: string): string {
  return `url("${String(url).replace(/["\\\n]/g, encodeURIComponent)}")`;
}

interface CharacterCardConfig extends LovelaceCardConfig {
  device: string;
  show_render?: boolean;
  show_stats?: boolean;
  show_progress?: boolean;
  show_equipment?: boolean;
}

const DEFAULTS = { show_render: true, show_stats: true, show_progress: true, show_equipment: false };

// Stat chips in display order: translation key of the sensor, label, minimum value to show it
const STAT_CHIPS: Array<[string, StringKey, number]> = [
  ["achievement_points", "achievement_points", 0],
  ["pvp_honorable_kills", "honorable_kills", 1],
  ["pvp_2v2_rating", "rating_2v2", 1],
  ["pvp_3v3_rating", "rating_3v3", 1],
  ["pvp_rbg_rating", "rating_rbg", 1],
  ["pvp_shuffle_rating", "rating_shuffle", 1],
  ["pvp_blitz_rating", "rating_blitz", 1],
];

const RAID_DIFFICULTIES: Array<[string, string]> = [
  ["raid_progress_lfr", "LFR"],
  ["raid_progress_normal", "N"],
  ["raid_progress_heroic", "H"],
  ["raid_progress_mythic", "M"],
];

export class WowCharacterCard extends LitElement {
  static properties = {
    hass: { attribute: false },
    _config: { state: true },
  };

  hass?: HomeAssistant;
  private _config?: CharacterCardConfig;
  private _entities: CharacterEntities = new Map();

  // --- Card API --------------------------------------------------------------

  static getConfigForm() {
    return {
      schema: [
        {
          name: "device",
          required: true,
          selector: { device: { filter: { integration: DOMAIN, model: CHARACTER_MODEL } } },
        },
        {
          type: "grid",
          name: "",
          schema: [
            { name: "show_render", selector: { boolean: {} }, default: DEFAULTS.show_render },
            { name: "show_stats", selector: { boolean: {} }, default: DEFAULTS.show_stats },
            { name: "show_progress", selector: { boolean: {} }, default: DEFAULTS.show_progress },
            { name: "show_equipment", selector: { boolean: {} }, default: DEFAULTS.show_equipment },
          ],
        },
      ],
      computeLabel: (schema: { name: string }) =>
        schema.name ? localize(uiLanguage(), schema.name as StringKey) : undefined,
    };
  }

  static getStubConfig(hass: HomeAssistant) {
    return { device: characterDevices(hass)[0]?.id ?? "" };
  }

  setConfig(config: CharacterCardConfig) {
    if (!config) throw new Error("Invalid configuration");
    this._config = { ...DEFAULTS, ...config };
  }

  getCardSize(): number {
    const c = this._config ?? DEFAULTS;
    return 3 + (c.show_stats ? 1 : 0) + (c.show_progress ? 1 : 0) + (c.show_equipment ? 6 : 0);
  }

  getGridOptions() {
    return { columns: 12, rows: "auto", min_columns: 6 };
  }

  // --- Rendering -------------------------------------------------------------

  protected shouldUpdate(changed: PropertyValues): boolean {
    if (changed.has("_config")) return true;
    const oldHass = changed.get("hass") as HomeAssistant | undefined;
    if (!this.hass || !this._config?.device) return true;
    const next = deviceEntities(this.hass, this._config.device);
    // Only redraw when one of this character's entities changed
    const changedEntities =
      !oldHass ||
      next.size !== this._entities.size ||
      [...next].some(([key, state]) => this._entities.get(key) !== state);
    this._entities = next;
    return changedEntities || oldHass.locale !== this.hass.locale;
  }

  private _t(key: StringKey): string {
    return localize(this.hass?.locale?.language ?? this.hass?.language, key);
  }

  private _number(value: number | undefined, digits = 0): string {
    if (value === undefined) return "–";
    return new Intl.NumberFormat(this.hass?.locale?.language, { maximumFractionDigits: digits }).format(value);
  }

  protected render(): TemplateResult | typeof nothing {
    if (!this._config || !this.hass) return nothing;
    if (!this._config.device) return this._message(this._t("no_device"));

    const entities = deviceEntities(this.hass, this._config.device);
    this._entities = entities;
    if (!entities.size) return this._message(this._t("not_found"), true);

    // Every character sensor carries the profile attributes; pick any loaded one
    const profile = [...entities.values()].find((s) => s.attributes.character_class)?.attributes;
    if (!profile) return this._message(this._t("no_data"));

    const faction = factionOf(profile.faction_type);
    const classColor = profile.class_color || "var(--wow-gold)";
    const showEquipment = this._config.show_equipment;
    const render = this._config.show_render ? profile.full_body_url || profile.avatar_url : undefined;

    return html`
      <ha-card class=${faction} style="--class-color: ${classColor}">
        ${render && !showEquipment
          ? html`<div class="render-bg" style="background-image: ${cssUrl(render)}"></div>`
          : nothing}
        <div class="content">
          ${this._renderHeader(profile, entities)}
          ${showEquipment ? this._renderEquipment(entities, render) : nothing}
          ${this._config.show_stats ? this._renderStats(entities) : nothing}
          ${this._config.show_progress ? this._renderProgress(entities) : nothing}
        </div>
      </ha-card>
    `;
  }

  private _renderHeader(profile: Record<string, any>, entities: CharacterEntities) {
    const level = profile.character_level ?? numericState(entities.get("character_level"));
    const title = titleOf(entities.get("active_title"), profile.character_name);
    const itemLevel = numericState(entities.get("character_item_level"));
    const realm = String(profile.realm ?? "")
      .replace(/-/g, " ")
      .replace(/\b\w/g, (c) => c.toUpperCase());

    return html`
      <div class="header" @click=${() => this._moreInfo(entities.get("character_level"))}>
        ${profile.avatar_url
          ? html`<img class="avatar" src=${profile.avatar_url} alt="" loading="lazy" />`
          : html`<div class="avatar placeholder"></div>`}
        <div class="ident">
          <div class="name heading">${profile.character_name}</div>
          ${title ? html`<div class="title">${title}</div>` : nothing}
          <div class="line">
            ${this._t("level")} ${level ?? "?"} ${profile.character_race ?? ""}
            <span class="class">${profile.character_class ?? ""}</span>
            ${profile.active_spec ? html`<span class="spec">· ${profile.active_spec}</span>` : nothing}
          </div>
          <div class="line dim">
            ${profile.guild ? html`<span class="guild">&lt;${profile.guild}&gt;</span>` : nothing}
            ${realm}
          </div>
        </div>
        ${itemLevel !== undefined
          ? html`<div class="ilvl" title=${this._t("item_level")}>
              <span class="value heading">${this._number(itemLevel)}</span>
              <span class="label">${this._t("item_level_short")}</span>
            </div>`
          : nothing}
      </div>
    `;
  }

  private _renderStats(entities: CharacterEntities) {
    const chips = STAT_CHIPS.flatMap(([key, label, min]) => {
      const value = numericState(entities.get(key));
      return value !== undefined && value >= min ? [{ key, label, value }] : [];
    });
    if (!chips.length) return nothing;
    return html`
      <div class="chips">
        ${chips.map(
          (chip) => html`
            <div class="chip" @click=${() => this._moreInfo(entities.get(chip.key))}>
              <span class="value">${this._number(chip.value)}</span>
              <span class="label">${this._t(chip.label)}</span>
            </div>
          `,
        )}
      </div>
    `;
  }

  private _renderProgress(entities: CharacterEntities) {
    const raids = RAID_DIFFICULTIES.flatMap(([key, short]) => {
      const state = entities.get(key);
      const kills = numericState(state);
      const total = Number(state?.attributes.total_bosses) || 0;
      return kills !== undefined && total ? [{ key, short, kills, total, state }] : [];
    });
    const score = numericState(entities.get("mythicplus_score"));
    const weekly = numericState(entities.get("mythicplus_weekly_best"));
    if (!raids.length && !score) return nothing;

    return html`
      <div class="progress">
        ${raids.length
          ? html`<div class="raid">
              <span class="section-label">${this._t("raid")}</span>
              ${raids.map(
                (r) => html`
                  <div class="difficulty ${r.short.toLowerCase()}" @click=${() => this._moreInfo(r.state)}>
                    <div class="bar"><div style="width: ${(100 * r.kills) / r.total}%"></div></div>
                    <span>${r.kills}/${r.total} ${r.short}</span>
                  </div>
                `,
              )}
            </div>`
          : nothing}
        ${score
          ? html`<div class="mplus" @click=${() => this._moreInfo(entities.get("mythicplus_score"))}>
              <span class="section-label">${this._t("mythic_score")}</span>
              <span class="score heading">${this._number(score)}</span>
              ${weekly ? html`<span class="weekly" title=${this._t("weekly_best")}>+${weekly}</span>` : nothing}
            </div>`
          : nothing}
      </div>
    `;
  }

  private _renderEquipment(entities: CharacterEntities, render?: string) {
    const items: EquippedItem[] = entities.get("character_equipment")?.attributes.equipped_items_list ?? [];
    const bySlot = new Map(items.map((item) => [item.slot_type, item]));
    const weapons = SLOTS_WEAPONS.filter((slot) => bySlot.has(slot) || slot !== "RANGED");

    return html`
      <div class="paperdoll">
        <div class="slots">${SLOTS_LEFT.map((slot) => this._renderSlot(bySlot.get(slot)))}</div>
        <div class="figure" style=${render ? `background-image: ${cssUrl(render)}` : ""}></div>
        <div class="slots">${SLOTS_RIGHT.map((slot) => this._renderSlot(bySlot.get(slot)))}</div>
        <div class="weapons">${weapons.map((slot) => this._renderSlot(bySlot.get(slot)))}</div>
      </div>
    `;
  }

  private _renderSlot(item?: EquippedItem) {
    if (!item) return html`<div class="slot empty"></div>`;
    const level = item.item_level || undefined;
    const tooltip = [item.name, level ? `${item.slot} · ${level}` : item.slot, item.transmog ? `⟲ ${item.transmog}` : ""]
      .filter(Boolean)
      .join("\n");
    return html`
      <div class="slot" style="--quality: ${item.quality_color}" title=${tooltip}>
        ${item.icon ? html`<img src=${item.icon} alt=${item.name} loading="lazy" />` : nothing}
        ${level ? html`<span class="slot-ilvl">${level}</span>` : nothing}
      </div>
    `;
  }

  private _message(text: string, error = false) {
    return html`<ha-card><div class="message ${error ? "error" : ""}">${text}</div></ha-card>`;
  }

  private _moreInfo(state?: HassEntityState) {
    if (!state) return;
    this.dispatchEvent(
      new CustomEvent("hass-more-info", { detail: { entityId: state.entity_id }, bubbles: true, composed: true }),
    );
  }

  static styles = [
    frameStyles,
    css`
      .render-bg {
        position: absolute;
        inset: 0 0 0 35%;
        /* Renders have wide empty margins; zoom in on the character */
        background-size: auto 230%;
        background-repeat: no-repeat;
        background-position: 55% 18%;
        opacity: 0.55;
        mask-image: linear-gradient(to right, transparent, #000 45%), linear-gradient(to top, transparent, #000 40%);
        mask-composite: intersect;
        -webkit-mask-composite: source-in;
        pointer-events: none;
      }
      .content {
        container-type: inline-size;
        position: relative;
        z-index: 1;
        padding: 16px;
        display: flex;
        flex-direction: column;
        gap: 14px;
      }

      /* Header */
      .header {
        display: flex;
        align-items: center;
        gap: 14px;
        cursor: pointer;
      }
      .avatar {
        width: 64px;
        height: 64px;
        flex: none;
        border-radius: 50%;
        object-fit: cover;
        border: 2px solid var(--class-color);
        box-shadow: 0 0 0 2px #000, 0 0 12px color-mix(in srgb, var(--class-color) 45%, transparent);
        background: #000;
      }
      .ident {
        min-width: 0;
        flex: 1;
      }
      .name {
        font-size: 1.5rem;
        line-height: 1.2;
        color: var(--class-color);
        text-shadow: 0 1px 2px #000;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
      }
      .title {
        font-size: 0.85rem;
        color: var(--wow-gold);
        font-style: italic;
      }
      .line {
        font-size: 0.9rem;
        line-height: 1.4;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
      }
      .line.dim { color: var(--wow-text-dim); }
      .class { color: var(--class-color); }
      .spec { color: var(--wow-text-dim); }
      .guild { color: var(--wow-guild); margin-right: 4px; }
      .ilvl {
        display: flex;
        flex-direction: column;
        align-items: center;
        flex: none;
        padding: 6px 10px;
        border: 1px solid var(--wow-gold-dim);
        border-radius: 6px;
        background: rgba(0, 0, 0, 0.45);
      }
      .ilvl .value {
        font-size: 1.6rem;
        line-height: 1;
        color: #a335ee;
        text-shadow: 0 0 8px rgba(163, 53, 238, 0.5);
      }
      .ilvl .label,
      .chip .label,
      .section-label {
        font-size: 0.7rem;
        text-transform: uppercase;
        letter-spacing: 0.06em;
        color: var(--wow-text-dim);
      }

      @container (max-width: 360px) {
        .avatar { width: 48px; height: 48px; }
        .name { font-size: 1.25rem; }
        .ilvl .value { font-size: 1.3rem; }
        .header { gap: 10px; }
      }

      /* Stat chips */
      .chips {
        display: flex;
        flex-wrap: wrap;
        gap: 8px;
      }
      .chip {
        display: flex;
        flex-direction: column;
        padding: 4px 10px;
        border-radius: 6px;
        background: rgba(0, 0, 0, 0.4);
        border: 1px solid rgba(255, 255, 255, 0.07);
        cursor: pointer;
      }
      .chip .value { font-weight: 600; color: var(--wow-gold); }

      /* Raid and Mythic+ */
      .progress {
        display: flex;
        flex-wrap: wrap;
        gap: 10px 24px;
        align-items: center;
      }
      .raid {
        display: flex;
        align-items: center;
        gap: 10px;
        flex-wrap: wrap;
      }
      .difficulty {
        display: flex;
        flex-direction: column;
        gap: 3px;
        min-width: 56px;
        font-size: 0.8rem;
        cursor: pointer;
      }
      .difficulty .bar {
        height: 5px;
        border-radius: 3px;
        background: rgba(255, 255, 255, 0.1);
        overflow: hidden;
      }
      .difficulty .bar > div { height: 100%; background: var(--diff-color); }
      .difficulty.lfr { --diff-color: #1eff00; }
      .difficulty.n { --diff-color: #0070dd; }
      .difficulty.h { --diff-color: #a335ee; }
      .difficulty.m { --diff-color: #ff8000; }
      .mplus {
        display: flex;
        align-items: baseline;
        gap: 8px;
        cursor: pointer;
      }
      .mplus .score { font-size: 1.3rem; color: #ff8000; }
      .mplus .weekly {
        font-size: 0.8rem;
        padding: 1px 6px;
        border-radius: 4px;
        background: rgba(255, 128, 0, 0.15);
        color: #ffb066;
      }

      /* Paper doll */
      .paperdoll {
        display: grid;
        grid-template-columns: auto 1fr auto;
        gap: 6px 10px;
      }
      .slots {
        display: flex;
        flex-direction: column;
        gap: 6px;
      }
      /* Renders have wide empty margins; crop them so the figure fills the column */
      .figure {
        min-height: 0;
        background-size: cover;
        background-position: center 25%;
        background-repeat: no-repeat;
        border-radius: 6px;
        mask-image: radial-gradient(75% 85% at 50% 45%, #000 55%, transparent 100%);
      }
      .weapons {
        grid-column: 1 / -1;
        display: flex;
        justify-content: center;
        gap: 6px;
      }
      .slot {
        position: relative;
        width: 40px;
        height: 40px;
        border-radius: 4px;
        border: 2px solid var(--quality, #333);
        background: #000;
        box-shadow: 0 0 6px color-mix(in srgb, var(--quality, #000) 40%, transparent);
        overflow: hidden;
      }
      .slot.empty {
        border-color: rgba(255, 255, 255, 0.08);
        background: rgba(0, 0, 0, 0.35);
        box-shadow: none;
      }
      .slot img {
        width: 100%;
        height: 100%;
        display: block;
      }
      .slot-ilvl {
        position: absolute;
        right: 1px;
        bottom: 0;
        font-size: 0.65rem;
        font-weight: 700;
        color: #fff;
        text-shadow: 0 0 2px #000, 0 0 2px #000, 0 0 2px #000;
      }
    `,
  ];
}
