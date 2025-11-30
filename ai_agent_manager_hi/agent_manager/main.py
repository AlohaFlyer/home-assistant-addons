#!/usr/bin/env python3
"""
Claude Agent Manager - Main Entry Point

An AI-powered meta-agent that monitors and manages all Home Assistant agents
using Claude for intelligent decision-making and autonomous actions.
"""

import asyncio
import os
import logging
import json
from datetime import datetime
from typing import Optional

from ha_client import HomeAssistantClient
from claude_agent import ClaudeAgentManager
from hybrid_llm import HybridLLMManager, LLMTier
from learning import PatternLearner
from config import Config
from permissions import (
    PermissionManager, ActionResult, check_action_permission,
    get_permission_manager
)

# Configure logging
log_level = os.environ.get('LOG_LEVEL', 'info').upper()
logging.basicConfig(
    level=getattr(logging, log_level),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('claude_agent_manager')


class AgentManagerService:
    """Main service orchestrating the Claude Agent Manager."""

    def __init__(self):
        self.config = Config()
        self.ha_client: Optional[HomeAssistantClient] = None
        self.claude_agent: Optional[ClaudeAgentManager] = None
        self.hybrid_llm: Optional[HybridLLMManager] = None
        self.learner: Optional[PatternLearner] = None
        self.permission_manager: Optional[PermissionManager] = None
        self.running = False
        self.last_check = None
        self.action_count_this_hour = 0
        self.hour_start = datetime.now().replace(minute=0, second=0, microsecond=0)

    async def initialize(self):
        """Initialize all components."""
        logger.info("Initializing Claude Agent Manager...")

        # Initialize Home Assistant client
        self.ha_client = HomeAssistantClient(
            base_url=self.config.ha_url,
            token=self.config.ha_token or self.config.supervisor_token
        )
        await self.ha_client.connect()
        logger.info("Connected to Home Assistant")

        # Initialize Claude agent (for tool use and complex queries)
        self.claude_agent = ClaudeAgentManager(
            api_key=self.config.claude_api_key,
            ha_client=self.ha_client,
            autonomous=self.config.autonomous_actions
        )
        logger.info("Claude Agent initialized")

        # Initialize Hybrid LLM Manager (cost optimization)
        if self.config.hybrid_mode_enabled:
            self.hybrid_llm = HybridLLMManager(
                claude_api_key=self.config.claude_api_key,
                ollama_url=self.config.ollama_url,
                ollama_model=self.config.ollama_model,
                claude_model=self.config.claude_model,
                escalation_threshold=self.config.escalation_threshold
            )
            await self.hybrid_llm.initialize()
            logger.info(f"Hybrid LLM initialized: {self.config.get_llm_stats_summary()}")
        else:
            logger.info("Hybrid mode disabled - using Claude API only")

        # Initialize pattern learner
        if self.config.learning_enabled:
            self.learner = PatternLearner(
                storage_path="/config/claude_agent_manager/learning_data.json"
            )
            await self.learner.load()
            logger.info("Pattern learner initialized")

        # Initialize permission manager
        self.permission_manager = get_permission_manager()
        logger.info("Permission manager initialized")
        stats = self.permission_manager.get_all_stats()
        for agent, agent_stats in stats.items():
            allowed = agent_stats.get('allowed_actions_count', 0)
            if allowed > 0:
                logger.info(f"  {agent}: {allowed} allowed actions, "
                           f"{agent_stats.get('max_per_hour', 0)}/hr limit")

    async def run_check_cycle(self):
        """Run a single check cycle analyzing all agents."""
        logger.info("Starting agent check cycle...")

        try:
            # Collect all agent states
            agent_states = await self.collect_agent_states()

            # Get historical patterns if learning enabled
            patterns = None
            if self.learner:
                patterns = await self.learner.get_relevant_patterns(agent_states)

            # Use hybrid LLM if enabled (90%+ cost savings)
            if self.hybrid_llm:
                hybrid_result = await self.hybrid_llm.analyze(agent_states)

                # Log which tier handled the request
                logger.info(f"Analysis handled by {hybrid_result.tier.name} "
                           f"(confidence: {hybrid_result.confidence:.2f}, "
                           f"cost: ${hybrid_result.cost:.4f})")

                # If hybrid handled it with high confidence, use that result
                if not hybrid_result.escalate and hybrid_result.confidence >= self.config.escalation_threshold:
                    analysis = {
                        'summary': hybrid_result.summary,
                        'issues': hybrid_result.issues,
                        'optimizations': [],  # Simple analysis doesn't optimize
                        'predictions': [],
                        'observations': [],
                        '_tier': hybrid_result.tier.name,
                        '_cost': hybrid_result.cost
                    }
                else:
                    # Escalate to full Claude agent for complex analysis
                    logger.info("Escalating to full Claude analysis (tool use enabled)")
                    analysis = await self.claude_agent.analyze_system(
                        agent_states=agent_states,
                        historical_patterns=patterns,
                        max_actions=self.get_remaining_actions()
                    )
                    analysis['_tier'] = 'CLAUDE_FULL'
                    analysis['_cost'] = hybrid_result.cost  # Include hybrid attempt cost

                # Update stats
                stats = self.hybrid_llm.get_stats()
                logger.debug(f"LLM Stats: Rule-based: {stats.get('rule_based_pct', 0):.1f}%, "
                            f"Local: {stats.get('local_pct', 0):.1f}%, "
                            f"Claude: {stats.get('claude_pct', 0):.1f}%, "
                            f"Total cost: ${stats.get('total_cost', 0):.4f}")
            else:
                # No hybrid mode - use Claude directly
                analysis = await self.claude_agent.analyze_system(
                    agent_states=agent_states,
                    historical_patterns=patterns,
                    max_actions=self.get_remaining_actions()
                )

            # Process recommendations
            if analysis.get('issues'):
                await self.handle_issues(analysis['issues'])

            if analysis.get('optimizations'):
                await self.handle_optimizations(analysis['optimizations'])

            if analysis.get('predictions'):
                await self.handle_predictions(analysis['predictions'])

            # Record patterns for learning
            if self.learner and analysis.get('observations'):
                await self.learner.record_observation(
                    agent_states=agent_states,
                    analysis=analysis,
                    timestamp=datetime.now()
                )

            self.last_check = datetime.now()
            logger.info(f"Check cycle completed. Issues: {len(analysis.get('issues', []))}, "
                       f"Optimizations: {len(analysis.get('optimizations', []))}")

        except Exception as e:
            logger.error(f"Error in check cycle: {e}", exc_info=True)
            await self.send_notification(
                title="Agent Manager Error",
                message=f"Check cycle failed: {str(e)}",
                level="error"
            )

    async def collect_agent_states(self) -> dict:
        """Collect current state of all monitored agents."""
        agents = {}

        # Define all agents and their key sensors
        agent_sensors = {
            'powerwall': [
                'sensor.powerwall_agent_status',
                'sensor.powerwall_agent_100_by_5pm_projection',
                'sensor.powerwall_agent_charging_cost_status',
                'sensor.home_energy_gateway_battery',
                'sensor.home_energy_gateway_solar_power',
                'sensor.home_energy_gateway_grid_power'
            ],
            'light_manager': [
                'sensor.light_manager_status',
                'sensor.light_manager_total_issues',
                'sensor.light_manager_relay_color_sync_issues',
                'sensor.light_manager_drifted_lights'
            ],
            'hot_tub': [
                'sensor.hot_tub_agent_status',
                'sensor.hot_tub_agent_temperature_status',
                'sensor.hot_tub_agent_energy_today',
                'climate.hot_tub_thermostat'
            ],
            'mower': [
                'sensor.mower_agent_status',
                'sensor.mower_agent_gate_status',
                'sensor.mower_agent_battery_status',
                'sensor.mower_leclerc_16_battery'
            ],
            'garage': [
                'sensor.garage_agent_status',
                'sensor.garage_agent_open_count',
                'sensor.garage_agent_stay_open_status'
            ],
            'occupancy': [
                'sensor.occupancy_agent_status',
                'sensor.occupancy_agent_active_rooms',
                'sensor.occupancy_agent_idle_rooms'
            ],
            'zwave': [
                'sensor.z_wave_agent_status',
                'sensor.z_wave_agent_unavailable_count',
                'sensor.z_wave_agent_total_devices'
            ],
            'security': [
                'sensor.security_agent_status',
                'sensor.security_agent_cameras_online',
                'sensor.security_agent_recent_detections'
            ],
            'climate': [
                'sensor.climate_agent_status',
                'sensor.climate_agent_solar_excess',
                'sensor.climate_agent_floor_heating_status'
            ],
            'selector': [
                'sensor.agent_selector_status',
                'sensor.agent_selector_active_agents',
                'sensor.agent_selector_issues_total',
                'sensor.agent_selector_summary'
            ]
        }

        for agent_name, sensors in agent_sensors.items():
            agent_data = {'sensors': {}, 'enabled': True}

            # Check if agent is enabled
            enabled_entity = f"input_boolean.{agent_name}_agent_enabled"
            if agent_name == 'light_manager':
                enabled_entity = "input_boolean.light_manager_enabled"
            elif agent_name == 'selector':
                enabled_entity = "input_boolean.agent_selector_enabled"

            enabled_state = await self.ha_client.get_state(enabled_entity)
            agent_data['enabled'] = enabled_state == 'on' if enabled_state else True

            # Get all sensor states
            for sensor in sensors:
                state = await self.ha_client.get_state(sensor)
                attrs = await self.ha_client.get_attributes(sensor)
                agent_data['sensors'][sensor] = {
                    'state': state,
                    'attributes': attrs
                }

            agents[agent_name] = agent_data

        # Add system context
        agents['_context'] = {
            'timestamp': datetime.now().isoformat(),
            'time_of_day': self.get_time_period(),
            'tou_rate': self.get_current_tou_rate()
        }

        return agents

    def get_time_period(self) -> str:
        """Get current time period for context."""
        hour = datetime.now().hour
        if 5 <= hour < 9:
            return 'morning_off_peak'
        elif 9 <= hour < 17:
            return 'mid_day_cheap'
        elif 17 <= hour < 22:
            return 'on_peak_expensive'
        else:
            return 'night_off_peak'

    def get_current_tou_rate(self) -> dict:
        """Get current TOU electricity rate."""
        hour = datetime.now().hour
        if 9 <= hour < 17:
            return {'rate': 0.213, 'period': 'mid_day', 'is_cheap': True}
        elif 17 <= hour < 22:
            return {'rate': 0.587, 'period': 'on_peak', 'is_cheap': False}
        else:
            return {'rate': 0.513, 'period': 'off_peak', 'is_cheap': False}

    def get_remaining_actions(self) -> int:
        """Get remaining autonomous actions allowed this hour."""
        now = datetime.now()
        current_hour = now.replace(minute=0, second=0, microsecond=0)

        if current_hour > self.hour_start:
            self.hour_start = current_hour
            self.action_count_this_hour = 0

        return self.config.max_auto_fixes - self.action_count_this_hour

    async def handle_issues(self, issues: list):
        """Handle detected issues with appropriate actions."""
        for issue in issues:
            severity = issue.get('severity', 'info')
            agent = issue.get('agent', 'unknown')

            # Send notification based on level
            if self.should_notify(severity):
                await self.send_notification(
                    title=f"Agent Issue: {agent}",
                    message=issue.get('description', 'No description'),
                    level=severity
                )

            # Take autonomous action if enabled and available
            if (self.config.autonomous_actions and
                issue.get('action') and
                self.get_remaining_actions() > 0):

                # Pass agent name for permission checking
                success = await self.execute_action(issue['action'], agent=agent)
                if success:
                    self.action_count_this_hour += 1
                    logger.info(f"[{agent}] Executed autonomous action: {issue['action'].get('type')}")

    async def handle_optimizations(self, optimizations: list):
        """Handle optimization suggestions."""
        for opt in optimizations:
            agent = opt.get('agent', 'optimizer')
            if self.config.autonomous_actions and opt.get('auto_apply'):
                if self.get_remaining_actions() > 0:
                    success = await self.execute_action(opt['action'], agent=agent)
                    if success:
                        self.action_count_this_hour += 1
                        await self.send_notification(
                            title="Optimization Applied",
                            message=opt.get('description', 'Auto-optimization applied'),
                            level="info"
                        )
            else:
                # Log suggestion for manual review
                logger.info(f"[{agent}] Optimization suggestion: {opt.get('description')}")

    async def handle_predictions(self, predictions: list):
        """Handle predictive warnings."""
        for pred in predictions:
            agent = pred.get('agent', 'predictor')
            if pred.get('confidence', 0) > 0.7:  # High confidence predictions
                await self.send_notification(
                    title=f"Prediction: {pred.get('type', 'Unknown')}",
                    message=f"{pred.get('description')} (Confidence: {pred.get('confidence')*100:.0f}%)",
                    level="warning"
                )

                # Take preemptive action if enabled
                if (self.config.autonomous_actions and
                    pred.get('preemptive_action') and
                    self.get_remaining_actions() > 0):
                    success = await self.execute_action(pred['preemptive_action'], agent=agent)
                    if success:
                        self.action_count_this_hour += 1

    async def execute_action(self, action: dict, agent: str = "unknown") -> bool:
        """
        Execute an autonomous action with permission checking.

        Args:
            action: Action dict with type, domain, service, entity_id, data
            agent: Name of the agent requesting this action

        Returns:
            True if action was executed, False if denied or failed
        """
        try:
            action_type = action.get('type')

            # Build service and entity for permission check
            if action_type == 'call_service':
                domain = action.get('domain', '')
                service_name = action.get('service', '')
                service = f"{domain}.{service_name}"
                entity_id = action.get('data', {}).get('entity_id', '*')
            elif action_type == 'set_state':
                service = "homeassistant.set_state"
                entity_id = action.get('entity_id', '*')
            elif action_type == 'enable_automation':
                service = "automation.turn_on"
                entity_id = action.get('entity_id', '*')
            elif action_type == 'trigger_script':
                service = "script.turn_on"
                entity_id = action.get('entity_id', '*')
            else:
                logger.warning(f"Unknown action type: {action_type}")
                return False

            # Check permissions
            if self.permission_manager:
                perm_check = self.permission_manager.check_permission(
                    agent=agent,
                    service=service,
                    entity_id=entity_id
                )

                if perm_check.result != ActionResult.ALLOWED:
                    # Log as recommendation instead of executing
                    logger.info(f"[RECOMMENDATION] {agent}: {service} on {entity_id} "
                               f"- {perm_check.result.value}: {perm_check.reason}")

                    # Send notification for denied actions
                    await self.send_notification(
                        title=f"Action Recommendation: {agent}",
                        message=f"Suggested: {service} on {entity_id}\n"
                               f"Status: {perm_check.result.value}\n"
                               f"Reason: {perm_check.reason}",
                        level="info"
                    )
                    return False

                logger.info(f"[EXECUTING] {agent}: {service} on {entity_id} "
                           f"(matched: {perm_check.reason})")

            # Execute the action
            if action_type == 'call_service':
                domain = action.get('domain', '')
                service_name = action.get('service', '')

                # SAFETY: Prevent repeated HA restart attempts
                if domain == 'homeassistant' and service_name == 'restart':
                    if hasattr(self, '_last_restart_attempt'):
                        elapsed = (datetime.now() - self._last_restart_attempt).total_seconds()
                        if elapsed < 1800:  # 30 minute cooldown
                            logger.warning(f"Skipping HA restart - cooldown active ({1800-elapsed:.0f}s remaining)")
                            return False

                    self._last_restart_attempt = datetime.now()
                    logger.info("Initiating HA restart (cooldown set for 30 minutes)")

                await self.ha_client.call_service(
                    domain=domain,
                    service=service_name,
                    data=action.get('data', {})
                )
                return True

            elif action_type == 'set_state':
                await self.ha_client.set_state(
                    entity_id=action['entity_id'],
                    state=action['state']
                )
                return True

            elif action_type == 'enable_automation':
                await self.ha_client.call_service(
                    domain='automation',
                    service='turn_on',
                    data={'entity_id': action['entity_id']}
                )
                return True

            elif action_type == 'trigger_script':
                await self.ha_client.call_service(
                    domain='script',
                    service='turn_on',
                    data={'entity_id': action['entity_id']}
                )
                return True

        except Exception as e:
            logger.error(f"Failed to execute action: {e}")
            return False

    def should_notify(self, severity: str) -> bool:
        """Check if notification should be sent based on level."""
        levels = ['debug', 'info', 'warning', 'error']
        current_level = levels.index(self.config.notification_level)
        severity_level = levels.index(severity) if severity in levels else 1
        return severity_level >= current_level

    async def send_notification(self, title: str, message: str, level: str = 'info'):
        """Send notification through Home Assistant."""
        try:
            await self.ha_client.call_service(
                domain='persistent_notification',
                service='create',
                data={
                    'title': f"🤖 {title}",
                    'message': message,
                    'notification_id': f"claude_agent_{datetime.now().timestamp()}"
                }
            )

            # Also log to HA logbook
            await self.ha_client.call_service(
                domain='logbook',
                service='log',
                data={
                    'name': 'Claude Agent Manager',
                    'message': f"[{level.upper()}] {title}: {message}",
                    'entity_id': 'sensor.agent_selector_status'
                }
            )
        except Exception as e:
            logger.error(f"Failed to send notification: {e}")

    async def run(self):
        """Main run loop."""
        await self.initialize()
        self.running = True

        logger.info(f"Claude Agent Manager started. Check interval: {self.config.check_interval} minutes")

        # Send startup notification
        hybrid_status = "Hybrid LLM (cost-optimized)" if self.config.hybrid_mode_enabled else "Claude API only"
        await self.send_notification(
            title="Agent Manager Started",
            message=f"Monitoring 9 agents. Mode: {hybrid_status}. Autonomous: {self.config.autonomous_actions}, Learning: {self.config.learning_enabled}",
            level="info"
        )

        while self.running:
            try:
                await self.run_check_cycle()

                # Save learning data periodically
                if self.learner:
                    await self.learner.save()

            except Exception as e:
                logger.error(f"Error in main loop: {e}", exc_info=True)

            # Wait for next check interval
            await asyncio.sleep(self.config.check_interval * 60)

    async def shutdown(self):
        """Graceful shutdown."""
        logger.info("Shutting down Claude Agent Manager...")
        self.running = False

        if self.learner:
            await self.learner.save()

        if self.ha_client:
            await self.ha_client.disconnect()

        logger.info("Shutdown complete")


async def main():
    """Entry point."""
    service = AgentManagerService()

    try:
        await service.run()
    except KeyboardInterrupt:
        logger.info("Received shutdown signal")
    finally:
        await service.shutdown()


if __name__ == '__main__':
    asyncio.run(main())
