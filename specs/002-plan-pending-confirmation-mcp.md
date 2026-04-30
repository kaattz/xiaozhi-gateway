# 002 实施计划：Pending Confirmation MCP

## 执行规则

| 规则 | 要求 |
|---|---|
| 先确认 | 未经用户明确说“开始实施”，不得写功能代码。 |
| 不提交 | 提交、推送、刷机前必须单独确认。 |
| 不新 worktree | 不私自创建新 worktree。 |
| 不改普通播报隐私边界 | `text.<client_id>_announcement` 绝不能自动开麦。 |
| 不新增第二 MCP 接入点 | 只扩展 `ha-mcp-for-xiaozhi` 当前 MCP server。 |
| 不猜上下文 | `ResolvePendingConfirmation` 拿不到 active-context 时不得 resolve 全局 pending。 |

## Task 0：实施前检查

<files>

- `specs/002-req-pending-confirmation-mcp.md`
- `specs/002-spec-pending-confirmation-mcp.md`
- `C:\Code\xiaozhi-gateway\app\main.py`
- `C:\Code\xiaozhi-gateway\app\models.py`
- `C:\Code\xiaozhi-gateway\app\audio_jobs.py`
- `C:\Code\xiaozhi-esp32\main\home_assistant_manager.cc`
- `C:\Code\xiaozhi-esp32\main\application.cc`
- `C:\Code\xiaozhi-esp32\main\announcement_audio_client.cc`
- `C:\Code\ha-mcp-for-xiaozhi\custom_components\ws_mcp_server\server.py`
- `C:\Code\ha-mcp-for-xiaozhi\custom_components\ws_mcp_server\gateway_context.py`

<action>

- 逐条读取 req/spec。
- 确认 001 播报链路仍然可用。
- 确认当前小智云 MCP 入口在 `ha-mcp-for-xiaozhi`。
- 确认普通播报和询问播报的英文实体名。

<verify>

- `git -C C:\Code\xiaozhi-gateway status -sb`
- `git -C C:\Code\xiaozhi-esp32 status -sb`
- `git -C C:\Code\ha-mcp-for-xiaozhi status -sb`
- `rg -n "announcement|question|pending|ResolvePendingConfirmation|GetPendingConfirmation" C:\Code\xiaozhi-gateway C:\Code\xiaozhi-esp32\main C:\Code\ha-mcp-for-xiaozhi\custom_components`

<done>

- 明确三个仓库的文件边界。
- 没有覆盖用户未提交修改。

## Task 1：gateway pending confirmation store

<files>

- Create: `C:\Code\xiaozhi-gateway\app\pending_confirmations.py`
- Modify: `C:\Code\xiaozhi-gateway\app\models.py`
- Test: `C:\Code\xiaozhi-gateway\tests\test_pending_confirmations.py`

<action>

- 新增 `PendingConfirmation` 数据结构。
- 新增内存 TTL store：create、get_active、resolve、expire cleanup。
- 同一 `device_id` 同时只允许一个 pending。
- 支持状态：`pending`、`confirmed`、`rejected`、`expired`、`cancelled`。

<verify>

- `cd C:\Code\xiaozhi-gateway; uv run pytest tests/test_pending_confirmations.py -v`

<done>

- store 单测覆盖 create/query/resolve/expired/duplicate/device mismatch/room mismatch。

## Task 2：gateway pending confirmation API

<files>

- Modify: `C:\Code\xiaozhi-gateway\app\main.py`
- Modify: `C:\Code\xiaozhi-gateway\app\models.py`
- Test: `C:\Code\xiaozhi-gateway\tests\test_pending_confirmation_api.py`

<action>

- 新增 `POST /pending-confirmations`。
- 新增 `GET /pending-confirmations/active`。
- 新增 `POST /pending-confirmations/{confirmation_id}/resolve`。
- 错误状态按 spec 返回，不做兜底成功。

<verify>

- `cd C:\Code\xiaozhi-gateway; uv run pytest tests/test_pending_confirmation_api.py -v`

<done>

- gateway 可创建、查询、resolve pending confirmation。

