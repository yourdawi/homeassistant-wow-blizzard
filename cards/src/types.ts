// The parts of the Home Assistant frontend objects the cards use.

export interface HassEntityState {
  entity_id: string;
  state: string;
  attributes: Record<string, any>;
  last_changed: string;
  last_updated: string;
}

export interface HassEntityEntry {
  entity_id: string;
  device_id?: string | null;
  platform?: string;
  translation_key?: string | null;
  hidden?: boolean;
}

export interface HassDeviceEntry {
  id: string;
  name: string | null;
  name_by_user: string | null;
  model: string | null;
  manufacturer: string | null;
  sw_version?: string | null;
}

export interface HomeAssistant {
  states: Record<string, HassEntityState>;
  entities: Record<string, HassEntityEntry>;
  devices: Record<string, HassDeviceEntry>;
  language: string;
  locale: { language: string; number_format?: string };
  themes?: { darkMode?: boolean };
  formatEntityState?: (stateObj: HassEntityState, state?: string) => string;
}

export interface LovelaceCardConfig {
  type: string;
  [key: string]: any;
}

declare global {
  interface Window {
    customCards?: Array<{
      type: string;
      name: string;
      description?: string;
      preview?: boolean;
      documentationURL?: string;
    }>;
  }
  const __VERSION__: string;
}
