from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from types import TracebackType
from typing import Self

from money_movement.application.ports import AccountSnapshot, PersistedTransfer
from money_movement.application.service import DuplicateAccountError
from money_movement.domain.model import LedgerEntry, Transfer


class FakeStore:
    def __init__(self) -> None:
        self.accounts: dict[str, AccountSnapshot] = {}
        self.transfers: dict[str, PersistedTransfer] = {}
        self.idempotency: dict[str, str] = {}
        self.ledger_entries: list[LedgerEntry] = []
        self.events: list[str] = []
        self.commits = 0


class FakeUnitOfWork:
    def __init__(self, store: FakeStore) -> None:
        self.store = store

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        return None

    async def lock_accounts(self, account_ids: tuple[str, str]) -> dict[str, AccountSnapshot]:
        return {
            account_id: self.store.accounts[account_id]
            for account_id in account_ids
            if account_id in self.store.accounts
        }

    async def find_transfer_by_idempotency_key(self, key: str) -> PersistedTransfer | None:
        transfer_id = self.store.idempotency.get(key)
        return self.store.transfers.get(transfer_id) if transfer_id is not None else None

    async def add_transfer(self, transfer: Transfer, idempotency_key: str, request_fingerprint: str) -> None:
        persisted = PersistedTransfer(
            transfer_id=transfer.transfer_id,
            source_account_id=transfer.source_account_id,
            destination_account_id=transfer.destination_account_id,
            amount=transfer.money.amount,
            currency=transfer.money.currency,
            reference=transfer.reference,
            status=str(transfer.status),
            created_at=transfer.created_at,
            request_fingerprint=request_fingerprint,
        )
        self.store.transfers[transfer.transfer_id] = persisted
        self.store.idempotency[idempotency_key] = transfer.transfer_id
        self.store.ledger_entries.extend(transfer.entries)
        self.store.events.extend(event.event_id for event in transfer.events)

    async def create_account(
        self, account_id: str, currency: str, opening_balance: Decimal
    ) -> AccountSnapshot:
        if account_id in self.store.accounts:
            raise DuplicateAccountError("account already exists")
        account = AccountSnapshot(account_id, currency, opening_balance)
        self.store.accounts[account_id] = account
        return account

    async def get_transfer(self, transfer_id: str) -> PersistedTransfer | None:
        return self.store.transfers.get(transfer_id)

    async def list_ledger_entries(self, account_id: str) -> list[LedgerEntry]:
        return [entry for entry in self.store.ledger_entries if entry.account_id == account_id]

    async def commit(self) -> None:
        self.store.commits += 1


def sample_transfer() -> PersistedTransfer:
    return PersistedTransfer(
        transfer_id="transfer-1",
        source_account_id="source",
        destination_account_id="destination",
        amount=Decimal("10.0000"),
        currency="SEK",
        reference="invoice",
        status="POSTED",
        created_at=datetime.now(UTC),
        request_fingerprint="fingerprint",
    )
