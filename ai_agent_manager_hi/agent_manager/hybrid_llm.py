#!/usr/bin/env python3
"""
Hybrid LLM Manager - Smart routing between Local LLM and Claude API

Architecture:
  TIER 1: Rule-based checks (free, instant)
  TIER 2: Local LLM via Ollama (free, ~1-5 seconds)
  TIER 3: Claude API (paid, best quality)

Cost savings: 90-95% reduction vs Claude-only approach
"""

import asyncio
import aiohttp
import json
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple, Callable
from dataclasses import dataclass, field
from enum import Enum
import time

logger = logging.getLogger('claude_agent_manager.hybrid')


class LLMTier(Enum):
    """LLM tier for routing decisions."""
    RULE_BASED = 1  # No LLM needed
    LOCAL = 2       # Ollama local model
    CLAUDE = 3      # Claude API


@dataclass
class AnalysisResult:
    """Result from any tier of analysis."""
    tier: LLMTier
    summary: str
    issues: List[Dict] = field(default_factory=list)
    actions: List[Dict] = field(default_factory=list)
    predictions: List[Dict] = field(default_factory=list)
    confidence: float = 0.8  # 0-1, triggers escalation if low
    escalate: bool = False   # Should escalate to higher tier?
    tokens_used: int = 0
    cost: float = 0.0
    latency_ms: int = 0
    error: Optional[str] = None


