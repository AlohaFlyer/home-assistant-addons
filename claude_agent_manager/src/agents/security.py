"""
Security Agent - Monitors security systems
"""

import logging
from datetime import datetime
from typing import Dict, Any, List
from .base import BaseAgent, AgentCheck

logger = logging.getLogger(__name__)


class SecurityAgent(BaseAgent):
    """Monitors security systems (locks, cameras, doors)"""

    def __init__(self, ha_client):
        super().__init__("security", ha_client)

        # These are common security entities - adjust to your actual setup
        self.monitored_entities = [
            # Door locks (adjust entity IDs to match your setup)
            "lock.front_door",
            "lock.back_door",
            "lock.garage_door",

            # Door sensors
            "binary_sensor.front_door",
            "binary_sensor.back_door",
            "binary_sensor.garage_door",

            # Motion sensors
            "binary_sensor.front_yard_motion",
            "binary_sensor.back_yard_motion",

            # Cameras (Frigate)
            "camera.front_yard",
            "camera.back_yard",
            "camera.driveway",

            # Alarm
            "alarm_control_panel.home_alarm",
        ]

    async def get_monitored_entities(self) -> List[str]:
        return self.monitored_entities

    async def check(self) -> AgentCheck:
        """Perform security health check"""
        states = await self.get_states(self.monitored_entities)
        issues = []

        current_hour = datetime.now().hour
        is_night = current_hour >= 22 or current_hour < 6

        # Check locks at night
        if is_night:
            for entity_id, state in states.items():
                if entity_id.startswith('lock.') and state == 'unlocked':
                    issues.append(f"unlocked_at_night: {entity_id} is unlocked during night hours")

        # Check for doors left open
        for entity_id, state in states.items():
            if entity_id.startswith('binary_sensor.') and 'door' in entity_id:
                if state == 'on':  # on = open for door sensors
                    if is_night:
                        issues.append(f"door_open_night: {entity_id} open during night")
                    # Even during day, doors open for extended periods might be an issue
                    # Would need state history to detect this properly

        # Check cameras online
        for entity_id, state in states.items():
            if entity_id.startswith('camera.'):
                if state in ['unavailable', 'unknown']:
                    issues.append(f"camera_offline: {entity_id} is offline")

        # Check alarm state at night
        alarm = states.get('alarm_control_panel.home_alarm')
        if is_night and alarm == 'disarmed':
            issues.append("alarm_disarmed_night: Alarm disarmed during night hours")

        self.last_check = AgentCheck(
            agent_name=self.name,
            issues=issues,
            states=states,
            recent_events=[],
            check_time=datetime.now().isoformat()
        )

        return self.last_check

    def get_rules(self) -> Dict[str, Any]:
        return {
            "night_hours": {"start": 22, "end": 6},
            "lock_at_night": True,
            "arm_at_night": True,
            "cameras_required_online": True
        }
