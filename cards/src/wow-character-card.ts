import { LitElement, css, html, nothing, type PropertyValues, type TemplateResult } from "lit";
import {
  DEFAULT_SECTIONS,
  SECTION_IDS,
  availableSections,
  characterDevices,
  deviceEntities,
  factionOf,
  numericState,
  titleOf,
  type CharacterEntities,
  type SectionId,
} from "./data";
import { localize, type StringKey } from "./i18n";
import { RENDERERS, cssUrl, sectionStyles, type SectionContext } from "./sections";
import { frameStyles } from "./styles";
import type { HassEntityState, HomeAssistant, LovelaceCardConfig } from "./types";

export const CARD_TYPE = "wow-character-card";
export const EDITOR_TYPE = "wow-character-card-editor";

export interface CharacterCardConfig extends LovelaceCardConfig {
  device: string;
  /** Sections in display order; see SECTIONS in data.ts */
  sections?: SectionId[];
  show_render?: boolean;
  // Options of the first version, still read when sections is not set
  show_stats?: boolean;
  show_progress?: boolean;
  show_equipment?: boolean;
}

/** The sections to draw, in order, from the config (or the options of the first version). */
export function configSections(config: Partial<CharacterCardConfig>): SectionId[] {
  if (Array.isArray(config.sections)) {
    return config.sections.filter((id, i, all): id is SectionId => SECTION_IDS.includes(id) && all.indexOf(id) === i);
  }
  if (config.show_stats === undefined && config.show_progress === undefined && config.show_equipment === undefined) {
    return [...DEFAULT_SECTIONS];
  }
  const legacy: SectionId[] = [];
  if (config.show_equipment) legacy.push("equipment");
  if (config.show_stats !== false) legacy.push("overview");
  if (config.show_progress !== false) legacy.push("progress");
  return legacy;
}

/** Blizzard timestamps: milliseconds, or "2026-11-13 18:00:00 UTC" strings from the integration. */
function toDate(value: unknown): Date | undefined {
  if (typeof value === "number") return new Date(value);
  if (typeof value !== "string" || !value) return undefined;
  const date = new Date(value.replace(" UTC", "Z").replace(" ", "T"));
  return Number.isNaN(date.getTime()) ? undefined : date;
}

export class WowCharacterCard extends LitElement {
  static properties = {
    hass: { attribute: false },
    _config: { state: true },
  };

  hass?: HomeAssistant;
  private _config?: CharacterCardConfig;
  private _entities: CharacterEntities = new Map();

  // --- Card API --------------------------------------------------------------

  static getConfigElement() {
    return document.createElement(EDITOR_TYPE);
  }

  static getStubConfig(hass: HomeAssistant) {
    return { device: characterDevices(hass)[0]?.id ?? "", sections: [...DEFAULT_SECTIONS] };
  }

  setConfig(config: CharacterCardConfig) {
    if (!config) throw new Error("Invalid configuration");
    if (config.sections !== undefined && !Array.isArray(config.sections)) {
      throw new Error("sections must be a list, e.g. [overview, progress]");
    }
    this._config = { show_render: true, ...config };
  }

  getCardSize(): number {
    const sections = this._config ? configSections(this._config) : DEFAULT_SECTIONS;
    return 3 + sections.reduce((size, id) => size + (id === "equipment" ? 7 : id === "overview" || id === "progress" ? 1 : 3), 0);
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

  private get _lang(): string | undefined {
    return this.hass?.locale?.language ?? this.hass?.language;
  }

  private _t(key: StringKey): string {
    return localize(this._lang, key);
  }

  private _number(value: number | undefined, digits = 0): string {
    if (value === undefined) return "–";
    return new Intl.NumberFormat(this._lang, { maximumFractionDigits: digits }).format(value);
  }

  private _date(value: unknown, withTime = false): string {
    const date = toDate(value);
    if (!date) return typeof value === "string" ? value : "";
    return new Intl.DateTimeFormat(this._lang, withTime ? { dateStyle: "medium", timeStyle: "short" } : { dateStyle: "medium" }).format(date);
  }

  private _entitiesProfile(): Record<string, any> | undefined {
    return [...this._entities.values()].find((s) => s.attributes.character_class)?.attributes;
  }

  protected render(): TemplateResult | typeof nothing {
    if (!this._config || !this.hass) return nothing;
    if (!this._config.device) return this._message(this._t("no_device"));

    const entities = deviceEntities(this.hass, this._config.device);
    this._entities = entities;
    if (!entities.size) return this._message(this._t("not_found"), true);

    // Every character sensor carries the profile attributes; pick any loaded one
    const profile = this._entitiesProfile();
    if (!profile) return this._message(this._t("no_data"));

    // Only sections this character has, e.g. no Mythic+ for a Classic character
    const available = availableSections(entities);
    const sections = configSections(this._config).filter((id) => available.includes(id));
    const faction = factionOf(profile.faction_type);
    const classColor = profile.class_color || "var(--wow-gold)";
    const render = this._config.show_render !== false ? profile.full_body_url || profile.avatar_url : undefined;
    const ctx: SectionContext = {
      entities,
      profile,
      render,
      t: (key) => this._t(key),
      num: (value, digits) => this._number(value, digits),
      date: (value, withTime) => this._date(value, withTime),
      moreInfo: (state) => this._moreInfo(state),
      copy: (text) => this._copy(text),
    };

    return html`
      <ha-card class=${faction} style="--class-color: ${classColor}">
        ${render && !sections.includes("equipment")
          ? html`<div class="render-bg" style="background-image: ${cssUrl(render)}"></div>`
          : nothing}
        <div class="content">
          ${this._renderHeader(profile, entities)}
          ${sections.map((id) => RENDERERS[id](ctx))}
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

  private _message(text: string, error = false) {
    return html`<ha-card><div class="message ${error ? "error" : ""}">${text}</div></ha-card>`;
  }

  private _moreInfo(state?: HassEntityState) {
    if (!state) return;
    this.dispatchEvent(
      new CustomEvent("hass-more-info", { detail: { entityId: state.entity_id }, bubbles: true, composed: true }),
    );
  }

  private async _copy(text: string) {
    try {
      await navigator.clipboard.writeText(text);
      this.dispatchEvent(
        new CustomEvent("hass-notification", { detail: { message: this._t("copied") }, bubbles: true, composed: true }),
      );
    } catch {
      // No clipboard without HTTPS; the code stays visible in the tooltip
    }
  }

  static styles = [
    frameStyles,
    sectionStyles,
    css`
      .render-bg {
        position: absolute;
        inset: 0 0 0 35%;
        /* Renders have wide empty margins; zoom in on the character */
        background-size: auto 230%;
        background-repeat: no-repeat;
        background-position: 55% 18%;
        max-height: 420px;
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
      .ilvl .label {
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
    `,
  ];
}
