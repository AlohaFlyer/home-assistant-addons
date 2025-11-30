#!/usr/bin/env python3
"""
Permission System for Claude Agent Manager

This module provides granular control over what actions each agent can
automatically execute vs. what requires human approval.

HOW TO USE:
1. Each agent has a whitelist of allowed actions
2. Actions not in the whitelist become RECOMMENDATIONS (logged, notified)
3. Use wildcards (*) to match patterns (e.g., "light.turn_off:light.exterior_*")
4. Edit AGENT_PERMISSIONS below to customize

SECURITY PRINCIPLE:
- Default: DENY all auto-actions
- Explicitly whitelist only safe, reversible actions
- Critical actions (locks, alarms, garage) require human approval
"""

import re
import logging
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger('claude_agent_manager.permissions')


class ActionResult(Enum):
    """Result of permission check."""
    ALLOWED = "allowed"           # Execute automatically
    DENIED = "denied"             # Not in whitelist - recommend only
    RATE_LIMITED = "rate_limited" # Too many actions recently
    COOLDOWN = "cooldown"         # Same action too soon


@dataclass
class PermissionCheck:
    """Result of checking an action against permissions."""
    result: ActionResult
    reason: str
    agent: str
    action: str
    entity: str


# ============================================================================
# AGENT PERMISSIONS CONFIGURATION
# ============================================================================
# Edit this section to control what each agent can do automatically.
#
# Format: "service.action:entity_id_pattern"
# Examples:
#   "switch.turn_on:switch.pool_pump"     - Exact match
#   "switch.turn_off:switch.pool_valve_*" - Wildcard (any pool valve)
#   "light.turn_off:light.*"              - All lights
#   "*:*"                                  - ALL actions (dangerous!)
#
# UNCOMMENT lines to ENABLE auto-execution
# COMMENT OUT lines to make them RECOMMENDATION-ONLY
# ============================================================================

