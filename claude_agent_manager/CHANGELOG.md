# Changelog

## [1.0.6] - 2025-12-02

### Changed
- Updated default Ollama model from `llama3.2:1b` to `qwen2.5:3b`
- Qwen 2.5 3B provides better reasoning for home automation tasks

## [1.0.5] - 2025-11-30

### Added - Startup Sequence Monitoring
Pool agent now monitors valve actuation timing during mode startup sequences:

**Timing Limits:**
- **Valve actuation**: 60 seconds max (Jandy valves take ~40s)
- **24VAC power**: 120 seconds max (should turn off after valves positioned)
- **Sequence lock**: 300 seconds max (5 minutes for full startup)

**New Issue Types:**
- `STARTUP_TIMEOUT` - Startup sequence taking too long (>5 min)
- `STARTUP_ISSUE` - 24VAC power stuck ON too long (>2 min)
- `VALVE_STUCK` - Individual valve switch ON too long (>60s)
- `VALVE_SWITCH_ON` - Valve switches ON during steady-state (should be OFF)

**New Auto-Fix Rules (Whitelisted):**
13. **Clear Startup Timeout** - Clears `pool_sequence_lock` when startup times out
14. **Turn Off 24VAC** - Turns off 24VAC power when stuck ON (protects valve motors)
15. **Turn Off Stuck Valve** - Turns off all valve switches when one is stuck
16. **Turn Off Orphan Switches** - Turns off valve switches during steady-state

### Changed
- Pool agent tracks state transitions to detect when valves turn ON/OFF
- Logs valve actuation timing for debugging
- Validates valve switches are OFF after startup completes

## [1.0.4] - 2025-11-30

### Fixed - Program Expected States
Corrected expected states based on actual automation behavior:

1. **`pool_action` is OFF during steady-state** - Only ON during startup phase, turned OFF after startup completes (line 1257 in valve executor, line 3610-3612 in hot_tub_heat_start)

2. **`skimmer_position_tracker` is OFF for hot_tub_heat** - Hot tub heat sets ALL pool-side trackers to OFF including skimmer (line 3300, 3343 in hot_tub_heat_start)

3. **Climate entity uses thermostat cycling** - The `climate.pool_heater_wifi` entity manages temperature cycling internally. `hvac_action` can be `heating` OR `idle` - both are valid when climate state is `heat`

### Changed
- All 6 modes now correctly expect `pool_action: "off"` in steady-state
- `hot_tub_heat` correctly expects `skimmer_position_tracker: "off"`
- Added explanatory comments in PROGRAM_EXPECTED_STATES

## [1.0.3] - 2025-11-29

### Added - Program Validation & Mode Timeout
Pool agent now validates that active modes have correct equipment states:

**7 Pool Modes Validated:**
1. **Hot Tub Heat** - Spa valves, pump ON, heater ON at 102°F
2. **Pool Heat** - Pool valves, pump ON, heater ON at 81°F (requires pool_heat_allow)
3. **Pool Skimmer** - Pool valves, pump ON, heater OFF
4. **Pool Waterfall** - Pool suction + spa return, pump ON, heater OFF
5. **Pool Vacuum** - Pool valves + vacuum position, pump ON, heater OFF
6. **Hot Tub Empty** - Spa suction + pool return, pump ON (MAX 6 MINUTES)
7. **No Mode** - All modes OFF, pump OFF, heater OFF

**New Auto-Fix Rules (Whitelisted):**
11. **Program Mismatch Fix** - Calls `script.pool_system_force_restart_current_mode` to correct equipment states
12. **Mode Timeout Stop** - Turns off `hot_tub_empty` after 6 minute timeout

### Changed
- Pool agent checks every 5 minutes for program validation
- Mode start times tracked for timeout detection
- Valve trackers validated against 3 Jandy valve pairs (mutually exclusive positions)

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
