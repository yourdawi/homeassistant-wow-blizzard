# World of Warcraft Blizzard API for Home Assistant

A custom integration that brings World of Warcraft character, realm and Hall of Fame data into Home Assistant, using the official Blizzard Battle.net API.

Use it to track levels and item level over time, watch realm status on reset day, follow PvP and Mythic+ progress, or see which guilds have cleared the current Mythic raids.

## Contents

- [Features](#features)
- [Supported game versions](#supported-game-versions)
- [Requirements](#requirements)
- [Installation](#installation)
- [Configuration](#configuration)
- [Entities](#entities)
- [Hall of Fame](#hall-of-fame)
- [Examples](#examples)
- [Update behavior](#update-behavior)
- [Troubleshooting](#troubleshooting)
- [Known limitations](#known-limitations)
- [Contributing](#contributing)
- [License](#license)

## Features

| Area | What you get |
| --- | --- |
| Characters | Level, item level, guild, achievement points, portrait as entity picture, full-body render as image entity, equipment per slot. Any number of characters across realms and game versions. |
| Realms | Realm status, population and whether a login queue is active. |
| PvP | 2v2, 3v3 and RBG ratings, honor level and season wins. |
| Raids | Bosses defeated per difficulty in the current expansion, plus a lifetime total. |
| Mythic+ | Season score, highest key, best runs, timed runs, weekly best key. |
| Hall of Fame | One sensor per raid of the current expansion with the world first guild and the ranks of your own guilds. |

Numeric sensors have the `measurement` state class, so Home Assistant keeps long-term statistics and you can graph them (for example a leveling race).

## Supported game versions

Each character is added with its game version. The integration only creates the sensors that the Blizzard API supports for that version.

| Game version | API namespace | Basic | PvP | Raids | Mythic+ | Hall of Fame |
| --- | --- | --- | --- | --- | --- | --- |
| Retail | `profile-{region}` | All | All | Yes | Yes | Yes |
| Classic Progression (currently Mists of Pandaria) | `profile-classic-{region}` | All | 2v2, 3v3, wins | No | No | No |
| Classic Anniversary (Burning Crusade) | `profile-classicann-{region}` | No item level | 2v2, 3v3, wins | No | No | No |
| Classic Era (Vanilla) | `profile-classic1x-{region}` | Level, guild | No | No | No | No |
| WoW Forever | detected at setup | All | No | No | No | No |

### WoW Forever

WoW Forever launches on November 4, 2026. As of this release Blizzard has not documented an API namespace for it. The integration ships with candidate namespaces and probes them when you add a Forever character:

- If one of them answers, it is stored with the character and used from then on.
- If none answers, setup shows "This game version is not available in the Blizzard API yet". Try again after Blizzard enables the API. If it still fails, please open an issue.

Forever support starts with the basic sensors (level, item level, guild, achievement points). More will follow once the API is known.

## Requirements

- Home Assistant 2024.11 or newer
- A Battle.net API client (free): https://develop.battle.net/access/clients
- HACS (recommended)

## Installation

### HACS

1. Open HACS and select **Integrations**.
2. Open the menu and select **Custom repositories**.
3. Add `https://github.com/yourdawi/homeassistant-wow-blizzard` with the category **Integration**.
4. Install **World of Warcraft Blizzard API**.
5. Restart Home Assistant.

### Manual

1. Copy `custom_components/wow_blizzard` into `config/custom_components/` of your Home Assistant installation.
2. Restart Home Assistant.

```
config/
  custom_components/
    wow_blizzard/
      __init__.py
      api_client.py
      config_flow.py
      const.py
      manifest.json
      image.py
      sensor.py
      strings.json
      translations/
      brand/
```

## Configuration

### 1. Create a Battle.net API client

1. Sign in at https://develop.battle.net/access/clients.
2. Create a new client. The client name must be unique across the whole Blizzard developer portal (for example `HA-WoW-<yourname>`); a name that is already taken makes the creation fail with an HTTP 500 error. The redirect URL is not used by this integration, but the form requires one; `https://my.home-assistant.io/redirect/oauth` works.
3. Copy the **Client ID** and **Client Secret**.

### 2. Add the integration

1. Go to **Settings > Devices & Services > Add Integration** and search for **World of Warcraft Blizzard API**.
2. Enter the client ID and secret, select your **region** (US, EU, KR, TW, CN) and the **API locale**. The locale sets the language of names returned by the API, such as classes, realm status and raid names.
3. Choose which feature groups to enable: realm status, PvP, raids, Mythic+ and Hall of Fame.

### 3. Add characters

1. Select the game version.
2. Pick the realm from the list (you can type to search) and enter the character name. Upper and lower case do not matter.
3. The integration checks that the character exists, then shows the character list. Add more characters or finish.

Submitting the realm form empty takes you back to the menu.

### Changing the configuration later

Open **Settings > Devices & Services > World of Warcraft Blizzard API > Configure**:

- **Add a Character** adds another character, in any game version.
- **Remove Character(s)** removes characters. At least one has to remain.
- **Configure Features** turns feature groups on or off.

The integration reloads on its own after every change.

## Entities

Each character becomes a device named `<Character> (<realm>)`, each realm becomes `<Realm> Server`, and all Hall of Fame sensors share the device `WoW Leaderboards`. Home Assistant builds entity IDs from the device name and the sensor name in your system language at the time the entity is created. With English as the system language, the character "Thrall" on "stormrage" gets IDs like `sensor.thrall_stormrage_level`. You can rename any entity ID in the UI.

### Character sensors

| Sensor | Example entity ID (English) | Notes |
| --- | --- | --- |
| Level | `sensor.thrall_stormrage_level` | |
| Item Level | `sensor.thrall_stormrage_item_level` | Equipped item level |
| Guild | `sensor.thrall_stormrage_guild` | |
| Achievement Points | `sensor.thrall_stormrage_achievement_points` | |
| Equipment Details | `sensor.thrall_stormrage_equipment_details` | Number of equipped items; gear per slot in attributes |
| 2v2 Arena Rating | `sensor.thrall_stormrage_2v2_arena_rating` | PvP |
| 3v3 Arena Rating | `sensor.thrall_stormrage_3v3_arena_rating` | PvP |
| RBG Rating | `sensor.thrall_stormrage_rbg_rating` | PvP, Retail |
| Honor Level | `sensor.thrall_stormrage_honor_level` | PvP, Retail |
| PvP Wins (Season) | `sensor.thrall_stormrage_pvp_wins_season` | Sum over the tracked brackets |
| LFR / Normal / Heroic / Mythic Progress | `sensor.thrall_stormrage_mythic_progress` | Bosses defeated in the current expansion's raids |
| Total Boss Kills | `sensor.thrall_stormrage_total_boss_kills` | Bosses defeated across all raids, lifetime |
| M+ Score | `sensor.thrall_stormrage_m_score` | Current season |
| Best M+ Level | `sensor.thrall_stormrage_best_m_level` | Highest key this season |
| M+ Runs Completed | `sensor.thrall_stormrage_m_runs_completed` | Number of best runs the API reports this season, not all runs |
| M+ Runs Timed | `sensor.thrall_stormrage_m_runs_timed` | Timed runs among those best runs |
| Weekly Best M+ | `sensor.thrall_stormrage_weekly_best_m` | Highest key this week |

Attributes on every character sensor: `character_name`, `realm`, `character_class`, `class_color`, `character_race`, `character_level`, `guild`, `faction`, `active_spec`, `last_login`, `game_version`, `category`.

Raid difficulty sensors also have `expansion`, `total_bosses` and `raids`, which holds the per-raid progress, for example `{"The Dreamrift": "6/8"}`.

The Equipment Details sensor lists the gear in `equipped_items` (keyed by slot, e.g. `head`, `trinket_1`) and `equipped_items_list`. Each item has `slot`, `name`, `item_id`, `item_level`, `quality`, `quality_color` and `stats`. These two attributes are not written to the recorder database.

### Character image

Every character also gets an image entity with the full-body render from the character media API, for example `image.thrall_stormrage_full_body_render`. It falls back to the avatar when no render is available. Show it on a dashboard with a picture entity card:

```yaml
type: picture-entity
entity: image.thrall_stormrage_full_body_render
show_name: false
show_state: false
```

### Realm sensors

| Sensor | Example entity ID (English) | Notes |
| --- | --- | --- |
| Realm Status | `sensor.stormrage_server_realm_status` | Localized, e.g. "Up" / "Down" |
| Population | `sensor.stormrage_server_population` | Localized, e.g. "High" |
| Queue | `sensor.stormrage_server_queue` | `True` while a login queue is active |

The `status_type` (`UP`, `DOWN`) and `population_type` (`LOW`, `MEDIUM`, `HIGH`, `FULL`, ...) attributes are language independent. Use them in automations.

If the same realm name exists in two game versions, the second device gets the game version appended to its name.

### Hall of Fame sensors

One sensor per raid of the current expansion, for example `sensor.wow_leaderboards_the_dreamrift`. See [Hall of Fame](#hall-of-fame).

## Hall of Fame

The Hall of Fame shows the first guilds worldwide to defeat a raid on Mythic. Blizzard does not offer it in the Battle.net API, so the integration reads the public GraphQL endpoint behind the [Mythic Raid Hall of Fame](https://worldofwarcraft.blizzard.com/en-us/worldsoul/us/leaderboards/hall-of-fame/mythic-raid) page on worldofwarcraft.blizzard.com.

- The raids of the newest expansion are discovered on their own and refreshed every 24 hours. New raids show up after the next reload of the integration.
- The sensor state is the name of the world first guild, or `Pending` while nobody has cleared the raid.
- Attributes: `world_first_guild`, `world_first_realm`, `world_first_region`, `world_first_timestamp_formatted`, `last_guild_name`, `last_guild_rank`, `total_entries`, `completed` (the list is full), `info_url` (link to the official page) and `character_guild_ranks` (rank of each configured Retail character's guild, if listed).
- Leaderboards are cached for 2 hours while the race is on and kept once the list is full.
- Hall of Fame data is only fetched when at least one Retail character is configured.

The website only accepts a fixed set of pre-registered (persisted) queries. When Blizzard changes them, the integration reads the current query IDs from the website's script bundle and retries. If the website itself is restructured, the Hall of Fame may break until the integration is updated.

## Examples

### Dashboard: characters

```yaml
type: entities
title: Characters
entities:
  - entity: sensor.thrall_stormrage_level
    name: Thrall - Level
  - entity: sensor.thrall_stormrage_item_level
    name: Thrall - Item Level
  - entity: sensor.jaina_stormrage_level
    name: Jaina - Level
```

### Dashboard: leveling race

```yaml
type: history-graph
title: Leveling race
hours_to_show: 168
entities:
  - entity: sensor.thrall_stormrage_level
  - entity: sensor.jaina_stormrage_level
```

### Dashboard: raid progress

```yaml
type: horizontal-stack
cards:
  - type: entity
    entity: sensor.thrall_stormrage_normal_progress
    name: Normal
  - type: entity
    entity: sensor.thrall_stormrage_heroic_progress
    name: Heroic
  - type: entity
    entity: sensor.thrall_stormrage_mythic_progress
    name: Mythic
```

### Dashboard: Hall of Fame

```yaml
type: entities
title: Mythic Hall of Fame
entities:
  - entity: sensor.wow_leaderboards_the_dreamrift
  - entity: sensor.wow_leaderboards_march_on_queldanas
```

### Automation: level up

```yaml
automation:
  - alias: WoW level up
    triggers:
      - trigger: state
        entity_id:
          - sensor.thrall_stormrage_level
          - sensor.jaina_stormrage_level
    conditions:
      - condition: template
        value_template: >
          {{ trigger.from_state.state | int(0) > 0 and
             trigger.to_state.state | int(0) > trigger.from_state.state | int(0) }}
    actions:
      - action: notify.mobile_app_phone
        data:
          title: Level up
          message: >
            {{ trigger.to_state.attributes.character_name }} reached level
            {{ trigger.to_state.state }}.
```

### Automation: new Mythic boss

```yaml
automation:
  - alias: WoW new Mythic boss
    triggers:
      - trigger: state
        entity_id: sensor.thrall_stormrage_mythic_progress
    conditions:
      - condition: template
        value_template: >
          {{ trigger.to_state.state | int(0) > trigger.from_state.state | int(0) }}
    actions:
      - action: notify.mobile_app_phone
        data:
          message: >
            {{ trigger.to_state.attributes.character_name }} defeated a new Mythic boss
            ({{ trigger.to_state.state }}/{{ trigger.to_state.attributes.total_bosses }}).
```

### Automation: realm back online

```yaml
automation:
  - alias: WoW realm back online
    triggers:
      - trigger: state
        entity_id: sensor.stormrage_server_realm_status
        attribute: status_type
        from: DOWN
        to: UP
    actions:
      - action: notify.mobile_app_phone
        data:
          message: Stormrage is back online.
```

## Update behavior

- All data is refreshed every 5 minutes in one update cycle.
- Data from the Battle.net API reflects what Blizzard has processed, which usually lags the game by a few minutes and may be refreshed only after logout.
- If a character profile cannot be fetched (API error, maintenance), the last known values are kept, so graphs do not drop to 0.
- On HTTP 429 (rate limit) the request is retried up to two times, waiting at most 30 seconds. The Battle.net API allows 36,000 requests per hour, and each character uses roughly 5 to 12 requests per update depending on the enabled features.

## Troubleshooting

**Creating the Battle.net API client fails with HTTP 500**
The client name is most likely taken already. Blizzard requires globally unique client names but does not say so in the error. Choose a more specific name, see the [developer forum thread](https://us.forums.blizzard.com/en/blizzard/t/creating-an-api-client-returns-500/56603/6).

**Invalid authentication during setup**
Check the client ID and secret at https://develop.battle.net/access/clients.

**Character not found**
- The character must exist in the selected region and game version.
- The realm must match the character's realm (pick it from the list).
- New characters, or characters that have not logged in for a long time, may not be in the API until they log in and log out once.

**Values are missing or unknown**
- PvP ratings appear only after the character has played rated games this season.
- Mythic+ values need at least one run in the current season.
- Some sensors are not offered for some game versions (see [Supported game versions](#supported-game-versions)).

**Hall of Fame sensors are missing or show errors**
Hall of Fame sensors are only created when at least one Retail character is configured and the website could be reached when the integration started. Reload the integration to retry. With debug logging enabled, errors show up as `GraphQL ... failed`.

**Debug logging**

```yaml
logger:
  default: info
  logs:
    custom_components.wow_blizzard: debug
```

## Known limitations

- The Battle.net API only reports whether a realm has a login queue, not how long it is.
- "M+ Runs Completed" and "M+ Runs Timed" count the best runs that the API returns, not every key you have run.
- Hall of Fame data comes from the public website rather than the official API and can break when Blizzard changes the site.
- WoW Forever support depends on Blizzard publishing its API namespace (see [WoW Forever](#wow-forever)).
- Weekly activities (Great Vault, weekly quests) are not part of the public game data API for other accounts, so they cannot be tracked.

## Contributing

Bug reports and feature requests are welcome in the [issue tracker](https://github.com/yourdawi/homeassistant-wow-blizzard/issues). For bugs, please include:

- Home Assistant version and integration version
- Game version, region and realm of the affected character
- Relevant log lines with debug logging enabled

Pull requests are welcome as well.

## License

MIT, see [LICENSE](LICENSE).

World of Warcraft and Blizzard Entertainment are trademarks of Blizzard Entertainment, Inc. This project is not affiliated with or endorsed by Blizzard Entertainment.
