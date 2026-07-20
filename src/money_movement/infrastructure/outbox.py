from __future__ import annotations

import json
from datetime import UTC, datetime

from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from money_movement.infrastructure.database import OutboxEventRow


class OutboxDispatcher:
    """Moves committed outbox events to Redis Streams with at-least-once delivery."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        redis: Redis,
        stream: str,
    ) -> None:
        self._session_factory = session_factory
        self._redis = redis
        self._stream = stream

    async def dispatch_batch(self, batch_size: int = 100) -> int:
        async with self._session_factory() as session, session.begin():
            statement = (
                select(OutboxEventRow)
                .where(OutboxEventRow.dispatched_at.is_(None))
                .order_by(OutboxEventRow.occurred_at)
                .limit(batch_size)
                .with_for_update(skip_locked=True)
            )
            events = list((await session.scalars(statement)).all())
            for event in events:
                try:
                    await self._redis.xadd(
                        self._stream,
                        {
                            "event_id": event.event_id,
                            "aggregate_id": event.aggregate_id,
                            "event_type": event.event_type,
                            "occurred_at": event.occurred_at.isoformat(),
                            "payload": json.dumps(event.payload, sort_keys=True),
                        },
                    )
                    event.dispatched_at = datetime.now(UTC)
                    event.attempts += 1
                    event.last_error = None
                except Exception as exc:
                    event.attempts += 1
                    event.last_error = str(exc)[:500]
                    raise
            return len(events)
