"""Hybrid LLM Manager - 3-tier cost optimization for AI decisions.

Tier 1: Rule-Based (FREE) - Handles ~70% of checks
    - Battery thresholds, device status, TOU rate checks
    - Escalates if: 3+ patterns, 2+ critical severity

Tier 2: Ollama Local LLM (FREE) - Handles ~25% of checks
    - Pattern analysis, correlations, JSON responses
    - Escalates if: low confidence, complex multi-system situation

Tier 3: Claude API (PAID) - Handles ~5% of checks
    - Full tool use, deep analysis, predictions
"""

import os
import json
import logging
import asyncio
from enum import Enum
from typing import Optional
from dataclasses import dataclass, field
from datetime import datetime

import aiohttp

logger = logging.getLogger(__name__)


class Tier(Enum):
    """Processing tier used for a decision."""
    RULE_BASED = "rule_based"
    LOCAL = "local"
    CLAUDE = "claude"


@dataclass
class HybridDecision:
    """Decision result from hybrid LLM system."""
    tier_used: Tier
    action_required: bool
    actions: list[dict] = field(default_factory=list)
    explanation: str = ""
    confidence: float = 0.0
    reasoning: str = ""
    cost_usd: float = 0.0
    escalation_reason: str = ""


@dataclass
class LLMStats:
    """Track usage statistics across tiers."""
    rule_based_count: int = 0
    local_count: int = 0
    claude_count: int = 0
    total_cost_usd: float = 0.0

    @property
    def total_count(self) -> int:
        return self.rule_based_count + self.local_count + self.claude_count

    def get_percentages(self) -> dict:
        total = self.total_count
        if total == 0:
            return {"rule_based": 0, "local": 0, "claude": 0}
        return {
            "rule_based": round(self.rule_based_count / total * 100, 1),
            "local": round(self.local_count / total * 100, 1),
            "claude": round(self.claude_count / total * 100, 1),
        }


class OllamaClient:
    """Client for local Ollama LLM."""

    def __init__(self, base_url: str, model: str, timeout: int = 60):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self._available: Optional[bool] = None

    async def check_availability(self) -> bool:
        """Check if Ollama is available and model is loaded."""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{self.base_url}/api/tags",
                    timeout=aiohttp.ClientTimeout(total=5)
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        models = [m.get("name", "") for m in data.get("models", [])]
                        # Check if our model (or base name) is available
                        model_base = self.model.split(":")[0]
                        self._available = any(
                            model_base in m for m in models
                        )
                        if not self._available:
                            logger.warning(
                                f"Ollama available but model '{self.model}' not found. "
                                f"Available: {models}"
                            )
                        return self._available
        except Exception as e:
            logger.debug(f"Ollama not available: {e}")
            self._available = False
        return False

    async def generate(self, prompt: str, system_prompt: str = "") -> Optional[str]:
        """Generate a response from Ollama."""
        if self._available is False:
            return None

        try:
            payload = {
                "model": self.model,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "temperature": 0.3,  # Lower for more deterministic responses
                    "num_predict": 1024,
                }
            }
            if system_prompt:
                payload["system"] = system_prompt

            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.base_url}/api/generate",
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=self.timeout)
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return data.get("response", "")
                    else:
                        logger.warning(f"Ollama returned status {resp.status}")
                        return None
        except asyncio.TimeoutError:
            logger.warning(f"Ollama request timed out after {self.timeout}s")
            return None
        except Exception as e:
            logger.error(f"Ollama generation error: {e}")
            return None


