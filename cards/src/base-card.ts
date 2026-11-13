// What every card shares: the hass object, redrawing only when its own
// entities change, number and date formatting, more-info and the frame.

import { LitElement, html, type PropertyValues } from "lit";
import type { BlockContext } from "./blocks";
import { localize, type StringKey } from "./i18n";
import type { HassEntityState, HomeAssistant, LovelaceCardConfig } from "./types";

export const EDITOR_TYPE = "wow-card-editor";

/** Blizzard timestamps: milliseconds, ISO strings, or "2026-11-13 18:00:00 UTC" from the integration. */
export function toDate(value: unknown): Date | undefined {
  if (typeof value === "number") return new Date(value);
  if (typeof value !== "string" || !value) return undefined;
  const date = new Date(value.endsWith(" UTC") ? value.replace(" UTC", "Z").replace(" ", "T") : value);
  return Number.isNaN(date.getTime()) ? undefined : date;
}

/** One field of a card editor, in ha-form's schema format. */
export type EditorField = Record<string, any>;

export abstract class WowBaseCard<C extends LovelaceCardConfig = LovelaceCardConfig> extends LitElement {
  static properties = {
    hass: { attribute: false },
    _config: { state: true },
  };

  hass?: HomeAssistant;
  protected _config?: C;
  private _watched: HassEntityState[] = [];

  /** The entity states this card shows; it redraws only when one of them changes. */
  protected abstract watched(): HassEntityState[];

  setConfig(config: C) {
    if (!config) throw new Error("Invalid configuration");
    this._config = config;
  }

  getGridOptions() {
    return { columns: 12, rows: "auto", min_columns: 6 };
  }

  static getConfigElement() {
    const editor = document.createElement(EDITOR_TYPE) as HTMLElement & { card?: unknown };
    editor.card = this;
    return editor;
  }

  protected shouldUpdate(changed: PropertyValues): boolean {
    if (changed.has("_config") || !this.hass) return true;
    const oldHass = changed.get("hass") as HomeAssistant | undefined;
    const next = this.watched();
    const previous = this._watched;
    this._watched = next;
    if (!oldHass || oldHass.locale !== this.hass.locale) return true;
    return next.length !== previous.length || next.some((state, i) => state !== previous[i]);
  }

  protected get uiLang(): string {
    return this.hass?.locale?.language ?? this.hass?.language ?? "en";
  }

  protected t(key: StringKey): string {
    return localize(this.uiLang, key);
  }

  protected num(value: number | undefined, digits = 0): string {
    if (value === undefined || Number.isNaN(value)) return "–";
    return new Intl.NumberFormat(this.uiLang, { maximumFractionDigits: digits }).format(value);
  }

  protected date(value: unknown, withTime = false): string {
    const date = toDate(value);
    if (!date) return typeof value === "string" ? value : "";
    return new Intl.DateTimeFormat(this.uiLang, withTime ? { dateStyle: "medium", timeStyle: "short" } : { dateStyle: "medium" }).format(date);
  }

  /** "in 3 days", "2 hours ago" */
  protected relative(value: unknown): string {
    const date = toDate(value);
    if (!date) return "";
    const seconds = (date.getTime() - Date.now()) / 1000;
    const units: Array<[Intl.RelativeTimeFormatUnit, number]> = [["day", 86400], ["hour", 3600], ["minute", 60]];
    const format = new Intl.RelativeTimeFormat(this.uiLang, { numeric: "auto" });
    for (const [unit, size] of units) {
      if (Math.abs(seconds) >= size || unit === "minute") return format.format(Math.round(seconds / size), unit);
    }
    return "";
  }

  protected moreInfo(state?: HassEntityState) {
    if (!state) return;
    this.dispatchEvent(new CustomEvent("hass-more-info", { detail: { entityId: state.entity_id }, bubbles: true, composed: true }));
  }

  protected async copy(text: string) {
    try {
      await navigator.clipboard.writeText(text);
      this.dispatchEvent(new CustomEvent("hass-notification", { detail: { message: this.t("copied") }, bubbles: true, composed: true }));
    } catch {
      // No clipboard without HTTPS; the text stays in the tooltip
    }
  }

  /** The context the building blocks draw with. */
  protected blockContext(entities: Map<string, HassEntityState>): BlockContext {
    return {
      entities,
      lang: this.uiLang,
      t: (key) => this.t(key),
      num: (value, digits) => this.num(value, digits),
      date: (value, withTime) => this.date(value, withTime),
      moreInfo: (state) => this.moreInfo(state),
      copy: (text) => this.copy(text),
    };
  }

  protected message(text: string, error = false) {
    return html`<ha-card><div class="message ${error ? "error" : ""}">${text}</div></ha-card>`;
  }
}
