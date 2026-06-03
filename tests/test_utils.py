"""Utils / JSON-RPC tests."""
from app.utils.rpc import JSONRPCError, jsonrpc_response, jsonrpc_error


def test_jsonrpc_response_success():
    resp = jsonrpc_response(result={"key": "value"}, request_id=1)
    assert resp["jsonrpc"] == "2.0"
    assert resp["result"] == {"key": "value"}
    assert resp["id"] == 1
    assert "error" not in resp


def test_jsonrpc_response_error():
    err = {"code": -32600, "message": "Invalid Request"}
    resp = jsonrpc_response(error=err, request_id=2)
    assert resp["error"] == err
    assert "result" not in resp


def test_jsonrpc_response_no_id():
    resp = jsonrpc_response(result="ok")
    assert "id" not in resp


def test_jsonrpc_error_response():
    resp = jsonrpc_error(JSONRPCError.INVALID_PARAMS, "Bad params", data={"field": "x"}, request_id=3)
    assert resp["error"]["code"] == JSONRPCError.INVALID_PARAMS
    assert resp["error"]["message"] == "Bad params"
    assert resp["error"]["data"] == {"field": "x"}
    assert resp["id"] == 3


def test_jsonrpc_error_constants():
    assert JSONRPCError.PARSE_ERROR == -32700
    assert JSONRPCError.METHOD_NOT_FOUND == -32601
    assert JSONRPCError.INTERNAL_ERROR == -32603
