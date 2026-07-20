from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from money_movement.application.ports import AccountSnapshot, PersistedTransfer
from money_movement.domain.model import LedgerEntry


class AccountCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    account_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9._-]+$")
    currency: str = Field(min_length=3, max_length=3, pattern=r"^[A-Za-z]{3}$")
    opening_balance: Decimal = Field(default=Decimal("0"), ge=0, max_digits=20, decimal_places=4)


class AccountResponse(BaseModel):
    account_id: str
    currency: str
    balance: Decimal

    @classmethod
    def from_snapshot(cls, account: AccountSnapshot) -> "AccountResponse":
        return cls(account_id=account.account_id, currency=account.currency, balance=account.balance)


class TransferCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_account_id: str = Field(min_length=1, max_length=64)
    destination_account_id: str = Field(min_length=1, max_length=64)
    amount: Decimal = Field(gt=0, max_digits=20, decimal_places=4)
    currency: str = Field(min_length=3, max_length=3, pattern=r"^[A-Za-z]{3}$")
    reference: str = Field(default="", max_length=140)


class TransferResponse(BaseModel):
    transfer_id: str
    source_account_id: str
    destination_account_id: str
    amount: Decimal
    currency: str
    reference: str
    status: str
    created_at: datetime
    replayed: bool = False

    @classmethod
    def from_transfer(cls, transfer: PersistedTransfer, *, replayed: bool = False) -> "TransferResponse":
        return cls(
            transfer_id=transfer.transfer_id,
            source_account_id=transfer.source_account_id,
            destination_account_id=transfer.destination_account_id,
            amount=transfer.amount,
            currency=transfer.currency,
            reference=transfer.reference,
            status=transfer.status,
            created_at=transfer.created_at,
            replayed=replayed,
        )


class LedgerEntryResponse(BaseModel):
    entry_id: str
    account_id: str
    transfer_id: str
    direction: str
    signed_amount: Decimal
    currency: str
    created_at: datetime

    @classmethod
    def from_entry(cls, entry: LedgerEntry) -> "LedgerEntryResponse":
        return cls(
            entry_id=entry.entry_id,
            account_id=entry.account_id,
            transfer_id=entry.transfer_id,
            direction=str(entry.direction),
            signed_amount=entry.signed_amount,
            currency=entry.currency,
            created_at=entry.created_at,
        )


class HealthResponse(BaseModel):
    status: str
