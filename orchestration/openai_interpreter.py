from __future__ import annotations

import json
import os
from typing import Any, get_args

from dotenv import load_dotenv
from openai import OpenAI

from core.models import ChangeType
from orchestration.interpreters import EnvelopeInterpreter


SYSTEM_PROMPT = """You convert user requests into a JSON envelope for a deterministic graph impact engine.

Return ONLY valid JSON matching the schema.

URI format:
- Instance URIs use prefix https://example.com/shopify-inst#
  e.g. "prod_mug" -> "https://example.com/shopify-inst#prod_mug"
- Always produce the FULL URI with the prefix for start_uri and target_uri.

Known instance shortnames (use these to build full URIs):
  Locations   : loc_syd_01 (Sydney), loc_mel_01 (Melbourne), loc_bne_01 (Brisbane), loc_per_01 (Perth)
  Customers   : cust_01 (Asha Iyer), cust_02 (Liam Chen), cust_03 (Sophie Taylor),
                cust_04 (Marco Rossi), cust_05 (Emma Wilson)
  Products    : prod_hoodie (Comfy Hoodie), prod_mug (Ceramic Mug),
                prod_tote (Canvas Tote Bag), prod_cap (Logo Cap), prod_bottle (Insulated Water Bottle)
  Variants    : var_hoodie_s, var_hoodie_m, var_mug_white, var_tote_natural, var_tote_black,
                var_cap_sm, var_cap_lxl, var_bottle_500, var_bottle_1000
  Inventory   : inv_hoodie_s, inv_hoodie_m, inv_mug_white, inv_tote_natural, inv_tote_black,
                inv_cap_sm, inv_cap_lxl, inv_bottle_500, inv_bottle_1000
  Orders      : order_9001, order_9002, order_9003, order_9004, order_9005
  Line Items  : li_9001_1, li_9001_2, li_9002_1, li_9003_1, li_9003_2, li_9004_1, li_9005_1, li_9005_2
  Fulfillments: ful_9001_1 (Sydney), ful_9002_1 (Melbourne), ful_9003_1 (Melbourne),
                ful_9004_1 (Brisbane), ful_9005_1 (Perth)
  Metafields  : mf_prod_hoodie_campaign, mf_prod_mug_campaign, mf_prod_tote_campaign, mf_prod_cap_campaign
  Metaobjects : mo_campaign_summer, mo_campaign_winter

Rules:
- intent: one of blast|impact|simulate|help
- start_uri: a full URI (https://example.com/shopify-inst#<shortname>)
- traversal: choose reasonable defaults if not specified (depth 3-4, direction both)
- For impact/simulate: include change with change_type and target_uri (usually target_uri=start_uri)
- For simulate with a known scenario file, set scenario_file as a path relative to the repo root.
  Available scenario files:
    "scenarios/remove_variant.json"               — remove a product variant
    "scenarios/rel_remove_mug_variant.json"       — remove the mug variant relationship
    "scenarios/rel_add_cross_variant.json"        — add a cross-variant relationship
    "scenarios/outage_reroute_fulfillment.json"   — reroute fulfillment during an outage
    "scenarios/d_reroute_outage.json"             — outage / reroute scenario (alternate)
    "scenarios/b_remove_metafield.json"           — remove a metafield
    "scenarios/schema_remove_metafield_link.json" — remove a metafield schema link
    "scenarios/attr_set_and_unset.json"           — set then unset an attribute
    "scenarios/e_attr_only_colors.json"           — attribute-only colour change
- For simulate with a hypothetical described in the query (e.g. "what if Melbourne goes down",
  "what if we run out of hoodie stock", "what if the summer campaign metaobject is removed"):
  generate an INLINE scenario object instead of scenario_file. Populate attribute_overrides
  and/or edge_mutations to represent the change. Examples:
    * Location outage: attribute_overrides [{node_uri: "...loc_mel_01", key: "status", op: "set", value: "outage"}]
    * Remove fulfillment link: edge_mutations [{op: "remove", src_uri: "...ful_9002_1", dst_uri: "...loc_mel_01", relation: "fulfilledFrom"}]
    * Out of stock: attribute_overrides [{node_uri: "...inv_hoodie_m", key: "status", op: "set", value: "out_of_stock"}]
  Use a descriptive scenario_id like "mel-outage" or "hoodie-m-oos".
- If user request is unclear, set intent=help and put a clarifying question in clarifying_questions.
"""

