from typing import Dict, List, Any, Optional
from tools.base import BaseTool, ToolResult


class ToolRegistry:
    def __init__(self):
        # store tools
        self._tools: Dict[str, BaseTool] = {}

    def register(self, tool: BaseTool) -> None:
        # validate type
        if not isinstance(tool, BaseTool):
            raise TypeError(f"Expected BaseTool, got {type(tool).__name__}")
        # save tool
        self._tools[tool.name] = tool

    def get(self, name: str) -> Optional[BaseTool]:
        # fetch tool
        return self._tools.get(name)

    def list_tools(self) -> List[str]:
        # tool names
        return list(self._tools.keys())

    def get_schemas(self) -> List[Dict[str, Any]]:
        # export schemas
        schemas = []
        for tool in self._tools.values():
            schemas.append({
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.parameters_schema or {
                    "type": "object",
                    "properties": {},
                }
            })
        return schemas

    def execute(self, tool_name: str, **kwargs) -> ToolResult:
        # find tool
        tool = self.get(tool_name)
        
        # handle missing
        if not tool:
            available = ", ".join(self.list_tools()) or "None"
            return ToolResult(
                success=False,
                data=None,
                error=f"Tool '{tool_name}' not found. Available: {available}"
            )

        # run tool
        return tool(**kwargs)
