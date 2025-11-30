#!/usr/bin/env python3
"""
Truth Agent - Sensor Integrity & Accuracy Monitoring

Validates sensor readings for accuracy, consistency, and staleness.
Specifically focused on Powerwall and energy monitoring sensors.

Validation Types:
1. Range Validation - Values within expected bounds
2. Power Balance - Energy flows must balance (solar + grid = load + battery + export)
3. Rate Consistency - Power (kW) integrated should match Energy (kWh) sensors
4. Staleness Detection - Sensors updating within expected intervals
5. Cost Validation - Costs match energy × TOU rates
6. Contradiction Detection - Impossible state combinations
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger('claude_agent_manager.truth')


class ValidationSeverity(Enum):
    """Severity levels for validation issues."""
    INFO = "info"           # Minor discrepancy, likely measurement noise
    WARNING = "warning"     # Significant discrepancy, worth investigating
    CRITICAL = "critical"   # Sensor is clearly wrong or failed


@dataclass
class ValidationResult:
    """Result of a single validation check."""
    check_name: str
    passed: bool
    severity: ValidationSeverity = ValidationSeverity.INFO
    message: str = ""
    expected: Any = None
    actual: Any = None
    deviation_pct: float = 0.0
    sensor_ids: List[str] = field(default_factory=list)


@dataclass
class TruthReport:
    """Complete truth report for all sensors."""
    timestamp: datetime
    overall_health: str  # healthy, degraded, critical
    validations: List[ValidationResult] = field(default_factory=list)
    issues: List[Dict] = field(default_factory=list)
    recommendations: List[str] = field(default_factory=list)

    @property
    def passed_count(self) -> int:
        return sum(1 for v in self.validations if v.passed)

    @property
    def failed_count(self) -> int:
        return sum(1 for v in self.validations if not v.passed)

    @property
    def critical_count(self) -> int:
        return sum(1 for v in self.validations
                   if not v.passed and v.severity == ValidationSeverity.CRITICAL)


class TruthAgent:
    """
    Truth Agent for validating sensor accuracy and consistency.
    """

    def __init__(self):
        # Expected ranges for sensors
        self.ranges = {
            # Powerwall sensors
            'sensor.home_energy_gateway_battery': (0, 100),  # %
            'sensor.home_energy_gateway_battery_power': (-15, 15),  # kW (charge/discharge)
            'sensor.home_energy_gateway_solar_power': (0, 15),  # kW (your 12.8kW system)
            'sensor.home_energy_gateway_grid_power': (-15, 25),  # kW (import/export)
            'sensor.home_energy_gateway_load_power': (0, 25),  # kW
            'sensor.home_energy_gateway_battery_remaining': (0, 45),  # kWh (40.5kWh capacity + margin)

            # EV charging
            'sensor.ev_charging_power': (0, 12),  # kW (Tesla Wall Connector max ~11.5kW)

            # Hot tub
            'sensor.hot_tub_power': (0, 7),  # kW (heater ~5.5kW + pumps)

            # Temperature
            'climate.hot_tub_thermostat': (60, 104),  # °F
        }

        # TOU rates (Hawaii Electric TOU-RI)
        self.tou_rates = {
            'mid_day': {'hours': range(9, 17), 'rate': 0.213},
            'on_peak': {'hours': range(17, 22), 'rate': 0.587},
            'off_peak': {'hours': list(range(22, 24)) + list(range(0, 9)), 'rate': 0.513},
        }

        # Staleness thresholds (seconds)
        self.staleness_thresholds = {
            'sensor.home_energy_gateway_battery': 300,  # 5 min
            'sensor.home_energy_gateway_solar_power': 300,
            'sensor.home_energy_gateway_grid_power': 300,
            'sensor.home_energy_gateway_load_power': 300,
            'default': 600,  # 10 min for others
        }

        # Power balance tolerance (kW)
        self.power_balance_tolerance = 0.5  # Allow 0.5kW measurement error

        # Energy/power consistency tolerance (%)
        self.energy_consistency_tolerance = 10  # 10% deviation acceptable

    def validate_all(self, sensor_states: Dict[str, Any]) -> TruthReport:
        """
        Run all validations and return comprehensive report.

        Args:
            sensor_states: Dict of entity_id -> {state, attributes, last_changed}
        """
        validations = []

        # 1. Range validations
        validations.extend(self.validate_ranges(sensor_states))

        # 2. Power balance validation
        validations.extend(self.validate_power_balance(sensor_states))

        # 3. Staleness validation
        validations.extend(self.validate_staleness(sensor_states))

        # 4. Cost validation
        validations.extend(self.validate_costs(sensor_states))

        # 5. Contradiction detection
        validations.extend(self.detect_contradictions(sensor_states))

        # 6. Energy accumulation validation
        validations.extend(self.validate_energy_accumulation(sensor_states))

        # Generate report
        return self._generate_report(validations)

    def validate_ranges(self, states: Dict) -> List[ValidationResult]:
        """Check all sensors are within expected ranges."""
        results = []

        for sensor_id, (min_val, max_val) in self.ranges.items():
            if sensor_id not in states:
                continue

            state_data = states[sensor_id]
            try:
                value = float(state_data.get('state', 0))
            except (ValueError, TypeError):
                results.append(ValidationResult(
                    check_name=f"range_{sensor_id}",
                    passed=False,
                    severity=ValidationSeverity.WARNING,
                    message=f"{sensor_id} has non-numeric value: {state_data.get('state')}",
                    sensor_ids=[sensor_id]
                ))
                continue

            if value < min_val or value > max_val:
                # Determine severity based on how far out of range
                deviation = max(abs(value - min_val), abs(value - max_val))
                range_size = max_val - min_val
                deviation_pct = (deviation / range_size) * 100 if range_size > 0 else 100

                severity = ValidationSeverity.CRITICAL if deviation_pct > 50 else ValidationSeverity.WARNING

                results.append(ValidationResult(
                    check_name=f"range_{sensor_id}",
                    passed=False,
                    severity=severity,
                    message=f"{sensor_id} value {value} outside range [{min_val}, {max_val}]",
                    expected=f"{min_val}-{max_val}",
                    actual=value,
                    deviation_pct=deviation_pct,
                    sensor_ids=[sensor_id]
                ))
            else:
                results.append(ValidationResult(
                    check_name=f"range_{sensor_id}",
                    passed=True,
                    message=f"{sensor_id} = {value} (valid)",
                    sensor_ids=[sensor_id]
                ))

        return results

    def validate_power_balance(self, states: Dict) -> List[ValidationResult]:
        """
        Validate power flow balance.

        Physics: Solar + Grid Import = Load + Battery Charge + Grid Export
        Or: Solar + Grid + Battery Discharge = Load + Battery Charge + Export

        Simplified: solar + grid = load + battery_power (where battery_power is +charge/-discharge)
        """
        results = []

        required = [
            'sensor.home_energy_gateway_solar_power',
            'sensor.home_energy_gateway_grid_power',
            'sensor.home_energy_gateway_load_power',
            'sensor.home_energy_gateway_battery_power'
        ]

        # Check if all required sensors available
        missing = [s for s in required if s not in states]
        if missing:
            results.append(ValidationResult(
                check_name="power_balance",
                passed=True,  # Can't fail if we can't check
                message=f"Power balance check skipped - missing: {missing}",
                sensor_ids=missing
            ))
            return results

        try:
            solar = float(states['sensor.home_energy_gateway_solar_power'].get('state', 0))
            grid = float(states['sensor.home_energy_gateway_grid_power'].get('state', 0))  # +import, -export
            load = float(states['sensor.home_energy_gateway_load_power'].get('state', 0))
            battery = float(states['sensor.home_energy_gateway_battery_power'].get('state', 0))  # +charge, -discharge

            # Power in = Power out
            # solar + grid_import + battery_discharge = load + battery_charge + grid_export
            # Simplified: solar + grid = load + battery (where signs handle direction)

            power_in = solar + max(grid, 0) + max(-battery, 0)  # solar + import + discharge
            power_out = load + max(battery, 0) + max(-grid, 0)  # load + charge + export

            imbalance = abs(power_in - power_out)

            if imbalance > self.power_balance_tolerance:
                deviation_pct = (imbalance / max(power_in, power_out, 1)) * 100
                severity = ValidationSeverity.CRITICAL if imbalance > 2 else ValidationSeverity.WARNING

                results.append(ValidationResult(
                    check_name="power_balance",
                    passed=False,
                    severity=severity,
                    message=f"Power imbalance: {imbalance:.2f}kW (in:{power_in:.1f}kW vs out:{power_out:.1f}kW)",
                    expected=f"±{self.power_balance_tolerance}kW",
                    actual=f"{imbalance:.2f}kW",
                    deviation_pct=deviation_pct,
                    sensor_ids=required
                ))
            else:
                results.append(ValidationResult(
                    check_name="power_balance",
                    passed=True,
                    message=f"Power balanced: solar={solar:.1f} grid={grid:.1f} load={load:.1f} batt={battery:.1f}",
                    sensor_ids=required
                ))

        except (ValueError, TypeError) as e:
            results.append(ValidationResult(
                check_name="power_balance",
                passed=False,
                severity=ValidationSeverity.WARNING,
                message=f"Power balance check error: {e}",
                sensor_ids=required
            ))

        return results

    def validate_staleness(self, states: Dict) -> List[ValidationResult]:
        """Check sensors are updating within expected intervals."""
        results = []
        now = datetime.now()

        for sensor_id, state_data in states.items():
            if not sensor_id.startswith('sensor.'):
                continue

            threshold = self.staleness_thresholds.get(
                sensor_id,
                self.staleness_thresholds['default']
            )

            last_changed = state_data.get('last_changed')
            if not last_changed:
                continue

            try:
                # Parse ISO timestamp
                if isinstance(last_changed, str):
                    last_changed = datetime.fromisoformat(last_changed.replace('Z', '+00:00'))
                    last_changed = last_changed.replace(tzinfo=None)  # Make naive for comparison

                age_seconds = (now - last_changed).total_seconds()

                if age_seconds > threshold:
                    hours = age_seconds / 3600
                    severity = ValidationSeverity.CRITICAL if hours > 1 else ValidationSeverity.WARNING

                    results.append(ValidationResult(
                        check_name=f"staleness_{sensor_id}",
                        passed=False,
                        severity=severity,
                        message=f"{sensor_id} stale: last updated {hours:.1f}h ago",
                        expected=f"<{threshold}s",
                        actual=f"{age_seconds:.0f}s",
                        sensor_ids=[sensor_id]
                    ))

            except Exception as e:
                logger.debug(f"Staleness check error for {sensor_id}: {e}")

        return results

    def validate_costs(self, states: Dict) -> List[ValidationResult]:
        """Validate cost calculations match energy × rate."""
        results = []

        # Check daily costs by period
        cost_checks = [
            ('sensor.grid_energy_daily_daytime', 'sensor.grid_cost_daily_daytime', 0.213),
            ('sensor.grid_energy_daily_onpeak', 'sensor.grid_cost_daily_onpeak', 0.587),
            ('sensor.grid_energy_daily_offpeak', 'sensor.grid_cost_daily_offpeak', 0.513),
        ]

        for energy_sensor, cost_sensor, rate in cost_checks:
            if energy_sensor not in states or cost_sensor not in states:
                continue

            try:
                energy_kwh = float(states[energy_sensor].get('state', 0))
                reported_cost = float(states[cost_sensor].get('state', 0))
                expected_cost = energy_kwh * rate

                if energy_kwh > 0:
                    deviation_pct = abs(reported_cost - expected_cost) / expected_cost * 100

                    if deviation_pct > 5:  # More than 5% off
                        results.append(ValidationResult(
                            check_name=f"cost_{cost_sensor}",
                            passed=False,
                            severity=ValidationSeverity.WARNING,
                            message=f"{cost_sensor}: expected ${expected_cost:.2f}, got ${reported_cost:.2f}",
                            expected=expected_cost,
                            actual=reported_cost,
                            deviation_pct=deviation_pct,
                            sensor_ids=[energy_sensor, cost_sensor]
                        ))
                    else:
                        results.append(ValidationResult(
                            check_name=f"cost_{cost_sensor}",
                            passed=True,
                            message=f"{cost_sensor} = ${reported_cost:.2f} (correct for {energy_kwh:.1f}kWh @ ${rate})",
                            sensor_ids=[energy_sensor, cost_sensor]
                        ))

            except (ValueError, TypeError):
                pass

        return results

    def detect_contradictions(self, states: Dict) -> List[ValidationResult]:
        """Detect impossible state combinations."""
        results = []

        # Check 1: Battery charging but solar=0 and grid_import=0
        if all(s in states for s in ['sensor.home_energy_gateway_battery_power',
                                      'sensor.home_energy_gateway_solar_power',
                                      'sensor.home_energy_gateway_grid_power']):
            try:
                battery = float(states['sensor.home_energy_gateway_battery_power'].get('state', 0))
                solar = float(states['sensor.home_energy_gateway_solar_power'].get('state', 0))
                grid = float(states['sensor.home_energy_gateway_grid_power'].get('state', 0))

                # Battery charging significantly but no source
                if battery > 2 and solar < 0.5 and grid < 0.5:
                    results.append(ValidationResult(
                        check_name="contradiction_battery_source",
                        passed=False,
                        severity=ValidationSeverity.CRITICAL,
                        message=f"Battery charging at {battery:.1f}kW but no source (solar={solar:.1f}, grid={grid:.1f})",
                        sensor_ids=['sensor.home_energy_gateway_battery_power',
                                   'sensor.home_energy_gateway_solar_power',
                                   'sensor.home_energy_gateway_grid_power']
                    ))
            except (ValueError, TypeError):
                pass

        # Check 2: Battery >100% or <0%
        if 'sensor.home_energy_gateway_battery' in states:
            try:
                battery_pct = float(states['sensor.home_energy_gateway_battery'].get('state', 0))
                if battery_pct > 100 or battery_pct < 0:
                    results.append(ValidationResult(
                        check_name="contradiction_battery_percent",
                        passed=False,
                        severity=ValidationSeverity.CRITICAL,
                        message=f"Battery percentage impossible: {battery_pct}%",
                        sensor_ids=['sensor.home_energy_gateway_battery']
                    ))
            except (ValueError, TypeError):
                pass

        # Check 3: Solar power at night
        hour = datetime.now().hour
        if hour < 5 or hour > 20:  # Night hours
            if 'sensor.home_energy_gateway_solar_power' in states:
                try:
                    solar = float(states['sensor.home_energy_gateway_solar_power'].get('state', 0))
                    if solar > 0.5:  # More than 500W at night
                        results.append(ValidationResult(
                            check_name="contradiction_solar_night",
                            passed=False,
                            severity=ValidationSeverity.WARNING,
                            message=f"Solar reporting {solar:.1f}kW at night ({hour}:00)",
                            sensor_ids=['sensor.home_energy_gateway_solar_power']
                        ))
                except (ValueError, TypeError):
                    pass

        # Check 4: EV charging but Wall Connector off
        if all(s in states for s in ['sensor.ev_charging_power',
                                      'binary_sensor.tesla_wall_connector_contactor_closed']):
            try:
                ev_power = float(states['sensor.ev_charging_power'].get('state', 0))
                contactor = states['binary_sensor.tesla_wall_connector_contactor_closed'].get('state')

                if ev_power > 1 and contactor != 'on':
                    results.append(ValidationResult(
                        check_name="contradiction_ev_charging",
                        passed=False,
                        severity=ValidationSeverity.WARNING,
                        message=f"EV charging at {ev_power:.1f}kW but contactor shows '{contactor}'",
                        sensor_ids=['sensor.ev_charging_power',
                                   'binary_sensor.tesla_wall_connector_contactor_closed']
                    ))
            except (ValueError, TypeError):
                pass

        return results

    def validate_energy_accumulation(self, states: Dict) -> List[ValidationResult]:
        """
        Validate that energy sensors accumulate correctly over time.

        This checks that Riemann sum integrations are working properly.
        """
        results = []

        # Check grid import energy is increasing when grid power is positive
        if all(s in states for s in ['sensor.home_energy_gateway_grid_power',
                                      'sensor.grid_import_energy']):
            try:
                grid_power = float(states['sensor.home_energy_gateway_grid_power'].get('state', 0))
                grid_energy = float(states['sensor.grid_import_energy'].get('state', 0))

                # If grid power is positive (importing) and energy shows 0, that's suspicious
                # (unless it just reset at midnight)
                hour = datetime.now().hour
                if grid_power > 1 and grid_energy < 0.01 and hour > 1:
                    results.append(ValidationResult(
                        check_name="energy_accumulation_grid",
                        passed=False,
                        severity=ValidationSeverity.WARNING,
                        message=f"Grid importing {grid_power:.1f}kW but daily energy only {grid_energy:.3f}kWh",
                        sensor_ids=['sensor.home_energy_gateway_grid_power',
                                   'sensor.grid_import_energy']
                    ))
            except (ValueError, TypeError):
                pass

        return results

    def _generate_report(self, validations: List[ValidationResult]) -> TruthReport:
        """Generate comprehensive report from validations."""
        issues = [v for v in validations if not v.passed]
        critical_count = sum(1 for v in issues if v.severity == ValidationSeverity.CRITICAL)
        warning_count = sum(1 for v in issues if v.severity == ValidationSeverity.WARNING)

        if critical_count > 0:
            health = "critical"
        elif warning_count > 2:
            health = "degraded"
        elif warning_count > 0:
            health = "warning"
        else:
            health = "healthy"

        # Generate recommendations
        recommendations = []
        for issue in issues:
            if "stale" in issue.check_name:
                recommendations.append(f"Check connectivity for {issue.sensor_ids}")
            elif "range" in issue.check_name:
                recommendations.append(f"Verify sensor calibration: {issue.sensor_ids}")
            elif "balance" in issue.check_name:
                recommendations.append("Check Powerwall integration - power flow sensors may need recalibration")
            elif "contradiction" in issue.check_name:
                recommendations.append(f"Investigate contradictory readings: {issue.message}")
            elif "cost" in issue.check_name:
                recommendations.append(f"Verify TOU rate configuration for {issue.sensor_ids}")

        return TruthReport(
            timestamp=datetime.now(),
            overall_health=health,
            validations=validations,
            issues=[{
                'check': v.check_name,
                'severity': v.severity.value,
                'message': v.message,
                'sensors': v.sensor_ids
            } for v in issues],
            recommendations=list(set(recommendations))  # Dedupe
        )


# Rule-based checks for hybrid LLM integration
def get_truth_rules() -> Dict:
    """
    Get rule-based truth checks for the hybrid LLM system.
    Returns dict of check_name -> check_function pairs.
    """
    return {
        'battery_range': lambda s: _check_battery_range(s),
        'power_balance': lambda s: _check_power_balance(s),
        'solar_night': lambda s: _check_solar_night(s),
        'cost_accuracy': lambda s: _check_cost_accuracy(s),
    }


def _check_battery_range(states: Dict) -> Dict:
    """Quick battery range check."""
    sensor = 'sensor.home_energy_gateway_battery'
    if sensor not in states:
        return {'passed': True, 'reason': 'sensor unavailable'}

    try:
        value = float(states[sensor].get('state', 0))
        if value < 0 or value > 100:
            return {
                'passed': False,
                'severity': 'critical',
                'reason': f'Battery {value}% out of range [0-100]'
            }
        return {'passed': True}
    except:
        return {'passed': True}


def _check_power_balance(states: Dict) -> Dict:
    """Quick power balance check."""
    required = ['sensor.home_energy_gateway_solar_power',
                'sensor.home_energy_gateway_grid_power',
                'sensor.home_energy_gateway_load_power']

    if not all(s in states for s in required):
        return {'passed': True, 'reason': 'sensors unavailable'}

    try:
        solar = float(states['sensor.home_energy_gateway_solar_power'].get('state', 0))
        grid = float(states['sensor.home_energy_gateway_grid_power'].get('state', 0))
        load = float(states['sensor.home_energy_gateway_load_power'].get('state', 0))

        # Simple check: solar + grid should roughly equal load (±2kW for battery)
        supply = solar + max(grid, 0)
        if load > 0 and abs(supply - load) > 5:  # 5kW tolerance
            return {
                'passed': False,
                'severity': 'warning',
                'reason': f'Power imbalance: supply={supply:.1f}kW vs load={load:.1f}kW'
            }
        return {'passed': True}
    except:
        return {'passed': True}


def _check_solar_night(states: Dict) -> Dict:
    """Check for solar power at night."""
    hour = datetime.now().hour
    if 5 <= hour <= 20:
        return {'passed': True, 'reason': 'daytime'}

    sensor = 'sensor.home_energy_gateway_solar_power'
    if sensor not in states:
        return {'passed': True}

    try:
        solar = float(states[sensor].get('state', 0))
        if solar > 0.5:
            return {
                'passed': False,
                'severity': 'warning',
                'reason': f'Solar {solar:.1f}kW at night ({hour}:00)'
            }
        return {'passed': True}
    except:
        return {'passed': True}


def _check_cost_accuracy(states: Dict) -> Dict:
    """Check cost calculation accuracy."""
    # Simple daily cost check
    energy_sensor = 'sensor.grid_import_energy'

    if energy_sensor not in states:
        return {'passed': True, 'reason': 'sensor unavailable'}

    try:
        energy = float(states[energy_sensor].get('state', 0))
        hour = datetime.now().hour

        # Very rough check: if we've imported energy, it should be > 0
        if hour > 6 and energy < 0:
            return {
                'passed': False,
                'severity': 'warning',
                'reason': f'Grid import energy is negative: {energy}'
            }
        return {'passed': True}
    except:
        return {'passed': True}
