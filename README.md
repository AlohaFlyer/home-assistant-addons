# AlohaFlyer Home Assistant apps

Home Assistant apps (add-ons) by AlohaFlyer.

| App | Folder | What it does |
|-----|--------|--------------|
| **Flight Watcher** | `flight_watcher/` | Watches FLICA for an airline pilot: the open time pot, the pilot's schedule and its versions, request decisions, Recall / Over 75, tickets. FLICA is read only. Dashboard cards and phone pushes in Home Assistant. |
| AI Agent Manager - HI | `ai_agent_manager_hi/` | A Claude meta-agent that watches the other Home Assistant agents. |
| AI Agent Manager - NV | `claude_agent_manager/` | Multi-agent manager: rules first, then Ollama on the local box, Claude only as the fallback. |

## Installation

1. In Home Assistant open the app store (Settings > Apps).
2. Use the three-dot menu in the top right corner and pick **Repositories**.
3. Add `https://github.com/AlohaFlyer/home-assistant-addons`.
4. Find the app and install it.

## Flight Watcher

Keeps one FLICA session alive, reloads the open time pot at random gaps and publishes new pairings, schedule
versions, request decisions and Recall / Over 75 checks to Home Assistant over MQTT. **Nothing is ever submitted,
dropped, swapped, added or bid in FLICA.** Logins go in on the dashboard Settings card (sealed in the browser) or
the app's Configuration tab, never in git. Bug reports and feature requests are tickets (FW-nnnn) filed from the
dashboard, which can be edited while new and deleted any time. A second pilot runs as his own instance. See
[flight_watcher/README.md](flight_watcher/README.md).

## AI Agent Manager

Three tiers, cheapest first:

```
┌─────────────────────────────────────────────────────────────┐
│  TIER 1: Rule-Based (FREE) - ~70% of decisions              │
│  └── Simple patterns: overheat, pump issues, lights on      │
├─────────────────────────────────────────────────────────────┤
│  TIER 2: Ollama Local (FREE) - ~25% of decisions            │
│  └── Pattern analysis, correlations (runs on your hardware) │
├─────────────────────────────────────────────────────────────┤
│  TIER 3: Claude API (PAID) - ~5% of decisions               │
│  └── Complex reasoning (only when Tier 2 is uncertain)      │
└─────────────────────────────────────────────────────────────┘
```

| Agent | What it monitors |
|-------|------------------|
| **Pool** | Temperature, pump, valves, heating modes, Z-Wave health |
| **Lights** | Exterior lights during day, late-night lights, pool lights |
| **Security** | Door locks, cameras online, alarm status |
| **Climate** | Indoor temperature, HVAC, humidity |

Needs the Ollama app running with a model pulled (e.g. `llama3.2:1b`); a Claude API key is optional, for Tier 3.

## License

MIT License
