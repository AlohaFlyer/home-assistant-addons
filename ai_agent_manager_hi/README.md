# AI Agent Manager - HI

An AI-powered meta-agent that monitors and manages all Home Assistant agents using Claude for intelligent decision-making, autonomous actions, and pattern learning.

## Features

- **Intelligent Monitoring**: Uses Claude to analyze all 9 Home Assistant agents
- **Autonomous Actions**: Can automatically fix issues when detected
- **Pattern Learning**: Learns from system behavior over time
- **Predictive Alerts**: Anticipates problems before they occur
- **TOU-Aware**: Understands Hawaii Electric TOU rates for cost optimization
- **Cross-Agent Correlation**: Detects relationships between agent behaviors
- **Hybrid LLM Mode**: Uses 3-tier approach (Rules → Ollama → Claude) for 90%+ cost savings

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                  AI Agent Manager - HI                       │
├─────────────────────────────────────────────────────────────┤
│  ┌─────────────────────────────────────────────────────┐    │
│  │              HYBRID LLM MANAGER                      │    │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────────────┐   │    │
│  │  │ TIER 1   │→ │ TIER 2   │→ │     TIER 3       │   │    │
│  │  │ Rules    │  │ Ollama   │  │    Claude API    │   │    │
│  │  │ (FREE)   │  │ (FREE)   │  │    (PAID)        │   │    │
│  │  └──────────┘  └──────────┘  └──────────────────┘   │    │
│  └─────────────────────────────────────────────────────┘    │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐  │
│  │   Claude    │  │   Pattern   │  │   Home Assistant    │  │
│  │   Agent     │←→│   Learner   │←→│      Client         │  │
│  │   (Tools)   │  │             │  │                     │  │
│  └─────────────┘  └─────────────┘  └─────────────────────┘  │
├─────────────────────────────────────────────────────────────┤
│                    Monitored Agents                          │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐       │
│  │Powerwall │ │  Light   │ │ Hot Tub  │ │  Mower   │       │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘       │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐       │
│  │ Garage   │ │Occupancy │ │  Z-Wave  │ │ Security │       │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘       │
│  ┌──────────┐ ┌──────────┐                                  │
│  │ Climate  │ │  Truth   │                                  │
│  └──────────┘ └──────────┘                                  │
└─────────────────────────────────────────────────────────────┘
```

## Installation

### Prerequisites

1. Home Assistant OS (HAOS) installation
2. Anthropic API key (get one at https://console.anthropic.com)
3. Home Assistant Long-Lived Access Token

### Steps

1. **Add the repository to HAOS**

   - Go to Settings → Add-ons → Add-on Store
   - Click the three-dot menu → Repositories
   - Add: `https://github.com/AlohaFlyer/home-assistant-addons`

2. **Install the add-on**

   - Find "AI Agent Manager - HI" in the add-on store
   - Click Install

3. **Configure the add-on**

   Click on the add-on and configure:
   ```yaml
   claude_api_key: "sk-ant-api03-..."  # Your Anthropic API key
   ha_token: ""  # Optional if using Supervisor API
   check_interval_minutes: 5
   autonomous_actions: true
   learning_enabled: true
   notification_level: "warning"
   max_auto_fixes_per_hour: 10
   log_level: "info"
   # Hybrid LLM (cost optimization)
   hybrid_mode_enabled: true
   ollama_url: "http://homeassistant.local:11434"
   ollama_model: "llama3.2:3b"
   ```

4. **Start the add-on**

   Click "Start" and check the logs.

## Configuration Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `claude_api_key` | string | Required | Your Anthropic API key |
| `ha_token` | string | Optional | Long-lived access token (uses Supervisor token if empty) |
| `check_interval_minutes` | int | 5 | How often to run analysis (1-60) |
| `autonomous_actions` | bool | true | Allow automatic issue resolution |
| `learning_enabled` | bool | true | Enable pattern learning |
| `notification_level` | string | warning | Minimum level to notify: debug/info/warning/error |
| `max_auto_fixes_per_hour` | int | 10 | Maximum automatic actions per hour |
| `log_level` | string | info | Logging verbosity |
| `hybrid_mode_enabled` | bool | true | Use 3-tier LLM approach for 90%+ cost savings |
| `ollama_url` | url | localhost:11434 | Local Ollama server URL |
| `ollama_model` | string | llama3.2:3b | Local model for Tier 2 |
| `claude_model` | string | claude-3-haiku | Claude model for Tier 3 |
| `escalation_threshold` | float | 0.7 | Confidence threshold for escalation |

