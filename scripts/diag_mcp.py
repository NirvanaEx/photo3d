"""Диагностика окружения: где лежит mcp, какой версии, есть ли FastMCP.

    /opt/photo3d/venv/bin/python /mnt/d/Develop/photo3d/scripts/diag_mcp.py
"""
import importlib.metadata as md
import inspect
import os
import pkgutil

import mcp

pkg_dir = os.path.dirname(mcp.__file__)
print("MCP AT :", pkg_dir)
try:
    print("VERSION:", md.version("mcp"))
except Exception as exc:  # noqa: BLE001
    print("VERSION: неизвестна:", exc)

print("SUBMODULES:", ", ".join(sorted(m.name for m in pkgutil.iter_modules([pkg_dir]))))

server_dir = os.path.join(pkg_dir, "server")
if os.path.isdir(server_dir):
    print("SERVER SUBMODULES:", ", ".join(
        sorted(m.name for m in pkgutil.iter_modules([server_dir]))
    ))

try:
    from mcp.server.fastmcp import FastMCP, Image
    print("FASTMCP: OK")
    print("  Image.__init__:", inspect.signature(Image.__init__))
    print("  FastMCP.tool  :", inspect.signature(FastMCP.tool))
except Exception as exc:  # noqa: BLE001
    print("FASTMCP: НЕДОСТУПЕН:", type(exc).__name__, exc)

for extra in ("fastmcp", "pydantic"):
    try:
        print(f"{extra}: {md.version(extra)}")
    except Exception:  # noqa: BLE001
        print(f"{extra}: не установлен")
