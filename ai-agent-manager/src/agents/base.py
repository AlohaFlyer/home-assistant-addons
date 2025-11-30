"""
Base Agent class - all specialized agents inherit from this
"""

import logging
from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class AgentCheck:
    """Result of an agent's monitoring check"""
    agent_name: str
    issues: List[str]
    states: Dict[str, Any]
    recent_events: List[Dict[str, Any]]
    check_time: str


class BaseAgent(ABC):
    """Base class for all monitoring agents"""

    def __init__(self, name: str, ha_client):
        self.name = name
        self.ha_client = ha_client
        self.monitored_entities: List[str] = []
        self.last_check: Optional[AgentCheck] = None

    @abstractmethod
    async def get_monitored_entities(self) -> List[str]:
        """Return list of entity IDs this agent monitors"""
        pass

    @abstractmethod
    async def check(self) -> AgentCheck:
        """
        Perform monitoring check.
        Returns detected issues and current states.
        """
        pass

    @abstractmethod
    def get_rules(self) -> Dict[str, Any]:
        """Return the rule definitions for this agent"""
        pass

    async def get_states(self, entities: List[str]) -> Dict[str, Any]:
        """Fetch current states for a list of entities"""
        states = {}
        for entity_id in entities:
            state = await self.ha_client.get_state(entity_id)
            if state:
                states[entity_id] = state.get('state', 'unknown')
        return states

    async def get_recent_events(self, hours: int = 1) -> List[Dict[str, Any]]:
        """Get recent events for monitored entities (placeholder)"""
        # Would query logbook API in full implementation
        return []
