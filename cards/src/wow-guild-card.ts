// The guild of a character: crest, members by class and rank, guild
// achievements and the latest guild activity. Guild entities belong to the
// character device, so the card is set up with a character.

import { html, nothing, type TemplateResult } from "lit";
import { WowBaseCard } from "./base-card";
import { bar, blockStyles, rows, section, tile, tiles, type BlockContext, type Content } from "./blocks";
import { CHARACTER_MODEL, characterDevices, deviceEntities, factionOf, hasValue } from "./data";
import { deviceField, keepOffered, listField } from "./editor";
import type { StringKey } from "./i18n";
import { extraStyles, frameStyles, layoutStyles } from "./styles";
import type { HassEntityState, HomeAssistant, LovelaceCardConfig } from "./types";

export const GUILD_CARD_TYPE = "wow-guild-card";

const SECTIONS = {
  overview: ["guild_members", "guild_max_level_members", "guild_rank", "guild_achievements"],
  classes: ["guild_members"],
  ranks: ["guild_members"],
  achievements: ["guild_achievements"],
  activity: ["guild_activity"],
} as const;
type GuildSection = keyof typeof SECTIONS;
const SECTION_IDS = Object.keys(SECTIONS) as GuildSection[];
const DEFAULT_SECTIONS: GuildSection[] = ["overview", "classes", "achievements", "activity"];

interface GuildCardConfig extends LovelaceCardConfig {
  device: string;
  sections?: GuildSection[];
}

function available(entities: Map<string, HassEntityState>): GuildSection[] {
  return SECTION_IDS.filter((id) => SECTIONS[id].some((key) => hasValue(entities.get(key))));
}

/** Characters whose guild the integration tracks. */
function guildCharacters(hass: HomeAssistant) {
  return characterDevices(hass).filter((d) => available(deviceEntities(hass, d.id)).length);
}

interface GuildAchievement {
  achievement: string;
  timestamp?: number;
}

export class WowGuildCard extends WowBaseCard<GuildCardConfig> {
  static getStubConfig(hass: HomeAssistant) {
    return { device: guildCharacters(hass)[0]?.id ?? "", sections: [...DEFAULT_SECTIONS] };
  }

  static editorForm(hass: HomeAssistant, config: GuildCardConfig, t: (key: StringKey) => string) {
    const offered = config.device ? available(deviceEntities(hass, config.device)) : [];
    return {
      schema: [
        deviceField("device", CHARACTER_MODEL),
        listField("sections", offered.map((id) => ({ value: id, label: t(`guild_${id}` as StringKey) }))),
      ],
      data: { device: config.device || undefined, sections: keepOffered(config.sections ?? DEFAULT_SECTIONS, offered) },
      labels: { device: "device_guild" as StringKey },
    };
  }

  static editorApply(hass: HomeAssistant, config: GuildCardConfig, value: Record<string, any>): GuildCardConfig {
    const device: string = value.device ?? "";
    const offered = device ? available(deviceEntities(hass, device)) : SECTION_IDS;
    return { ...config, device, sections: keepOffered(value.sections, offered) };
  }

  getCardSize() {
    return 2 + (this._config?.sections ?? DEFAULT_SECTIONS).length * 3;
  }

  protected watched(): HassEntityState[] {
    return this.hass && this._config?.device ? [...deviceEntities(this.hass, this._config.device).values()] : [];
  }

  protected render(): TemplateResult | typeof nothing {
    if (!this._config || !this.hass) return nothing;
    if (!this._config.device) return this.message(this.t("no_device"));
    const entities = deviceEntities(this.hass, this._config.device);
    if (!entities.size) return this.message(this.t("not_found"), true);
    const offered = available(entities);
    if (!offered.length) return this.message(this.t("no_guild"));

    const profile = [...entities.values()].find((s) => s.attributes.character_class)?.attributes ?? {};
    const ctx = this.blockContext(entities);
    const sections = keepOffered(this._config.sections ?? DEFAULT_SECTIONS, offered);
    return html`
      <ha-card class=${factionOf(profile.faction_type)}>
        <div class="content">
          ${this._header(entities, profile)}
          ${sections.map((id) => this._section(id, ctx))}
        </div>
      </ha-card>
    `;
  }

  private _header(entities: Map<string, HassEntityState>, profile: Record<string, any>) {
    const members = entities.get("guild_members");
    const crest = entities.get("guild_crest");
    const m = members?.attributes ?? {};
    const picture = hasValue(crest) ? crest.attributes.entity_picture : undefined;
    const guild = profile.guild ?? entities.get("guild_name")?.state;
    return html`
      <div class="header" @click=${() => this.moreInfo(crest ?? members)}>
        ${picture ? html`<img class="avatar crest" src=${picture} alt="" loading="lazy" />` : html`<div class="avatar emblem">⚑</div>`}
        <div class="ident">
          <div class="name heading guild-name">&lt;${guild}&gt;</div>
          <div class="line dim">${[m.guild_realm, m.guild_faction].filter(Boolean).join(" · ")}</div>
          <div class="line dim">
            ${m.guild_master ? html`${this.t("guild_master")}: <span class="text">${m.guild_master}</span>` : nothing}
            ${m.guild_created ? html` · ${this.t("guild_created")} ${this.date(m.guild_created)}` : nothing}
          </div>
        </div>
      </div>
    `;
  }

