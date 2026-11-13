// The sections of the character card. Each one draws only the values the
// character has, so the same code works for Retail and every Classic version.

import { css, html, nothing, type TemplateResult } from "lit";
import {
  SLOTS_LEFT,
  SLOTS_RIGHT,
  SLOTS_WEAPONS,
  hasValue,
  numericState,
  type CharacterEntities,
  type EquippedItem,
  type SectionId,
} from "./data";
import type { StringKey } from "./i18n";
import type { HassEntityState } from "./types";

export interface SectionContext {
  entities: CharacterEntities;
  profile: Record<string, any>;
  render?: string;
  t(key: StringKey): string;
  num(value: number | undefined, digits?: number): string;
  date(value: unknown, withTime?: boolean): string;
  moreInfo(state?: HassEntityState): void;
  copy(text: string): void;
}

type Renderer = (ctx: SectionContext) => TemplateResult | typeof nothing;
type Content = TemplateResult | typeof nothing;

/** A URL as a CSS url() value; quotes and backslashes in it cannot end the string. */
export function cssUrl(url: string): string {
  return `url("${String(url).replace(/["\\\n]/g, encodeURIComponent)}")`;
}

// --- Building blocks ---------------------------------------------------------

function section(ctx: SectionContext, title: StringKey, body: Content, extra?: string): Content {
  if (body === nothing) return nothing;
  return html`
    <section>
      <h3 class="section-title heading"><span>${ctx.t(title)}${extra ? html` <small>${extra}</small>` : nothing}</span></h3>
      ${body}
    </section>
  `;
}

interface Tile {
  label: string;
  value: string;
  state?: HassEntityState;
  accent?: string;
}

