// A realm: status, population and login queue, the best Mythic+ keys of the
// week on it, and (with a region device) the WoW Token, weekly reset,
// affixes and seasons of its region.

import { html, nothing, type TemplateResult } from "lit";
import { WowBaseCard } from "./base-card";
import { blockStyles, rows, section, tile, tiles, type BlockContext, type Content } from "./blocks";
import { MODELS, deviceEntities, deviceName, devicesOf, hasValue, realmTitle } from "./data";
import { deviceField, keepOffered, listField } from "./editor";
import type { StringKey } from "./i18n";
import { extraStyles, frameStyles, layoutStyles } from "./styles";
import type { HassEntityState, HomeAssistant, LovelaceCardConfig } from "./types";

export const REALM_CARD_TYPE = "wow-realm-card";

const SECTIONS = {
  status: ["realm_status", "realm_population", "realm_queue"],
  mythic_plus: ["mythicplus_realm_best"],
  token: ["wow_token_price", "wow_token_price_classic"],
  reset: ["weekly_reset"],
  mythic_season: ["mythicplus_season", "mythicplus_affixes"],
  pvp_season: ["pvp_season", "pvp_cutoff_gladiator", "pvp_cutoff_hero", "pvp_season_classic", "pvp_season_classicann"],
} as const;
type RealmSection = keyof typeof SECTIONS;
const SECTION_IDS = Object.keys(SECTIONS) as RealmSection[];

interface RealmCardConfig extends LovelaceCardConfig {
  device: string;
  region?: string;
  sections?: RealmSection[];
}

/** Realm and region entities in one map; their translation keys do not overlap. */
function entitiesOf(hass: HomeAssistant, config: Partial<RealmCardConfig>): Map<string, HassEntityState> {
  return new Map([
    ...(config.region ? deviceEntities(hass, config.region) : []),
    ...(config.device ? deviceEntities(hass, config.device) : []),
  ]);
}

function available(entities: Map<string, HassEntityState>): RealmSection[] {
  return SECTION_IDS.filter((id) => SECTIONS[id].some((key) => hasValue(entities.get(key))));
}

interface RealmDungeon {
  best_level: number;
  best_duration_min?: number;
  runs?: number;
}

export class WowRealmCard extends WowBaseCard<RealmCardConfig> {
  static getStubConfig(hass: HomeAssistant) {
    return {
      device: devicesOf(hass, MODELS.realm)[0]?.id ?? "",
      region: devicesOf(hass, MODELS.region)[0]?.id,
      sections: [...SECTION_IDS],
    };
  }

  static editorForm(hass: HomeAssistant, config: RealmCardConfig, t: (key: StringKey) => string) {
    const offered = available(entitiesOf(hass, config));
    return {
      schema: [
        deviceField("device", MODELS.realm),
        deviceField("region", MODELS.region, false),
        listField("sections", offered.map((id) => ({ value: id, label: t(`realm_${id}` as StringKey) }))),
      ],
      data: {
        device: config.device || undefined,
        region: config.region || undefined,
        sections: keepOffered(config.sections ?? SECTION_IDS, offered),
      },
      labels: { device: "device_realm" as StringKey },
    };
  }

  static editorApply(hass: HomeAssistant, config: RealmCardConfig, value: Record<string, any>): RealmCardConfig {
    const next: RealmCardConfig = { ...config, device: value.device ?? "", region: value.region || undefined };
    if (!next.region) delete next.region;
    next.sections = keepOffered(value.sections, available(entitiesOf(hass, next)));
    return next;
  }

  getCardSize() {
    return 2 + (this._config?.sections ?? SECTION_IDS).length * 2;
  }

  protected watched(): HassEntityState[] {
    return this.hass && this._config ? [...entitiesOf(this.hass, this._config).values()] : [];
  }

  protected render(): TemplateResult | typeof nothing {
    if (!this._config || !this.hass) return nothing;
    if (!this._config.device) return this.message(this.t("no_device"));
    const entities = entitiesOf(this.hass, this._config);
    const status = entities.get("realm_status");
    if (!status) return this.message(this.t("not_found"), true);

    const ctx = this.blockContext(entities);
    const offered = available(entities);
    const sections = keepOffered(this._config.sections ?? SECTION_IDS, offered);
    return html`
      <ha-card class="neutral">
        <div class="content">
          ${this._header(status)}
          ${sections.map((id) => this._section(id, ctx))}
        </div>
      </ha-card>
    `;
  }

  private _header(status: HassEntityState) {
    const a = status.attributes;
    const up = a.status_type === "UP";
    const device = this.hass!.devices[this._config!.device];
    const name = a.realm ? realmTitle(a.realm) : deviceName(this.hass!, this._config!.device);
    return html`
      <div class="header" @click=${() => this.moreInfo(status)}>
        <div class="avatar emblem status ${up ? "up" : "down"}"></div>
        <div class="ident">
          <div class="name heading gold">${name}</div>
          <div class="line ${up ? "ok" : "bad"}">${status.state}</div>
          <div class="line dim">${[device?.sw_version, a.locale, a.timezone].filter(Boolean).join(" · ")}</div>
        </div>
      </div>
    `;
  }

