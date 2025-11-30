"""Home Assistant API client for REST and WebSocket communication."""

import os
import json
import asyncio
import logging
from typing import Any, Callable, Optional
from dataclasses import dataclass

import aiohttp
import websockets

logger = logging.getLogger(__name__)


@dataclass
class EntityState:
    """Represents the state of a Home Assistant entity."""
    entity_id: str
    state: str
    attributes: dict
    last_changed: str
    last_updated: str


class HAClient:
    """Client for Home Assistant REST API and WebSocket."""

    def __init__(self):
        self.base_url = "http://supervisor/core/api"
        self.ws_url = "ws://supervisor/core/websocket"
        self.token = os.environ.get("SUPERVISOR_TOKEN", "")
        self._ws_connection = None
        self._ws_id = 0
        self._event_callbacks: list[Callable] = []

    @property
    def headers(self) -> dict:
        """Get authorization headers."""
        return {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }

    async def get_state(self, entity_id: str) -> Optional[EntityState]:
        """Get the current state of an entity."""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{self.base_url}/states/{entity_id}",
                    headers=self.headers
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        return EntityState(
                            entity_id=data["entity_id"],
                            state=data["state"],
                            attributes=data.get("attributes", {}),
                            last_changed=data.get("last_changed", ""),
                            last_updated=data.get("last_updated", ""),
                        )
                    else:
                        logger.error(f"Failed to get state for {entity_id}: {response.status}")
                        return None
        except Exception as e:
            logger.error(f"Error getting state for {entity_id}: {e}")
            return None

    async def get_states(self, entity_ids: list[str]) -> dict[str, EntityState]:
        """Get states for multiple entities."""
        states = {}
        tasks = [self.get_state(eid) for eid in entity_ids]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for entity_id, result in zip(entity_ids, results):
            if isinstance(result, EntityState):
                states[entity_id] = result
            elif isinstance(result, Exception):
                logger.error(f"Error fetching {entity_id}: {result}")

        return states

    async def get_all_states(self) -> list[EntityState]:
        """Get all entity states."""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{self.base_url}/states",
                    headers=self.headers
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        return [
                            EntityState(
                                entity_id=item["entity_id"],
                                state=item["state"],
                                attributes=item.get("attributes", {}),
                                last_changed=item.get("last_changed", ""),
                                last_updated=item.get("last_updated", ""),
                            )
                            for item in data
                        ]
                    else:
                        logger.error(f"Failed to get all states: {response.status}")
                        return []
        except Exception as e:
            logger.error(f"Error getting all states: {e}")
            return []

    async def call_service(
        self,
        domain: str,
        service: str,
        entity_id: Optional[str] = None,
        data: Optional[dict] = None
    ) -> bool:
        """Call a Home Assistant service."""
        payload = data or {}
        if entity_id:
            payload["entity_id"] = entity_id

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.base_url}/services/{domain}/{service}",
                    headers=self.headers,
                    json=payload
                ) as response:
                    if response.status in (200, 201):
                        logger.info(f"Service call successful: {domain}.{service}")
                        return True
                    else:
                        text = await response.text()
                        logger.error(f"Service call failed: {response.status} - {text}")
                        return False
        except Exception as e:
            logger.error(f"Error calling service {domain}.{service}: {e}")
            return False

    async def send_notification(
        self,
        message: str,
        title: str = "Pool AI Agent"
    ) -> bool:
        """Send a persistent notification."""
        return await self.call_service(
            "persistent_notification",
            "create",
            data={
                "message": message,
                "title": title,
                "notification_id": "pool_ai_agent"
            }
        )

    async def send_mobile_notification(
        self,
        message: str,
        title: str = "Pool AI Agent"
    ) -> bool:
        """Send a mobile app notification."""
        return await self.call_service(
            "notify",
            "notify",
            data={
                "message": message,
                "title": title,
            }
        )

    def register_event_callback(self, callback: Callable):
        """Register a callback for state change events."""
        self._event_callbacks.append(callback)

    async def _handle_ws_message(self, message: dict):
        """Handle incoming WebSocket messages."""
        if message.get("type") == "event":
            event_data = message.get("event", {})
            if event_data.get("event_type") == "state_changed":
                new_state = event_data.get("data", {}).get("new_state")
                if new_state:
                    entity_state = EntityState(
                        entity_id=new_state["entity_id"],
                        state=new_state["state"],
                        attributes=new_state.get("attributes", {}),
                        last_changed=new_state.get("last_changed", ""),
                        last_updated=new_state.get("last_updated", ""),
                    )
                    for callback in self._event_callbacks:
                        try:
                            await callback(entity_state)
                        except Exception as e:
                            logger.error(f"Error in event callback: {e}")

    async def _ws_send(self, websocket, message: dict) -> int:
        """Send a WebSocket message and return the message ID."""
        self._ws_id += 1
        message["id"] = self._ws_id
        await websocket.send(json.dumps(message))
        return self._ws_id

    async def connect_websocket(self, entity_filter: Optional[list[str]] = None):
        """Connect to Home Assistant WebSocket and subscribe to state changes."""
        retry_delay = 5

        while True:
            try:
                async with websockets.connect(self.ws_url) as websocket:
                    self._ws_connection = websocket
                    logger.info("WebSocket connected")

                    # Wait for auth required message
                    auth_required = json.loads(await websocket.recv())
                    if auth_required.get("type") != "auth_required":
                        logger.error(f"Unexpected message: {auth_required}")
                        continue

                    # Send auth
                    await websocket.send(json.dumps({
                        "type": "auth",
                        "access_token": self.token
                    }))

                    # Wait for auth result
                    auth_result = json.loads(await websocket.recv())
                    if auth_result.get("type") != "auth_ok":
                        logger.error(f"Auth failed: {auth_result}")
                        continue

                    logger.info("WebSocket authenticated")

                    # Subscribe to state changes
                    subscribe_msg = {
                        "type": "subscribe_events",
                        "event_type": "state_changed"
                    }
                    await self._ws_send(websocket, subscribe_msg)

                    # Receive subscription confirmation
                    confirm = json.loads(await websocket.recv())
                    if confirm.get("success"):
                        logger.info("Subscribed to state_changed events")

                    # Process incoming messages
                    async for message in websocket:
                        data = json.loads(message)

                        # Filter to pool entities if specified
                        if entity_filter and data.get("type") == "event":
                            entity_id = (
                                data.get("event", {})
                                .get("data", {})
                                .get("new_state", {})
                                .get("entity_id", "")
                            )
                            if entity_id and not any(
                                entity_id.startswith(f) or f in entity_id
                                for f in entity_filter
                            ):
                                continue

                        await self._handle_ws_message(data)

            except websockets.exceptions.ConnectionClosed:
                logger.warning("WebSocket connection closed, reconnecting...")
            except Exception as e:
                logger.error(f"WebSocket error: {e}")

            self._ws_connection = None
            logger.info(f"Reconnecting in {retry_delay} seconds...")
            await asyncio.sleep(retry_delay)

    async def check_connection(self) -> bool:
        """Check if HA API is accessible."""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{self.base_url}/",
                    headers=self.headers
                ) as response:
                    return response.status == 200
        except Exception as e:
            logger.error(f"Connection check failed: {e}")
            return False
