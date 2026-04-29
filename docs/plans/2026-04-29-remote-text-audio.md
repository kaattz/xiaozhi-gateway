# Remote Text Audio Bridge Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a gateway-backed remote text flow that converts Home Assistant text into Opus audio frames and lets ESP32 upload them to Xiaozhi official cloud as microphone audio.

**Architecture:** `xiaozhi-gateway` runs as a HAOS add-on, calls the HAOS Piper add-on at `core-piper:10200` over Wyoming, converts the generated audio with `ffmpeg`, then encodes raw Opus frames with `opuslib`. ESP32 remains the only client connected to Xiaozhi official cloud and uploads generated Opus frames through the existing `Protocol::SendAudio()` path. This avoids misusing `listen/detect/text` for long text.

**Tech Stack:** FastAPI, Pydantic, pytest, HAOS Piper add-on/Wyoming, ffmpeg, libopus, opuslib, ESP-IDF C++, cJSON, existing Xiaozhi `Protocol`.

**2026-04-29 update:** the original local-Piper snippets below are superseded by the HAOS add-on architecture. The implemented gateway default is `remote_text.provider=wyoming`, `wyoming_host=core-piper`, `wyoming_port=10200`.

---

## Preconditions

| Item | Requirement |
|---|---|
| Gateway repo | `C:\Code\xiaozhi-gateway` |
| ESP32 repo | `C:\Code\xiaozhi-esp32` |
| TTS service | HAOS Piper add-on available as `core-piper:10200` |
| PCM normalizer | `ffmpeg` available in gateway runtime |
| Opus runtime | `libopus` available in gateway runtime |
| Opus encoder | `opuslib` Python package available in gateway runtime |

Do not create a new git worktree unless the user explicitly approves it.

## Task 1: Add Gateway Remote Text Models

**Files:**
- Modify: `C:\Code\xiaozhi-gateway\app\models.py`
- Test: `C:\Code\xiaozhi-gateway\tests\test_remote_text_models.py`

**Step 1: Write failing tests**

Create `tests/test_remote_text_models.py`:

```python
import pytest
from pydantic import ValidationError

from app.models import RemoteTextJobRequest


def test_remote_text_rejects_empty_text():
    with pytest.raises(ValidationError):
        RemoteTextJobRequest(device_id="aa:bb:cc:dd:ee:ff", text="")


def test_remote_text_rejects_overlong_text():
    with pytest.raises(ValidationError):
        RemoteTextJobRequest(device_id="aa:bb:cc:dd:ee:ff", text="x" * 121)


def test_remote_text_accepts_valid_text():
    request = RemoteTextJobRequest(
        device_id="aa:bb:cc:dd:ee:ff",
        client_id="livingroom_xiaozhi",
        text="打开客厅灯",
    )
    assert request.text == "打开客厅灯"
```

**Step 2: Run test to verify it fails**

Run:

```powershell
pytest tests/test_remote_text_models.py -v
```

Expected: FAIL because `RemoteTextJobRequest` does not exist.

**Step 3: Implement models**

Add to `app/models.py`:

```python
from pydantic import BaseModel, Field


class RemoteTextJobRequest(BaseModel):
    device_id: str
    client_id: str = ""
    text: str = Field(min_length=1, max_length=120)


class RemoteTextJobCreated(BaseModel):
    job_id: str
    device_id: str
    sample_rate: int
    frame_duration_ms: int
    frame_count: int
    expires_at: float


class RemoteTextFramesResponse(BaseModel):
    job_id: str
    sample_rate: int
    frame_duration_ms: int
    frames_base64: list[str]
```

If `BaseModel` is already imported, only extend the existing import.

**Step 4: Run test to verify it passes**

Run:

```powershell
pytest tests/test_remote_text_models.py -v
```

Expected: PASS.

**Step 5: Commit**

```powershell
git add app/models.py tests/test_remote_text_models.py
git commit -m "feat: add remote text job models"
```

## Task 2: Add Gateway Remote Text Job Store

**Files:**
- Create: `C:\Code\xiaozhi-gateway\app\remote_text_jobs.py`
- Test: `C:\Code\xiaozhi-gateway\tests\test_remote_text_jobs.py`

**Step 1: Write failing tests**

Create `tests/test_remote_text_jobs.py`:

