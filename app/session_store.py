import json
import time
from collections.abc import Callable
from pathlib import Path

from app.models import ActiveContext, DeviceMapping

MULTIPLE_ACTIVE_CONTEXTS = "multiple_active_contexts"


class SessionStore:
    def __init__(
        self,
        state_path: Path = Path("state.json"),
        ttl_seconds: int = 120,
        now: Callable[[], float] = time.time,
    ) -> None:
        self._state_path = state_path
        self._ttl_seconds = ttl_seconds
        self._now = now

    def set(self, device: DeviceMapping) -> ActiveContext:
        contexts = self._read_contexts()
        contexts = self._active_contexts(contexts)
        context = ActiveContext(
            device_id=device.device_id,
            client_id=device.client_id,
            room_id=device.room_id,
            room_name=device.room_name,
            ha_area_id=device.ha_area_id,
            ha_device_id=device.ha_device_id,
            expires_at=self._now() + self._ttl_seconds,
        )
        contexts[context.device_id] = context
        self._write_contexts(contexts)
        return context

    def get(self, device_id: str | None = None) -> ActiveContext | str | None:
        contexts = self._read_contexts()
        active = self._active_contexts(contexts)
        if active != contexts:
            self._write_contexts(active)

        if device_id is not None:
            return active.get(device_id)

        if not active:
            return None
        if len(active) > 1:
            return MULTIPLE_ACTIVE_CONTEXTS
        return next(iter(active.values()))

    def clear(self, device_id: str | None = None) -> None:
        if device_id is None:
            self._state_path.unlink(missing_ok=True)
            return

        contexts = self._read_contexts()
        contexts.pop(device_id, None)
        self._write_contexts(self._active_contexts(contexts))

    def _read_contexts(self) -> dict[str, ActiveContext]:
        if not self._state_path.exists():
            return {}

        raw = json.loads(self._state_path.read_text(encoding="utf-8"))
        if "device_id" in raw:
            context = ActiveContext.model_validate(raw)
            return {context.device_id: context}

        contexts: dict[str, ActiveContext] = {}
        for device_id, payload in raw.items():
            context = ActiveContext.model_validate(payload)
            contexts[device_id] = context
        return contexts

    def _active_contexts(
        self, contexts: dict[str, ActiveContext]
    ) -> dict[str, ActiveContext]:
        return {
            device_id: context
            for device_id, context in contexts.items()
            if context.expires_at > self._now()
        }

    def _write_contexts(self, contexts: dict[str, ActiveContext]) -> None:
        if not contexts:
            self._state_path.unlink(missing_ok=True)
            return

        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        self._state_path.write_text(
            json.dumps(
                {
                    device_id: context.model_dump()
                    for device_id, context in contexts.items()
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
