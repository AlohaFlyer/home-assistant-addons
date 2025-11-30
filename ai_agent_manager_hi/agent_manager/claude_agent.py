#!/usr/bin/env python3
"""Claude Agent integration for intelligent system analysis."""

import json
import logging
from datetime import datetime
from typing import Dict, List, Optional, Any

import anthropic

from permissions import check_action_permission, ActionResult

logger = logging.getLogger('claude_agent_manager.claude')


# Tool definitions for Claude
TOOLS = [
    {
        "name": "get_entity_state",
        "description": "Get the current state and attributes of a Home Assistant entity",
        "input_schema": {
            "type": "object",
            "properties": {
                "entity_id": {
                    "type": "string",
                    "description": "The entity ID (e.g., sensor.temperature, light.living_room)"
                }
            },
            "required": ["entity_id"]
        }
    },
    {
        "name": "get_entity_history",
        "description": "Get historical state changes for an entity over the past hours",
        "input_schema": {
            "type": "object",
            "properties": {
                "entity_id": {
                    "type": "string",
                    "description": "The entity ID to get history for"
                },
                "hours": {
                    "type": "integer",
                    "description": "Number of hours of history to retrieve (default: 24)",
                    "default": 24
                }
            },
            "required": ["entity_id"]
        }
    },
    {
        "name": "call_service",
        "description": "Call a Home Assistant service to take an action",
        "input_schema": {
            "type": "object",
            "properties": {
                "domain": {
                    "type": "string",
                    "description": "Service domain (e.g., light, switch, automation)"
                },
                "service": {
                    "type": "string",
                    "description": "Service name (e.g., turn_on, turn_off, reload)"
                },
                "data": {
                    "type": "object",
                    "description": "Optional service data",
                    "default": {}
                }
            },
            "required": ["domain", "service"]
        }
    },
    {
        "name": "send_notification",
        "description": "Send a notification to the user",
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "Notification title"
                },
                "message": {
                    "type": "string",
                    "description": "Notification message"
                },
                "priority": {
                    "type": "string",
                    "enum": ["low", "normal", "high"],
                    "description": "Notification priority",
                    "default": "normal"
                }
            },
            "required": ["title", "message"]
        }
    },
    {
        "name": "log_observation",
        "description": "Log an observation or pattern to the learning system",
        "input_schema": {
            "type": "object",
            "properties": {
                "category": {
                    "type": "string",
                    "description": "Observation category (e.g., pattern, anomaly, correlation)"
                },
                "description": {
                    "type": "string",
                    "description": "Description of the observation"
                },
                "entities_involved": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of entity IDs involved"
                },
                "confidence": {
                    "type": "number",
                    "description": "Confidence level (0.0 to 1.0)",
                    "default": 0.8
                }
            },
            "required": ["category", "description"]
        }
    }
]


SYSTEM_PROMPT = """You are an AI Agent Manager for a Home Assistant smart home system. You monitor and manage 9 specialized agents:

1. **Powerwall Agent** - Battery/solar/TOU optimization (Hawaii Electric TOU-RI rates)
   - Mid-Day (9am-5pm): $0.213/kWh (CHEAPEST)
   - On-Peak (5pm-10pm): $0.587/kWh (MOST EXPENSIVE)
   - Off-Peak (10pm-9am): $0.513/kWh

2. **Light Manager Agent** - Zigbee bulb sync, relay/color coordination, drift detection

3. **Hot Tub Agent** - Temperature management, TOU-aware scheduling (HIGH 9am-10pm, LOW overnight)

4. **Mower Agent** - Mammotion Luba 2 AWD coordination with driveway gate

5. **Garage/Gate Agent** - 3 garage doors + driveway gate, stay-open modes, obstruction detection

6. **Occupancy Agent** - 21 room occupancy sensors, auto-off for idle rooms

7. **Z-Wave Agent** - Large mesh network health (500+ entities)

8. **Security Agent** - Frigate NVR with 10 cameras

9. **Climate Agent** - Floor heating optimization using solar excess

Your responsibilities:
1. **Monitor**: Analyze all agent statuses and detect issues
2. **Correlate**: Find patterns across agents (e.g., high power draw affecting Powerwall goal)
3. **Predict**: Anticipate problems before they occur
4. **Act**: Take corrective actions when authorized
5. **Learn**: Identify recurring patterns for future optimization

When analyzing, consider:
- Time of day and TOU rates
- Correlations between agents (e.g., hot tub heating during expensive hours)
- Historical patterns
- Weather impacts on solar production
- Device health trends

Respond with structured JSON containing:
{
  "summary": "Brief overall status",
  "issues": [{"agent": "...", "severity": "info|warning|error", "description": "...", "action": {...}}],
  "optimizations": [{"description": "...", "auto_apply": true|false, "action": {...}}],
  "predictions": [{"type": "...", "description": "...", "confidence": 0.0-1.0, "preemptive_action": {...}}],
  "observations": [{"category": "...", "description": "...", "entities": [...]}]
}

For actions, use this format:
{
  "type": "call_service|set_state|enable_automation|trigger_script",
  "domain": "...",
  "service": "...",
  "entity_id": "...",
  "data": {...}
}
"""


