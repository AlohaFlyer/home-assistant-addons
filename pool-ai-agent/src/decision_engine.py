"""Decision engine that orchestrates the AI agent."""

import os
import logging
from typing import Optional
from datetime import datetime

from .ha_client import HAClient
from .claude_client import ClaudeClient, Decision
from .state_monitor import StateMonitor, PoolSystemState
from .pattern_analyzer import PatternAnalyzer, AnalysisResult
from .action_executor import ActionExecutor
from .database import Database
from .prompts.system import SYSTEM_PROMPT
from .hybrid_llm import HybridLLMManager, Tier

logger = logging.getLogger(__name__)


class DecisionEngine:
    """Orchestrates the AI decision-making process."""

    def __init__(
        self,
        ha_client: HAClient,
        database: Database,
    ):
        self.ha_client = ha_client
        self.database = database
        self.state_monitor = StateMonitor(ha_client)
        self.pattern_analyzer = PatternAnalyzer()
        self.action_executor = ActionExecutor(ha_client)
        self.claude_client: Optional[ClaudeClient] = None
        self.hybrid_manager: Optional[HybridLLMManager] = None

        self._last_decision_time: Optional[datetime] = None
        self._consecutive_errors = 0

    def initialize_claude(self):
        """Initialize Claude client (called after env vars are set)."""
        try:
            self.claude_client = ClaudeClient(SYSTEM_PROMPT)
            logger.info("Claude client initialized")
        except ValueError as e:
            logger.error(f"Failed to initialize Claude client: {e}")
            raise

    async def initialize_hybrid(self):
        """Initialize hybrid LLM manager for cost optimization."""
        hybrid_enabled = os.environ.get("HYBRID_MODE_ENABLED", "true").lower() == "true"
        ollama_url = os.environ.get("OLLAMA_URL", "http://homeassistant.local:11434")
        ollama_model = os.environ.get("OLLAMA_MODEL", "llama3.2:3b")

        self.hybrid_manager = HybridLLMManager(
            claude_client=self.claude_client,
            ollama_url=ollama_url,
            ollama_model=ollama_model,
            hybrid_enabled=hybrid_enabled,
        )

        await self.hybrid_manager.initialize()

        if hybrid_enabled:
            logger.info(
                f"Hybrid LLM mode enabled - Ollama: {ollama_url} ({ollama_model})"
            )
        else:
            logger.info("Hybrid LLM mode disabled - using Claude only")

    async def run_decision_cycle(self, trigger: str = "scheduled") -> dict:
        """
        Run a complete decision cycle.

        Args:
            trigger: What triggered this cycle (scheduled, event, startup)

        Returns:
            Dictionary with cycle results
        """
        cycle_result = {
            "timestamp": datetime.now().isoformat(),
            "trigger": trigger,
            "state_collected": False,
            "patterns_analyzed": False,
            "llm_called": False,
            "tier_used": None,
            "actions_taken": [],
            "errors": []
        }

        try:
            # Step 1: Collect current state
            logger.debug("Collecting current state...")
            state = await self.state_monitor.get_current_state()
            self.pattern_analyzer.add_state(state)
            self.database.save_state(state.to_dict())
            cycle_result["state_collected"] = True

            # Step 2: Run local pattern analysis
            logger.debug("Analyzing patterns...")
            analysis = self.pattern_analyzer.analyze(state)
            cycle_result["patterns_analyzed"] = True

            # Log any anomalies detected
            if analysis.patterns:
                self.database.increment_anomalies(len(analysis.patterns))
                for pattern in analysis.patterns:
                    logger.info(f"Pattern detected: {pattern.type} ({pattern.severity})")

            # Step 3: Determine if LLM analysis is needed
            if not analysis.needs_claude_analysis:
                logger.debug("No LLM analysis needed - system operating normally")
                cycle_result["reasoning"] = "System operating normally"
                cycle_result["tier_used"] = "none"
                self._consecutive_errors = 0
                return cycle_result

            # Step 4: Use Hybrid LLM Manager (or fall back to Claude-only)
            if self.hybrid_manager:
                logger.info(f"Running hybrid analysis: {analysis.analysis_reason}")
                hybrid_decision = await self.hybrid_manager.analyze(
                    state=state.to_dict(),
                    patterns=analysis.to_dict(),
                    history=self.database.get_recent_decisions(hours=24),
                    question=self._build_analysis_question(state, analysis)
                )

                cycle_result["llm_called"] = True
                cycle_result["tier_used"] = hybrid_decision.tier_used.value

                # Convert hybrid decision to standard format for rest of pipeline
                decision = Decision(
                    action_required=hybrid_decision.action_required,
                    actions=hybrid_decision.actions,
                    explanation=hybrid_decision.explanation,
                    confidence=hybrid_decision.confidence,
                    reasoning=hybrid_decision.reasoning,
                    raw_response=""
                )

                # Track cost in database (0 for rule-based and local)
                cost_usd = hybrid_decision.cost_usd

            elif self.claude_client:
                # Fallback: Claude-only mode
                logger.info(f"Calling Claude for analysis: {analysis.analysis_reason}")
                decision = await self.claude_client.analyze(
                    current_state=state.to_dict(),
                    patterns=analysis.to_dict(),
                    history=self.database.get_recent_decisions(hours=24),
                    question=self._build_analysis_question(state, analysis)
                )
                cycle_result["llm_called"] = True
                cycle_result["tier_used"] = "claude"
                cost_usd = self.claude_client.get_usage_stats().get("estimated_cost_usd", 0)
            else:
                logger.error("No LLM client available")
                cycle_result["errors"].append("No LLM client initialized")
                return cycle_result

            # Step 5: Save decision to database
            usage = self.claude_client.get_usage_stats() if self.claude_client else {}
            decision_id = self.database.save_decision(
                state_dict=state.to_dict(),
                patterns_dict=analysis.to_dict(),
                decision_dict={
                    "action_required": decision.action_required,
                    "actions": decision.actions,
                    "explanation": decision.explanation,
                    "confidence": decision.confidence,
                    "reasoning": decision.reasoning,
                    "tier_used": cycle_result["tier_used"],
                },
                input_tokens=usage.get("input_tokens", 0),
                output_tokens=usage.get("output_tokens", 0)
            )

            # Step 6: Execute actions if any
            if decision.action_required and decision.actions:
                logger.info(f"Executing {len(decision.actions)} actions...")
                results = await self.action_executor.execute(decision.actions, state)

                for result in results:
                    cycle_result["actions_taken"].append({
                        "action": result.action,
                        "success": result.success,
                        "message": result.message,
                        "blocked": result.blocked_by_safety
                    })

                    # Save action to database
                    self.database.save_action(
                        decision_id=decision_id,
                        action_dict=result.action,
                        success=result.success,
                        blocked_by_safety=result.blocked_by_safety,
                        message=result.message
                    )

                    if not result.success:
                        logger.warning(f"Action failed: {result.message}")

            # Step 7: Send notification if significant action taken
            if decision.explanation and decision.action_required:
                await self.ha_client.send_notification(
                    message=decision.explanation,
                    title="Pool AI Agent"
                )

            self._last_decision_time = datetime.now()
            self._consecutive_errors = 0
            cycle_result["reasoning"] = decision.reasoning

        except Exception as e:
            logger.error(f"Decision cycle error: {e}", exc_info=True)
            cycle_result["errors"].append(str(e))
            self._consecutive_errors += 1

            # If too many consecutive errors, alert user
            if self._consecutive_errors >= 3:
                await self.ha_client.send_notification(
                    message=f"Pool AI Agent experiencing errors: {e}. Please check logs.",
                    title="Pool AI Agent - Error"
                )

        return cycle_result

    def _build_analysis_question(
        self,
        state: PoolSystemState,
        analysis: AnalysisResult
    ) -> str:
        """Build the analysis question for Claude based on detected patterns."""
        questions = []

        # Build question based on patterns
        for pattern in analysis.patterns:
            if pattern.severity == "critical":
                questions.append(f"CRITICAL: {pattern.description}")
            elif pattern.severity == "high":
                questions.append(f"HIGH PRIORITY: {pattern.description}")

        if analysis.optimization_opportunity:
            questions.append("Consider optimization opportunities for the current system state.")

        if not questions:
            questions.append("Analyze the current system state and recommend any actions.")

        # Add context
        context_parts = [
            f"Current time: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
            f"Active mode: {state.active_mode}",
            f"Water temp: {state.water_temp}°F" if state.water_temp else "Water temp: unknown",
        ]

        return "\n".join(questions) + "\n\nContext:\n" + "\n".join(context_parts)

    async def handle_critical_event(self, entity_id: str, new_state: str, old_state: str):
        """
        Handle a critical event that requires immediate analysis.

        Called from WebSocket event handler for important state changes.
        """
        logger.info(f"Critical event: {entity_id} changed from {old_state} to {new_state}")

        # Determine if this warrants immediate analysis
        immediate_triggers = [
            # Sensor failure detected
            ("input_boolean.pool_sensor_failure_detected", "on"),
            # System health degraded
            ("input_boolean.pool_system_health_ok", "off"),
            # Emergency temperature readings
            ("sensor.pool_water_temperature_reliable", None),  # Any change
        ]

        for trigger_entity, trigger_state in immediate_triggers:
            if entity_id == trigger_entity:
                if trigger_state is None or new_state == trigger_state:
                    logger.warning(f"Immediate analysis triggered by {entity_id}")
                    await self.run_decision_cycle(trigger="critical_event")
                    return

        # Check for dangerous temperature
        if entity_id == "sensor.pool_water_temperature_reliable":
            try:
                temp = float(new_state)
                if temp > 105 or temp < 40:
                    logger.critical(f"Dangerous temperature detected: {temp}°F")
                    await self.action_executor.emergency_stop()
                    await self.ha_client.send_notification(
                        message=f"EMERGENCY: Water temperature {temp}°F is dangerous. Emergency stop executed.",
                        title="Pool AI Agent - EMERGENCY"
                    )
            except ValueError:
                pass

    def get_status(self) -> dict:
        """Get current agent status."""
        stats = self.database.get_daily_stats()

        status = {
            "status": "running",
            "last_decision": self._last_decision_time.isoformat() if self._last_decision_time else None,
            "consecutive_errors": self._consecutive_errors,
            "today": stats,
            "claude_usage": self.claude_client.get_usage_stats() if self.claude_client else None,
        }

        # Add hybrid LLM stats if available
        if self.hybrid_manager:
            status["hybrid_llm"] = self.hybrid_manager.get_stats()

        return status
