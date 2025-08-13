# World of Warcraft Blizzard API Home Assistant Integration

**The most comprehensive World of Warcraft integration for Home Assistant!**

Monitor multiple characters, server status, PvP ratings, raid progress, and Mythic+ scores directly in your smart home dashboard.

## 🚀 Features

### 📊 Character Monitoring
- **Multiple Characters**: Monitor unlimited characters across different realms
- **Real-time Stats**: Level, item level, guild, achievement points
- **Cross-Realm Support**: Characters from different servers in one integration

### 🌐 Server Monitoring
- **Realm Status**: Online/Offline status
- **Population**: Low/Medium/High/Full
- **Queue Times**: Login queue information
- **Maintenance Tracking**: Scheduled downtime alerts

### ⚔️ PvP Statistics  
- **Arena Ratings**: 2v2, 3v3 current season ratings
- **Rated Battlegrounds**: RBG rating and wins
- **Honor System**: Honor level and seasonal statistics
- **Win/Loss Tracking**: Season performance metrics

### 🏰 Raid Progress
- **Current Tier Tracking**: Aberrus, Amirdrassil, Vault progress
- **All Difficulties**: LFR, Normal, Heroic, Mythic boss kills
- **Total Kill Counter**: Lifetime boss defeats
- **Weekly Progress**: Fresh raid lockouts

### 🗝️ Mythic+ Dungeons
- **Season Score**: Current Mythic+ rating
- **Best Key Level**: Highest completed key
- **Completion Stats**: Total runs, timed runs
- **Weekly Progress**: Best weekly key completion

### 🎮 Multi-Region Support
- **Americas (US)**: us.api.blizzard.com
- **Europe (EU)**: eu.api.blizzard.com  
- **Korea (KR)**: kr.api.blizzard.com
- **Taiwan (TW)**: tw.api.blizzard.com
- **China (CN)**: gateway.battlenet.com.cn

## 📋 Prerequisites

1. **Battle.net Developer Account**: https://develop.battle.net/access/clients
2. **API Client Credentials**: Client ID & Client Secret
3. **Home Assistant 2023.8+**: Latest stable release
4. **HACS (Recommended)**: For easy installation and updates

## 🔧 Installation

### Via HACS (Recommended)

1. Open **HACS** → **Integrations**
2. Click **⋮** → **Custom repositories** 
3. Add: `https://github.com/yourdawi/homeassistant-wow-blizzard`
4. Category: **Integration**
5. Install **"World of Warcraft Blizzard API"**
6. **Restart Home Assistant**

### Manual Installation

1. Download all files to `config/custom_components/wow_blizzard/`
2. Ensure folder structure matches:
```
config/
├── custom_components/
│   └── wow_blizzard/
│       ├── __init__.py
│       ├── manifest.json
│       ├── const.py
│       ├── api_client.py
│       ├── sensor.py
│       ├── config_flow.py
│       └── strings.json
```
3. **Restart Home Assistant**

## ⚙️ Configuration

### 1. Create Battle.net API Application

1. Visit https://develop.battle.net/access/clients
2. **Sign in** with your Battle.net account
3. **Create new client**:
   - **Name**: "Home Assistant WoW Integration"
   - **Redirect URLs**: `https://my.home-assistant.io/redirect/oauth`
4. **Save** your Client ID and Client Secret

### 2. Add Integration

1. **Settings** → **Devices & Services**
2. **Add Integration** → Search **"WoW Blizzard API"**
3. **Enter API Credentials**:
   - Client ID from step 1
   - Client Secret from step 1
   - Your region (US/EU/KR/TW/CN)

### 3. Select Features

Choose which features to enable:
- ✅ **Server Status**: Realm monitoring
- ✅ **PvP Statistics**: Arena/RBG ratings  
- ✅ **Raid Progress**: Boss kill tracking
- ✅ **Mythic+ Data**: Dungeon scores

### 4. Add Characters

1. **Select Realm**: Choose from dropdown list
2. **Enter Character Name**: Case-sensitive
3. **Validate**: Integration checks character exists
4. **Add More**: Repeat for additional characters
5. **Finish**: Complete setup

## 📱 Created Sensors

### Per Character Sensors

**Basic Stats** (Always enabled):
- `sensor.charactername_level`
- `sensor.charactername_item_level` 
- `sensor.charactername_guild`
- `sensor.charactername_achievement_points`
- `sensor.charactername_gold`

