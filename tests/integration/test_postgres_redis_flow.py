import os
from decimal import Decimal

import pytest
from httpx import ASGITransport, AsyncClient
from redis.asyncio import Redis
from sqlalchemy import func, select

from money_movement.api.app import create_app
from money_movement.infrastructure.config import Settings
from money_movement.infrastructure.database import AccountRow, Database, OutboxEventRow
from money_movement.infrastructure.outbox import OutboxDispatcher

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_transfer_is_atomic_idempotent_and_dispatched() -> None:
    database_url = os.getenv("TEST_DATABASE_URL")
    redis_url = os.getenv("TEST_REDIS_URL")
    if not database_url or not redis_url:
        pytest.skip("TEST_DATABASE_URL and TEST_REDIS_URL are required")

    settings = Settings(
        database_url=database_url,
        redis_url=redis_url,
        api_key="integration-test-api-key",
    )
    database = Database(database_url)
    redis = Redis.from_url(redis_url, decode_responses=True)
    await database.drop_schema()
    await database.create_schema()
    await redis.flushdb()
    app = create_app(settings, database=database, redis=redis, initialize_schema=False)
    headers = {"X-API-Key": settings.api_key}

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            source = await client.post(
                "/v1/accounts",
                headers=headers,
                json={"account_id": "source", "currency": "SEK", "opening_balance": "500.0000"},
            )
            destination = await client.post(
                "/v1/accounts",
                headers=headers,
                json={"account_id": "destination", "currency": "SEK", "opening_balance": "0"},
            )
            assert source.status_code == destination.status_code == 201

            transfer_headers = headers | {"Idempotency-Key": "integration-transfer-1"}
            payload = {
                "source_account_id": "source",
                "destination_account_id": "destination",
                "amount": "125.5000",
                "currency": "SEK",
                "reference": "verified integration flow",
            }
            created = await client.post("/v1/transfers", headers=transfer_headers, json=payload)
            replayed = await client.post("/v1/transfers", headers=transfer_headers, json=payload)
            assert created.status_code == 201
            assert replayed.status_code == 200
            assert created.json()["transfer_id"] == replayed.json()["transfer_id"]
            assert replayed.json()["replayed"] is True

            ledger = await client.get("/v1/accounts/source/ledger", headers=headers)
            assert ledger.status_code == 200
            assert Decimal(ledger.json()[0]["signed_amount"]) == Decimal("-125.5000")

            insufficient = await client.post(
                "/v1/transfers",
                headers=headers | {"Idempotency-Key": "integration-transfer-2"},
                json=payload | {"amount": "1000.0000"},
            )
            assert insufficient.status_code == 409

        async with database.sessions() as session:
            balances = dict((await session.execute(select(AccountRow.account_id, AccountRow.balance))).all())
            outbox_count = await session.scalar(select(func.count()).select_from(OutboxEventRow))
        assert balances == {"source": Decimal("374.5000"), "destination": Decimal("125.5000")}
        assert outbox_count == 1

        dispatcher = OutboxDispatcher(database.sessions, redis, settings.event_stream)
        assert await dispatcher.dispatch_batch() == 1
        assert await dispatcher.dispatch_batch() == 0
        assert await redis.xlen(settings.event_stream) == 1
    finally:
        await database.drop_schema()
        await redis.aclose()
        await database.dispose()
