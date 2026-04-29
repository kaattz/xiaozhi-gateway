# xiaozhi-gateway

内网小智前置网关，负责唤醒仲裁和当前房间上下文。

## HAOS Add-on 部署

推荐把 `xiaozhi-gateway` 和 Piper 都放在 HAOS `192.168.166.68` 上：

```text
HAOS 192.168.166.68
  ├─ Home Assistant
  ├─ Piper add-on: core-piper:10200
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
| Piper | 官方 Piper add-on |
| `ffmpeg` | `xiaozhi-gateway` add-on 容器内 |
| `libopus` | `xiaozhi-gateway` add-on 容器内 |
| `opuslib` | `xiaozhi-gateway` Python 环境 |

不要在 HAOS 主系统里装 `ffmpeg/libopus`。

### Add-on 配置

`xiaozhi-gateway` add-on 配置页里填写 Piper 和设备信息：

```yaml
piper_host: core-piper
piper_port: 10200
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

`remote_text` 默认配置：

```yaml
remote_text:
  provider: "wyoming"
  wyoming_host: "core-piper"
  wyoming_port: 10200
  ffmpeg_binary: "ffmpeg"
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
| `POST /remote-text/jobs` | 把文字生成 Opus 音频任务 |
| `GET /remote-text/jobs/{job_id}/frames` | 获取任务的 base64 Opus 帧 |

## Remote Text Audio

这个功能用于把 Home Assistant 发来的文字转成音频，让 ESP32 再按“麦克风音频”上传给小智官方云。

运行依赖：

| 依赖 | 用途 |
|---|---|
| Piper add-on | 通过 Wyoming 协议生成语音 |
| `ffmpeg` | 转成 16 kHz mono s16le PCM |
| `libopus` / `opuslib` | 编码 raw Opus 帧 |

配置写在 `config/devices.yaml`：

```yaml
remote_text:
  provider: "wyoming"
  wyoming_host: "core-piper"
  wyoming_port: 10200
  ffmpeg_binary: "ffmpeg"
```

接口示例：

```bash
curl -X POST http://127.0.0.1:8125/remote-text/jobs \
  -H "Content-Type: application/json" \
  -d '{"device_id":"aa:bb:cc:dd:ee:ff","text":"现在房间温度比较高"}'
```

不要把这个服务暴露到公网。
