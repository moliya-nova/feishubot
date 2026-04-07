from feishubot.ai.core.registry import NamedRegistry
from feishubot.ai.tools.base import Tool


tool_registry: NamedRegistry[Tool] = NamedRegistry()