AGENT_PERMISSIONS: Dict[str, Dict] = {
    # -------------------------------------------------------------------------
    # POWERWALL AGENT
    # Controls battery reserve and operation mode for TOU optimization
    # -------------------------------------------------------------------------
    "powerwall": {
        "description": "Battery/Solar/TOU optimization",
        "allowed_actions": [
            # Reserve adjustments (safe - Tesla has its own limits)
            "number.set_value:number.home_energy_gateway_backup_reserve",

            # Operation mode changes (safe - switches between modes)
            "select.select_option:select.home_energy_gateway_operation_mode",

            # COMMENTED = Recommendation only:
            # "select.select_option:select.home_energy_gateway_grid_charging",
        ],
        "max_actions_per_hour": 10,
        "cooldown_seconds": 60,  # Same action can't repeat within 60s
    },

    # -------------------------------------------------------------------------
    # LIGHT MANAGER AGENT
    # Handles relay/color sync and drift detection
    # -------------------------------------------------------------------------
    "light_manager": {
        "description": "Zigbee bulb sync and drift correction",
        "allowed_actions": [
            # Power cycling relays to fix sync (safe - just toggling)
            # "light.turn_off:light.*_relay",
            # "light.turn_on:light.*_relay",

            # Color corrections (safe - just setting colors)
            # "light.turn_on:light.*_color",
            # "light.turn_on:light.*_color_a",
            # "light.turn_on:light.*_color_b",

            # ALL COMMENTED = Recommendation only (default)
            # Uncomment above to enable auto-fix
        ],
        "max_actions_per_hour": 20,
        "cooldown_seconds": 30,
    },

    # -------------------------------------------------------------------------
    # HOT TUB AGENT
    # Temperature and schedule management
    # -------------------------------------------------------------------------
    "hot_tub": {
        "description": "Hot tub temperature and TOU scheduling",
        "allowed_actions": [
            # Temperature range changes (safe - within Balboa limits)
            "select.select_option:select.hot_tub_temperature_range",

            # Preset mode changes
            # "select.select_option:select.hot_tub_preset_mode",

            # Temperature setpoint (within safe range)
            # "climate.set_temperature:climate.hot_tub_thermostat",
        ],
        "max_actions_per_hour": 6,
        "cooldown_seconds": 300,  # 5 min cooldown
    },

    # -------------------------------------------------------------------------
    # MOWER AGENT
    # Gate coordination for Mammotion Luba 2
    # -------------------------------------------------------------------------
    "mower": {
        "description": "Mower gate coordination",
        "allowed_actions": [
            # Gate control for mower access (safe - mower needs this)
            "cover.open_cover:cover.driveway_gate",
            "cover.close_cover:cover.driveway_gate",
            "input_boolean.turn_on:input_boolean.gate_stay_open",
            "input_boolean.turn_off:input_boolean.gate_stay_open",

            # Mower task flag
            "input_boolean.turn_on:input_boolean.mower_driveway_task_active",
            "input_boolean.turn_off:input_boolean.mower_driveway_task_active",
        ],
        "max_actions_per_hour": 20,
        "cooldown_seconds": 10,
    },

    # -------------------------------------------------------------------------
    # GARAGE/GATE AGENT
    # Monitors doors but should NOT auto-control them (security)
    # -------------------------------------------------------------------------
    "garage": {
        "description": "Garage doors and gate monitoring",
        "allowed_actions": [
            # ALL COMMENTED = Recommendation only (SECURITY)
            # "cover.open_cover:cover.garage_*",
            # "cover.close_cover:cover.garage_*",
            # "cover.open_cover:cover.driveway_gate",
            # "cover.close_cover:cover.driveway_gate",
        ],
        "max_actions_per_hour": 5,
        "cooldown_seconds": 60,
    },

    # -------------------------------------------------------------------------
    # OCCUPANCY AGENT
    # Auto-off for idle rooms
    # -------------------------------------------------------------------------
    "occupancy": {
        "description": "Room occupancy and idle light control",
        "allowed_actions": [
            # Auto-off lights in unoccupied rooms (safe - energy saving)
            # Uncomment specific rooms to enable:
            # "light.turn_off:light.garage_*",
            # "light.turn_off:light.laundry_*",
            # "light.turn_off:light.pantry_*",

            # ALL COMMENTED = Recommendation only (default)
        ],
        "max_actions_per_hour": 30,
        "cooldown_seconds": 300,  # 5 min per room
    },

    # -------------------------------------------------------------------------
    # Z-WAVE AGENT
    # Network health and device recovery
    # -------------------------------------------------------------------------
    "zwave": {
        "description": "Z-Wave network health monitoring",
        "allowed_actions": [
            # Device ping/refresh (safe - just queries)
            "zwave_js.refresh_value:*",
            "button.press:button.*_ping",

            # DANGEROUS - requires manual approval:
            # "zwave_js.heal_node:*",
            # "zwave_js.remove_failed_node:*",
        ],
        "max_actions_per_hour": 50,
        "cooldown_seconds": 5,
    },

    # -------------------------------------------------------------------------
    # SECURITY AGENT
    # Camera monitoring - NO auto-actions (security critical)
    # -------------------------------------------------------------------------
    "security": {
        "description": "Frigate NVR and camera monitoring",
        "allowed_actions": [
            # ALL COMMENTED = Recommendation only (SECURITY CRITICAL)
            # "lock.lock:lock.*",
            # "lock.unlock:lock.*",
            # "alarm_control_panel.alarm_arm_*:*",
        ],
        "max_actions_per_hour": 0,  # No auto-actions
        "cooldown_seconds": 0,
    },

    # -------------------------------------------------------------------------
    # CLIMATE AGENT
    # Floor heating based on solar excess
    # -------------------------------------------------------------------------
    "climate": {
        "description": "Floor heating and solar excess optimization",
        "allowed_actions": [
            # Floor heating control (safe - thermostat has limits)
            "climate.turn_on:climate.bathroom_floor_thermostat",
            "climate.turn_off:climate.bathroom_floor_thermostat",
            "climate.set_temperature:climate.bathroom_floor_thermostat",

            # Input booleans for modes
            # "input_boolean.turn_on:input_boolean.bathroom_floors_on",
            # "input_boolean.turn_off:input_boolean.bathroom_floors_on",
        ],
        "max_actions_per_hour": 10,
        "cooldown_seconds": 300,
    },

    # -------------------------------------------------------------------------
    # AGENT SELECTOR (Meta-Agent)
    # Should NOT take actions directly
    # -------------------------------------------------------------------------
    "agent_selector": {
        "description": "Meta-agent that monitors all other agents",
        "allowed_actions": [
            # Notifications only (safe)
            "persistent_notification.create:*",
            "logbook.log:*",
        ],
        "max_actions_per_hour": 100,
        "cooldown_seconds": 0,
    },
}


