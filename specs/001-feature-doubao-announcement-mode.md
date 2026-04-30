# 001 Feature：多 TTS Provider 播报模式

## 目标

在 `xiaozhi-gateway` 增加独立播报能力：HA 发文本，gateway 调 TTS provider 生成音频，ESP32 本地播放。第一期 provider 为 Doubao TTS 2.0，保留 Bailian/Piper 扩展点。

## 代码证据

| 文件 | 证据 |
|---|---|
| `app/main.py` | 当前只保留 `/announcement/jobs` 和 `/announcement/jobs/{job_id}/frames`。 |
| `app/audio_jobs.py` | 通用内存 TTL job store，供播报任务分页读取。 |
| `app/audio_frames.py` | 通用 raw Opus 编码，供播报任务复用。 |
| `app/config.py` | 读取 `AnnouncementConfig`，旧远程文本配置已移除。 |
| `app/addon_options.py` | 已有 add-on options 渲染 `devices.yaml`，需要加入 `announcement` 配置渲染。 |
| `config.yaml` | 已有 add-on 配置页字段和 `addon_version`，新增 provider 配置应从这里进入。 |
| `tests/test_remote_text_api.py` | 只保留旧 `/remote-text` API 未注册的回归测试。 |

## 外部 API 依据

| Provider | 依据 |
|---|---|
| Doubao | 火山 Realtime TTS 文档：WebSocket `wss://ai-gateway.vei.volces.com/v1/realtime?model=doubao-tts`，通过 `tts_session.update` 设置 `voice`、`output_audio_format=pcm`、`output_audio_sample_rate=16000`，发送 `input_text.append` / `input_text.done`，接收 `response.audio.delta` base64 音频。文档链接：https://www.volcengine.com/docs/6893/1527770 |
| Bailian | 第一版只预留 provider 名称和接口，不绑定具体 API。 |

## 推荐架构

```text
HA text.<client_id>_bo_bao
  -> ESP32 HomeAssistantManager
  -> ESP32 AnnouncementAudioClient
  -> POST gateway /announcement/jobs
  -> gateway validates device and text
  -> gateway selects TTS provider
  -> Doubao provider returns 16 kHz mono PCM
  -> gateway encodes paged local-playback frames
  -> ESP32 GET /announcement/jobs/{job_id}/frames?offset=N&limit=4
  -> ESP32 plays audio locally
```

## Provider 抽象

新增模块建议：

| 文件 | 责任 |
|---|---|
| `app/announcement_config.py` 或扩展 `app/config.py` | 读取 `announcement` 配置。 |
| `app/tts_providers/base.py` | 定义 `TtsProvider.synthesize_pcm(text, config) -> bytes`。 |
| `app/tts_providers/doubao.py` | 调 Doubao Realtime TTS WebSocket，输出 PCM。 |
| `app/announcement_audio.py` | 调 provider、校验 PCM、编码 frames。 |
| `app/audio_jobs.py` | 通用音频 job store；当前供 announcement 使用。 |

Provider 接口：

```python
class TtsProvider(Protocol):
    def synthesize_pcm(self, text: str) -> bytes:
        ...
```

第一版仅实现：

```text
provider = "doubao"
```

对以下 provider 直接返回配置错误：

```text
bailian
piper
```

## 配置模型

Add-on 配置页新增：

```yaml
announcement_enabled: true
announcement_provider: doubao
doubao_api_key: ""
doubao_model: doubao-tts
doubao_voice: zh_female_kailangjiejie_moon_bigtts
doubao_sample_rate: 16000
```

渲染到 `/config/devices.yaml`：

```yaml
announcement:
  enabled: true
  provider: doubao
  frame_format: opus
  frame_duration_ms: 60
  doubao:
    api_key: "..."
    model: doubao-tts
    voice: zh_female_kailangjiejie_moon_bigtts
    sample_rate: 16000
```

密钥规则：

| 规则 | 说明 |
|---|---|
| 不打印 | 日志不能输出 `doubao_api_key`。 |
| 不下发 | API 响应不能包含 key。 |
| 不进 ESP32 | ESP32 只知道 gateway URL。 |

