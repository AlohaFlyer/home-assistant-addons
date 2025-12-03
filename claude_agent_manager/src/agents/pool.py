"""
Pool Agent - Monitors pool/hot tub system
Version 1.0.5 - Added startup sequence monitoring
"""

import logging
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple
from .base import BaseAgent, AgentCheck

logger = logging.getLogger(__name__)


# Expected states for each pool program
# Format: { entity_id: expected_state }
PROGRAM_EXPECTED_STATES = {
    "hot_tub_heat": {
        "input_boolean.hot_tub_heat": "on",
        "switch.pool_pump_zwave": "on",
        "switch.pool_heater_wifi": "on",
        "climate.pool_heater_wifi": "heat",
        # climate temp: 102 (checked separately)
        # Valve trackers for spa heating: spa ON, pool OFF, skimmer OFF (per automation line 3343)
        "input_boolean.pool_valve_spa_suction_position_tracker": "on",
        "input_boolean.pool_valve_pool_suction_position_tracker": "off",
        "input_boolean.pool_valve_spa_return_position_tracker": "on",
        "input_boolean.pool_valve_pool_return_position_tracker": "off",
        "input_boolean.pool_valve_skimmer_position_tracker": "off",  # OFF for hot tub heat
        "input_boolean.pool_valve_vacuum_position_tracker": "off",
        "input_boolean.pool_sequence_lock": "off",
        "input_boolean.pool_action": "off",  # OFF after startup completes (line 3610-3612)
        "switch.pool_valve_power_24vac_zwave": "off",
    },
    "pool_heat": {
        "input_boolean.pool_heat": "on",
        "input_boolean.pool_heat_allow": "on",
        "switch.pool_pump_zwave": "on",
        "switch.pool_heater_wifi": "on",
        "climate.pool_heater_wifi": "heat",
        # climate temp: 81 (checked separately)
        # Valve trackers for pool heating: pool ON, spa OFF, skimmer ON (per automation line 5180)
        "input_boolean.pool_valve_spa_suction_position_tracker": "off",
        "input_boolean.pool_valve_pool_suction_position_tracker": "on",
        "input_boolean.pool_valve_spa_return_position_tracker": "off",
        "input_boolean.pool_valve_pool_return_position_tracker": "on",
        "input_boolean.pool_valve_skimmer_position_tracker": "on",
        "input_boolean.pool_valve_vacuum_position_tracker": "off",
        "input_boolean.pool_sequence_lock": "off",
        "input_boolean.pool_action": "off",  # OFF after startup completes
        "switch.pool_valve_power_24vac_zwave": "off",
    },
    "pool_skimmer": {
        "input_boolean.pool_skimmer": "on",
        "switch.pool_pump_zwave": "on",
        "switch.pool_heater_wifi": "off",
        "climate.pool_heater_wifi": "off",
        # Valve trackers for skimmer: pool ON, spa OFF, skimmer ON, vacuum OFF
        "input_boolean.pool_valve_spa_suction_position_tracker": "off",
        "input_boolean.pool_valve_pool_suction_position_tracker": "on",
        "input_boolean.pool_valve_spa_return_position_tracker": "off",
        "input_boolean.pool_valve_pool_return_position_tracker": "on",
        "input_boolean.pool_valve_skimmer_position_tracker": "on",
        "input_boolean.pool_valve_vacuum_position_tracker": "off",
        "input_boolean.pool_sequence_lock": "off",
        "input_boolean.pool_action": "off",  # OFF after startup completes
    },
    "pool_waterfall": {
        "input_boolean.pool_waterfall": "on",
        "switch.pool_pump_zwave": "on",
        "switch.pool_heater_wifi": "off",
        "climate.pool_heater_wifi": "off",
        # Valve trackers for waterfall: pool suction ON, spa return ON (for waterfall), skimmer ON
        "input_boolean.pool_valve_spa_suction_position_tracker": "off",
        "input_boolean.pool_valve_pool_suction_position_tracker": "on",
        "input_boolean.pool_valve_spa_return_position_tracker": "on",
        "input_boolean.pool_valve_pool_return_position_tracker": "off",
        "input_boolean.pool_valve_skimmer_position_tracker": "on",
        "input_boolean.pool_valve_vacuum_position_tracker": "off",
        "input_boolean.pool_sequence_lock": "off",
        "input_boolean.pool_action": "off",  # OFF after startup completes
    },
    "pool_vacuum": {
        "input_boolean.pool_vacuum": "on",
        "switch.pool_pump_zwave": "on",
        "switch.pool_heater_wifi": "off",
        "climate.pool_heater_wifi": "off",
        # Valve trackers for vacuum: pool ON, spa OFF, skimmer OFF (vacuum ON)
        "input_boolean.pool_valve_spa_suction_position_tracker": "off",
        "input_boolean.pool_valve_pool_suction_position_tracker": "on",
        "input_boolean.pool_valve_spa_return_position_tracker": "off",
        "input_boolean.pool_valve_pool_return_position_tracker": "on",
        "input_boolean.pool_valve_skimmer_position_tracker": "off",
        "input_boolean.pool_valve_vacuum_position_tracker": "on",
        "input_boolean.pool_sequence_lock": "off",
        "input_boolean.pool_action": "off",  # OFF after startup completes
    },
    "hot_tub_empty": {
        "input_boolean.hot_tub_empty": "on",
        "switch.pool_pump_zwave": "on",
        "switch.pool_heater_wifi": "off",
        "climate.pool_heater_wifi": "off",
        # Valve trackers for hot tub empty: spa suction ON, pool return ON (drains spa to pool)
        "input_boolean.pool_valve_spa_suction_position_tracker": "on",
        "input_boolean.pool_valve_pool_suction_position_tracker": "off",
        "input_boolean.pool_valve_spa_return_position_tracker": "off",
        "input_boolean.pool_valve_pool_return_position_tracker": "on",
        "input_boolean.pool_valve_skimmer_position_tracker": "on",
        "input_boolean.pool_valve_vacuum_position_tracker": "off",
        "input_boolean.pool_sequence_lock": "off",
        "input_boolean.pool_action": "off",  # OFF after startup completes
        # Max runtime: 6 minutes (checked separately)
    },
    "no_mode": {
        "input_boolean.hot_tub_heat": "off",
        "input_boolean.pool_heat": "off",
        "input_boolean.pool_skimmer": "off",
        "input_boolean.pool_waterfall": "off",
        "input_boolean.pool_vacuum": "off",
        "input_boolean.hot_tub_empty": "off",
        "switch.pool_pump_zwave": "off",
        "switch.pool_heater_wifi": "off",
        "climate.pool_heater_wifi": "off",
        "input_boolean.pool_sequence_lock": "off",
        "input_boolean.pool_action": "off",
    },
}

