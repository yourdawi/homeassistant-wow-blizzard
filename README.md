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
| Characters | Level, item level, guild, achievement points, profile status, portrait as entity picture, full-body render as image entity, equipment per slot. Any number of characters across realms and game versions. |
| Character details | Professions, health and secondary stats, title, reputations, talents, dungeons completed, deaths, quests completed, hunter pets. |
| Collections | Number of mounts, pets, toys, heirlooms and housing decor. |
| Guild | Member count, guild achievement points and an event entity for new guild achievements and boss kills. |
| Realms | Realm status, population and whether a login queue is active. |
| Region | WoW Token price (Retail and Classic Progression), the next weekly reset, the PvP season with its title cutoffs and, opt-in, the weekly Mythic+ affixes. |
| PvP | 2v2, 3v3, RBG, Solo Shuffle and Blitz ratings of the current season, honor level, season wins, honorable kills and the Classic Era PvP rank. |
| Raids | Bosses defeated per difficulty in the current expansion, plus a lifetime total. |
| Mythic+ | Season score, highest key, best runs, timed runs, weekly best key. |
| Hall of Fame | One sensor per raid of the current expansion with the world first guild and the ranks of your own guilds. |
| Mythic+ leaderboards (opt-in) | Best key of the week per realm, with the best runs of your characters. |
| Auction house | Lowest price for item IDs you choose (Retail commodities and realm auctions, Classic Progression realm auctions). |
| Battle.net account (optional) | Import characters by logging in with Battle.net. While the login is valid (24 hours): gold per character, total gold, account mounts and pets. |

Numeric sensors have the `measurement` state class, so Home Assistant keeps long-term statistics and you can graph them (for example a leveling race).

## Supported game versions

Each character is added with its game version. The integration only creates the sensors that the Blizzard API supports for that version.

| Game version | API namespace | Basic | PvP | Raids | Mythic+ | Details | Collections | Guild | Hall of Fame |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Retail | `profile-{region}` | All | All except PvP rank | Yes | Yes | All | Yes | Yes | Yes |
| Classic Progression (currently Mists of Pandaria) | `profile-classic-{region}` | All | 2v2, 3v3, wins, honorable kills | No | No | No professions, versatility or dungeons | No | Yes | No |
| Classic Anniversary (Burning Crusade) | `profile-classicann-{region}` | No achievement points | 2v2, 3v3, wins, honorable kills | No | No | Health, crit, haste, title, reputations, talents, hunter pets | No | Yes | No |
| Classic Era (Vanilla) | `profile-classic1x-{region}` | No achievement points | Honorable kills, PvP rank | No | No | Health, crit, title, reputations, talents, hunter pets | No | Yes | No |
| WoW Forever | detected at setup | All | No | No | No | No | No | No | No |

The support per version was checked against the live API (EU, October 2026). The WoW Token price is available for Retail and Classic Progression; Blizzard does not offer it for Classic Era and Anniversary.

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
      event.py
      image.py
      parsers.py
      sensor.py
      strings.json
      translations/
      brand/
```

## Configuration

### 1. Create a Battle.net API client

1. Sign in at https://develop.battle.net/access/clients.
2. Create a new client. The client name must be unique across the whole Blizzard developer portal (for example `HA-WoW-<yourname>`); a name that is already taken makes the creation fail with an HTTP 500 error. Enter `https://my.home-assistant.io/redirect/oauth` as redirect URL. It is only used for the optional Battle.net login, but the form requires one anyway.
3. Copy the **Client ID** and **Client Secret**.

### 2. Add the integration

1. Go to **Settings > Devices & Services > Add Integration** and search for **World of Warcraft Blizzard API**.
2. Enter the client ID and secret, select your **region** (US, EU, KR, TW, CN) and the **API locale**. The locale sets the language of names returned by the API, such as classes, realm status and raid names.
3. Choose which feature groups to enable: realm status, PvP, raids, Mythic+, Hall of Fame, character details, collections, guild, region data (WoW Token, weekly reset) and the Mythic+ realm leaderboards (off by default, they download about 8 MB per realm and hour).
4. Optionally enter item IDs to track auction prices, for example `210796, 224025`. You find the ID in the item's Wowhead URL. Leave the field empty to skip the auction house.

### 3. Add characters

Choose **Enter realm and name** or **Log in with Battle.net**.

**Log in with Battle.net** (optional) opens the Battle.net login. Afterwards all characters of your account (Retail and all Classic versions) are listed and you tick the ones to add. With **Also load account data** the login is kept and the integration adds gold and account collections. Blizzard logins last 24 hours and cannot be renewed automatically. An expired login never breaks the integration: everything that does not need the login keeps updating, gold and account values keep their last state (also across restarts), and a notice under **Settings > Repairs** reminds you that you can log in again with **Reconfigure**. Logging in again is optional; you can ignore the notice or remove the login. If the login fails or is cancelled during setup, nothing is lost and you can add characters by hand. The login needs My Home Assistant (part of `default_config`) and the redirect URL from step 1.

**Enter realm and name:**

