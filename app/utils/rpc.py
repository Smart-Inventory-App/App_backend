"""Utilities for API responses"""
from typing import Any, Dict, Optional


class JSONRPCError:
    """JSON-RPC Error codes"""
    PARSE_ERROR = -32700
    INVALID_REQUEST = -32600
    METHOD_NOT_FOUND = -32601
    INVALID_PARAMS = -32602
    INTERNAL_ERROR = -32603


def jsonrpc_response(result: Any = None, error: Optional[Dict] = None, request_id: Any = None) -> dict:
    """
    Create a JSON-RPC 2.0 compliant response
    https://www.jsonrpc.org/specification
    """
    response = {"jsonrpc": "2.0"}
    
    if error:
        response["error"] = error
    else:
        response["result"] = result
    
    if request_id is not None:
        response["id"] = request_id
    
    return response


def jsonrpc_error(code: int, message: str, data: Any = None, request_id: Any = None) -> dict:
    """Create a JSON-RPC error response"""
    error = {"code": code, "message": message}
    if data:
        error["data"] = data
    
    return jsonrpc_response(error=error, request_id=request_id)
