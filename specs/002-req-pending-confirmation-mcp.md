# 002 需求：小智云 Pending Confirmation MCP

## 背景

001 已经把播报做成本地播放：HA 发文本，gateway 调 TTS，ESP32 本地播放，不经过小智云 LLM。

现在要解决“播报一个问题后，用户回答好的，HA 怎么执行动作”的问题。小智云当前只有一个 MCP 接入点，且这个接入点由 `ha-mcp-for-xiaozhi` 提供，所以新增确认能力不能要求小智云配置第二个 MCP 接入点。

命名说明：001 早期文档用过 `bo_bao` 这类拼音名；当前 ESP32 实现已经使用英文 suffix `announcement`，002 继续使用英文实体名。

## 入口判定

这是中大型功能：

| 原因 | 说明 |
|---|---|
| 跨仓库 | 需要改 `xiaozhi-gateway`、`xiaozhi-esp32`、`ha-mcp-for-xiaozhi`。 |
| 接口契约 | 需要新增 pending confirmation API 和 MCP 工具。 |
| 状态流 | 有 pending、resolved、expired、room mismatch 等状态。 |
| 隐私边界 | 普通播报不能自动开麦，只有询问播报能短时监听。 |
| 安全边界 | gateway 不应直接执行 HA 任意服务调用。 |

## 用户故事

| 编号 | 用户故事 |
|---|---|
| US-1 | 作为 HA 用户，我希望自动化可以让小智音箱询问“是否打开空调”，用户回答“好的”后再执行动作。 |
| US-2 | 作为家庭用户，我希望普通播报只播放声音，不自动打开麦克风。 |
| US-3 | 作为维护者，我希望小智云仍然只配置现有一个 MCP 接入点，不新增第二个 MCP 接入点。 |
| US-4 | 作为维护者，我希望“好的/是的”只在存在有效待确认任务时才被当成确认，不影响小智云自己的追问对话。 |

## 功能需求

| 编号 | 需求 |
|---|---|
| REQ-1 | gateway 必须新增 pending confirmation 状态接口，用于创建、查询和 resolve 一个待确认问题。 |
| REQ-2 | pending confirmation 必须包含 `confirmation_id`、`device_id`、`room_id`、`prompt`、`status`、`expires_at`、`metadata`。 |
| REQ-3 | `ha-mcp-for-xiaozhi` 必须在现有 MCP 接入点内新增 `GetPendingConfirmation` 和 `ResolvePendingConfirmation` 工具，不新增第二个小智云 MCP 接入点。 |
| REQ-4 | `ResolvePendingConfirmation(decision=yes/no)` 必须先查询 gateway；没有有效 pending 时必须返回 `no_pending_confirmation`，不能执行动作。 |
| REQ-5 | 普通播报实体必须使用英文实体名 `text.<client_id>_announcement`，只本地播放，不开麦。 |
| REQ-6 | 询问播报实体必须使用英文实体名 `text.<client_id>_question`，本地播放结束后才打开短监听窗口。 |
| REQ-7 | ESP32 的 question 监听窗口必须有明确超时，默认 8 秒；超时后自动回到 idle。 |
| REQ-8 | gateway 创建 announcement job 时必须知道 `mode=announcement/question`，并把 `listen_after_playback`、`listen_timeout_seconds` 返回给 ESP32。 |
| REQ-9 | HA 动作执行第一版由 HA 自动化负责：MCP resolve 后触发 HA 事件，自动化根据事件决定是否打开空调。gateway 不直接执行 HA 服务。 |
| REQ-10 | 过期、房间不匹配、设备不匹配、重复确认都必须显式返回状态，不能静默成功。 |
| REQ-11 | 所有新增日志不得包含 TTS access key、prompt 全文或用户回答全文；API 只有业务需要时才返回 prompt。 |
| REQ-12 | question job 创建时必须刷新 gateway active-context，使后续小智云 MCP 调用能定位当前设备和房间。 |

## 验收标准

| 编号 | 验收 |
|---|---|
| AC-1 | HA 调 `text.<client_id>_announcement` 播放“晚饭好了”后，ESP32 不进入 listening。 |
| AC-2 | HA 创建 pending confirmation 后，再调 `text.<client_id>_question` 播放“是否打开空调”，ESP32 播放结束后进入短监听窗口。 |
| AC-3 | 用户在监听窗口内说“好的”，小智云通过现有 MCP 接入点调用 `ResolvePendingConfirmation(decision=yes)`。 |
| AC-4 | `ha-mcp-for-xiaozhi` resolve 成功后向 HA 发事件，HA 自动化收到事件后执行打开空调。 |
| AC-5 | 没有 pending confirmation 时，用户对小智云自己的追问回答“是的”，`ResolvePendingConfirmation` 返回 `no_pending_confirmation`，不影响原对话。 |
| AC-6 | pending confirmation 过期后再回答，MCP 工具返回 `expired`，HA 不执行动作。 |
| AC-7 | 所有单元测试、静态测试和 ESP32 构建通过后，才能进入真实联调。 |

## 非目标

| 非目标 | 原因 |
|---|---|
| 不让 gateway 直接调用 HA 服务 | 第一版先把确认链路做稳，避免 gateway 变成动作执行器。 |
| 不新增第二个小智云 MCP 接入点 | 小智云当前只有一个 MCP 接入点，现有入口由 `ha-mcp-for-xiaozhi` 提供。 |
| 不让普通播报自动监听 | 隐私和体验风险太高。 |
| 不做本地 ASR | ESP32 本地识别“好的”不稳定，也会绕开小智云语义能力。 |
| 不做多轮复杂表单 | 第一版只做 yes/no confirmation。 |
| 不支持同一设备多个并发 pending | V1 简化设计，同一设备同时只允许一个 pending。 |

## 界面约束

| 项 | 约束 |
|---|---|
| HA MQTT 实体 | 必须使用英文后缀：`announcement` 和 `question`。 |
| HA add-on 配置页 | 继续使用 `config.yaml` schema，不做自定义 UI。 |
| 小智云 MCP 配置 | 继续使用 `ha-mcp-for-xiaozhi` 当前接入点。 |
| 禁止项 | 禁止把普通播报实体改成自动监听。 |

## 需求追踪

| 需求 | Spec 章节 | 验证方式 |
|---|---|---|
| REQ-1 | Gateway API | gateway API 测试 |
| REQ-2 | 数据模型 | store 单元测试 |
| REQ-3 | MCP 工具 | ha-mcp 工具测试 |
| REQ-4 | Resolve 规则 | no pending / expired 测试 |
| REQ-5 | ESP32 实体 | ESP32 静态测试 |
| REQ-6 | ESP32 实体 | ESP32 静态测试 |
| REQ-7 | ESP32 监听窗口 | ESP32 构建和手工联调 |
| REQ-8 | Announcement job | gateway API 测试 |
| REQ-9 | HA 事件 | ha-mcp 测试和 HA 自动化示例 |
| REQ-10 | 错误状态 | gateway + ha-mcp 测试 |
| REQ-11 | 日志安全 | rg 检查和单测 |
| REQ-12 | active-context 刷新 | gateway API 测试和 ha-mcp 测试 |
