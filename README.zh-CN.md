# Asset Scout

Asset Scout 是一个本地优先、授权感知的图片与视频素材发现工具，面向 AI 辅助剪辑。它只调用少量官方来源 API，记录来源与许可证据，执行确定性的使用门禁，将允许的素材下载到内容寻址本地库，并通过 CLI 与 MCP 提供逐帧指标。

首版范围很窄：优先支持 macOS ARM、以 Linux CI 为基本兼容；不抓取任意网页、不提取会话或 Cookie、不绕过来源限制，也不把聚合站结果直接当作许可证明。

## 快速开始

```bash
uv sync --extra dev
uv run asset-scout project init --profile commercial-edited-video
uv run asset-scout --json doctor
uv run asset-scout --json search "night city" --type image --limit 10
uv run asset-scout --json library search night
```

默认画像面向可能商业化的视频剪辑：`allow` 表示当前证据满足机器判定；`review` 必须由用户带理由明确批准；`deny` 在 v0.1 中不能下载。

Wikimedia Commons 与 Openverse 无需密钥。Openverse 只是聚合入口，必须回到原始来源核验后才能继续。Pexels、Pixabay 需要各自 API key，并且需要显式确认其条款：

```bash
export PEXELS_API_KEY="..."
export ASSET_SCOUT_ACCEPT_PEXELS_TERMS=1
export PIXABAY_API_KEY="..."
export ASSET_SCOUT_ACCEPT_PIXABAY_TERMS=1
```

密钥不会写入目录或 manifest；工具不是法律意见。

## 开发

```bash
uv run pytest
uv run ruff check .
```

详见 [SECURITY.md](SECURITY.md)、[CONTRIBUTING.md](CONTRIBUTING.md) 与英文 README 的命令示例。

