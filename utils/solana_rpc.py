from __future__ import annotations

import asyncio
import httpx
import itertools
import time
from typing import Any, Dict, Optional


class SolanaRPC:
    def __init__(self, rpc_url: str | list[str], timeout: float = 20.0, cooldown_seconds: float = 45.0):
        urls = rpc_url if isinstance(rpc_url, list) else [rpc_url]
        cleaned = [u.strip() for u in urls if u and u.strip()]
        if not cleaned:
            raise ValueError("At least one Solana RPC URL is required")
        self.rpc_urls = cleaned
        self._id = itertools.count(1)
        self.client = httpx.AsyncClient(timeout=timeout)
        self.cooldown_seconds = cooldown_seconds
        self._cursor = 0
        self._down_until: dict[str, float] = {}
        self._lock = asyncio.Lock()

    async def _pick_urls(self) -> list[str]:
        async with self._lock:
            now = time.time()
            healthy = [u for u in self.rpc_urls if self._down_until.get(u, 0) <= now]
            if not healthy:
                # Cooldown has temporarily sidelined every endpoint. Try them all again.
                self._down_until.clear()
                healthy = list(self.rpc_urls)

            start = self._cursor % len(healthy)
            ordered = healthy[start:] + healthy[:start]
            self._cursor = (self._cursor + 1) % max(1, len(healthy))
            return ordered

    def _mark_down(self, url: str):
        self._down_until[url] = time.time() + self.cooldown_seconds

    @staticmethod
    def _is_retryable_rpc_error(err: Any) -> bool:
        text = str(err).lower()
        retry_terms = (
            "429",
            "rate limit",
            "too many requests",
            "timed out",
            "timeout",
            "connection",
            "temporarily unavailable",
            "try again",
            "service unavailable",
            "internal error",
            "gateway",
        )
        return any(term in text for term in retry_terms)

    async def call(self, method: str, params: list | None = None) -> Any:
        payload = {
            "jsonrpc": "2.0",
            "id": next(self._id),
            "method": method,
            "params": params or [],
        }
        urls = await self._pick_urls()
        last_error: Exception | None = None

        for url in urls:
            try:
                r = await self.client.post(url, json=payload)
                r.raise_for_status()
                data = r.json()
                if "error" in data:
                    err = RuntimeError(f"RPC error from {url}: {data['error']}")
                    # Only fail over on rate-limit / temporary server conditions.
                    if self._is_retryable_rpc_error(data["error"]):
                        self._mark_down(url)
                        last_error = err
                        continue
                    raise err
                return data["result"]
            except (httpx.TimeoutException, httpx.NetworkError, httpx.HTTPStatusError, RuntimeError) as exc:
                retryable = True
                if isinstance(exc, RuntimeError):
                    retryable = self._is_retryable_rpc_error(exc)
                elif isinstance(exc, httpx.HTTPStatusError):
                    retryable = exc.response.status_code in {408, 409, 425, 429, 500, 502, 503, 504}
                if retryable:
                    self._mark_down(url)
                    last_error = exc
                    continue
                raise

        if last_error:
            raise RuntimeError(f"All Solana RPC endpoints failed for {method}: {last_error}")
        raise RuntimeError(f"No Solana RPC endpoint available for {method}")

    async def get_transaction(self, signature: str) -> Optional[Dict[str, Any]]:
        return await self.call(
            "getTransaction",
            [signature, {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 0}],
        )

    async def get_signatures_for_address(self, address: str, limit: int = 20, before: str | None = None) -> list[dict]:
        params = [address, {"limit": limit}]
        if before:
            params[1]["before"] = before
        return await self.call("getSignaturesForAddress", params)

    async def close(self):
        await self.client.aclose()
