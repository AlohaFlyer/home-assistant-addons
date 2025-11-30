"""
Home Assistant API Client
"""

import os
import logging
import aiohttp
from typing import Dict, Any, Optional, List

logger = logging.getLogger(__name__)


class HAClient:
    """Client for Home Assistant Supervisor API"""

    def __init__(self):
        self.base_url = os.environ.get('HA_URL', 'http://supervisor/core')
        self.token = os.environ.get('SUPERVISOR_TOKEN', '')

        if not self.token:
            logger.warning("SUPERVISOR_TOKEN not set - API calls will fail")

    @property
    def headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json"
        }

    async def get_state(self, entity_id: str) -> Optional[Dict[str, Any]]:
        """Get current state of an entity"""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{self.base_url}/api/states/{entity_id}",
                    headers=self.headers,
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as resp:
                    if resp.status == 200:
                        return await resp.json()
                    elif resp.status == 404:
                        logger.debug(f"Entity not found: {entity_id}")
                        return None
                    else:
                        logger.warning(f"Failed to get state for {entity_id}: {resp.status}")
                        return None
        except Exception as e:
            logger.error(f"Error getting state for {entity_id}: {e}")
            return None

    async def get_states(self, entity_ids: List[str]) -> Dict[str, Any]:
        """Get states for multiple entities"""
        states = {}
        for entity_id in entity_ids:
            state = await self.get_state(entity_id)
            if state:
                states[entity_id] = state.get('state', 'unknown')
        return states

    async def call_service(self, domain: str, service: str,
                          target: Optional[Dict[str, Any]] = None,
                          data: Optional[Dict[str, Any]] = None) -> bool:
        """Call a Home Assistant service"""
        payload = {}
        if target:
            payload.update(target)
        if data:
            payload.update(data)

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.base_url}/api/services/{domain}/{service}",
                    headers=self.headers,
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=30)
                ) as resp:
                    if resp.status in [200, 201]:
                        logger.info(f"Service called: {domain}.{service}")
                        return True
                    else:
                        logger.error(f"Service call failed: {domain}.{service} - {resp.status}")
                        return False
        except Exception as e:
            logger.error(f"Error calling service {domain}.{service}: {e}")
            return False

    async def send_notification(self, title: str, message: str,
                               notification_id: Optional[str] = None) -> bool:
        """Send a persistent notification"""
        data = {
            "title": title,
            "message": message
        }
        if notification_id:
            data["notification_id"] = notification_id

        return await self.call_service(
            "persistent_notification",
            "create",
            data=data
        )

    async def log_to_logbook(self, name: str, message: str,
                            entity_id: Optional[str] = None) -> bool:
        """Log an entry to the logbook"""
        data = {
            "name": name,
            "message": message
        }
        if entity_id:
            data["entity_id"] = entity_id

        return await self.call_service(
            "logbook",
            "log",
            data=data
        )

    async def is_healthy(self) -> bool:
        """Check if HA API is accessible"""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{self.base_url}/api/",
                    headers=self.headers,
                    timeout=aiohttp.ClientTimeout(total=5)
                ) as resp:
                    return resp.status == 200
        except Exception:
            return False
