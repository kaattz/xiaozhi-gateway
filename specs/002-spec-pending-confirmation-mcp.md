# 002 Spec：Pending Confirmation MCP

## 目标

建立一条“HA 发起询问 -> 小智设备播报并短时监听 -> 小智云理解用户回答 -> 现有 MCP 工具 resolve -> HA 自动化执行动作”的链路。

核心原则：

| 原则 | 说明 |
|---|---|
| 一个 MCP 接入点 | 只扩展 `ha-mcp-for-xiaozhi`，不让小智云接第二个 gateway MCP。 |
| 两种播报入口 | `announcement` 只播报；`question` 播报后短时监听。 |
| 动作留在 HA | gateway 只保存待确认状态，不直接执行 HA 服务。 |
| 无 pending 不确认 | 用户说“好的”只有在有效 pending 存在时才 resolve。 |

命名说明：001 早期文档用过 `bo_bao` 这类拼音实体名；当前 ESP32 代码已经使用英文 suffix `announcement`，002 统一使用 `announcement` 和 `question`。

## 代码证据

| 仓库/文件 | 证据 |
|---|---|
| `xiaozhi-gateway/app/main.py` | 已有 `/announcement/jobs` 和 `/announcement/jobs/{job_id}/frames`，可扩展 request/response 加 mode 和 listen 信息。 |
| `xiaozhi-gateway/app/audio_jobs.py` | 已有 TTL 内存 job store，可参考实现 pending confirmation store。 |
| `xiaozhi-gateway/app/models.py` | 已有 `AnnouncementJobRequest`，当前只有 `device_id/client_id/text`。 |
| `xiaozhi-esp32/main/home_assistant_manager.cc` | 当前只有一个播报 text 实体，callback 调 `PlayRemoteAnnouncement(text)`。 |
| `xiaozhi-esp32/main/application.cc` | `PlayRemoteAnnouncement` 已经本地播放，并在播放完成后回到 idle。 |
| `xiaozhi-esp32/main/announcement_audio_client.cc` | 创建 job 时可增加 `mode` 字段，解析 response 时可读取监听参数。 |
| `ha-mcp-for-xiaozhi/custom_components/ws_mcp_server/server.py` | 现有 MCP server 只转发 HA LLM tools，可在 list/call tool 中合并自定义 pending tools。 |
| `ha-mcp-for-xiaozhi/custom_components/ws_mcp_server/gateway_context.py` | 已有 gateway URL、active context 查询和 room 注入逻辑，可复用 gateway URL。 |

## 总体流程

```text
HA automation
  -> POST gateway /pending-confirmations
  -> text.set_value text.<client_id>_question
  -> ESP32 POST /announcement/jobs mode=question
  -> gateway refreshes active-context for this device
  -> gateway returns listen_after_playback=true
  -> ESP32 local playback
  -> ESP32 opens short listening window
  -> user says "好的"
  -> Xiaozhi cloud calls existing MCP endpoint
  -> ha-mcp-for-xiaozhi ResolvePendingConfirmation(decision=yes)
  -> ha-mcp-for-xiaozhi calls gateway resolve API
  -> ha-mcp-for-xiaozhi fires HA event
  -> HA automation receives event and opens AC
```

普通播报流程：

```text
text.<client_id>_announcement
  -> ESP32 POST /announcement/jobs mode=announcement
  -> local playback
  -> idle
```

## 数据模型

### PendingConfirmation

```json
{
  "confirmation_id": "uuid",
  "device_id": "fc:01:2c:d2:5d:94",
  "client_id": "livingroom_xiaozhi",
  "room_id": "living_room",
  "prompt": "现在房间温度比较高，是否打开空调？",
  "status": "pending",
  "expires_at": 1777440000.0,
  "metadata": {
    "automation": "living_room_hot_ask_ac",
    "entity_id": "climate.living_room_ac"
  }
}
```

### 状态

