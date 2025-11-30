"""
Climate Agent - Monitors indoor climate systems
"""

import logging
from datetime import datetime
from typing import Dict, Any, List
from .base import BaseAgent, AgentCheck

logger = logging.getLogger(__name__)


class ClimateAgent(BaseAgent):
    """Monitors indoor climate/HVAC systems"""

    def __init__(self, ha_client):
        super().__init__("climate", ha_client)

        # Common climate entities - adjust to your setup
        self.monitored_entities = [
            # Thermostats
            "climate.thermostat",
            "climate.downstairs",
            "climate.upstairs",

            # Temperature sensors
            "sensor.indoor_temperature",
            "sensor.outdoor_temperature",

            # Humidity
            "sensor.indoor_humidity",
        ]

    async def get_monitored_entities(self) -> List[str]:
        return self.monitored_entities

    async def check(self) -> AgentCheck:
        """Perform climate health check"""
        states = await self.get_states(self.monitored_entities)
        issues = []

        # Check indoor temperature range (68-76°F comfortable)
        indoor_temp = states.get('sensor.indoor_temperature')
        if indoor_temp and indoor_temp not in ['unavailable', 'unknown']:
            try:
                temp_f = float(indoor_temp)
                if temp_f < 65:
                    issues.append(f"too_cold: Indoor temperature low ({temp_f}°F)")
                elif temp_f > 78:
                    issues.append(f"too_hot: Indoor temperature high ({temp_f}°F)")
            except (ValueError, TypeError):
                pass

        # Check HVAC systems availability
        for entity_id, state in states.items():
            if entity_id.startswith('climate.'):
                if state == 'unavailable':
                    issues.append(f"hvac_offline: {entity_id} is unavailable")

        # Check for high humidity (desert climate, indoor humidity should be low)
        humidity = states.get('sensor.indoor_humidity')
        if humidity and humidity not in ['unavailable', 'unknown']:
            try:
                humidity_pct = float(humidity)
                if humidity_pct > 60:
                    issues.append(f"high_humidity: Indoor humidity {humidity_pct}%")
            except (ValueError, TypeError):
                pass

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
            "temperature_range": {"min": 68, "max": 76},
            "humidity_max": 60,
            "hvac_required_online": True
        }
