"""
Pool Agent - Monitors pool/hot tub system
Version 1.0.2 - Added comprehensive auto-fix capabilities
"""

import logging
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple
from .base import BaseAgent, AgentCheck

logger = logging.getLogger(__name__)


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

    async def get_monitored_entities(self) -> List[str]:
        return self.monitored_entities

    async def check(self) -> AgentCheck:
        """Perform pool system health check"""
        states = await self.get_states(self.monitored_entities)
        issues = []

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
                "stop_heating_wrong_valves"
            ]
        }
