from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass
class ToolResult:
    # tool result object
    success: bool
    data: Any = None
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        # serialize to dict
        return {
            "success": self.success,
            "data": self.data,
            "error": self.error,
            "metadata": self.metadata,
        }


class BaseTool(ABC):
    # base tool class
    name: str = "base_tool"
    description: str = "Base tool description"
    parameters_schema: Dict[str, Any] = {}

    @abstractmethod
    def execute(self, **kwargs) -> ToolResult:
        # execute tool action
        pass

    def __call__(self, **kwargs) -> ToolResult:
        # safely handle exceptions
        try:
            return self.execute(**kwargs)
        except Exception as e:
            return ToolResult(
                success=False,
                data=None,
                error=f"Error executing tool '{self.name}': {type(e).__name__} - {str(e)}"
            )
