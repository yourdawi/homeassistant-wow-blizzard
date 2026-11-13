# World of Warcraft for Home Assistant

<!-- ha-marketplace:exclude-start -->
[![Validate](https://github.com/yourdawi/homeassistant-wow-blizzard/actions/workflows/validate.yaml/badge.svg)](https://github.com/yourdawi/homeassistant-wow-blizzard/actions/workflows/validate.yaml)
[![Validate with hassfest](https://github.com/yourdawi/homeassistant-wow-blizzard/actions/workflows/hassfest.yaml/badge.svg)](https://github.com/yourdawi/homeassistant-wow-blizzard/actions/workflows/hassfest.yaml)
![GitHub Downloads (all assets, all releases)](https://img.shields.io/github/downloads/yourdawi/homeassistant-wow-blizzard/total)

[![Open your Home Assistant instance and open a repository in the Marketplace.](https://my.home-assistant.io/badges/marketplace_repository.svg)](https://my.home-assistant.io/redirect/marketplace_repository/?owner=yourdawi&repository=homeassistant-wow-blizzard&category=integration)
<!-- ha-marketplace:exclude-end -->

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
- [Dashboard cards](#dashboard-cards)
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
| Character details | Professions, health and secondary stats, title, reputations, talents, dungeons completed, deaths, quests completed, active quests, achievements (with an event for every new one), hunter pets. |
| Collections | Number of mounts, pets, toys, heirlooms, transmog appearances and housing decor. |
| Guild | Member count, members at max level by class, your guild rank, completed guild achievements, the guild crest as image and an event entity for new guild achievements, boss kills and members joining or leaving. |
| Realms | Realm status, population and whether a login queue is active. |
| Region | WoW Token price (Retail and Classic Progression), the next weekly reset, the Mythic+ season, the PvP season with its title cutoffs and, opt-in, the weekly Mythic+ affixes. |
| PvP | 2v2, 3v3, RBG, Solo Shuffle and Blitz ratings of the current season, honor level, season wins, honorable kills, the Classic Era PvP rank and the PvP seasons of Classic Progression and Anniversary with their title cutoffs. |
| Raids | Bosses defeated per difficulty in the current expansion, plus a lifetime total. |
| Mythic+ | Season score, highest key, best runs, timed runs, weekly best key. |
| Hall of Fame | One sensor per raid of the current expansion with the world first guild and the ranks of your own guilds. |
| Mythic+ leaderboards (opt-in) | Best key of the week per realm, with the best runs of your characters. |
| PvP leaderboards (opt-in) | Rank of your characters on the regional 2v2, 3v3, RBG, Solo Shuffle and Blitz leaderboards. |
| Auction house | Lowest price for item IDs you choose (Retail commodities and realm auctions, Classic Progression realm auctions). |
| Dashboard cards | A character card in the style of the in-game UI, with render, stats, progress and equipment. Included, no extra download. |
| Battle.net account (optional) | Its own entry: import characters by logging in with Battle.net. While the login is valid (24 hours): gold per Retail character, total gold, account mounts, pets, toys, heirlooms and transmog appearances. |

Numeric sensors have the `measurement` state class, so Home Assistant keeps long-term statistics and you can graph them (for example a leveling race).

## Supported game versions

Each character is added with its game version. The integration only creates the sensors that the Blizzard API supports for that version.

| Game version | API namespace | Basic | PvP | Raids | Mythic+ | Details | Collections | Guild | Hall of Fame |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Retail | `profile-{region}` | All | All except PvP rank | Yes | Yes | All | Yes | Yes | Yes |
| Classic Progression (currently Mists of Pandaria) | `profile-classic-{region}` | All | 2v2, 3v3, wins, honorable kills | No | No | No professions, versatility, dungeons or active quests | No | Yes, no crest | No |
| Classic Anniversary (Burning Crusade) | `profile-classicann-{region}` | No achievement points | 2v2, 3v3, wins, honorable kills | No | No | Health, crit, haste, title, reputations, talents, hunter pets | No | Yes | No |
| Classic Era (Vanilla) | `profile-classic1x-{region}` | No achievement points | Honorable kills, PvP rank | No | No | Health, crit, title, reputations, talents, hunter pets | No | Yes | No |
| WoW Forever | `profile-forever-{region}` | All | Honorable kills, PvP rank | Normal progress, total kills | No | No versatility, haste or mastery | Mounts, pets, toys, heirlooms, transmogs | Yes, no crest | No |

The support per version was checked against the live API (EU, October 2026; WoW Forever November 2026). The WoW Token price is available for Retail and Classic Progression; Blizzard does not offer it for Classic Era and Anniversary.

### WoW Forever

WoW Forever (since November 4, 2026) uses the API namespace `forever` (`profile-forever-eu`, `dynamic-forever-eu`, ...). Blizzard's documentation does not list it yet; the integration checks it when you add a Forever character.

WoW Forever has **no realms**. Characters have a first and last name and play in a game mode (Blizzard calls it ruleset: Normal, PvP, Role-play, Role-play PvP). So adding a Forever character only asks for the name, for example `Arthas Menethil`; the game mode comes from the character. It takes the place of the realm:

- The character device is named after it, e.g. `Arthas Menethil (normal)`.
- The server device, e.g. `Normal (WoW Forever) Server`, only has **Realm Status** (the status of the game mode). Population and queue do not exist for Forever.

Not available for Forever in the API: arena ratings, Mythic+, WoW Token, weekly reset and housing decor. Its auction house is split into 15 houses per game mode with about 10 MB each, which is too much to download hourly, so auction prices are not offered for Forever.

## Requirements

- Home Assistant 2025.3 or newer (for the per-character entries)
- A Battle.net API client (free): https://develop.battle.net/access/clients

<!-- ha-marketplace:exclude-start -->
## Installation

### Marketplace (Home Assistant 2026.11 and newer)

Since Home Assistant 2026.11 the Marketplace (formerly HACS) is part of Home Assistant.

[![Open your Home Assistant instance and open a repository in the Marketplace.](https://my.home-assistant.io/badges/marketplace_repository.svg)](https://my.home-assistant.io/redirect/marketplace_repository/?owner=yourdawi&repository=homeassistant-wow-blizzard&category=integration)

1. Click the button above, or go to **Settings > Marketplace** and search for **World of Warcraft**. If it is not listed yet, add `https://github.com/yourdawi/homeassistant-wow-blizzard` as a repository by link with the type **Integration**.
2. Select **Download**.
3. Continue with [Configuration](#configuration). A restart is only needed for updates.

### HACS (Home Assistant before 2026.11)

1. Open HACS and select **Integrations**.
2. Open the menu and select **Custom repositories**.
3. Add `https://github.com/yourdawi/homeassistant-wow-blizzard` with the category **Integration**.
4. Install **World of Warcraft**.
5. Restart Home Assistant.

### Manual

1. Download `wow_blizzard.zip` from the [latest release](https://github.com/yourdawi/homeassistant-wow-blizzard/releases/latest).
2. Unpack it into `config/custom_components/wow_blizzard/` of your Home Assistant installation.
3. Restart Home Assistant.

```
config/
  custom_components/
    wow_blizzard/
      __init__.py
      api_client.py
      config_flow.py
      const.py
      crest.py
      manifest.json
      event.py
      image.py
      parsers.py
      sensor.py
      strings.json
      translations/
      brand/
```
<!-- ha-marketplace:exclude-end -->

## Configuration

### 1. Create a Battle.net API client

1. Sign in at https://develop.battle.net/access/clients.
2. Create a new client. The client name must be unique across the whole Blizzard developer portal (for example `HA-WoW-<yourname>`); a name that is already taken makes the creation fail with an HTTP 500 error. Enter `https://my.home-assistant.io/redirect/oauth` as redirect URL. It is only used for the optional Battle.net login, but the form requires one anyway.
3. Copy the **Client ID** and **Client Secret**.

### 2. Add a game version

The integration has **one entry per game version** (Retail, Classic Progression, Classic Era, Classic Anniversary, WoW Forever), and every character is listed under its entry. Add one entry for each game version you play.

[![Open your Home Assistant instance and start setting up a new integration.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=wow_blizzard)

1. Click the button above, or go to **Settings > Devices & Services > Add Integration** and search for **World of Warcraft**.
2. Enter the client ID and secret, select your **region** (US, EU, KR, TW, CN) and the **API locale**. The locale sets the language of names returned by the API, such as classes, realm status and raid names. For the second and later game versions the credentials of the first entry are filled in.
3. Select the **game version**. Game versions that are already set up in the region are not offered again.
4. Choose which feature groups to enable: realm status, PvP, raids, Mythic+, Hall of Fame, character details, collections, guild, region data (WoW Token, weekly reset), the Mythic+ realm leaderboards (off by default, they download about 8 MB per realm and hour) and the PvP leaderboard ranks (off by default, about 2 MB per bracket and hour).
5. Optionally enter item IDs to track auction prices, for example `210796, 224025`. You find the ID in the item's Wowhead URL. Leave the field empty to skip the auction house.

### 3. Add characters

Finish the setup with **Enter realm and name**, **Log in with Battle.net** or **Finish without characters**. Afterwards every entry has an **Add character** button next to it.

**Add character / Enter realm and name:** pick the realm from the list (you can type to search) and enter the character name; upper and lower case do not matter. For WoW Forever enter the first and last name instead. The integration checks that the character exists.

**Log in with Battle.net** (optional) opens the Battle.net login. Afterwards all characters of your account (Retail, all Classic versions and WoW Forever) are listed and you tick the ones to add. Characters of other game versions go to the entry of their game version, which is created if it does not exist yet. Characters below level 10 are not listed, the Battle.net API has no data for them.

### 4. Battle.net account (optional)

The Battle.net login has its own entry, **Battle.net Account (EU)** (one per region). Add it with **Add entry** and choose **Battle.net Account** instead of a game version, or keep the login when you import characters with **Log in with Battle.net**.

After the login you pick characters of all game versions; they go to the entry of their game version. While the login is valid the account entry loads gold per character (shown on the character), total gold and the account collections. Only Retail has gold: the Classic Era account lists characters but has no gold for them, and Classic Progression and Anniversary have no account data in the API.

Blizzard logins last 24 hours and cannot be renewed automatically. An expired login never breaks the integration: everything that does not need the login keeps updating, gold and account values keep their last state (also across restarts), and a notice under **Settings > Repairs** reminds you that you can log in again with **Reconfigure** on the account entry. Logging in again is optional; you can ignore the notice or remove the login. If the login fails or is cancelled, nothing is lost. The login needs My Home Assistant (part of `default_config`) and the redirect URL from step 1.

### Changing the configuration later

Open **Settings > Devices & Services > World of Warcraft**. Each game version is an entry with its characters listed below it, plus a **Realms** subentry (created by the integration) with the realm servers, the region device (WoW Token, seasons), the auction house and the Hall of Fame. The Battle.net login is the separate **Battle.net Account** entry.

- **Add character** (next to a game version entry) adds a character of that game version.
- To remove a character, open the menu of the character below its entry and delete it. Its devices and entities are removed.
- **Configure** on a game version entry turns feature groups on or off and sets the auction item IDs, for that game version only. It only shows the features with an effect in that game version (for example Mythic+ and the Hall of Fame only for Retail).
- **Configure** on the Battle.net Account entry removes the login (deleting the entry does the same); the account sensors and the gold of the characters go, characters and everything else stay.
- **Reconfigure** (in an entry's menu) logs in with Battle.net to import more characters or renew the login.

The entry reloads on its own after every change.

### Upgrading from an older version

Older versions kept all characters and the Battle.net login in one entry. On the first start the entry is split into one entry per game version, with every character as a subentry, and a kept login moves to a new Battle.net Account entry. Entity IDs, history and statistics stay the same.

## Entities

Each character becomes a device named `<Character> (<realm>)`, each realm becomes `<Realm> Server`, and all Hall of Fame sensors share the device `WoW Leaderboards`. Devices belong to the entry of their game version. Home Assistant builds entity IDs from the device name and the sensor name in your system language at the time the entity is created. With English as the system language, the character "Thrall" on "stormrage" gets IDs like `sensor.thrall_stormrage_level`. You can rename any entity ID in the UI.

### Character sensors

| Sensor | Example entity ID (English) | Notes |
| --- | --- | --- |
| Level | `sensor.thrall_stormrage_level` | |
| Item Level | `sensor.thrall_stormrage_item_level` | Equipped item level |
| Guild | `sensor.thrall_stormrage_guild` | "No guild" if the character is in none |
| Achievement Points | `sensor.thrall_stormrage_achievement_points` | |
| Equipment Details | `sensor.thrall_stormrage_equipment_details` | Number of equipped items; gear per slot in attributes |
| 2v2 Arena Rating | `sensor.thrall_stormrage_2v2_arena_rating` | PvP |
| 3v3 Arena Rating | `sensor.thrall_stormrage_3v3_arena_rating` | PvP |
| RBG Rating | `sensor.thrall_stormrage_rbg_rating` | PvP, Retail |
| Honor Level | `sensor.thrall_stormrage_honor_level` | PvP, Retail |
| PvP Wins (Season) | `sensor.thrall_stormrage_pvp_wins_season` | Sum over the tracked brackets |

Classic Progression and Anniversary characters get `title_cutoffs` on the 2v2 and 3v3 sensors instead: every title of the season (for example Gladiator, Duelist, Rival) with the rating it needs, highest first.

The rated PvP sensors only count the current season. Blizzard returns the last season a character played; ratings from an older season show as 0, with the old rating in `last_season_rating`. Every bracket sensor has `season_played`, `season_won`, `season_lost`, `weekly_played` and `weekly_won`, and 3v3 / RBG show the `gladiator_cutoff` / `hero_cutoff`.

With **PvP leaderboards** enabled, the bracket sensors of every bracket a Retail character played this season also get `leaderboard_rank` (place on the regional leaderboard, `null` if not on it), `leaderboard_entries` and `leaderboard_min_rating` (the rating needed to be listed). Blizzard only lists the best players of the region, about 5000 per bracket. Each leaderboard needed by one of your characters is downloaded once per hour (about 2 MB).

| LFR / Normal / Heroic / Mythic Progress | `sensor.thrall_stormrage_mythic_progress` | Bosses defeated in the current expansion's raids |
| Total Boss Kills | `sensor.thrall_stormrage_total_boss_kills` | Bosses defeated across all raids, lifetime |
| M+ Score | `sensor.thrall_stormrage_m_score` | Current season |
| Best M+ Level | `sensor.thrall_stormrage_best_m_level` | Highest key this season; best key, timing and duration per dungeon in `best_runs` |
| M+ Runs Completed | `sensor.thrall_stormrage_m_runs_completed` | Number of best runs the API reports this season, not all runs |
| M+ Runs Timed | `sensor.thrall_stormrage_m_runs_timed` | Timed runs among those best runs |
| Weekly Best M+ | `sensor.thrall_stormrage_weekly_best_m` | Highest key this week |
| Profile Status | `sensor.thrall_stormrage_profile_status` | `valid`, `invalid` or `not_found`, e.g. after a rename, transfer or deletion |
| Honorable Kills | `sensor.thrall_stormrage_honorable_kills` | PvP, lifetime |
| PvP Rank | `sensor.thrall_stormrage_pvp_rank` | PvP, Classic Era honor rank (0 = none) |
| Professions | `sensor.thrall_stormrage_professions` | Primary professions; skill of the newest tier per profession in `professions` |
| Health | `sensor.thrall_stormrage_health` | Details; primary stats, armor, power in attributes |
| Critical Strike / Haste / Mastery / Versatility | `sensor.thrall_stormrage_haste` | Details, in percent |
| Title | `sensor.thrall_stormrage_title` | Details, active title ("No title" if none is selected); Retail adds `title_count` |
| Reputations | `sensor.thrall_stormrage_reputations` | Details, number of known factions; standing per faction in `factions` |
| Talents | `sensor.thrall_stormrage_talents` | Details; Retail: hero talent tree with `loadout_code`, Classic Progression: specialization with `talent_list` and `glyphs`, Era/Anniversary: points per tree |
| Dungeons Completed | `sensor.thrall_stormrage_dungeons_completed` | Details, dungeons of the newest expansion with at least one completed difficulty |
| Deaths | `sensor.thrall_stormrage_deaths` | Details, lifetime |
| Quests Completed | `sensor.thrall_stormrage_quests_completed` | Details, lifetime |
| Active Quests | `sensor.thrall_stormrage_active_quests` | Details, Retail and WoW Forever; quest names in `quests` |
| Achievements | `sensor.thrall_stormrage_achievements` | Details, Retail, Classic Progression and WoW Forever; `total_points` and the 10 most recent achievements in `recent_achievements`. The response is 1 to 3 MB, it is only fetched after a new login and at most every 6 hours |
| Hunter Pet | `sensor.thrall_stormrage_hunter_pet` | Details, hunters only; summoned pet, all pets in `pets` |
| Mounts / Pets / Toys / Heirlooms / Housing Decor | `sensor.thrall_stormrage_mounts` | Collections, Retail |
| Transmog Appearances | `sensor.thrall_stormrage_transmog_appearances` | Collections, Retail and WoW Forever; `appearance_sets` and `appearances_per_slot` in attributes. The response can be several MB, it is only fetched after a new login and at most every 6 hours |
| Solo Shuffle Rating / Blitz Rating | `sensor.thrall_stormrage_solo_shuffle_rating` | PvP, Retail, for the active specialization; `legend_cutoff` attribute |
| Gold | `sensor.thrall_stormrage_gold` | Retail, with the Battle.net Account entry; gold gained/lost, deaths, location and hearthstone in attributes |
| Guild Members | `sensor.thrall_stormrage_guild_members` | Guild, only for characters in a guild; achievement points, realm, faction, creation date, guild master and members per rank and class in attributes |
| Guild Members at Max Level | `sensor.thrall_stormrage_guild_members_at_max_level` | Guild; members at the highest level in the guild (`max_level`), per class in `members_by_class` |
| Guild Rank | `sensor.thrall_stormrage_guild_rank` | Guild; the character's rank number, 0 is the guild master (the API has no rank names) |
| Guild Achievements | `sensor.thrall_stormrage_guild_achievements` | Guild, Retail and Classic Progression; `total_points`, progress per category and the 10 most recent achievements |

Attributes on every character sensor: `character_name`, `realm`, `character_class`, `class_color`, `character_race`, `gender`, `character_level`, `guild`, `faction`, `active_spec`, `last_login`, `game_version`, `category`.

Raid difficulty sensors also have `expansion`, `total_bosses` and `raids`, which holds the per-raid progress, for example `{"The Dreamrift": "6/8"}`.

The Equipment Details sensor lists the gear in `equipped_items` (keyed by slot, e.g. `head`, `trinket_1`) and `equipped_items_list`. Each item has `slot`, `name`, `item_id`, `icon` (image URL), `item_level` (from the item itself in Classic, whose equipment has none; `null` if Blizzard returns none), `quality`, `quality_color`, `stats` and `transmog` (name of the transmogrified appearance, if any). These two attributes are not written to the recorder database.

### Character image

Every character also gets an image entity with the full-body render from the character media API, for example `image.thrall_stormrage_full_body_render`. It falls back to the avatar when no render is available. Blizzard only makes renders when a character logs out, so for new characters both URLs carry the CDN fallback (`?alt=/shadow/avatar/{race}-{gender}.jpg`) and show a silhouette instead of a broken image. Show it on a dashboard with a picture entity card:

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

Region-wide data lives on the device `WoW <REGION>`, for example `WoW EU`; Classic entries have their own, for example `WoW EU (Classic Progression)`.

| Sensor | Example entity ID (English) | Notes |
| --- | --- | --- |
| WoW Token Price | `sensor.wow_eu_wow_token_price` | Retail, in gold; `last_updated` attribute |
| WoW Token Price (Classic) | `sensor.wow_eu_wow_token_price_classic` | Only with a Classic Progression character |
| Weekly Reset | `sensor.wow_eu_weekly_reset` | Timestamp of the next weekly reset (Retail) |
| M+ Season | `sensor.wow_eu_m_season` | Mythic+, Retail; season ID, start and number of weeks in attributes |
| PvP Season | `sensor.wow_eu_pvp_season` | PvP, Retail; season ID and start in attributes |
| PvP Season (Classic) / (Anniversary) | `sensor.wow_eu_pvp_season_classic` | PvP, only with a character of that version; season number, start and `title_cutoffs` per bracket |
| Gladiator Cutoff | `sensor.wow_eu_gladiator_cutoff` | 3v3 rating needed for Gladiator this season |
| Hero Cutoff | `sensor.wow_eu_hero_cutoff` | RBG rating for Hero of the Alliance/Horde, per faction in attributes |
| M+ Affixes | `sensor.wow_eu_m_affixes` | Mythic+ leaderboards only; affixes of the week with their starting key level |

### Mythic+ realm leaderboards (opt-in)

With **Mythic+ leaderboards** enabled, every Retail realm device gets `Best M+ Key This Week` (e.g. `sensor.stormrage_server_best_m_key_this_week`). The attribute `dungeons` holds the best key, its duration and the number of listed runs per dungeon, `own_characters` the ranking of your configured characters. Each realm needs one download of about 1 MB per dungeon every hour.

### Auction house

Every tracked item gets a sensor on the device `WoW <REGION> Auction House`, named after the item, with the lowest price per item in gold (silver and copper as decimals). Attributes: `quantity` (items listed), `auctions`, and `sources` (lowest price per source). Retail looks in the region-wide commodity market first and in the auctions of your characters' realms for everything else; Classic Progression uses the realms of your Classic Progression characters. Classic Era and Anniversary auctions are not available in the API. The data is refreshed hourly; the Retail commodity market alone is about 30 MB, so only add the auction house if you need it.

### Guild activity

Each guild of your characters gets an event entity on the device of the first character in it, e.g. `event.thrall_stormrage_guild_activity`. It fires `achievement` (attributes `character`, `achievement`, `achievement_id`) and `encounter` (`encounter`, `encounter_id`, `difficulty`, `difficulty_name`) for every new entry in the guild's activity feed, and `member_joined` / `member_left` (`character`, `character_realm`, `level`) when the guild roster changes. Activity and roster are checked hourly; entries from before Home Assistant started are not replayed, and roster changes are found by comparing two checks, so joins and leaves while Home Assistant was off are not reported. A new event entity starts with the guild's newest feed entry instead of `unknown`. Blizzard has no activity feed for Classic Anniversary and WoW Forever guilds; those only get roster events.

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

### Character achievements

With character details enabled, every Retail, Classic Progression and WoW Forever character gets an event entity, e.g. `event.thrall_stormrage_achievements`. It fires `achievement` (attributes `achievement`, `achievement_id`, `timestamp`, `character`) for every new achievement. Blizzard updates achievements when the character logs out, and the integration checks them after a new login, so the event follows the logout.

### Guild crest

Each guild with a crest gets an image entity on the device of the first character in it, e.g. `image.thrall_stormrage_guild_crest`. The integration colors Blizzard's emblem and border images with the guild's colors. Classic Progression and WoW Forever guilds have no crest in the API.

### Battle.net account (optional)

The Battle.net Account entry has the device `Battle.net Account` with `Total Gold` (Retail), `Characters`, `Account Mounts`, `Account Pets`, `Account Toys`, `Account Heirlooms`, `Account Transmog Appearances` (with `appearance_sets` and `appearances_per_slot`) and `Battle.net Login Expires`. Housing decor is left out while Blizzard answers its account endpoint with 404. The account transmog collection can be several MB, so it is fetched at most every 6 hours. The attribute `login_valid` turns `false` when the 24 hour login has expired or Blizzard rejects it (for example after a password change); the values then keep their last state. Temporary API errors also keep the last values instead of dropping to 0.

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

## Dashboard cards

The integration includes its own dashboard cards. They load with the integration, so you do not need to download anything or add a dashboard resource. After installing or updating, reload the browser once.

### Character card

Edit a dashboard, select **Add card** and choose **WoW Character** (under the community cards). Pick a character, then choose its sections under **Sections**. The list only offers the sections the character has data for, so a Classic character has no Mythic+ section. Drag the sections to change their order.

```yaml
type: custom:wow-character-card
device: 270f6e8b30eed0c326a3891a590356e8
sections:
  - overview
  - equipment
  - stats
  - mythic_plus
```

| Option | Default | Description |
| --- | --- | --- |
| `device` | – | The character device. Required. The editor only lists World of Warcraft characters. |
| `sections` | `[overview, progress]` | The sections below the header, in this order. See the table below. |
| `show_render` | `true` | Shows the character render in the background, or between the item slots of the equipment section. |

The header is always shown: portrait, name, title, level, race, class and spec in class color, guild, realm and item level.

| Section | Shows |
| --- | --- |
| `overview` | Achievement points, honorable kills, gold and PvP ratings above 0, as tiles |
| `progress` | Raid progress per difficulty and the Mythic+ rating, in one line |
| `equipment` | The equipped items like the in-game character window, with item level and quality; hover an item for its name and transmog |
| `stats` | Health, power, primary stats, armor, attack and spell power, critical strike, haste, mastery and versatility |
| `talents` | Specialization, hero talents and the loadout code (select it to copy), or the talent points per tree and glyphs in Classic |
| `raids` | Bosses per difficulty and per raid of the current expansion, and boss kills in total |
| `mythic_plus` | Rating, best key, weekly best, runs in time and completed, and the best run per dungeon |
| `pvp` | All ratings, honor level, season wins, honorable kills and the Classic PvP rank |
| `professions` | Primary and secondary professions with skill |
| `reputations` | All factions with standing, with progress where Blizzard provides it |
| `collections` | Mounts, pets, toys, heirlooms, appearances and decor |
| `achievements` | Achievement points, achievements completed and the latest achievements |
| `activity` | Gold, deaths, quests, active quests, dungeons completed, location, hearthstone and last login |
| `guild` | Crest, members, members at max level, your rank, guild master, founding date, guild achievements and the latest guild activity |
| `hunter_pet` | The hunter's pets with level and the active one |

A section the character has no data for is left out, also when it is in `sections`. Select a value to open the entity's history.

Cards from the first version with `show_stats`, `show_progress` and `show_equipment` keep working; the editor converts them to `sections` when you change them.

The card texts are in English and German, following the language of your Home Assistant profile. Names, classes, factions and dungeons come from the Blizzard API in the language set for the integration.

### Card styling

All colors are CSS custom properties, so a theme or card-mod can change them:

| Property | Default | Used for |
| --- | --- | --- |
| `--wow-gold` | `#c8a95c` | Frame corners, values, titles |
| `--wow-panel` / `--wow-panel-2` | `#0d0f14` / `#181b24` | Background |
| `--wow-text` / `--wow-text-dim` | `#f2ead7` / `#a59e8c` | Text |
| `--wow-guild` | `#40ff40` | Guild name |
| `--wow-alliance` / `--wow-horde` | `#2f6fd6` / `#c4232b` | Faction glow |
| `--wow-heading-font` | Friz Quadrata, Georgia, serif | Names and large numbers |

The cards ship no fonts or textures and load no code from other sites. Pictures (portraits, renders, item icons) come from Blizzard's render server, the same addresses the entities use.

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

- All data is refreshed every 5 minutes, each game version entry on its own. Characters are fetched in parallel; all entries with the same API client share a limit of 8 requests at a time and 40 per second. The status of all realms of a game version comes from a single connected realm search request.
- Item icons and the slowly changing character data (details, collections, achievements) are stored, so a restart or reload only fetches what changed (e.g. 15 characters: about 13 seconds instead of about a minute).
- Data from the Battle.net API reflects what Blizzard has processed, which usually lags the game by a few minutes and may be refreshed only after logout.
- Character details and collections are only fetched again when the character's last login changes, and at least every 6 hours. Guild data, roster, guild achievements and guild activity are cached for 1 hour, the weekly period until the reset, the Mythic+ and PvP seasons for 6 hours.
- Auction prices, Mythic+ and PvP leaderboards are refreshed hourly, account data (gold) every 15 minutes while the Battle.net login is valid. Large responses are decoded outside the event loop.
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
- PvP ratings show `0` until the character has played rated games in that bracket this season.
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
- WoW Forever auction prices are not supported (see [WoW Forever](#wow-forever)).
- Weekly activities (Great Vault, weekly quests) are not part of the public game data API for other accounts, so they cannot be tracked.

## Contributing

Bug reports and feature requests are welcome in the [issue tracker](https://github.com/yourdawi/homeassistant-wow-blizzard/issues). For bugs, please include:

- Home Assistant version and integration version
- Game version, region and realm of the affected character
- Relevant log lines with debug logging enabled

Pull requests are welcome as well.

The dashboard cards are written in TypeScript with Lit in [`cards/`](cards). Build them with Node.js 22 or newer:

```bash
cd cards
npm install
npm run build
```

The build writes `custom_components/wow_blizzard/www/wow-cards.js`, which the release workflow builds for every release. `npm run watch` rebuilds on every change. Restart Home Assistant to serve a new build under a new cache key, then reload the browser.

## License

MIT, see [LICENSE](LICENSE).

World of Warcraft and Blizzard Entertainment are trademarks of Blizzard Entertainment, Inc. This project is not affiliated with or endorsed by Blizzard Entertainment.
