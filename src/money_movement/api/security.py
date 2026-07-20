import hashlib
import secrets
from typing import Annotated

from fastapi import Header, HTTPException, status


class ApiKeyVerifier:
    def __init__(self, expected_key: str) -> None:
        self._expected_digest = hashlib.sha256(expected_key.encode()).digest()

    async def __call__(self, x_api_key: Annotated[str | None, Header()] = None) -> None:
        if x_api_key is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="missing API key")
        provided_digest = hashlib.sha256(x_api_key.encode()).digest()
        if not secrets.compare_digest(provided_digest, self._expected_digest):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid API key")
