"""Redis connection management (M1).

Owns the client lifecycle, namespaced key conventions, JSON serialization with
optional expiry, and a health probe. The ``redis`` SDK is imported lazily.

M1 provides *capability only*. Conversation memory (M5), LangGraph checkpointing,
and event consumers (M13) are explicitly out of scope here — this adapter just
proves Redis is reachable and usable behind the boundary.

Direct ``redis`` SDK access is permitted only inside this package.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from ...bootstrap.settings import RedisSettings
from ..errors import map_redis_error

if TYPE_CHECKING:  # pragma: no cover
    from redis.asyncio import Redis


class RedisClient:
    name = "redis"
    required = True

    def __init__(self, settings: RedisSettings) -> None:
        self._settings = settings
        self._client: Redis | None = None

    def namespaced(self, *parts: str) -> str:
        """Build a namespaced key: ``<namespace>:<part>:<part>``."""
        return ":".join((self._settings.namespace, *parts))

    async def connect(self) -> None:
        if self._client is not None:
            return
        from redis.asyncio import Redis

        s = self._settings
        try:
            self._client = Redis(
                host=s.host,
                port=s.port,
                db=s.db,
                password=s.password.get_secret_value() if s.password else None,
                socket_connect_timeout=s.connect_timeout_seconds,
                decode_responses=True,
            )
        except Exception as exc:  # noqa: BLE001
            raise map_redis_error(exc) from exc

    async def disconnect(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    @property
    def _require_client(self) -> Redis:
        if self._client is None:
            raise map_redis_error(RuntimeError("redis client not connected"))
        return self._client

    async def set_json(self, key: str, value: Any, *, ttl_seconds: int | None = None) -> None:
        client = self._require_client
        try:
            await client.set(self.namespaced(key), json.dumps(value), ex=ttl_seconds)
        except (TypeError, ValueError) as exc:
            from mesiri_contracts.common.errors import ErrorCategory, ErrorCode, MesiriError

            raise MesiriError(
                error_code=ErrorCode.SERIALIZATION_ERROR.value,
                category=ErrorCategory.SERIALIZATION,
                internal_message=f"redis json serialization failed: {exc}",
            ) from exc
        except Exception as exc:  # noqa: BLE001
            raise map_redis_error(exc) from exc

    async def get_json(self, key: str) -> Any | None:
        client = self._require_client
        try:
            raw = await client.get(self.namespaced(key))
        except Exception as exc:  # noqa: BLE001
            raise map_redis_error(exc) from exc
        return json.loads(raw) if raw is not None else None

    async def set_if_absent(self, key: str, value: str, *, ttl_seconds: int | None = None) -> bool:
        """Atomically claim ``key``, returning True only for the first caller.

        SET NX in one round trip — deliberately not get-then-set, which has a
        race window two concurrent webhook deliveries of the same message_id
        would fall straight through (Meta retries aggressively, and the two
        retries can land on different workers). This is the primitive behind
        RedisDeduplicationStore; the TTL is what bounds the key set, since
        nothing ever deletes a claim explicitly.
        """
        client = self._require_client
        try:
            claimed = await client.set(self.namespaced(key), value, nx=True, ex=ttl_seconds)
        except Exception as exc:  # noqa: BLE001
            raise map_redis_error(exc) from exc
        return bool(claimed)

    async def count(self, key: str, *, ttl_seconds: int) -> int:
        """Add one to a counter and return it; the counter goes ``ttl_seconds`` after its first count (a window).

        INCR and EXPIRE in one round trip (a pipeline), so a counter can never be left without its expiry.
        """
        client = self._require_client
        name = self.namespaced(key)
        try:
            async with client.pipeline(transaction=True) as pipe:
                pipe.incr(name)
                pipe.expire(name, ttl_seconds, nx=True)
                value, _ = await pipe.execute()
        except Exception as exc:  # noqa: BLE001
            raise map_redis_error(exc) from exc
        return int(value)

    async def check_health(self) -> None:
        client = self._require_client
        try:
            await client.ping()
        except Exception as exc:  # noqa: BLE001
            raise map_redis_error(exc) from exc

    async def delete(self, key: str) -> None:
        """Delete a raw (non-namespaced) key.

        Callers that share a key with non-namespaced readers/writers (e.g.
        DynamicAIProviderResolver's own get/set on "mesiri:ai:config") must
        delete that exact key, not a namespaced variant.
        """
        client = self._require_client
        try:
            await client.delete(key)
        except Exception as exc:  # noqa: BLE001
            raise map_redis_error(exc) from exc

    async def get_raw(self, key: str) -> str | None:
        """Read a raw (non-namespaced) string key -- same non-namespaced
        posture as delete() above. Exists for values this process didn't
        write as JSON, e.g. ARQ's own health-check key (admin/queue_router.py),
        which is a plain string ARQ's Worker.record_health() writes itself.
        """
        client = self._require_client
        try:
            return await client.get(key)
        except Exception as exc:  # noqa: BLE001
            raise map_redis_error(exc) from exc


class FakeRedis:
    """In-memory Redis stand-in for scenarios/tests (no TTL expiry emulation)."""

    name = "redis"
    required = True

    def __init__(self, *, namespace: str = "mesiri", fail_health: bool = False) -> None:
        self._namespace = namespace
        self.fail_health = fail_health
        self._connected = False
        self._store: dict[str, str] = {}

    def namespaced(self, *parts: str) -> str:
        return ":".join((self._namespace, *parts))

    async def connect(self) -> None:
        self._connected = True

    async def disconnect(self) -> None:
        self._connected = False

    async def set_json(self, key: str, value: Any, *, ttl_seconds: int | None = None) -> None:
        self._store[self.namespaced(key)] = json.dumps(value)

    async def get_json(self, key: str) -> Any | None:
        raw = self._store.get(self.namespaced(key))
        return json.loads(raw) if raw is not None else None

    async def set_if_absent(self, key: str, value: str, *, ttl_seconds: int | None = None) -> bool:
        namespaced = self.namespaced(key)
        if namespaced in self._store:
            return False
        self._store[namespaced] = value
        return True

    async def count(self, key: str, *, ttl_seconds: int) -> int:
        namespaced = self.namespaced(key)
        value = int(self._store.get(namespaced, "0")) + 1
        self._store[namespaced] = str(value)
        return value

    async def check_health(self) -> None:
        if self.fail_health or not self._connected:
            raise map_redis_error(ConnectionError("fake redis unavailable"))

    async def delete(self, key: str) -> None:
        self._store.pop(key, None)

    async def get_raw(self, key: str) -> str | None:
        # Nothing ever writes ARQ's health-check key against FakeRedis --
        # the queue is only wired up against real Redis (see runtime/queue.py) --
        # so this always reports "worker not running", which is the correct
        # answer for a dev/test environment with no worker process at all.
        return self._store.get(key)
