from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import ROUND_HALF_EVEN, Decimal, InvalidOperation
from enum import StrEnum
from typing import Any
from uuid import uuid4

MONEY_SCALE = Decimal("0.0001")


class DomainValidationError(ValueError):
    """Raised when a domain invariant is violated."""


class LedgerDirection(StrEnum):
    DEBIT = "DEBIT"
    CREDIT = "CREDIT"


class TransferStatus(StrEnum):
    POSTED = "POSTED"


@dataclass(frozen=True, slots=True)
class Money:
    amount: Decimal
    currency: str

    @classmethod
    def from_value(cls, amount: str | Decimal, currency: str) -> Money:
        try:
            normalized_amount = Decimal(amount).quantize(MONEY_SCALE, rounding=ROUND_HALF_EVEN)
        except (InvalidOperation, ValueError) as exc:
            raise DomainValidationError("amount must be a valid decimal") from exc

        normalized_currency = currency.strip().upper()
        if not normalized_amount.is_finite() or normalized_amount <= 0:
            raise DomainValidationError("amount must be finite and greater than zero")
        if len(normalized_currency) != 3 or not normalized_currency.isalpha():
            raise DomainValidationError("currency must contain exactly three letters")
        return cls(normalized_amount, normalized_currency)


@dataclass(frozen=True, slots=True)
class LedgerEntry:
    entry_id: str
    account_id: str
    transfer_id: str
    direction: LedgerDirection
    signed_amount: Decimal
    currency: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class DomainEvent:
    event_id: str
    aggregate_id: str
    event_type: str
    occurred_at: datetime
    payload: dict[str, Any]


@dataclass(frozen=True, slots=True)
class Transfer:
    transfer_id: str
    source_account_id: str
    destination_account_id: str
    money: Money
    reference: str
    status: TransferStatus
    created_at: datetime
    entries: tuple[LedgerEntry, LedgerEntry]
    events: tuple[DomainEvent, ...]

    @classmethod
    def request(
        cls,
        *,
        source_account_id: str,
        destination_account_id: str,
        money: Money,
        reference: str,
        now: datetime | None = None,
        transfer_id: str | None = None,
    ) -> Transfer:
        source = source_account_id.strip()
        destination = destination_account_id.strip()
        normalized_reference = reference.strip()
        if not source or not destination:
            raise DomainValidationError("source and destination accounts are required")
        if source == destination:
            raise DomainValidationError("source and destination accounts must differ")
        if len(normalized_reference) > 140:
            raise DomainValidationError("reference must not exceed 140 characters")

        created_at = now or datetime.now(UTC)
        identifier = transfer_id or str(uuid4())
        debit = LedgerEntry(
            entry_id=str(uuid4()),
            account_id=source,
            transfer_id=identifier,
            direction=LedgerDirection.DEBIT,
            signed_amount=-money.amount,
            currency=money.currency,
            created_at=created_at,
        )
        credit = LedgerEntry(
            entry_id=str(uuid4()),
            account_id=destination,
            transfer_id=identifier,
            direction=LedgerDirection.CREDIT,
            signed_amount=money.amount,
            currency=money.currency,
            created_at=created_at,
        )
        if debit.signed_amount + credit.signed_amount != Decimal("0"):
            raise DomainValidationError("ledger entries must balance to zero")

        event = DomainEvent(
            event_id=str(uuid4()),
            aggregate_id=identifier,
            event_type="money_movement.transfer_posted.v1",
            occurred_at=created_at,
            payload={
                "transfer_id": identifier,
                "source_account_id": source,
                "destination_account_id": destination,
                "amount": str(money.amount),
                "currency": money.currency,
                "status": TransferStatus.POSTED,
            },
        )
        return cls(
            transfer_id=identifier,
            source_account_id=source,
            destination_account_id=destination,
            money=money,
            reference=normalized_reference,
            status=TransferStatus.POSTED,
            created_at=created_at,
            entries=(debit, credit),
            events=(event,),
        )
