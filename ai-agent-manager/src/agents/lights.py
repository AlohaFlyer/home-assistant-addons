"""
Lights Agent - Monitors lighting systems
"""

import logging
from datetime import datetime
from typing import Dict, Any, List
from .base import BaseAgent, AgentCheck

logger = logging.getLogger(__name__)


class LightsAgent(BaseAgent):
    """Monitors lighting systems"""

    def __init__(self, ha_client):
        super().__init__("lights", ha_client)

        self.monitored_entities = [
            # Exterior lights
            "light.exterior_lights",
            "light.front_porch",
            "light.back_porch",
            "light.garage_lights",

            # Pool area lights
            "switch.light_pool_zwave",
            "switch.light_hot_tub_zwave",

            # Sun state
            "sun.sun",
        ]

    async def get_monitored_entities(self) -> List[str]:
        return self.monitored_entities

    async def check(self) -> AgentCheck:
        """Perform lighting health check"""
        states = await self.get_states(self.monitored_entities)
        issues = []

        sun_state = states.get('sun.sun', 'unknown')
        current_hour = datetime.now().hour

        # Check exterior lights during day
        exterior = states.get('light.exterior_lights')
        if sun_state == 'above_horizon' and exterior == 'on':
            issues.append("exterior_lights_on_during_day: Exterior lights on during daylight")

        # Check all lights after 2 AM (should be off)
        if 2 <= current_hour < 6:
            for entity_id, state in states.items():
                if entity_id.startswith('light.') and state == 'on':
                    issues.append(f"late_night_lights: {entity_id} still on after 2 AM")

        # Check pool/hot tub lights during day (waste of energy)
        pool_light = states.get('switch.light_pool_zwave')
        hot_tub_light = states.get('switch.light_hot_tub_zwave')
        if sun_state == 'above_horizon':
            if pool_light == 'on':
                issues.append("pool_light_daytime: Pool light on during day")
            if hot_tub_light == 'on':
                issues.append("hot_tub_light_daytime: Hot tub light on during day")

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
            "auto_off_time": 2,  # 2 AM
            "daylight_exterior_off": True,
            "daylight_pool_lights_off": True
        }