  private _section(id: GuildSection, ctx: BlockContext): Content {
    const e = ctx.entities;
    const members = e.get("guild_members");
    switch (id) {
      case "overview":
        return tiles(ctx, [
          tile(ctx, "guild_members", "members"),
          tile(ctx, "guild_max_level_members", "max_level_members"),
          tile(ctx, "guild_rank", "guild_rank"),
          tile(ctx, "guild_achievements", "guild_achievements", { min: 1 }),
          typeof members?.attributes.guild_achievement_points === "number" && members.attributes.guild_achievement_points > 0
            ? { label: this.t("achievement_points_long"), value: this.num(members.attributes.guild_achievement_points), state: members, accent: "var(--wow-gold)" }
            : undefined,
        ]);
      case "classes":
        return this._classes(ctx);
      case "ranks": {
        const byRank = Object.entries((members?.attributes.members_by_rank ?? {}) as Record<string, number>);
        if (!byRank.length) return nothing;
        const max = Math.max(...byRank.map(([, n]) => n));
        const body = html`
          <div class="meters">
            ${byRank.map(
              ([rank, count]) => html`
                <div class="meter" @click=${() => this.moreInfo(members)}>
                  <div class="meter-head">
                    <span>${rank === "0" ? this.t("guild_master") : `${this.t("rank")} ${rank}`}</span>
                    <span class="value">${this.num(count)}</span>
                  </div>
                  ${bar(count, max)}
                </div>
              `,
            )}
          </div>
        `;
        return section(ctx, "guild_ranks", body);
      }
      case "achievements": {
        const state = e.get("guild_achievements");
        if (!hasValue(state)) return nothing;
        const categories = Object.entries((state.attributes.categories ?? {}) as Record<string, { quantity: number; points: number }>)
          .filter(([name]) => name !== "Guild")
          .sort((a, b) => b[1].quantity - a[1].quantity)
          .slice(0, 8);
        const recent = ((state.attributes.recent_achievements ?? []) as GuildAchievement[]).slice(0, 5);
        const body = html`
          ${tiles(ctx, [
            tile(ctx, "guild_achievements", "achievements_completed"),
            typeof state.attributes.total_points === "number"
              ? { label: this.t("achievement_points_long"), value: this.num(state.attributes.total_points), state, accent: "var(--wow-gold)" }
              : undefined,
          ])}
          ${categories.length
            ? rows(ctx, categories.map(([name, c]) => ({ label: name, value: `${this.num(c.quantity)} · ${this.num(c.points)} ${this.t("points")}`, state })))
            : nothing}
          ${recent.length
            ? html`<span class="section-label">${this.t("recent")}</span>
                <div class="list">
                  ${recent.map(
                    (a) => html`<div class="list-row">
                      <span class="grow achievement">${a.achievement}</span>
                      ${a.timestamp ? html`<span class="dim">${this.date(a.timestamp)}</span>` : nothing}
                    </div>`,
                  )}
                </div>`
            : nothing}
        `;
        return section(ctx, "guild_achievements_section", body);
      }
      case "activity": {
        const event = e.get("guild_activity");
        const a = event?.attributes ?? {};
        const text = this._event(a);
        if (!text) return nothing;
        return section(
          ctx,
          "guild_activity",
          rows(ctx, [{ label: this.date(a.timestamp, true), value: text, state: event }]),
        );
      }
    }
  }

  /** Members per class in class colors, with how many of them are at max level. */
  private _classes(ctx: BlockContext): Content {
    const members = ctx.entities.get("guild_members");
    const maxLevel = ctx.entities.get("guild_max_level_members");
    const byClass = Object.entries((members?.attributes.members_by_class ?? {}) as Record<string, number>);
    if (!byClass.length) return nothing;
    const colors = (members?.attributes.class_colors ?? {}) as Record<string, string>;
    const atMax = (maxLevel?.attributes.members_by_class ?? {}) as Record<string, number>;
    const level = maxLevel?.attributes.max_level;
    const max = Math.max(...byClass.map(([, n]) => n));
    const body = html`
      <div class="meters">
        ${byClass.map(
          ([name, count]) => html`
            <div class="meter" @click=${() => this.moreInfo(members)}>
              <div class="meter-head">
                <span style="color: ${colors[name] ?? "var(--wow-text)"}">${name}</span>
                <span class="value">
                  ${this.num(count)}${atMax[name] !== undefined && level ? html` <small class="dim" title=${`${this.t("max_level_members")} (${level})`}>(${this.num(atMax[name])})</small>` : nothing}
                </span>
              </div>
              ${bar(count, max, colors[name] ?? "var(--wow-gold)")}
            </div>
          `,
        )}
      </div>
    `;
    return section(ctx, "guild_classes", body, level ? `(${this.t("max_level_members")} ${level})` : undefined);
  }

  private _event(a: Record<string, any>): string | undefined {
    switch (a.event_type) {
      case "achievement":
        return [a.character, a.achievement].filter(Boolean).join(": ");
      case "encounter":
        return [a.encounter, a.difficulty_name ? `(${a.difficulty_name})` : ""].filter(Boolean).join(" ");
      case "member_joined":
      case "member_left":
        return `${a.character ?? ""} ${this.t(a.event_type)}`.trim();
      default:
        return undefined;
    }
  }

  static styles = [frameStyles, blockStyles, layoutStyles, extraStyles];
}
