"""
Agent Manager - Orchestrates all agents with confirm-critical mode
"""

import os
import logging
import asyncio
from datetime import datetime
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field

from ha_client import HAClient
from hybrid_llm import HybridLLM, LLMResponse, DecisionTier
from agents import PoolAgent, LightsAgent, SecurityAgent, ClimateAgent, AgentCheck

logger = logging.getLogger(__name__)


@dataclass
class PendingAction:
    """An action waiting for user confirmation"""
    id: str
    agent_name: str
    decision: str
    action: Dict[str, Any]
    reasoning: str
    tier: DecisionTier
    created_at: datetime
    expires_at: datetime


@dataclass
class ManagerState:
    """Current state of the manager"""
    last_cycle: Optional[datetime] = None
    cycles_completed: int = 0
    pending_actions: List[PendingAction] = field(default_factory=list)
    recent_actions: List[Dict[str, Any]] = field(default_factory=list)


class AgentManager:
    """
    Orchestrates multiple agents with hybrid LLM decision-making.
    Implements confirm-critical mode: auto-fix minor issues, confirm major actions.
    """

    def __init__(self):
        self.ha_client = HAClient()
        self.llm = HybridLLM()
        self.state = ManagerState()

        self.check_interval = int(os.environ.get('CHECK_INTERVAL', '5'))
        self.confirm_critical = os.environ.get('CONFIRM_CRITICAL', 'true').lower() == 'true'

        # Initialize agents
        self.agents = {
            'pool': PoolAgent(self.ha_client),
            'lights': LightsAgent(self.ha_client),
            'security': SecurityAgent(self.ha_client),
            'climate': ClimateAgent(self.ha_client)
        }

        # Filter to enabled agents only
        enabled = os.environ.get('AGENTS_ENABLED', 'pool,lights,security,climate')
        enabled_list = [a.strip() for a in enabled.split(',')]
        self.agents = {k: v for k, v in self.agents.items() if k in enabled_list}

        logger.info(f"Manager initialized with agents: {list(self.agents.keys())}")

    async def run_cycle(self) -> Dict[str, Any]:
        """
        Run one monitoring cycle across all agents.
        Returns summary of findings and actions.
        """
        cycle_start = datetime.now()
        logger.info(f"Starting monitoring cycle at {cycle_start.isoformat()}")

        results = {
            "cycle_time": cycle_start.isoformat(),
            "agents": {},
            "actions_taken": [],
            "actions_pending": [],
            "errors": []
        }

        # Check each agent
        for agent_name, agent in self.agents.items():
            try:
                # Get agent's check results
                check = await agent.check()
                logger.info(f"[{agent_name}] Found {len(check.issues)} issues")

                # If issues found, analyze with LLM
                if check.issues:
                    context = {
                        "issues": check.issues,
                        "states": check.states,
                        "recent_events": check.recent_events
                    }

                    response = await self.llm.analyze(agent_name, context)

                    results["agents"][agent_name] = {
                        "issues": check.issues,
                        "decision": response.decision,
                        "confidence": response.confidence,
                        "tier": response.tier.name,
                        "action_required": response.action_required
                    }

                    # Handle the decision
                    if response.action_required and response.action:
                        await self._handle_action(agent_name, response, results)
                else:
                    results["agents"][agent_name] = {
                        "issues": [],
                        "decision": "all_normal",
                        "confidence": 1.0,
                        "tier": "RULE_BASED",
                        "action_required": False
                    }

            except Exception as e:
                logger.error(f"Error in {agent_name} agent: {e}")
                results["errors"].append({
                    "agent": agent_name,
                    "error": str(e)
                })

        # Update state
        self.state.last_cycle = cycle_start
        self.state.cycles_completed += 1

        # Log summary
        cycle_duration = (datetime.now() - cycle_start).total_seconds()
        logger.info(f"Cycle completed in {cycle_duration:.2f}s")

        return results

    async def _handle_action(self, agent_name: str, response: LLMResponse,
                            results: Dict[str, Any]) -> None:
        """Handle an action recommendation from the LLM"""

        action = response.action

        # If confirm-critical mode and action needs confirmation
        if self.confirm_critical and response.needs_confirmation:
            await self._queue_for_confirmation(agent_name, response)
            results["actions_pending"].append({
                "agent": agent_name,
                "decision": response.decision,
                "action": action,
                "reason": "Awaiting user confirmation"
            })
            return

        # Auto-execute non-critical actions
        success = await self._execute_action(action)

        action_record = {
            "agent": agent_name,
            "decision": response.decision,
            "action": action,
            "tier": response.tier.name,
            "success": success,
            "time": datetime.now().isoformat()
        }

        if success:
            results["actions_taken"].append(action_record)
            self.state.recent_actions.append(action_record)
            # Keep only last 50 actions
            if len(self.state.recent_actions) > 50:
                self.state.recent_actions = self.state.recent_actions[-50:]

            # Log to HA
            await self.ha_client.log_to_logbook(
                name=f"Agent Manager - {agent_name}",
                message=f"Action: {response.decision} - {response.reasoning}"
            )
        else:
            results["errors"].append({
                "agent": agent_name,
                "error": f"Failed to execute action: {response.decision}"
            })

    async def _queue_for_confirmation(self, agent_name: str,
                                      response: LLMResponse) -> None:
        """Queue a critical action for user confirmation"""

        pending = PendingAction(
            id=f"{agent_name}_{datetime.now().timestamp()}",
            agent_name=agent_name,
            decision=response.decision,
            action=response.action,
            reasoning=response.reasoning,
            tier=response.tier,
            created_at=datetime.now(),
            expires_at=datetime.now()  # Would set actual expiry
        )

        self.state.pending_actions.append(pending)

        # Send notification to user
        await self.ha_client.send_notification(
            title=f"🤖 Agent Action Requires Confirmation",
            message=(
                f"**Agent**: {agent_name}\n"
                f"**Action**: {response.decision}\n"
                f"**Reason**: {response.reasoning}\n"
                f"**Tier**: {response.tier.name}\n\n"
                f"Reply to this notification or check the Agent Manager UI to confirm or reject."
            ),
            notification_id=f"agent_confirm_{pending.id}"
        )

        logger.info(f"Queued action for confirmation: {pending.id}")

    async def _execute_action(self, action: Dict[str, Any]) -> bool:
        """Execute a service call action"""

        service_full = action.get('service', '')
        if '.' in service_full:
            domain, service = service_full.split('.', 1)
        else:
            logger.error(f"Invalid service format: {service_full}")
            return False

        target = action.get('target', {})
        data = action.get('data', {})

        return await self.ha_client.call_service(domain, service, target, data)

    async def confirm_action(self, action_id: str) -> bool:
        """User confirms a pending action"""

        for pending in self.state.pending_actions:
            if pending.id == action_id:
                success = await self._execute_action(pending.action)
                self.state.pending_actions.remove(pending)

                if success:
                    await self.ha_client.log_to_logbook(
                        name=f"Agent Manager - {pending.agent_name}",
                        message=f"User confirmed action: {pending.decision}"
                    )
                return success

        logger.warning(f"Pending action not found: {action_id}")
        return False

    async def reject_action(self, action_id: str) -> bool:
        """User rejects a pending action"""

        for pending in self.state.pending_actions:
            if pending.id == action_id:
                self.state.pending_actions.remove(pending)
                await self.ha_client.log_to_logbook(
                    name=f"Agent Manager - {pending.agent_name}",
                    message=f"User rejected action: {pending.decision}"
                )
                return True

        return False

    def get_stats(self) -> Dict[str, Any]:
        """Get manager statistics"""
        return {
            "cycles_completed": self.state.cycles_completed,
            "last_cycle": self.state.last_cycle.isoformat() if self.state.last_cycle else None,
            "pending_actions": len(self.state.pending_actions),
            "recent_actions_count": len(self.state.recent_actions),
            "llm_stats": self.llm.get_stats(),
            "agents_enabled": list(self.agents.keys())
        }
