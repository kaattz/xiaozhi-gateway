# 001 实施计划：多 TTS Provider 播报模式

## 执行规则

| 规则 | 要求 |
|---|---|
| 先确认 | 未经用户明确说“开始实施”，不得写功能代码。 |
| 不提交 | 提交、推送、刷机前必须单独确认。 |
| 不降级 | Doubao 失败不得自动切到 Piper。 |
| 不泄密 | 任何日志、API 响应、测试快照不得包含真实 API key。 |

## Task 0：实施前检查

<files>

- `specs/001-req-doubao-announcement-mode.md`
- `specs/001-feature-doubao-announcement-mode.md`
- `app/main.py`
- `app/config.py`
- `app/addon_options.py`
- `app/audio_frames.py`
- `app/audio_jobs.py`
- `config.yaml`
- `tests/`

<action>

- 逐条读取 req 和 feature。
- 确认 gateway 不再暴露旧 `/remote-text` API。
- 确认 add-on 配置页字段只保留 `announcement` 语义。
- 确认 ESP32 companion 变更范围，避免误把播报音频发到小智云。

<verify>

- `git status -sb`
- `rg -n "remote-text|RemoteText|SendAudio|Protocol::SendAudio|piper|wyoming|addon_version" app tests config.yaml run.sh`

<done>

- 明确现有代码边界和本次实施文件范围。

## Task 1：新增 announcement 配置模型和 add-on options

<files>

- `app/config.py`
- `app/addon_options.py`
- `config.yaml`
- `config/devices.example.yaml`
- `tests/test_addon_static.py`
- `tests/test_addon_options.py`
- `tests/test_devices.py`

<action>

- 新增 `AnnouncementConfig`。
- add-on 配置页加入 `announcement_enabled`、`announcement_provider`、`doubao_api_key`、`doubao_model`、`doubao_voice`、`doubao_sample_rate`。
- `app.addon_options` 将配置渲染到 `/config/devices.yaml` 的 `announcement` 节点。
- 版本号升到下一版，例如 `0.1.3`。

<verify>

- `uv run pytest tests/test_addon_static.py tests/test_addon_options.py tests/test_devices.py -v`
- YAML 解析检查：`uv run python -c "import yaml, pathlib; [yaml.safe_load(pathlib.Path(p).read_text(encoding='utf-8')) for p in ['config.yaml','config/devices.example.yaml']]; print('yaml ok')"`

<done>

- 配置页能表达 Doubao provider。
- 未配置真实 key 时测试仍可运行。

## Task 2：实现 TTS provider 抽象和 Doubao provider

<files>

- `app/tts_providers/__init__.py`
- `app/tts_providers/base.py`
- `app/tts_providers/doubao.py`
- `app/announcement_audio.py`
- `pyproject.toml`
- `uv.lock`
- `tests/test_doubao_tts_provider.py`
- `tests/test_announcement_audio.py`

<action>

- 定义 provider 接口：输入文本，输出 `16 kHz mono s16le PCM`。
- 新增 Doubao WebSocket 客户端。
- 发送 `tts_session.update`、`input_text.append`、`input_text.done`。
- 接收 `response.audio.delta`，base64 解码后合并 PCM。
- 对空音频、鉴权失败、超时、非 PCM 输出显式报错。

<verify>

- 使用 mocked WebSocket 测试事件顺序和 PCM 输出。
- `uv run pytest tests/test_doubao_tts_provider.py tests/test_announcement_audio.py -v`

<done>

- Doubao provider 不依赖真实网络即可通过单元测试。
- 日志和异常不包含 API key。

## Task 3：新增 announcement job API

<files>

- `app/models.py`
- `app/main.py`
- `app/audio_jobs.py`
- `tests/test_announcement_api.py`

<action>

- 新增 `AnnouncementJobRequest`、`AnnouncementJobCreated`、`AnnouncementFramesResponse`。
- 新增 `POST /announcement/jobs`。
- 新增 `GET /announcement/jobs/{job_id}/frames?offset=0&limit=4`。
- 使用通用 audio job store。
- 默认分页 `limit=4`，上限 `16`。

<verify>

- `uv run pytest tests/test_announcement_api.py -v`

<done>

- API 支持创建播报 job 和分页读取。
- 响应结构与 ESP32 分页客户端一致。

## Task 4：音频编码和响应体大小约束

<files>

- `app/announcement_audio.py`
- `app/audio_frames.py`
- `tests/test_announcement_audio.py`
- `tests/test_announcement_api.py`

<action>

- Doubao PCM 统一按 `SAMPLE_RATE=16000`、`FRAME_DURATION_MS=60` 分帧。
- 第一版可以复用 raw Opus 编码，保证 ESP32 端播放契约明确。
- 增加分页响应大小测试，避免再次超过 ESP32 HTTP 客户端 8KB 队列风险。