class RuleBasedAnalyzer:
    """
    TIER 1: Free rule-based analysis.
    Handles ~70% of routine checks without any LLM.
    """

    def __init__(self):
        # Thresholds for common issues
        self.thresholds = {
            'battery_low': 20,
            'battery_critical': 5,
            'battery_target_5pm': 100,
            'unavailable_warning': 3,
            'unavailable_critical': 10,
            'zwave_unhealthy': 5,
            'light_sync_warning': 1,
            'idle_room_warning': 2,
        }

        # TOU rate schedule (Hawaii Electric)
        self.tou_rates = {
            'mid_day': {'start': 9, 'end': 17, 'rate': 0.213},      # 9am-5pm
            'on_peak': {'start': 17, 'end': 22, 'rate': 0.587},     # 5pm-10pm
            'off_peak': {'start': 22, 'end': 9, 'rate': 0.513},     # 10pm-9am
        }

    def analyze(self, agent_states: Dict[str, Any]) -> AnalysisResult:
        """
        Analyze agent states using simple rules.
        Returns result with escalate=True if rules can't handle the situation.
        """
        start_time = time.time()
        issues = []
        actions = []
        predictions = []
        escalate = False

        # Check each agent with simple rules
        for agent_name, state in agent_states.items():
            result = self._check_agent(agent_name, state)
            issues.extend(result.get('issues', []))
            actions.extend(result.get('actions', []))
            predictions.extend(result.get('predictions', []))

        # Determine if we need LLM escalation
        if self._needs_escalation(agent_states, issues):
            escalate = True

        # Generate summary
        critical_count = sum(1 for i in issues if i.get('severity') == 'critical')
        warning_count = sum(1 for i in issues if i.get('severity') == 'warning')

        if not issues:
            summary = "All agents healthy. No issues detected."
        elif critical_count > 0:
            summary = f"CRITICAL: {critical_count} critical, {warning_count} warnings detected."
        else:
            summary = f"Found {len(issues)} issue(s): {warning_count} warnings."

        latency = int((time.time() - start_time) * 1000)

        return AnalysisResult(
            tier=LLMTier.RULE_BASED,
            summary=summary,
            issues=issues,
            actions=actions,
            predictions=predictions,
            confidence=0.9 if not escalate else 0.5,
            escalate=escalate,
            tokens_used=0,
            cost=0.0,
            latency_ms=latency
        )

    def _check_agent(self, agent_name: str, state: Dict) -> Dict:
        """Check a single agent for issues using rules."""
        issues = []
        actions = []
        predictions = []

        status = state.get('status', 'unknown')

        # Universal status checks
        if status in ['critical', 'failed', 'error']:
            issues.append({
                'agent': agent_name,
                'severity': 'critical',
                'description': f'{agent_name} reports {status} status',
                'rule': 'status_check'
            })
        elif status in ['warning', 'degraded', 'at_risk']:
            issues.append({
                'agent': agent_name,
                'severity': 'warning',
                'description': f'{agent_name} reports {status} status',
                'rule': 'status_check'
            })

        # Agent-specific rules
        checkers = {
            'powerwall': self._check_powerwall,
            'light_manager': self._check_light_manager,
            'hot_tub': self._check_hot_tub,
            'mower': self._check_mower,
            'garage': self._check_garage,
            'occupancy': self._check_occupancy,
            'zwave': self._check_zwave,
            'security': self._check_security,
            'bathroom_floors': self._check_bathroom_floors,
            'entity_availability': self._check_entity_availability,
            'esphome': self._check_esphome,
        }

        checker = checkers.get(agent_name)
        if checker:
            result = checker(state)
            issues.extend(result.get('issues', []))
            actions.extend(result.get('actions', []))
            predictions.extend(result.get('predictions', []))

        return {'issues': issues, 'actions': actions, 'predictions': predictions}

    def _get_current_rate(self) -> Tuple[str, float]:
        """Get current TOU rate period and price."""
        hour = datetime.now().hour
        if 9 <= hour < 17:
            return 'mid_day', 0.213
        elif 17 <= hour < 22:
            return 'on_peak', 0.587
        else:
            return 'off_peak', 0.513

    def _check_powerwall(self, state: Dict) -> Dict:
        """Powerwall-specific rules."""
        issues = []
        actions = []
        predictions = []

        battery = state.get('battery_pct', 100)
        charging = state.get('is_charging', False)
        grid_power = state.get('grid_power', 0)
        hour = datetime.now().hour
        rate_period, rate = self._get_current_rate()

        # Critical: Battery very low
        if battery < self.thresholds['battery_critical']:
            issues.append({
                'agent': 'powerwall',
                'severity': 'critical',
                'description': f'Battery critically low at {battery}%',
                'rule': 'battery_critical'
            })
            actions.append({
                'agent': 'powerwall',
                'action': 'set_reserve_100',
                'service': 'number.set_value',
                'entity': 'number.home_energy_gateway_backup_reserve',
                'value': 100,
                'reason': 'Emergency - battery critical'
            })

        # Critical: Charging during ON-PEAK (most expensive!)
        elif rate_period == 'on_peak' and grid_power > 0.5:
            issues.append({
                'agent': 'powerwall',
                'severity': 'critical',
                'description': f'Charging from grid during ON-PEAK at ${rate}/kWh!',
                'rule': 'onpeak_charging'
            })
            actions.append({
                'agent': 'powerwall',
                'action': 'set_reserve_0',
                'service': 'number.set_value',
                'entity': 'number.home_energy_gateway_backup_reserve',
                'value': 0,
                'reason': 'Stop expensive on-peak charging'
            })

        # Warning: Battery low during on-peak
        elif battery < self.thresholds['battery_low'] and rate_period == 'on_peak':
            issues.append({
                'agent': 'powerwall',
                'severity': 'warning',
                'description': f'Battery low ({battery}%) during on-peak hours',
                'rule': 'battery_onpeak'
            })

        # Prediction: Won't reach 100% by 5pm
        if 9 <= hour < 17:
            hours_to_5pm = 17 - hour
            # Assume 10kW max charge rate, need (100-battery)% of 40.5kWh
            kwh_needed = (100 - battery) / 100 * 40.5
            hours_needed = kwh_needed / 10  # 10kW max rate

            if hours_needed > hours_to_5pm and battery < 95:
                predictions.append({
                    'agent': 'powerwall',
                    'type': 'goal_at_risk',
                    'description': f'May not reach 100% by 5pm (need {hours_needed:.1f}h, have {hours_to_5pm}h)',
                    'confidence': 0.7
                })
                if battery < 80:
                    actions.append({
                        'agent': 'powerwall',
                        'action': 'set_reserve_100',
                        'service': 'number.set_value',
                        'entity': 'number.home_energy_gateway_backup_reserve',
                        'value': 100,
                        'reason': f'Force grid charging - only {hours_to_5pm}h until 5pm'
                    })

        return {'issues': issues, 'actions': actions, 'predictions': predictions}

    def _check_light_manager(self, state: Dict) -> Dict:
        """Light Manager rules."""
        issues = []
        actions = []

        sync_issues = state.get('sync_issues', 0)
        drifted = state.get('drifted_lights', 0)
        unavailable = state.get('unavailable_lights', 0)

        if sync_issues > 0:
            issues.append({
                'agent': 'light_manager',
                'severity': 'warning',
                'description': f'{sync_issues} relay/color sync issues detected',
                'rule': 'light_sync'
            })

        if drifted > 0:
            issues.append({
                'agent': 'light_manager',
                'severity': 'info',
                'description': f'{drifted} lights drifted from scene state',
                'rule': 'light_drift'
            })
            actions.append({
                'agent': 'light_manager',
                'action': 'fix_drift',
                'service': 'script.turn_on',
                'entity': 'script.light_manager_fix_drifted_member',
                'reason': f'Auto-sync {drifted} drifted bulbs'
            })

        if unavailable > 0:
            issues.append({
                'agent': 'light_manager',
                'severity': 'warning',
                'description': f'{unavailable} lights unavailable',
                'rule': 'light_unavailable'
            })

        return {'issues': issues, 'actions': actions, 'predictions': []}

    def _check_hot_tub(self, state: Dict) -> Dict:
        """Hot Tub rules."""
        issues = []
        hour = datetime.now().hour

        temp_range = state.get('temperature_range', 'unknown')
        is_heating = state.get('is_heating', False)
        rate_period, rate = self._get_current_rate()

        # Check schedule compliance
        expected_range = 'high' if 9 <= hour < 22 else 'low'
        if temp_range != expected_range and temp_range != 'unknown':
            issues.append({
                'agent': 'hot_tub',
                'severity': 'info',
                'description': f'Temperature range is {temp_range}, expected {expected_range} at {hour}:00',
                'rule': 'schedule_check'
            })

        # Warning: Heating during expensive hours
        if is_heating and rate_period != 'mid_day':
            issues.append({
                'agent': 'hot_tub',
                'severity': 'warning',
                'description': f'Hot tub heating during {rate_period} at ${rate}/kWh',
                'rule': 'expensive_heating'
            })

        return {'issues': issues, 'actions': [], 'predictions': []}

    def _check_mower(self, state: Dict) -> Dict:
        """Mower rules."""
        issues = []

        battery = state.get('battery_pct', 100)
        is_mowing = state.get('is_mowing', False)
        gate_status = state.get('gate_status', 'unknown')

        if battery < 20 and is_mowing:
            issues.append({
                'agent': 'mower',
                'severity': 'warning',
                'description': f'Mower battery low ({battery}%) while mowing',
                'rule': 'mower_battery'
            })

        return {'issues': issues, 'actions': [], 'predictions': []}

    def _check_garage(self, state: Dict) -> Dict:
        """Garage/Gate rules."""
        issues = []

        open_count = state.get('open_count', 0)
        obstruction = state.get('obstruction', False)

        if obstruction:
            issues.append({
                'agent': 'garage',
                'severity': 'critical',
                'description': 'Gate obstruction detected!',
                'rule': 'obstruction'
            })

        if open_count > 0:
            issues.append({
                'agent': 'garage',
                'severity': 'info',
                'description': f'{open_count} garage door(s) open',
                'rule': 'door_open'
            })

        return {'issues': issues, 'actions': [], 'predictions': []}

    def _check_occupancy(self, state: Dict) -> Dict:
        """Occupancy rules."""
        issues = []
        actions = []

        idle_rooms = state.get('idle_rooms', [])
        idle_count = len(idle_rooms) if isinstance(idle_rooms, list) else state.get('idle_count', 0)

        if idle_count >= self.thresholds['idle_room_warning']:
            issues.append({
                'agent': 'occupancy',
                'severity': 'info',
                'description': f'{idle_count} rooms with lights on but unoccupied',
                'rule': 'idle_lights'
            })

            # Generate turn-off actions for each idle room
            if isinstance(idle_rooms, list):
                for room in idle_rooms[:5]:  # Limit to 5 actions
                    actions.append({
                        'agent': 'occupancy',
                        'action': 'turn_off_idle',
                        'service': 'light.turn_off',
                        'entity': room.get('light_entity', ''),
                        'reason': f"Room '{room.get('name', 'unknown')}' unoccupied for {room.get('minutes', '?')} min"
                    })

        return {'issues': issues, 'actions': actions, 'predictions': []}

    def _check_zwave(self, state: Dict) -> Dict:
        """Z-Wave network rules."""
        issues = []
        actions = []

        unavailable = state.get('unavailable_count', 0)
        unavailable_devices = state.get('unavailable_devices', [])

        if unavailable >= self.thresholds['unavailable_critical']:
            issues.append({
                'agent': 'zwave',
                'severity': 'critical',
                'description': f'{unavailable} Z-Wave devices unavailable - possible network issue',
                'rule': 'zwave_unavailable'
            })
        elif unavailable >= self.thresholds['unavailable_warning']:
            issues.append({
                'agent': 'zwave',
                'severity': 'warning',
                'description': f'{unavailable} Z-Wave devices unavailable',
                'rule': 'zwave_unavailable'
            })

            # Generate ping actions for unavailable devices
            if isinstance(unavailable_devices, list):
                for device in unavailable_devices[:10]:  # Limit to 10
                    actions.append({
                        'agent': 'zwave',
                        'action': 'ping_device',
                        'service': 'zwave_js.ping',
                        'entity': device.get('entity_id', ''),
                        'reason': f"Device '{device.get('name', 'unknown')}' unavailable"
                    })

        return {'issues': issues, 'actions': actions, 'predictions': []}

    def _check_security(self, state: Dict) -> Dict:
        """Security rules."""
        issues = []

        cameras_online = state.get('cameras_online', 10)
        total_cameras = state.get('total_cameras', 10)

        offline = total_cameras - cameras_online
        if offline >= 3:
            issues.append({
                'agent': 'security',
                'severity': 'critical',
                'description': f'{offline} cameras offline!',
                'rule': 'cameras_offline'
            })
        elif offline > 0:
            issues.append({
                'agent': 'security',
                'severity': 'warning',
                'description': f'{offline} camera(s) offline',
                'rule': 'cameras_offline'
            })

        return {'issues': issues, 'actions': [], 'predictions': []}

    def _check_bathroom_floors(self, state: Dict) -> Dict:
        """Bathroom Floors (Climate) rules."""
        issues = []
        actions = []

        hour = datetime.now().hour
        solar_excess = state.get('solar_excess', 0)
        battery_pct = state.get('battery_pct', 0)
        is_heating = state.get('is_heating', False)
        ev_charging = state.get('ev_charging', False)

        # Check if conditions are right for heating (11am-2pm window)
        in_window = 11 <= hour < 14
        good_conditions = solar_excess > 3.5 and battery_pct > 60 and not ev_charging

        if in_window and good_conditions and not is_heating:
            actions.append({
                'agent': 'bathroom_floors',
                'action': 'turn_on_heating',
                'service': 'input_boolean.turn_on',
                'entity': 'input_boolean.heat_up_bathroom_floors',
                'reason': f'Solar excess {solar_excess:.1f}kW, battery {battery_pct}%'
            })
        elif is_heating and (not in_window or not good_conditions):
            actions.append({
                'agent': 'bathroom_floors',
                'action': 'turn_off_heating',
                'service': 'input_boolean.turn_off',
                'entity': 'input_boolean.heat_up_bathroom_floors',
                'reason': 'Conditions no longer optimal for floor heating'
            })

        return {'issues': issues, 'actions': actions, 'predictions': []}

    def _check_entity_availability(self, state: Dict) -> Dict:
        """Entity Availability Agent rules."""
        issues = []
        actions = []
        predictions = []

        total_unavail = state.get('total_unavailable', 0)
        zwave_unavail = state.get('zwave_unavailable', 0)
        esphome_unavail = state.get('esphome_unavailable', 0)
        zigbee_unavail = state.get('zigbee_unavailable', 0)
        camera_unavail = state.get('camera_unavailable', 0)
        critical_count = state.get('critical_count', 0)

        # Critical: Many entities unavailable
        if total_unavail > 20:
            issues.append({
                'agent': 'entity_availability',
                'severity': 'critical',
                'description': f'{total_unavail} entities unavailable - possible network issue',
                'rule': 'mass_unavailable'
            })

        # Warning: Critical entities unavailable
        if critical_count > 0:
            issues.append({
                'agent': 'entity_availability',
                'severity': 'warning',
                'description': f'{critical_count} critical entity(s) unavailable (relays, gates, cameras)',
                'rule': 'critical_unavailable'
            })

        # Route to appropriate agents
        if zwave_unavail > 0:
            actions.append({
                'agent': 'entity_availability',
                'action': 'route_to_zwave',
                'service': 'event.fire',
                'entity': 'entity_availability_route_zwave',
                'reason': f'{zwave_unavail} Z-Wave entities need ping/refresh'
            })

        if esphome_unavail > 0:
            actions.append({
                'agent': 'entity_availability',
                'action': 'route_to_esphome',
                'service': 'event.fire',
                'entity': 'entity_availability_route_esphome',
                'reason': f'{esphome_unavail} ESPHome devices may need reboot'
            })

        if camera_unavail > 0:
            actions.append({
                'agent': 'entity_availability',
                'action': 'route_to_security',
                'service': 'event.fire',
                'entity': 'entity_availability_route_camera',
                'reason': f'{camera_unavail} cameras may need restart'
            })

        return {'issues': issues, 'actions': actions, 'predictions': predictions}

    def _check_esphome(self, state: Dict) -> Dict:
        """ESPHome Agent rules."""
        issues = []
        actions = []
        predictions = []

        unavail_count = state.get('unavailable_count', 0)
        weak_signal_count = state.get('weak_signal_count', 0)
        avg_rssi = state.get('avg_rssi', -50)

        # Critical: Multiple devices offline
        if unavail_count > 3:
            issues.append({
                'agent': 'esphome',
                'severity': 'critical',
                'description': f'{unavail_count} ESPHome devices unavailable - possible network issue',
                'rule': 'mass_offline'
            })
        elif unavail_count > 0:
            issues.append({
                'agent': 'esphome',
                'severity': 'warning',
                'description': f'{unavail_count} ESPHome device(s) unavailable',
                'rule': 'devices_offline'
            })

        # Warning: Weak WiFi signals
        if weak_signal_count > 5:
            issues.append({
                'agent': 'esphome',
                'severity': 'warning',
                'description': f'{weak_signal_count} devices have weak WiFi signal (<-75dBm)',
                'rule': 'weak_signals'
            })

        # Prediction: Network degradation
        if avg_rssi < -70:
            predictions.append({
                'agent': 'esphome',
                'type': 'network_degradation',
                'description': f'Average RSSI {avg_rssi}dBm is below optimal - connectivity issues likely',
                'confidence': 0.7
            })

        return {'issues': issues, 'actions': actions, 'predictions': predictions}

    def _needs_escalation(self, states: Dict, issues: List) -> bool:
        """Determine if we need LLM analysis."""
        # Escalate if multiple agents have issues (correlation needed)
        agents_with_issues = set(i['agent'] for i in issues)
        if len(agents_with_issues) >= 3:
            return True

        # Escalate for multiple critical issues
        critical_count = sum(1 for i in issues if i.get('severity') == 'critical')
        if critical_count >= 2:
            return True

        # Escalate for unusual patterns (would need more context)
        # Future: Add anomaly detection here

        return False