```python
from app.remote_text_jobs import RemoteTextJobStore


def test_job_store_creates_and_reads_frames():
    now = 1000.0
    store = RemoteTextJobStore(now=lambda: now)

    job = store.create(
        device_id="aa:bb:cc:dd:ee:ff",
        frames=[b"one", b"two"],
        sample_rate=16000,
        frame_duration_ms=60,
    )

    stored = store.get(job.job_id)
    assert stored is not None
    assert stored.frames == [b"one", b"two"]
    assert stored.expires_at == 1120.0


def test_job_store_expires_jobs():
    current = 1000.0
    store = RemoteTextJobStore(now=lambda: current)
    job = store.create("device", [b"one"], 16000, 60)

    current = 1121.0

    assert store.get(job.job_id) is None
```

**Step 2: Run test to verify it fails**

Run:

```powershell
pytest tests/test_remote_text_jobs.py -v
```

Expected: FAIL because `app.remote_text_jobs` does not exist.

**Step 3: Implement store**

Create `app/remote_text_jobs.py`:

```python
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class RemoteTextJob:
    job_id: str
    device_id: str
    frames: list[bytes]
    sample_rate: int
    frame_duration_ms: int
    expires_at: float


class RemoteTextJobStore:
    def __init__(
        self,
        ttl_seconds: int = 120,
        now: Callable[[], float] = time.time,
    ) -> None:
        self._ttl_seconds = ttl_seconds
        self._now = now
        self._jobs: dict[str, RemoteTextJob] = {}

    def create(
        self,
        device_id: str,
        frames: list[bytes],
        sample_rate: int,
        frame_duration_ms: int,
    ) -> RemoteTextJob:
        self._cleanup()
        job = RemoteTextJob(
            job_id=uuid.uuid4().hex,
            device_id=device_id,
            frames=frames,
            sample_rate=sample_rate,
            frame_duration_ms=frame_duration_ms,
            expires_at=self._now() + self._ttl_seconds,
        )
        self._jobs[job.job_id] = job
        return job

    def get(self, job_id: str) -> RemoteTextJob | None:
        self._cleanup()
        return self._jobs.get(job_id)

    def delete(self, job_id: str) -> bool:
        return self._jobs.pop(job_id, None) is not None

    def _cleanup(self) -> None:
        now = self._now()
        expired = [
            job_id
            for job_id, job in self._jobs.items()
            if job.expires_at <= now
        ]
        for job_id in expired:
            del self._jobs[job_id]
```

**Step 4: Run test to verify it passes**

Run:

```powershell
pytest tests/test_remote_text_jobs.py -v
```

Expected: PASS.

**Step 5: Commit**

```powershell
git add app/remote_text_jobs.py tests/test_remote_text_jobs.py
git commit -m "feat: add remote text job store"
```

## Task 3: Add Gateway TTS And Raw Opus Service Interfaces

**Files:**
- Modify: `C:\Code\xiaozhi-gateway\pyproject.toml`
- Create: `C:\Code\xiaozhi-gateway\app\remote_text_audio.py`
- Test: `C:\Code\xiaozhi-gateway\tests\test_remote_text_audio.py`

**Step 1: Write failing tests**

Create `tests/test_remote_text_audio.py`:

```python
from pathlib import Path

from app.remote_text_audio import encode_raw_opus_frames


def test_encode_raw_opus_frames_encodes_one_60ms_packet_for_960_samples():
    pcm = b"\x00\x00" * 960


    frames = encode_raw_opus_frames(pcm)

    assert len(frames) == 1
    assert frames[0]
```

**Step 2: Run test to verify it fails**

Run:

```powershell
pytest tests/test_remote_text_audio.py -v
```

Expected: FAIL because `remote_text_audio` does not exist.

**Step 3: Add opuslib dependency**

Add to `pyproject.toml` project dependencies:

```toml
"opuslib>=3.0.1",
```

If using `uv`, refresh the lock file:

```powershell
uv lock
```

**Step 4: Implement minimal audio helpers**

Create `app/remote_text_audio.py`:

```python
# Current implementation:
# 1. synthesize_remote_text_wav() calls HAOS Piper add-on over Wyoming.
# 2. normalize_wav_to_pcm_s16le() calls ffmpeg.
# 3. encode_raw_opus_frames() calls opuslib/libopus.
```

