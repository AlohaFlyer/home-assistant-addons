"""Action executor with safety checks."""

import logging
from typing import Optional
from dataclasses import dataclass

from .ha_client import HAClient
from .state_monitor import PoolSystemState

logger = logging.getLogger(__name__)


@dataclass
class ActionResult:
    """Result of action execution."""
    success: bool
    action: dict
    message: str
    blocked_by_safety: bool = False


class ActionExecutor:
    """Executes actions from Claude decisions with safety validation."""

    # Safety: Actions that are always allowed
    ALWAYS_ALLOWED_ACTIONS = [
        ("script", "turn_on", "script.pool_emergency_all_stop"),
        ("persistent_notification", "create", None),
        ("notify", "notify", None),
    ]

    # Safety: Actions that require heating mode to be active
    HEATING_REQUIRED_ACTIONS = [
        ("climate", "set_temperature", "climate.pool_heater_wifi"),
        ("climate", "set_hvac_mode", "climate.pool_heater_wifi"),
    ]

    def __init__(self, ha_client: HAClient):
        self.ha_client = ha_client
        self._last_action_time: Optional[str] = None

    async def execute(
        self,
        actions: list[dict],
        current_state: PoolSystemState
    ) -> list[ActionResult]:
        """
        Execute a list of actions with safety validation.

        Args:
            actions: List of action dictionaries from Claude decision
            current_state: Current pool system state for safety checks

        Returns:
            List of ActionResult objects
        """
        results = []

        for action in actions:
            result = await self._execute_single_action(action, current_state)
            results.append(result)

            # Stop executing if a critical action failed
            if not result.success and action.get("critical", False):
                logger.warning(f"Critical action failed, stopping execution: {action}")
                break

        return results

    async def _execute_single_action(
        self,
        action: dict,
        current_state: PoolSystemState
    ) -> ActionResult:
        """Execute a single action with safety checks."""
        action_type = action.get("type", "")

        if action_type == "service_call":
            return await self._execute_service_call(action, current_state)
        elif action_type == "notification":
            return await self._send_notification(action)
        else:
            return ActionResult(
                success=False,
                action=action,
                message=f"Unknown action type: {action_type}"
            )

    async def _execute_service_call(
        self,
        action: dict,
        current_state: PoolSystemState
    ) -> ActionResult:
        """Execute a Home Assistant service call."""
        domain = action.get("domain", "")
        service = action.get("service", "")
        entity_id = action.get("entity_id", "")
        data = action.get("data", {})

        # Safety check
        safety_result = self._check_safety(domain, service, entity_id, current_state)
        if safety_result:
            return ActionResult(
                success=False,
                action=action,
                message=safety_result,
                blocked_by_safety=True
            )

        # Execute the service call
        success = await self.ha_client.call_service(
            domain=domain,
            service=service,
            entity_id=entity_id if entity_id else None,
            data=data if data else None
        )

        if success:
            logger.info(f"Action executed: {domain}.{service} on {entity_id}")
            return ActionResult(
                success=True,
                action=action,
                message=f"Successfully called {domain}.{service}"
            )
        else:
            return ActionResult(
                success=False,
                action=action,
                message=f"Failed to call {domain}.{service}"
            )

    async def _send_notification(self, action: dict) -> ActionResult:
        """Send a notification to the user."""
        message = action.get("message", "")
        title = action.get("title", "Pool AI Agent")
        notify_type = action.get("notify_type", "persistent")

        if notify_type == "mobile":
            success = await self.ha_client.send_mobile_notification(message, title)
        else:
            success = await self.ha_client.send_notification(message, title)

        return ActionResult(
            success=success,
            action=action,
            message="Notification sent" if success else "Failed to send notification"
        )

    def _check_safety(
        self,
        domain: str,
        service: str,
        entity_id: str,
        state: PoolSystemState
    ) -> Optional[str]:
        """
        Check if action passes safety rules.

        Returns:
            None if safe, or error message if blocked
        """
        # Always allowed actions
        for allowed_domain, allowed_service, allowed_entity in self.ALWAYS_ALLOWED_ACTIONS:
            if domain == allowed_domain and service == allowed_service:
                if allowed_entity is None or entity_id == allowed_entity:
                    return None

        # SAFETY RULE 1: Never enable heating if sensor failure detected
        if state.sensor_failure:
            if entity_id in ("input_boolean.hot_tub_heat", "input_boolean.pool_heat"):
                if service == "turn_on":
                    return "BLOCKED: Cannot enable heating - sensor failure detected"

        # SAFETY RULE 2: Never bypass sequence lock for mode changes
        if state.sequence_lock:
            if domain == "input_boolean" and service == "turn_on":
                if entity_id.startswith("input_boolean.pool_") or entity_id.startswith("input_boolean.hot_tub_"):
                    return "BLOCKED: Sequence lock active - wait for current operation to complete"

        # SAFETY RULE 3: Check Z-Wave availability for valve operations
        if state.zwave_unavailable:
            if "valve" in entity_id.lower():
                return f"BLOCKED: Z-Wave devices unavailable - cannot control valves"

            # Also block heating mode starts if valves are unavailable
            if entity_id in ("input_boolean.hot_tub_heat", "input_boolean.pool_heat"):
                if service == "turn_on":
                    return "BLOCKED: Z-Wave valves unavailable - cannot safely start heating mode"

        # SAFETY RULE 4: Heating actions require heating mode
        for req_domain, req_service, req_entity in self.HEATING_REQUIRED_ACTIONS:
            if domain == req_domain and service == req_service:
                if req_entity and entity_id == req_entity:
                    if state.active_mode not in ("hot_tub_heat", "pool_heat"):
                        return f"BLOCKED: {service} requires heating mode to be active"

        # SAFETY RULE 5: Prevent turning on conflicting modes
        if domain == "input_boolean" and service == "turn_on":
            if entity_id == "input_boolean.pool_skimmer" and state.pool_waterfall:
                return "BLOCKED: Cannot enable skimmer while waterfall is active"
            if entity_id == "input_boolean.pool_waterfall" and state.pool_skimmer:
                return "BLOCKED: Cannot enable waterfall while skimmer is active"

        return None  # All checks passed

    async def emergency_stop(self) -> bool:
        """Execute emergency stop script."""
        logger.warning("Executing EMERGENCY STOP")
        return await self.ha_client.call_service(
            domain="script",
            service="turn_on",
            entity_id="script.pool_emergency_all_stop"
        )
