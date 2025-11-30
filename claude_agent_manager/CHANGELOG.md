# Changelog

## [1.0.2] - 2025-11-29

### Added - Pool Agent Auto-Fix Whitelist
User-approved automatic fixes (no confirmation required):

1. **Emergency Overheat Stop** - Runs `pool_emergency_all_stop` when temp >105°F
2. **Stop Heating Wrong Valves** - Turns off heating if valve trackers show drainage risk
3. **Pump ON During Heating** - Turns pump ON if heating active but pump OFF
4. **Clear Stuck Sequence Lock** - Clears `pool_sequence_lock` when stuck with no mode active
5. **Clear Stuck Action Flag** - Clears `pool_action` when stuck with no mode active
6. **Resolve Mode Conflict** - Turns off waterfall when both skimmer+waterfall active
7. **Pump OFF Orphan** - Turns off pump during quiet hours (6PM-8AM) if no mode active
8. **Sync Valve Trackers** - Runs `pool_valve_tracker_sync_to_mode` on tracker mismatch
9. **Z-Wave Recovery** - Reloads Z-Wave integration when 3+ valves unavailable
10. **Z-Wave Ping** - Pings Z-Wave valves when 1-2 unavailable

### Changed
- Pool agent now has comprehensive auto-fix capabilities
- All auto-fixes logged to HA logbook
- Improved issue detection messages with more context

## [1.0.1] - 2025-11-29

### Fixed
- HA_URL now correctly set to `http://supervisor/core` for Supervisor API access
- Previously was reading undefined config option causing `null` URL

### Changed
- Renamed add-on to "AI Agent Manager - NV"

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
