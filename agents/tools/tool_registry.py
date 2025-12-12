"""
Tool Registry for RAG Agent.
Defines all available tools in OpenAI Function Calling format
and provides tool execution dispatcher.
"""

from typing import List, Dict, Any, Callable, Optional
import time
from utils.logger import logger, log_tool_execution


class ToolRegistry:
    """Registry for all agent tools with OpenAI Function Calling format."""

    def __init__(self):
        """Initialize tool registry."""
        self.tools: Dict[str, Callable] = {}
        self.tool_definitions: List[Dict[str, Any]] = []

    def register_tool(
        self,
        name: str,
        function: Callable,
        description: str,
        parameters: Dict[str, Any]
    ) -> None:
        """
        Register a tool with its OpenAI function definition.

        Args:
            name: Tool name
            function: Python function to execute
            description: Tool description for LLM
            parameters: JSON schema for parameters
        """
        # Store function
        self.tools[name] = function

        # Store OpenAI function definition
        tool_def = {
            "type": "function",
            "function": {
                "name": name,
                "description": description,
                "parameters": parameters
            }
        }
        self.tool_definitions.append(tool_def)

        logger.debug(f"Tool registered: {name}")

    def execute_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute a tool by name with given arguments.

        Args:
            tool_name: Name of the tool to execute
            arguments: Tool arguments as dictionary

        Returns:
            Tool execution result with metadata

        Example:
            {
                'success': True,
                'result': [...],
                'error': None,
                'execution_time': 0.5,
                'document_count': 5
            }
        """
        start_time = time.time()

        try:
            if tool_name not in self.tools:
                error_msg = f"Tool not found: {tool_name}"
                logger.error(error_msg)
                return {
                    'success': False,
                    'result': None,
                    'error': error_msg,
                    'execution_time': 0.0,
                    'document_count': 0
                }

            # Execute tool
            function = self.tools[tool_name]
            result = function(**arguments)

            execution_time = time.time() - start_time

            # Determine document count
            doc_count = 0
            if isinstance(result, list):
                doc_count = len(result)
            elif isinstance(result, dict) and result is not None:
                doc_count = 1

            # Log execution
            log_tool_execution(tool_name, arguments, execution_time)

            return {
                'success': True,
                'result': result,
                'error': None,
                'execution_time': execution_time,
                'document_count': doc_count
            }

        except Exception as e:
            execution_time = time.time() - start_time
            error_msg = f"{type(e).__name__}: {str(e)}"
            logger.error(f"Tool execution failed: {tool_name} - {error_msg}", exc_info=True)

            return {
                'success': False,
                'result': None,
                'error': error_msg,
                'execution_time': execution_time,
                'document_count': 0
            }

    def get_tool_definitions(self) -> List[Dict[str, Any]]:
        """
        Get all tool definitions in OpenAI format.

        Returns:
            List of tool definitions for OpenAI API
        """
        return self.tool_definitions

    def get_tool_names(self) -> List[str]:
        """
        Get list of all registered tool names.

        Returns:
            List of tool names
        """
        return list(self.tools.keys())

    def tool_exists(self, tool_name: str) -> bool:
        """
        Check if a tool exists.

        Args:
            tool_name: Name of the tool

        Returns:
            True if tool exists, False otherwise
        """
        return tool_name in self.tools


# Global tool registry instance (will be populated by individual tool modules)
tool_registry = ToolRegistry()


def create_parameter_schema(
    properties: Dict[str, Dict[str, Any]],
    required: Optional[List[str]] = None
) -> Dict[str, Any]:
    """
    Helper function to create OpenAI parameter schema.

    Args:
        properties: Dictionary of parameter definitions
        required: List of required parameter names

    Returns:
        Parameter schema in JSON schema format

    Example:
        properties = {
            "error_code": {
                "type": "string",
                "description": "Error code to search (e.g., '50001')"
            },
            "top_k": {
                "type": "integer",
                "description": "Number of results",
                "default": 5
            }
        }
        required = ["error_code"]
    """
    return {
        "type": "object",
        "properties": properties,
        "required": required or []
    }
