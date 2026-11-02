"""
Model Context Protocol (MCP) Integration Package.
Exposes native JSON-RPC 2.0 stdio server for LLM agents.
"""

from .server import MCPServer

__all__ = ["MCPServer"]