| status | 含义 |
|---|---|
| `pending` | 等待用户确认。 |
| `confirmed` | 用户同意。 |
| `rejected` | 用户拒绝。 |
| `expired` | 超时未确认。 |
| `cancelled` | HA 或系统主动取消。 |

### decision

| decision | 含义 |
|---|---|
| `yes` | 同意。 |
| `no` | 拒绝。 |

第一版只支持 yes/no。不要把“打开空调”这类具体动作文本塞进 decision，具体动作由 HA 自动化根据 `confirmation_id` 或 `metadata` 处理。

## Gateway API

### `POST /pending-confirmations`

创建一个待确认任务。

Request:

```json
{
  "device_id": "fc:01:2c:d2:5d:94",
  "client_id": "livingroom_xiaozhi",
  "room_id": "living_room",
  "prompt": "现在房间温度比较高，是否打开空调？",
  "ttl_seconds": 30,
  "metadata": {
    "automation": "living_room_hot_ask_ac",
    "entity_id": "climate.living_room_ac"
  }
}
```

Response:

```json
{
  "confirmation_id": "uuid",
  "status": "pending",
  "expires_at": 1777440000.0
}
```

规则：

| 规则 | 行为 |
|---|---|
| 同一 `device_id` 已有 pending | 返回 `409 pending confirmation already exists`。 |
| 未知设备 | 返回 `404 device not found`。 |
| prompt 为空或过长 | 返回 `422`。 |
| ttl 超出范围 | 返回 `422`，允许范围 5 到 120 秒。 |
| `client_id` 缺失 | 从 `devices.yaml` 按 `device_id` 自动填充；如果找不到设备则返回 `404 device not found`。 |

### `GET /pending-confirmations/active`

查询当前设备或房间是否有有效 pending。

Query:

```text
device_id=fc:01:2c:d2:5d:94&room_id=living_room
```

Response when active:

```json
{
  "active": true,
  "confirmation_id": "uuid",
  "device_id": "fc:01:2c:d2:5d:94",
  "client_id": "livingroom_xiaozhi",
  "room_id": "living_room",
  "prompt": "现在房间温度比较高，是否打开空调？",
  "expires_at": 1777440000.0,
  "metadata": {}
}
```

Response when none:

```json
{
  "active": false,
  "status": "no_pending_confirmation"
}
```

### `POST /pending-confirmations/{confirmation_id}/resolve`

Request:

```json
{
  "decision": "yes",
  "device_id": "fc:01:2c:d2:5d:94",
  "room_id": "living_room",
  "source": "xiaozhi_mcp"
}
```

Response:

```json
{
  "confirmation_id": "uuid",
  "status": "confirmed",
  "decision": "yes",
  "metadata": {}
}
```

错误/边界：

| 场景 | 返回 |
|---|---|
| 不存在 | `404 no_pending_confirmation` |
| 已过期 | `409 expired` |
| 已 resolved | `409 already_resolved` |
| 设备不匹配 | `409 device_mismatch` |
| 房间不匹配 | `409 room_mismatch` |

## Announcement API 扩展

`POST /announcement/jobs` 增加 mode。

Request:

```json
{
  "device_id": "fc:01:2c:d2:5d:94",
  "client_id": "livingroom_xiaozhi",
  "text": "现在房间温度比较高，是否打开空调？",
  "mode": "question"
}
```

Response 增加：

```json
{
  "listen_after_playback": true,
  "listen_timeout_seconds": 8
}
```

规则：

| mode | listen_after_playback | 说明 |
|---|---:|---|
| `announcement` | false | 普通播报，不开麦。 |
| `question` | true | 播放完成后短时监听。 |

`mode=question` 的额外规则：

| 规则 | 行为 |
|---|---|
| 设备校验 | 复用 `load_devices()`，`device_id` 必须和 gateway `devices.yaml` 一致。 |
| active-context | 创建 question job 时刷新 `/active-context` 对应的设备和房间，TTL 必须覆盖监听窗口，默认复用现有 120 秒。 |
| 无 pending | 仍允许生成 question 音频，但后续 `ResolvePendingConfirmation` 必须返回 `no_pending_confirmation`。 |
| 日志 | 只记录 `mode`、`device_id`、`job_id`、frame 数，不记录 prompt 全文。 |

