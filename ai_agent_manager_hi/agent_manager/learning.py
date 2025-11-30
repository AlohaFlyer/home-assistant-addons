#!/usr/bin/env python3
"""Pattern learning and observation storage for Claude Agent Manager."""

import json
import logging
import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from collections import defaultdict
from dataclasses import dataclass, asdict

logger = logging.getLogger('claude_agent_manager.learning')


@dataclass
class Pattern:
    """A detected pattern in the system."""
    id: str
    category: str  # 'timing', 'correlation', 'anomaly', 'sequence', 'optimization'
    description: str
    entities: List[str]
    confidence: float
    occurrences: int
    first_seen: str
    last_seen: str
    metadata: Dict[str, Any]


@dataclass
class Observation:
    """A single observation recorded by the system."""
    timestamp: str
    agent_states: Dict[str, Any]
    analysis_summary: str
    issues_count: int
    actions_taken: List[Dict]
    patterns_detected: List[str]


class PatternLearner:
    """Learns and stores patterns from system observations."""

    def __init__(self, storage_path: str):
        """Initialize the pattern learner.

        Args:
            storage_path: Path to store learning data
        """
        self.storage_path = storage_path
        self.patterns: Dict[str, Pattern] = {}
        self.observations: List[Observation] = []
        self.correlations: Dict[str, Dict[str, float]] = defaultdict(lambda: defaultdict(float))
        self.timing_patterns: Dict[int, Dict[str, int]] = defaultdict(lambda: defaultdict(int))

        # Ensure storage directory exists
        os.makedirs(os.path.dirname(storage_path), exist_ok=True)

    async def load(self):
        """Load learning data from storage."""
        if os.path.exists(self.storage_path):
            try:
                with open(self.storage_path, 'r') as f:
                    data = json.load(f)

                # Load patterns
                for pid, pdata in data.get('patterns', {}).items():
                    self.patterns[pid] = Pattern(**pdata)

                # Load observations (keep last 1000)
                for obs_data in data.get('observations', [])[-1000:]:
                    self.observations.append(Observation(**obs_data))

                # Load correlations
                self.correlations = defaultdict(
                    lambda: defaultdict(float),
                    {k: defaultdict(float, v) for k, v in data.get('correlations', {}).items()}
                )

                # Load timing patterns
                self.timing_patterns = defaultdict(
                    lambda: defaultdict(int),
                    {int(k): defaultdict(int, v) for k, v in data.get('timing_patterns', {}).items()}
                )

                logger.info(f"Loaded {len(self.patterns)} patterns, {len(self.observations)} observations")

            except Exception as e:
                logger.error(f"Error loading learning data: {e}")
        else:
            logger.info("No existing learning data found, starting fresh")

    async def save(self):
        """Save learning data to storage."""
        try:
            data = {
                'patterns': {pid: asdict(p) for pid, p in self.patterns.items()},
                'observations': [asdict(o) for o in self.observations[-1000:]],  # Keep last 1000
                'correlations': dict(self.correlations),
                'timing_patterns': {str(k): dict(v) for k, v in self.timing_patterns.items()},
                'last_saved': datetime.now().isoformat()
            }

            with open(self.storage_path, 'w') as f:
                json.dump(data, f, indent=2)

            logger.debug("Saved learning data")

        except Exception as e:
            logger.error(f"Error saving learning data: {e}")

    async def record_observation(
        self,
        agent_states: Dict[str, Any],
        analysis: Dict[str, Any],
        timestamp: datetime
    ):
        """Record an observation for learning.

        Args:
            agent_states: Current state of all agents
            analysis: Claude's analysis results
            timestamp: Time of observation
        """
        # Create observation record
        obs = Observation(
            timestamp=timestamp.isoformat(),
            agent_states=self._summarize_states(agent_states),
            analysis_summary=analysis.get('summary', ''),
            issues_count=len(analysis.get('issues', [])),
            actions_taken=[],
            patterns_detected=[]
        )

        self.observations.append(obs)

        # Update timing patterns
        hour = timestamp.hour
        for agent_name, agent_data in agent_states.items():
            if agent_name.startswith('_'):
                continue

            for sensor_id, sensor_data in agent_data.get('sensors', {}).items():
                if 'status' in sensor_id:
                    state = sensor_data.get('state', 'unknown')
                    key = f"{sensor_id}:{state}"
                    self.timing_patterns[hour][key] += 1

        # Detect correlations
        await self._detect_correlations(agent_states)

        # Analyze for new patterns
        new_patterns = await self._analyze_patterns(agent_states, analysis, timestamp)
        obs.patterns_detected = [p.id for p in new_patterns]

        # Log observations from Claude
        for observation in analysis.get('observations', []):
            await self._record_claude_observation(observation, timestamp)

    def _summarize_states(self, agent_states: Dict[str, Any]) -> Dict[str, str]:
        """Create a summary of agent states for storage."""
        summary = {}
        for agent_name, agent_data in agent_states.items():
            if agent_name.startswith('_'):
                continue

            # Get the primary status sensor
            for sensor_id, sensor_data in agent_data.get('sensors', {}).items():
                if 'status' in sensor_id and 'agent' in sensor_id:
                    summary[agent_name] = sensor_data.get('state', 'unknown')
                    break

        return summary

    async def _detect_correlations(self, agent_states: Dict[str, Any]):
        """Detect correlations between agent states."""
        # Get current states
        current_states = {}
        for agent_name, agent_data in agent_states.items():
            if agent_name.startswith('_'):
                continue

            for sensor_id, sensor_data in agent_data.get('sensors', {}).items():
                state = sensor_data.get('state')
                if state:
                    current_states[sensor_id] = state

        # Update correlation matrix
        sensors = list(current_states.keys())
        for i, sensor1 in enumerate(sensors):
            for sensor2 in sensors[i+1:]:
                # Simple co-occurrence tracking
                state1 = current_states[sensor1]
                state2 = current_states[sensor2]

                # Track which states occur together
                key = f"{state1}|{state2}"
                self.correlations[f"{sensor1}:{sensor2}"][key] += 1

    async def _analyze_patterns(
        self,
        agent_states: Dict[str, Any],
        analysis: Dict[str, Any],
        timestamp: datetime
    ) -> List[Pattern]:
        """Analyze current state for patterns."""
        new_patterns = []
        current_time = timestamp.isoformat()

        # Pattern: Recurring issues at same time
        hour = timestamp.hour
        for issue in analysis.get('issues', []):
            agent = issue.get('agent', 'unknown')
            severity = issue.get('severity', 'info')

            pattern_id = f"timing_{agent}_{hour}_{severity}"
            if pattern_id in self.patterns:
                # Update existing pattern
                pattern = self.patterns[pattern_id]
                pattern.occurrences += 1
                pattern.last_seen = current_time
                pattern.confidence = min(0.95, pattern.confidence + 0.05)
            else:
                # Check if this is a recurring issue at this hour
                timing_key = f"issue_{agent}_{severity}"
                if self.timing_patterns[hour].get(timing_key, 0) >= 2:
                    # This issue has occurred at this hour multiple times
                    pattern = Pattern(
                        id=pattern_id,
                        category='timing',
                        description=f"{agent} agent tends to have {severity} issues around {hour}:00",
                        entities=[],
                        confidence=0.6,
                        occurrences=1,
                        first_seen=current_time,
                        last_seen=current_time,
                        metadata={'hour': hour, 'severity': severity}
                    )
                    self.patterns[pattern_id] = pattern
                    new_patterns.append(pattern)

                self.timing_patterns[hour][timing_key] += 1

        # Pattern: Agent state sequences
        recent_obs = self.observations[-10:]
        if len(recent_obs) >= 3:
            for agent_name in agent_states.keys():
                if agent_name.startswith('_'):
                    continue

                states = [o.agent_states.get(agent_name, 'unknown') for o in recent_obs]
                states.append(self._summarize_states(agent_states).get(agent_name, 'unknown'))

                # Look for repeating sequences
                if len(states) >= 4:
                    for seq_len in range(2, min(4, len(states)//2)):
                        seq = tuple(states[-seq_len:])
                        prev_seq = tuple(states[-(seq_len*2):-seq_len])
                        # Skip if sequence contains None values
                        if any(s is None for s in seq) or any(s is None for s in prev_seq):
                            continue
                        if seq == prev_seq:
                            pattern_id = f"sequence_{agent_name}_{hash(seq)}"
                            if pattern_id not in self.patterns:
                                # Convert to strings to ensure join works
                                seq_strs = [str(s) if s is not None else 'unknown' for s in seq]
                                pattern = Pattern(
                                    id=pattern_id,
                                    category='sequence',
                                    description=f"{agent_name} shows repeating pattern: {' -> '.join(seq_strs)}",
                                    entities=[],
                                    confidence=0.5,
                                    occurrences=1,
                                    first_seen=current_time,
                                    last_seen=current_time,
                                    metadata={'sequence': list(seq)}
                                )
                                self.patterns[pattern_id] = pattern
                                new_patterns.append(pattern)

        return new_patterns

    async def _record_claude_observation(self, observation: Dict, timestamp: datetime):
        """Record an observation from Claude's analysis."""
        category = observation.get('category', 'general')
        description = observation.get('description', '')
        entities = observation.get('entities', [])
        confidence = observation.get('confidence', 0.8)

        pattern_id = f"claude_{category}_{hash(description) % 10000}"
        current_time = timestamp.isoformat()

        if pattern_id in self.patterns:
            pattern = self.patterns[pattern_id]
            pattern.occurrences += 1
            pattern.last_seen = current_time
            pattern.confidence = min(0.99, (pattern.confidence + confidence) / 2)
        else:
            pattern = Pattern(
                id=pattern_id,
                category=category,
                description=description,
                entities=entities,
                confidence=confidence,
                occurrences=1,
                first_seen=current_time,
                last_seen=current_time,
                metadata={'source': 'claude'}
            )
            self.patterns[pattern_id] = pattern

    async def get_relevant_patterns(
        self,
        agent_states: Dict[str, Any],
        max_patterns: int = 10
    ) -> List[Dict]:
        """Get patterns relevant to the current state.

        Args:
            agent_states: Current agent states
            max_patterns: Maximum patterns to return

        Returns:
            List of relevant patterns
        """
        hour = datetime.now().hour
        relevant = []

        for pattern in self.patterns.values():
            relevance = 0.0

            # Timing relevance
            if pattern.category == 'timing':
                pattern_hour = pattern.metadata.get('hour', -1)
                if pattern_hour == hour:
                    relevance += 0.5
                elif abs(pattern_hour - hour) <= 1:
                    relevance += 0.3

            # Entity relevance
            current_entities = set()
            for agent_data in agent_states.values():
                if isinstance(agent_data, dict):
                    current_entities.update(agent_data.get('sensors', {}).keys())

            if pattern.entities:
                overlap = len(set(pattern.entities) & current_entities)
                relevance += overlap / len(pattern.entities) * 0.3

            # Confidence and recency
            relevance += pattern.confidence * 0.2

            if relevance > 0.3:
                relevant.append({
                    'id': pattern.id,
                    'category': pattern.category,
                    'description': pattern.description,
                    'confidence': pattern.confidence,
                    'occurrences': pattern.occurrences,
                    'relevance': relevance
                })

        # Sort by relevance and return top patterns
        relevant.sort(key=lambda x: x['relevance'], reverse=True)
        return relevant[:max_patterns]

    async def get_statistics(self) -> Dict[str, Any]:
        """Get learning statistics."""
        return {
            'total_patterns': len(self.patterns),
            'total_observations': len(self.observations),
            'pattern_categories': self._count_by_category(),
            'high_confidence_patterns': len([p for p in self.patterns.values() if p.confidence > 0.8]),
            'recent_observations': len([o for o in self.observations
                                        if datetime.fromisoformat(o.timestamp) >
                                        datetime.now() - timedelta(hours=24)])
        }

    def _count_by_category(self) -> Dict[str, int]:
        """Count patterns by category."""
        counts = defaultdict(int)
        for pattern in self.patterns.values():
            counts[pattern.category] += 1
        return dict(counts)

    async def prune_old_data(self, max_age_days: int = 30):
        """Remove old observations and low-confidence patterns.

        Args:
            max_age_days: Maximum age of data to keep
        """
        cutoff = datetime.now() - timedelta(days=max_age_days)
        cutoff_str = cutoff.isoformat()

        # Prune old observations
        self.observations = [
            o for o in self.observations
            if o.timestamp > cutoff_str
        ]

        # Prune low-confidence patterns not seen recently
        patterns_to_remove = []
        for pid, pattern in self.patterns.items():
            if pattern.last_seen < cutoff_str and pattern.confidence < 0.5:
                patterns_to_remove.append(pid)

        for pid in patterns_to_remove:
            del self.patterns[pid]

        logger.info(f"Pruned {len(patterns_to_remove)} patterns")
