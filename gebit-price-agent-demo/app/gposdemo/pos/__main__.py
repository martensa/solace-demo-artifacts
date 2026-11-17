"""``python -m gposdemo.pos [--dump-tools]`` (UC1-BUILD-SPEC 2.4, 8.5).

``--dump-tools`` prints ``tools/list`` of ``gpos-pos-api`` and exits without DB, bus or
GEBIT descriptor sets; otherwise the process runs until it is stopped.
"""

from __future__ import annotations

from gposdemo.common import mcputil

from . import tools
from .server import run


def main() -> None:
    """Dump the tool list or run the service."""
    if mcputil.wants_dump_tools():
        mcputil.dump_tools(tools.build_mcp(None, None))
        return
    run()


if __name__ == "__main__":
    main()
