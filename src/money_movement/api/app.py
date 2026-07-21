from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated
from uuid import uuid4

from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse
from redis.asyncio import Redis
from starlette.middleware.base import RequestResponseEndpoint

from money_movement.api.schemas import (
    AccountCreateRequest,
    AccountResponse,
    HealthResponse,
    LedgerEntryResponse,
    TransferCreateRequest,
    TransferResponse,
)
from money_movement.api.security import ApiKeyVerifier
from money_movement.application.service import (
    AccountNotFoundError,
    ApplicationError,
    CreateTransferCommand,
    CurrencyMismatchError,
    DuplicateAccountError,
    IdempotencyConflictError,
    InsufficientFundsError,
    MoneyMovementService,
)
from money_movement.domain.model import DomainValidationError
from money_movement.infrastructure.config import Settings, get_settings
from money_movement.infrastructure.database import Database
from money_movement.risk_review.factory import build_risk_review_workflow
from money_movement.risk_review.models import ReviewCase, ReviewResult
from money_movement.risk_review.workflow import RiskReviewWorkflow


def create_app(
    settings: Settings | None = None,
    *,
    database: Database | None = None,
    redis: Redis | None = None,
    risk_reviewer: RiskReviewWorkflow | None = None,
    initialize_schema: bool = True,
) -> FastAPI:
    active_settings = settings or get_settings()
    active_database = database or Database(active_settings.database_url)
    active_redis = redis or Redis.from_url(active_settings.redis_url, decode_responses=True)
    service = MoneyMovementService(active_database.unit_of_work)
    active_risk_reviewer = risk_reviewer or build_risk_review_workflow(active_settings)
    verify_api_key = ApiKeyVerifier(active_settings.api_key)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        if initialize_schema:
            await active_database.create_schema()
        yield
        await active_redis.aclose()
        await active_database.dispose()

    app = FastAPI(
        title="Money Movement Ledger and Risk Review Service",
        version="1.1.0",
        description=("Secure, idempotent transfers plus bounded, policy-grounded human-review routing."),
        lifespan=lifespan,
    )
    app.state.database = active_database
    app.state.redis = active_redis
    app.state.service = service
    app.state.risk_reviewer = active_risk_reviewer
    app.state.settings = active_settings

    @app.middleware("http")
    async def correlation_id_middleware(request: Request, call_next: RequestResponseEndpoint) -> Response:
        supplied = request.headers.get("X-Correlation-ID", "").strip()
        correlation_id = supplied[:128] if supplied else str(uuid4())
        request.state.correlation_id = correlation_id
        response = await call_next(request)
        response.headers["X-Correlation-ID"] = correlation_id
        return response

    @app.exception_handler(DomainValidationError)
    async def domain_error_handler(_: Request, exc: DomainValidationError) -> JSONResponse:
        return JSONResponse(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, content={"detail": str(exc)})

    @app.exception_handler(AccountNotFoundError)
    async def account_not_found_handler(_: Request, exc: AccountNotFoundError) -> JSONResponse:
        return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content={"detail": str(exc)})

    @app.exception_handler(ApplicationError)
    async def application_error_handler(_: Request, exc: ApplicationError) -> JSONResponse:
        code = status.HTTP_409_CONFLICT
        return JSONResponse(status_code=code, content={"detail": str(exc)})

    secured = [Depends(verify_api_key)]

    @app.get("/health/live", response_model=HealthResponse)
    async def liveness() -> HealthResponse:
        return HealthResponse(status="ok")

    @app.get("/health/ready", response_model=HealthResponse)
    async def readiness() -> HealthResponse:
        try:
            database_ready = await active_database.ping()
            redis_ready = bool(await active_redis.ping())
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="dependency unavailable"
            ) from exc
        if not database_ready or not redis_ready:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="dependency unavailable"
            )
        return HealthResponse(status="ready")

    @app.post(
        "/v1/accounts",
        response_model=AccountResponse,
        status_code=status.HTTP_201_CREATED,
        dependencies=secured,
    )
    async def create_account(payload: AccountCreateRequest) -> AccountResponse:
        account = await service.create_account(payload.account_id, payload.currency, payload.opening_balance)
        return AccountResponse.from_snapshot(account)

    @app.post(
        "/v1/transfers",
        response_model=TransferResponse,
        status_code=status.HTTP_201_CREATED,
        dependencies=secured,
    )
    async def create_transfer(
        payload: TransferCreateRequest,
        response: Response,
        idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=128)],
    ) -> TransferResponse:
        result = await service.create_transfer(
            CreateTransferCommand(
                source_account_id=payload.source_account_id,
                destination_account_id=payload.destination_account_id,
                amount=str(payload.amount),
                currency=payload.currency,
                reference=payload.reference,
                idempotency_key=idempotency_key,
            )
        )
        if result.replayed:
            response.status_code = status.HTTP_200_OK
        return TransferResponse.from_transfer(result.transfer, replayed=result.replayed)

    @app.get("/v1/transfers/{transfer_id}", response_model=TransferResponse, dependencies=secured)
    async def get_transfer(transfer_id: str) -> TransferResponse:
        transfer = await service.get_transfer(transfer_id)
        if transfer is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="transfer not found")
        return TransferResponse.from_transfer(transfer)

    @app.get(
        "/v1/accounts/{account_id}/ledger",
        response_model=list[LedgerEntryResponse],
        dependencies=secured,
    )
    async def list_ledger(account_id: str) -> list[LedgerEntryResponse]:
        entries = await service.list_ledger_entries(account_id)
        return [LedgerEntryResponse.from_entry(entry) for entry in entries]

    @app.post(
        "/v1/risk-reviews",
        response_model=ReviewResult,
        dependencies=secured,
        summary="Create a human-review routing recommendation",
    )
    async def create_risk_review(payload: ReviewCase) -> ReviewResult:
        return await active_risk_reviewer.review(payload)

    return app


app = create_app()


__all__ = [
    "AccountNotFoundError",
    "CurrencyMismatchError",
    "DuplicateAccountError",
    "IdempotencyConflictError",
    "InsufficientFundsError",
    "app",
    "create_app",
]