## ESP32 契约

| 模块 | 变更 |
|---|---|
| `HomeAssistantManager` | 发布两个 text 实体：`Announcement` 和 `Question`。 |
| `AnnouncementAudioClient` | `FetchFrames(text, mode)`，请求里带 `mode`，响应里解析监听参数。 |
| `Application` | `PlayRemoteAnnouncement(text, mode)`，只有 `mode=question` 且 response 允许时才监听。 |

### ESP32 状态转换

question 不能简单在本地播放后直接 `SetDeviceState(kDeviceStateIdle)`。播放后必须走现有小智云监听链路：

| 阶段 | 行为 |
|---|---|
| 拉取音频 | `AnnouncementAudioClient::FetchFrames(text, mode)` 获取 frames 和监听参数。 |
| 本地播放 | `SetDeviceState(kDeviceStateSpeaking)`，推送本地播放 frames。 |
| 播放完成 | `WaitForPlaybackQueueEmpty()` 后检查 `listen_after_playback`。 |
| 普通播报 | `mode=announcement` 直接回 idle。 |
| 询问播报 | `mode=question` 打开 `protocol_->OpenAudioChannel()`，再进入 `SetListeningMode(kListeningModeAutoStop)`。 |
| 本地超时 | 启动本地 8 秒超时；到期仍在 listening 时关闭 audio channel 并回 idle。 |

实施前必须先确认 `OpenAudioChannel()`、`SetListeningMode()`、`CloseAudioChannel()` 在该路径下不会和正在播放的本地音频抢状态。

HA 实体名：

| 目的 | entity_id |
|---|---|
| 普通播报 | `text.<client_id>_announcement` |
| 询问播报 | `text.<client_id>_question` |

监听行为：

| 场景 | 行为 |
|---|---|
| announcement 播放完成 | 直接回 idle。 |
| question 播放完成 | 进入 listening，最长 8 秒。 |
| 用户无回答 | 超时关闭音频通道，回 idle。 |
| 用户回答 | 由小智云正常 ASR/LLM 判断，并调用 MCP。 |

## ha-mcp-for-xiaozhi 契约

新增两个自定义 MCP 工具，并和 HA 原有 LLM tools 一起出现在同一个 MCP 接入点。

### `GetPendingConfirmation`

用途：让小智云判断当前是否有 HA 发起的待确认问题。

Input:

```json
{
  "device_id": "fc:01:2c:d2:5d:94",
  "room_id": "living_room"
}
```

Output:

```json
{
  "active": true,
  "confirmation_id": "uuid",
  "prompt": "现在房间温度比较高，是否打开空调？",
  "room_id": "living_room"
}
```

### `ResolvePendingConfirmation`

用途：用户回答“好的/不用”后，resolve 当前 pending。

Input:

```json
{
  "decision": "yes"
}
```

工具内部规则：

| 步骤 | 说明 |
|---|---|
| 1 | 从 gateway `/active-context` 获取当前设备和房间。 |
| 2 | 查 gateway `/pending-confirmations/active`。 |
| 3 | 没有 pending 时返回 `no_pending_confirmation`。 |
| 4 | 有 pending 时调用 resolve API。 |
| 5 | resolve 成功后在 HA 内发事件 `xiaozhi_gateway_pending_confirmation_resolved`。 |

如果 `/active-context` 不可用，`ResolvePendingConfirmation` 必须返回 `active_context_unavailable`，不能为了“猜中”去 resolve 全局 pending。question job 创建时已经负责刷新 active-context，因此这里拿不到上下文就是链路异常。

HA 事件 payload：

```json
{
  "confirmation_id": "uuid",
  "decision": "yes",
  "status": "confirmed",
  "device_id": "fc:01:2c:d2:5d:94",
  "room_id": "living_room",
  "metadata": {}
}
```

