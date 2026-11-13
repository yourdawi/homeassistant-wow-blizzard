// Hall of Fame: per Mythic raid of the current expansion the world first guild,
// the top guilds and where the guilds of your characters placed.

import { html, nothing, type TemplateResult } from "lit";
import { WowBaseCard } from "./base-card";
import { blockStyles, rows, section, type BlockContext } from "./blocks";
import { DOMAIN, MODELS, devicesOf } from "./data";
import { deviceField, keepOffered, listField } from "./editor";
import { extraStyles, frameStyles, layoutStyles } from "./styles";
import type { HassEntityState, HomeAssistant, LovelaceCardConfig } from "./types";

export const HALL_OF_FAME_CARD_TYPE = "wow-hall-of-fame-card";

// The game shows 200 guilds (100 per faction before unified rankings)
const DEFAULT_TOP = 5;

interface HallOfFameCardConfig extends LovelaceCardConfig {
  device: string;
  /** Raid entities in display order; all raids when not set */
  raids?: string[];
  /** Guilds listed per raid, 0 to 10 */
  top?: number;
}

interface TopGuild {
  rank: number;
  guild: string;
  realm?: string;
  region?: string;
  faction?: string | null;
  timestamp?: number;
}

/** The raid sensors of the device, in the order the integration created them (raid order). */
function raidStates(hass: HomeAssistant, deviceId: string): HassEntityState[] {
  return Object.values(hass.entities)
    .filter((e) => e.device_id === deviceId && e.platform === DOMAIN && !e.hidden)
    .map((e) => hass.states[e.entity_id])
    .filter((s): s is HassEntityState => !!s && s.attributes.raid_name !== undefined);
}

export class WowHallOfFameCard extends WowBaseCard<HallOfFameCardConfig> {
  static getStubConfig(hass: HomeAssistant) {
    return { device: devicesOf(hass, MODELS.leaderboards)[0]?.id ?? "" };
  }

  static editorForm(hass: HomeAssistant, config: HallOfFameCardConfig) {
    const raids = config.device ? raidStates(hass, config.device) : [];
    const ids = raids.map((s) => s.entity_id);
    return {
      schema: [
        deviceField("device", MODELS.leaderboards),
        listField("raids", raids.map((s) => ({ value: s.entity_id, label: String(s.attributes.raid_name) }))),
        { name: "top", selector: { number: { min: 0, max: 10, mode: "slider" } } },
      ],
      data: { device: config.device || undefined, raids: keepOffered(config.raids ?? ids, ids), top: config.top ?? DEFAULT_TOP },
      labels: { device: "device_leaderboards" as const, raids: "raids" as const, top: "top_guilds" as const },
    };
  }

  static editorApply(hass: HomeAssistant, config: HallOfFameCardConfig, value: Record<string, any>): HallOfFameCardConfig {
    const device: string = value.device ?? "";
    const ids = device ? raidStates(hass, device).map((s) => s.entity_id) : [];
    const raids = keepOffered(value.raids, ids);
    const next: HallOfFameCardConfig = { ...config, device, raids, top: Number(value.top ?? DEFAULT_TOP) };
    // All raids in the default order: leave it open so the raids of a new tier show up
    if (device !== config.device || (raids.length === ids.length && raids.every((id, i) => id === ids[i]))) delete next.raids;
    if (next.top === DEFAULT_TOP) delete next.top;
    return next;
  }

  getCardSize() {
    return 2 + (this._config?.raids?.length ?? 4) * (3 + (this._config?.top ?? DEFAULT_TOP) / 2);
  }

  protected watched(): HassEntityState[] {
    return this.hass && this._config?.device ? raidStates(this.hass, this._config.device) : [];
  }

  protected render(): TemplateResult | typeof nothing {
    if (!this._config || !this.hass) return nothing;
    if (!this._config.device) return this.message(this.t("no_device"));
    const all = raidStates(this.hass, this._config.device);
    if (!all.length) return this.message(this.t("not_found"), true);
    const byId = new Map(all.map((s) => [s.entity_id, s]));
    const raids = (this._config.raids ?? all.map((s) => s.entity_id)).map((id) => byId.get(id)).filter((s): s is HassEntityState => !!s);
    const ctx = this.blockContext(new Map());

    return html`
      <ha-card class="neutral">
        <div class="content">
          <div class="header">
            <div class="avatar emblem">♛</div>
            <div class="ident">
              <div class="name heading gold">${this.t("hall_of_fame")}</div>
              <div class="line dim">${this.t("hall_of_fame_subtitle")}</div>
            </div>
          </div>
          ${raids.map((state) => this._raid(state, ctx))}
        </div>
      </ha-card>
    `;
  }

  private _raid(state: HassEntityState, ctx: BlockContext) {
    const a = state.attributes;
    const top = ((a.top_guilds ?? []) as TopGuild[]).slice(0, this._config!.top ?? DEFAULT_TOP);
    const own = Object.entries((a.character_guild_ranks ?? {}) as Record<string, number>).sort((x, y) => x[1] - y[1]);
    const total = Number(a.total_entries) || 0;
    const status = a.completed ? this.t("hof_complete") : total ? `${this.num(total)} ${this.t("guilds")}` : this.t("hof_pending");

    const body = html`
      ${a.world_first_guild
        ? html`<div class="world-first" @click=${() => this.moreInfo(state)}>
            <span class="key gold-key">#1</span>
            <div class="grow">
              <div class="heading first-guild">${a.world_first_guild}</div>
              <div class="dim small">
                ${[a.world_first_realm, a.world_first_region].filter(Boolean).join(" · ")}
                ${a.world_first_timestamp ? html` · ${this.date(a.world_first_timestamp, true)}` : nothing}
              </div>
            </div>
          </div>`
        : html`<div class="dim">${this.t("hof_pending")}</div>`}
      ${top.length > 1
        ? html`<div class="list">
            ${top.slice(1).map(
              (g) => html`
                <div class="list-row">
                  <span class="key">#${g.rank}</span>
                  <span class="grow">${g.guild} <span class="dim">${[g.realm, g.region].filter(Boolean).join(" · ")}</span></span>
                  ${g.timestamp ? html`<span class="dim">${this.date(g.timestamp)}</span>` : nothing}
                </div>
              `,
            )}
          </div>`
        : nothing}
      ${rows(ctx, [
        a.completed && a.last_guild_name
          ? {
              label: `#${a.last_guild_rank ?? total}`,
              value: html`${a.last_guild_name} <span class="dim">${a.last_guild_timestamp ? this.date(a.last_guild_timestamp) : ""}</span>`,
              state,
            }
          : undefined,
        ...own.map(([character, rank]) => ({ label: `${this.t("your_guild")} (${character})`, value: html`<span class="badge">#${rank}</span>`, state })),
      ])}
      ${a.info_url
        ? html`<div class="actions">
            <a class="action" href=${a.info_url} target="_blank" rel="noopener noreferrer">${this.t("open_hall_of_fame")}</a>
          </div>`
        : nothing}
    `;
    return section(ctx, { text: String(a.raid_name ?? state.entity_id) }, body, status);
  }

  static styles = [frameStyles, blockStyles, layoutStyles, extraStyles];
}