class PermissionManager:
    """
    Manages action permissions for all agents.

    Usage:
        pm = PermissionManager()

        # Check if action is allowed
        check = pm.check_permission("powerwall", "number.set_value",
                                    "number.home_energy_gateway_backup_reserve")

        if check.result == ActionResult.ALLOWED:
            # Execute action
            pass
        else:
            # Log as recommendation
            pass
    """

    def __init__(self):
        self.permissions = AGENT_PERMISSIONS
        self.action_history: Dict[str, List[float]] = {}  # agent -> [timestamps]
        self.last_action: Dict[str, Dict[str, float]] = {}  # agent -> {action: timestamp}

    def check_permission(
        self,
        agent: str,
        service: str,
        entity_id: str,
        current_time: Optional[float] = None
    ) -> PermissionCheck:
        """
        Check if an agent is allowed to execute an action.

        Args:
            agent: Agent name (e.g., "powerwall", "light_manager")
            service: Service call (e.g., "switch.turn_on", "number.set_value")
            entity_id: Target entity (e.g., "switch.pool_pump")
            current_time: Current timestamp (for testing)

        Returns:
            PermissionCheck with result and reason
        """
        import time
        current_time = current_time or time.time()

        action_key = f"{service}:{entity_id}"

        # Check if agent exists in permissions
        if agent not in self.permissions:
            return PermissionCheck(
                result=ActionResult.DENIED,
                reason=f"Unknown agent: {agent}",
                agent=agent,
                action=service,
                entity=entity_id
            )

        agent_config = self.permissions[agent]
        allowed_actions = agent_config.get("allowed_actions", [])
        max_per_hour = agent_config.get("max_actions_per_hour", 10)
        cooldown = agent_config.get("cooldown_seconds", 60)

        # Check rate limit
        if max_per_hour == 0:
            return PermissionCheck(
                result=ActionResult.DENIED,
                reason=f"Agent {agent} has no auto-actions enabled",
                agent=agent,
                action=service,
                entity=entity_id
            )

        # Count actions in last hour
        if agent in self.action_history:
            hour_ago = current_time - 3600
            recent_actions = [t for t in self.action_history[agent] if t > hour_ago]
            self.action_history[agent] = recent_actions  # Clean up old entries

            if len(recent_actions) >= max_per_hour:
                return PermissionCheck(
                    result=ActionResult.RATE_LIMITED,
                    reason=f"Rate limited: {len(recent_actions)}/{max_per_hour} actions this hour",
                    agent=agent,
                    action=service,
                    entity=entity_id
                )

        # Check cooldown for same action
        if agent in self.last_action and action_key in self.last_action[agent]:
            last_time = self.last_action[agent][action_key]
            elapsed = current_time - last_time
            if elapsed < cooldown:
                return PermissionCheck(
                    result=ActionResult.COOLDOWN,
                    reason=f"Cooldown: {cooldown - elapsed:.0f}s remaining",
                    agent=agent,
                    action=service,
                    entity=entity_id
                )

        # Check if action matches any allowed pattern
        for pattern in allowed_actions:
            if self._matches_pattern(action_key, pattern):
                # Action is allowed - record it
                self._record_action(agent, action_key, current_time)

                return PermissionCheck(
                    result=ActionResult.ALLOWED,
                    reason=f"Matched pattern: {pattern}",
                    agent=agent,
                    action=service,
                    entity=entity_id
                )

        # No match found - denied
        return PermissionCheck(
            result=ActionResult.DENIED,
            reason=f"Action not in whitelist for {agent}",
            agent=agent,
            action=service,
            entity=entity_id
        )

    def _matches_pattern(self, action_key: str, pattern: str) -> bool:
        """
        Check if action_key matches a pattern with wildcard support.

        Examples:
            "switch.turn_on:switch.pool_pump" matches "switch.turn_on:switch.pool_pump"
            "switch.turn_off:switch.pool_valve_1" matches "switch.turn_off:switch.pool_valve_*"
            "light.turn_on:light.kitchen_main" matches "*:light.*"
        """
        # Convert wildcard pattern to regex
        regex_pattern = pattern.replace(".", r"\.").replace("*", ".*")
        regex_pattern = f"^{regex_pattern}$"

        return bool(re.match(regex_pattern, action_key))

    def _record_action(self, agent: str, action_key: str, timestamp: float):
        """Record that an action was executed."""
        # Record for rate limiting
        if agent not in self.action_history:
            self.action_history[agent] = []
        self.action_history[agent].append(timestamp)

        # Record for cooldown
        if agent not in self.last_action:
            self.last_action[agent] = {}
        self.last_action[agent][action_key] = timestamp

    def get_agent_stats(self, agent: str) -> Dict:
        """Get statistics for an agent's action usage."""
        import time
        current_time = time.time()
        hour_ago = current_time - 3600

        if agent not in self.permissions:
            return {"error": f"Unknown agent: {agent}"}

        config = self.permissions[agent]
        recent_count = 0
        if agent in self.action_history:
            recent_count = len([t for t in self.action_history[agent] if t > hour_ago])

        return {
            "agent": agent,
            "description": config.get("description", ""),
            "allowed_actions_count": len(config.get("allowed_actions", [])),
            "max_per_hour": config.get("max_actions_per_hour", 10),
            "actions_this_hour": recent_count,
            "remaining_actions": max(0, config.get("max_actions_per_hour", 10) - recent_count),
            "cooldown_seconds": config.get("cooldown_seconds", 60),
        }

    def get_all_stats(self) -> Dict[str, Dict]:
        """Get statistics for all agents."""
        return {agent: self.get_agent_stats(agent) for agent in self.permissions}

    def is_action_safe(self, service: str, entity_id: str) -> Tuple[bool, str]:
        """
        Quick check if an action is generally considered safe.
        Used as a secondary check even for allowed actions.
        """
        # Dangerous service patterns
        dangerous_services = [
            "homeassistant.restart",
            "homeassistant.stop",
            "zwave_js.remove_failed_node",
            "zwave_js.replace_failed_node",
            "persistent_notification.dismiss_all",
        ]

        if service in dangerous_services:
            return False, f"Service {service} is in dangerous list"

        # Dangerous entity patterns
        dangerous_entities = [
            "lock.*",       # Locks require human approval
            "alarm_*",      # Alarms require human approval
            "siren.*",      # Sirens require human approval
        ]

        for pattern in dangerous_entities:
            regex = pattern.replace(".", r"\.").replace("*", ".*")
            if re.match(f"^{regex}$", entity_id):
                return False, f"Entity {entity_id} matches dangerous pattern {pattern}"

        return True, "Action appears safe"


# Global instance for easy access
_permission_manager: Optional[PermissionManager] = None


def get_permission_manager() -> PermissionManager:
    """Get or create the global permission manager instance."""
    global _permission_manager
    if _permission_manager is None:
        _permission_manager = PermissionManager()
    return _permission_manager


def check_action_permission(agent: str, service: str, entity_id: str) -> PermissionCheck:
    """
    Convenience function to check action permission.

    Usage:
        from permissions import check_action_permission, ActionResult

        check = check_action_permission("powerwall", "number.set_value",
                                        "number.home_energy_gateway_backup_reserve")

        if check.result == ActionResult.ALLOWED:
            # Execute
            await ha_client.call_service(...)
        else:
            # Log recommendation
            logger.info(f"Recommendation: {check.reason}")
    """
    return get_permission_manager().check_permission(agent, service, entity_id)
