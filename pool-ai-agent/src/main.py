"""Main entry point for Pool AI Agent."""

import os
import asyncio
import logging
import signal
from datetime import datetime

from .ha_client import HAClient, EntityState
from .database import Database
from .decision_engine import DecisionEngine
from .state_monitor import StateMonitor

# Configure logging
log_level = os.environ.get("LOG_LEVEL", "info").upper()
logging.basicConfig(
    level=getattr(logging, log_level, logging.INFO),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger(__name__)


class PoolAIAgent:
    """Main Pool AI Agent daemon."""

    def __init__(self):
        self.ha_client = HAClient()
        self.database = Database()
        self.decision_engine = DecisionEngine(self.ha_client, self.database)

        self.decision_interval = int(os.environ.get("DECISION_INTERVAL", "5")) * 60  # Convert to seconds
        self._running = False
        self._tasks: list[asyncio.Task] = []

    async def start(self):
        """Start the agent."""
        logger.info("=" * 50)
        logger.info("Pool AI Agent starting...")
        logger.info("=" * 50)

        # Check HA connection
        if not await self.ha_client.check_connection():
            logger.error("Cannot connect to Home Assistant API")
            raise RuntimeError("Failed to connect to Home Assistant")

        logger.info("Connected to Home Assistant API")

        # Initialize Claude client
        try:
            self.decision_engine.initialize_claude()
        except ValueError as e:
            logger.error(f"Claude initialization failed: {e}")
            logger.warning("Agent will run in monitoring-only mode")

        # Initialize Hybrid LLM system for cost optimization
        try:
            await self.decision_engine.initialize_hybrid()
        except Exception as e:
            logger.error(f"Hybrid LLM initialization failed: {e}")
            logger.warning("Falling back to Claude-only mode")

        self._running = True

        # Start background tasks
        self._tasks = [
            asyncio.create_task(self._decision_loop()),
            asyncio.create_task(self._websocket_loop()),
            asyncio.create_task(self._daily_maintenance()),
        ]

        # Send startup notification
        await self.ha_client.send_notification(
            message=f"Pool AI Agent started. Decision interval: {self.decision_interval // 60} minutes.",
            title="Pool AI Agent"
        )

        # Run initial decision cycle
        logger.info("Running initial decision cycle...")
        await self.decision_engine.run_decision_cycle(trigger="startup")

        # Wait for tasks
        try:
            await asyncio.gather(*self._tasks)
        except asyncio.CancelledError:
            logger.info("Tasks cancelled")

    async def stop(self):
        """Stop the agent gracefully."""
        logger.info("Stopping Pool AI Agent...")
        self._running = False

        # Cancel all tasks
        for task in self._tasks:
            task.cancel()

        await self.ha_client.send_notification(
            message="Pool AI Agent stopped.",
            title="Pool AI Agent"
        )

    async def _decision_loop(self):
        """Main decision loop - runs every N minutes."""
        logger.info(f"Decision loop started (interval: {self.decision_interval}s)")

        while self._running:
            try:
                # Wait for next interval
                await asyncio.sleep(self.decision_interval)

                if not self._running:
                    break

                # Adjust interval based on time of day
                current_hour = datetime.now().hour
                if 8 <= current_hour < 18:
                    # Active hours - normal interval
                    pass
                else:
                    # Off hours - less frequent checks
                    # Skip every other cycle during off hours
                    if datetime.now().minute < 30:
                        logger.debug("Off-hours: skipping decision cycle")
                        continue

                logger.debug("Running scheduled decision cycle...")
                result = await self.decision_engine.run_decision_cycle(trigger="scheduled")

                if result.get("errors"):
                    logger.warning(f"Decision cycle completed with errors: {result['errors']}")
                else:
                    logger.debug("Decision cycle completed successfully")

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Decision loop error: {e}", exc_info=True)
                await asyncio.sleep(60)  # Wait before retry

    async def _websocket_loop(self):
        """WebSocket event listener for real-time updates."""
        logger.info("WebSocket loop started")

        # Register callback for critical events
        self.ha_client.register_event_callback(self._on_state_change)

        # Get entity filter patterns
        filter_patterns = self.decision_engine.state_monitor.get_entity_filter_patterns()

        while self._running:
            try:
                await self.ha_client.connect_websocket(entity_filter=filter_patterns)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"WebSocket loop error: {e}")
                await asyncio.sleep(10)

    async def _on_state_change(self, entity_state: EntityState):
        """Handle real-time state changes."""
        entity_id = entity_state.entity_id
        new_state = entity_state.state

        # Log significant changes
        if "pool" in entity_id or "hot_tub" in entity_id:
            logger.debug(f"State change: {entity_id} = {new_state}")

        # Check for critical events that need immediate attention
        critical_entities = [
            "input_boolean.pool_sensor_failure_detected",
            "input_boolean.pool_system_health_ok",
            "sensor.pool_water_temperature_reliable",
        ]

        if entity_id in critical_entities:
            await self.decision_engine.handle_critical_event(
                entity_id=entity_id,
                new_state=new_state,
                old_state=""  # We don't track old state in this simple implementation
            )

    async def _daily_maintenance(self):
        """Run daily maintenance tasks."""
        logger.info("Daily maintenance task started")

        while self._running:
            try:
                # Wait until 2 AM
                now = datetime.now()
                target = now.replace(hour=2, minute=0, second=0, microsecond=0)
                if now >= target:
                    target = target.replace(day=target.day + 1)

                wait_seconds = (target - now).total_seconds()
                logger.debug(f"Next maintenance in {wait_seconds / 3600:.1f} hours")

                await asyncio.sleep(wait_seconds)

                if not self._running:
                    break

                # Run maintenance
                logger.info("Running daily maintenance...")

                # Clean up old database records
                self.database.cleanup_old_data(days=90)

                # Reset LLM usage tracking
                if self.decision_engine.claude_client:
                    stats = self.decision_engine.claude_client.get_usage_stats()
                    logger.info(f"Yesterday's Claude usage: {stats}")
                    self.decision_engine.claude_client.reset_usage()

                # Reset hybrid LLM stats and log summary
                if self.decision_engine.hybrid_manager:
                    hybrid_stats = self.decision_engine.hybrid_manager.get_stats()
                    logger.info(f"Yesterday's Hybrid LLM stats: {hybrid_stats}")
                    self.decision_engine.hybrid_manager.reset_stats()

                # Send daily summary
                daily_stats = self.database.get_daily_stats(
                    (datetime.now().replace(day=datetime.now().day - 1)).strftime("%Y-%m-%d")
                )

                if daily_stats["api_calls"] > 0 or (hybrid_stats and hybrid_stats.get("total_analyses", 0) > 0):
                    # Build message with hybrid stats if available
                    msg_parts = ["Yesterday's stats:"]

                    if hybrid_stats and hybrid_stats.get("total_analyses", 0) > 0:
                        msg_parts.append(
                            f"- Analyses: {hybrid_stats['total_analyses']} "
                            f"(Rules: {hybrid_stats['rule_based_pct']:.0f}%, "
                            f"Local: {hybrid_stats['local_pct']:.0f}%, "
                            f"Claude: {hybrid_stats['claude_pct']:.0f}%)"
                        )

                    msg_parts.extend([
                        f"- Actions: {daily_stats['actions_executed']}",
                        f"- Blocked: {daily_stats['actions_blocked']}",
                        f"- Cost: ${daily_stats['cost_usd']:.2f}",
                    ])

                    await self.ha_client.send_notification(
                        message="\n".join(msg_parts),
                        title="Pool AI Agent - Daily Summary"
                    )

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Daily maintenance error: {e}", exc_info=True)
                await asyncio.sleep(3600)  # Wait an hour before retry


async def main():
    """Main entry point."""
    agent = PoolAIAgent()

    # Handle shutdown signals
    loop = asyncio.get_event_loop()

    def signal_handler():
        logger.info("Shutdown signal received")
        asyncio.create_task(agent.stop())

    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, signal_handler)

    try:
        await agent.start()
    except Exception as e:
        logger.error(f"Agent failed: {e}", exc_info=True)
        raise


if __name__ == "__main__":
    asyncio.run(main())
