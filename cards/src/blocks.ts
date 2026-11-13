// Building blocks shared by all cards: section titles, tiles, label/value rows
// and bars in the style of the in-game UI.

import { css, html, nothing, type TemplateResult } from "lit";
import { numericState } from "./data";
import type { StringKey } from "./i18n";
import type { HassEntityState } from "./types";

/** What the building blocks need from a card. */
export interface BlockContext {
  /** Entity states of the card's device, keyed by translation key */
  entities: Map<string, HassEntityState>;
  /** UI language, e.g. "de" */
  lang: string;
  t(key: StringKey): string;
  num(value: number | undefined, digits?: number): string;
  date(value: unknown, withTime?: boolean): string;
  moreInfo(state?: HassEntityState): void;
  copy(text: string): void;
}

export type Content = TemplateResult | typeof nothing;

/** A URL as a CSS url() value; quotes and backslashes in it cannot end the string. */
export function cssUrl(url: string): string {
  return `url("${String(url).replace(/["\\\n]/g, encodeURIComponent)}")`;
}

export function section(ctx: BlockContext, title: StringKey, body: Content, extra?: string): Content {
  if (body === nothing) return nothing;
  return html`
    <section>
      <h3 class="section-title heading"><span>${ctx.t(title)}${extra ? html` <small>${extra}</small>` : nothing}</span></h3>
      ${body}
    </section>
  `;
}

export interface Tile {
  label: string;
  value: string;
  state?: HassEntityState;
  accent?: string;
}

export function tiles(ctx: BlockContext, items: Array<Tile | undefined>): Content {
  const shown = items.filter((t): t is Tile => !!t);
  if (!shown.length) return nothing;
  return html`
    <div class="chips">
      ${shown.map(
        (tile) => html`
          <div class="chip" style=${tile.accent ? `--accent: ${tile.accent}` : ""} @click=${() => ctx.moreInfo(tile.state)}>
            <span class="value">${tile.value}</span>
            <span class="label">${tile.label}</span>
          </div>
        `,
      )}
    </div>
  `;
}

/** A tile from an entity's numeric state; undefined when it is missing or below min. */
export function tile(ctx: BlockContext, key: string, label: StringKey, opts: { min?: number; prefix?: string; digits?: number; accent?: string } = {}): Tile | undefined {
  const state = ctx.entities.get(key);
  const value = numericState(state);
  if (value === undefined || value < (opts.min ?? 0)) return undefined;
  return { label: ctx.t(label), value: `${opts.prefix ?? ""}${ctx.num(value, opts.digits)}`, state, accent: opts.accent };
}

export interface Row {
  label: string;
  value: string | TemplateResult;
  state?: HassEntityState;
}

export function rows(ctx: BlockContext, items: Array<Row | undefined>): Content {
  const shown = items.filter((r): r is Row => !!r && r.value !== "" && r.value !== undefined);
  if (!shown.length) return nothing;
  return html`
    <dl class="rows">
      ${shown.map(
        (row) => html`
          <div class="row" @click=${() => ctx.moreInfo(row.state)}>
            <dt>${row.label}</dt>
            <dd>${row.value}</dd>
          </div>
        `,
      )}
    </dl>
  `;
}

export function bar(value: number, max: number, color = "var(--wow-gold)") {
  const width = max > 0 ? Math.min(100, (100 * value) / max) : 0;
  return html`<div class="bar" style="--bar: ${color}"><div style="width: ${width}%"></div></div>`;
}

export function attr(ctx: BlockContext, key: string, name: string): any {
  return ctx.entities.get(key)?.attributes[name];
}

