"""Local pattern analysis for anomaly detection."""

import logging
from typing import Optional
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from .state_monitor import PoolSystemState

logger = logging.getLogger(__name__)


@dataclass
class Pattern:
    """Represents a detected pattern or anomaly."""
    type: str  # temperature_anomaly, valve_mismatch, pump_issue, runtime_anomaly, mode_conflict
    severity: str  # low, medium, high, critical
    description: str
    data: dict = field(default_factory=dict)


@dataclass
class AnalysisResult:
    """Result of local pattern analysis."""
    timestamp: str
    patterns: list[Pattern] = field(default_factory=list)
    needs_claude_analysis: bool = False
    analysis_reason: str = ""
    optimization_opportunity: bool = False

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "timestamp": self.timestamp,
            "patterns": [
                {
                    "type": p.type,
                    "severity": p.severity,
                    "description": p.description,
                    "data": p.data,
                }
                for p in self.patterns
            ],
            "needs_claude_analysis": self.needs_claude_analysis,
            "analysis_reason": self.analysis_reason,
            "optimization_opportunity": self.optimization_opportunity,
        }


class PatternAnalyzer:
    """Analyzes pool state for patterns and anomalies."""

    def __init__(self):
        self._state_history: list[PoolSystemState] = []
        self._max_history = 288  # 24 hours at 5-min intervals

    def add_state(self, state: PoolSystemState):
        """Add a state to the history buffer."""
        self._state_history.append(state)
        if len(self._state_history) > self._max_history:
            self._state_history.pop(0)

    def analyze(self, current_state: PoolSystemState) -> AnalysisResult:
        """
        Analyze current state for patterns and anomalies.

        Returns analysis result indicating if Claude analysis is needed.
        """
        result = AnalysisResult(timestamp=datetime.now().isoformat())

        # Check for critical issues first
        self._check_sensor_failure(current_state, result)
        self._check_zwave_availability(current_state, result)
        self._check_valve_position_mismatch(current_state, result)
        self._check_pump_issues(current_state, result)
        self._check_heater_issues(current_state, result)
        self._check_temperature_anomalies(current_state, result)
        self._check_runtime_anomalies(current_state, result)
        self._check_mode_conflicts(current_state, result)
        self._check_optimization_opportunities(current_state, result)

        # Determine if Claude analysis is needed
        if any(p.severity in ("high", "critical") for p in result.patterns):
            result.needs_claude_analysis = True
            result.analysis_reason = "Critical or high severity pattern detected"
        elif result.optimization_opportunity:
            result.needs_claude_analysis = True
            result.analysis_reason = "Optimization opportunity detected"
        elif len(result.patterns) >= 3:
            result.needs_claude_analysis = True
            result.analysis_reason = "Multiple patterns detected - need holistic analysis"

        return result

    def _check_sensor_failure(self, state: PoolSystemState, result: AnalysisResult):
        """Check for temperature sensor failures."""
        if state.sensor_failure:
            result.patterns.append(Pattern(
                type="sensor_failure",
                severity="critical",
                description="Temperature sensor failure detected - heating blocked",
                data={"flag_state": state.sensor_failure}
            ))

        if state.water_temp is None:
            result.patterns.append(Pattern(
                type="sensor_unavailable",
                severity="high",
                description="Water temperature sensor unavailable",
                data={}
            ))

    def _check_zwave_availability(self, state: PoolSystemState, result: AnalysisResult):
        """Check for Z-Wave device availability issues."""
        if state.zwave_unavailable:
            severity = "critical" if len(state.zwave_unavailable) > 3 else "high"
            result.patterns.append(Pattern(
                type="zwave_unavailable",
                severity=severity,
                description=f"{len(state.zwave_unavailable)} Z-Wave devices unavailable",
                data={"devices": state.zwave_unavailable}
            ))

    def _check_valve_position_mismatch(self, state: PoolSystemState, result: AnalysisResult):
        """Check if valve positions match the expected configuration for active mode."""
        if state.active_mode == "none" or state.sequence_lock:
            return  # Skip during transitions or when no mode active

        expected_positions = self._get_expected_valve_positions(state.active_mode)
        if not expected_positions:
            return

        mismatches = []
        for valve, expected in expected_positions.items():
            actual = state.valve_positions.get(valve)
            if actual is not None and actual != expected:
                mismatches.append({
                    "valve": valve,
                    "expected": "spa" if expected else "pool",
                    "actual": "spa" if actual else "pool"
                })

        if mismatches:
            result.patterns.append(Pattern(
                type="valve_mismatch",
                severity="high",
                description=f"Valve positions don't match {state.active_mode} mode",
                data={
                    "mode": state.active_mode,
                    "mismatches": mismatches
                }
            ))

    def _get_expected_valve_positions(self, mode: str) -> dict:
        """Get expected valve positions for a given mode."""
        # Position tracker: True = spa position, False = pool position
        if mode == "hot_tub_heat":
            return {
                "spa_suction": True,
                "spa_return": True,
                "pool_suction": False,
                "pool_return": False,
                "skimmer": False,
                "vacuum": False,
            }
        elif mode == "pool_heat":
            return {
                "spa_suction": False,
                "spa_return": False,
                "pool_suction": True,
                "pool_return": True,
                "skimmer": False,
                "vacuum": False,
            }
        elif mode == "pool_skimmer":
            return {
                "spa_suction": False,
                "spa_return": False,
                "pool_suction": True,
                "pool_return": False,
                "skimmer": True,
                "vacuum": False,
            }
        elif mode == "pool_waterfall":
            return {
                "spa_suction": False,
                "spa_return": False,
                "pool_suction": True,
                "pool_return": True,
                "skimmer": False,
                "vacuum": False,
            }
        elif mode == "pool_vacuum":
            return {
                "spa_suction": False,
                "spa_return": False,
                "pool_suction": True,
                "pool_return": False,
                "skimmer": False,
                "vacuum": True,
            }
        return {}

    def _check_pump_issues(self, state: PoolSystemState, result: AnalysisResult):
        """Check for pump-related issues."""
        # Mode active but pump off
        if state.active_mode != "none" and not state.pump_on and not state.sequence_lock:
            result.patterns.append(Pattern(
                type="pump_not_running",
                severity="critical",
                description=f"Mode {state.active_mode} active but pump is OFF",
                data={
                    "mode": state.active_mode,
                    "pump_state": "off"
                }
            ))

        # Pump on but no sound detected (if sound sensor available)
        if state.pump_on and state.pump_sound_level is not None:
            if state.pump_sound_level < 40:  # Below normal pump sound level
                result.patterns.append(Pattern(
                    type="pump_sound_anomaly",
                    severity="medium",
                    description="Pump ON but sound level below normal",
                    data={
                        "sound_level": state.pump_sound_level,
                        "expected_min": 50
                    }
                ))

    def _check_heater_issues(self, state: PoolSystemState, result: AnalysisResult):
        """Check for heater-related issues."""
        # Heating mode active but heater not heating
        if state.active_mode in ("hot_tub_heat", "pool_heat"):
            if not state.heater_on:
                result.patterns.append(Pattern(
                    type="heater_not_on",
                    severity="high",
                    description=f"Heating mode {state.active_mode} active but heater relay OFF",
                    data={
                        "mode": state.active_mode,
                        "heater_state": "off"
                    }
                ))

            # Check if temperature is at setpoint but still heating
            if state.water_temp and state.heater_target_temp:
                temp_diff = state.heater_target_temp - state.water_temp
                if temp_diff <= 0 and state.heater_current_action == "heating":
                    result.patterns.append(Pattern(
                        type="heater_overshoot",
                        severity="medium",
                        description="Heater still heating despite reaching setpoint",
                        data={
                            "water_temp": state.water_temp,
                            "target_temp": state.heater_target_temp,
                            "hvac_action": state.heater_current_action
                        }
                    ))

        # Heater on but no heating mode active
        if state.heater_on and state.active_mode not in ("hot_tub_heat", "pool_heat"):
            result.patterns.append(Pattern(
                type="orphan_heater",
                severity="high",
                description="Heater ON but no heating mode active",
                data={
                    "active_mode": state.active_mode,
                    "heater_state": "on"
                }
            ))

    def _check_temperature_anomalies(self, state: PoolSystemState, result: AnalysisResult):
        """Check for temperature anomalies."""
        if state.water_temp is None:
            return

        # Dangerous temperature levels
        if state.water_temp > 105:
            result.patterns.append(Pattern(
                type="overheat",
                severity="critical",
                description=f"Water temperature dangerously high: {state.water_temp}F",
                data={"temperature": state.water_temp}
            ))
        elif state.water_temp < 40:
            result.patterns.append(Pattern(
                type="freeze_risk",
                severity="critical",
                description=f"Water temperature dangerously low: {state.water_temp}F",
                data={"temperature": state.water_temp}
            ))

        # Check temperature trends if we have history
        if len(self._state_history) >= 6:  # At least 30 minutes of history
            recent_temps = [
                s.water_temp for s in self._state_history[-6:]
                if s.water_temp is not None
            ]
            if len(recent_temps) >= 4:
                temp_change = recent_temps[-1] - recent_temps[0]

                # Rapid temperature drop (possible drainage/leak)
                if temp_change < -5:
                    result.patterns.append(Pattern(
                        type="rapid_temp_drop",
                        severity="high",
                        description=f"Water temp dropped {abs(temp_change):.1f}F in 30 min",
                        data={
                            "start_temp": recent_temps[0],
                            "end_temp": recent_temps[-1],
                            "change": temp_change
                        }
                    ))

                # Heating mode but temperature not rising
                if state.active_mode in ("hot_tub_heat", "pool_heat"):
                    if state.heater_current_action == "heating" and temp_change < 0.5:
                        result.patterns.append(Pattern(
                            type="heating_ineffective",
                            severity="medium",
                            description="Heater running but temperature not rising",
                            data={
                                "temp_change_30min": temp_change,
                                "expected_min": 1.0
                            }
                        ))

    def _check_runtime_anomalies(self, state: PoolSystemState, result: AnalysisResult):
        """Check for runtime anomalies."""
        # Get current hour
        current_hour = datetime.now().hour

        # Expected runtime calculation
        if 8 <= current_hour < 18:  # Active hours
            hours_elapsed = current_hour - 8
            expected_runtime = hours_elapsed * 60  # minutes

            if state.runtime_today < expected_runtime * 0.5:
                result.patterns.append(Pattern(
                    type="low_runtime",
                    severity="medium",
                    description=f"Runtime today ({state.runtime_today:.0f} min) is below expected",
                    data={
                        "actual": state.runtime_today,
                        "expected_min": expected_runtime * 0.5
                    }
                ))

    def _check_mode_conflicts(self, state: PoolSystemState, result: AnalysisResult):
        """Check for conflicting modes."""
        active_modes = []
        for mode in ["hot_tub_heat", "pool_heat", "pool_skimmer", "pool_waterfall", "pool_vacuum"]:
            if getattr(state, mode, False):
                active_modes.append(mode)

        if len(active_modes) > 1:
            result.patterns.append(Pattern(
                type="mode_conflict",
                severity="high",
                description=f"Multiple modes active: {', '.join(active_modes)}",
                data={"active_modes": active_modes}
            ))

        # Skimmer and waterfall conflict
        if state.pool_skimmer and state.pool_waterfall:
            result.patterns.append(Pattern(
                type="skimmer_waterfall_conflict",
                severity="high",
                description="Both skimmer and waterfall modes active",
                data={}
            ))

    def _check_optimization_opportunities(self, state: PoolSystemState, result: AnalysisResult):
        """Check for optimization opportunities."""
        current_hour = datetime.now().hour

        # Evening preheating opportunity
        if 16 <= current_hour <= 17 and not state.hot_tub_heat:
            if state.water_temp and state.water_temp < 95:
                result.optimization_opportunity = True
                result.patterns.append(Pattern(
                    type="preheat_opportunity",
                    severity="low",
                    description="Evening approaching - consider preheating hot tub",
                    data={
                        "current_temp": state.water_temp,
                        "typical_target": 103
                    }
                ))

        # Off-hours pump still running
        if current_hour >= 18 or current_hour < 8:
            if state.pump_on and state.active_mode not in ("hot_tub_heat", "pool_heat"):
                result.patterns.append(Pattern(
                    type="off_hours_pump",
                    severity="low",
                    description="Pump running during off-hours without heating mode",
                    data={
                        "hour": current_hour,
                        "active_mode": state.active_mode
                    }
                ))

    def get_state_history(self, hours: int = 24) -> list[dict]:
        """Get state history as list of dictionaries."""
        # Calculate how many states to return based on 5-min intervals
        max_states = min(hours * 12, len(self._state_history))
        return [s.to_dict() for s in self._state_history[-max_states:]]
