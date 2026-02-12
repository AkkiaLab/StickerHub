# StickerHub

StickerHub 是一个 Telegram 表情素材（Sticker/Image/GIF/Video）转换与获取工具，支持可选的飞书转发功能。

![bind.gif](docs/bind.gif)

## 功能范围

### Telegram 核心功能（无需飞书配置）

- 发送单个贴纸，机器人自动回复转换后的原始图片（可直接保存到相册）
- 发送单个贴纸后，可选择整包获取方式：
  - **📦 下载 ZIP 包**：全部转换后打包为 ZIP 文件发送
  - **🖼 Telegram 图片组**：以图片组形式发送，方便批量保存
- 支持贴纸格式自动转换：
  - 视频/动图 → GIF（保留透明背景）
  - TGS 动态贴纸 → GIF
  - WebP 静态图 → PNG
- 发送过程中可点击「停止发送」按钮，任务在当前批次结束后停止

### 飞书转发功能（可选）

配置飞书应用后，额外支持：

- 双端绑定机制（`/bind`），将 Telegram 身份与飞书身份关联
- 单个贴纸自动转发到飞书
- 整包发送时可选「📤 发送到飞书」，按每批 10 个并发发送
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

# 飞书配置（可选，留空则仅使用 Telegram 功能）
FEISHU_APP_ID=
FEISHU_APP_SECRET=

BINDING_DB_PATH=data/stickerhub.db
BIND_MAGIC_TTL_SECONDS=600
LOG_LEVEL=INFO
```

说明：

- `TELEGRAM_BOT_API_TOKEN`：必填，Telegram Bot API Token
- `FEISHU_APP_ID` / `FEISHU_APP_SECRET`：可选，填写后启用飞书转发和 `/bind` 功能
- 飞书需在应用后台开启机器人收发消息权限(im:message)以及获取与上传图片或文件资源权限(im:resource) ![lark_permission.png](docs/lark_permission.png)
- 飞书事件添加接收消息(im.message.receive_v1)并启用长连接事件能力。 ![lark_event.png](docs/lark_event.png)


## 使用 Docker Compose 部署（默认拉取 GHCR 镜像）

```bash
docker compose up -d
```

查看日志：

```bash
docker compose logs -f stickerhub
```

默认会拉取并运行：`ghcr.io/akkialab/stickerhub:latest`。

## 本地构建测试（不依赖远程镜像）

```bash
docker compose -f docker-compose.local.yml up -d --build
```

查看日志：

```bash
docker compose -f docker-compose.local.yml logs -f stickerhub
```

## 绑定流程（需配置飞书）
![20260213-050307.gif](../../Downloads/20260213-050307.gif)
1. 在 Telegram 或飞书任一端发送：`/bind`
2. 机器人返回一串魔法字符串
3. 在另一端发送：`/bind <魔法字符串>`
4. 绑定成功后，Telegram 发来的素材会路由到对应飞书身份

## 已知限制

- 个别复杂 `TGS` 贴纸可能因渲染差异转换失败。
- 飞书侧的表情“入库”仍需用户手动执行（本阶段目标如此）。