  private _section(id: RealmSection, ctx: BlockContext): Content {
    const e = ctx.entities;
    switch (id) {
      case "status": {
        const population = e.get("realm_population");
        const queue = e.get("realm_queue");
        return rows(ctx, [
          hasValue(population) ? { label: this.t("population"), value: population.state, state: population } : undefined,
          hasValue(queue)
            ? { label: this.t("queue"), value: queue.state === "True" ? this.t("queue_active") : this.t("queue_none"), state: queue }
            : undefined,
        ]);
      }
      case "mythic_plus":
        return this._mythicPlus(ctx);
      case "token":
        return section(
          ctx,
          "realm_token",
          tiles(ctx, [
            tile(ctx, "wow_token_price", "token_price", { accent: "#ffd100" }),
            tile(ctx, "wow_token_price_classic", "token_price_classic", { accent: "#ffd100" }),
          ]),
        );
      case "reset": {
        const reset = e.get("weekly_reset");
        if (!hasValue(reset)) return nothing;
        return section(
          ctx,
          "realm_reset",
          rows(ctx, [
            { label: this.t("next_reset"), value: html`${this.date(reset.state, true)} <span class="dim">(${this.relative(reset.state)})</span>`, state: reset },
          ]),
        );
      }
      case "mythic_season": {
        const season = e.get("mythicplus_season");
        const affixes = e.get("mythicplus_affixes");
        const list = (affixes?.attributes.affixes ?? []) as Array<{ name: string; starting_level?: number }>;
        const body = html`
          ${rows(ctx, [
            hasValue(season) ? { label: this.t("season"), value: season.state, state: season } : undefined,
            hasValue(season) && season.attributes.season_start
              ? { label: this.t("season_start"), value: this.date(season.attributes.season_start), state: season }
              : undefined,
          ])}
          ${list.length
            ? html`<span class="section-label">${this.t("affixes")}</span>
                <div class="tags">
                  ${list.map(
                    (affix) => html`<span class="tag" @click=${() => this.moreInfo(affixes)}>
                      ${affix.starting_level ? html`<b>+${affix.starting_level}</b> ` : nothing}${affix.name}
                    </span>`,
                  )}
                </div>`
            : nothing}
        `;
        return section(ctx, "realm_mythic_season", body);
      }
      case "pvp_season": {
        const seasons = ["pvp_season", "pvp_season_classic", "pvp_season_classicann"].map((key) => e.get(key)).filter(hasValue);
        const body = html`
          ${rows(ctx, seasons.map((s) => ({ label: this.t("season"), value: s.state, state: s })))}
          ${tiles(ctx, [
            tile(ctx, "pvp_cutoff_gladiator", "cutoff_gladiator", { accent: "#ff8000" }),
            tile(ctx, "pvp_cutoff_hero", "cutoff_hero", { accent: "#a335ee" }),
          ])}
        `;
        return section(ctx, "realm_pvp_season", body);
      }
    }
  }

  private _mythicPlus(ctx: BlockContext): Content {
    const best = ctx.entities.get("mythicplus_realm_best");
    if (!hasValue(best)) return nothing;
    const dungeons = Object.entries((best.attributes.dungeons ?? {}) as Record<string, RealmDungeon>).sort(
      (a, b) => b[1].best_level - a[1].best_level,
    );
    const own = (best.attributes.own_characters ?? {}) as Record<string, Record<string, { ranking?: number; keystone_level?: number }>>;
    const body = html`
      ${tiles(ctx, [tile(ctx, "mythicplus_realm_best", "best_key_week", { prefix: "+", accent: "#ff8000" })])}
      ${dungeons.length
        ? html`<div class="list">
            ${dungeons.map(
              ([name, d]) => html`
                <div class="list-row">
                  <span class="key timed">+${d.best_level}</span>
                  <span class="grow">${name}</span>
                  ${d.best_duration_min ? html`<span class="dim">${this.num(d.best_duration_min, 1)} ${this.t("minutes")}</span>` : nothing}
                  ${d.runs ? html`<span class="dim">${this.num(d.runs)} ${this.t("runs")}</span>` : nothing}
                </div>
              `,
            )}
          </div>`
        : nothing}
      ${Object.keys(own).length
        ? html`<span class="section-label">${this.t("own_characters")}</span>
            <div class="list">
              ${Object.entries(own).flatMap(([char, runs]) =>
                Object.entries(runs).map(
                  ([dungeon, run]) => html`
                    <div class="list-row">
                      <span class="key timed">+${run.keystone_level ?? "?"}</span>
                      <span class="grow">${char} <span class="dim">${dungeon}</span></span>
                      ${run.ranking ? html`<span class="badge">#${run.ranking}</span>` : nothing}
                    </div>
                  `,
                ),
              )}
            </div>`
        : nothing}
    `;
    return section(ctx, "realm_mythic_plus", body);
  }

  static styles = [frameStyles, blockStyles, layoutStyles, extraStyles];
}
