"""State monitor for collecting pool entity states."""

import logging
from typing import Optional
from dataclasses import dataclass, field
from datetime import datetime

from .ha_client import HAClient, EntityState

logger = logging.getLogger(__name__)


# Pool entities to monitor
POOL_ENTITIES = {
    # Equipment switches
    "switches": [
        "switch.pool_pump_zwave",
        "switch.pool_heater_wifi",
        "switch.pool_hot_tub_bubbler_zwave",
        "switch.light_pool_zwave",
        "switch.light_hot_tub_zwave",
    ],
    # Valve switches
    "valves": [
        "switch.pool_valve_spa_suction_zwave",
        "switch.pool_valve_spa_return_zwave",
        "switch.pool_valve_pool_suction_zwave",
        "switch.pool_valve_pool_return_zwave",
        "switch.pool_valve_skimmer_zwave",
        "switch.pool_valve_vacuum_zwave",
        "switch.pool_valve_power_24vac_zwave",
    ],
    # Sensors
    "sensors": [
        "sensor.pool_water_temperature_reliable",
        "sensor.pool_heater_wifi_temperature",
        "sensor.pool_area_sound_pressure",
    ],
    # Climate
    "climate": [
        "climate.pool_heater_wifi",
    ],
    # Mode controls
    "modes": [
        "input_boolean.hot_tub_heat",
        "input_boolean.pool_heat",
        "input_boolean.pool_skimmer",
        "input_boolean.pool_waterfall",
        "input_boolean.pool_vacuum",
        "input_boolean.hot_tub_empty",
    ],
    # System flags
    "flags": [
        "input_boolean.pool_action",
        "input_boolean.pool_sequence_lock",
        "input_boolean.pool_sensor_failure_detected",
        "input_boolean.pool_system_health_ok",
    ],
    # Position trackers
    "trackers": [
        "input_boolean.pool_valve_spa_suction_position_tracker",
        "input_boolean.pool_valve_spa_return_position_tracker",
        "input_boolean.pool_valve_pool_suction_position_tracker",
        "input_boolean.pool_valve_pool_return_position_tracker",
        "input_boolean.pool_valve_skimmer_position_tracker",
        "input_boolean.pool_valve_vacuum_position_tracker",
    ],
    # Runtime tracking
    "runtime": [
        "input_number.pool_pump_runtime_today",
        "input_number.pool_pump_runtime_this_week",
    ],
}


@dataclass
class PoolSystemState:
    """Complete snapshot of the pool system state."""
    timestamp: str
    pump_on: bool = False
    heater_on: bool = False
    heater_hvac_mode: str = "off"
    heater_target_temp: float = 0.0
    heater_current_action: str = "idle"
    water_temp: Optional[float] = None
    outdoor_temp: Optional[float] = None
    pump_sound_level: Optional[float] = None

    # Active mode
    active_mode: str = "none"  # hot_tub_heat, pool_heat, pool_skimmer, pool_waterfall, pool_vacuum, none

    # Mode states
    hot_tub_heat: bool = False
    pool_heat: bool = False
    pool_skimmer: bool = False
    pool_waterfall: bool = False
    pool_vacuum: bool = False
    hot_tub_empty: bool = False

    # System flags
    pool_action: bool = False
    sequence_lock: bool = False
    sensor_failure: bool = False
    system_health_ok: bool = True

    # Valve positions (from trackers)
    valve_positions: dict = field(default_factory=dict)

    # Valve switch states (from Z-Wave)
    valve_switches: dict = field(default_factory=dict)

    # Runtime
    runtime_today: float = 0.0
    runtime_this_week: float = 0.0

    # Z-Wave health
    zwave_unavailable: list = field(default_factory=list)

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "timestamp": self.timestamp,
            "pump": {
                "on": self.pump_on,
                "sound_level": self.pump_sound_level,
            },
            "heater": {
                "on": self.heater_on,
                "hvac_mode": self.heater_hvac_mode,
                "target_temp": self.heater_target_temp,
                "current_action": self.heater_current_action,
            },
            "temperature": {
                "water": self.water_temp,
                "outdoor": self.outdoor_temp,
            },
            "active_mode": self.active_mode,
            "modes": {
                "hot_tub_heat": self.hot_tub_heat,
                "pool_heat": self.pool_heat,
                "pool_skimmer": self.pool_skimmer,
                "pool_waterfall": self.pool_waterfall,
                "pool_vacuum": self.pool_vacuum,
                "hot_tub_empty": self.hot_tub_empty,
            },
            "flags": {
                "pool_action": self.pool_action,
                "sequence_lock": self.sequence_lock,
                "sensor_failure": self.sensor_failure,
                "system_health_ok": self.system_health_ok,
            },
            "valve_positions": self.valve_positions,
            "valve_switches": self.valve_switches,
            "runtime": {
                "today_hours": round(self.runtime_today / 60, 2),
                "this_week_hours": round(self.runtime_this_week / 60, 2),
            },
            "zwave_unavailable": self.zwave_unavailable,
        }


