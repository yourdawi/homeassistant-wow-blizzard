import { css } from "lit";

// The look shared by all cards: a dark panel with a thin gold frame, in the style
// of the in-game UI. Every color is a custom property, so themes and card-mod can
// override it (e.g. --wow-gold: #b0b0b0).
export const frameStyles = css`
  :host {
    --wow-gold: #c8a95c;
    --wow-gold-dim: rgba(200, 169, 92, 0.35);
    --wow-panel: #0d0f14;
    --wow-panel-2: #181b24;
    --wow-text: #f2ead7;
    --wow-text-dim: #a59e8c;
    --wow-guild: #40ff40;
    --wow-alliance: #2f6fd6;
    --wow-horde: #c4232b;
    --wow-neutral: #8a7a55;
    --wow-heading-font: "Friz Quadrata", "Friz Quadrata TT", Georgia, "Times New Roman", serif;
    display: block;
  }

  ha-card {
    position: relative;
    overflow: hidden;
    height: 100%;
    box-sizing: border-box;
    color: var(--wow-text);
    background:
      radial-gradient(120% 90% at 0% 0%, color-mix(in srgb, var(--faction-color) 22%, transparent), transparent 60%),
      linear-gradient(160deg, var(--wow-panel-2), var(--wow-panel));
    border: 1px solid var(--wow-gold-dim);
    box-shadow:
      inset 0 0 0 1px rgba(0, 0, 0, 0.6),
      inset 0 0 24px rgba(0, 0, 0, 0.55),
      var(--ha-card-box-shadow, none);
  }

  ha-card.alliance { --faction-color: var(--wow-alliance); }
  ha-card.horde { --faction-color: var(--wow-horde); }
  ha-card.neutral { --faction-color: var(--wow-neutral); }

  /* Gold corner marks */
  ha-card::before,
  ha-card::after {
    content: "";
    position: absolute;
    width: 14px;
    height: 14px;
    pointer-events: none;
    border-color: var(--wow-gold);
    border-style: solid;
    opacity: 0.8;
    z-index: 2;
  }
  ha-card::before { top: 5px; left: 5px; border-width: 2px 0 0 2px; }
  ha-card::after { bottom: 5px; right: 5px; border-width: 0 2px 2px 0; }

  .heading {
    font-family: var(--wow-heading-font);
    letter-spacing: 0.02em;
  }

  .message {
    padding: 16px;
    color: var(--wow-text-dim);
    font-style: italic;
  }
  .message.error { color: #ff6b6b; font-style: normal; }
`;

// Card layout and header: the round portrait (or crest), a name in the
// heading font, lines below it and a framed value on the right.
export const layoutStyles = css`
      .render-bg {
        position: absolute;
        inset: 0 0 0 35%;
        /* Renders have wide empty margins; zoom in on the character */
        background-size: auto 230%;
        background-repeat: no-repeat;
        background-position: 55% 18%;
        max-height: 420px;
        opacity: 0.55;
        mask-image: linear-gradient(to right, transparent, #000 45%), linear-gradient(to top, transparent, #000 40%);
        mask-composite: intersect;
        -webkit-mask-composite: source-in;
        pointer-events: none;
      }
      .content {
        container-type: inline-size;
        position: relative;
        z-index: 1;
        padding: 16px;
        display: flex;
        flex-direction: column;
        gap: 14px;
      }

      /* Header */
      .header {
        display: flex;
        align-items: center;
        gap: 14px;
        cursor: pointer;
      }
      .avatar {
        width: 64px;
        height: 64px;
        flex: none;
        border-radius: 50%;
        object-fit: cover;
        border: 2px solid var(--class-color);
        box-shadow: 0 0 0 2px #000, 0 0 12px color-mix(in srgb, var(--class-color) 45%, transparent);
        background: #000;
      }
      .ident {
        min-width: 0;
        flex: 1;
      }
      .name {
        font-size: 1.5rem;
        line-height: 1.2;
        color: var(--class-color);
        text-shadow: 0 1px 2px #000;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
      }
      .title {
        font-size: 0.85rem;
        color: var(--wow-gold);
        font-style: italic;
      }
      .line {
        font-size: 0.9rem;
        line-height: 1.4;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
      }
      .line.dim { color: var(--wow-text-dim); }
      .class { color: var(--class-color); }
      .spec { color: var(--wow-text-dim); }
      .guild { color: var(--wow-guild); margin-right: 4px; }
      .ilvl {
        display: flex;
        flex-direction: column;
        align-items: center;
        flex: none;
        padding: 6px 10px;
        border: 1px solid var(--wow-gold-dim);
        border-radius: 6px;
        background: rgba(0, 0, 0, 0.45);
      }
      .ilvl .value {
        font-size: 1.6rem;
        line-height: 1;
        color: #a335ee;
        text-shadow: 0 0 8px rgba(163, 53, 238, 0.5);
      }
      .ilvl .label {
        font-size: 0.7rem;
        text-transform: uppercase;
        letter-spacing: 0.06em;
        color: var(--wow-text-dim);
      }

      @container (max-width: 360px) {
        .avatar { width: 48px; height: 48px; }
        .name { font-size: 1.25rem; }
        .ilvl .value { font-size: 1.3rem; }
        .header { gap: 10px; }
      }
`;

