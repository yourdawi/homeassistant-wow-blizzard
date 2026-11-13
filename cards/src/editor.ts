// Visual editor of the character card. It is a small element around ha-form
// (the form the built-in cards use), because the section list depends on the
// chosen character: a static getConfigForm() cannot offer only the sections
// that character has.

import { LitElement, html, nothing } from "lit";
import { CHARACTER_MODEL, DOMAIN, availableSections, deviceEntities, type SectionId } from "./data";
import { localize, type StringKey } from "./i18n";
import type { HomeAssistant } from "./types";
import { EDITOR_TYPE, configSections, type CharacterCardConfig } from "./wow-character-card";

const LEGACY_KEYS = ["show_stats", "show_progress", "show_equipment"] as const;

interface FormData {
  device?: string;
  sections: SectionId[];
  show_render: boolean;
}

export class WowCharacterCardEditor extends LitElement {
  static properties = {
    hass: { attribute: false },
    _config: { state: true },
  };

  hass?: HomeAssistant;
  private _config?: CharacterCardConfig;

  setConfig(config: CharacterCardConfig) {
    this._config = config;
  }

  private _t(key: StringKey) {
    return localize(this.hass?.locale?.language ?? this.hass?.language, key);
  }

  /** Sections the chosen character has entities for. */
  private _available(device: string | undefined): SectionId[] {
    return this.hass && device ? availableSections(deviceEntities(this.hass, device)) : [];
  }

  private _schema(data: FormData) {
    return [
      {
        name: "device",
        required: true,
        selector: { device: { filter: { integration: DOMAIN, model: CHARACTER_MODEL } } },
      },
      {
        name: "sections",
        selector: {
          select: {
            multiple: true,
            reorder: true,
            mode: "dropdown",
            options: this._available(data.device).map((id) => ({ value: id, label: this._t(`section_${id}` as StringKey) })),
          },
        },
      },
      { name: "show_render", selector: { boolean: {} } },
    ];
  }

  protected render() {
    if (!this.hass || !this._config) return nothing;
    const device = this._config.device || undefined;
    // Sections the character does not have are not drawn, so they are not offered either
    const available = this._available(device);
    const data: FormData = {
      device,
      sections: configSections(this._config).filter((id) => available.includes(id)),
      show_render: this._config.show_render !== false,
    };
    return html`
      <ha-form
        .hass=${this.hass}
        .data=${data}
        .schema=${this._schema(data)}
        .computeLabel=${(s: { name: string }) => this._t(s.name as StringKey)}
        .computeHelper=${(s: { name: string }) => (s.name === "sections" ? this._t("sections_helper") : undefined)}
        @value-changed=${this._valueChanged}
      ></ha-form>
    `;
  }

  private _valueChanged(ev: CustomEvent<{ value: FormData }>) {
    ev.stopPropagation();
    if (!this._config || !this.hass) return;
    const value = ev.detail.value;
    let sections = (value.sections ?? []) as SectionId[];

    // Keep only the sections the (possibly new) character has
    const available = this._available(value.device);
    if (value.device) sections = sections.filter((id) => available.includes(id));

    const config: CharacterCardConfig = { ...this._config, device: value.device ?? "", sections };
    for (const key of LEGACY_KEYS) delete config[key];
    if (value.show_render) delete config.show_render;
    else config.show_render = false;

    this._config = config;
    this.dispatchEvent(new CustomEvent("config-changed", { detail: { config }, bubbles: true, composed: true }));
  }
}

if (!customElements.get(EDITOR_TYPE)) {
  customElements.define(EDITOR_TYPE, WowCharacterCardEditor);
}
