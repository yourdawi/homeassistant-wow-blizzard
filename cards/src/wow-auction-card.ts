// Auction house: the lowest price of each tracked item, with icon and quality
// like the in-game auction house, and optionally the price per realm.

import { html, nothing, type TemplateResult } from "lit";
import { WowBaseCard } from "./base-card";
import { blockStyles } from "./blocks";
import { MODELS, deviceName, deviceStates, devicesOf, numericState } from "./data";
import { deviceField, keepOffered, listField } from "./editor";
import { extraStyles, frameStyles, layoutStyles } from "./styles";
import type { HassEntityState, HomeAssistant, LovelaceCardConfig } from "./types";

export const AUCTION_CARD_TYPE = "wow-auction-card";

interface AuctionCardConfig extends LovelaceCardConfig {
  device: string;
  /** Item entities in display order; all items of the device when not set */
  items?: string[];
  show_sources?: boolean;
}

/** Item name from the friendly name, without the device name in front. */
function itemName(hass: HomeAssistant, state: HassEntityState, deviceId: string): string {
  const full = String(state.attributes.friendly_name ?? state.entity_id);
  const device = deviceName(hass, deviceId);
  return full.startsWith(device) ? full.slice(device.length).trim() || full : full;
}

export class WowAuctionCard extends WowBaseCard<AuctionCardConfig> {
  static getStubConfig(hass: HomeAssistant) {
    return { device: devicesOf(hass, MODELS.auction)[0]?.id ?? "" };
  }

  static editorForm(hass: HomeAssistant, config: AuctionCardConfig) {
    const items = config.device ? deviceStates(hass, config.device) : [];
    const ids = items.map((s) => s.entity_id);
    return {
      schema: [
        deviceField("device", MODELS.auction),
        listField("items", items.map((s) => ({ value: s.entity_id, label: itemName(hass, s, config.device) }))),
        { name: "show_sources", selector: { boolean: {} } },
      ],
      data: {
        device: config.device || undefined,
        items: keepOffered(config.items ?? ids, ids),
        show_sources: !!config.show_sources,
      },
      labels: { device: "device_auction" as const },
    };
  }

  static editorApply(hass: HomeAssistant, config: AuctionCardConfig, value: Record<string, any>): AuctionCardConfig {
    const device: string = value.device ?? "";
    const ids = device ? deviceStates(hass, device).map((s) => s.entity_id) : [];
    const items = keepOffered(value.items, ids);
    const next: AuctionCardConfig = { ...config, device, items };
    // All items, in the default order: leave it open so new items show up
    if (device !== config.device || (items.length === ids.length && items.every((id, i) => id === ids[i]))) delete next.items;
    if (value.show_sources) next.show_sources = true;
    else delete next.show_sources;
    return next;
  }

  getCardSize() {
    return 2 + (this._config?.items?.length ?? 4);
  }

  protected watched(): HassEntityState[] {
    return this.hass && this._config?.device ? deviceStates(this.hass, this._config.device) : [];
  }

  protected render(): TemplateResult | typeof nothing {
    if (!this._config || !this.hass) return nothing;
    if (!this._config.device) return this.message(this.t("no_device"));
    const all = deviceStates(this.hass, this._config.device);
    if (!all.length) return this.message(this.t("not_found"), true);
    const byId = new Map(all.map((s) => [s.entity_id, s]));
    const items = (this._config.items ?? all.map((s) => s.entity_id)).map((id) => byId.get(id)).filter((s): s is HassEntityState => !!s);

    return html`
      <ha-card class="neutral">
        <div class="content">
          <div class="header">
            <div class="avatar emblem">⚖</div>
            <div class="ident">
              <div class="name heading gold">${this.t("auction_house")}</div>
              <div class="line dim">${deviceName(this.hass, this._config.device)}</div>
            </div>
          </div>
          <div class="list">${items.map((state) => this._item(state))}</div>
        </div>
      </ha-card>
    `;
  }

  private _item(state: HassEntityState) {
    const a = state.attributes;
    const price = numericState(state);
    const sources = Object.entries((a.sources ?? {}) as Record<string, number | null>);
    const showSources = this._config!.show_sources && sources.length > 1;
    return html`
      <div class="list-row auction" @click=${() => this.moreInfo(state)}>
        <div class="slot" style="--quality: ${a.quality_color ?? "#333"}">
          ${a.item_icon ? html`<img src=${a.item_icon} alt="" loading="lazy" />` : nothing}
        </div>
        <div class="grow">
          <div class="item-name" style="color: ${a.quality_color ?? "var(--wow-text)"}">${itemName(this.hass!, state, this._config!.device)}</div>
          <div class="dim small">
            ${price === undefined
              ? this.t("no_auctions")
              : html`${this.num(a.quantity)} ${this.t("quantity")} · ${this.num(a.auctions)} ${this.t("auctions")}`}
          </div>
          ${showSources
            ? html`<div class="sources">
                ${sources.map(
                  ([source, p]) => html`<span class="tag">${source === "commodities" ? this.t("commodities") : source}: ${p === null ? "–" : this._coins(p)}</span>`,
                )}
              </div>`
            : nothing}
        </div>
        <div class="price">${price === undefined ? "–" : this._coins(price)}</div>
      </div>
    `;
  }

  /** Gold, silver and copper with coin marks, like the in-game prices. */
  private _coins(gold: number) {
    const copperTotal = Math.round(gold * 10000);
    const g = Math.floor(copperTotal / 10000);
    const s = Math.floor((copperTotal % 10000) / 100);
    const c = copperTotal % 100;
    return html`<span class="coins">
      ${g ? html`<span>${this.num(g)}<i class="coin gold"></i></span>` : nothing}
      ${s ? html`<span>${s}<i class="coin silver"></i></span>` : nothing}
      ${c || (!g && !s) ? html`<span>${c}<i class="coin copper"></i></span>` : nothing}
    </span>`;
  }

  static styles = [frameStyles, blockStyles, layoutStyles, extraStyles];
}
