# FeishuBot

一个专注于飞书生态的 Python Bot 项目骨架，建议按「先终端、后飞书」顺序推进：

- 先在终端完成多轮对话验证
- 可直接调用大模型接口（`/api/llm/chat`）
- 内置 OpenAI 兼容协议客户端（也可切回 `echo`）
- 飞书 webhook 保留为后续对接能力

## 1. 项目结构

```text
feishubot/
├── src/feishubot/
│   ├── app.py            # FastAPI 应用
│   ├── ai/               # 模型与工具调用骨架目录
│   │   ├── core/         # 通用 schema / registry / error
│   │   ├── providers/    # 各模型适配器（openai/anthropic/gemini...）
│   │   ├── tools/        # 工具定义与实现
│   │   ├── orchestrator/ # Agent 执行编排层
│   │   ├── prompts/      # Prompt 模板
│   │   ├── memory/       # 会话状态抽象
│   │   └── configs/      # 路由与工具配置样例
│   ├── config.py         # 环境配置
│   ├── feishu.py         # 飞书 API 客户端
│   ├── llm_client.py     # 大模型抽象与 OpenAI 兼容客户端
│   └── main.py           # 启动入口
├── .env.example
├── pyproject.toml
└── README.md
```

## 2. 快速开始

1. 创建并激活虚拟环境
2. 安装uv依赖：

```bash
pipx install uv
```

3. 开启虚拟环境(python版本3.14)：

```bash
uv venv --python 3.14
```

```bash
.venv\Scripts\Activate
```

4. 安装项目依赖：

```bash
uv sync
```

5. 启动网关服务：

```bash
feishubot gateway --reload --host 0.0.0.0 --port 8000
```

6. 快速配置（推荐首次执行）：

```bash
feishubot setup
```

会进入交互式向导，快速选择 LLM 提供商（`echo` / `openai_compatible`）并写入 `.env`。
当前内置大模型预设：`qwen`、`kimi`、`deepseek`。
该向导会写入 `LLM_MODELS_CONFIG_PATH` 和 `LLM_ACTIVE_MODEL`，用于维护多个模型并快速切换。

## 3. 先在终端跑通对话

配置好 `.env` 后可直接进入终端对话：

```bash
feishubot chat
```

可选参数：

```bash
feishubot chat --user-id demo-user --system-prompt "你是一个简洁的助手"
```

兼容旧命令（仍可用）：

```bash
feishubot-chat --user-id demo-user
```

退出方式：输入 `exit` / `quit` / `/exit`，或按 `Ctrl+C`。

工具层配置（可选）：

- 默认读取 `tools.default.toml`（仓库根目录，真实运行配置）
- 通过 `AI_TOOLS_CONFIG_PATH` 覆盖配置文件路径（可参考 `src/feishubot/ai/configs/tools.example.toml`）
- 支持 `enabled_tools` 控制可用工具集合
- 支持 `routing.<tool>.timeout_seconds` 覆盖工具默认超时
- 支持 `terminal.blocked_commands` 定义禁用命令片段（命中即拒绝执行）

## 4. 再调通 HTTP 大模型接口

1. 在 `.env` 中配置（单模型或多模型二选一）：

- `LLM_PROVIDER=openai_compatible`
- `LLM_BASE_URL=https://api.openai.com`（或你的网关地址）
- `LLM_API_KEY=<你的密钥>`
- `LLM_MODEL=<你的模型名>`

多模型模式（推荐）：

- `LLM_ACTIVE_MODEL=qwen`
- `LLM_MODELS_CONFIG_PATH=src/feishubot/ai/configs/model_routes.example.toml`

切换模型时只需修改 `LLM_ACTIVE_MODEL`，然后重启 `feishubot chat` 或 gateway 进程。

2. 调用接口测试：

```bash
curl -X POST http://127.0.0.1:8000/api/llm/chat \
  -H "Content-Type: application/json" \
  -d '{
    "message": "你好，给我一段简短的项目启动建议",
    "user_id": "demo-user"
  }'
```

## 5. 飞书侧配置（后续）

- 在飞书开发者后台创建应用并开启机器人能力
- 设置事件订阅请求地址为：`https://<your-domain>/webhook/feishu/events`
- 在 `.env` 中填写：
  - `FEISHU_APP_ID`
  - `FEISHU_APP_SECRET`
  - `FEISHU_VERIFICATION_TOKEN`（可选，按你启用方式）
  - `FEISHU_ENCRYPT_KEY`（可选）

## 6. 接入大模型说明

当前在 `llm_client.py` 提供了：

- `LLMClient` 抽象接口
- `EchoLLMClient`（本地调试）
- `OpenAICompatibleLLMClient`（兼容 OpenAI Chat Completions 协议）

你可以继续扩展：

- OpenAI Responses API
- Azure OpenAI
- 自建兼容 OpenAI 协议网关

建议保留统一接口，方便后续扩展「工具调用」「多 Agent」「任务执行器」。

## 7. 下一步建议

- 增加飞书消息去重（基于 `event_id`）
- 增加签名校验与加解密
- 增加指令路由（如 `/plan`、`/run`）
- 持久化会话上下文（Redis / PostgreSQL）

## 8. License

本项目使用 Apache-2.0 许可证，详见 `LICENSE`。

## 9. CI 与 PR 合并策略

项目已提供 GitHub Actions 工作流：

- `.github/workflows/ci.yml`：在 PR 和 `main` push 时自动执行 Ruff 格式检查、Ruff lint/安全规则检查、语法检查、基础导入检查、测试（若存在 `tests/`）
- `.github/CODEOWNERS`：指定代码所有者审阅（默认 `@wsmxd`）

建议在仓库 `Settings -> Branches -> Branch protection rules` 中启用：

- `Require a pull request before merging`
- `Require status checks to pass before merging`（勾选 `CI / Quality and Tests (Python 3.14)`）
- `Require review from Code Owners`

这样可实现：PR 自动审查测试通过后，再由所有者决定是否合并。