export const blockStyles = css`
  section {
    display: flex;
    flex-direction: column;
    gap: 8px;
  }
  .section-title {
    display: flex;
    align-items: center;
    gap: 10px;
    margin: 0;
    font-size: 0.95rem;
    font-weight: normal;
    color: var(--wow-gold);
  }
  .section-title::before,
  .section-title::after {
    content: "";
    flex: 1;
    height: 1px;
    background: linear-gradient(to right, transparent, var(--wow-gold-dim));
  }
  .section-title::after {
    background: linear-gradient(to left, transparent, var(--wow-gold-dim));
  }
  .section-title small {
    font-family: var(--paper-font-body1_-_font-family, sans-serif);
    font-size: 0.75rem;
    color: var(--wow-text-dim);
  }
  .section-label {
    font-size: 0.7rem;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    color: var(--wow-text-dim);
  }
  .dim {
    color: var(--wow-text-dim);
  }

  /* Tiles */
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
  .chip .value {
    font-weight: 600;
    color: var(--accent, var(--wow-gold));
  }
  .chip .label {
    font-size: 0.7rem;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    color: var(--wow-text-dim);
  }

  /* Label/value rows, like the in-game character sheet */
  .rows {
    margin: 0;
    display: flex;
    flex-direction: column;
    gap: 2px;
    min-width: 0;
  }
  .row {
    display: flex;
    justify-content: space-between;
    gap: 12px;
    padding: 3px 8px;
    border-radius: 4px;
    font-size: 0.875rem;
    cursor: pointer;
  }
  .row:nth-child(odd) {
    background: rgba(255, 255, 255, 0.03);
  }
  .row dt {
    color: var(--wow-text-dim);
  }
  .row dd {
    margin: 0;
    text-align: right;
    color: var(--wow-text);
    font-weight: 600;
  }
  .columns {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
    gap: 4px 16px;
  }

  /* Bars */
  .bar {
    height: 5px;
    border-radius: 3px;
    background: rgba(255, 255, 255, 0.1);
    overflow: hidden;
  }
  .bar > div {
    height: 100%;
    background: var(--bar);
  }
  .meters {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
    gap: 8px 16px;
  }
  .meter {
    display: flex;
    flex-direction: column;
    gap: 3px;
    font-size: 0.85rem;
    cursor: pointer;
    min-width: 0;
  }
  .meter-head {
    display: flex;
    justify-content: space-between;
    gap: 8px;
    min-width: 0;
  }
  .meter-head > span:first-child {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .meter-head .value {
    font-weight: 600;
    color: var(--wow-gold);
  }

  /* Lists */
  .list {
    display: flex;
    flex-direction: column;
    gap: 2px;
  }
  .list.scroll {
    max-height: 240px;
    overflow-y: auto;
    padding-right: 4px;
    scrollbar-width: thin;
    scrollbar-color: var(--wow-gold-dim) transparent;
  }
  .list-row {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 4px 8px;
    border-radius: 4px;
    font-size: 0.875rem;
  }
  .list-row.stacked {
    flex-direction: column;
    align-items: stretch;
    gap: 3px;
  }
  .list-row:nth-child(odd) {
    background: rgba(255, 255, 255, 0.03);
  }
  .grow {
    flex: 1;
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .achievement {
    color: #ffd100;
  }
  .key {
    min-width: 34px;
    text-align: center;
    font-weight: 700;
    border-radius: 4px;
    padding: 1px 4px;
  }
  .key.timed {
    color: #ffb066;
    background: rgba(255, 128, 0, 0.15);
  }
  .key.depleted {
    color: var(--wow-text-dim);
    background: rgba(255, 255, 255, 0.06);
  }
  .badge {
    font-size: 0.8rem;
    padding: 1px 6px;
    border-radius: 4px;
    background: rgba(255, 128, 0, 0.15);
    color: #ffb066;
  }
  .tags {
    display: flex;
    flex-wrap: wrap;
    gap: 4px;
  }
  .tag {
    font-size: 0.8rem;
    padding: 2px 8px;
    border-radius: 10px;
    background: rgba(0, 0, 0, 0.4);
    border: 1px solid rgba(255, 255, 255, 0.07);
  }
  .tag.glyph {
    color: #69ccf0;
  }
  /* Buttons in the style of the in-game UI */
  .actions {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 8px;
  }
  .action {
    padding: 4px 12px;
    border: 1px solid var(--wow-gold-dim);
    border-radius: 4px;
    background: linear-gradient(to bottom, #5a1010, #2a0505);
    color: #ffd100;
    font: inherit;
    font-size: 0.8rem;
    text-decoration: none;
    cursor: pointer;
    box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.15);
  }
  .action:hover {
    background: linear-gradient(to bottom, #7a1616, #3a0808);
  }

  /* Raid table */
  .grid-table {
    width: 100%;
    border-collapse: collapse;
    font-size: 0.85rem;
  }
  .grid-table th {
    font-weight: 600;
    padding: 2px 6px;
    text-align: center;
  }
  .grid-table td {
    padding: 3px 6px;
    text-align: center;
    color: var(--wow-text-dim);
  }
  .grid-table td:first-child {
    text-align: left;
    color: var(--wow-text);
  }
  .grid-table tbody tr:nth-child(odd) {
    background: rgba(255, 255, 255, 0.03);
  }
  .grid-table td.complete {
    color: #1eff00;
  }

  /* Guild */
  .guild-head {
    display: flex;
    align-items: center;
    gap: 12px;
  }
  .crest {
    width: 56px;
    height: 56px;
    flex: none;
    border-radius: 6px;
    border: 1px solid var(--wow-gold-dim);
    background: #000;
    cursor: pointer;
  }
  .guild-name {
    font-size: 1.1rem;
    color: var(--wow-guild);
  }

  /* Compact progress */
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
  .mplus {
    display: flex;
    align-items: baseline;
    gap: 8px;
    cursor: pointer;
  }
  .mplus .score {
    font-size: 1.3rem;
    color: #ff8000;
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
`;