## API 设计

### `POST /announcement/jobs`

Request:

```json
{
  "device_id": "fc:01:2c:d2:5d:94",
  "client_id": "livingroom_xiaozhi",
  "text": "现在房间温度较高，是否打开空调。"
}
```

Response:

```json
{
  "job_id": "uuid",
  "device_id": "fc:01:2c:d2:5d:94",
  "sample_rate": 16000,
  "frame_duration_ms": 60,
  "frame_count": 42,
  "expires_at": 1777440000.0
}
```

### `GET /announcement/jobs/{job_id}/frames`

Query:

```text
offset=0&limit=4
```

Response:

```json
{
  "job_id": "uuid",
  "sample_rate": 16000,
  "frame_duration_ms": 60,
  "frames_base64": ["..."],
  "offset": 0,
  "next_offset": 4,
  "total_frames": 42
}
```

分页使用小页策略，默认 `limit=4`。

## ESP32 集成契约

虽然 feature 属于 `xiaozhi-gateway`，但验收需要 ESP32 配合：

| ESP32 模块 | 变更 |
|---|---|
| `HomeAssistantManager` | 新增 `text.<client_id>_bo_bao`，callback 调本地播报；不再发布 `text.<client_id>_zhi_ling`。 |
| `AnnouncementAudioClient` | 调 `/announcement/jobs` 和分页 `/frames`。 |
| `Application` | 新增 `PlayRemoteAnnouncement(text)`，本地播放，不调用 `Protocol::SendAudio()`。 |
| `AudioCodec` / audio service | 使用现有输出链路播放 decoded PCM/Opus。 |

关键禁令：

```text
播报模式不得调用 Protocol::SendAudio()
播报模式不得发送 listen/start
播报模式不得上传音频到小智云
```

## 错误处理

| 场景 | 行为 |
|---|---|
| 未知设备 | `404 device not found` |
| 空文本/过长文本 | `422` |
| announcement disabled | `400 announcement disabled` |
| provider 未实现 | `400 unsupported announcement provider` |
| Doubao API key 缺失 | `500 doubao api key is not configured` |
| Doubao 鉴权失败 | `502 doubao authentication failed` |
| Doubao 超时 | `504 doubao synthesis timeout` |
| 音频为空 | `500 tts produced no audio` |
| job 过期 | `404 job not found` |

不做 fallback。`doubao` 失败不能自动切到 `piper`。

## 验证策略

| 层 | 测试 |
|---|---|
| 配置 | add-on options 渲染 announcement 配置；key 不出现在响应里。 |
| Provider | mocked WebSocket：发送 session/update/text/done，接收 audio.delta，输出 PCM。 |
| API | create job、paged frames、unknown device、missing key、unsupported provider。 |
| 音频 | PCM 长度、采样率、分页响应体大小。 |
| ESP32 静态 | `bo_bao` 实体存在；播报路径不出现 `SendAudio` / `SendStartListening`。 |
| 手工 | HA 发送 `bo_bao` 文本，设备本地播放，不触发小智云回复。 |

## 需求追踪

| 需求 | Spec 章节 | 实施任务 | 验证 |
|---|---|---|---|
| REQ-1 | 推荐架构、API | Task 3/7 | API + ESP32 静态 |
| REQ-2 | Provider 抽象 | Task 2 | Provider 单测 |
| REQ-3 | 配置模型 | Task 1/2 | 配置测试 |
| REQ-4 | Provider 抽象、音频 | Task 2/4 | 音频测试 |
| REQ-5 | API 设计 | Task 3 | API 分页测试 |
| REQ-6 | ESP32 集成契约 | Task 7 | ESP32 静态 |
| REQ-7 | ESP32 集成契约 | Task 7/8 | 构建 + 手工 |
| REQ-8 | 错误处理 | Task 5 | 错误测试 |
| REQ-9 | 配置模型 | Task 1 | add-on 静态 |
| REQ-10 | API 设计 | Task 9 | drift check |