<verify>

- `uv run pytest tests/test_announcement_audio.py tests/test_announcement_api.py -v`

<done>

- 10 秒以内播报文本可以分多页稳定返回。

## Task 5：错误处理测试

<files>

- `app/main.py`
- `app/tts_providers/doubao.py`
- `tests/test_announcement_api.py`
- `tests/test_doubao_tts_provider.py`

<action>

- 覆盖缺 key、provider 未实现、Doubao 超时、Doubao 错误事件、空音频、未知设备。
- FastAPI 层把 provider 异常转换为明确 HTTP 错误。

<verify>

- `uv run pytest tests/test_announcement_api.py tests/test_doubao_tts_provider.py -v`

<done>

- 失败路径可诊断，不静默返回空 frames。

## Task 6：README 和部署说明

<files>

- `README.md`
- `config/devices.example.yaml`
- `specs/001-feature-doubao-announcement-mode.md`

<action>

- 说明 `zhi_ling` 已移除，HA 侧只保留 `bo_bao`。
- 说明 Doubao API key、model、voice、sample_rate 配置。
- 说明 provider 扩展策略：第一期 Doubao，Bailian 预留。

<verify>

- `rg -n "bo_bao|announcement|doubao|bailian|zhi_ling" README.md specs`

<done>

- 用户能知道如何配置和调用播报模式。

## Task 7：ESP32 companion：新增本地播报入口

<files>

- `C:\Code\xiaozhi-esp32\main\home_assistant_manager.cc`
- `C:\Code\xiaozhi-esp32\main\home_assistant_manager.h`
- `C:\Code\xiaozhi-esp32\main\application.cc`
- `C:\Code\xiaozhi-esp32\main\application.h`
- `C:\Code\xiaozhi-esp32\main\announcement_audio_client.cc`
- `C:\Code\xiaozhi-esp32\main\announcement_audio_client.h`
- `C:\Code\xiaozhi-esp32\tests\test_remote_text_audio_static.py` 或新增测试

<action>

- 新增 `text.<client_id>_bo_bao`。
- 新增 `AnnouncementAudioClient` 调 `/announcement/jobs` 和分页 frames。
- 新增 `Application::PlayRemoteAnnouncement(text)`。
- 本地播放，禁止 `Protocol::SendAudio()`、`SendStartListening()`、`listen/start`。

<verify>

- `python -m pytest tests -q`
- `. C:\Espressif\frameworks\esp-idf-v5.5.4\export.ps1; idf.py build`

<done>

- 固件可编译。
- 静态测试能证明播报模式没有上传到小智云。

## Task 8：联调验证

<files>

- gateway add-on
- ESP32 固件
- HA text entity

<action>

- HA add-on 更新到新版本。
- 配置 Doubao key 和 voice。
- 刷入 ESP32 companion 固件。
- 调用 `text.<client_id>_bo_bao`。

<verify>

- HA 服务调用：

```yaml
action: text.set_value
target:
  entity_id: text.livingroom_xiaozhi_bo_bao
data:
  value: 现在房间温度较高，是否打开空调。
```

- gateway 日志出现 announcement job。
- ESP32 日志出现分页拉取和本地播放。
- 小智云不回复、不执行对话。

<done>

- 用户听到原文播报。

## Task 9：完成前漂移检查

<files>

- `specs/001-req-doubao-announcement-mode.md`
- `specs/001-feature-doubao-announcement-mode.md`
- `specs/001-plan-doubao-announcement-mode.md`
- 全部实现文件和测试文件

<action>

- 对照 REQ-1 到 REQ-10，逐条确认实现和测试。
- 确认没有偷偷实现 Bailian。
- 确认没有把播报音频走小智云。
- 确认配置和 README 只暴露 `announcement` 语义，且不再暴露 `zhi_ling`。

<verify>

- `uv run pytest -q`
- ESP32：`python -m pytest tests -q`
- ESP32：`. C:\Espressif\frameworks\esp-idf-v5.5.4\export.ps1; idf.py build`
- 人工联调记录

<done>

- req/spec/plan/实现/测试一致。

## 分层 Review

| 层 | 检查点 |
|---|---|
| 产品 review | `bo_bao` 语义是否清晰；Doubao 是否第一期足够。 |
| 工程 review | provider 抽象是否过度；API key 是否安全；分页是否复用稳定模式。 |
| UI review | add-on 配置字段是否能看懂；版本号是否可见。 |
| 验证 review | 单测、构建、真实 HA 调用、ESP32 日志是否齐全。 |

## 等待确认

收到用户明确“开始实施”后，才进入编码阶段。
