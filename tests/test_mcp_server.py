"""Live MCP protocol tests for the server (Phase 5).

Uses the MCP SDK's in-memory connected client/server session, so these exercise the real
protocol (initialize -> list_tools -> call_tool) without spawning a subprocess or needing
Maven. `verify_build` is asserted present but not invoked (it shells out to mvn; its logic
is covered by test_build_runner.py).
"""
from __future__ import annotations
import asyncio
import json
import shutil
from pathlib import Path

from mcp.shared.memory import create_connected_server_and_client_session

from dep_remediation.mcp_server import mcp

FIXTURES = Path(__file__).parent / "fixtures"
ADVISORY = str(FIXTURES / "dummy_advisory.xlsx")


def _run(coro):
    return asyncio.run(coro)


def _result_dict(result):
    """Extract the tool's dict return from a CallToolResult."""
    if getattr(result, "structuredContent", None):
        return result.structuredContent
    return json.loads(result.content[0].text)


def test_list_tools_exposes_three_tools():
    async def go():
        async with create_connected_server_and_client_session(mcp) as client:
            tools = (await client.list_tools()).tools
            by_name = {t.name: t for t in tools}
            for name in ("parse_advisory", "apply_fixes", "verify_build"):
                assert name in by_name, f"missing tool: {name}"
                assert by_name[name].description  # non-empty description
                assert by_name[name].inputSchema  # has an input schema
    _run(go())


def test_call_parse_advisory():
    async def go():
        async with create_connected_server_and_client_session(mcp) as client:
            result = await client.call_tool(
                "parse_advisory", {"xlsx_path": ADVISORY, "app": "app-alpha"})
            assert not result.isError
            data = _result_dict(result)
            assert len(data["findings"]) == 4
            conflicts = {c["coordinate"]: c for c in data["conflicts"]}
            assert conflicts["io.netty:netty-handler"]["chosen"] == "4.2.15.Final"
    _run(go())


def test_call_apply_fixes_dry_run(tmp_path):
    pom = tmp_path / "direct.xml"
    shutil.copy(FIXTURES / "poms" / "direct.xml", pom)

    async def go():
        async with create_connected_server_and_client_session(mcp) as client:
            result = await client.call_tool(
                "apply_fixes",
                {"pom_path": str(pom), "xlsx_path": ADVISORY, "app": "app-alpha"})
            assert not result.isError
            data = _result_dict(result)
            assert data["applied"] is False          # dry-run by default
            assert data["actions"]                    # something to do
    _run(go())
    # dry-run must not have modified the copied pom
    assert "4.2.4.Final" in pom.read_text(encoding="utf-8")


def test_call_apply_fixes_with_skip_override(tmp_path):
    pom = tmp_path / "direct.xml"
    shutil.copy(FIXTURES / "poms" / "direct.xml", pom)

    async def go():
        async with create_connected_server_and_client_session(mcp) as client:
            # baseline: netty-handler is among the planned actions
            base = _result_dict(await client.call_tool(
                "apply_fixes", {"pom_path": str(pom), "xlsx_path": ADVISORY, "app": "app-alpha"}))
            assert any(a["coordinate"] == "io.netty:netty-handler" for a in base["actions"])
            # with an override dropping it ("" = skip), it must disappear from the plan
            curated = _result_dict(await client.call_tool(
                "apply_fixes",
                {"pom_path": str(pom), "xlsx_path": ADVISORY, "app": "app-alpha",
                 "overrides": {"io.netty:netty-handler": ""}}))
            assert not any(a["coordinate"] == "io.netty:netty-handler" for a in curated["actions"])
    _run(go())