function tiles(ctx: SectionContext, items: Array<Tile | undefined>): Content {
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
function tile(ctx: SectionContext, key: string, label: StringKey, opts: { min?: number; prefix?: string; digits?: number; accent?: string } = {}): Tile | undefined {
  const state = ctx.entities.get(key);
  const value = numericState(state);
  if (value === undefined || value < (opts.min ?? 0)) return undefined;
  return { label: ctx.t(label), value: `${opts.prefix ?? ""}${ctx.num(value, opts.digits)}`, state, accent: opts.accent };
}

interface Row {
  label: string;
  value: string | TemplateResult;
  state?: HassEntityState;
}

function rows(ctx: SectionContext, items: Array<Row | undefined>): Content {
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

function bar(value: number, max: number, color = "var(--wow-gold)") {
  const width = max > 0 ? Math.min(100, (100 * value) / max) : 0;
  return html`<div class="bar" style="--bar: ${color}"><div style="width: ${width}%"></div></div>`;
}

function attr(ctx: SectionContext, key: string, name: string): any {
  return ctx.entities.get(key)?.attributes[name];
}

// --- Sections ----------------------------------------------------------------

const STAT_CHIPS: Array<[string, StringKey, number]> = [
  ["achievement_points", "achievement_points", 0],
  ["pvp_honorable_kills", "honorable_kills", 1],
  ["character_gold", "gold", 0],
  ["pvp_2v2_rating", "rating_2v2", 1],
  ["pvp_3v3_rating", "rating_3v3", 1],
  ["pvp_rbg_rating", "rating_rbg", 1],
  ["pvp_shuffle_rating", "rating_shuffle", 1],
  ["pvp_blitz_rating", "rating_blitz", 1],
];

const overview: Renderer = (ctx) =>
  tiles(ctx, STAT_CHIPS.map(([key, label, min]) => tile(ctx, key, label, { min })));

const RAID_DIFFICULTIES: Array<[string, string]> = [
  ["raid_progress_lfr", "LFR"],
  ["raid_progress_normal", "N"],
  ["raid_progress_heroic", "H"],
  ["raid_progress_mythic", "M"],
];
const DIFFICULTY_COLORS: Record<string, string> = { LFR: "#1eff00", N: "#0070dd", H: "#a335ee", M: "#ff8000" };

function raidDifficulties(ctx: SectionContext) {
  return RAID_DIFFICULTIES.flatMap(([key, short]) => {
    const state = ctx.entities.get(key);
    const kills = numericState(state);
    const total = Number(state?.attributes.total_bosses) || 0;
    return kills !== undefined && total ? [{ key, short, kills, total, state: state!, raids: (state!.attributes.raids ?? {}) as Record<string, string> }] : [];
  });
}

const progress: Renderer = (ctx) => {
  const raids = raidDifficulties(ctx);
  const scoreState = ctx.entities.get("mythicplus_score");
  const score = numericState(scoreState);
  const weekly = numericState(ctx.entities.get("mythicplus_weekly_best"));
  if (!raids.length && !score) return nothing;
  return html`
    <div class="progress">
      ${raids.length
        ? html`<div class="raid">
            <span class="section-label">${ctx.t("raid")}</span>
            ${raids.map(
              (r) => html`
                <div class="difficulty" @click=${() => ctx.moreInfo(r.state)}>
                  ${bar(r.kills, r.total, DIFFICULTY_COLORS[r.short])}
                  <span>${r.kills}/${r.total} ${r.short}</span>
                </div>
              `,
            )}
          </div>`
        : nothing}
      ${score
        ? html`<div class="mplus" @click=${() => ctx.moreInfo(scoreState)}>
            <span class="section-label">${ctx.t("mythic_score")}</span>
            <span class="score heading">${ctx.num(score)}</span>
            ${weekly ? html`<span class="badge" title=${ctx.t("weekly_best")}>+${weekly}</span>` : nothing}
          </div>`
        : nothing}
    </div>
  `;
};

function slot(item?: EquippedItem) {
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

const equipment: Renderer = (ctx) => {
  const items: EquippedItem[] = attr(ctx, "character_equipment", "equipped_items_list") ?? [];
  if (!items.length) return nothing;
  const bySlot = new Map(items.map((item) => [item.slot_type, item]));
  const weapons = SLOTS_WEAPONS.filter((s) => bySlot.has(s) || s !== "RANGED");
  return html`
    <div class="paperdoll">
      <div class="slots">${SLOTS_LEFT.map((s) => slot(bySlot.get(s)))}</div>
      <div class="figure" style=${ctx.render ? `background-image: ${cssUrl(ctx.render)}` : ""}></div>
      <div class="slots">${SLOTS_RIGHT.map((s) => slot(bySlot.get(s)))}</div>
      <div class="weapons">${weapons.map((s) => slot(bySlot.get(s)))}</div>
    </div>
  `;
};

const PRIMARY_STATS: Array<[string, StringKey]> = [
  ["strength", "strength"],
  ["agility", "agility"],
  ["intellect", "intellect"],
  ["stamina", "stamina"],
  ["spirit", "spirit"],
  ["armor", "armor"],
  ["attack_power", "attack_power"],
  ["spell_power", "spell_power"],
];
const SECONDARY_STATS: Array<[string, StringKey]> = [
  ["stat_crit", "crit"],
  ["stat_haste", "haste"],
  ["stat_mastery", "mastery"],
  ["stat_versatility", "versatility"],
];

const stats: Renderer = (ctx) => {
  const health = ctx.entities.get("stat_health");
  const a = health?.attributes ?? {};
  const left = rows(ctx, [
    hasValue(health) && numericState(health) !== undefined
      ? { label: ctx.t("health"), value: ctx.num(numericState(health)), state: health }
      : undefined,
    a.power_type && a.power !== undefined ? { label: a.power_type, value: ctx.num(a.power), state: health } : undefined,
    ...PRIMARY_STATS.map(([key, label]) =>
      typeof a[key] === "number" && a[key] > 0 ? { label: ctx.t(label), value: ctx.num(a[key]), state: health } : undefined,
    ),
  ]);
  const right = rows(
    ctx,
    SECONDARY_STATS.map(([key, label]) => {
      const state = ctx.entities.get(key);
      const value = numericState(state);
      return value !== undefined ? { label: ctx.t(label), value: `${ctx.num(value, 2)} %`, state } : undefined;
    }),
  );
  if (left === nothing && right === nothing) return nothing;
  return section(ctx, "section_stats", html`<div class="columns">${left}${right}</div>`);
};

const talents: Renderer = (ctx) => {
  const state = ctx.entities.get("talents");
  if (!hasValue(state) || state.state === "unknown") return nothing;
  const a = state.attributes;
  const points = a.talent_points as Record<string, number> | undefined;
  const total = points ? Object.values(points).reduce((sum, v) => sum + (v || 0), 0) : 0;
  const list = (a.talent_list ?? []) as string[];
  const glyphs = (a.glyphs ?? []) as string[];
  const body = html`
    ${rows(ctx, [
      a.specialization ? { label: ctx.t("specialization"), value: a.specialization, state } : undefined,
      a.hero_talent_tree ? { label: ctx.t("hero_talents"), value: a.hero_talent_tree, state } : undefined,
    ])}
    ${points
      ? html`<div class="meters">
          ${Object.entries(points).map(
            ([tree, spent]) => html`
              <div class="meter">
                <div class="meter-head"><span>${tree}</span><span class="value">${spent}</span></div>
                ${bar(spent, total, "var(--class-color)")}
              </div>
            `,
          )}
        </div>`
      : nothing}
    ${list.length ? html`<div class="tags">${list.map((name) => html`<span class="tag">${name}</span>`)}</div>` : nothing}
    ${glyphs.length ? html`<div class="tags">${glyphs.map((name) => html`<span class="tag glyph">${name}</span>`)}</div>` : nothing}
    ${a.loadout_code
      ? html`<button class="code" title=${ctx.t("copy")} @click=${() => ctx.copy(a.loadout_code)}>
          <span class="section-label">${ctx.t("loadout")}</span>
          <code>${a.loadout_code}</code>
        </button>`
      : nothing}
  `;
  return section(ctx, "section_talents", body);
};

const raidsSection: Renderer = (ctx) => {
  const difficulties = raidDifficulties(ctx);
  const totalState = ctx.entities.get("raid_kills_total");
  const totalKills = numericState(totalState);
  if (!difficulties.length && totalKills === undefined) return nothing;
  const raidNames = [...new Set(difficulties.flatMap((d) => Object.keys(d.raids)))];
  const expansion = difficulties[0]?.state.attributes.expansion ?? totalState?.attributes.expansion;
  const body = html`
    ${difficulties.length
      ? html`<div class="meters">
          ${difficulties.map(
            (d) => html`
              <div class="meter" @click=${() => ctx.moreInfo(d.state)}>
                <div class="meter-head"><span>${d.short}</span><span class="value">${d.kills}/${d.total}</span></div>
                ${bar(d.kills, d.total, DIFFICULTY_COLORS[d.short])}
              </div>
            `,
          )}
        </div>`
      : nothing}
    ${raidNames.length
      ? html`<table class="grid-table">
          <thead>
            <tr>
              <th></th>
              ${difficulties.map((d) => html`<th style="color: ${DIFFICULTY_COLORS[d.short]}">${d.short}</th>`)}
            </tr>
          </thead>
          <tbody>
            ${raidNames.map(
              (raid) => html`
                <tr>
                  <td>${raid}</td>
                  ${difficulties.map((d) => {
                    const value = d.raids[raid];
                    const [done, all] = String(value ?? "").split("/").map(Number);
                    return html`<td class=${value && done === all ? "complete" : ""}>${value ?? "–"}</td>`;
                  })}
                </tr>
              `,
            )}
          </tbody>
        </table>`
      : nothing}
    ${rows(ctx, [totalKills !== undefined ? { label: ctx.t("raid_kills_total"), value: ctx.num(totalKills), state: totalState } : undefined])}
  `;
  return section(ctx, "section_raids", body, expansion);
};

interface BestRun {
  keystone_level: number;
  timed: boolean;
  duration_minutes?: number;
}

const mythicPlus: Renderer = (ctx) => {
  const top = tiles(ctx, [
    tile(ctx, "mythicplus_score", "mythic_score", { accent: "#ff8000" }),
    tile(ctx, "mythicplus_best_run", "best_key", { min: 1, prefix: "+" }),
    tile(ctx, "mythicplus_weekly_best", "weekly_best", { min: 1, prefix: "+" }),
    tile(ctx, "mythicplus_runs_timed", "runs_timed"),
    tile(ctx, "mythicplus_runs_completed", "runs_completed"),
  ]);
  const runs = Object.entries((attr(ctx, "mythicplus_best_run", "best_runs") ?? {}) as Record<string, BestRun>).sort(
    (a, b) => b[1].keystone_level - a[1].keystone_level,
  );
  if (top === nothing && !runs.length) return nothing;
  const body = html`
    ${top}
    ${runs.length
      ? html`<div class="list">
          ${runs.map(
            ([dungeon, run]) => html`
              <div class="list-row">
                <span class="key ${run.timed ? "timed" : "depleted"}" title=${ctx.t(run.timed ? "timed" : "depleted")}>+${run.keystone_level}</span>
                <span class="grow">${dungeon}</span>
                ${run.duration_minutes ? html`<span class="dim">${ctx.num(run.duration_minutes, 1)} ${ctx.t("minutes")}</span>` : nothing}
              </div>
            `,
          )}
        </div>`
      : nothing}
  `;
  return section(ctx, "section_mythic_plus", body);
};

const pvp: Renderer = (ctx) =>
  section(
    ctx,
    "section_pvp",
    tiles(ctx, [
      tile(ctx, "pvp_2v2_rating", "rating_2v2"),
      tile(ctx, "pvp_3v3_rating", "rating_3v3"),
      tile(ctx, "pvp_rbg_rating", "rating_rbg"),
      tile(ctx, "pvp_shuffle_rating", "rating_shuffle"),
      tile(ctx, "pvp_blitz_rating", "rating_blitz"),
      tile(ctx, "pvp_honor_level", "honor_level"),
      tile(ctx, "pvp_wins_season", "season_wins"),
      tile(ctx, "pvp_honorable_kills", "honorable_kills"),
      tile(ctx, "pvp_rank", "pvp_rank"),
    ]),
  );

interface Profession {
  type: string;
  tier: string | null;
  skill_points: number | null;
  max_skill_points: number | null;
}

const professions: Renderer = (ctx) => {
  const state = ctx.entities.get("professions");
  const all = Object.entries((state?.attributes.professions ?? {}) as Record<string, Profession>);
  if (!all.length) return nothing;
  const group = (type: string, label: StringKey) => {
    const items = all.filter(([, p]) => p.type === type);
    if (!items.length) return nothing;
    return html`
      <span class="section-label">${ctx.t(label)}</span>
      <div class="meters">
        ${items.map(
          ([name, p]) => html`
            <div class="meter" @click=${() => ctx.moreInfo(state)}>
              <div class="meter-head">
                <span>${name}${p.tier && p.tier !== name ? html` <small class="dim">${p.tier}</small>` : nothing}</span>
                <span class="value">${p.max_skill_points ? `${p.skill_points ?? 0}/${p.max_skill_points}` : "–"}</span>
              </div>
              ${bar(p.skill_points ?? 0, p.max_skill_points ?? 0, "#1eff00")}
            </div>
          `,
        )}
      </div>
    `;
  };
  return section(ctx, "section_professions", html`${group("primary", "primary")}${group("secondary", "secondary")}`);
};

const reputations: Renderer = (ctx) => {
  const state = ctx.entities.get("reputations");
  const factions = Object.entries((state?.attributes.factions ?? {}) as Record<string, string>);
  if (!factions.length) return nothing;
  const body = html`
    <div class="list scroll">
      ${factions.map(([name, standing]) => {
        // Classic standings carry progress, e.g. "Friendly (3882/6000)"
        const match = /^(.*?)\s*\((\d+)\/(\d+)\)\s*$/.exec(standing);
        return html`
          <div class="list-row stacked">
            <div class="meter-head"><span>${name}</span><span class="dim">${match ? match[1] : standing}</span></div>
            ${match ? bar(Number(match[2]), Number(match[3])) : nothing}
          </div>
        `;
      })}
    </div>
  `;
  return section(ctx, "section_reputations", body, `${ctx.num(factions.length)} ${ctx.t("factions")}`);
};

const collections: Renderer = (ctx) =>
  section(
    ctx,
    "section_collections",
    tiles(ctx, [
      tile(ctx, "mounts_collected", "mounts"),
      tile(ctx, "pets_collected", "pets"),
      tile(ctx, "toys_collected", "toys"),
      tile(ctx, "heirlooms_collected", "heirlooms"),
      tile(ctx, "transmogs_collected", "transmogs"),
      tile(ctx, "decor_collected", "decor"),
    ]),
  );

interface Achievement {
  achievement: string;
  timestamp?: number;
}

function achievementList(ctx: SectionContext, items: Achievement[]): Content {
  if (!items.length) return nothing;
  return html`
    <div class="list">
      ${items.map(
        (a) => html`
          <div class="list-row">
            <span class="grow achievement">${a.achievement}</span>
            ${a.timestamp ? html`<span class="dim">${ctx.date(a.timestamp)}</span>` : nothing}
          </div>
        `,
      )}
    </div>
  `;
}

const achievements: Renderer = (ctx) => {
  const top = tiles(ctx, [
    tile(ctx, "achievement_points", "achievement_points", { accent: "var(--wow-gold)" }),
    tile(ctx, "achievements_completed", "achievements_completed"),
  ]);
  let recent = (attr(ctx, "achievements_completed", "recent_achievements") ?? []) as Achievement[];
  const latest = ctx.entities.get("character_achievements")?.attributes;
  if (!recent.length && latest?.achievement) recent = [latest as Achievement];
  if (top === nothing && !recent.length) return nothing;
  return section(
    ctx,
    "section_achievements",
    html`${top}${recent.length ? html`<span class="section-label">${ctx.t("recent")}</span>${achievementList(ctx, recent.slice(0, 5))}` : nothing}`,
  );
};

// In-game order of the difficulties a dungeon was completed on
const DIFFICULTY_LETTER: Array<[string, string]> = [["normal", "N"], ["heroic", "H"], ["mythic", "M"], ["mythic_keystone", "M+"]];

const activity: Renderer = (ctx) => {
  const gold = ctx.entities.get("character_gold");
  const g = gold?.attributes ?? {};
  const top = tiles(ctx, [
    tile(ctx, "character_gold", "gold", { accent: "#ffd100" }),
    tile(ctx, "deaths", "deaths"),
    tile(ctx, "quests_completed", "quests_completed"),
    tile(ctx, "active_quests", "active_quests"),
    tile(ctx, "dungeons_completed", "dungeons"),
  ]);
  const info = rows(ctx, [
    g.location ? { label: ctx.t("location"), value: g.location, state: gold } : undefined,
    g.hearthstone ? { label: ctx.t("hearthstone"), value: g.hearthstone, state: gold } : undefined,
    typeof g.total_gold_gained === "number" ? { label: ctx.t("gold_gained"), value: ctx.num(g.total_gold_gained), state: gold } : undefined,
    typeof g.total_gold_lost === "number" ? { label: ctx.t("gold_lost"), value: ctx.num(g.total_gold_lost), state: gold } : undefined,
    ctx.profile.last_login ? { label: ctx.t("last_login"), value: ctx.date(ctx.profile.last_login, true) } : undefined,
  ]);
  const quests = (attr(ctx, "active_quests", "quests") ?? []) as string[];
  const dungeons = Object.entries((attr(ctx, "dungeons_completed", "dungeons") ?? {}) as Record<string, string[]>);
  if (top === nothing && info === nothing && !quests.length && !dungeons.length) return nothing;
  const body = html`
    ${top}${info}
    ${dungeons.length
      ? html`<span class="section-label">${ctx.t("dungeons")}</span>
          <div class="list">
            ${dungeons.map(
              ([name, modes]) => html`
                <div class="list-row">
                  <span class="grow">${name}</span>
                  <span class="dim">${DIFFICULTY_LETTER.filter(([mode]) => modes.includes(mode)).map(([, letter]) => letter).join(" · ")}</span>
                </div>
              `,
            )}
          </div>`
      : nothing}
    ${quests.length
      ? html`<span class="section-label">${ctx.t("active_quests")}</span>
          <div class="tags">${quests.map((q) => html`<span class="tag">${q}</span>`)}</div>`
      : nothing}
  `;
  return section(ctx, "section_activity", body);
};

function guildEvent(ctx: SectionContext, a: Record<string, any>): string | undefined {
  switch (a.event_type) {
    case "achievement":
      return [a.character, a.achievement].filter(Boolean).join(": ");
    case "encounter":
      return [a.encounter, a.difficulty_name ? `(${a.difficulty_name})` : ""].filter(Boolean).join(" ");
    case "member_joined":
    case "member_left":
      return `${a.character ?? a.name ?? ""} ${ctx.t(a.event_type)}`.trim();
    default:
      return undefined;
  }
}

const guild: Renderer = (ctx) => {
  const members = ctx.entities.get("guild_members");
  const crest = ctx.entities.get("guild_crest");
  const event = ctx.entities.get("guild_activity");
  const m = members?.attributes ?? {};
  const top = tiles(ctx, [
    tile(ctx, "guild_members", "members"),
    tile(ctx, "guild_max_level_members", "max_level_members"),
    tile(ctx, "guild_rank", "guild_rank"),
    tile(ctx, "guild_achievements", "guild_achievements", { min: 1 }),
  ]);
  const latest = event?.attributes.event_type ? guildEvent(ctx, event.attributes) : undefined;
  const info = rows(ctx, [
    m.guild_master ? { label: ctx.t("guild_master"), value: m.guild_master, state: members } : undefined,
    m.guild_created ? { label: ctx.t("guild_created"), value: ctx.date(m.guild_created), state: members } : undefined,
    latest
      ? { label: ctx.t("latest_activity"), value: html`${latest} <span class="dim">${ctx.date(event!.attributes.timestamp)}</span>`, state: event }
      : undefined,
  ]);
  if (top === nothing && info === nothing) return nothing;
  const picture = hasValue(crest) ? crest.attributes.entity_picture : undefined;
  const body = html`
    <div class="guild-head">
      ${picture ? html`<img class="crest" src=${picture} alt="" loading="lazy" @click=${() => ctx.moreInfo(crest)} />` : nothing}
      <div>
        <div class="guild-name heading">${ctx.profile.guild ? `<${ctx.profile.guild}>` : ""}</div>
        <div class="dim">${[m.guild_realm, m.guild_faction].filter(Boolean).join(" · ")}</div>
      </div>
    </div>
    ${top}${info}
  `;
  return section(ctx, "section_guild", body);
};

interface HunterPet {
  name: string;
  level?: number;
  creature?: string;
  active?: boolean;
}

const hunterPet: Renderer = (ctx) => {
  const state = ctx.entities.get("hunter_pet");
  const pets = (state?.attributes.pets ?? []) as HunterPet[];
  if (!pets.length) return nothing;
  const body = html`
    <div class="list">
      ${pets.map(
        (pet) => html`
          <div class="list-row" @click=${() => ctx.moreInfo(state)}>
            <span class="grow">${pet.name}${pet.creature && pet.creature !== pet.name ? html` <span class="dim">${pet.creature}</span>` : nothing}</span>
            ${pet.level ? html`<span class="dim">${ctx.t("level")} ${pet.level}</span>` : nothing}
            ${pet.active ? html`<span class="badge">${ctx.t("active")}</span>` : nothing}
          </div>
        `,
      )}
    </div>
  `;
  return section(ctx, "section_hunter_pet", body);
};

export const RENDERERS: Record<SectionId, Renderer> = {
  overview,
  progress,
  equipment,
  stats,
  talents,
  raids: raidsSection,
  mythic_plus: mythicPlus,
  pvp,
  professions,
  reputations,
  collections,
  achievements,
  activity,
  guild,
  hunter_pet: hunterPet,
};

export const sectionStyles = css`
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
  .code {
    display: flex;
    flex-direction: column;
    gap: 2px;
    width: 100%;
    padding: 6px 8px;
    border: 1px dashed var(--wow-gold-dim);
    border-radius: 6px;
    background: rgba(0, 0, 0, 0.35);
    color: var(--wow-text);
    text-align: left;
    cursor: copy;
    font: inherit;
  }
  .code code {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    font-size: 0.75rem;
    color: var(--wow-text-dim);
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
