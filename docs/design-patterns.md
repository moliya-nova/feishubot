# Design Patterns

## 1. Provider Abstraction

The codebase uses a provider interface to isolate model-specific API calls from the rest of the application.

- `ModelProvider` defines the async `chat()` contract.
- Concrete providers implement the protocol for each backend.
- `create_provider()` centralizes provider construction from resolved settings.

This keeps the rest of the system independent from transport details and backend-specific payload formats.

The repository still contains `src/feishubot/llm_client.py` as a prompt-based compatibility layer and reference implementation, but the provider factory is the main execution path.

## 2. Single Orchestrator Flow

`AgentLoop` is the shared execution path for CLI, HTTP chat, and Feishu webhook processing.

- It asks the provider for a first response.
- It parses a tool request when present.
- It executes the selected tool through `ToolRuntime`.
- It asks the provider for the final user-facing answer.

This avoids multiple divergent chat flows and keeps tool behavior consistent across entry points.

## 3. Tool Registry and Runtime

Tools follow a simple registry pattern.

- Each tool is a named singleton instance.
- `register_builtin_tools()` adds built-ins to the shared registry.
- `ToolRuntime` resolves enabled tools, applies routing config, validates args, and executes the tool.

This makes the runtime predictable and keeps tool discovery separate from tool execution.

## 4. Configuration-Driven Behavior

Several runtime decisions are controlled by settings or YAML config.

- `Settings.active_llm_config()` resolves the active provider model.
- `AI_TOOLS_CONFIG_PATH` can point to a tool routing file.
- `enabled_tools` controls which tools are available.
- `routing.<tool>.timeout_seconds` overrides per-tool timeout behavior.

This reduces code changes when introducing new tools or changing defaults.

## 5. Fail-Loud, Explain-Later Tool Handling

Tool invocation errors are captured and reflected back to the model instead of immediately terminating the user request.

- Tool execution failures are logged with context.
- The orchestrator gives the model the error message and result envelope.
- The final reply can explain the failure and suggest a safer retry.

This is useful for interactive assistants where tool failure should be recoverable.

## 6. Lightweight Service Boundaries

The current design keeps boundaries narrow.

- FastAPI handles HTTP transport and Feishu webhook ingress.
- The provider layer handles model I/O.
- The orchestrator handles reasoning and routing.
- The tool layer handles side-effectful actions and pure helpers.

That separation makes the project easier to extend without entangling entry points with execution logic.
