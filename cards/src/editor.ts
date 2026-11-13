// Visual editor of all cards. It is a small element around ha-form (the form
// the built-in cards use), because the choices depend on the chosen device: a
// static getConfigForm() cannot offer only the sections a character has.

import { LitElement, html, nothing } from "lit";
import { EDITOR_TYPE, type EditorField } from "./base-card";
import { localize, type StringKey } from "./i18n";
import type { HomeAssistant, LovelaceCardConfig } from "./types";

/** What a card class tells the editor. */
export interface CardEditor<C extends LovelaceCardConfig = LovelaceCardConfig> {
  /** Form fields and their current values for a config */
  editorForm(
    hass: HomeAssistant,
    config: C,
    t: (key: StringKey) => string,
  ): { schema: EditorField[]; data: Record<string, any>; labels?: Record<string, StringKey> };
  /** The new config after the form changed */
  editorApply(hass: HomeAssistant, config: C, value: Record<string, any>): C;
}

/** Helper texts shown below a field, by field name. */
const HELPERS: Partial<Record<string, StringKey>> = {
  sections: "sections_helper",
  items: "items_helper",
  region: "region_helper",
};

export class WowCardEditor extends LitElement {
  static properties = {
    hass: { attribute: false },
    card: { attribute: false },
    _config: { state: true },
  };

  hass?: HomeAssistant;
  card?: CardEditor;
  private _config?: LovelaceCardConfig;

  setConfig(config: LovelaceCardConfig) {
    this._config = config;
  }

  private _t = (key: StringKey) => localize(this.hass?.locale?.language ?? this.hass?.language, key);

  protected render() {
    if (!this.hass || !this._config || !this.card) return nothing;
    const { schema, data, labels } = this.card.editorForm(this.hass, this._config, this._t);
    return html`
      <ha-form
        .hass=${this.hass}
        .data=${data}
        .schema=${schema}
        .computeLabel=${(s: { name: string }) => this._t(labels?.[s.name] ?? (s.name as StringKey))}
        .computeHelper=${(s: { name: string }) => (HELPERS[s.name] ? this._t(HELPERS[s.name]!) : undefined)}
        @value-changed=${this._valueChanged}
      ></ha-form>
    `;
  }

  private _valueChanged(ev: CustomEvent<{ value: Record<string, any> }>) {
    ev.stopPropagation();
    if (!this._config || !this.hass || !this.card) return;
    const config = this.card.editorApply(this.hass, this._config, ev.detail.value);
    this._config = config;
    this.dispatchEvent(new CustomEvent("config-changed", { detail: { config }, bubbles: true, composed: true }));
  }
}

if (!customElements.get(EDITOR_TYPE)) {
  customElements.define(EDITOR_TYPE, WowCardEditor);
}

/** A device picker limited to one kind of device of the integration. */
export function deviceField(name: string, model: string, required = true): EditorField {
  return { name, required, selector: { device: { filter: { integration: "wow_blizzard", model } } } };
}

/** A sortable multi-select. */
export function listField(name: string, options: Array<{ value: string; label: string }>): EditorField {
  return { name, selector: { select: { multiple: true, reorder: true, mode: "dropdown", options } } };
}

/** Keeps the chosen values that are offered, in the chosen order. */
export function keepOffered<T extends string>(values: unknown, offered: T[]): T[] {
  return (Array.isArray(values) ? values : []).filter((v, i, all): v is T => offered.includes(v) && all.indexOf(v) === i);
}
