"""
FastAPI demo server for Blast Radius.

Endpoints
---------
GET  /                  → Single-page web app
GET  /api/graph         → Full graph as vis.js nodes + edges (inst# nodes only)
GET  /api/entities      → Grouped entity summary for the sidebar
POST /api/chat          → Run NL/JSON envelope through workflow; return text + URIs to highlight
"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from core.nx_builder import local_name
from core.shopify_graph import ShopifyGraph
from orchestration.openai_interpreter import AutoEnvelopeInterpreter, OpenAIEnvelopeInterpreter
from orchestration.workflow import build_workflow

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_BASE = Path(__file__).parent.parent          # repo root
DEFAULT_ONTO = _BASE / "data" / "shopify_ontology.ttl"
DEFAULT_INST = _BASE / "data" / "synthetic_instances.ttl"
INST_PREFIX  = "https://example.com/shopify-inst#"

_TYPE_COLORS: dict[str, str] = {
    "Product":        "#3498db",
    "ProductVariant": "#2ecc71",
    "Order":          "#9b59b6",
    "Customer":       "#e67e22",
    "InventoryItem":  "#e74c3c",
    "Location":       "#f39c12",
    "Metafield":      "#95a5a6",
    "Metaobject":     "#1abc9c",
    "Fulfillment":    "#e91e63",
    "LineItem":       "#795548",
}
_DEFAULT_COLOR = "#bdc3c7"

# ---------------------------------------------------------------------------
# App-level singletons (loaded once at startup)
# ---------------------------------------------------------------------------

_sg: ShopifyGraph | None = None
_wf = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _sg, _wf
    _sg = ShopifyGraph.from_ttl(DEFAULT_ONTO, DEFAULT_INST)
    _wf = build_workflow(
        graph=_sg,
        interpreter=AutoEnvelopeInterpreter(nl=OpenAIEnvelopeInterpreter()),
    )
    yield


app = FastAPI(title="Blast Radius Demo", lifespan=lifespan)

# ---------------------------------------------------------------------------
# Static files  (lib/ served as /lib)
# ---------------------------------------------------------------------------

app.mount("/lib", StaticFiles(directory=str(_BASE / "lib")), name="lib")

# ---------------------------------------------------------------------------
# Helper: node type from RDF
# ---------------------------------------------------------------------------

def _node_type(uri: str) -> str:
    if _sg is None:
        return "Unknown"
    types = _sg.get_node_types(uri)
    for t in types:
        if t in _TYPE_COLORS:
            return t
    return types[0] if types else "Unknown"


def _is_inst(uri: str) -> bool:
    return uri.startswith(INST_PREFIX)


# ---------------------------------------------------------------------------
# GET  /api/graph
# ---------------------------------------------------------------------------

@app.get("/api/graph")
def api_graph() -> JSONResponse:
    assert _sg is not None
    G = _sg.nx_graph

    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []

    for uri in G.nodes():
        if not _is_inst(uri):
            continue
        short = local_name(uri)
        ntype = _node_type(uri)
        color = _TYPE_COLORS.get(ntype, _DEFAULT_COLOR)
        data  = _sg.get_node_data(uri)
        display = data.get("name") or data.get("sku") or short
        nodes.append({
            "id":    uri,
            "label": display,
            "title": f"{ntype} · {short}\n{uri}",
            "group": ntype,
            "color": {"background": color, "border": color, "highlight": {"background": "#f1c40f", "border": "#f39c12"}},
            "font":  {"color": "#fff"},
        })

    edge_id = 0
    for src, dst, data in G.edges(data=True):
        if not (_is_inst(src) and _is_inst(dst)):
            continue
        edges.append({
            "id":     edge_id,
            "from":   src,
            "to":     dst,
            "label":  data.get("relation", ""),
            "arrows": "to",
            "color":  {"color": "#7f8c8d"},
            "font":   {"size": 10, "color": "#555"},
        })
        edge_id += 1

    return JSONResponse({"nodes": nodes, "edges": edges})


# ---------------------------------------------------------------------------
# GET  /api/entities
# ---------------------------------------------------------------------------

@app.get("/api/entities")
def api_entities() -> JSONResponse:
    assert _sg is not None
    G = _sg.nx_graph

    groups: dict[str, list[dict]] = {}

    for uri in sorted(G.nodes()):
        if not _is_inst(uri):
            continue
        ntype = _node_type(uri)
        data = _sg.get_node_data(uri)
        short = local_name(uri)

        # Pick a readable display name
        display = data.get("name") or data.get("sku") or data.get("status") or short

        entry: dict[str, Any] = {
            "uri":     uri,
            "short":   short,
            "display": display,
            "type":    ntype,
            "color":   _TYPE_COLORS.get(ntype, _DEFAULT_COLOR),
            "attrs":   {k: v for k, v in data.items() if k != "uri"},
        }
        groups.setdefault(ntype, []).append(entry)

    # Sort groups by a preferred display order
    order = ["Product", "ProductVariant", "Order", "Customer",
             "InventoryItem", "Fulfillment", "Location", "Metafield", "Metaobject", "LineItem"]
    sorted_groups = {k: groups[k] for k in order if k in groups}
    for k in groups:
        if k not in sorted_groups:
            sorted_groups[k] = groups[k]

    return JSONResponse(sorted_groups)


# ---------------------------------------------------------------------------
# POST /api/chat
# ---------------------------------------------------------------------------

class ChatRequest(BaseModel):
    message: str
    base_dir: str = str(_BASE)


@app.post("/api/chat")
def api_chat(req: ChatRequest) -> JSONResponse:
    assert _wf is not None

    state = _wf.invoke({"user_input": req.message, "base_dir": req.base_dir})

    response_text: str = state.get("response", "")
    result_dict:  dict  = state.get("result") or {}
    env_dict:     dict  = state.get("envelope") or {}

    intent = env_dict.get("intent", "")
    start_uri: str | None = env_dict.get("start_uri")

    # Extract the URIs that should be highlighted on the graph
    highlighted: list[str] = []
    newly_impacted: list[str] = []
    removed_impacts: list[str] = []

    if intent == "blast":
        highlighted = [u for u in result_dict.get("reached", []) if _is_inst(u)]

    elif intent == "impact":
        highlighted = [u for u in result_dict.get("impacted_uris", []) if _is_inst(u)]

    elif intent == "simulate":
        simulated_uris = result_dict.get("simulated", {}).get("impacted_uris", [])
        delta          = result_dict.get("delta", {})
        newly_impacted  = [u for u in delta.get("newly_impacted", [])  if _is_inst(u)]
        removed_impacts = [u for u in delta.get("removed_impacts", []) if _is_inst(u)]
        highlighted     = [u for u in simulated_uris if _is_inst(u)]

    return JSONResponse({
        "response":        response_text,
        "intent":          intent,
        "start_uri":       start_uri,
        "highlighted":     highlighted,
        "newly_impacted":  newly_impacted,
        "removed_impacts": removed_impacts,
        "error":           state.get("error"),
    })


# ---------------------------------------------------------------------------
# GET  /   → serve the SPA
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    html_path = Path(__file__).parent / "static" / "index.html"
    return HTMLResponse(html_path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# CLI entry (used by `uv run web/server.py` or main.py serve command)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    host = os.environ.get("BR_HOST", "127.0.0.1")
    port = int(os.environ.get("BR_PORT", "8000"))
    uvicorn.run("web.server:app", host=host, port=port, reload=True)
