import { html, nothing, type TemplateResult } from "lit";
import { WowBaseCard } from "./base-card";
import { blockStyles, cssUrl } from "./blocks";
import {
  CHARACTER_MODEL,
  DEFAULT_SECTIONS,
  SECTION_IDS,
  availableSections,
  characterDevices,
  deviceEntities,
  factionOf,
  numericState,
  realmTitle,
  titleOf,
  type CharacterEntities,
  type SectionId,
} from "./data";
import { deviceField, keepOffered, listField } from "./editor";
import type { StringKey } from "./i18n";
import { RENDERERS, type SectionContext } from "./sections";
import { frameStyles, layoutStyles } from "./styles";
import type { HassEntityState, HomeAssistant, LovelaceCardConfig } from "./types";

export const CARD_TYPE = "wow-character-card";

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

const LEGACY_KEYS = ["show_stats", "show_progress", "show_equipment"] as const;

/** The sections to draw, in order, from the config (or the options of the first version). */
export function configSections(config: Partial<CharacterCardConfig>): SectionId[] {
  if (Array.isArray(config.sections)) return keepOffered(config.sections, SECTION_IDS);
  if (LEGACY_KEYS.every((key) => config[key] === undefined)) return [...DEFAULT_SECTIONS];
  const legacy: SectionId[] = [];
  if (config.show_equipment) legacy.push("equipment");
  if (config.show_stats !== false) legacy.push("overview");
  if (config.show_progress !== false) legacy.push("progress");
  return legacy;
}

export class WowCharacterCard extends WowBaseCard<CharacterCardConfig> {
  // --- Card API --------------------------------------------------------------

  static getStubConfig(hass: HomeAssistant) {
    return { device: characterDevices(hass)[0]?.id ?? "", sections: [...DEFAULT_SECTIONS] };
  }

  static editorForm(hass: HomeAssistant, config: CharacterCardConfig, t: (key: StringKey) => string) {
    // Sections the character does not have are not drawn, so they are not offered either
    const available = config.device ? availableSections(deviceEntities(hass, config.device)) : [];
    return {
      schema: [
        deviceField("device", CHARACTER_MODEL),
        listField("sections", available.map((id) => ({ value: id, label: t(`section_${id}` as StringKey) }))),
        { name: "show_render", selector: { boolean: {} } },
      ],
      data: {
        device: config.device || undefined,
        sections: configSections(config).filter((id) => available.includes(id)),
        show_render: config.show_render !== false,
      },
    };
  }

  static editorApply(hass: HomeAssistant, config: CharacterCardConfig, value: Record<string, any>): CharacterCardConfig {
    const device: string = value.device ?? "";
    // Keep only the sections the (possibly new) character has
    const available = device ? availableSections(deviceEntities(hass, device)) : SECTION_IDS;
    const next: CharacterCardConfig = { ...config, device, sections: keepOffered(value.sections, available) };
    for (const key of LEGACY_KEYS) delete next[key];
    if (value.show_render) delete next.show_render;
    else next.show_render = false;
    return next;
  }

  setConfig(config: CharacterCardConfig) {
    if (config?.sections !== undefined && !Array.isArray(config.sections)) {
      throw new Error("sections must be a list, e.g. [overview, progress]");
    }
    super.setConfig(config);
  }

  getCardSize(): number {
    const sections = this._config ? configSections(this._config) : DEFAULT_SECTIONS;
    return 3 + sections.reduce((size, id) => size + (id === "equipment" ? 7 : id === "overview" || id === "progress" ? 1 : 3), 0);
  }

  protected watched(): HassEntityState[] {
    return this.hass && this._config?.device ? [...deviceEntities(this.hass, this._config.device).values()] : [];
  }

  // --- Rendering -------------------------------------------------------------

  protected render(): TemplateResult | typeof nothing {
    if (!this._config || !this.hass) return nothing;
    if (!this._config.device) return this.message(this.t("no_device"));

    const entities = deviceEntities(this.hass, this._config.device);
    if (!entities.size) return this.message(this.t("not_found"), true);

    // Every character sensor carries the profile attributes; pick any loaded one
    const profile = [...entities.values()].find((s) => s.attributes.character_class)?.attributes;
    if (!profile) return this.message(this.t("no_data"));

    // Only sections this character has, e.g. no Mythic+ for a Classic character
    const available = availableSections(entities);
    const sections = configSections(this._config).filter((id) => available.includes(id));
    const faction = factionOf(profile.faction_type);
    const classColor = profile.class_color || "var(--wow-gold)";
    const render = this._config.show_render !== false ? profile.full_body_url || profile.avatar_url : undefined;
    const ctx: SectionContext = { ...this.blockContext(entities), profile, render };

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
    const realm = realmTitle(profile.realm);

    return html`
      <div class="header" @click=${() => this.moreInfo(entities.get("character_level"))}>
        ${profile.avatar_url
          ? html`<img class="avatar" src=${profile.avatar_url} alt="" loading="lazy" />`
          : html`<div class="avatar placeholder"></div>`}
        <div class="ident">
          <div class="name heading">${profile.character_name}</div>
          ${title ? html`<div class="title">${title}</div>` : nothing}
          <div class="line">
            ${this.t("level")} ${level ?? "?"} ${profile.character_race ?? ""}
            <span class="class">${profile.character_class ?? ""}</span>
            ${profile.active_spec ? html`<span class="spec">· ${profile.active_spec}</span>` : nothing}
          </div>
          <div class="line dim">
            ${profile.guild ? html`<span class="guild">&lt;${profile.guild}&gt;</span>` : nothing}
            ${realm}
          </div>
        </div>
        ${itemLevel !== undefined
          ? html`<div class="ilvl" title=${this.t("item_level")}>
              <span class="value heading">${this.num(itemLevel)}</span>
              <span class="label">${this.t("item_level_short")}</span>
            </div>`
          : nothing}
      </div>
    `;
  }

  static styles = [frameStyles, blockStyles, layoutStyles];
}