## Task 3：gateway announcement mode 扩展

<files>

- Modify: `C:\Code\xiaozhi-gateway\app\models.py`
- Modify: `C:\Code\xiaozhi-gateway\app\main.py`
- Test: `C:\Code\xiaozhi-gateway\tests\test_announcement_api.py`

<action>

- `AnnouncementJobRequest` 增加 `mode`，默认 `announcement`。
- `AnnouncementJobCreated` 增加 `listen_after_playback` 和 `listen_timeout_seconds`。
- `mode=announcement` 返回 `listen_after_playback=false`。
- `mode=question` 返回 `listen_after_playback=true`、默认 8 秒。
- `mode=question` 创建 job 时刷新该 `device_id` 的 active-context，TTL 覆盖监听窗口。
- `mode=question` 仍复用 `load_devices()` 校验设备，HA automation 的 `device_id` 必须与 `devices.yaml` 一致。
- 日志只记录 `job_id`、`device_id`、`mode`、frame 数，不记录 prompt 全文。

<verify>

- `cd C:\Code\xiaozhi-gateway; uv run pytest tests/test_announcement_api.py -v`

<done>

- gateway 能明确告诉 ESP32 是否需要播放后监听。

## Task 4：ESP32 两个英文 text 实体和 question 监听

<files>

- Modify: `C:\Code\xiaozhi-esp32\main\home_assistant_manager.cc`
- Modify: `C:\Code\xiaozhi-esp32\main\home_assistant_manager.h`
- Modify: `C:\Code\xiaozhi-esp32\main\application.cc`
- Modify: `C:\Code\xiaozhi-esp32\main\application.h`
- Modify: `C:\Code\xiaozhi-esp32\main\announcement_audio_client.cc`
- Modify: `C:\Code\xiaozhi-esp32\main\announcement_audio_client.h`
- Test: `C:\Code\xiaozhi-esp32\tests\test_announcement_audio_static.py`

<action>

- 把普通播报实体命名为 `Announcement` / suffix `announcement`，目标 entity_id 为 `text.<client_id>_announcement`。
- 新增询问实体 `Question` / suffix `question`，目标 entity_id 为 `text.<client_id>_question`。
- announcement 实体回调调用 `Application::PlayRemoteAnnouncement(text, kAnnouncementModeAnnouncement)`。
- question 实体回调调用 `Application::PlayRemoteAnnouncement(text, kAnnouncementModeQuestion)`。
- `AnnouncementAudioClient::FetchFrames` 增加 mode 参数，并解析 response 的监听字段。
- `Application::PlayRemoteAnnouncement` 增加播放后监听参数。
- 先分析 `PlayRemoteAnnouncement` 播放完成后进入 listening 的状态转换路径，确认 `OpenAudioChannel()`、`SetListeningMode()`、`CloseAudioChannel()` 可复用。
- 只有 question 且 `listen_after_playback=true` 时才打开短监听窗口。
- question 播放完成后进入 `kListeningModeAutoStop`，并设置本地 8 秒超时关闭 audio channel。
- announcement 播放完必须直接 idle。

<verify>

- `cd C:\Code\xiaozhi-esp32; python -m pytest tests/test_announcement_audio_static.py -v`
- `cd C:\Code\xiaozhi-esp32; . C:\Espressif\frameworks\esp-idf-v5.5.4\export.ps1; idf.py build`

<done>

- 静态测试证明普通播报不触发监听。
- 固件编译通过。

## Task 5：ha-mcp-for-xiaozhi pending tools

<files>

- Modify: `C:\Code\ha-mcp-for-xiaozhi\custom_components\ws_mcp_server\server.py`
- Modify: `C:\Code\ha-mcp-for-xiaozhi\custom_components\ws_mcp_server\gateway_context.py`
- Create: `C:\Code\ha-mcp-for-xiaozhi\custom_components\ws_mcp_server\pending_confirmation.py`
- Test: `C:\Code\ha-mcp-for-xiaozhi\tests\test_pending_confirmation_tools.py`

<action>

