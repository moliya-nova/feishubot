from feishubot.ai.tools.base import Tool


class CalculatorTool(Tool):
    name = "calculator"
    description = "Evaluate simple arithmetic expressions."

    async def run(self, arguments):  # type: ignore[override]
        raise NotImplementedError("Scaffold only. Implement calculator logic here.")