class OllamaClient:
    """
    TIER 2: Local LLM via Ollama.
    Free, runs locally, good for pattern analysis.
    """

    def __init__(
        self,
        base_url: str = "http://homeassistant.local:11434",
        model: str = "llama3.2:3b",
        timeout: int = 30,
        max_retries: int = 2
    ):
        self.base_url = base_url.rstrip('/')
        self.model = model
        self.timeout = timeout
        self.max_retries = max_retries
        self.available = False
        self._last_check = None
        self._check_interval = 60  # Recheck availability every 60 seconds

    async def check_availability(self) -> bool:
        """Check if Ollama is running and model is available."""
        # Cache availability check
        if self._last_check and (time.time() - self._last_check) < self._check_interval:
            return self.available

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{self.base_url}/api/tags",
                    timeout=aiohttp.ClientTimeout(total=5)
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        models = [m['name'] for m in data.get('models', [])]
                        self.available = any(self.model in m for m in models)
                        self._last_check = time.time()
                        logger.info(f"Ollama available: {self.available}, models: {models}")
                        return self.available
        except asyncio.TimeoutError:
            logger.warning("Ollama check timed out")
        except aiohttp.ClientError as e:
            logger.warning(f"Ollama connection error: {e}")
        except Exception as e:
            logger.warning(f"Ollama not available: {e}")

        self.available = False
        self._last_check = time.time()
        return False

    async def analyze(
        self,
        agent_states: Dict[str, Any],
        context: str = ""
    ) -> AnalysisResult:
        """Analyze system state using local Ollama model with retry logic."""
        start_time = time.time()

        # Check availability first
        if not await self.check_availability():
            return AnalysisResult(
                tier=LLMTier.LOCAL,
                summary="Local LLM unavailable",
                escalate=True,
                error="Ollama not available"
            )

        prompt = self._build_prompt(agent_states, context)
        last_error = None

        for attempt in range(self.max_retries + 1):
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.post(
                        f"{self.base_url}/api/generate",
                        json={
                            "model": self.model,
                            "prompt": prompt,
                            "stream": False,
                            "options": {
                                "temperature": 0.3,
                                "num_predict": 500,
                                "top_p": 0.9
                            }
                        },
                        timeout=aiohttp.ClientTimeout(total=self.timeout)
                    ) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            result = self._parse_response(data)
                            result.latency_ms = int((time.time() - start_time) * 1000)
                            return result
                        else:
                            last_error = f"HTTP {resp.status}"

            except asyncio.TimeoutError:
                last_error = "Request timed out"
                logger.warning(f"Ollama attempt {attempt + 1} timed out")
            except aiohttp.ClientError as e:
                last_error = str(e)
                logger.warning(f"Ollama attempt {attempt + 1} failed: {e}")
            except Exception as e:
                last_error = str(e)
                logger.error(f"Ollama unexpected error: {e}")
                break  # Don't retry on unexpected errors

            # Wait before retry
            if attempt < self.max_retries:
                await asyncio.sleep(1)

        # All retries failed - escalate to Claude
        return AnalysisResult(
            tier=LLMTier.LOCAL,
            summary="Local analysis failed after retries",
            escalate=True,
            latency_ms=int((time.time() - start_time) * 1000),
            error=last_error
        )

    def _build_prompt(self, states: Dict, context: str) -> str:
        """Build a concise prompt for local model."""
        # Simplify states for smaller context
        simplified = {}
        for agent, state in states.items():
            simplified[agent] = {
                'status': state.get('status', 'unknown'),
                'key_metrics': {k: v for k, v in state.items()
                              if k in ['battery_pct', 'unavailable_count', 'sync_issues',
                                      'idle_count', 'cameras_online', 'solar_excess']}
            }

        return f"""You are a Home Assistant monitoring agent. Analyze these agent states briefly.

Current time: {datetime.now().strftime('%H:%M')}
Rate period: {'mid_day ($0.213)' if 9 <= datetime.now().hour < 17 else 'on_peak ($0.587)' if 17 <= datetime.now().hour < 22 else 'off_peak ($0.513)'}

Agent States:
{json.dumps(simplified, indent=2)}

{f'Context: {context}' if context else ''}

Respond ONLY with valid JSON (no other text):
{{"summary": "one line summary", "issues": [{{"agent": "name", "severity": "warning|critical", "description": "issue"}}], "confidence": 0.8, "escalate": false}}

Set escalate=true ONLY if you see complex multi-agent correlations needing deeper analysis."""

    def _parse_response(self, data: Dict) -> AnalysisResult:
        """Parse Ollama response."""
        response_text = data.get('response', '')
        tokens = data.get('eval_count', 0) + data.get('prompt_eval_count', 0)

        # Try to extract JSON from response
        try:
            # Find JSON in response (handle potential preamble text)
            start = response_text.find('{')
            end = response_text.rfind('}') + 1
            if start >= 0 and end > start:
                json_str = response_text[start:end]
                parsed = json.loads(json_str)

                # Validate required fields
                confidence = float(parsed.get('confidence', 0.7))
                escalate = bool(parsed.get('escalate', False))

                return AnalysisResult(
                    tier=LLMTier.LOCAL,
                    summary=str(parsed.get('summary', 'Analysis complete'))[:200],
                    issues=parsed.get('issues', []) if isinstance(parsed.get('issues'), list) else [],
                    actions=parsed.get('actions', []) if isinstance(parsed.get('actions'), list) else [],
                    confidence=min(max(confidence, 0), 1),  # Clamp 0-1
                    escalate=escalate,
                    tokens_used=tokens,
                    cost=0.0
                )
        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse Ollama JSON: {e}")
        except Exception as e:
            logger.warning(f"Error parsing Ollama response: {e}")

        # Fallback: couldn't parse, escalate
        return AnalysisResult(
            tier=LLMTier.LOCAL,
            summary=response_text[:200] if response_text else "Parse error",
            confidence=0.3,
            escalate=True,
            tokens_used=tokens,
            error="Failed to parse JSON response"
        )


