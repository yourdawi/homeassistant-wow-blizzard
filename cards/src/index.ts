import { localize, uiLanguage } from "./i18n";
import { CARD_TYPE, WowCharacterCard } from "./wow-character-card";

const DOCS = "https://github.com/yourdawi/homeassistant-wow-blizzard#dashboard-cards";

if (!customElements.get(CARD_TYPE)) {
  customElements.define(CARD_TYPE, WowCharacterCard);
}

const lang = uiLanguage();
window.customCards = window.customCards || [];
if (!window.customCards.some((card) => card.type === CARD_TYPE)) {
  window.customCards.push({
    type: CARD_TYPE,
    name: localize(lang, "card_name"),
    description: localize(lang, "card_description"),
    preview: true,
    documentationURL: DOCS,
  });
}

console.info(
  `%c WOW-CARDS %c ${__VERSION__} `,
  "color: #000; background: #c8a95c; font-weight: 700;",
  "color: #c8a95c; background: #0d0f14;",
);
