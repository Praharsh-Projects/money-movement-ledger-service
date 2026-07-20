from datetime import UTC, datetime
from decimal import Decimal

import pytest

from money_movement.domain.model import DomainValidationError, LedgerDirection, Money, Transfer


def test_money_normalizes_amount_and_currency() -> None:
    money = Money.from_value("12.34567", "sek")

    assert money.amount == Decimal("12.3457")
    assert money.currency == "SEK"


@pytest.mark.parametrize("amount", ["0", "-1", "NaN", "Infinity", "invalid"])
def test_money_rejects_invalid_amounts(amount: str) -> None:
    with pytest.raises(DomainValidationError):
        Money.from_value(amount, "SEK")


def test_transfer_creates_balanced_double_entry_posting_and_event() -> None:
    now = datetime(2026, 7, 20, tzinfo=UTC)
    transfer = Transfer.request(
        source_account_id="wallet-a",
        destination_account_id="wallet-b",
        money=Money.from_value("125.50", "SEK"),
        reference="rent",
        now=now,
        transfer_id="transfer-123",
    )

    debit, credit = transfer.entries
    assert debit.direction is LedgerDirection.DEBIT
    assert credit.direction is LedgerDirection.CREDIT
    assert debit.signed_amount + credit.signed_amount == Decimal("0")
    assert transfer.events[0].event_type == "money_movement.transfer_posted.v1"
    assert transfer.events[0].payload["transfer_id"] == "transfer-123"


def test_transfer_rejects_same_account() -> None:
    with pytest.raises(DomainValidationError, match="must differ"):
        Transfer.request(
            source_account_id="wallet-a",
            destination_account_id="wallet-a",
            money=Money.from_value("1", "SEK"),
            reference="invalid",
        )
