# StickerHub 仓库级 Copilot 指令

本文件为仓库级指令，适用于整个 StickerHub 代码库。

## 项目范围

- 项目是 `StickerHub`，用于 Telegram 表情素材转换与获取，支持可选的飞书转发。
- 飞书配置为可选，仅配置 Telegram Bot Token 即可使用核心功能。
- 飞书事件接收必须使用长连接模式。
- 不要在本项目新增 HTTP Webhook 监听端口。

## 技术栈

- 语言与运行时：Python 3.13。
- 包管理与任务执行：`uv`。
- 本地调试应支持直接终端运行。
- Docker Compose 主要用于分发和快速启动。

## 架构规则

- `src/stickerhub/core/` 仅放领域模型与端口协议。
- `src/stickerhub/services/` 仅放业务逻辑编排。
- `src/stickerhub/adapters/` 仅放平台 SDK、HTTP、I/O 细节。
- `src/stickerhub/main.py` 仅负责依赖装配与启动。
- 扩展能力优先走端口抽象，不要在适配器中堆跨平台硬编码分支。

## 不可破坏的业务行为

- `/bind`（无参数）应创建或复用当前平台身份，并返回魔法字符串。
- `/bind <code>` 应将当前平台账号绑定到该魔法字符串对应身份。
- 绑定冲突策略为可覆盖：以魔法字符串所属身份为高优先级。
- Telegram 单贴纸流程必须保持两步：
  - 先立即转发表情。
  - 再提示是否发送整包。
- 整包发送保持分批（每批 `10` 个）并发，带进度更新和停止按钮。
- 用户点击停止后，应在当前批次结束后生效。
- 不支持的命令或消息类型必须返回清晰使用说明。
- 启动时注册 Telegram 命令：`/bind`、`/help`、`/start`。

## 媒体转换规则

- 必须支持 TGS 动态贴纸，并转换为 GIF。
- 视频或动图转发到飞书前应转换为 GIF。
- WebP 需要时应转换为 PNG。
- 转换失败必须输出可定位日志。
- 临时文件必须在 `finally` 中清理。

## 配置规则

- 环境配置统一通过 `src/stickerhub/config.py` 中的 `Settings` 读取。
- 新增配置项时必须同步更新：
  - `.env.example`
  - `README.md`
  - 对应测试
- 不要引入未被需求明确要求的配置项。

## 编码规范

- 注释、文档、用户可见提示默认使用中文。
- 新增或修改代码应保持完整类型标注。
- 避免泛化使用 `hasattr/getattr`；仅在第三方 SDK 动态对象场景做局部封装。
- `except Exception` 必须记录上下文日志，禁止静默吞错。
- 日志应带关键上下文（`platform`、`user`、`task_id`、`batch`）。
- 日志中禁止输出密钥、Token 等敏感信息。

## 测试与质量门禁

- 任何行为变化都必须新增或更新 `tests/`。
- 优先覆盖：`/bind` 解析、绑定冲突覆盖策略、Telegram 任务状态与消息解析。
- 完成修改前运行：
  - `uv run pytest`
  - `uv run pre-commit run --all-files`

## 变更自检清单

- 复用现有命名和实现模式，避免平行实现。
- 改动函数签名或契约时，同步更新调用方和测试。
- 用户可见流程变化时，同步更新 `README.md`。
- 保持改动聚焦，避免无关重构。
