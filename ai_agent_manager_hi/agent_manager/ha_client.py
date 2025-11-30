#!/usr/bin/env python3
"""Home Assistant API Client for Claude Agent Manager."""

import aiohttp
import asyncio
import logging
from typing import Optional, Any, Dict, List

logger = logging.getLogger('claude_agent_manager.ha_client')


class HomeAssistantClient:
    """Async client for Home Assistant REST API."""

    def __init__(self, base_url: str, token: str):
        """Initialize the client.

        Args:
            base_url: Home Assistant URL (e.g., http://supervisor/core)
            token: Long-lived access token or supervisor token
        """
        self.base_url = base_url.rstrip('/')
        self.token = token
        self.session: Optional[aiohttp.ClientSession] = None
        self._connected = False

    async def connect(self):
        """Establish connection to Home Assistant."""
        headers = {
            'Authorization': f'Bearer {self.token}',
            'Content-Type': 'application/json'
        }
        self.session = aiohttp.ClientSession(headers=headers)

        # Test connection
        try:
            async with self.session.get(f'{self.base_url}/api/') as resp:
                if resp.status == 200:
                    self._connected = True
                    data = await resp.json()
                    logger.info(f"Connected to Home Assistant: {data.get('message', 'OK')}")
                else:
                    raise ConnectionError(f"Failed to connect: HTTP {resp.status}")
        except Exception as e:
            logger.error(f"Connection failed: {e}")
            raise

    async def disconnect(self):
        """Close the connection."""
        if self.session:
            await self.session.close()
            self._connected = False

    @property
    def is_connected(self) -> bool:
        """Check if connected."""
        return self._connected and self.session is not None

    async def get_state(self, entity_id: str) -> Optional[str]:
        """Get the state of an entity.

        Args:
            entity_id: Entity ID (e.g., sensor.temperature)

        Returns:
            State value as string, or None if not found
        """
        if not self.is_connected:
            return None

        try:
            async with self.session.get(
                f'{self.base_url}/api/states/{entity_id}'
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data.get('state')
                elif resp.status == 404:
                    logger.debug(f"Entity not found: {entity_id}")
                    return None
                else:
                    logger.warning(f"Error getting state for {entity_id}: HTTP {resp.status}")
                    return None
        except Exception as e:
            logger.error(f"Error getting state for {entity_id}: {e}")
            return None

    async def get_attributes(self, entity_id: str) -> Optional[Dict[str, Any]]:
        """Get the attributes of an entity.

        Args:
            entity_id: Entity ID

        Returns:
            Dictionary of attributes, or None if not found
        """
        if not self.is_connected:
            return None

        try:
            async with self.session.get(
                f'{self.base_url}/api/states/{entity_id}'
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data.get('attributes', {})
                return None
        except Exception as e:
            logger.error(f"Error getting attributes for {entity_id}: {e}")
            return None

    async def get_full_state(self, entity_id: str) -> Optional[Dict[str, Any]]:
        """Get the full state object of an entity.

        Args:
            entity_id: Entity ID

        Returns:
            Full state dictionary, or None if not found
        """
        if not self.is_connected:
            return None

        try:
            async with self.session.get(
                f'{self.base_url}/api/states/{entity_id}'
            ) as resp:
                if resp.status == 200:
                    return await resp.json()
                return None
        except Exception as e:
            logger.error(f"Error getting full state for {entity_id}: {e}")
            return None

    async def get_all_states(self) -> List[Dict[str, Any]]:
        """Get all entity states.

        Returns:
            List of all state dictionaries
        """
        if not self.is_connected:
            return []

        try:
            async with self.session.get(f'{self.base_url}/api/states') as resp:
                if resp.status == 200:
                    return await resp.json()
                return []
        except Exception as e:
            logger.error(f"Error getting all states: {e}")
            return []

    async def set_state(self, entity_id: str, state: str, attributes: Optional[Dict] = None):
        """Set the state of an entity (for virtual entities).

        Args:
            entity_id: Entity ID
            state: New state value
            attributes: Optional attributes to set
        """
        if not self.is_connected:
            raise ConnectionError("Not connected to Home Assistant")

        data = {'state': state}
        if attributes:
            data['attributes'] = attributes

        try:
            async with self.session.post(
                f'{self.base_url}/api/states/{entity_id}',
                json=data
            ) as resp:
                if resp.status not in (200, 201):
                    text = await resp.text()
                    raise Exception(f"Failed to set state: HTTP {resp.status} - {text}")
        except Exception as e:
            logger.error(f"Error setting state for {entity_id}: {e}")
            raise

    async def call_service(self, domain: str, service: str, data: Optional[Dict] = None):
        """Call a Home Assistant service.

        Args:
            domain: Service domain (e.g., 'light', 'switch')
            service: Service name (e.g., 'turn_on', 'turn_off')
            data: Optional service data
        """
        if not self.is_connected:
            raise ConnectionError("Not connected to Home Assistant")

        try:
            async with self.session.post(
                f'{self.base_url}/api/services/{domain}/{service}',
                json=data or {}
            ) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    raise Exception(f"Service call failed: HTTP {resp.status} - {text}")
                return await resp.json()
        except Exception as e:
            logger.error(f"Error calling service {domain}.{service}: {e}")
            raise

    async def fire_event(self, event_type: str, event_data: Optional[Dict] = None):
        """Fire a Home Assistant event.

        Args:
            event_type: Event type name
            event_data: Optional event data
        """
        if not self.is_connected:
            raise ConnectionError("Not connected to Home Assistant")

        try:
            async with self.session.post(
                f'{self.base_url}/api/events/{event_type}',
                json=event_data or {}
            ) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    raise Exception(f"Failed to fire event: HTTP {resp.status} - {text}")
        except Exception as e:
            logger.error(f"Error firing event {event_type}: {e}")
            raise

    async def get_history(
        self,
        entity_id: str,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Get history for an entity.

        Args:
            entity_id: Entity ID
            start_time: ISO format start time
            end_time: ISO format end time

        Returns:
            List of historical state changes
        """
        if not self.is_connected:
            return []

        params = {'filter_entity_id': entity_id}
        url = f'{self.base_url}/api/history/period'

        if start_time:
            url = f'{url}/{start_time}'

        try:
            async with self.session.get(url, params=params) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data[0] if data else []
                return []
        except Exception as e:
            logger.error(f"Error getting history for {entity_id}: {e}")
            return []

    async def get_logbook(
        self,
        entity_id: Optional[str] = None,
        start_time: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Get logbook entries.

        Args:
            entity_id: Optional entity ID to filter
            start_time: Optional ISO format start time

        Returns:
            List of logbook entries
        """
        if not self.is_connected:
            return []

        params = {}
        if entity_id:
            params['entity'] = entity_id

        url = f'{self.base_url}/api/logbook'
        if start_time:
            url = f'{url}/{start_time}'

        try:
            async with self.session.get(url, params=params) as resp:
                if resp.status == 200:
                    return await resp.json()
                return []
        except Exception as e:
            logger.error(f"Error getting logbook: {e}")
            return []

    async def get_config(self) -> Optional[Dict[str, Any]]:
        """Get Home Assistant configuration.

        Returns:
            Configuration dictionary
        """
        if not self.is_connected:
            return None

        try:
            async with self.session.get(f'{self.base_url}/api/config') as resp:
                if resp.status == 200:
                    return await resp.json()
                return None
        except Exception as e:
            logger.error(f"Error getting config: {e}")
            return None
