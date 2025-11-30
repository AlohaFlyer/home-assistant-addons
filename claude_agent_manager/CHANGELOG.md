# Changelog

## [1.0.0] - 2025-11-29

### Added
- Initial release
- 3-tier hybrid LLM system (Rule-based → Ollama → Claude)
- 4 monitoring agents: Pool, Lights, Security, Climate
- Confirm-critical mode for major actions
- Automatic minor issue fixes
- LLM usage statistics
- Persistent notifications for pending actions

### Agents
- **Pool Agent**: Temperature, pump, valves, heating modes, Z-Wave health
- **Lights Agent**: Daylight detection, late-night lights, pool area lights
- **Security Agent**: Locks, doors, cameras, alarm status
- **Climate Agent**: Temperature range, HVAC, humidity

### Hybrid LLM
- Tier 1: Rule-based (70% of decisions) - FREE
- Tier 2: Ollama local (25% of decisions) - FREE
- Tier 3: Claude API (5% of decisions) - PAID, optional
