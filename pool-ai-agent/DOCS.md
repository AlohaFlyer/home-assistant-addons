# Pool AI Agent

AI-powered autonomous pool and hot tub management using Claude API with hybrid LLM cost optimization.

## Overview

Pool AI Agent is a Home Assistant add-on that uses AI to intelligently monitor and manage your pool system. It works alongside your existing automations, providing an additional layer of intelligent oversight.

**NEW in v1.1.0**: Hybrid LLM system reduces API costs by 90%+ using a 3-tier approach.

## Features

- **Autonomous Decision Making**: Makes decisions without requiring user approval
- **Real-time Monitoring**: WebSocket connection for instant state change detection
- **Pattern Analysis**: Detects anomalies like temperature drops, valve mismatches, pump issues
- **Safety-First**: Built-in safety rules that cannot be overridden
- **Cost Tracking**: Monitors API usage and costs
- **Decision History**: SQLite database logs all decisions for review
- **Hybrid LLM**: 3-tier cost optimization (rules → local → Claude)

## Installation

1. Copy the `pool-ai-agent` folder to `/config/addons/`
2. Go to Settings → Add-ons → Add-on Store
3. Click the three dots menu → Check for updates
4. Find "Pool AI Agent" in the local add-ons section
5. Click Install

## Configuration

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `anthropic_api_key` | string | required | Your Anthropic API key |
| `decision_interval_minutes` | int | 5 | Minutes between scheduled decision cycles |
| `log_level` | string | info | Logging level (debug/info/warning/error) |
| `hybrid_mode_enabled` | bool | true | Enable 3-tier hybrid LLM cost optimization |
| `ollama_url` | string | http://homeassistant.local:11434 | Ollama server URL |
| `ollama_model` | string | llama3.2:3b | Ollama model to use |

### Getting an Anthropic API Key