// Headers of the account, realm, guild and auction cards, and auction rows
export const extraStyles = css`
  .avatar.emblem {
    display: flex;
    align-items: center;
    justify-content: center;
    border-color: var(--wow-gold);
    color: var(--wow-gold);
    font-size: 1.8rem;
    background: radial-gradient(circle, #2a2418, #000);
  }
  .avatar.crest {
    border-radius: 8px;
    border-color: var(--wow-gold-dim);
  }
  .avatar.status::after {
    content: "";
    width: 22px;
    height: 22px;
    border-radius: 50%;
    background: var(--status);
    box-shadow: 0 0 14px var(--status);
  }
  .avatar.status.up { --status: #1eff00; }
  .avatar.status.down { --status: #ff3b3b; }
  .name.gold { color: var(--wow-gold); }
  .name.guild-name { color: var(--wow-guild); }
  .line.ok { color: #1eff00; }
  .line.bad { color: #ff6b6b; }
  .text { color: var(--wow-text); }
  .small { font-size: 0.8rem; }

  .list-row.auction {
    gap: 12px;
    padding: 6px 8px;
    cursor: pointer;
  }
  .list-row.auction .grow {
    white-space: normal;
  }
  .item-name {
    font-weight: 600;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .sources {
    display: flex;
    flex-wrap: wrap;
    gap: 4px;
    margin-top: 4px;
  }
  .sources .tag.cheapest {
    color: var(--wow-gold);
    border-color: var(--wow-gold);
  }
  .price {
    flex: none;
    font-weight: 600;
  }
  .coins {
    display: inline-flex;
    gap: 6px;
    white-space: nowrap;
  }
  .coin {
    display: inline-block;
    width: 0.7em;
    height: 0.7em;
    margin-left: 2px;
    border-radius: 50%;
    vertical-align: baseline;
    box-shadow: inset -1px -1px 1px rgba(0, 0, 0, 0.45);
  }
  .coin.gold { background: radial-gradient(circle at 35% 35%, #fff2a8, #e5b10b 60%, #8a6400); }
  .coin.silver { background: radial-gradient(circle at 35% 35%, #ffffff, #b8b8b8 60%, #6b6b6b); }
  .coin.copper { background: radial-gradient(circle at 35% 35%, #ffc9a0, #c0662b 60%, #6e3410); }

  /* Hall of Fame */
  .world-first {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 8px 10px;
    border: 1px solid var(--wow-gold-dim);
    border-radius: 6px;
    background: linear-gradient(to right, rgba(255, 209, 0, 0.12), transparent);
    cursor: pointer;
  }
  .first-guild {
    font-size: 1.15rem;
    color: #ffd100;
  }
  .key.gold-key {
    color: #000;
    background: linear-gradient(to bottom, #ffe066, #c8a95c);
  }
`;
