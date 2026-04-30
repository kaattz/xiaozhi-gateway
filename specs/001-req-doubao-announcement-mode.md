# 001 需求：多 TTS Provider 播报模式

## 背景

之前的远程文本链路会把 Home Assistant 的文字转成音频，再由 ESP32 当作麦克风输入发给小智官方云。这个链路会经过云端 ASR/LLM/TTS，所以小智可能改写、解释或自我发挥。

新需求是增加“播报模式”：Home Assistant 发一段文字，设备尽量按原文朗读，不进入小智云 LLM。

## 入口判定

这是中大型功能：

| 原因 | 说明 |
|---|---|
| 外部输入输出 | 新增豆包 TTS 2.0 外部 API 调用 |
| 接口契约 | 新增播报 job / frames API |
| 跨模块 | gateway 生成音频，ESP32 本地播放 |
| 配置和密钥 | add-on 配置需要保存 provider、voice、API key 等 |
| 长期扩展 | 后续要支持 Bailian 等 TTS provider |

## 用户故事

| 编号 | 用户故事 |
|---|---|
| US-1 | 作为 HA 用户，我希望给小智设备发送播报文本，设备按原文朗读，不让小智云自由发挥。 |
| US-2 | 作为部署者，我希望在 `xiaozhi-gateway` add-on 配置页选择 TTS provider 和音色。 |
| US-3 | 作为维护者，我希望 Doubao、Bailian、Piper 等 TTS 能通过统一 provider 接口接入，避免每加一个 provider 就改主流程。 |

## 功能需求

| 编号 | 需求 |
|---|---|
| REQ-1 | 新增独立的 `announcement` 播报模式，不复用旧的小智云输入语义。 |
| REQ-2 | gateway 必须提供统一 TTS provider 抽象，第一期实现 `doubao`，预留 `bailian`、`piper` provider 名称但不实现。 |
| REQ-3 | Doubao provider 必须在 gateway 侧调用，API key 不得下发到 ESP32。 |
| REQ-4 | Doubao provider 第一版输出统一转成 `16 kHz mono s16le PCM`，再按既有分页模式交付给 ESP32。 |
| REQ-5 | gateway 必须提供播报 job 创建接口和分页取帧接口，响应体大小必须适配 ESP32 当前 HTTP 客户端，不允许单次返回大音频。 |
| REQ-6 | HA 侧只暴露播报文本实体，例如 `text.<client_id>_bo_bao`，不再暴露 `text.<client_id>_zhi_ling`。 |
| REQ-7 | ESP32 播报模式必须本地播放音频，不调用 `Protocol::SendAudio()`，不把播报音频上传到小智云。 |
| REQ-8 | 失败必须显式报错：provider 未配置、鉴权失败、TTS 超时、音频格式不支持、分页 job 过期都不能静默降级。 |
| REQ-9 | 配置页必须显示当前 add-on 版本和 announcement 配置，方便判断 HA 是否刷新到新 manifest。 |
| REQ-10 | 第一版不做流式边播边下发，先做 job 生成后分页拉取；只有分页稳定后再评估流式。 |

## 验收标准

| 编号 | 验收 |
|---|---|
| AC-1 | HA 调用播报实体后，gateway 创建 announcement job，ESP32 本地播放，不出现小智云理解/回复。 |
| AC-2 | 使用 Doubao provider 时，gateway 日志能显示 provider、voice、音频时长/帧数，但不能打印 API key。 |
| AC-3 | 播报短句和 10 秒以内文本时，ESP32 分页拉取成功，不触发 HTTP 8KB 队列卡死问题。 |
| AC-4 | 未配置 Doubao API key 时，接口返回明确错误，ESP32 日志显示播报失败原因。 |
| AC-5 | gateway 的 `/remote-text` API 已移除，ESP32 HA Discovery 不再发布 `zhi_ling` 文本实体。 |

## 非目标

| 非目标 | 原因 |
|---|---|
| 不在第一期实现 Bailian provider | 先把 provider 抽象和 Doubao 链路跑通。 |
| 不让 ESP32 直连 Doubao/Bailian | 密钥安全和协议复杂度都应留在 gateway。 |
| 不复用小智云 TTS 播报 | 复用小智云会重新引入 LLM 改写问题。 |
| 不做跨公网暴露 | gateway 仍然是内网服务。 |
| 不做语义问答 | 播报模式只朗读文本，不执行动作，不理解问题。 |

## 界面约束

| 项 | 约束 |
|---|---|
| HA add-on 配置页 | 使用 `config.yaml` options/schema 暴露配置，不做自定义 UI。 |
| HA MQTT 实体 | 只保留 `bo_bao` 播报 text 实体，不再发布 `zhi_ling`。 |
| 禁止项 | 不再使用旧的远程文本配置字段承载播报配置。 |

## 需求追踪

| 需求 | Spec 章节 | 验证方式 |
|---|---|---|
| REQ-1 | 架构、接口 | API 测试、ESP32 静态测试 |
| REQ-2 | Provider 抽象 | 单元测试 |
| REQ-3 | 配置和密钥 | 配置测试、日志检查 |
| REQ-4 | 音频格式 | 音频单元测试 |
| REQ-5 | API 分页 | API 测试 |
| REQ-6 | HA 实体 | ESP32 静态测试 |
| REQ-7 | 本地播放 | ESP32 构建和日志验证 |
| REQ-8 | 错误处理 | API 错误测试 |
| REQ-9 | Add-on 配置 | add-on 静态测试 |
| REQ-10 | 非流式边界 | plan drift check |
