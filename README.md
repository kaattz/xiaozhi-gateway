# xiaozhi-gateway

内网小智前置网关，负责唤醒仲裁和当前房间上下文。

## HAOS Add-on 部署

推荐把 `xiaozhi-gateway` 放在 HAOS `192.168.166.68` 上：

```text
HAOS 192.168.166.68
  ├─ Home Assistant
  └─ xiaozhi-gateway add-on: 8125
```

### GitHub 仓库安装

先把当前代码提交并推送到 GitHub：

```bash
git add .
git commit -m "feat: add xiaozhi gateway haos addon"
git push
```

然后在 Home Assistant 里添加仓库：

```text
设置 -> 加载项 -> 加载项商店 -> 右上角三个点 -> 仓库
```

填入：

```text
https://github.com/kaattz/xiaozhi-gateway
```

刷新加载项商店后安装 `Xiaozhi Gateway`。

### 依赖说明

| 依赖 | 安装位置 |
|---|---|
| `libopus` | `xiaozhi-gateway` add-on 容器内 |
| `opuslib` | `xiaozhi-gateway` Python 环境 |

不要在 HAOS 主系统里装 `libopus`，add-on 容器会自己带运行依赖。

### Add-on 配置

`xiaozhi-gateway` add-on 配置页里填写播报和设备信息：

```yaml
addon_version: "0.1.6"
announcement_enabled: true
announcement_provider: doubao
doubao_app_id: "你的火山语音合成服务 AppID"
doubao_access_key: "你的火山语音合成服务 Access Token"
doubao_resource_id: volc.service_type.10029
doubao_voice: zh_female_xiaohe_uranus_bigtts
doubao_sample_rate: 16000
devices:
  - key: living_room_xiaozhi
    device_id: "你的ESP32_WIFI_MAC"
    client_id: livingroom_xiaozhi
    room_id: living_room
    room_name: 客厅
    ha_area_id: living_room
    ha_device_id: ""
```

保存配置并重启 add-on 后，启动脚本会自动生成 `/config/devices.yaml`。不要再手工改 add-on 配置目录里的 `devices.yaml`，下次重启会被配置页内容覆盖。

如果配置页里看不到 `addon_version: "0.1.6"` 或播报配置，说明 HA 还在用旧 manifest。到加载项商店右上角菜单执行刷新/检查更新后，再安装或重启。

`announcement` 播报模式默认配置：

```yaml
announcement:
  enabled: true
  provider: "doubao"
  frame_format: "opus"
  frame_duration_ms: 60
  doubao:
    app_id: "你的火山语音合成服务 AppID"
    access_key: "你的火山语音合成服务 Access Token"
    resource_id: "volc.service_type.10029"
    voice: "zh_female_xiaohe_uranus_bigtts"
    sample_rate: 16000
```

ESP32 端网关地址配置为：

```text
http://192.168.166.68:8125
```

## Docker 部署

1. 在要运行 Docker 的机器上克隆项目：

```bash
git clone https://github.com/kaattz/xiaozhi-gateway.git
cd xiaozhi-gateway
```

2. 创建并修改设备配置：

```bash
cp config/devices.example.yaml config/devices.yaml
```

```yaml
devices:
  living_room_speaker:
    device_id: "aa:bb:cc:dd:ee:ff"
    client_id: "xiaozhi-living-room"
    room_id: "living_room"
    room_name: "客厅"
```

3. 启动服务：

```bash
docker compose up -d --build
```

4. 检查健康状态：

```bash
curl http://127.0.0.1:8125/health
```

5. ESP32 端网关地址配置为：

```text
http://NAS_IP:8125
```

6. Home Assistant MCP 集成里的 gateway URL 配置为：

```text
http://NAS_IP:8125
```

## 常用接口

| 接口 | 用途 |
|---|---|
| `GET /health` | 健康检查 |
| `GET /devices` | 查看设备和房间配置 |
| `POST /wake-detected` | 设备上报唤醒 |
| `POST /session/end` | 设备结束会话 |
| `GET /active-context` | HA MCP 获取当前房间上下文 |
| `POST /announcement/jobs` | 把播报文本生成本地播放音频任务 |
| `GET /announcement/jobs/{job_id}/frames` | 分页获取播报任务的 base64 Opus 帧 |

## Announcement Audio

这个功能用于播报固定文字。HA 写入 `text.<client_id>_bo_bao` 后，ESP32 从 gateway 拉取音频并本地播放，不上传到小智云，也不让小智云改写内容。

`text.<client_id>_zhi_ling` 入口已移除，避免把文本误当作小智云对话输入。现在 HA 侧只保留播报入口 `text.<client_id>_bo_bao`。

调用示例：

```yaml
action: text.set_value
target:
  entity_id: text.livingroom_xiaozhi_bo_bao
data:
  value: 现在房间温度较高，是否打开空调。
```

`doubao` provider 使用火山 TTS2 V3 双向流式 WebSocket 正式接口。`doubao_voice` 填音色列表里的 voice_type，例如 `zh_female_xiaohe_uranus_bigtts`；如果要试 S2S-Omni 小何，可填 `zh_female_xiaohe_jupiter_bigtts`。`bailian`、`piper` 名称预留，不做自动降级。