**Step 5: Run test to verify it passes**

Run:

```powershell
pytest tests/test_remote_text_audio.py -v
```

Expected: PASS.

**Step 6: Manual command verification**

Run against the HAOS Piper add-on:

```powershell
python - <<'PY'
from app.config import RemoteTextConfig
from app.remote_text_audio import synthesize_remote_text_wav, normalize_wav_to_pcm_s16le, encode_raw_opus_frames
wav = synthesize_remote_text_wav("现在房间温度比较高", RemoteTextConfig())
pcm = normalize_wav_to_pcm_s16le(wav, "ffmpeg")
frames = encode_raw_opus_frames(pcm)
print(len(wav), len(pcm), len(frames))
PY
```

Expected: prints non-zero sizes and frame count. Frames are raw Opus packets, not Ogg pages.

**Step 7: Commit**

```powershell
git add pyproject.toml uv.lock app/remote_text_audio.py tests/test_remote_text_audio.py
git commit -m "feat: add remote text audio helpers"
```

## Task 4: Add Gateway Remote Text API

**Files:**
- Modify: `C:\Code\xiaozhi-gateway\app\main.py`
- Modify: `C:\Code\xiaozhi-gateway\app\config.py`
- Modify: `C:\Code\xiaozhi-gateway\app\models.py`
- Test: `C:\Code\xiaozhi-gateway\tests\test_remote_text_api.py`

**Step 1: Write failing API tests with monkeypatched audio**

Create `tests/test_remote_text_api.py`:

```python
from fastapi.testclient import TestClient

import app.main as main
from app.main import app

client = TestClient(app)


def test_remote_text_creates_and_fetches_frames(monkeypatch):
    client.delete("/active-context")

    monkeypatch.setattr(main, "synthesize_remote_text_wav", lambda text, config: b"wav")
    monkeypatch.setattr(main, "normalize_wav_to_pcm_s16le", lambda wav, ffmpeg_binary: b"pcm")
    monkeypatch.setattr(main, "encode_raw_opus_frames", lambda pcm: [b"one", b"two"])

    created = client.post(
        "/remote-text/jobs",
        json={
            "device_id": "aa:bb:cc:dd:ee:ff",
            "client_id": "xiaozhi-living-room",
            "text": "现在房间温度比较高",
        },
    )

    assert created.status_code == 200
    body = created.json()
    assert body["sample_rate"] == 16000
    assert body["frame_duration_ms"] == 60
    assert body["frame_count"] == 2

    frames = client.get(f"/remote-text/jobs/{body['job_id']}/frames")
    assert frames.status_code == 200
    assert frames.json()["frames_base64"] == ["b25l", "dHdv"]


def test_remote_text_rejects_unknown_device():
    response = client.post(
        "/remote-text/jobs",
        json={"device_id": "missing", "text": "hello"},
    )

    assert response.status_code == 404
```

**Step 2: Run test to verify it fails**

Run:

```powershell
pytest tests/test_remote_text_api.py -v
```

Expected: FAIL because API routes do not exist.

**Step 3: Add config loader**

Add a small remote text config in `app/config.py`:

```python
from pydantic import BaseModel


class RemoteTextConfig(BaseModel):
    provider: str = "wyoming"
    wyoming_host: str = "core-piper"
    wyoming_port: int = 10200
    ffmpeg_binary: str = "ffmpeg"
```

For first version, keep defaults hardcoded. Move to YAML only after the API works.

**Step 4: Add API routes**

In `app/main.py`, add imports:

```python
import base64

from app.config import RemoteTextConfig
from app.models import RemoteTextFramesResponse, RemoteTextJobCreated, RemoteTextJobRequest
from app.remote_text_audio import FRAME_DURATION_MS, SAMPLE_RATE, encode_raw_opus_frames, normalize_wav_to_pcm_s16le, synthesize_remote_text_wav
from app.remote_text_jobs import RemoteTextJobStore
```

Add module store:

```python
remote_text_jobs = RemoteTextJobStore()
remote_text_config = RemoteTextConfig()
```

Add routes:

