from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from types import TracebackType
from typing import Protocol, Self

from money_movement.domain.model import LedgerEntry, Transfer


@dataclass(slots=True)
class AccountSnapshot:
    account_id: str
    currency: str
    balance: Decimal


@dataclass(frozen=True, slots=True)
class PersistedTransfer:
    transfer_id: str
    source_account_id: str
    destination_account_id: str
    amount: Decimal
    currency: str
    reference: str
    status: str
    created_at: datetime
    request_fingerprint: str


class MoneyMovementUnitOfWork(Protocol):
    async def __aenter__(self) -> Self: ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None: ...

    async def lock_accounts(self, account_ids: tuple[str, str]) -> dict[str, AccountSnapshot]: ...

    async def find_transfer_by_idempotency_key(self, key: str) -> PersistedTransfer | None: ...

    async def add_transfer(
        self, transfer: Transfer, idempotency_key: str, request_fingerprint: str
    ) -> None: ...

    async def create_account(
        self, account_id: str, currency: str, opening_balance: Decimal
    ) -> AccountSnapshot: ...

    async def get_transfer(self, transfer_id: str) -> PersistedTransfer | None: ...

    async def list_ledger_entries(self, account_id: str) -> list[LedgerEntry]: ...

    async def commit(self) -> None: ...


UnitOfWorkFactory = Callable[[], MoneyMovementUnitOfWork]
