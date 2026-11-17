"""G0-05 S5 stub: MCP tool load_photo(scan_id) returns MCP ImageContent.

Stand-in for media.photo (Plan 3.6, fallback A2b). The images are the
synthetic, brand-free test images of spikes/mm/img, baked into the
image under /app/img. scan_id selects the file by its stem
(e.g. "s5-1-competitor_tag" -> competitor_tag.jpg); unknown ids fall
back to competitor_tag.jpg.

Run: python photo_stub.py   (streamable HTTP on :8766/mcp, /health)
"""
import logging
import os
import sys

from mcp.server.mcpserver import Image, MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("gpos-spike-p05-photo")

IMG_DIR = os.environ.get("IMG_DIR", "/app/img")
PORT = int(os.environ.get("MCP_PORT", "8766"))
PATH = os.environ.get("MCP_PATH", "/mcp")

mcp = MCPServer(name="gpos-spike-p05-photo",
                instructions="G0-05 spike: returns stored competitor photos.")


def _pick(scan_id: str) -> str:
    names = sorted(f for f in os.listdir(IMG_DIR) if f.endswith(".jpg"))
    # longest stem first, so competitor_tag_150k wins over competitor_tag
    for f in sorted(names, key=len, reverse=True):
        if f.rsplit(".", 1)[0] in scan_id:
            return f
    return "competitor_tag.jpg"


@mcp.tool()
def load_photo(scan_id: str, run_id: str = "") -> Image:
    """Load the stored photo of one competitor scan (stand-in for media.photo).

    Returns the JPEG as MCP image content.
    """
    f = _pick(scan_id)
    p = os.path.join(IMG_DIR, f)
    log.info("load_photo scan_id=%s run_id=%s -> %s (%d bytes)", scan_id, run_id, f,
             os.path.getsize(p))
    return Image(path=p)


@mcp.custom_route("/health", methods=["GET"])
async def health(request: Request) -> Response:
    return JSONResponse({"ok": True, "images": sorted(os.listdir(IMG_DIR))})


def dump_tools() -> None:
    import asyncio
    import json

    async def _list():
        out = []
        for t in await mcp.list_tools():
            d = t.model_dump(exclude_none=True, by_alias=True)
            out.append({k: d[k] for k in ("name", "description", "inputSchema",
                                          "outputSchema") if k in d})
        return out

    print(json.dumps(asyncio.run(_list()), indent=1))


if __name__ == "__main__":
    if "--dump-tools" in sys.argv:
        dump_tools()
    else:
        log.info("photo stub on :%d%s, images in %s", PORT, PATH, IMG_DIR)
        mcp.run(transport="streamable-http", host="0.0.0.0", port=PORT,
                streamable_http_path=PATH, json_response=True, stateless_http=True,
                transport_security=TransportSecuritySettings(
                    enable_dns_rebinding_protection=False))