```python
@app.post("/remote-text/jobs", response_model=RemoteTextJobCreated)
def create_remote_text_job(request: RemoteTextJobRequest) -> RemoteTextJobCreated:
    device = next(
        (device for device in load_devices() if device.device_id == request.device_id),
        None,
    )
    if device is None:
        raise HTTPException(status_code=404, detail="device not found")

    wav = synthesize_remote_text_wav(request.text, remote_text_config)
    pcm = normalize_wav_to_pcm_s16le(wav, remote_text_config.ffmpeg_binary)
    frames = encode_raw_opus_frames(pcm)
    if not frames:
        raise HTTPException(status_code=500, detail="opus encoding produced no frames")

    job = remote_text_jobs.create(
        device_id=device.device_id,
        frames=frames,
        sample_rate=SAMPLE_RATE,
        frame_duration_ms=FRAME_DURATION_MS,
    )
    return RemoteTextJobCreated(
        job_id=job.job_id,
        device_id=job.device_id,
        sample_rate=job.sample_rate,
        frame_duration_ms=job.frame_duration_ms,
        frame_count=len(job.frames),
        expires_at=job.expires_at,
    )


@app.get("/remote-text/jobs/{job_id}/frames", response_model=RemoteTextFramesResponse)
def get_remote_text_frames(job_id: str) -> RemoteTextFramesResponse:
    job = remote_text_jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return RemoteTextFramesResponse(
        job_id=job.job_id,
        sample_rate=job.sample_rate,
        frame_duration_ms=job.frame_duration_ms,
        frames_base64=[
            base64.b64encode(frame).decode("ascii")
            for frame in job.frames
        ],
    )
```

**Step 5: Run test to verify it passes**

Run:

```powershell
pytest tests/test_remote_text_api.py -v
```

Expected: PASS.

**Step 6: Run all gateway tests**

Run:

```powershell
pytest -v
```

Expected: PASS.

**Step 7: Commit**

```powershell
git add app/main.py app/config.py app/models.py tests/test_remote_text_api.py
git commit -m "feat: add remote text audio API"
```

## Task 5: Add Gateway Documentation

**Files:**
- Modify: `C:\Code\xiaozhi-gateway\README.md`
- Create or modify: `C:\Code\xiaozhi-gateway\config\devices.example.yaml`

**Step 1: Document runtime dependencies**

Add to `README.md`:

```markdown
## Remote Text Audio

The gateway can convert a text instruction into Opus audio frames for ESP32 to upload as microphone audio.

Required runtime services and libraries:

- HAOS Piper add-on: `core-piper:10200`
- `ffmpeg`
- `libopus`

Required Python dependency:

- `opuslib`

First version uses the HAOS Piper add-on through Wyoming:

```yaml
remote_text:
  provider: "wyoming"
  wyoming_host: "core-piper"
  wyoming_port: 10200
  ffmpeg_binary: "ffmpeg"
```

Do not expose this service publicly.
```

**Step 2: Run docs check**

Run:

```powershell
pytest -v
```

Expected: PASS.

**Step 3: Commit**

```powershell
git add README.md config/devices.example.yaml
git commit -m "docs: document remote text audio"
```

## Task 6: Add ESP32 Remote Text Client Skeleton

**Files:**
- Create: `C:\Code\xiaozhi-esp32\main\remote_text_audio_client.h`
- Create: `C:\Code\xiaozhi-esp32\main\remote_text_audio_client.cc`
- Modify: `C:\Code\xiaozhi-esp32\main\CMakeLists.txt`
- Test: `C:\Code\xiaozhi-esp32\tests\test_remote_text_audio_static.py`

**Step 1: Write failing static tests**

Create `tests/test_remote_text_audio_static.py`:

```python
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_remote_text_client_exists_and_uses_gateway():
    header = read("main/remote_text_audio_client.h")
    source = read("main/remote_text_audio_client.cc")

    assert "class RemoteTextAudioClient" in header
    assert "/remote-text/jobs" in source
    assert "frames_base64" in source
    assert "BuildCreateJobPayload" in source
```

**Step 2: Run test to verify it fails**

Run:

```powershell
pytest tests/test_remote_text_audio_static.py -v
```

Expected: FAIL because files do not exist.

**Step 3: Add header**

Create `main/remote_text_audio_client.h`:

