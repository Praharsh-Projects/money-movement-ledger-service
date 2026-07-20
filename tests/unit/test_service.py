from decimal import Decimal

import pytest

from money_movement.application.ports import AccountSnapshot
from money_movement.application.service import (
    AccountNotFoundError,
    CreateTransferCommand,
    CurrencyMismatchError,
    IdempotencyConflictError,
    InsufficientFundsError,
    MoneyMovementService,
)
from tests.unit.fakes import FakeStore, FakeUnitOfWork


def command(**overrides: str) -> CreateTransferCommand:
    values = {
        "source_account_id": "source",
        "destination_account_id": "destination",
        "amount": "25.5000",
        "currency": "SEK",
        "reference": "invoice-2026-07",
        "idempotency_key": "request-1",
    }
    values.update(overrides)
    return CreateTransferCommand(**values)


def service_with_accounts() -> tuple[MoneyMovementService, FakeStore]:
    store = FakeStore()
    store.accounts = {
        "source": AccountSnapshot("source", "SEK", Decimal("100.0000")),
        "destination": AccountSnapshot("destination", "SEK", Decimal("10.0000")),
    }
    return MoneyMovementService(lambda: FakeUnitOfWork(store)), store


@pytest.mark.asyncio
async def test_create_transfer_posts_balances_ledger_event_and_commit() -> None:
    service, store = service_with_accounts()

    result = await service.create_transfer(command())

    assert result.replayed is False
    assert store.accounts["source"].balance == Decimal("74.5000")
    assert store.accounts["destination"].balance == Decimal("35.5000")
    assert sum((entry.signed_amount for entry in store.ledger_entries), Decimal("0")) == 0
    assert len(store.events) == 1
    assert store.commits == 1


@pytest.mark.asyncio
async def test_same_idempotency_key_replays_without_second_posting() -> None:
    service, store = service_with_accounts()
    first = await service.create_transfer(command())
    replay = await service.create_transfer(command())

    assert replay.replayed is True
    assert replay.transfer.transfer_id == first.transfer.transfer_id
    assert len(store.ledger_entries) == 2
    assert store.commits == 1


@pytest.mark.asyncio
async def test_reused_idempotency_key_with_changed_request_is_rejected() -> None:
    service, _ = service_with_accounts()
    await service.create_transfer(command())

    with pytest.raises(IdempotencyConflictError):
        await service.create_transfer(command(amount="26.0000"))


@pytest.mark.asyncio
async def test_insufficient_funds_does_not_post() -> None:
    service, store = service_with_accounts()

    with pytest.raises(InsufficientFundsError):
        await service.create_transfer(command(amount="100.0001"))
    assert store.ledger_entries == []
    assert store.commits == 0


@pytest.mark.asyncio
async def test_currency_mismatch_is_rejected() -> None:
    service, _ = service_with_accounts()

    with pytest.raises(CurrencyMismatchError):
        await service.create_transfer(command(currency="EUR"))


@pytest.mark.asyncio
async def test_missing_account_is_rejected() -> None:
    service, _ = service_with_accounts()

    with pytest.raises(AccountNotFoundError):
        await service.create_transfer(command(destination_account_id="missing"))


@pytest.mark.asyncio
async def test_create_and_query_account() -> None:
    store = FakeStore()
    service = MoneyMovementService(lambda: FakeUnitOfWork(store))

    account = await service.create_account("wallet-1", "sek", Decimal("5.5000"))

    assert account.currency == "SEK"
    assert account.balance == Decimal("5.5000")
    assert store.commits == 1
