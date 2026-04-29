# Remote Text Audio Bridge Design

## Goal

让 Home Assistant 发送一段文字后，小智官方云按“用户说了一句话”处理，而不是把长文本塞进 `listen/detect` 唤醒词字段。

## Core Decision

不修改官方云协议，不让 `xiaozhi-gateway` 直连官方云。`xiaozhi-gateway` 只负责把文本合成为 Opus 音频帧；ESP32 仍然作为唯一官方云客户端，把这些 Opus 帧当作麦克风音频上传。

## Non-Goals

| 不做 | 原因 |
|---|---|
| 不继续用 `listen/detect/text` 承载长文本 | 官方云已经明确拒绝：detect 只用于唤醒词 |
| 不让 gateway 伪装 ESP32 直连官方云 | 认证、会话状态、设备状态都会变复杂 |
| 不做多 TTS 兜底 | 失败应直接暴露，不做不严谨降级 |
| 不在 ESP32 上做中文 TTS | 资源、质量、维护成本都不合适 |

## Recommended Architecture

```text
Home Assistant text entity
  -> ESP32 HA MQTT bridge
  -> ESP32 RemoteTextAudioClient
  -> POST xiaozhi-gateway /remote-text/jobs
  -> gateway validates device and text
  -> gateway calls HAOS Piper add-on over Wyoming
  -> gateway normalizes audio to 16 kHz mono s16le PCM
  -> gateway encodes raw 60 ms Opus packets
  -> ESP32 downloads frames
  -> ESP32 opens Xiaozhi audio channel
  -> ESP32 sends listen/start
  -> ESP32 sends Opus frames through Protocol::SendAudio()
  -> ESP32 sends listen/stop
  -> Xiaozhi official cloud ASR/LLM/TTS handles the utterance
```

## Components

| Component | Repo | Responsibility |
|---|---|---|
| `RemoteTextJob` models | `xiaozhi-gateway` | Request/response schema for text-to-audio jobs |
| `tts_engine.py` | `xiaozhi-gateway` | Call HAOS Piper add-on and produce WAV/PCM |
| `opus_encoder.py` | `xiaozhi-gateway` | Convert PCM into raw Opus packet list |
| `remote_text_jobs.py` | `xiaozhi-gateway` | Store generated frames with TTL |
| `/remote-text/jobs` | `xiaozhi-gateway` | Create a text audio job |
| `/remote-text/jobs/{job_id}/frames` | `xiaozhi-gateway` | Return generated Opus frames |
| `RemoteTextAudioClient` | `xiaozhi-esp32` | Call gateway and parse frame payloads |
| `Application::InvokeRemoteText()` | `xiaozhi-esp32` | Open audio channel and upload frames |
| HA MQTT text callback | `xiaozhi-esp32` | Route text to remote audio flow, not `WakeWordInvoke(text)` |

## Gateway API

### `POST /remote-text/jobs`

Request:

```json
{
  "device_id": "aa:bb:cc:dd:ee:ff",
  "client_id": "optional-client-id",
  "text": "请说一句：现在房间温度比较高，是否打开空调"
}
```

Response:

```json
{
  "job_id": "20260429-abcdef",
  "device_id": "aa:bb:cc:dd:ee:ff",
  "sample_rate": 16000,
  "frame_duration_ms": 60,
  "frame_count": 42,
  "expires_at": 1777440000.0
}
```

Rules:

| Rule | Behavior |
|---|---|
| Unknown device | `404 device not found` |
| Empty text | `422` |
| Text too long | `422` |
| Piper add-on fails | `500 tts synthesis failed` |
| Opus encoding fails | `500 opus encoding failed` |

### `GET /remote-text/jobs/{job_id}/frames`

Response:

```json
{
  "job_id": "20260429-abcdef",
  "sample_rate": 16000,
  "frame_duration_ms": 60,
  "frames_base64": [
    "....",
    "...."
  ]
}
```

First version returns all frames in one response. If memory becomes a problem, add paged reads later. Do not build streaming until the one-shot path proves correct.

### `DELETE /remote-text/jobs/{job_id}`

Optional cleanup endpoint. Jobs also expire by TTL.

## Gateway Runtime Dependencies

| Dependency | Purpose |
|---|---|
| HAOS Piper add-on | Chinese TTS over Wyoming TCP |
| `ffmpeg` binary | Resample WAV to 16 kHz mono s16le PCM |
| `libopus` system library | Runtime codec library used by `opuslib` |
| `opuslib` Python package | Encode raw Opus packets |

Suggested config:

```yaml
remote_text:
  enabled: true
  max_text_length: 120
  job_ttl_seconds: 120
  provider: "wyoming"
  wyoming_host: "core-piper"
  wyoming_port: 10200
  ffmpeg_binary: "ffmpeg"
```

## ESP32 Flow

```text
HomeAssistantManager::setOnText(text)
  -> Application::InvokeRemoteText(text)
  -> RemoteTextAudioClient::CreateJob(text)
  -> RemoteTextAudioClient::FetchFrames(job_id)
  -> protocol_->OpenAudioChannel()
  -> protocol_->SendStartListening(kListeningModeAutoStop)
  -> SendAudio(frame 0..n)
  -> protocol_->SendStopListening()
```

Do not call `WakeWordInvoke(text)` for remote text. Keep `WakeWordInvoke("你好小智")` only for wake buttons and real wake-word paths.

## Error Handling

| Failure | Behavior |
|---|---|
| gateway unavailable | Log error and return to idle |
| TTS job creation fails | Log response body and return to idle |
| frame fetch fails | Log response body and return to idle |
| official audio channel cannot open | Log and return to idle |
| `SendAudio` fails mid-job | Stop sending, send stop if possible, return to idle |

No fallback TTS. No retry loop in first version. Repeated command attempts should be explicit user actions.

## Security

This remains an internal network service. First version uses existing device identification fields:

| Field | Source |
|---|---|
| `device_id` | ESP32 MAC address |
| `client_id` | board UUID / configured client id |

Do not expose `xiaozhi-gateway` publicly. If it must cross network boundaries later, add a shared token before exposing any endpoint.

## Test Strategy

| Layer | Tests |
|---|---|
| Gateway models | reject empty and overlong text |
| Gateway device validation | unknown device returns 404 |
| Gateway TTS service | mocked Wyoming Piper socket returns WAV bytes |
| Gateway Opus service | mocked PCM normalization and Opus encoder return deterministic frame bytes |
| Gateway API | create job, fetch frames, expire job |
| ESP32 static tests | text callback no longer calls `WakeWordInvoke(text)` |
| ESP32 unit/static tests | remote text client builds expected JSON and parses frames |

## Open Risks

| Risk | Mitigation |
|---|---|
| Piper Chinese voice ASR recognition is poor | Run a manual recognition test before polishing |
| Opus framing mismatches server expectation | Send raw Opus packets, not Ogg Opus pages; match existing firmware defaults: 16 kHz mono, 60 ms frames |
| ESP32 memory pressure when fetching all frames | Add pagination only if one-shot response fails |
| HA text entity name says wake_word | Rename UI label later after core flow works |
