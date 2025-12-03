"""
Hybrid LLM Client - 3-tier decision system
Version 1.0.5 - Added startup sequence monitoring rules

Tier 1: Rule-based (FREE) - handles ~70%
Tier 2: Ollama local (FREE) - handles ~25%
Tier 3: Claude API (PAID) - handles ~5%
"""

import os
import json
import logging
import aiohttp
from typing import Optional, Dict, Any, Tuple
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


class DecisionTier(Enum):
    RULE_BASED = 1
    OLLAMA_LOCAL = 2
    CLAUDE_API = 3


@dataclass
class LLMResponse:
    """Response from any tier of the LLM system"""
    tier: DecisionTier
    decision: str
    confidence: float
    reasoning: str
    action_required: bool
    action: Optional[Dict[str, Any]] = None
    needs_confirmation: bool = False
    escalated: bool = False


class HybridLLM:
    """3-tier hybrid LLM system with Ollama primary, Claude fallback"""

    def __init__(self):
        self.ollama_url = os.environ.get('OLLAMA_URL', 'http://76e18fb5-ollama:11434')
        self.ollama_model = os.environ.get('OLLAMA_MODEL', 'llama3.2:1b')
        self.claude_api_key = os.environ.get('CLAUDE_API_KEY', '')
        self.claude_model = os.environ.get('CLAUDE_MODEL', 'claude-sonnet-4-20250514')
        self.escalation_threshold = float(os.environ.get('ESCALATION_THRESHOLD', '0.7'))
        self.confirm_critical = os.environ.get('CONFIRM_CRITICAL', 'true').lower() == 'true'

        # Track API usage
        self.tier1_calls = 0
        self.tier2_calls = 0
        self.tier3_calls = 0

    async def analyze(self, agent_name: str, context: Dict[str, Any]) -> LLMResponse:
        """
        Analyze a situation using the 3-tier system.
        Returns decision with confidence and recommended action.
        """
        # Tier 1: Rule-based checks (always runs first)
        tier1_result = self._tier1_rules(agent_name, context)
        if tier1_result:
            self.tier1_calls += 1
            logger.info(f"[{agent_name}] Tier 1 handled: {tier1_result.decision}")
            return tier1_result

        # Tier 2: Ollama local LLM
        tier2_result = await self._tier2_ollama(agent_name, context)
        if tier2_result and tier2_result.confidence >= self.escalation_threshold:
            self.tier2_calls += 1
            logger.info(f"[{agent_name}] Tier 2 handled (confidence: {tier2_result.confidence:.2f})")
            return tier2_result

        # Tier 3: Claude API (only if Tier 2 low confidence or failed)
        if self.claude_api_key:
            tier3_result = await self._tier3_claude(agent_name, context, tier2_result)
            if tier3_result:
                self.tier3_calls += 1
                tier3_result.escalated = True
                logger.info(f"[{agent_name}] Tier 3 Claude handled")
                return tier3_result

        # Fallback: return Tier 2 result even if low confidence
        if tier2_result:
            tier2_result.reasoning += " (Low confidence, Claude unavailable)"
            return tier2_result

        # Ultimate fallback
        return LLMResponse(
            tier=DecisionTier.RULE_BASED,
            decision="no_action",
            confidence=0.5,
            reasoning="Unable to analyze - all tiers failed",
            action_required=False
        )

    def _tier1_rules(self, agent_name: str, context: Dict[str, Any]) -> Optional[LLMResponse]:
        """
        Tier 1: Simple rule-based decisions.
        Handles clear-cut cases without any LLM calls.
        """
        issues = context.get('issues', [])
        states = context.get('states', {})

        # Pool agent rules
        if agent_name == 'pool':
            return self._pool_rules(issues, states)

        # Lights agent rules
        elif agent_name == 'lights':
            return self._lights_rules(issues, states)

        # Security agent rules
        elif agent_name == 'security':
            return self._security_rules(issues, states)

        # Climate agent rules
        elif agent_name == 'climate':
            return self._climate_rules(issues, states)

        return None

    def _pool_rules(self, issues: list, states: dict) -> Optional[LLMResponse]:
        """Pool-specific Tier 1 rules - comprehensive auto-fix"""

        issues_str = ' '.join(issues).lower()

        # ========== CRITICAL SAFETY RULES (Act immediately) ==========

        # Rule 1: EMERGENCY - Overheat protection (>105°F)
        if 'overheat' in issues_str and '105' in issues_str:
            temp = states.get('sensor.pool_heater_wifi_temperature', 'unknown')
            return LLMResponse(
                tier=DecisionTier.RULE_BASED,
                decision="emergency_overheat_stop",
                confidence=1.0,
                reasoning=f"EMERGENCY: Water temperature {temp}°F exceeds 105°F safety limit - running emergency stop",
                action_required=True,
                action={
                    "service": "script.turn_on",
                    "target": {"entity_id": "script.pool_emergency_all_stop"}
                },
                needs_confirmation=True  # User wants confirmation for all pool actions
            )

        # Rule 2: CRITICAL - Heating mode with wrong valve position (drainage risk)
        if 'hot tub heat on but valve trackers show wrong position' in issues_str:
            return LLMResponse(
                tier=DecisionTier.RULE_BASED,
                decision="stop_heating_wrong_valves",
                confidence=1.0,
                reasoning="CRITICAL: Hot tub heating with valves in wrong position - drainage risk! Stopping heating mode.",
                action_required=True,
                action={
                    "service": "input_boolean.turn_off",
                    "target": {"entity_id": "input_boolean.hot_tub_heat"}
                },
                needs_confirmation=True  # User wants confirmation for all pool actions
            )

        # Rule 3: CRITICAL - Pump not running during heating mode
        if 'heating mode active but pump is off' in issues_str:
            return LLMResponse(
                tier=DecisionTier.RULE_BASED,
                decision="pump_on_during_heating",
                confidence=1.0,
                reasoning="CRITICAL: Heating mode active but pump is OFF - turning pump ON to prevent dry heater damage",
                action_required=True,
                action={
                    "service": "switch.turn_on",
                    "target": {"entity_id": "switch.pool_pump_zwave"}
                },
                needs_confirmation=True  # User wants confirmation for all pool actions
            )

        # ========== MEDIUM PRIORITY RULES (Auto-fix whitelisted) ==========

        # Rule 4: Stuck sequence lock (no mode active)
        if 'sequence lock stuck on' in issues_str:
            return LLMResponse(
                tier=DecisionTier.RULE_BASED,
                decision="clear_stuck_sequence_lock",
                confidence=1.0,
                reasoning="Sequence lock is stuck ON with no mode active - clearing lock",
                action_required=True,
                action={
                    "service": "input_boolean.turn_off",
                    "target": {"entity_id": "input_boolean.pool_sequence_lock"}
                },
                needs_confirmation=True  # User wants confirmation for all pool actions
            )

        # Rule 5: Stuck pool_action flag (no mode active)
        if 'pool action flag stuck on' in issues_str:
            return LLMResponse(
                tier=DecisionTier.RULE_BASED,
                decision="clear_stuck_action_flag",
                confidence=1.0,
                reasoning="Pool action flag is stuck ON with no mode active - clearing flag",
                action_required=True,
                action={
                    "service": "input_boolean.turn_off",
                    "target": {"entity_id": "input_boolean.pool_action"}
                },
                needs_confirmation=True  # User wants confirmation for all pool actions
            )

        # Rule 6: Skimmer + Waterfall conflict
        if 'both skimmer and waterfall active' in issues_str:
            return LLMResponse(
                tier=DecisionTier.RULE_BASED,
                decision="resolve_mode_conflict",
                confidence=1.0,
                reasoning="Both skimmer and waterfall are active (conflict) - turning off waterfall, keeping skimmer",
                action_required=True,
                action={
                    "service": "input_boolean.turn_off",
                    "target": {"entity_id": "input_boolean.pool_waterfall"}
                },
                needs_confirmation=True  # User wants confirmation for all pool actions
            )

        # Rule 7: Orphan pump during quiet hours
        if 'pump running during quiet hours' in issues_str and 'orphan' in issues_str:
            return LLMResponse(
                tier=DecisionTier.RULE_BASED,
                decision="pump_off_orphan",
                confidence=1.0,
                reasoning="Pump running during quiet hours (6PM-8AM) with no mode active - turning off orphan pump",
                action_required=True,
                action={
                    "service": "switch.turn_off",
                    "target": {"entity_id": "switch.pool_pump_zwave"}
                },
                needs_confirmation=True  # User wants confirmation for all pool actions
            )

        # Rule 8: Valve tracker mismatch (sync trackers)
        # Note: This handles the WARNING level mismatch, not the CRITICAL drainage risk one
        if 'valve trackers' in issues_str and 'wrong' in issues_str and 'drainage' not in issues_str:
            return LLMResponse(
                tier=DecisionTier.RULE_BASED,
                decision="sync_valve_trackers",
                confidence=0.95,
                reasoning="Valve trackers don't match expected positions - syncing trackers to current mode",
                action_required=True,
                action={
                    "service": "script.turn_on",
                    "target": {"entity_id": "script.pool_valve_tracker_sync_to_mode"}
                },
                needs_confirmation=True  # User wants confirmation for all pool actions
            )

        # Rule 9: Z-Wave valves unavailable (3+) - attempt recovery
        if 'z-wave valves unavailable' in issues_str and 'z-wave issue' in issues_str:
            return LLMResponse(
                tier=DecisionTier.RULE_BASED,
                decision="zwave_recovery",
                confidence=0.9,
                reasoning="Multiple Z-Wave valves unavailable - attempting Z-Wave integration reload",
                action_required=True,
                action={
                    "service": "homeassistant.reload_config_entry",
                    "data": {"entry_id": "zwave_js"}  # May need adjustment based on actual entry ID
                },
                needs_confirmation=True  # User wants confirmation for all pool actions
            )

        # Rule 10: Single Z-Wave valve unavailable - ping it
        if 'z-wave valve(s) unavailable' in issues_str and 'z-wave issue' not in issues_str:
            # Extract the unavailable valve name if possible
            return LLMResponse(
                tier=DecisionTier.RULE_BASED,
                decision="zwave_ping",
                confidence=0.85,
                reasoning="Z-Wave valve(s) unavailable - attempting to ping devices",
                action_required=True,
                action={
                    "service": "zwave_js.ping",
                    "target": {"entity_id": [
                        "switch.pool_valve_power_24vac_zwave",
                        "switch.pool_valve_spa_suction_zwave",
                        "switch.pool_valve_spa_return_zwave",
                        "switch.pool_valve_pool_suction_zwave",
                        "switch.pool_valve_pool_return_zwave",
                        "switch.pool_valve_skimmer_zwave",
                        "switch.pool_valve_vacuum_zwave"
                    ]}
                },
                needs_confirmation=True  # User wants confirmation for all pool actions
            )

        # Rule 11: Program mismatch - restart current mode to fix
        if 'program_mismatch' in issues_str or 'program mismatch' in issues_str:
            # Extract mode name from issue if possible for better logging
            mode_name = "active mode"
            for mode in ['hot_tub_heat', 'pool_heat', 'pool_skimmer', 'pool_waterfall', 'pool_vacuum', 'hot_tub_empty']:
                if mode in issues_str:
                    mode_name = mode.replace('_', ' ')
                    break
            return LLMResponse(
                tier=DecisionTier.RULE_BASED,
                decision="restart_mode_fix_mismatch",
                confidence=1.0,
                reasoning=f"Program mismatch detected in {mode_name} - restarting mode to correct equipment states",
                action_required=True,
                action={
                    "service": "script.turn_on",
                    "target": {"entity_id": "script.pool_system_force_restart_current_mode"}
                },
                needs_confirmation=True  # User wants confirmation for all pool actions
            )

        # Rule 12: Mode timeout - stop the timed-out mode
        if 'mode_timeout' in issues_str or 'mode timeout' in issues_str:
            # hot_tub_empty is currently the only mode with a timeout (6 minutes)
            if 'hot_tub_empty' in issues_str:
                return LLMResponse(
                    tier=DecisionTier.RULE_BASED,
                    decision="stop_timed_out_mode",
                    confidence=1.0,
                    reasoning="Hot Tub Empty mode has exceeded 6 minute timeout - stopping mode to prevent damage",
                    action_required=True,
                    action={
                        "service": "input_boolean.turn_off",
                        "target": {"entity_id": "input_boolean.hot_tub_empty"}
                    },
                    needs_confirmation=True  # User wants confirmation for all pool actions
                )

        # ========== STARTUP SEQUENCE MONITORING RULES ==========

        # Rule 13: Startup timeout - clear sequence lock
        if 'startup_timeout' in issues_str:
            return LLMResponse(
                tier=DecisionTier.RULE_BASED,
                decision="clear_startup_timeout",
                confidence=1.0,
                reasoning="Startup sequence has timed out (>5 min) - clearing sequence lock to unblock system",
                action_required=True,
                action={
                    "service": "input_boolean.turn_off",
                    "target": {"entity_id": "input_boolean.pool_sequence_lock"}
                },
                needs_confirmation=True  # User wants confirmation for all pool actions
            )

        # Rule 14: 24VAC power stuck ON - turn it off to protect valve motors
        if 'startup_issue' in issues_str and '24vac' in issues_str:
            return LLMResponse(
                tier=DecisionTier.RULE_BASED,
                decision="turn_off_24vac",
                confidence=1.0,
                reasoning="24VAC power has been ON too long - turning off to prevent valve motor damage",
                action_required=True,
                action={
                    "service": "switch.turn_off",
                    "target": {"entity_id": "switch.pool_valve_power_24vac_zwave"}
                },
                needs_confirmation=True  # User wants confirmation for all pool actions
            )

        # Rule 15: Valve switch stuck ON - turn off all valve switches
        if 'valve_stuck' in issues_str:
            return LLMResponse(
                tier=DecisionTier.RULE_BASED,
                decision="turn_off_stuck_valve",
                confidence=1.0,
                reasoning="Valve switch has been ON too long (>60s) - turning off all valve switches to prevent motor damage",
                action_required=True,
                action={
                    "service": "switch.turn_off",
                    "target": {"entity_id": [
                        "switch.pool_valve_spa_suction_zwave",
                        "switch.pool_valve_spa_return_zwave",
                        "switch.pool_valve_pool_suction_zwave",
                        "switch.pool_valve_pool_return_zwave",
                        "switch.pool_valve_skimmer_zwave",
                        "switch.pool_valve_vacuum_zwave"
                    ]}
                },
                needs_confirmation=True  # User wants confirmation for all pool actions
            )

        # Rule 16: Valve switches ON during steady-state - turn them off
        if 'valve_switch_on' in issues_str and 'steady-state' in issues_str:
            return LLMResponse(
                tier=DecisionTier.RULE_BASED,
                decision="turn_off_orphan_valve_switches",
                confidence=1.0,
                reasoning="Valve switches are ON during steady-state (no startup) - turning off orphan switches",
                action_required=True,
                action={
                    "service": "switch.turn_off",
                    "target": {"entity_id": [
                        "switch.pool_valve_power_24vac_zwave",
                        "switch.pool_valve_spa_suction_zwave",
                        "switch.pool_valve_spa_return_zwave",
                        "switch.pool_valve_pool_suction_zwave",
                        "switch.pool_valve_pool_return_zwave",
                        "switch.pool_valve_skimmer_zwave",
                        "switch.pool_valve_vacuum_zwave"
                    ]}
                },
                needs_confirmation=True  # User wants confirmation for all pool actions
            )

        # ========== MONITORING ONLY (No action) ==========

        # Sensor failure - just monitor, don't try to fix
        if 'sensor failure' in issues_str:
            return LLMResponse(
                tier=DecisionTier.RULE_BASED,
                decision="sensor_failure_monitor",
                confidence=1.0,
                reasoning="Temperature sensor failure detected - heating is blocked by existing automations. Monitoring only.",
                action_required=False
            )

        # High temperature warning (but not overheat)
        if 'temperature high' in issues_str and 'overheat' not in issues_str:
            return LLMResponse(
                tier=DecisionTier.RULE_BASED,
                decision="high_temp_monitor",
                confidence=1.0,
                reasoning="Temperature is high but below critical threshold - monitoring",
                action_required=False
            )

        # ========== NO ISSUES ==========

        if not issues:
            return LLMResponse(
                tier=DecisionTier.RULE_BASED,
                decision="all_normal",
                confidence=1.0,
                reasoning="All pool systems operating normally",
                action_required=False
            )

        # Complex issues - escalate to Tier 2
        return None

    def _lights_rules(self, issues: list, states: dict) -> Optional[LLMResponse]:
        """Lights-specific Tier 1 rules"""

        # Simple: Exterior lights on during day
        for issue in issues:
            if 'exterior_lights_on_during_day' in str(issue):
                return LLMResponse(
                    tier=DecisionTier.RULE_BASED,
                    decision="turn_off_exterior_lights",
                    confidence=1.0,
                    reasoning="Exterior lights on during daylight - wasting energy",
                    action_required=True,
                    action={
                        "service": "light.turn_off",
                        "target": {"entity_id": "light.exterior_lights"}
                    },
                    needs_confirmation=False  # Minor action
                )

        # No issues
        if not issues:
            return LLMResponse(
                tier=DecisionTier.RULE_BASED,
                decision="all_normal",
                confidence=1.0,
                reasoning="All lighting systems normal",
                action_required=False
            )

        return None

    def _security_rules(self, issues: list, states: dict) -> Optional[LLMResponse]:
        """Security-specific Tier 1 rules"""

        # No issues
        if not issues:
            return LLMResponse(
                tier=DecisionTier.RULE_BASED,
                decision="all_normal",
                confidence=1.0,
                reasoning="All security systems normal",
                action_required=False
            )

        # Security issues need more analysis - escalate
        return None

    def _climate_rules(self, issues: list, states: dict) -> Optional[LLMResponse]:
        """Climate-specific Tier 1 rules"""

        # No issues
        if not issues:
            return LLMResponse(
                tier=DecisionTier.RULE_BASED,
                decision="all_normal",
                confidence=1.0,
                reasoning="All climate systems normal",
                action_required=False
            )

        return None

    async def _tier2_ollama(self, agent_name: str, context: Dict[str, Any]) -> Optional[LLMResponse]:
        """
        Tier 2: Local Ollama LLM analysis.
        Handles pattern analysis and moderate complexity decisions.
        """
        prompt = self._build_prompt(agent_name, context)

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.ollama_url}/api/generate",
                    json={
                        "model": self.ollama_model,
                        "prompt": prompt,
                        "stream": False,
                        "options": {
                            "temperature": 0.3,
                            "num_predict": 500
                        }
                    },
                    timeout=aiohttp.ClientTimeout(total=60)
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return self._parse_llm_response(data.get('response', ''), DecisionTier.OLLAMA_LOCAL)
                    else:
                        logger.warning(f"Ollama returned status {resp.status}")
                        return None
        except Exception as e:
            logger.error(f"Ollama error: {e}")
            return None

    async def _tier3_claude(self, agent_name: str, context: Dict[str, Any],
                           tier2_result: Optional[LLMResponse]) -> Optional[LLMResponse]:
        """
        Tier 3: Claude API for complex decisions.
        Only called when Tier 2 has low confidence or complex multi-system issues.
        """
        if not self.claude_api_key:
            return None

        prompt = self._build_prompt(agent_name, context, include_tier2=tier2_result)

        try:
            # Using anthropic SDK
            import anthropic
            client = anthropic.Anthropic(api_key=self.claude_api_key)

            message = client.messages.create(
                model=self.claude_model,
                max_tokens=500,
                messages=[
                    {"role": "user", "content": prompt}
                ]
            )

            response_text = message.content[0].text
            return self._parse_llm_response(response_text, DecisionTier.CLAUDE_API)

        except Exception as e:
            logger.error(f"Claude API error: {e}")
            return None

    def _build_prompt(self, agent_name: str, context: Dict[str, Any],
                     include_tier2: Optional[LLMResponse] = None) -> str:
        """Build the analysis prompt for LLM tiers"""

        prompt = f"""You are a home automation {agent_name} agent analyzing the current system state.

CURRENT STATE:
{json.dumps(context.get('states', {}), indent=2)}

DETECTED ISSUES:
{json.dumps(context.get('issues', []), indent=2)}

RECENT EVENTS:
{json.dumps(context.get('recent_events', []), indent=2)}

"""
        if include_tier2:
            prompt += f"""
PREVIOUS ANALYSIS (low confidence):
Decision: {include_tier2.decision}
Confidence: {include_tier2.confidence}
Reasoning: {include_tier2.reasoning}

Please provide a more thorough analysis.
"""

        prompt += """
Respond in this exact JSON format:
{
  "decision": "action_name or no_action",
  "confidence": 0.0 to 1.0,
  "reasoning": "brief explanation",
  "action_required": true/false,
  "action": {"service": "...", "target": {"entity_id": "..."}} or null,
  "is_critical": true/false
}

Be conservative - only recommend actions when clearly needed.
"""
        return prompt

    def _parse_llm_response(self, response: str, tier: DecisionTier) -> Optional[LLMResponse]:
        """Parse LLM response into structured format"""
        try:
            # Extract JSON from response
            start = response.find('{')
            end = response.rfind('}') + 1
            if start >= 0 and end > start:
                json_str = response[start:end]
                data = json.loads(json_str)

                return LLMResponse(
                    tier=tier,
                    decision=data.get('decision', 'no_action'),
                    confidence=float(data.get('confidence', 0.5)),
                    reasoning=data.get('reasoning', 'No reasoning provided'),
                    action_required=data.get('action_required', False),
                    action=data.get('action'),
                    needs_confirmation=data.get('is_critical', False) and self.confirm_critical
                )
        except (json.JSONDecodeError, ValueError, KeyError) as e:
            logger.warning(f"Failed to parse LLM response: {e}")

        return None

    def get_stats(self) -> Dict[str, int]:
        """Get usage statistics by tier"""
        total = self.tier1_calls + self.tier2_calls + self.tier3_calls
        return {
            "tier1_calls": self.tier1_calls,
            "tier2_calls": self.tier2_calls,
            "tier3_calls": self.tier3_calls,
            "total_calls": total,
            "tier1_pct": round(self.tier1_calls / total * 100, 1) if total > 0 else 0,
            "tier2_pct": round(self.tier2_calls / total * 100, 1) if total > 0 else 0,
            "tier3_pct": round(self.tier3_calls / total * 100, 1) if total > 0 else 0
        }
