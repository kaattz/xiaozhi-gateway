import json
import time
from collections.abc import Callable
from pathlib import Path

from app.models import ActiveContext, DeviceMapping


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
        context = ActiveContext(
            device_id=device.device_id,
            client_id=device.client_id,
            room_id=device.room_id,
            room_name=device.room_name,
            ha_area_id=device.ha_area_id,
            ha_device_id=device.ha_device_id,
            expires_at=self._now() + self._ttl_seconds,
        )
        self._write(context)
        return context

    def get(self) -> ActiveContext | None:
        if not self._state_path.exists():
            return None

        context = ActiveContext.model_validate_json(
            self._state_path.read_text(encoding="utf-8")
        )
        if context.expires_at <= self._now():
            self.clear()
            return None
        return context

    def clear(self) -> None:
        self._state_path.unlink(missing_ok=True)

    def _write(self, context: ActiveContext) -> None:
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        self._state_path.write_text(
            json.dumps(context.model_dump(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