**PvP Stats** (If enabled):
- `sensor.charactername_2v2_arena_rating`
- `sensor.charactername_3v3_arena_rating`
- `sensor.charactername_rbg_rating`
- `sensor.charactername_honor_level`
- `sensor.charactername_pvp_wins_season`

**Raid Progress** (If enabled):
- `sensor.charactername_lfr_progress`
- `sensor.charactername_normal_progress`
- `sensor.charactername_heroic_progress`
- `sensor.charactername_mythic_progress`
- `sensor.charactername_total_boss_kills`

**Mythic+ Stats** (If enabled):
- `sensor.charactername_m_score`
- `sensor.charactername_best_m_level`
- `sensor.charactername_m_runs_completed`
- `sensor.charactername_m_runs_timed`
- `sensor.charactername_weekly_best_m`

### Server Sensors

**Per Realm** (If enabled):
- `sensor.realmname_realm_status`
- `sensor.realmname_population`
- `sensor.realmname_queue_time`

## 🏠 Dashboard Examples

### Multi-Character Overview Card
```yaml
type: entities
title: WoW Characters
entities:
  - entity: sensor.mainchar_level
    name: "Main - Level"
  - entity: sensor.mainchar_item_level
    name: "Main - iLvl"
  - entity: sensor.alt1_level
    name: "Alt 1 - Level"
  - entity: sensor.alt1_item_level  
    name: "Alt 1 - iLvl"
  - entity: sensor.alt2_level
    name: "Alt 2 - Level"
  - entity: sensor.alt2_item_level
    name: "Alt 2 - iLvl"
```

### PvP Ratings Dashboard
```yaml
type: glance
title: PvP Ratings
entities:
  - entity: sensor.mainchar_2v2_arena_rating
    name: "2v2"
  - entity: sensor.mainchar_3v3_arena_rating
    name: "3v3"  
  - entity: sensor.mainchar_rbg_rating
    name: "RBG"
  - entity: sensor.mainchar_honor_level
    name: "Honor"
```

### Raid Progress Tracker
```yaml
type: horizontal-stack
cards:
  - type: entity
    entity: sensor.mainchar_normal_progress
    name: "Normal"
    icon: mdi:castle
  - type: entity
    entity: sensor.mainchar_heroic_progress  
    name: "Heroic"
    icon: mdi:castle
  - type: entity
    entity: sensor.mainchar_mythic_progress
    name: "Mythic"
    icon: mdi:castle
```

### Server Status Card
```yaml
type: entities
title: Server Status
entities:
  - entity: sensor.stormrage_realm_status
    name: "Stormrage Status"
  - entity: sensor.stormrage_population
    name: "Population"
  - entity: sensor.stormrage_queue_time
    name: "Queue"
```

## 🤖 Automation Examples

### Level-Up Celebration
```yaml
automation:
  - alias: "WoW Character Level Up"
    trigger:
      - platform: state
        entity_id: 
          - sensor.mainchar_level
          - sensor.alt1_level
          - sensor.alt2_level
    condition:
      - condition: template
        value_template: "{{ trigger.to_state.state | int > trigger.from_state.state | int }}"
    action:
      - service: notify.mobile_app
        data:
          title: "🎉 Level Up!"
          message: "{{ trigger.to_state.attributes.character_name }} reached level {{ trigger.to_state.state }}!"
```

### High PvP Rating Alert
```yaml
automation:
  - alias: "High Arena Rating Achieved"
    trigger:
      - platform: numeric_state
        entity_id: sensor.mainchar_3v3_arena_rating
        above: 2100
    action:
      - service: notify.discord
        data:
          message: "🏆 {{ trigger.to_state.attributes.character_name }} hit {{ trigger.to_state.state }} rating in 3v3!"
```

### Raid Boss Kill Notification
```yaml
automation:
  - alias: "New Raid Boss Kill"
    trigger:
      - platform: state
        entity_id: sensor.mainchar_mythic_progress
    condition:
      - condition: template
        value_template: "{{ trigger.to_state.state | int > trigger.from_state.state | int }}"
    action:
      - service: notify.family
        data:
          message: "🐉 {{ trigger.to_state.attributes.character_name }} killed a new Mythic boss! ({{ trigger.to_state.state }}/{{ trigger.to_state.attributes.total_bosses }})"
```

### Server Downtime Alert
```yaml
automation:
  - alias: "Server Maintenance Alert"
    trigger:
      - platform: state
        entity_id: sensor.stormrage_realm_status
        to: "Offline"
    action:
      - service: notify.mobile_app
        data:
          title: "🔧 Server Maintenance"
          message: "Stormrage is offline for maintenance"
```

