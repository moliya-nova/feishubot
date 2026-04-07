# AI Module Layout

This directory is intentionally scaffolded first and implementation-light.

Goals:
- Integrate multiple LLM providers under a unified interface
- Register and invoke callable tools
- Build an orchestrator layer for planning and execution

Subdirectories:
- core: shared schemas, errors, and registries
- providers: model provider adapters
- tools: tool specs and executable tools
- orchestrator: planning/execution loop
- prompts: system and task prompts
- memory: conversation and state abstractions
- configs: provider/tool route examples