1. Select the game version.
2. Pick the realm from the list (you can type to search) and enter the character name. Upper and lower case do not matter.
3. The integration checks that the character exists, then shows the character list. Add more characters or finish.

Submitting the realm form empty takes you back to the menu.

### Changing the configuration later

Open **Settings > Devices & Services > World of Warcraft Blizzard API > Configure**:

- **Add a Character** adds another character, in any game version.
- **Remove Character(s)** removes characters. At least one has to remain.
- **Configure Features** turns feature groups on or off and sets the auction item IDs.
- **Remove Battle.net login** (only shown with a kept login) forgets the login and removes the gold and account sensors. Characters and everything else stay.
- **Reconfigure** (in the integration's menu) logs in with Battle.net to import characters or renew the account login. Unticking **Also load account data** there removes the login as well.

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

The rated PvP sensors only count the current season. Blizzard returns the last season a character played; ratings from an older season show as 0, with the old rating in `last_season_rating`. Every bracket sensor has `season_played`, `season_won`, `season_lost`, `weekly_played` and `weekly_won`, and 3v3 / RBG show the `gladiator_cutoff` / `hero_cutoff`.

| LFR / Normal / Heroic / Mythic Progress | `sensor.thrall_stormrage_mythic_progress` | Bosses defeated in the current expansion's raids |
| Total Boss Kills | `sensor.thrall_stormrage_total_boss_kills` | Bosses defeated across all raids, lifetime |
| M+ Score | `sensor.thrall_stormrage_m_score` | Current season |
| Best M+ Level | `sensor.thrall_stormrage_best_m_level` | Highest key this season |
| M+ Runs Completed | `sensor.thrall_stormrage_m_runs_completed` | Number of best runs the API reports this season, not all runs |
| M+ Runs Timed | `sensor.thrall_stormrage_m_runs_timed` | Timed runs among those best runs |
| Weekly Best M+ | `sensor.thrall_stormrage_weekly_best_m` | Highest key this week |
| Profile Status | `sensor.thrall_stormrage_profile_status` | `valid`, `invalid` or `not_found`, e.g. after a rename, transfer or deletion |
| Honorable Kills | `sensor.thrall_stormrage_honorable_kills` | PvP, lifetime |
| PvP Rank | `sensor.thrall_stormrage_pvp_rank` | PvP, Classic Era honor rank (0 = none) |
| Professions | `sensor.thrall_stormrage_professions` | Primary professions; skill of the newest tier per profession in `professions` |
| Health | `sensor.thrall_stormrage_health` | Details; primary stats, armor, power in attributes |
| Critical Strike / Haste / Mastery / Versatility | `sensor.thrall_stormrage_haste` | Details, in percent |
| Title | `sensor.thrall_stormrage_title` | Details, active title; Retail adds `title_count` |
| Reputations | `sensor.thrall_stormrage_reputations` | Details, number of known factions; standing per faction in `factions` |
| Talents | `sensor.thrall_stormrage_talents` | Details; Retail: hero talent tree with `loadout_code`, Classic Progression: specialization with `talent_list` and `glyphs`, Era/Anniversary: points per tree |
| Dungeons Completed | `sensor.thrall_stormrage_dungeons_completed` | Details, dungeons of the newest expansion with at least one completed difficulty |
| Deaths | `sensor.thrall_stormrage_deaths` | Details, lifetime |
| Quests Completed | `sensor.thrall_stormrage_quests_completed` | Details, lifetime |
| Hunter Pet | `sensor.thrall_stormrage_hunter_pet` | Details, hunters only; summoned pet, all pets in `pets` |
| Mounts / Pets / Toys / Heirlooms / Housing Decor | `sensor.thrall_stormrage_mounts` | Collections, Retail |
| Solo Shuffle Rating / Blitz Rating | `sensor.thrall_stormrage_solo_shuffle_rating` | PvP, Retail, for the active specialization; `legend_cutoff` attribute |
| Gold | `sensor.thrall_stormrage_gold` | Battle.net login only; gold gained/lost, deaths, location and hearthstone in attributes |
| Guild Members | `sensor.thrall_stormrage_guild_members` | Guild, only for characters in a guild; achievement points, realm, faction, creation date in attributes |

Attributes on every character sensor: `character_name`, `realm`, `character_class`, `class_color`, `character_race`, `character_level`, `guild`, `faction`, `active_spec`, `last_login`, `game_version`, `category`.

Raid difficulty sensors also have `expansion`, `total_bosses` and `raids`, which holds the per-raid progress, for example `{"The Dreamrift": "6/8"}`.

The Equipment Details sensor lists the gear in `equipped_items` (keyed by slot, e.g. `head`, `trinket_1`) and `equipped_items_list`. Each item has `slot`, `name`, `item_id`, `icon` (image URL), `item_level`, `quality`, `quality_color` and `stats`. These two attributes are not written to the recorder database.

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

### Region sensors

Region-wide data lives on the device `WoW <REGION>`, for example `WoW EU`.

| Sensor | Example entity ID (English) | Notes |
| --- | --- | --- |
| WoW Token Price | `sensor.wow_eu_wow_token_price` | Retail, in gold; `last_updated` attribute |
| WoW Token Price (Classic) | `sensor.wow_eu_wow_token_price_classic` | Only with a Classic Progression character |
| Weekly Reset | `sensor.wow_eu_weekly_reset` | Timestamp of the next weekly reset (Retail) |
| PvP Season | `sensor.wow_eu_pvp_season` | PvP, Retail; season ID and start in attributes |
| Gladiator Cutoff | `sensor.wow_eu_gladiator_cutoff` | 3v3 rating needed for Gladiator this season |
| Hero Cutoff | `sensor.wow_eu_hero_cutoff` | RBG rating for Hero of the Alliance/Horde, per faction in attributes |
| M+ Affixes | `sensor.wow_eu_m_affixes` | Mythic+ leaderboards only; affixes of the week with their starting key level |

### Mythic+ realm leaderboards (opt-in)

With **Mythic+ leaderboards** enabled, every Retail realm device gets `Best M+ Key This Week` (e.g. `sensor.stormrage_server_best_m_key_this_week`). The attribute `dungeons` holds the best key, its duration and the number of listed runs per dungeon, `own_characters` the ranking of your configured characters. Each realm needs one download of about 1 MB per dungeon every hour.

### Auction house

Every tracked item gets a sensor on the device `WoW <REGION> Auction House`, named after the item, with the lowest price per item in gold (silver and copper as decimals). Attributes: `quantity` (items listed), `auctions`, and `sources` (lowest price per source). Retail looks in the region-wide commodity market first and in the auctions of your characters' realms for everything else; Classic Progression uses the realms of your Classic Progression characters. Classic Era and Anniversary auctions are not available in the API. The data is refreshed hourly; the Retail commodity market alone is about 30 MB, so only add the auction house if you need it.

### Guild activity

Each guild of your characters gets an event entity on the device of the first character in it, e.g. `event.thrall_stormrage_guild_activity`. It fires `achievement` (attributes `character`, `achievement`, `achievement_id`) and `encounter` (`encounter`, `encounter_id`, `difficulty`, `difficulty_name`) for every new entry in the guild's activity feed. Activity is checked hourly; entries from before Home Assistant started are not replayed.

```yaml
automation:
  - alias: Guild boss kill
    triggers:
      - trigger: state
        entity_id: event.thrall_stormrage_guild_activity
    conditions:
      - condition: state
        entity_id: event.thrall_stormrage_guild_activity
        attribute: event_type
        state: encounter
    actions:
      - action: notify.mobile_app_phone
        data:
          message: >
            Guild kill: {{ state_attr('event.thrall_stormrage_guild_activity', 'encounter') }}
            ({{ state_attr('event.thrall_stormrage_guild_activity', 'difficulty_name') }})
```

### Battle.net account (optional)

With a kept Battle.net login, the device `Battle.net Account` has `Total Gold` (Retail), `Characters`, `Account Mounts`, `Account Pets` and `Battle.net Login Expires`. The attribute `login_valid` turns `false` when the 24 hour login has expired or Blizzard rejects it (for example after a password change); the values then keep their last state. Temporary API errors also keep the last values instead of dropping to 0.

### Hall of Fame sensors

One sensor per raid of the current expansion, for example `sensor.wow_leaderboards_the_dreamrift`. See [Hall of Fame](#hall-of-fame).

## Hall of Fame

The Hall of Fame shows the first guilds worldwide to defeat a raid on Mythic. The Battle.net API has a Hall of Fame endpoint (`/data/wow/leaderboard/hall-of-fame/{raid}/{faction}`), but it only covers raids up to Vault of the Incarnates (Dragonflight) and returns 404 for every newer raid. So the integration reads the public GraphQL endpoint behind the [Mythic Raid Hall of Fame](https://worldofwarcraft.blizzard.com/en-us/worldsoul/us/leaderboards/hall-of-fame/mythic-raid) page on worldofwarcraft.blizzard.com.

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
- Character details and collections are only fetched again when the character's last login changes, and at least every 6 hours. Guild data and guild activity are cached for 1 hour, the weekly period until the reset, the PvP season for 6 hours.
- Auction prices and Mythic+ leaderboards are refreshed hourly, account data (gold) every 15 minutes while the Battle.net login is valid. Large responses are decoded outside the event loop.
- If a character profile cannot be fetched (API error, maintenance), the last known values are kept, so graphs do not drop to 0. The profile status sensor then shows whether the character still exists.
- On HTTP 429 (rate limit) the request is retried up to two times, waiting at most 30 seconds. The Battle.net API allows 36,000 requests per hour, and each character uses roughly 4 to 10 requests per update depending on the enabled features, plus up to 13 after a new login.

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
- The API does not say which Mythic+ affixes are active this week.
- Account data needs a Battle.net login of the player, which Blizzard limits to 24 hours without a way to renew it automatically.
- Classic Era and Anniversary auction houses are listed by the API but return no data.
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