### Mythic+ Score Milestone
```yaml
automation:
  - alias: "M+ Score Milestone"
    trigger:
      - platform: numeric_state
        entity_id: sensor.mainchar_m_score
        above: 2500
    action:
      - service: script.celebrate_achievement
        data:
          character: "{{ trigger.to_state.attributes.character_name }}"
          achievement: "M+ Score over 2500!"
          score: "{{ trigger.to_state.state }}"
```

## 🔧 Advanced Configuration

### Custom Update Intervals

The integration uses smart update intervals:
- **Basic Data**: 5 minutes
- **PvP/M+ Data**: 1 minute (during active play)
- **Server Status**: 15 minutes
- **Rate Limiting**: Automatic handling

### Multiple Characters Management

Add/remove characters through:
1. **Integration Options**: Settings → Devices & Services → WoW Integration → Configure
2. **Reconfigure**: Remove and re-add integration
3. **YAML** (Advanced): Direct configuration editing

### Feature Toggle

Enable/disable features without recreating sensors:
- Go to integration **Options**
- Toggle feature checkboxes
- **Restart** Home Assistant

## 🚨 Troubleshooting

### Common Issues

**Authentication Errors (401/403)**:
- Verify Client ID and Client Secret
- Check API client is active on Battle.net
- Ensure region matches your characters

**Character Not Found (404)**:
- Verify character name spelling (case-sensitive)
- Confirm character exists and is public
- Check realm name matches exactly
- Character must be level 10+ for some data

**Rate Limiting (429)**:
- Integration handles automatically
- Waits and retries on rate limits
- Consider reducing character count if persistent

**Server Timeout Issues**:
- Check Blizzard API status
- Verify internet connectivity
- Try different region if applicable

**Missing Data**:
- Some features require character activity
- PvP data needs recent PvP participation
- M+ data requires current season runs
- Raid data needs recent raid clears

### Debug Logging

Enable debug logging in `configuration.yaml`:
```yaml
logger:
  default: info
  logs:
    custom_components.wow_blizzard: debug
```

### Data Freshness

API data updates at different rates:
- **Character Level/Gear**: Near real-time
- **PvP Ratings**: After match completion
- **Raid Progress**: After boss kills
- **M+ Scores**: After key completion
- **Server Status**: Every few minutes

## 🔄 Updates & Maintenance

### Season Updates

When new content releases:
1. **Integration Update**: Install latest version
2. **Season IDs**: Automatically updated
3. **New Features**: May require reconfiguration

### API Changes

Blizzard occasionally updates APIs:
- Integration adapts automatically
- Check Home Assistant logs for warnings
- Update integration when available

## 🤝 Contributing

We welcome contributions!

### Feature Requests
- **GitHub Issues**: Report bugs, request features

## 📊 Supported Content

### Current Expansion: Dragonflight
- **Raids**: Vault of Incarnates, Aberrus, Amirdrassil
- **Dungeons**: Season 3 & 4 rotation
- **PvP**: Seasons 1-4 support
- **Features**: All current expansion content

### Legacy Support
- **Previous Expansions**: Limited data
- **Classic**: Separate API (future support)
- **Hardcore**: Character monitoring only


## 📈 Performance

### Resource Usage
- **Memory**: ~10MB per character
- **CPU**: Minimal impact
- **Network**: ~1MB/hour per character
- **Storage**: <1MB configuration

### Scalability
- **Characters**: Unlimited (API rate limited)
- **Realms**: All supported regions
- **Refresh Rate**: Configurable intervals
- **Data Retention**: Home Assistant standard

### Special Thanks
- **Blizzard Entertainment**: Official API
- **Home Assistant**: Platform foundation
- **Community**: Feature requests & testing
- **HACS**: Distribution platform

### Open Source
- **License**: MIT License
- **Source Code**: Fully open source

## 📞 Support

### Getting Help
1. **Documentation**: Check this README first
2. **GitHub Issues**: Technical problems

### Reporting Bugs
Please include:
- Home Assistant version
- Integration version  
- Error logs
- Steps to reproduce
- Character/realm details (if relevant)

### Feature Requests
We love new ideas! Include:
- Use case description
- Expected behavior
- API endpoints needed
- Priority level

---

**⚡ Transform your Home Assistant into the ultimate WoW command center!**

Monitor your entire guild, track progression, and never miss another raid night with the most comprehensive World of Warcraft integration available.