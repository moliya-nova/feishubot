# Project Structure

## Top-level Layout

- `src/feishubot/`: Python package source code for FeishuBot
- `docs/`: architecture and design notes
- `pyproject.toml`: packaging, dependencies, and tooling configuration
- `README.md`: user-facing project overview and quick start

## Naming Convention

- Use `FeishuBot` for the project/product name in prose and metadata.
- Use `feishubot` only for the Python package path, CLI module path, and filesystem references.

## Source Code Areas

### Application entry points

- `src/feishubot/main.py`: ASGI app entry for running the service
- `src/feishubot/app.py`: FastAPI routes for health, chat, and Feishu webhook handling
- `src/feishubot/cli.py`: terminal CLI, gateway launcher, and setup/model management commands

### Configuration and integration

- `src/feishubot/config.py`: environment-backed settings and active LLM resolution
- `src/feishubot/feishu.py`: Feishu API client
- `src/feishubot/llm_client.py`: prompt-based LLM client and compatibility reference for the earlier chat flow

### LLM and agent system

- `src/feishubot/ai/core/`: shared errors, schemas, and registries
- `src/feishubot/ai/providers/`: model provider abstraction and provider implementations
- `src/feishubot/ai/orchestrator/`: model-tool execution loop
- `src/feishubot/ai/tools/`: tool base classes, runtime, registry, and built-ins
- `src/feishubot/ai/prompts/`: system prompt templates
- `src/feishubot/ai/configs/`: sample YAML configuration files for routing and tools
- `src/feishubot/ai/memory/`: memory store scaffolding for future conversation state

## Runtime Flow

1. CLI or HTTP entry point receives a user message.
2. `settings.active_llm_config()` resolves the active model configuration.
3. `ai.providers.create_provider()` builds the matching provider.
4. `AgentLoop` sends the user prompt plus system prompt to the provider.
5. If the model returns a tool call, `ToolRuntime` validates and executes the tool.
6. The final model reply is returned to the caller or sent back to Feishu.

## Extension Points

- Add new providers under `src/feishubot/ai/providers/`.
- Add new tools under `src/feishubot/ai/tools/builtins/` and register them in the builtin registry.
- Add new routing or tool defaults in `src/feishubot/ai/configs/tools.example.yaml`.
- Add new prompts in `src/feishubot/ai/prompts/system/`.