class RuleBasedAnalyzer:
    """Tier 1: Rule-based analysis for common scenarios."""

    # Thresholds for rule-based decisions
    TEMP_OVERHEAT = 105
    TEMP_FREEZE = 40
    TEMP_HOT_TUB_TARGET = 103
    TEMP_POOL_TARGET = 81

    def analyze(self, state: dict, patterns: list[dict]) -> Optional[HybridDecision]:
        """
        Attempt to make a decision using only rules.

        Returns None if escalation to higher tier is needed.
        """
        # Count severity levels
        critical_count = sum(1 for p in patterns if p.get("severity") == "critical")
        high_count = sum(1 for p in patterns if p.get("severity") == "high")

        # Escalate if too many serious issues
        if critical_count >= 2:
            return None  # Escalate to higher tier
        if critical_count >= 1 and high_count >= 1:
            return None  # Escalate
        if len(patterns) >= 3:
            return None  # Too complex, escalate

        # Handle specific single-pattern cases
        if len(patterns) == 0:
            return HybridDecision(
                tier_used=Tier.RULE_BASED,
                action_required=False,
                explanation="System operating normally",
                confidence=0.95,
                reasoning="No patterns detected - all checks passed"
            )

        # Single pattern handling
        if len(patterns) == 1:
            pattern = patterns[0]
            return self._handle_single_pattern(pattern, state)

        # Two low/medium patterns - can still handle
        if len(patterns) == 2:
            severities = [p.get("severity") for p in patterns]
            if all(s in ("low", "medium") for s in severities):
                return self._handle_simple_patterns(patterns, state)

        return None  # Escalate anything else

    def _handle_single_pattern(self, pattern: dict, state: dict) -> Optional[HybridDecision]:
        """Handle a single detected pattern with rules."""
        pattern_type = pattern.get("type", "")
        severity = pattern.get("severity", "")

        # Critical patterns that need immediate rule-based response
        if pattern_type == "overheat":
            return HybridDecision(
                tier_used=Tier.RULE_BASED,
                action_required=True,
                actions=[
                    {"type": "service_call", "domain": "script", "service": "turn_on",
                     "entity_id": "script.pool_emergency_all_stop"}
                ],
                explanation=f"EMERGENCY: Water temperature {pattern.get('data', {}).get('temperature', '?')}°F - emergency stop executed",
                confidence=1.0,
                reasoning="Rule: Temperature exceeds 105°F safety limit"
            )

        if pattern_type == "freeze_risk":
            return HybridDecision(
                tier_used=Tier.RULE_BASED,
                action_required=True,
                actions=[
                    {"type": "service_call", "domain": "input_boolean", "service": "turn_on",
                     "entity_id": "input_boolean.pool_heat"}
                ],
                explanation=f"Freeze protection: Water at {pattern.get('data', {}).get('temperature', '?')}°F - activating pool heat",
                confidence=0.95,
                reasoning="Rule: Temperature below 40°F freeze threshold"
            )

        if pattern_type == "pump_not_running" and severity == "critical":
            return HybridDecision(
                tier_used=Tier.RULE_BASED,
                action_required=True,
                actions=[
                    {"type": "service_call", "domain": "script", "service": "turn_on",
                     "entity_id": "script.pool_system_force_restart_current_mode"}
                ],
                explanation="Pump not running during active mode - forcing restart",
                confidence=0.90,
                reasoning="Rule: Active mode requires pump - attempting force restart"
            )

        if pattern_type == "orphan_heater":
            return HybridDecision(
                tier_used=Tier.RULE_BASED,
                action_required=True,
                actions=[
                    {"type": "service_call", "domain": "switch", "service": "turn_off",
                     "entity_id": "switch.pool_heater_wifi"}
                ],
                explanation="Heater running without heating mode - turning off for safety",
                confidence=0.95,
                reasoning="Rule: Heater must only run during heating modes"
            )

        if pattern_type == "sensor_failure":
            return HybridDecision(
                tier_used=Tier.RULE_BASED,
                action_required=False,
                explanation="Temperature sensor failure detected - heating blocked by safety system",
                confidence=0.90,
                reasoning="Rule: Sensor failure is handled by existing automations, no action needed"
            )

        # Low severity patterns - log but no action
        if severity == "low":
            return HybridDecision(
                tier_used=Tier.RULE_BASED,
                action_required=False,
                explanation=pattern.get("description", "Minor issue detected"),
                confidence=0.85,
                reasoning=f"Rule: Low severity pattern '{pattern_type}' - monitoring only"
            )

        # Medium severity - some we can handle
        if severity == "medium":
            if pattern_type in ("pump_sound_anomaly", "heating_ineffective", "low_runtime"):
                return HybridDecision(
                    tier_used=Tier.RULE_BASED,
                    action_required=False,
                    explanation=pattern.get("description", "Issue detected, monitoring"),
                    confidence=0.80,
                    reasoning=f"Rule: Medium pattern '{pattern_type}' - monitoring, may self-resolve"
                )

        # High severity single patterns - escalate for analysis
        return None

    def _handle_simple_patterns(self, patterns: list[dict], state: dict) -> Optional[HybridDecision]:
        """Handle two simple patterns together."""
        pattern_types = [p.get("type") for p in patterns]

        # Common combinations we can handle
        if set(pattern_types) <= {"low_runtime", "preheat_opportunity"}:
            return HybridDecision(
                tier_used=Tier.RULE_BASED,
                action_required=False,
                explanation="Low runtime and preheating opportunity noted",
                confidence=0.85,
                reasoning="Rule: Both patterns are informational only"
            )

        if set(pattern_types) <= {"off_hours_pump", "low_runtime"}:
            return HybridDecision(
                tier_used=Tier.RULE_BASED,
                action_required=False,
                explanation="Off-hours activity detected, monitoring",
                confidence=0.80,
                reasoning="Rule: Off-hours patterns are typically handled by automations"
            )

        return None  # Escalate other combinations


