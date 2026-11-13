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