class ClaudeClient:
    """
    TIER 3: Claude API for complex analysis.
    Best quality, paid, used only when needed.
    """

    def __init__(
        self,
        api_key: str,
        model: str = "claude-3-haiku-20240307",
        max_retries: int = 2
    ):
        # Strip whitespace from API key (common copy-paste issue)
        self.api_key = api_key.strip() if api_key else ""
        self.model = model
        self.max_retries = max_retries

        # Pricing per 1M tokens (as of 2024)
        self.pricing = {
            'claude-3-haiku-20240307': {'input': 0.25, 'output': 1.25},
            'claude-3-5-sonnet-20241022': {'input': 3.00, 'output': 15.00},
            'claude-3-opus-20240229': {'input': 15.00, 'output': 75.00},
        }

    async def analyze(
        self,
        agent_states: Dict[str, Any],
        context: str = "",
        tool_results: Optional[List[Dict]] = None
    ) -> AnalysisResult:
        """Call Claude API for complex analysis."""
        start_time = time.time()

        try:
            import anthropic
        except ImportError:
            return AnalysisResult(
                tier=LLMTier.CLAUDE,
                summary="anthropic package not installed",
                escalate=False,
                error="Missing anthropic package"
            )

        if not self.api_key:
            return AnalysisResult(
                tier=LLMTier.CLAUDE,
                summary="Claude API key not configured",
                escalate=False,
                error="Missing API key"
            )

        prompt = self._build_prompt(agent_states, context, tool_results)
        last_error = None

        for attempt in range(self.max_retries + 1):
            try:
                client = anthropic.Anthropic(api_key=self.api_key)

                response = client.messages.create(
                    model=self.model,
                    max_tokens=1000,
                    messages=[{"role": "user", "content": prompt}]
                )

                # Calculate cost
                input_tokens = response.usage.input_tokens
                output_tokens = response.usage.output_tokens
                pricing = self.pricing.get(self.model, {'input': 0.25, 'output': 1.25})
                cost = (input_tokens * pricing['input'] + output_tokens * pricing['output']) / 1_000_000

                # Parse response
                text = response.content[0].text
                parsed = self._parse_response(text)

                return AnalysisResult(
                    tier=LLMTier.CLAUDE,
                    summary=parsed.get('summary', 'Analysis complete'),
                    issues=parsed.get('issues', []),
                    actions=parsed.get('actions', []),
                    predictions=parsed.get('predictions', []),
                    confidence=0.95,
                    escalate=False,
                    tokens_used=input_tokens + output_tokens,
                    cost=cost,
                    latency_ms=int((time.time() - start_time) * 1000)
                )

            except anthropic.RateLimitError:
                last_error = "Rate limited"
                logger.warning(f"Claude rate limited, attempt {attempt + 1}")
                await asyncio.sleep(2 ** attempt)  # Exponential backoff
            except anthropic.APIError as e:
                last_error = str(e)
                logger.error(f"Claude API error: {e}")
                break
            except Exception as e:
                last_error = str(e)
                logger.error(f"Claude unexpected error: {e}")
                break

        return AnalysisResult(
            tier=LLMTier.CLAUDE,
            summary=f"Claude API error: {last_error}",
            escalate=False,
            latency_ms=int((time.time() - start_time) * 1000),
            error=last_error
        )

    def _build_prompt(
        self,
        states: Dict,
        context: str,
        tool_results: Optional[List[Dict]]
    ) -> str:
        """Build prompt for Claude."""
        hour = datetime.now().hour
        rate_info = "mid_day ($0.213/kWh)" if 9 <= hour < 17 else \
                   "on_peak ($0.587/kWh - EXPENSIVE)" if 17 <= hour < 22 else \
                   "off_peak ($0.513/kWh)"

        prompt = f"""You are an expert Home Assistant monitoring agent for a home in Hawaii.

Current time: {datetime.now().strftime('%Y-%m-%d %H:%M')}
TOU Rate: {rate_info}

System has 9 agents monitoring:
- Powerwall (battery/solar, goal: 100% by 5pm)
- Light Manager (relay/color sync, drift detection)
- Hot Tub (temp, schedule, energy)
- Mower (gate coordination)
- Garage/Gate (door status, obstructions)
- Occupancy (idle room detection)
- Z-Wave (network health)
- Security (10 cameras)
- Bathroom Floors (solar-powered heating)

Agent States:
{json.dumps(states, indent=2)}

{f'Additional Context: {context}' if context else ''}
{f'Tool Results: {json.dumps(tool_results, indent=2)}' if tool_results else ''}

Analyze the system and provide:
1. Brief summary (1-2 sentences)
2. Any issues (with severity: critical/warning/info)
3. Recommended actions (with reasoning)
4. Predictions (potential future problems)

Respond as JSON:
{{"summary": "...", "issues": [...], "actions": [...], "predictions": [...]}}"""

        return prompt

    def _parse_response(self, text: str) -> Dict:
        """Parse Claude response."""
        try:
            start = text.find('{')
            end = text.rfind('}') + 1
            if start >= 0 and end > start:
                return json.loads(text[start:end])
        except json.JSONDecodeError:
            pass

        return {"summary": text[:500]}