class HybridLLMManager:
    """Manages the 3-tier hybrid LLM system."""

    def __init__(
        self,
        claude_client,  # ClaudeClient instance
        ollama_url: str = "http://localhost:11434",
        ollama_model: str = "llama3.2:3b",
        hybrid_enabled: bool = True,
    ):
        self.claude_client = claude_client
        self.hybrid_enabled = hybrid_enabled
        self.stats = LLMStats()

        # Initialize components
        self.rule_analyzer = RuleBasedAnalyzer()
        self.ollama = OllamaClient(ollama_url, ollama_model) if hybrid_enabled else None

        # Ollama system prompt for pool analysis
        self.ollama_system_prompt = """You are a pool system analyzer. Analyze the given pool state and patterns.
Respond ONLY with valid JSON in this exact format:
{
    "action_required": true or false,
    "actions": [],
    "explanation": "brief explanation",
    "confidence": 0.0 to 1.0,
    "reasoning": "your reasoning",
    "needs_escalation": true or false
}

Set needs_escalation=true if:
- You're uncertain (confidence < 0.7)
- Multiple systems are affected
- The situation requires complex reasoning
- Safety-critical decisions are needed

Keep actions array empty unless you're very confident. Better to escalate than make wrong decisions."""

    async def initialize(self):
        """Initialize the hybrid system."""
        if self.ollama:
            available = await self.ollama.check_availability()
            if available:
                logger.info(f"Ollama available with model {self.ollama.model}")
            else:
                logger.warning("Ollama not available - will skip Tier 2")

    async def analyze(
        self,
        state: dict,
        patterns: dict,
        history: list[dict],
        question: str
    ) -> HybridDecision:
        """
        Analyze using the 3-tier hybrid system.

        Args:
            state: Current pool system state
            patterns: Detected patterns from PatternAnalyzer
            history: Recent decision history
            question: Analysis question

        Returns:
            HybridDecision with tier_used indicating which level handled it
        """
        pattern_list = patterns.get("patterns", [])

        # TIER 1: Rule-based analysis
        logger.debug("Tier 1: Attempting rule-based analysis")
        rule_decision = self.rule_analyzer.analyze(state, pattern_list)

        if rule_decision is not None:
            self.stats.rule_based_count += 1
            logger.info(
                f"Analysis handled by RULE_BASED "
                f"(confidence: {rule_decision.confidence:.2f}, cost: $0.0000)"
            )
            return rule_decision

        # TIER 2: Local Ollama LLM
        if self.ollama and self.ollama._available is not False:
            logger.debug("Tier 1 escalated - trying Tier 2: Local LLM")
            local_decision = await self._try_local_llm(state, patterns, question)

            if local_decision is not None:
                self.stats.local_count += 1
                logger.info(
                    f"Analysis handled by LOCAL "
                    f"(confidence: {local_decision.confidence:.2f}, cost: $0.0000)"
                )
                return local_decision

        # TIER 3: Claude API
        logger.debug("Escalating to Tier 3: Claude API")
        claude_decision = await self._call_claude(state, patterns, history, question)

        self.stats.claude_count += 1
        self.stats.total_cost_usd += claude_decision.cost_usd
        logger.info(
            f"Analysis handled by CLAUDE "
            f"(confidence: {claude_decision.confidence:.2f}, cost: ${claude_decision.cost_usd:.4f})"
        )

        self._log_stats()
        return claude_decision

    async def _try_local_llm(
        self,
        state: dict,
        patterns: dict,
        question: str
    ) -> Optional[HybridDecision]:
        """Try to get a decision from local Ollama LLM."""
        # Build a simplified prompt for the local model
        prompt = f"""Analyze this pool system state:

Current State Summary:
- Active Mode: {state.get('active_mode', 'unknown')}
- Water Temp: {state.get('water_temp', 'unknown')}°F
- Pump On: {state.get('pump_on', False)}
- Heater On: {state.get('heater_on', False)}

Detected Patterns:
{json.dumps(patterns.get('patterns', []), indent=2)}

Question: {question}

Respond with JSON only."""

        try:
            response = await self.ollama.generate(prompt, self.ollama_system_prompt)
            if not response:
                return None

            # Parse JSON response
            json_start = response.find("{")
            json_end = response.rfind("}") + 1

            if json_start == -1 or json_end == 0:
                logger.warning("Ollama response didn't contain valid JSON")
                return None

            data = json.loads(response[json_start:json_end])

            # Check if local model wants to escalate
            if data.get("needs_escalation", False):
                logger.debug("Local LLM requested escalation to Claude")
                return None

            confidence = data.get("confidence", 0.0)
            if confidence < 0.7:
                logger.debug(f"Local LLM confidence too low ({confidence}) - escalating")
                return None

            return HybridDecision(
                tier_used=Tier.LOCAL,
                action_required=data.get("action_required", False),
                actions=data.get("actions", []),
                explanation=data.get("explanation", ""),
                confidence=confidence,
                reasoning=data.get("reasoning", ""),
                cost_usd=0.0
            )

        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse Ollama JSON response: {e}")
            return None
        except Exception as e:
            logger.error(f"Local LLM error: {e}")
            return None

    async def _call_claude(
        self,
        state: dict,
        patterns: dict,
        history: list[dict],
        question: str
    ) -> HybridDecision:
        """Call Claude API for complex analysis."""
        if not self.claude_client:
            return HybridDecision(
                tier_used=Tier.CLAUDE,
                action_required=False,
                explanation="Claude API not available",
                confidence=0.0,
                reasoning="No API key configured"
            )

        # Get usage before call
        usage_before = self.claude_client.get_usage_stats()

        # Call Claude
        decision = await self.claude_client.analyze(state, patterns, history, question)

        # Calculate cost for this call
        usage_after = self.claude_client.get_usage_stats()
        call_cost = usage_after["estimated_cost_usd"] - usage_before["estimated_cost_usd"]

        return HybridDecision(
            tier_used=Tier.CLAUDE,
            action_required=decision.action_required,
            actions=decision.actions,
            explanation=decision.explanation,
            confidence=decision.confidence,
            reasoning=decision.reasoning,
            cost_usd=call_cost
        )

    def _log_stats(self):
        """Log current tier usage statistics."""
        if self.stats.total_count % 10 == 0:  # Log every 10 analyses
            pcts = self.stats.get_percentages()
            logger.info(
                f"LLM Stats: Rule-based: {pcts['rule_based']}%, "
                f"Local: {pcts['local']}%, Claude: {pcts['claude']}% "
                f"(Total cost: ${self.stats.total_cost_usd:.2f})"
            )

    def get_stats(self) -> dict:
        """Get current statistics."""
        pcts = self.stats.get_percentages()
        return {
            "total_analyses": self.stats.total_count,
            "rule_based_count": self.stats.rule_based_count,
            "local_count": self.stats.local_count,
            "claude_count": self.stats.claude_count,
            "rule_based_pct": pcts["rule_based"],
            "local_pct": pcts["local"],
            "claude_pct": pcts["claude"],
            "total_cost_usd": round(self.stats.total_cost_usd, 4),
            "ollama_available": self.ollama._available if self.ollama else False,
        }

    def reset_stats(self):
        """Reset statistics (e.g., daily reset)."""
        self.stats = LLMStats()