- 在现有 `list_tools()` 返回值里追加 `GetPendingConfirmation` 和 `ResolvePendingConfirmation`。
- 在现有 `call_tool()` 里先拦截这两个工具名。
- `GetPendingConfirmation` 查询 gateway active pending。
- `ResolvePendingConfirmation` 使用 active context 查询 pending；没有 pending 返回 `no_pending_confirmation`。
- `ResolvePendingConfirmation` 如果 active-context 不可用，返回 `active_context_unavailable`，不 resolve 全局 pending。
- resolve 成功后用 `hass.bus.async_fire("xiaozhi_gateway_pending_confirmation_resolved", payload)` 发 HA 事件。
- 将现有 `_LOGGER.error("mcp list tools...")` 和 `_LOGGER.error("Tool call...")` 调试日志降为 debug，避免生产环境打印完整工具参数。

<verify>

- `cd C:\Code\ha-mcp-for-xiaozhi; pytest tests/test_pending_confirmation_tools.py tests/test_gateway_context.py -v`

<done>

- 小智云只需要现有 MCP 接入点，就能看到 pending confirmation 工具。

## Task 6：README 和 HA 自动化示例

<files>

- Modify: `C:\Code\xiaozhi-gateway\README.md`
- Modify: `C:\Code\ha-mcp-for-xiaozhi\README.md` if exists
- Modify: `C:\Code\xiaozhi-esp32\README_zh.md`

<action>

- 说明两个实体：
  - `text.<client_id>_announcement`
  - `text.<client_id>_question`
- 说明普通播报不会开麦。
- 说明 pending confirmation 的 HA 自动化示例。
- 说明小智云只配置 `ha-mcp-for-xiaozhi` 一个 MCP 接入点。

<verify>

- `rg -n "text\\.<client_id>_announcement|text\\.<client_id>_question|ResolvePendingConfirmation|pending confirmation" C:\Code\xiaozhi-gateway C:\Code\xiaozhi-esp32 C:\Code\ha-mcp-for-xiaozhi`

<done>

- 用户能按文档配置和测试。

## Task 7：完成前漂移检查

<files>

- `specs/002-req-pending-confirmation-mcp.md`
- `specs/002-spec-pending-confirmation-mcp.md`
- `specs/002-plan-pending-confirmation-mcp.md`
- 三个仓库的本次改动文件

<action>

- 对照 REQ-1 到 REQ-12，逐条核对实现。
- 确认没有让普通播报开麦。
- 确认没有新增第二个 MCP 接入点。
- 确认 gateway 没有直接执行 HA 服务。
- 确认没有新增未写进 spec 的行为。
- 确认日志不打印 access key、prompt 全文、用户回答全文。

<verify>

- `cd C:\Code\xiaozhi-gateway; uv run pytest -q`
- `cd C:\Code\xiaozhi-esp32; python -m pytest tests -q`
- `cd C:\Code\xiaozhi-esp32; . C:\Espressif\frameworks\esp-idf-v5.5.4\export.ps1; idf.py build`
- `cd C:\Code\ha-mcp-for-xiaozhi; pytest -q`
- `rg -n "access_key|access_token|api_key|Tool call:|mcp list tools" C:\Code\xiaozhi-gateway\app C:\Code\ha-mcp-for-xiaozhi\custom_components`
- `rg -n -g "002-*.md" "text\\.<client_id>_(bo_bao|xun_wen|zhi_ling)" C:\Code\xiaozhi-gateway\specs`

<done>

- req/spec/plan/实现/测试一致。

## 分层 Review

| 层 | 检查点 |
|---|---|
| 产品 review | 两个英文 text 实体是否清楚；普通播报是否保持隐私边界。 |
| 工程 review | pending store、API、MCP tools 是否职责清晰。 |
| 安全 review | gateway 是否没有执行 HA 任意服务；日志是否不泄露密钥。 |
| 验证 review | gateway、ESP32、ha-mcp 三边测试是否覆盖主链路和失败链路。 |

## 等待确认

收到用户明确“开始实施”后，才进入编码阶段。