class HybridLLMManager:
    """
    Main hybrid LLM manager that routes between tiers.

    Routing logic:
    1. Always start with rule-based analysis (free, instant)
    2. If rules flag for escalation OR low confidence, try local LLM
    3. If local LLM unavailable OR flags for escalation, use Claude

    Expected cost savings: 90-95% vs Claude-only
    """

    def __init__(
        self,
        claude_api_key: str,
        ollama_url: str = "http://homeassistant.local:11434",
        ollama_model: str = "llama3.2:3b",
        claude_model: str = "claude-3-haiku-20240307",
        escalation_threshold: float = 0.7,
        enabled: bool = True
    ):
        self.enabled = enabled
        self.rule_analyzer = RuleBasedAnalyzer()
        self.ollama = OllamaClient(base_url=ollama_url, model=ollama_model)
        self.claude = ClaudeClient(api_key=claude_api_key, model=claude_model)
        self.escalation_threshold = escalation_threshold

        # Statistics tracking
        self.stats = {
            'rule_based_count': 0,
            'local_count': 0,
            'claude_count': 0,
            'total_cost': 0.0,
            'total_latency_ms': 0,
            'errors': 0
        }

    async def initialize(self) -> bool:
        """Initialize and check local LLM availability."""
        available = await self.ollama.check_availability()
        if available:
            logger.info(f"Hybrid LLM initialized - Local: {self.ollama.model}, Claude: {self.claude.model}")
        else:
            logger.warning(f"Local LLM not available - will fallback to Claude for escalations")
        return available

    async def analyze(
        self,
        agent_states: Dict[str, Any],
        force_tier: Optional[LLMTier] = None,
        context: str = ""
    ) -> AnalysisResult:
        """
        Analyze agent states using hybrid approach.

        Args:
            agent_states: Current state of all agents
            force_tier: Force a specific tier (for testing)
            context: Additional context for analysis

        Returns:
            AnalysisResult from whichever tier handled the request
        """
        if not self.enabled and force_tier is None:
            # Disabled - just run rules
            return self.rule_analyzer.analyze(agent_states)

        # TIER 1: Rule-based analysis (always runs first unless forced)
        if force_tier is None or force_tier == LLMTier.RULE_BASED:
            result = self.rule_analyzer.analyze(agent_states)
            self.stats['rule_based_count'] += 1
            self.stats['total_latency_ms'] += result.latency_ms

            # If rules handle it with high confidence, we're done
            if not result.escalate and result.confidence >= self.escalation_threshold:
                logger.debug(f"Tier 1 (rules) handled - {len(result.issues)} issues, {result.latency_ms}ms")
                return result

            # If forced to rules only, return even with low confidence
            if force_tier == LLMTier.RULE_BASED:
                return result

        # TIER 2: Local LLM (if available)
        if force_tier is None or force_tier == LLMTier.LOCAL:
            if self.ollama.available or force_tier == LLMTier.LOCAL:
                result = await self.ollama.analyze(agent_states, context)
                self.stats['local_count'] += 1
                self.stats['total_latency_ms'] += result.latency_ms

                if result.error:
                    self.stats['errors'] += 1

                if not result.escalate and result.confidence >= self.escalation_threshold:
                    logger.debug(f"Tier 2 (local) handled - confidence {result.confidence:.2f}, {result.latency_ms}ms")
                    return result

                # If forced to local only, return even if escalation flagged
                if force_tier == LLMTier.LOCAL:
                    return result

        # TIER 3: Claude API (fallback)
        result = await self.claude.analyze(agent_states, context)
        self.stats['claude_count'] += 1
        self.stats['total_cost'] += result.cost
        self.stats['total_latency_ms'] += result.latency_ms

        if result.error:
            self.stats['errors'] += 1

        logger.info(f"Tier 3 (Claude) handled - cost: ${result.cost:.4f}, {result.latency_ms}ms")
        return result

    def get_stats(self) -> Dict:
        """Get routing statistics."""
        total = self.stats['rule_based_count'] + self.stats['local_count'] + self.stats['claude_count']

        if total == 0:
            return {**self.stats, 'total_requests': 0}

        return {
            **self.stats,
            'total_requests': total,
            'rule_based_pct': round(self.stats['rule_based_count'] / total * 100, 1),
            'local_pct': round(self.stats['local_count'] / total * 100, 1),
            'claude_pct': round(self.stats['claude_count'] / total * 100, 1),
            'avg_cost_per_request': round(self.stats['total_cost'] / total, 6),
            'avg_latency_ms': round(self.stats['total_latency_ms'] / total, 0),
            'error_rate_pct': round(self.stats['errors'] / total * 100, 1) if total else 0
        }

    def reset_stats(self):
        """Reset statistics."""
        self.stats = {
            'rule_based_count': 0,
            'local_count': 0,
            'claude_count': 0,
            'total_cost': 0.0,
            'total_latency_ms': 0,
            'errors': 0
        }
