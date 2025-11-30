"""
Hybrid LLM Client - 3-tier decision system
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
        """Pool-specific Tier 1 rules"""

        # CRITICAL: Overheat protection
        temp = states.get('sensor.pool_heater_wifi_temperature')
        if temp and temp != 'unavailable' and temp != 'unknown':
            try:
                temp_f = float(temp)
                if temp_f > 105:
                    return LLMResponse(
                        tier=DecisionTier.RULE_BASED,
                        decision="emergency_shutdown",
                        confidence=1.0,
                        reasoning=f"CRITICAL: Water temperature {temp_f}°F exceeds 105°F safety limit",
                        action_required=True,
                        action={
                            "service": "homeassistant.turn_off",
                            "target": {"entity_id": ["input_boolean.hot_tub_heat", "input_boolean.pool_heat"]}
                        },
                        needs_confirmation=False  # Emergency - act immediately
                    )
            except (ValueError, TypeError):
                pass

        # CRITICAL: Sensor failure detected
        sensor_failure = states.get('input_boolean.pool_sensor_failure_detected')
        if sensor_failure == 'on':
            return LLMResponse(
                tier=DecisionTier.RULE_BASED,
                decision="sensor_failure_block",
                confidence=1.0,
                reasoning="Sensor failure detected - heating blocked for safety",
                action_required=False
            )

        # CRITICAL: Pump not running during heating mode
        hot_tub_heat = states.get('input_boolean.hot_tub_heat')
        pool_heat = states.get('input_boolean.pool_heat')
        pump = states.get('switch.pool_pump_zwave')

        if (hot_tub_heat == 'on' or pool_heat == 'on') and pump == 'off':
            return LLMResponse(
                tier=DecisionTier.RULE_BASED,
                decision="pump_not_running",
                confidence=1.0,
                reasoning="CRITICAL: Heating mode active but pump is OFF",
                action_required=True,
                action={
                    "service": "switch.turn_on",
                    "target": {"entity_id": "switch.pool_pump_zwave"}
                },
                needs_confirmation=self.confirm_critical
            )

        # Normal: All systems operational
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
