// Battle.net account: total gold, characters, account-wide collections and the
// gold of every character, from the integration's Battle.net account entry.

import { html, nothing, type TemplateResult } from "lit";
import { WowBaseCard } from "./base-card";
import { bar, blockStyles, section, tile, tiles, type BlockContext, type Content } from "./blocks";
import { MODELS, deviceEntities, devicesOf, hasValue, numericState, realmTitle, statesWithKey } from "./data";
import { deviceField, keepOffered, listField } from "./editor";
import type { StringKey } from "./i18n";
import { extraStyles, frameStyles, layoutStyles } from "./styles";
import type { HassEntityState, HomeAssistant, LovelaceCardConfig } from "./types";

export const ACCOUNT_CARD_TYPE = "wow-account-card";

const SECTIONS = {
  overview: ["account_gold_total", "account_characters"],
  collections: ["account_mounts", "account_pets", "account_toys", "account_heirlooms", "account_transmogs", "account_decor"],
  characters: [],
} as const;
type AccountSection = keyof typeof SECTIONS;
const SECTION_IDS = Object.keys(SECTIONS) as AccountSection[];

interface AccountCardConfig extends LovelaceCardConfig {
  device: string;
  sections?: AccountSection[];
}

function available(hass: HomeAssistant, entities: Map<string, HassEntityState>): AccountSection[] {
  return SECTION_IDS.filter((id) =>
    id === "characters"
      ? statesWithKey(hass, "character_gold").some((s) => numericState(s) !== undefined)
      : SECTIONS[id].some((key) => hasValue(entities.get(key))),
  );
}

export class WowAccountCard extends WowBaseCard<AccountCardConfig> {
  static getStubConfig(hass: HomeAssistant) {
    return { device: devicesOf(hass, MODELS.account)[0]?.id ?? "", sections: [...SECTION_IDS] };
  }

  static editorForm(hass: HomeAssistant, config: AccountCardConfig, t: (key: StringKey) => string) {
    const offered = config.device ? available(hass, deviceEntities(hass, config.device)) : [];
    return {
      schema: [
        deviceField("device", MODELS.account),
        listField("sections", offered.map((id) => ({ value: id, label: t(`account_${id}` as StringKey) }))),
      ],
      data: { device: config.device || undefined, sections: keepOffered(config.sections ?? SECTION_IDS, offered) },
      labels: { device: "device_account" as StringKey },
    };
  }

  static editorApply(hass: HomeAssistant, config: AccountCardConfig, value: Record<string, any>): AccountCardConfig {
    const device: string = value.device ?? "";
    const offered = device ? available(hass, deviceEntities(hass, device)) : SECTION_IDS;
    return { ...config, device, sections: keepOffered(value.sections, offered) };
  }

  getCardSize() {
    return 3 + (this._config?.sections ?? SECTION_IDS).length * 2;
  }

  protected watched(): HassEntityState[] {
    if (!this.hass || !this._config?.device) return [];
    return [...deviceEntities(this.hass, this._config.device).values(), ...statesWithKey(this.hass, "character_gold")];
  }

  protected render(): TemplateResult | typeof nothing {
    if (!this._config || !this.hass) return nothing;
    if (!this._config.device) return this.message(this.t("no_device"));
    const entities = deviceEntities(this.hass, this._config.device);
    if (!entities.size) return this.message(this.t("not_found"), true);

    const ctx = this.blockContext(entities);
    const offered = available(this.hass, entities);
    const sections = keepOffered(this._config.sections ?? SECTION_IDS, offered);
    return html`
      <ha-card class="neutral">
        <div class="content">
          ${this._header(entities)}
          ${sections.map((id) => this._section(id, ctx))}
        </div>
      </ha-card>
    `;
  }

  private _header(entities: Map<string, HassEntityState>) {
    const login = entities.get("account_login");
    const valid = !!login?.attributes.login_valid;
    const expires = hasValue(login) ? login.state : undefined;
    return html`
      <div class="header" @click=${() => this.moreInfo(login)}>
        <div class="avatar emblem">⚔</div>
        <div class="ident">
          <div class="name heading gold">${this.t("battlenet_account")}</div>
          <div class="line ${valid ? "ok" : "bad"}">
            ${valid ? html`${this.t("login_valid")} ${expires ? this.relative(expires) : ""}` : this.t("login_expired")}
          </div>
          ${valid ? nothing : html`<div class="line dim">${this.t("login_expired_hint")}</div>`}
        </div>
      </div>
    `;
  }

  private _section(id: AccountSection, ctx: BlockContext): Content {
    switch (id) {
      case "overview":
        return tiles(ctx, [
          tile(ctx, "account_gold_total", "gold_total", { accent: "#ffd100" }),
          tile(ctx, "account_characters", "characters"),
        ]);
      case "collections":
        return section(
          ctx,
          "section_collections",
          tiles(ctx, [
            tile(ctx, "account_mounts", "mounts"),
            tile(ctx, "account_pets", "pets"),
            tile(ctx, "account_toys", "toys"),
            tile(ctx, "account_heirlooms", "heirlooms"),
            tile(ctx, "account_transmogs", "transmogs"),
            tile(ctx, "account_decor", "decor"),
          ]),
        );
      case "characters":
        return this._characters(ctx);
    }
  }

  /** Gold per character, richest first, in class colors. */
  private _characters(ctx: BlockContext): Content {
    const rows = statesWithKey(this.hass!, "character_gold")
      .map((state) => ({ state, gold: numericState(state) }))
      .filter((r): r is { state: HassEntityState; gold: number } => r.gold !== undefined)
      .sort((a, b) => b.gold - a.gold);
    if (!rows.length) return nothing;
    const max = rows[0].gold || 1;
    const body = html`
      <div class="list scroll">
        ${rows.map(({ state, gold }) => {
          const a = state.attributes;
          return html`
            <div class="list-row stacked" @click=${() => this.moreInfo(state)}>
              <div class="meter-head">
                <span>
                  <span style="color: ${a.class_color ?? "var(--wow-text)"}">${a.character_name}</span>
                  <small class="dim">${a.character_level ? `${this.t("level")} ${a.character_level} · ` : ""}${realmTitle(a.realm)}</small>
                </span>
                <span class="value">${this.num(gold)} g</span>
              </div>
              ${bar(gold, max, "#ffd100")}
            </div>
          `;
        })}
      </div>
    `;
    return section(ctx, "account_characters", body);
  }

  static styles = [frameStyles, blockStyles, layoutStyles, extraStyles];
}
