# xiaozhi-gateway

内网小智前置网关，负责唤醒仲裁和当前房间上下文。

## Docker 部署

1. 创建并修改设备配置：

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

2. 启动服务：

```bash
docker compose up -d --build
```

3. 检查健康状态：

```bash
curl http://127.0.0.1:8125/health
```

4. ESP32 端网关地址配置为：

```text
http://NAS_IP:8125
```

5. Home Assistant MCP 集成里的 gateway URL 配置为：

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
