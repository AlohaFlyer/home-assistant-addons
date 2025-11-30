# AI Agent Manager for Home Assistant

Multi-agent home automation manager using a 3-tier hybrid LLM system.

## Installation

1. Go to **Settings** → **Add-ons** → **Add-on Store**
2. Click the three dots menu in the top right corner
3. Select **Repositories**
4. Add the URL: `https://github.com/AlohaFlyer/home-assistant-addons`
5. Click **Add**
6. Find "AI Agent Manager" and install

## How It Works

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

## Agents

| Agent | What It Monitors |
|-------|------------------|
| **Pool** | Temperature, pump, valves, heating modes, Z-Wave health |
| **Lights** | Exterior lights during day, late-night lights, pool lights |
| **Security** | Door locks, cameras online, alarm status |
| **Climate** | Indoor temperature, HVAC, humidity |

## Requirements

- Ollama add-on installed and running
- A model pulled (e.g., `llama3.2:1b`)
- Optional: Claude API key for Tier 3 fallback

## License

MIT License