# Climate temperature targets per mode
CLIMATE_TEMP_TARGETS = {
    "hot_tub_heat": 102,
    "pool_heat": 81,
}

# Mode timeout limits (in minutes)
MODE_TIMEOUT_MINUTES = {
    "hot_tub_empty": 6,
}

# Startup sequence timing limits (in seconds)
STARTUP_TIMING = {
    "valve_actuation_max": 60,      # Jandy valve takes ~40s, allow 60s max
    "24vac_power_max": 120,         # 24VAC should be off within 2 minutes of startup
    "sequence_lock_max": 300,       # Full startup should complete within 5 minutes
}

# Valve switches that should be OFF during steady-state operation
VALVE_SWITCHES = [
    "switch.pool_valve_power_24vac_zwave",
    "switch.pool_valve_spa_suction_zwave",
    "switch.pool_valve_spa_return_zwave",
    "switch.pool_valve_pool_suction_zwave",
    "switch.pool_valve_pool_return_zwave",
    "switch.pool_valve_skimmer_zwave",
    "switch.pool_valve_vacuum_zwave",
]


class PoolAgent(BaseAgent):
    """Monitors pool and hot tub systems with auto-fix capabilities"""

    def __init__(self, ha_client):
        super().__init__("pool", ha_client)

        # All monitored pool entities
        self.monitored_entities = [
            # Temperature
            "sensor.pool_heater_wifi_temperature",
            "sensor.pool_water_temperature_reliable",

            # Pump
            "switch.pool_pump_zwave",

            # Heater
            "switch.pool_heater_wifi",
            "climate.pool_heater_wifi",

            # Mode toggles
            "input_boolean.hot_tub_heat",
            "input_boolean.pool_heat",
            "input_boolean.pool_heat_allow",
            "input_boolean.pool_skimmer",
            "input_boolean.pool_waterfall",
            "input_boolean.pool_vacuum",
            "input_boolean.hot_tub_empty",

            # System flags
            "input_boolean.pool_action",
            "input_boolean.pool_sequence_lock",
            "input_boolean.pool_sensor_failure_detected",

            # Valves (Z-Wave)
            "switch.pool_valve_power_24vac_zwave",
            "switch.pool_valve_spa_suction_zwave",
            "switch.pool_valve_spa_return_zwave",
            "switch.pool_valve_pool_suction_zwave",
            "switch.pool_valve_pool_return_zwave",
            "switch.pool_valve_skimmer_zwave",
            "switch.pool_valve_vacuum_zwave",

            # Valve position trackers
            "input_boolean.pool_valve_spa_suction_position_tracker",
            "input_boolean.pool_valve_spa_return_position_tracker",
            "input_boolean.pool_valve_pool_suction_position_tracker",
            "input_boolean.pool_valve_pool_return_position_tracker",
            "input_boolean.pool_valve_skimmer_position_tracker",
            "input_boolean.pool_valve_vacuum_position_tracker",

            # Lights
            "switch.light_pool_zwave",
            "switch.light_hot_tub_zwave",

            # Bubbler
            "switch.pool_hot_tub_bubbler_zwave",
        ]

        # Z-Wave valve entities for availability checks
        self.zwave_valves = [
            'switch.pool_valve_power_24vac_zwave',
            'switch.pool_valve_spa_suction_zwave',
            'switch.pool_valve_spa_return_zwave',
            'switch.pool_valve_pool_suction_zwave',
            'switch.pool_valve_pool_return_zwave',
            'switch.pool_valve_skimmer_zwave',
            'switch.pool_valve_vacuum_zwave'
        ]

        # Track mode start times for timeout detection
        self.mode_start_times: Dict[str, datetime] = {}

        # Track startup sequence state
        self.startup_tracking: Dict[str, Any] = {
            "sequence_lock_start": None,      # When sequence_lock turned ON
            "24vac_on_start": None,           # When 24VAC turned ON
            "valve_switch_on_times": {},      # When each valve switch turned ON
            "last_sequence_lock_state": None, # Previous sequence_lock state
            "last_24vac_state": None,         # Previous 24VAC state
            "last_valve_states": {},          # Previous valve switch states
        }

    async def get_monitored_entities(self) -> List[str]:
        return self.monitored_entities

    def _get_active_mode(self, states: Dict[str, Any]) -> Optional[str]:
        """Determine which mode is currently active, if any"""
        mode_entities = {
            "hot_tub_heat": "input_boolean.hot_tub_heat",
            "pool_heat": "input_boolean.pool_heat",
            "pool_skimmer": "input_boolean.pool_skimmer",
            "pool_waterfall": "input_boolean.pool_waterfall",
            "pool_vacuum": "input_boolean.pool_vacuum",
            "hot_tub_empty": "input_boolean.hot_tub_empty",
        }

        for mode, entity in mode_entities.items():
            if states.get(entity) == 'on':
                return mode

        return None

    def _validate_program(self, mode: str, states: Dict[str, Any]) -> List[str]:
        """Validate that current states match expected states for the active mode"""
        mismatches = []

        if mode not in PROGRAM_EXPECTED_STATES:
            return mismatches

        expected = PROGRAM_EXPECTED_STATES[mode]

        for entity, expected_state in expected.items():
            actual_state = states.get(entity)

            # Skip if entity is unavailable (separate check handles this)
            if actual_state in ['unavailable', 'unknown', None]:
                continue

            if actual_state != expected_state:
                mismatches.append(f"{entity}: expected '{expected_state}', got '{actual_state}'")

        return mismatches

    def _check_mode_timeout(self, mode: str) -> bool:
        """Check if a mode has exceeded its timeout limit"""
        if mode not in MODE_TIMEOUT_MINUTES:
            return False

        if mode not in self.mode_start_times:
            # First time seeing this mode active, record start time
            self.mode_start_times[mode] = datetime.now()
            return False

        elapsed = (datetime.now() - self.mode_start_times[mode]).total_seconds() / 60
        return elapsed > MODE_TIMEOUT_MINUTES[mode]

    def _clear_mode_start_time(self, mode: str):
        """Clear the start time when a mode is no longer active"""
        if mode in self.mode_start_times:
            del self.mode_start_times[mode]

    def _check_startup_sequence(self, states: Dict[str, Any]) -> List[str]:
        """
        Monitor startup sequence timing and valve actuation.
        Returns list of issues found during startup monitoring.
        """
        issues = []
        now = datetime.now()

        sequence_lock = states.get('input_boolean.pool_sequence_lock')
        power_24vac = states.get('switch.pool_valve_power_24vac_zwave')

        # Track sequence_lock state changes
        if sequence_lock == 'on' and self.startup_tracking["last_sequence_lock_state"] != 'on':
            # Sequence lock just turned ON - startup beginning
            self.startup_tracking["sequence_lock_start"] = now
            logger.info("Startup sequence detected - sequence_lock turned ON")
        elif sequence_lock == 'off' and self.startup_tracking["last_sequence_lock_state"] == 'on':
            # Sequence lock just turned OFF - startup completed
            if self.startup_tracking["sequence_lock_start"]:
                duration = (now - self.startup_tracking["sequence_lock_start"]).total_seconds()
                logger.info(f"Startup sequence completed in {duration:.1f} seconds")
            # Reset tracking
            self.startup_tracking["sequence_lock_start"] = None
            self.startup_tracking["24vac_on_start"] = None
            self.startup_tracking["valve_switch_on_times"] = {}

        self.startup_tracking["last_sequence_lock_state"] = sequence_lock

        # Track 24VAC power state changes
        if power_24vac == 'on' and self.startup_tracking["last_24vac_state"] != 'on':
            # 24VAC just turned ON
            self.startup_tracking["24vac_on_start"] = now
            logger.info("24VAC power turned ON for valve actuation")
        elif power_24vac == 'off' and self.startup_tracking["last_24vac_state"] == 'on':
            # 24VAC just turned OFF
            if self.startup_tracking["24vac_on_start"]:
                duration = (now - self.startup_tracking["24vac_on_start"]).total_seconds()
                logger.info(f"24VAC power turned OFF after {duration:.1f} seconds")
            self.startup_tracking["24vac_on_start"] = None

        self.startup_tracking["last_24vac_state"] = power_24vac

        # Track individual valve switch state changes
        for valve in VALVE_SWITCHES:
            if valve == "switch.pool_valve_power_24vac_zwave":
                continue  # Already tracked above

            current_state = states.get(valve)
            last_state = self.startup_tracking["last_valve_states"].get(valve)

            if current_state == 'on' and last_state != 'on':
                # Valve switch just turned ON - only track if 24VAC is powered (actually actuating)
                valve_name = valve.split('.')[-1].replace('_zwave', '')
                if power_24vac == 'on':
                    self.startup_tracking["valve_switch_on_times"][valve] = now
                    logger.info(f"Valve {valve_name} ACTUATING (24VAC powered)")
                else:
                    logger.info(f"Valve {valve_name} position set (24VAC off - not actuating)")
            elif current_state == 'off' and last_state == 'on':
                # Valve switch just turned OFF
                if valve in self.startup_tracking["valve_switch_on_times"]:
                    duration = (now - self.startup_tracking["valve_switch_on_times"][valve]).total_seconds()
                    valve_name = valve.split('.')[-1].replace('_zwave', '')
                    logger.info(f"Valve switch {valve_name} turned OFF after {duration:.1f} seconds")
                    del self.startup_tracking["valve_switch_on_times"][valve]

            self.startup_tracking["last_valve_states"][valve] = current_state

        # Check for timing violations during active startup
        if sequence_lock == 'on' and self.startup_tracking["sequence_lock_start"]:
            lock_duration = (now - self.startup_tracking["sequence_lock_start"]).total_seconds()
            if lock_duration > STARTUP_TIMING["sequence_lock_max"]:
                issues.append(f"STARTUP_TIMEOUT: Sequence lock has been ON for {lock_duration:.0f}s (max {STARTUP_TIMING['sequence_lock_max']}s) - startup may be stuck")

        # Check 24VAC power timeout
        if power_24vac == 'on' and self.startup_tracking["24vac_on_start"]:
            power_duration = (now - self.startup_tracking["24vac_on_start"]).total_seconds()
            if power_duration > STARTUP_TIMING["24vac_power_max"]:
                issues.append(f"STARTUP_ISSUE: 24VAC power has been ON for {power_duration:.0f}s (max {STARTUP_TIMING['24vac_power_max']}s) - may damage valve motors")

        # Check individual valve switch timeouts
        for valve, on_time in list(self.startup_tracking["valve_switch_on_times"].items()):
            valve_duration = (now - on_time).total_seconds()
            if valve_duration > STARTUP_TIMING["valve_actuation_max"]:
                valve_name = valve.split('.')[-1].replace('_zwave', '')
                issues.append(f"VALVE_STUCK: {valve_name} switch has been ON for {valve_duration:.0f}s (max {STARTUP_TIMING['valve_actuation_max']}s) - valve may be stuck or Z-Wave command failed")

        return issues

    def _check_steady_state_valves(self, states: Dict[str, Any]) -> List[str]:
        """
        During steady-state operation (no startup in progress),
        24VAC power should be OFF. Valve direction switches stay ON to indicate
        position - they are depowered by turning off 24VAC, not by turning off
        the direction switches.
        """
        issues = []
        sequence_lock = states.get('input_boolean.pool_sequence_lock')
        power_24vac = states.get('switch.pool_valve_power_24vac_zwave')

        # Only check if NOT in startup sequence
        if sequence_lock == 'on':
            return issues  # Startup in progress, 24VAC may legitimately be ON

        # The only issue is if 24VAC is ON during steady-state (no startup)
        # Valve direction switches being ON is NORMAL - they indicate position
        if power_24vac == 'on':
            issues.append(f"24VAC_ON_STEADY_STATE: 24VAC power is ON but no startup in progress - valves may be actuating unnecessarily")

        return issues

    async def check(self) -> AgentCheck:
        """Perform pool system health check"""
        states = await self.get_states(self.monitored_entities)
        issues = []

        # Determine active mode
        active_mode = self._get_active_mode(states)

        # Clear start times for modes that are no longer active
        for mode in list(self.mode_start_times.keys()):
            if mode != active_mode:
                self._clear_mode_start_time(mode)

        # Check for sensor failure
        sensor_failure = states.get('input_boolean.pool_sensor_failure_detected')
        if sensor_failure == 'on':
            issues.append("CRITICAL: Temperature sensor failure detected")

        # Check temperature sensor availability
        temp = states.get('sensor.pool_heater_wifi_temperature')
        if temp in ['unavailable', 'unknown', None]:
            issues.append("WARNING: Temperature sensor unavailable")

        # Check for overheat
        if temp and temp not in ['unavailable', 'unknown']:
            try:
                temp_f = float(temp)
                if temp_f > 105:
                    issues.append(f"CRITICAL: Overheat detected ({temp_f}°F)")
                elif temp_f > 103:
                    issues.append(f"WARNING: Temperature high ({temp_f}°F)")
                elif temp_f < 40:
                    issues.append(f"WARNING: Temperature very low ({temp_f}°F) - possible sensor issue")
            except (ValueError, TypeError):
                pass

        # Check heating mode + pump status
        hot_tub_heat = states.get('input_boolean.hot_tub_heat')
        pool_heat = states.get('input_boolean.pool_heat')
        pump = states.get('switch.pool_pump_zwave')

        if (hot_tub_heat == 'on' or pool_heat == 'on') and pump == 'off':
            issues.append("CRITICAL: Heating mode active but pump is OFF")

        if (hot_tub_heat == 'on' or pool_heat == 'on') and pump == 'unavailable':
            issues.append("CRITICAL: Pump unavailable during heating mode")

        # Check for stuck sequence lock
        sequence_lock = states.get('input_boolean.pool_sequence_lock')
        pool_action = states.get('input_boolean.pool_action')
        any_mode_active = self._any_mode_active(states)

        if sequence_lock == 'on' and not any_mode_active:
            issues.append("WARNING: Sequence lock stuck ON (no mode active)")

        # Check for stuck pool_action flag
        if pool_action == 'on' and not any_mode_active:
            issues.append("WARNING: Pool action flag stuck ON (no mode active)")

        # Check Z-Wave valve availability
        unavailable_valves = [v for v in self.zwave_valves if states.get(v) == 'unavailable']
        if len(unavailable_valves) >= 3:
            issues.append(f"CRITICAL: {len(unavailable_valves)} Z-Wave valves unavailable - Z-Wave issue")
        elif unavailable_valves:
            issues.append(f"WARNING: {len(unavailable_valves)} Z-Wave valve(s) unavailable: {', '.join([v.split('.')[-1] for v in unavailable_valves])}")

        # Check valve tracker mismatches during heating
        if hot_tub_heat == 'on':
            spa_suction_tracker = states.get('input_boolean.pool_valve_spa_suction_position_tracker')
            spa_return_tracker = states.get('input_boolean.pool_valve_spa_return_position_tracker')
            if spa_suction_tracker == 'off' or spa_return_tracker == 'off':
                issues.append("CRITICAL: Hot tub heat ON but valve trackers show WRONG position (drainage risk)")

        if pool_heat == 'on':
            pool_suction_tracker = states.get('input_boolean.pool_valve_pool_suction_position_tracker')
            pool_return_tracker = states.get('input_boolean.pool_valve_pool_return_position_tracker')
            if pool_suction_tracker == 'off' or pool_return_tracker == 'off':
                issues.append("WARNING: Pool heat ON but valve trackers may be wrong")

        # Check for mutual exclusion violations
        skimmer = states.get('input_boolean.pool_skimmer')
        waterfall = states.get('input_boolean.pool_waterfall')
        if skimmer == 'on' and waterfall == 'on':
            issues.append("WARNING: Both skimmer and waterfall active (conflict)")

        # Check off-hours pump (6 PM - 8 AM)
        current_hour = datetime.now().hour
        is_quiet_hours = current_hour >= 18 or current_hour < 8

        if is_quiet_hours and pump == 'on' and not any_mode_active:
            issues.append("WARNING: Pump running during quiet hours with no mode active (orphan pump)")

        # ========== STARTUP SEQUENCE MONITORING ==========
        # Monitor valve actuation timing during startup sequences
        startup_issues = self._check_startup_sequence(states)
        issues.extend(startup_issues)

        # Check valve switches are OFF during steady-state
        steady_state_issues = self._check_steady_state_valves(states)
        issues.extend(steady_state_issues)

        # ========== PROGRAM VALIDATION ==========
        # Validate that active mode has correct states
        if active_mode:
            mismatches = self._validate_program(active_mode, states)
            if mismatches:
                issues.append(f"PROGRAM_MISMATCH: {active_mode} has incorrect states: {'; '.join(mismatches)}")

            # Check mode timeout (e.g., hot_tub_empty > 6 minutes)
            if self._check_mode_timeout(active_mode):
                timeout_mins = MODE_TIMEOUT_MINUTES.get(active_mode, 0)
                issues.append(f"MODE_TIMEOUT: {active_mode} has been running longer than {timeout_mins} minutes")
        else:
            # No mode active - validate "no_mode" state
            mismatches = self._validate_program("no_mode", states)
            # Filter out pump mismatch during scheduled hours (8 AM - 6 PM) - pump may legitimately be off
            # Only flag if heater or action flags are wrong when no mode is active
            critical_mismatches = [m for m in mismatches if 'pool_heater' in m or 'pool_action' in m or 'pool_sequence_lock' in m]
            if critical_mismatches:
                issues.append(f"NO_MODE_MISMATCH: System flags incorrect with no mode active: {'; '.join(critical_mismatches)}")

        self.last_check = AgentCheck(
            agent_name=self.name,
            issues=issues,
            states=states,
            recent_events=[],
            check_time=datetime.now().isoformat()
        )

        return self.last_check

    def _any_mode_active(self, states: Dict[str, Any]) -> bool:
        """Check if any pool mode is currently active"""
        return any([
            states.get('input_boolean.hot_tub_heat') == 'on',
            states.get('input_boolean.pool_heat') == 'on',
            states.get('input_boolean.pool_skimmer') == 'on',
            states.get('input_boolean.pool_waterfall') == 'on',
            states.get('input_boolean.pool_vacuum') == 'on',
            states.get('input_boolean.hot_tub_empty') == 'on'
        ])

    def get_rules(self) -> Dict[str, Any]:
        return {
            "temperature_limits": {
                "max_safe": 105,
                "max_warning": 103,
                "min_warning": 40
            },
            "heating_requires": ["pump_on", "valves_available"],
            "quiet_hours": {"start": 18, "end": 8},
            "mutual_exclusions": [
                ["pool_skimmer", "pool_waterfall"],
                ["hot_tub_heat", "pool_heat"]
            ],
            "mode_timeouts": MODE_TIMEOUT_MINUTES,
            "climate_temp_targets": CLIMATE_TEMP_TARGETS,
            "auto_fix_whitelist": [
                "clear_stuck_sequence_lock",
                "clear_stuck_action_flag",
                "sync_valve_trackers",
                "resolve_mode_conflict",
                "pump_on_during_heating",
                "pump_off_orphan",
                "force_restart_mode",
                "zwave_recovery",
                "emergency_overheat_stop",
                "stop_heating_wrong_valves",
                "program_mismatch_restart",
                "mode_timeout_stop"
            ]
        }