```cpp
#ifndef REMOTE_TEXT_AUDIO_CLIENT_H
#define REMOTE_TEXT_AUDIO_CLIENT_H

#include <cstdint>
#include <string>
#include <vector>

struct RemoteTextAudioFrames {
    int sample_rate = 0;
    int frame_duration_ms = 0;
    std::vector<std::vector<uint8_t>> frames;
};

class RemoteTextAudioClient {
public:
    bool FetchFrames(const std::string& text, RemoteTextAudioFrames& out);

private:
    std::string BuildEndpointUrl(const std::string& path) const;
    std::string BuildCreateJobPayload(const std::string& text) const;
};

#endif
```

**Step 4: Add source skeleton**

Create `main/remote_text_audio_client.cc` with JSON construction, HTTP POST, HTTP GET, and base64 decode. Keep it fail-fast:

```cpp
#include "remote_text_audio_client.h"

#include "board.h"
#include "system_info.h"

#include <cJSON.h>
#include <esp_log.h>

#define TAG "RemoteTextAudioClient"

bool RemoteTextAudioClient::FetchFrames(const std::string& text, RemoteTextAudioFrames& out) {
    // Implement in Task 7 after the application call site is clear.
    (void)text;
    (void)out;
    ESP_LOGE(TAG, "Remote text audio client is not implemented yet");
    return false;
}

std::string RemoteTextAudioClient::BuildEndpointUrl(const std::string& path) const {
    std::string gateway_url = CONFIG_WAKE_ARBITRATION_GATEWAY_URL;
    while (!gateway_url.empty() && gateway_url.back() == '/') {
        gateway_url.pop_back();
    }
    if (gateway_url.empty()) {
        return "";
    }
    return gateway_url + path;
}

std::string RemoteTextAudioClient::BuildCreateJobPayload(const std::string& text) const {
    cJSON* payload = cJSON_CreateObject();
    if (payload == nullptr) {
        return "{}";
    }
    cJSON_AddStringToObject(payload, "device_id", SystemInfo::GetMacAddress().c_str());
    cJSON_AddStringToObject(payload, "client_id", Board::GetInstance().GetUuid().c_str());
    cJSON_AddStringToObject(payload, "text", text.c_str());

    auto json_str = cJSON_PrintUnformatted(payload);
    std::string json = "{}";
    if (json_str != nullptr) {
        json = json_str;
        cJSON_free(json_str);
    }
    cJSON_Delete(payload);
    return json;
}
```

**Step 5: Add to CMake sources**

Add `remote_text_audio_client.cc` to `main/CMakeLists.txt`.

**Step 6: Run test to verify it passes**

Run:

```powershell
pytest tests/test_remote_text_audio_static.py -v
```

Expected: PASS.

**Step 7: Commit**

```powershell
git add main/remote_text_audio_client.h main/remote_text_audio_client.cc main/CMakeLists.txt tests/test_remote_text_audio_static.py
git commit -m "feat: add remote text audio client skeleton"
```

## Task 7: Implement ESP32 Remote Text Upload Flow

**Files:**
- Modify: `C:\Code\xiaozhi-esp32\main\application.h`
- Modify: `C:\Code\xiaozhi-esp32\main\application.cc`
- Modify: `C:\Code\xiaozhi-esp32\main\home_assistant_manager.cc`
- Modify: `C:\Code\xiaozhi-esp32\main\remote_text_audio_client.cc`
- Test: `C:\Code\xiaozhi-esp32\tests\test_remote_text_audio_static.py`

**Step 1: Extend static test**

Append assertions:

```python
def test_ha_text_uses_remote_text_audio_not_wake_word_detect():
    ha_source = read("main/home_assistant_manager.cc")
    app_header = read("main/application.h")
    app_source = read("main/application.cc")

    assert "InvokeRemoteText" in app_header
    assert "InvokeRemoteText" in app_source
    assert "WakeWordInvoke(text)" not in ha_source
```

**Step 2: Run test to verify it fails**

Run:

```powershell
pytest tests/test_remote_text_audio_static.py -v
```

Expected: FAIL because `InvokeRemoteText` does not exist and HA still calls `WakeWordInvoke(text)`.

**Step 3: Implement client HTTP parsing**

Complete `RemoteTextAudioClient::FetchFrames()`:

1. POST `/remote-text/jobs`.
2. Parse `job_id`.
3. GET `/remote-text/jobs/{job_id}/frames`.
4. Parse `sample_rate`, `frame_duration_ms`, `frames_base64`.
5. Decode each frame into `out.frames`.
6. Return false on any malformed or non-200 response.