1. Go to [console.anthropic.com](https://console.anthropic.com)
2. Sign up or log in
3. Navigate to API Keys
4. Create a new API key
5. Copy and paste into the add-on configuration

### Setting Up Ollama (Optional but Recommended)

Ollama provides free local LLM processing for Tier 2. Without it, the system falls back to Rules → Claude (still ~70% savings).

**Option 1: Ollama Home Assistant Add-on**
1. Search "Ollama" in the add-on store
2. Install and start
3. Set `ollama_url` to `http://homeassistant.local:11434`

**Option 2: External Ollama Server**
1. Install on any machine with 8GB+ RAM:
   ```bash
   curl -fsSL https://ollama.com/install.sh | sh
   ollama pull llama3.2:3b
   ```
2. Set `ollama_url` to `http://YOUR_SERVER_IP:11434`

**Recommended Models:**
| Model | RAM Needed | Speed | Quality |
|-------|------------|-------|---------|
| `llama3.2:3b` | 4GB | Fast | Good |
| `llama3.2:1b` | 2GB | Fastest | Basic |
| `mistral:7b` | 8GB | Medium | Better |
| `phi3:mini` | 4GB | Fast | Good |

## Hybrid LLM System

The agent uses a 3-tier approach to minimize Claude API costs:

```
┌─────────────────────────────────────────────────────────────┐
│  TIER 1: Rule-Based (FREE) - Handles ~70% of checks         │
│  ├── Simple patterns: overheat, freeze, orphan heater       │
│  ├── Single low/medium severity issues                      │
│  └── Escalates if: 2+ critical, 3+ patterns, complex        │
├─────────────────────────────────────────────────────────────┤
│  TIER 2: Ollama Local LLM (FREE) - Handles ~25% of checks   │
│  ├── Pattern correlation, multi-factor analysis             │
│  ├── JSON-formatted decisions                               │
│  └── Escalates if: confidence < 0.7, complex situation      │
├─────────────────────────────────────────────────────────────┤
│  TIER 3: Claude API (PAID) - Handles ~5% of checks          │
│  └── Complex reasoning, predictions, unusual situations     │
└─────────────────────────────────────────────────────────────┘
```

### Cost Comparison

| Mode | Daily Cost | Monthly Cost |
|------|------------|--------------|
| Claude-only | $0.50-1.00 | $15-30 |
| Hybrid (with Ollama) | $0.03-0.10 | $1-3 |
| Hybrid (no Ollama) | $0.10-0.30 | $3-9 |
| **Savings** | **90-95%** | **~$25/month** |

### Monitoring Tier Usage

Logs show which tier handled each analysis:
```
INFO: Analysis handled by RULE_BASED (confidence: 0.90, cost: $0.0000)
INFO: Analysis handled by LOCAL (confidence: 0.85, cost: $0.0000)
INFO: Analysis handled by CLAUDE (confidence: 0.95, cost: $0.0150)
INFO: LLM Stats: Rule-based: 72.3%, Local: 23.1%, Claude: 4.6%
```

Daily summary notifications include tier breakdown.

## How It Works

### Decision Cycle

Every 5 minutes (configurable), the agent:

1. **Collects State**: Gets current state of all pool entities
2. **Analyzes Patterns**: Runs local anomaly detection
3. **Hybrid LLM Analysis** (if needed):
   - Tier 1: Try rule-based decision
   - Tier 2: Try local Ollama if rules escalate
   - Tier 3: Fall back to Claude if local escalates
4. **Executes Actions**: Carries out recommendations with safety validation
5. **Logs Everything**: Stores decisions in SQLite database

### Safety Rules

The agent will NEVER:
- Enable heating if sensor failure is detected
- Start operations while sequence lock is active
- Control valves if Z-Wave is unavailable
- Allow water temperature above 105°F or below 40°F
- Run heater without pump confirmed running

### Pattern Detection

Local analysis detects:
- **Temperature Anomalies**: Rapid drops, overheating, freezing
- **Valve Mismatches**: Positions don't match active mode
- **Pump Issues**: Running but no sound, or not running when needed
- **Mode Conflicts**: Multiple incompatible modes active
- **Runtime Anomalies**: Low circulation compared to schedule

### Actions the Agent Can Take

| Action | When Used |
|--------|-----------|
| Start/Stop hot_tub_heat | Preheating for evening, responding to issues |
| Start/Stop pool_heat | Temperature optimization |
| Adjust heater temperature | Fine-tuning setpoints |
| Emergency stop | Critical safety issues |
| Force restart mode | Recovering from stuck states |
| Send notifications | Informing user of actions |

## Monitoring

### Notifications

The agent sends notifications for:
- Startup/shutdown
- Any action taken
- Daily summary (at 2 AM) including tier usage stats
- Errors or warnings

### Database

Decision history stored in `/config/pool_ai_agent/agent.db`:
- `state_snapshots`: Historical state data
- `decisions`: All LLM decisions (with tier_used field)
- `actions`: Action execution results
- `daily_stats`: Usage statistics

### Logs

View logs in HA add-on interface or:
```bash
docker logs addon_local_pool_ai_agent
```

## Troubleshooting

### Agent Not Starting

1. Check API key is configured
2. Verify HA API is accessible
3. Check logs for error messages

### No Decisions Being Made

This is normal! The agent only calls LLMs when:
- Anomalies are detected
- Optimization opportunities exist
- Multiple patterns need holistic analysis

Normal operation = quiet agent.

### Ollama Not Available

If you see "Ollama not available" in logs:
1. Check Ollama is running: `curl http://YOUR_OLLAMA_URL/api/tags`
2. Verify model is pulled: `ollama list`
3. Check network connectivity between HA and Ollama server

The system will gracefully fall back to Rules → Claude (still ~70% savings).

### Actions Not Executing

Check if safety rules are blocking:
- Is sensor failure flag on?
- Is sequence lock active?
- Are Z-Wave devices unavailable?

### Unexpected Claude API Costs

If Claude is being called more than expected:
1. Check logs for escalation reasons
2. Ensure Ollama is properly configured and running
3. Review patterns - frequent high-severity issues will escalate
4. Consider tuning thresholds in `hybrid_llm.py`

## Files

```
/config/addons/pool-ai-agent/
├── Dockerfile              # Container build
├── config.yaml             # Add-on manifest
├── run.sh                  # Entry point
├── requirements.txt        # Python dependencies
├── DOCS.md                 # This file
└── src/
    ├── main.py             # Daemon loop
    ├── ha_client.py        # HA API client
    ├── claude_client.py    # Claude API client
    ├── hybrid_llm.py       # 3-tier hybrid LLM manager
    ├── state_monitor.py    # Entity monitoring
    ├── pattern_analyzer.py # Local analysis
    ├── decision_engine.py  # Orchestration
    ├── action_executor.py  # Action execution
    ├── database.py         # SQLite storage
    └── prompts/
        └── system.py       # Claude system prompt
```

## Integration with Existing Automations

The agent complements your existing pool automations:
- It does NOT replace your automations
- It calls the same scripts (emergency_stop, force_restart, etc.)
- It respects the same safety flags (sequence_lock, sensor_failure)
- It provides an additional layer of intelligent oversight

## Support

For issues or feature requests, check the Home Assistant logs and database for diagnostic information.
