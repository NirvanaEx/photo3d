"""Разведка API MCP SDK 2.0: чем заменили FastMCP, как регистрировать
инструменты, как возвращать картинки и как поднимать stdio-транспорт.

    /opt/photo3d/venv/bin/python /mnt/d/Develop/photo3d/scripts/diag_mcp2.py
"""
import inspect


def public(mod):
    return sorted(n for n in dir(mod) if not n.startswith("_"))


def head(title):
    print("\n" + "=" * 8, title)


head("mcp.server")
import mcp.server as S
print(public(S))

head("mcp.server.mcpserver")
from mcp.server import mcpserver
names = public(mcpserver)
print(names)
for n in names:
    obj = getattr(mcpserver, n)
    if inspect.isclass(obj) and obj.__module__.startswith("mcp"):
        doc = (obj.__doc__ or "").strip().splitlines()
        print(f"\n--- class {n}: {doc[0] if doc else ''}")
        try:
            print("    __init__", inspect.signature(obj.__init__))
        except (ValueError, TypeError):
            pass
        methods = [m for m in public(obj) if callable(getattr(obj, m, None))]
        print("    methods:", ", ".join(methods[:25]))
        for m in ("tool", "add_tool", "run", "run_stdio", "run_stdio_async"):
            if hasattr(obj, m):
                try:
                    print(f"    .{m}{inspect.signature(getattr(obj, m))}")
                except (ValueError, TypeError):
                    print(f"    .{m}(...)")

head("mcp.server.runner")
try:
    from mcp.server import runner
    print(public(runner))
    for n in public(runner):
        o = getattr(runner, n)
        if inspect.isfunction(o):
            print(f"  {n}{inspect.signature(o)}")
except Exception as exc:  # noqa: BLE001
    print("нет:", exc)

head("типы контента в mcp.types")
import mcp.types as T
print([n for n in public(T) if "Content" in n or "Image" in n or "Blob" in n])
for n in ("ImageContent", "TextContent"):
    if hasattr(T, n):
        cls = getattr(T, n)
        flds = getattr(cls, "model_fields", None)
        print(f"  {n}: {list(flds) if flds else '?'}")