Do not retry.

**Step 4: Add application entry**

Add to `application.h`:

```cpp
void InvokeRemoteText(const std::string& text);
```

Add to `application.cc`:

```cpp
void Application::InvokeRemoteText(const std::string& text) {
    if (text.empty() || protocol_ == nullptr) {
        return;
    }

    Schedule([this, text]() {
        RemoteTextAudioFrames audio;
        RemoteTextAudioClient client;
        if (!client.FetchFrames(text, audio) || audio.frames.empty()) {
            ESP_LOGE(TAG, "Failed to fetch remote text audio");
            return;
        }

        if (!protocol_->IsAudioChannelOpened() && !protocol_->OpenAudioChannel()) {
            ESP_LOGE(TAG, "Failed to open audio channel for remote text");
            return;
        }

        SetListeningMode(kListeningModeAutoStop);
        protocol_->SendStartListening(kListeningModeAutoStop);

        uint32_t timestamp = 0;
        for (const auto& frame : audio.frames) {
            auto packet = std::make_unique<AudioStreamPacket>();
            packet->sample_rate = audio.sample_rate;
            packet->frame_duration = audio.frame_duration_ms;
            packet->timestamp = timestamp;
            packet->payload = frame;
            if (!protocol_->SendAudio(std::move(packet))) {
                ESP_LOGE(TAG, "Failed to send remote text audio frame");
                protocol_->SendStopListening();
                return;
            }
            timestamp += audio.frame_duration_ms;
            vTaskDelay(pdMS_TO_TICKS(audio.frame_duration_ms));
        }

        protocol_->SendStopListening();
    });
}
```

Include `remote_text_audio_client.h`.

**Step 5: Change HA text callback**

In `home_assistant_manager.cc`, replace:

```cpp
Application::GetInstance().WakeWordInvoke(text);
```

with:

```cpp
Application::GetInstance().InvokeRemoteText(text);
```

Keep wake-up button using `WakeWordInvoke("你好小智")`.

**Step 6: Run static tests**

Run:

```powershell
pytest tests/test_remote_text_audio_static.py tests/test_ha_mqtt_static.py -v
```

Expected: PASS after updating old HA MQTT test expectations.

**Step 7: Build firmware target**

Run the selected board build command, for example:

```powershell
idf.py build
```

Expected: build succeeds.

**Step 8: Commit**

```powershell
git add main/application.h main/application.cc main/home_assistant_manager.cc main/remote_text_audio_client.cc tests/test_remote_text_audio_static.py tests/test_ha_mqtt_static.py
git commit -m "feat: upload remote text audio through xiaozhi protocol"
```

## Task 8: End-To-End Manual Test

**Files:**
- Modify only if test exposes a real bug.

**Step 1: Start gateway**

Run:

```powershell
uvicorn app.main:app --host 0.0.0.0 --port 8125
```

Expected: gateway starts.

**Step 2: Verify remote text job directly**

Run:

```powershell
curl -X POST http://127.0.0.1:8125/remote-text/jobs `
  -H "Content-Type: application/json" `
  -d "{\"device_id\":\"aa:bb:cc:dd:ee:ff\",\"text\":\"现在房间温度比较高\"}"
```

Expected: JSON with non-zero `frame_count`.

**Step 3: Flash and monitor ESP32**

Run normal firmware flash/monitor for the target board.

Expected logs:

```text
RemoteTextAudioClient: created remote text job
RemoteTextAudioClient: fetched N remote text frames
Application: sending remote text audio
```

**Step 4: Send HA command**

Run in Home Assistant:

```yaml
action: text.set_value
target:
  entity_id: text.livingroom_xiaozhi_zhi_ling
data:
  value: "现在房间温度比较高，是否打开空调"
```

Expected:

| Expected | Meaning |
|---|---|
| ESP32 enters listening | Audio channel opened |
| HA `user_message` updates | Official cloud ASR recognized text |
| Device speaks answer | LLM/TTS handled the utterance |
| No `detect 仅用于唤醒词` error | Long text no longer uses detect |

**Step 5: Commit fixes if needed**

Only commit if code changed:

```powershell
git status --short
git add <changed-files>
git commit -m "fix: stabilize remote text audio flow"
```
