# Hybrid Agent Manager

Multi-agent home automation manager using a 3-tier hybrid LLM system: Ollama (local) as primary, Claude API as fallback for complex decisions.

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  TIER 1: Rule-Based (FREE) - ~70% of decisions              │
│  ├── Simple patterns: overheat, pump issues, lights on      │
│  └── Instant response, no LLM calls                         │
├─────────────────────────────────────────────────────────────┤
│  TIER 2: Ollama Local (FREE) - ~25% of decisions            │
│  ├── Pattern analysis, correlations, moderate complexity    │
│  └── Runs on your Yellow (llama3.2:1b recommended)          │
├─────────────────────────────────────────────────────────────┤
│  TIER 3: Claude API (PAID) - ~5% of decisions               │
│  └── Complex multi-system reasoning, unusual situations     │
│  └── Only called when Tier 2 confidence < 0.7               │
└─────────────────────────────────────────────────────────────┘
```

## Agents

### Pool Agent
Monitors your pool/hot tub system:
- Temperature sensor health
- Pump status during heating
- Valve positions and Z-Wave availability
- Sequence lock status
- Off-hours pump activity

**Critical rules (Tier 1):**
- Emergency shutdown if temp > 105°F
- Block heating if sensor failure detected
- Turn on pump if heating mode active but pump OFF

### Lights Agent
Monitors lighting:
- Exterior lights on during daylight
- All lights after 2 AM
- Pool/hot tub lights during day

### Security Agent
Monitors security:
- Locks at night
- Doors left open
- Camera availability
- Alarm status

### Climate Agent
Monitors indoor climate:
- Temperature range (68-76°F)
- HVAC availability
- Humidity levels

## Configuration

| Option | Description | Default |
|--------|-------------|---------|
| `ollama_url` | Ollama API URL | `http://76e18fb5-ollama:11434` |
| `ollama_model` | Ollama model to use | `llama3.2:1b` |
| `claude_api_key` | Optional Claude API key | (empty) |
| `claude_model` | Claude model for Tier 3 | `claude-sonnet-4-20250514` |
| `check_interval_minutes` | How often to run checks | `5` |
| `escalation_confidence_threshold` | Tier 2→3 threshold | `0.7` |
| `confirm_critical_actions` | Require user OK for critical actions | `true` |
| `agents_enabled` | Which agents to run | `pool,lights,security,climate` |

## Confirm-Critical Mode

When `confirm_critical_actions` is enabled:
- **Minor issues** (lights on during day) → Auto-fixed immediately
- **Critical issues** (emergency shutdowns) → Still auto-fixed (safety first)
- **Major actions** (mode changes, complex fixes) → Queued for user confirmation

You'll receive a persistent notification asking you to confirm or reject the action.

## Recommended Ollama Models for Pi CM4

The Yellow has limited RAM. Recommended models:

| Model | Size | Speed | Quality |
|-------|------|-------|---------|
| `llama3.2:1b` | 1.3GB | Fast | Good for simple tasks |
| `phi3:mini` | 2.3GB | Medium | Better reasoning |
| `llama3.2:3b` | 2GB | Slow | Best quality |

To change the model:
1. Go to Ollama add-on terminal
2. Run: `ollama pull llama3.2:1b`
3. Update this add-on's config

## Logs

View logs via:
- Settings → Add-ons → Hybrid Agent Manager → Log

The manager logs:
- Each monitoring cycle with agent summaries
- Actions taken (with Tier that made the decision)
- LLM usage statistics (every 10 cycles)
- Errors and failures

## Troubleshooting

### Ollama not responding
1. Check Ollama add-on is running
2. Verify the URL in config matches your Ollama instance
3. Try pulling the model again: `ollama pull llama3.2:1b`

### No actions being taken
1. Check the logs for errors
2. Verify agents_enabled includes your agents
3. Check if issues are being detected (log shows "0 issues" for each agent)

### Too many Tier 3 (Claude) calls
1. Lower `escalation_confidence_threshold` (e.g., 0.5)
2. Use a larger Ollama model for better confidence
3. Check if Ollama is responding properly

### Actions stuck pending
1. Check persistent notifications for confirmation requests
2. View pending actions in the logs
3. Pending actions expire after 1 hour