class StateMonitor:
    """Monitors and collects pool system state."""

    def __init__(self, ha_client: HAClient):
        self.ha_client = ha_client
        self._last_state: Optional[PoolSystemState] = None

    def get_all_entity_ids(self) -> list[str]:
        """Get flat list of all pool entity IDs."""
        entities = []
        for category in POOL_ENTITIES.values():
            entities.extend(category)
        return entities

    async def get_current_state(self) -> PoolSystemState:
        """Collect current state of all pool entities."""
        all_entity_ids = self.get_all_entity_ids()
        states = await self.ha_client.get_states(all_entity_ids)

        state = PoolSystemState(
            timestamp=datetime.now().isoformat()
        )

        # Parse equipment switches
        pump_state = states.get("switch.pool_pump_zwave")
        if pump_state:
            state.pump_on = pump_state.state == "on"
            if pump_state.state == "unavailable":
                state.zwave_unavailable.append("switch.pool_pump_zwave")

        heater_switch = states.get("switch.pool_heater_wifi")
        if heater_switch:
            state.heater_on = heater_switch.state == "on"

        # Parse climate entity
        climate_state = states.get("climate.pool_heater_wifi")
        if climate_state:
            state.heater_hvac_mode = climate_state.state
            state.heater_target_temp = climate_state.attributes.get("temperature", 0)
            state.heater_current_action = climate_state.attributes.get("hvac_action", "idle")

        # Parse sensors
        water_temp = states.get("sensor.pool_water_temperature_reliable")
        if water_temp and water_temp.state not in ("unknown", "unavailable"):
            try:
                state.water_temp = float(water_temp.state)
            except ValueError:
                pass

        heater_temp = states.get("sensor.pool_heater_wifi_temperature")
        if heater_temp and heater_temp.state not in ("unknown", "unavailable"):
            try:
                state.water_temp = state.water_temp or float(heater_temp.state)
            except ValueError:
                pass

        sound_sensor = states.get("sensor.pool_area_sound_pressure")
        if sound_sensor and sound_sensor.state not in ("unknown", "unavailable"):
            try:
                state.pump_sound_level = float(sound_sensor.state)
            except ValueError:
                pass

        # Parse mode states
        for mode in ["hot_tub_heat", "pool_heat", "pool_skimmer", "pool_waterfall", "pool_vacuum", "hot_tub_empty"]:
            entity_state = states.get(f"input_boolean.{mode}")
            if entity_state:
                setattr(state, mode, entity_state.state == "on")

        # Determine active mode (priority order)
        if state.hot_tub_heat:
            state.active_mode = "hot_tub_heat"
        elif state.pool_heat:
            state.active_mode = "pool_heat"
        elif state.pool_vacuum:
            state.active_mode = "pool_vacuum"
        elif state.pool_skimmer:
            state.active_mode = "pool_skimmer"
        elif state.pool_waterfall:
            state.active_mode = "pool_waterfall"
        else:
            state.active_mode = "none"

        # Parse system flags
        for flag, attr in [
            ("pool_action", "pool_action"),
            ("pool_sequence_lock", "sequence_lock"),
            ("pool_sensor_failure_detected", "sensor_failure"),
            ("pool_system_health_ok", "system_health_ok"),
        ]:
            entity_state = states.get(f"input_boolean.{flag}")
            if entity_state:
                setattr(state, attr, entity_state.state == "on")

        # Parse valve position trackers
        for tracker in POOL_ENTITIES["trackers"]:
            entity_state = states.get(tracker)
            if entity_state:
                # Extract valve name from tracker entity ID
                valve_name = tracker.replace("input_boolean.pool_valve_", "").replace("_position_tracker", "")
                state.valve_positions[valve_name] = entity_state.state == "on"

        # Parse valve switch states
        for valve in POOL_ENTITIES["valves"]:
            entity_state = states.get(valve)
            if entity_state:
                valve_name = valve.replace("switch.pool_valve_", "").replace("_zwave", "")
                state.valve_switches[valve_name] = entity_state.state
                if entity_state.state == "unavailable":
                    state.zwave_unavailable.append(valve)

        # Parse runtime
        runtime_today = states.get("input_number.pool_pump_runtime_today")
        if runtime_today and runtime_today.state not in ("unknown", "unavailable"):
            try:
                state.runtime_today = float(runtime_today.state)
            except ValueError:
                pass

        runtime_week = states.get("input_number.pool_pump_runtime_this_week")
        if runtime_week and runtime_week.state not in ("unknown", "unavailable"):
            try:
                state.runtime_this_week = float(runtime_week.state)
            except ValueError:
                pass

        self._last_state = state
        return state

    def get_last_state(self) -> Optional[PoolSystemState]:
        """Get the last collected state."""
        return self._last_state

    def get_entity_filter_patterns(self) -> list[str]:
        """Get patterns for WebSocket entity filtering."""
        return [
            "pool",
            "hot_tub",
            "heater",
        ]