## Hybrid LLM System (Cost Optimization)

The hybrid mode dramatically reduces Claude API costs by using a 3-tier approach:

### Tier 1: Rule-Based Analysis (FREE)
Handles ~70% of routine checks without any LLM:
- Simple status checks (healthy/warning/critical)
- Threshold violations (battery low, devices unavailable)
- Time-based rules (TOU rates, schedules)

### Tier 2: Local LLM via Ollama (FREE)
Runs on your Home Assistant server:
- Pattern recognition in state data
- Simple correlation detection
- JSON-structured responses

### Tier 3: Claude API (PAID)
Full Claude capabilities for complex situations:
- Deep pattern analysis
- Tool use (query entities, call services)
- Predictive insights
- Natural language recommendations

### Cost Comparison
| Mode | Daily Cost | Monthly Cost |
|------|------------|--------------|
| Claude-only | ~$0.50-1.00 | ~$15-30 |
| Hybrid mode | ~$0.03-0.10 | ~$1-3 |

## How It Works

### Analysis Cycle

Every `check_interval_minutes`, the agent:

1. **Collects** all agent sensor states
2. **Tier 1**: Rule-based checks (FREE)
3. **Tier 2**: Local Ollama analysis if needed (FREE)
4. **Tier 3**: Claude API for complex issues (PAID)
5. **Takes action** if autonomous and authorized
6. **Learns** new patterns from the analysis

### Claude's Capabilities

Claude receives:
- Current state of all 10 agents
- Time of day and TOU electricity rates
- Historical patterns from the learning system
- Recent observations and correlations

Claude can:
- Call Home Assistant services (if autonomous)
- Query entity history
- Send notifications
- Log observations for learning

### Learning System

The pattern learner tracks:
- **Timing patterns**: Issues that occur at specific times
- **Correlations**: Entities that change together
- **Sequences**: State change patterns
- **Anomalies**: Unusual behaviors

Patterns are stored in `/config/ai_agent_manager_hi/learning_data.json`.

## Monitored Agents

| Agent | Purpose |
|-------|---------|
| **Powerwall** | Battery, solar, TOU optimization |
| **Light Manager** | Relay/color sync, drift detection |
| **Hot Tub** | Temperature, schedule, energy |
| **Mower** | Gate coordination, task tracking |
| **Garage/Gate** | Door status, obstructions |
| **Occupancy** | Room presence, idle detection |
| **Z-Wave** | Network health, device availability |
| **Security** | Camera status, detections |
| **Climate** | Floor heating, solar excess |
| **Truth** | Sensor validation, cost accuracy |

## Notifications

The agent sends notifications via Home Assistant's persistent notification system:

- **🤖 Agent Manager Started** - On startup
- **🔴 Agent Issue** - When problems detected
- **✅ Optimization Applied** - After auto-fix
- **⚠️ Prediction** - For high-confidence predictions
- **❌ Agent Manager Error** - On failures

## Troubleshooting

### Add-on won't start

1. Check that `claude_api_key` is set correctly
2. Verify the API key is valid at console.anthropic.com
3. Check add-on logs for specific errors

### No analysis happening

1. Verify `check_interval_minutes` is reasonable (5-15 recommended)
2. Check that agent sensors exist and are not unavailable
3. Look for API rate limiting in logs

### Autonomous actions not working

1. Verify `autonomous_actions: true`
2. Check `max_auto_fixes_per_hour` hasn't been reached
3. Ensure the Home Assistant token has sufficient permissions

### Ollama not working

1. Install Ollama add-on or run external Ollama server
2. Pull a model: `ollama pull llama3.2:3b`
3. Verify URL is correct in configuration
4. System falls back to Claude if Ollama unavailable

## API Usage

**With Hybrid Mode (recommended):**
- Tier 1 (Rules): ~70% of checks → FREE
- Tier 2 (Ollama): ~25% of checks → FREE
- Tier 3 (Claude): ~5% of checks → ~$0.03-0.05/day

**Without Hybrid Mode:**
- ~1,000-2,000 tokens per analysis
- 5-minute intervals = ~288 calls/day
- ~$0.50-1.00/day

## Security Considerations

- API keys are stored in add-on options (encrypted by Supervisor)
- The add-on runs in a sandboxed container
- Only authorized service calls are made
- Pattern data stays local

## License

MIT License - Use freely with attribution.

## Credits

- Built with [Anthropic Claude API](https://anthropic.com)
- For [Home Assistant](https://home-assistant.io)
- Pattern learning inspired by time-series analysis techniques
- Hybrid LLM architecture for cost optimization
