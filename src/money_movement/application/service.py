from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from decimal import Decimal

from money_movement.application.ports import AccountSnapshot, PersistedTransfer, UnitOfWorkFactory
from money_movement.domain.model import DomainValidationError, LedgerEntry, Money, Transfer


class ApplicationError(RuntimeError):
    """Base application error."""


class AccountNotFoundError(ApplicationError):
    pass


class DuplicateAccountError(ApplicationError):
    pass


class CurrencyMismatchError(ApplicationError):
    pass


class InsufficientFundsError(ApplicationError):
    pass


class IdempotencyConflictError(ApplicationError):
    pass


@dataclass(frozen=True, slots=True)
class CreateTransferCommand:
    source_account_id: str
    destination_account_id: str
    amount: str
    currency: str
    reference: str
    idempotency_key: str

    def fingerprint(self) -> str:
        canonical = json.dumps(
            asdict(self) | {"idempotency_key": None}, sort_keys=True, separators=(",", ":")
        )
        return hashlib.sha256(canonical.encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class TransferResult:
    transfer: PersistedTransfer
    replayed: bool


class MoneyMovementService:
    def __init__(self, unit_of_work_factory: UnitOfWorkFactory) -> None:
        self._unit_of_work_factory = unit_of_work_factory

    async def create_transfer(self, command: CreateTransferCommand) -> TransferResult:
        if not command.idempotency_key.strip() or len(command.idempotency_key) > 128:
            raise DomainValidationError("idempotency key must contain between 1 and 128 characters")
        fingerprint = command.fingerprint()

        async with self._unit_of_work_factory() as unit_of_work:
            existing = await unit_of_work.find_transfer_by_idempotency_key(command.idempotency_key)
            if existing is not None:
                if existing.request_fingerprint != fingerprint:
                    raise IdempotencyConflictError("idempotency key was already used for a different request")
                return TransferResult(existing, replayed=True)

            accounts = await unit_of_work.lock_accounts(
                (command.source_account_id, command.destination_account_id)
            )
            source = accounts.get(command.source_account_id)
            destination = accounts.get(command.destination_account_id)
            if source is None or destination is None:
                raise AccountNotFoundError("source or destination account was not found")

            money = Money.from_value(command.amount, command.currency)
            if source.currency != money.currency or destination.currency != money.currency:
                raise CurrencyMismatchError("account and transfer currencies must match")
            if source.balance < money.amount:
                raise InsufficientFundsError("source account has insufficient funds")

            transfer = Transfer.request(
                source_account_id=source.account_id,
                destination_account_id=destination.account_id,
                money=money,
                reference=command.reference,
            )
            source.balance -= money.amount
            destination.balance += money.amount
            await unit_of_work.add_transfer(transfer, command.idempotency_key, fingerprint)
            await unit_of_work.commit()

            persisted = PersistedTransfer(
                transfer_id=transfer.transfer_id,
                source_account_id=transfer.source_account_id,
                destination_account_id=transfer.destination_account_id,
                amount=transfer.money.amount,
                currency=transfer.money.currency,
                reference=transfer.reference,
                status=transfer.status,
                created_at=transfer.created_at,
                request_fingerprint=fingerprint,
            )
            return TransferResult(persisted, replayed=False)

    async def create_account(
        self, account_id: str, currency: str, opening_balance: Decimal
    ) -> AccountSnapshot:
        normalized_currency = currency.strip().upper()
        if not account_id.strip():
            raise DomainValidationError("account id is required")
        if len(normalized_currency) != 3 or not normalized_currency.isalpha():
            raise DomainValidationError("currency must contain exactly three letters")
        if not opening_balance.is_finite() or opening_balance < 0:
            raise DomainValidationError("opening balance must be finite and non-negative")

        async with self._unit_of_work_factory() as unit_of_work:
            account = await unit_of_work.create_account(
                account_id.strip(), normalized_currency, opening_balance
            )
            await unit_of_work.commit()
            return account

    async def get_transfer(self, transfer_id: str) -> PersistedTransfer | None:
        async with self._unit_of_work_factory() as unit_of_work:
            return await unit_of_work.get_transfer(transfer_id)

    async def list_ledger_entries(self, account_id: str) -> list[LedgerEntry]:
        async with self._unit_of_work_factory() as unit_of_work:
            return await unit_of_work.list_ledger_entries(account_id)
