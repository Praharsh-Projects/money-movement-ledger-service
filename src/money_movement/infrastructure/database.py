from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from types import TracebackType
from typing import Any, Self

from sqlalchemy import JSON, DateTime, ForeignKey, Numeric, String, Text, select, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from money_movement.application.ports import AccountSnapshot, PersistedTransfer
from money_movement.application.service import DuplicateAccountError
from money_movement.domain.model import LedgerDirection, LedgerEntry, Transfer

MONEY_NUMERIC = Numeric(20, 4)


class Base(DeclarativeBase):
    pass


class AccountRow(Base):
    __tablename__ = "accounts"

    account_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    balance: Mapped[Decimal] = mapped_column(MONEY_NUMERIC, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))


class TransferRow(Base):
    __tablename__ = "transfers"

    transfer_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    source_account_id: Mapped[str] = mapped_column(ForeignKey("accounts.account_id"), index=True)
    destination_account_id: Mapped[str] = mapped_column(ForeignKey("accounts.account_id"), index=True)
    amount: Mapped[Decimal] = mapped_column(MONEY_NUMERIC, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    reference: Mapped[str] = mapped_column(String(140), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class LedgerEntryRow(Base):
    __tablename__ = "ledger_entries"

    entry_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.account_id"), index=True)
    transfer_id: Mapped[str] = mapped_column(ForeignKey("transfers.transfer_id"), index=True)
    direction: Mapped[str] = mapped_column(String(10), nullable=False)
    signed_amount: Mapped[Decimal] = mapped_column(MONEY_NUMERIC, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class IdempotencyRow(Base):
    __tablename__ = "idempotency_records"

    idempotency_key: Mapped[str] = mapped_column(String(128), primary_key=True)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    transfer_id: Mapped[str] = mapped_column(ForeignKey("transfers.transfer_id"), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))


class OutboxEventRow(Base):
    __tablename__ = "outbox_events"

    event_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    aggregate_id: Mapped[str] = mapped_column(String(36), index=True)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    dispatched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(default=0, nullable=False)
    last_error: Mapped[str | None] = mapped_column(Text)


class SqlAlchemyUnitOfWork:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory
        self._session: AsyncSession | None = None
        self._account_rows: dict[str, tuple[AccountRow, AccountSnapshot]] = {}
        self._committed = False

    @property
    def session(self) -> AsyncSession:
        if self._session is None:
            raise RuntimeError("unit of work has not been entered")
        return self._session

    async def __aenter__(self) -> Self:
        self._session = self._session_factory()
        await self._session.begin()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if self._session is None:
            return
        if exc is not None or not self._committed:
            await self._session.rollback()
        await self._session.close()

    async def lock_accounts(self, account_ids: tuple[str, str]) -> dict[str, AccountSnapshot]:
        statement = (
            select(AccountRow)
            .where(AccountRow.account_id.in_(account_ids))
            .order_by(AccountRow.account_id)
            .with_for_update()
        )
        rows = (await self.session.scalars(statement)).all()
        snapshots: dict[str, AccountSnapshot] = {}
        for row in rows:
            snapshot = AccountSnapshot(row.account_id, row.currency, row.balance)
            snapshots[row.account_id] = snapshot
            self._account_rows[row.account_id] = (row, snapshot)
        return snapshots

    async def find_transfer_by_idempotency_key(self, key: str) -> PersistedTransfer | None:
        # Serialize concurrent requests for the same key, including when no record exists yet.
        await self.session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"), {"key": key}
        )
        statement = (
            select(TransferRow, IdempotencyRow.request_fingerprint)
            .join(IdempotencyRow, IdempotencyRow.transfer_id == TransferRow.transfer_id)
            .where(IdempotencyRow.idempotency_key == key)
        )
        result = (await self.session.execute(statement)).one_or_none()
        if result is None:
            return None
        transfer, fingerprint = result
        return _persisted_transfer(transfer, fingerprint)

    async def add_transfer(self, transfer: Transfer, idempotency_key: str, request_fingerprint: str) -> None:
        for row, snapshot in self._account_rows.values():
            row.balance = snapshot.balance

        self.session.add(
            TransferRow(
                transfer_id=transfer.transfer_id,
                source_account_id=transfer.source_account_id,
                destination_account_id=transfer.destination_account_id,
                amount=transfer.money.amount,
                currency=transfer.money.currency,
                reference=transfer.reference,
                status=str(transfer.status),
                created_at=transfer.created_at,
            )
        )
        self.session.add_all(
            [
                LedgerEntryRow(
                    entry_id=entry.entry_id,
                    account_id=entry.account_id,
                    transfer_id=entry.transfer_id,
                    direction=str(entry.direction),
                    signed_amount=entry.signed_amount,
                    currency=entry.currency,
                    created_at=entry.created_at,
                )
                for entry in transfer.entries
            ]
        )
        self.session.add(
            IdempotencyRow(
                idempotency_key=idempotency_key,
                request_fingerprint=request_fingerprint,
                transfer_id=transfer.transfer_id,
            )
        )
        self.session.add_all(
            [
                OutboxEventRow(
                    event_id=event.event_id,
                    aggregate_id=event.aggregate_id,
                    event_type=event.event_type,
                    payload=event.payload,
                    occurred_at=event.occurred_at,
                )
                for event in transfer.events
            ]
        )

    async def create_account(
        self, account_id: str, currency: str, opening_balance: Decimal
    ) -> AccountSnapshot:
        if await self.session.get(AccountRow, account_id) is not None:
            raise DuplicateAccountError(f"account {account_id!r} already exists")
        self.session.add(AccountRow(account_id=account_id, currency=currency, balance=opening_balance))
        return AccountSnapshot(account_id, currency, opening_balance)

    async def get_transfer(self, transfer_id: str) -> PersistedTransfer | None:
        statement = (
            select(TransferRow, IdempotencyRow.request_fingerprint)
            .join(IdempotencyRow, IdempotencyRow.transfer_id == TransferRow.transfer_id)
            .where(TransferRow.transfer_id == transfer_id)
        )
        result = (await self.session.execute(statement)).one_or_none()
        if result is None:
            return None
        transfer, fingerprint = result
        return _persisted_transfer(transfer, fingerprint)

    async def list_ledger_entries(self, account_id: str) -> list[LedgerEntry]:
        statement = (
            select(LedgerEntryRow)
            .where(LedgerEntryRow.account_id == account_id)
            .order_by(LedgerEntryRow.created_at, LedgerEntryRow.entry_id)
        )
        rows = (await self.session.scalars(statement)).all()
        return [
            LedgerEntry(
                entry_id=row.entry_id,
                account_id=row.account_id,
                transfer_id=row.transfer_id,
                direction=LedgerDirection(row.direction),
                signed_amount=row.signed_amount,
                currency=row.currency,
                created_at=row.created_at,
            )
            for row in rows
        ]

    async def commit(self) -> None:
        await self.session.commit()
        self._committed = True


def _persisted_transfer(row: TransferRow, fingerprint: str) -> PersistedTransfer:
    return PersistedTransfer(
        transfer_id=row.transfer_id,
        source_account_id=row.source_account_id,
        destination_account_id=row.destination_account_id,
        amount=row.amount,
        currency=row.currency,
        reference=row.reference,
        status=row.status,
        created_at=row.created_at,
        request_fingerprint=fingerprint,
    )


class Database:
    def __init__(self, url: str, *, echo: bool = False) -> None:
        self.engine: AsyncEngine = create_async_engine(url, echo=echo, pool_pre_ping=True)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)

    def unit_of_work(self) -> SqlAlchemyUnitOfWork:
        return SqlAlchemyUnitOfWork(self.sessions)

    async def create_schema(self) -> None:
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    async def drop_schema(self) -> None:
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.drop_all)

    async def ping(self) -> bool:
        async with self.engine.connect() as connection:
            return bool((await connection.scalar(text("SELECT 1"))) == 1)

    async def dispose(self) -> None:
        await self.engine.dispose()


DatabaseFactory = Callable[[], Database]
