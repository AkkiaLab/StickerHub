# StickerHub

StickerHub 是一个在不同 IM 平台之间转换表情素材（Sticker/Image/GIF/Video）的工具。

当前阶段实现：**Telegram -> 飞书**，并提供 **Telegram/飞书双端身份绑定**（`/bind`）。

## 功能范围

- 监听 Telegram Bot 收到的单个素材：Sticker、图片、GIF、视频
- 自动转换并发送到飞书机器人目标用户：
  - 视频/动图优先转 GIF
  - Telegram `TGS` 动态贴纸转 GIF
  - WebP 静态图转 PNG
  - 上传图片后发送飞书 `image` 消息
- 双端注册绑定机制：
  - 任意一端发送 `/bind`，生成魔法字符串并绑定当前平台身份
  - 在另一端发送 `/bind <魔法字符串>`，完成跨平台绑定
- 友好提示：
  - Telegram 支持 `/start`、`/help` 查看使用说明
  - 发送不支持的命令或消息类型时，机器人会返回使用说明
- Sticker 包整包发送交互：
  - 用户发送单个 Telegram 贴纸后，先立即发送该贴纸到飞书
  - 机器人在 Telegram 通过按钮提示是否发送整个表情包（展示数量）
  - 用户确认后按每批 10 个并发发送；每批在飞书插入文本分隔符，同时更新 Telegram 进度
  - 发送过程中可点击“停止发送”按钮，任务会在当前批次结束后停止
- 飞书事件接收方式：**长连接（Long Connection）**，项目不对外开放 HTTP 端口

## 环境要求

- Python 3.13
- [uv](https://docs.astral.sh/uv/)
- Docker + Docker Compose（推荐部署方式）
- `ffmpeg`（Docker 镜像已内置）
- `lottie_convert.py`（由 `lottie` 依赖提供）

## 配置环境变量

复制示例文件：

```bash
cp .env.example .env
```

编辑 `.env`：

```env
TELEGRAM_BOT_API_TOKEN=...
FEISHU_APP_ID=...
FEISHU_APP_SECRET=...
BINDING_DB_PATH=data/stickerhub.db
BIND_MAGIC_TTL_SECONDS=600
LOG_LEVEL=INFO
```

说明：

- 飞书需在应用后台开启机器人收发消息权限，并启用长连接事件能力。

## 使用 Docker Compose 部署

```bash
docker compose up -d --build
```

查看日志：

```bash
docker compose logs -f stickerhub
```

## 绑定流程

1. 在 Telegram 或飞书任一端发送：`/bind`
2. 机器人返回一串魔法字符串
3. 在另一端发送：`/bind <魔法字符串>`
4. 绑定成功后，Telegram 发来的素材会路由到对应飞书身份

## 已知限制

- 个别复杂 `TGS` 贴纸可能因渲染差异转换失败。
- 飞书侧的表情“入库”仍需用户手动执行（本阶段目标如此）。
