from feishubot.ai.tools.base import Tool


class WebSearchTool(Tool):
    name = "web_search"
    description = "Search web content and return snippets."

    async def run(self, arguments):  # type: ignore[override]
        raise NotImplementedError("Scaffold only. Implement web search logic here.")