## HA 自动化示例

第一版推荐 HA 自动化自己执行动作。

```yaml
alias: Ask AC confirmation when living room is hot
sequence:
  - action: rest_command.xiaozhi_create_pending_confirmation
    data:
      device_id: "fc:01:2c:d2:5d:94"
      room_id: living_room
      prompt: "现在房间温度比较高，是否打开空调？"
      ttl_seconds: 30
      metadata:
        automation: living_room_hot_ask_ac
        entity_id: climate.living_room_ac
    response_variable: pending_confirmation
  - action: text.set_value
    target:
      entity_id: text.livingroom_xiaozhi_question
    data:
      value: "现在房间温度比较高，是否打开空调？"
  - wait_for_trigger:
      - trigger: event
        event_type: xiaozhi_gateway_pending_confirmation_resolved
    timeout:
      seconds: 35
    continue_on_timeout: true
  - condition: template
    value_template: >
      {{ wait.trigger is not none
         and wait.trigger.event.data.confirmation_id == pending_confirmation.content.confirmation_id
         and wait.trigger.event.data.decision == 'yes' }}
  - action: climate.set_hvac_mode
    target:
      entity_id: climate.living_room_ac
    data:
      hvac_mode: cool
```

## 错误处理

| 层 | 错误 | 行为 |
|---|---|---|
| gateway | pending 已存在 | 409，不覆盖旧 pending。 |
| gateway | pending 过期 | 查询时返回 inactive，resolve 时返回 expired。 |
| gateway | unknown device | 404。 |
| gateway | question job unknown device | 404，HA automation 的 `device_id` 必须和 `devices.yaml` 一致。 |
| ESP32 | question audio 拉取失败 | 不开麦，记录错误。 |
| ESP32 | 监听超时 | 关闭音频通道，回 idle。 |
| ha-mcp | gateway 不可达 | MCP 工具返回明确错误，不调用 HA 动作。 |
| ha-mcp | no pending | 返回 no_pending_confirmation。 |
| ha-mcp | active-context 不可用 | 返回 active_context_unavailable。 |
| 日志 | 敏感字段 | 不记录 access key、prompt 全文、用户回答全文；只记录 id、状态、mode。 |

## 验证策略

| 层 | 验证 |
|---|---|
| gateway unit | pending store create/query/resolve/expire。 |
| gateway API | pending API、announcement mode response。 |
| ESP32 static | `announcement` 不触发监听，`question` 才能触发监听。 |
| ESP32 build | `idf.py build`。 |
| ha-mcp unit | tools list 包含两个 pending tools；resolve no pending 不执行事件；resolve yes 发 HA event。 |
| 手工联调 | 普通播报不亮麦；询问播报后 8 秒内回答“好的”能触发 HA 自动化。 |

## 需求追踪

| 需求 | Spec 章节 | 实施任务 | 验证 |
|---|---|---|---|
| REQ-1 | Gateway API | Task 2 | gateway API 测试 |
| REQ-2 | 数据模型 | Task 1/2 | store 测试 |
| REQ-3 | ha-mcp 契约 | Task 5 | ha-mcp 测试 |
| REQ-4 | ha-mcp 契约 | Task 5 | no pending 测试 |
| REQ-5 | ESP32 契约 | Task 4 | ESP32 静态测试 |
| REQ-6 | ESP32 契约 | Task 4 | ESP32 静态测试 |
| REQ-7 | ESP32 契约 | Task 4 | build + 联调 |
| REQ-8 | Announcement API | Task 3 | gateway API 测试 |
| REQ-9 | HA 自动化示例 | Task 5/6 | event 测试 |
| REQ-10 | 错误处理 | Task 2/5 | 错误测试 |
| REQ-11 | 错误处理 | Task 7 | rg + review |
| REQ-12 | Announcement API、ha-mcp 契约 | Task 3/5 | API + ha-mcp 测试 |