class ClaudeAgentManager:
    """Claude-powered intelligent agent manager."""

    def __init__(self, api_key: str, ha_client, autonomous: bool = True):
        """Initialize the Claude agent.

        Args:
            api_key: Anthropic API key
            ha_client: HomeAssistantClient instance
            autonomous: Whether to allow autonomous actions
        """
        # Strip whitespace from API key (common copy-paste issue)
        self.client = anthropic.Anthropic(api_key=api_key.strip() if api_key else "")
        self.ha_client = ha_client
        self.autonomous = autonomous
        self.model = "claude-sonnet-4-20250514"  # Use Sonnet for good balance of speed/capability
        self.conversation_history = []

    async def analyze_system(
        self,
        agent_states: Dict[str, Any],
        historical_patterns: Optional[List[Dict]] = None,
        max_actions: int = 10
    ) -> Dict[str, Any]:
        """Analyze the current system state using Claude.

        Args:
            agent_states: Current state of all agents
            historical_patterns: Relevant historical patterns from learning system
            max_actions: Maximum autonomous actions allowed

        Returns:
            Analysis results with issues, optimizations, and predictions
        """
        # Build the analysis prompt
        prompt = self._build_analysis_prompt(agent_states, historical_patterns, max_actions)

        try:
            # Call Claude with tool use capability
            response = await self._call_claude(prompt)

            # Parse the response
            analysis = self._parse_response(response)

            return analysis

        except Exception as e:
            logger.error(f"Error in Claude analysis: {e}", exc_info=True)
            return {
                'summary': f'Analysis failed: {str(e)}',
                'issues': [],
                'optimizations': [],
                'predictions': [],
                'observations': []
            }

    def _build_analysis_prompt(
        self,
        agent_states: Dict[str, Any],
        patterns: Optional[List[Dict]],
        max_actions: int
    ) -> str:
        """Build the analysis prompt for Claude."""
        context = agent_states.get('_context', {})

        prompt = f"""Analyze the current state of all Home Assistant agents and provide recommendations.

## Current Context
- **Time**: {context.get('timestamp', 'Unknown')}
- **Period**: {context.get('time_of_day', 'Unknown')}
- **TOU Rate**: ${context.get('tou_rate', {}).get('rate', 0):.3f}/kWh ({context.get('tou_rate', {}).get('period', 'unknown')})
- **Autonomous Actions Remaining**: {max_actions}

## Agent States

"""
        # Add each agent's state
        for agent_name, agent_data in agent_states.items():
            if agent_name.startswith('_'):
                continue

            enabled = "✅ Enabled" if agent_data.get('enabled', True) else "❌ Disabled"
            prompt += f"### {agent_name.replace('_', ' ').title()} Agent ({enabled})\n"

            for sensor_id, sensor_data in agent_data.get('sensors', {}).items():
                state = sensor_data.get('state', 'unknown')
                prompt += f"- `{sensor_id}`: **{state}**\n"

            prompt += "\n"

        # Add historical patterns if available
        if patterns:
            prompt += "## Historical Patterns\n"
            for pattern in patterns[:5]:  # Limit to 5 most relevant
                prompt += f"- {pattern.get('description', 'Unknown pattern')}\n"
            prompt += "\n"

        prompt += """## Instructions

1. Analyze each agent's status and identify any issues
2. Look for correlations between agents
3. Check if current state aligns with time-of-day optimization (especially TOU rates)
4. Identify any predictable problems based on current trends
5. Suggest optimizations that could improve efficiency or reliability

Respond with structured JSON as specified in the system prompt.
"""

        return prompt

    async def _call_claude(self, prompt: str) -> str:
        """Call Claude API with the analysis prompt."""
        messages = [
            {"role": "user", "content": prompt}
        ]

        response = self.client.messages.create(
            model=self.model,
            max_tokens=4096,
            system=SYSTEM_PROMPT,
            tools=TOOLS if self.autonomous else [],
            messages=messages
        )

        # Handle tool use if requested
        while response.stop_reason == "tool_use":
            # Process tool calls
            tool_results = await self._process_tool_calls(response.content)

            # Continue conversation with tool results
            messages.append({"role": "assistant", "content": response.content})
            messages.append({"role": "user", "content": tool_results})

            response = self.client.messages.create(
                model=self.model,
                max_tokens=4096,
                system=SYSTEM_PROMPT,
                tools=TOOLS,
                messages=messages
            )

        # Extract text response
        for block in response.content:
            if hasattr(block, 'text'):
                return block.text

        return ""

    async def _process_tool_calls(self, content: List) -> List[Dict]:
        """Process tool calls from Claude's response."""
        results = []

        for block in content:
            if block.type == "tool_use":
                tool_name = block.name
                tool_input = block.input

                try:
                    result = await self._execute_tool(tool_name, tool_input)
                    results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": json.dumps(result)
                    })
                except Exception as e:
                    results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": json.dumps({"error": str(e)}),
                        "is_error": True
                    })

        return results

    async def _execute_tool(self, tool_name: str, tool_input: Dict) -> Any:
        """Execute a tool call."""
        if tool_name == "get_entity_state":
            entity_id = tool_input["entity_id"]
            state = await self.ha_client.get_full_state(entity_id)
            return state or {"error": "Entity not found"}

        elif tool_name == "get_entity_history":
            from datetime import timedelta
            entity_id = tool_input["entity_id"]
            hours = tool_input.get("hours", 24)
            start_time = (datetime.now() - timedelta(hours=hours)).isoformat()
            history = await self.ha_client.get_history(entity_id, start_time)
            return history[:100]  # Limit to last 100 entries

        elif tool_name == "call_service":
            if not self.autonomous:
                return {"error": "Autonomous actions disabled"}
            await self.ha_client.call_service(
                domain=tool_input["domain"],
                service=tool_input["service"],
                data=tool_input.get("data", {})
            )
            return {"success": True}

        elif tool_name == "send_notification":
            await self.ha_client.call_service(
                domain="persistent_notification",
                service="create",
                data={
                    "title": tool_input["title"],
                    "message": tool_input["message"]
                }
            )
            return {"success": True}

        elif tool_name == "log_observation":
            # This would be handled by the learning system
            logger.info(f"Observation: {tool_input}")
            return {"logged": True}

        else:
            return {"error": f"Unknown tool: {tool_name}"}

    def _parse_response(self, response_text: str) -> Dict[str, Any]:
        """Parse Claude's response into structured data."""
        try:
            # Try to extract JSON from the response
            # Handle case where JSON might be wrapped in markdown code blocks
            text = response_text.strip()

            if text.startswith("```json"):
                text = text[7:]
            elif text.startswith("```"):
                text = text[3:]

            if text.endswith("```"):
                text = text[:-3]

            return json.loads(text.strip())

        except json.JSONDecodeError:
            # If JSON parsing fails, try to extract meaningful content
            logger.warning("Failed to parse JSON response, using fallback")
            return {
                'summary': response_text[:500] if len(response_text) > 500 else response_text,
                'issues': [],
                'optimizations': [],
                'predictions': [],
                'observations': []
            }

    async def ask_question(self, question: str, context: Optional[Dict] = None) -> str:
        """Ask Claude a question about the system.

        Args:
            question: Natural language question
            context: Optional additional context

        Returns:
            Claude's response
        """
        prompt = question
        if context:
            prompt = f"Context:\n{json.dumps(context, indent=2)}\n\nQuestion: {question}"

        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=2048,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}]
            )

            for block in response.content:
                if hasattr(block, 'text'):
                    return block.text

            return "No response generated"

        except Exception as e:
            logger.error(f"Error asking question: {e}")
            return f"Error: {str(e)}"
