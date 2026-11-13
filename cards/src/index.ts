import "./editor";
import { localize, uiLanguage, type StringKey } from "./i18n";
import { ACCOUNT_CARD_TYPE, WowAccountCard } from "./wow-account-card";
import { AUCTION_CARD_TYPE, WowAuctionCard } from "./wow-auction-card";
import { CARD_TYPE, WowCharacterCard } from "./wow-character-card";
import { GUILD_CARD_TYPE, WowGuildCard } from "./wow-guild-card";
import { REALM_CARD_TYPE, WowRealmCard } from "./wow-realm-card";

const DOCS = "https://github.com/yourdawi/homeassistant-wow-blizzard#dashboard-cards";

const CARDS: Array<[string, CustomElementConstructor, StringKey, StringKey]> = [
  [CARD_TYPE, WowCharacterCard, "card_name", "card_description"],
  [GUILD_CARD_TYPE, WowGuildCard, "card_guild_name", "card_guild_description"],
  [ACCOUNT_CARD_TYPE, WowAccountCard, "card_account_name", "card_account_description"],
  [REALM_CARD_TYPE, WowRealmCard, "card_realm_name", "card_realm_description"],
  [AUCTION_CARD_TYPE, WowAuctionCard, "card_auction_name", "card_auction_description"],
];

const lang = uiLanguage();
window.customCards = window.customCards || [];
for (const [type, element, name, description] of CARDS) {
  if (!customElements.get(type)) customElements.define(type, element);
  if (!window.customCards.some((card) => card.type === type)) {
    window.customCards.push({
      type,
      name: localize(lang, name),
      description: localize(lang, description),
      preview: true,
      documentationURL: DOCS,
    });
  }
}

console.info(
  `%c WOW-CARDS %c ${__VERSION__} `,
  "color: #000; background: #c8a95c; font-weight: 700;",
  "color: #c8a95c; background: #0d0f14;",
);
