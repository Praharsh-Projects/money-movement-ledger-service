import asyncio
import logging

from redis.asyncio import Redis

from money_movement.infrastructure.config import get_settings
from money_movement.infrastructure.database import Database
from money_movement.infrastructure.outbox import OutboxDispatcher

LOGGER = logging.getLogger(__name__)


async def run() -> None:
    settings = get_settings()
    database = Database(settings.database_url)
    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    dispatcher = OutboxDispatcher(database.sessions, redis, settings.event_stream)
    try:
        while True:
            dispatched = await dispatcher.dispatch_batch()
            if dispatched == 0:
                await asyncio.sleep(0.5)
    finally:
        await redis.aclose()
        await database.dispose()


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        LOGGER.info("outbox worker stopped")


if __name__ == "__main__":
    main()