# Derive change-type enum from the canonical ChangeType literal so they stay in sync.
_CHANGE_TYPES: list[str] = list(get_args(ChangeType))

ENVELOPE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "intent": {"type": "string", "enum": ["blast", "impact", "simulate", "help"]},
        "start_uri": {"type": ["string", "null"]},
        "traversal": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "depth": {"type": "integer", "minimum": 1},
                "direction": {"type": "string", "enum": ["out", "in", "both"]},
                "max_results": {"type": "integer", "minimum": 1},
                "top_n": {"type": "integer", "minimum": 1},
            },
            "required": ["depth", "direction", "max_results", "top_n"],
        },
        "change": {
            "type": ["object", "null"],
            "additionalProperties": False,
            "properties": {
                "change_type": {
                    "type": "string",
                    "enum": _CHANGE_TYPES,
                },
                "target_uri": {"type": "string"},
                "attribute_name": {"type": ["string", "null"]},
                "old_value": {"type": ["string", "null"]},
                "new_value": {"type": ["string", "null"]},
                "relation": {"type": ["string", "null"]},
                "related_uri": {"type": ["string", "null"]},
                "operation": {"type": ["string", "null"]},
            },
            "required": ["change_type", "target_uri", "attribute_name", "old_value", "new_value", "relation", "related_uri", "operation"],
        },
        "scenario_file": {"type": ["string", "null"]},
        "scenario": {
            "type": ["object", "null"],
            "additionalProperties": False,
            "properties": {
                "scenario_id": {"type": "string"},
                "description": {"type": ["string", "null"]},
                "attribute_overrides": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "node_uri": {"type": "string"},
                            "key": {"type": "string"},
                            "op": {"type": "string", "enum": ["set", "unset"]},
                            "value": {"type": ["string", "null"]},
                        },
                        "required": ["node_uri", "key", "op", "value"],
                    },
                },
                "edge_mutations": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "op": {"type": "string", "enum": ["add", "remove"]},
                            "src_uri": {"type": "string"},
                            "dst_uri": {"type": "string"},
                            "relation": {"type": "string"},
                            "predicate_uri": {"type": ["string", "null"]},
                        },
                        "required": ["op", "src_uri", "dst_uri", "relation", "predicate_uri"],
                    },
                },
            },
            "required": ["scenario_id", "description", "attribute_overrides", "edge_mutations"],
        },
        "strict": {"type": "boolean"},
        "validate_scenario": {"type": "boolean"},
        "assumptions": {"type": "array", "items": {"type": "string"}},
        "clarifying_questions": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["intent", "start_uri", "traversal", "change", "scenario_file", "scenario", "strict", "validate_scenario", "assumptions", "clarifying_questions"],
}


class OpenAIEnvelopeInterpreter(EnvelopeInterpreter):
    """
    Natural language -> envelope dict via OpenAI Responses API + Structured Outputs.
    """

    def __init__(self) -> None:
        load_dotenv(override=True, encoding="utf-8-sig")
        self._client = OpenAI()
        self._model = os.environ.get("OPENAI_MODEL", "gpt-5.2")

    def interpret(self, text: str) -> dict[str, Any]:
        resp = self._client.responses.create(
            model=self._model,
            input=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": text},
            ],
            text={
                "format": {
                    "type": "json_schema",
                    "name": "request_envelope",
                    "strict": True,
                    "schema": ENVELOPE_SCHEMA,
                }
            },
        )

        out = resp.output_text
        if not out:
            raise ValueError("OpenAI response contained no output_text")

        try:
            raw = json.loads(out)
        except json.JSONDecodeError as e:
            raise ValueError(f"Model returned non-JSON output: {e}") from e

        if not isinstance(raw, dict):
            raise ValueError("Envelope must be a JSON object")
        return raw


class AutoEnvelopeInterpreter(EnvelopeInterpreter):
    """
    If input is already JSON, parse locally. Otherwise use OpenAI interpreter.
    """

    def __init__(self, *, nl: EnvelopeInterpreter) -> None:
        self._nl = nl

    def interpret(self, text: str) -> dict[str, Any]:
        t = text.lstrip("\ufeff").strip()  # strip BOM if present
        if t.startswith("{"):
            try:
                raw = json.loads(t)
            except json.JSONDecodeError as e:
                raise ValueError(f"Invalid JSON envelope: {e}") from e
            if not isinstance(raw, dict):
                raise ValueError("Envelope JSON must be an object")
            return raw
        return self._nl.interpret(text)