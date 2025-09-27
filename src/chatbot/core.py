from __future__ import annotations

import base64
from functools import wraps
import json, redis
from types import SimpleNamespace
import os
import logging
from datetime import datetime, timedelta, UTC
from typing import Iterable, Sequence, Dict, Any, Optional, List, Tuple
from src.feeds.models import SportKey, MarketType, Period, Region
from src.feeds.webhook.boltodds_webhook import BoltOddsWebhookAdapter


import openai

from config.config import Config
from src.database import get_db_session
from src.database.models import User, UserSubscription
from src.database.session import get_user_by_phone
from src.messaging.base import BaseMessagingClient
from src.feeds.base import OddsFeed
from src.feeds.api.the_odds_api import TheOddsApiAdapter
from src.feeds.api.unabated_api import UnabatedApiAdapter
from src.feeds.models import Event, SportKey, MarketType, EventOdds
from src.analysis.base import AnalysisEngine
from src.feeds.query import FeedQuery
from src.feeds.models import Event, Competitor
from src.utils.utils import SubscriptionError, get_redis_client, require_subscription, standardize_phone_number


logger = logging.getLogger(__name__)

class ChatbotCore:
    """Coordinate messaging, odds feeds and analysis engines."""

    def __init__(
        self,
        platform: BaseMessagingClient,
        feeds: Optional[List[OddsFeed]],
        analysis_engines: Optional[Sequence[AnalysisEngine]] = None,
        openai_api_key: Optional[str] = None,
        model: str = Config.OPENAI_MODEL,
        product: Optional[Dict[str, str]] = None,
    ) -> None:
        self.platform = platform
        self.feeds = feeds
        self.main_feed = feeds[0]
        self.engines: list[AnalysisEngine] = list(analysis_engines or [])
        self.model = model
        fallback = Config.PRODUCTS.get('betting_assistant', {}).get('test', {})
        self.product_id  = (product or fallback).get('product_id', 'default')
        self.payment_url = (product or fallback).get('payment_url', 'oddsmate.ai')
        self.openai_api_key = openai_api_key or Config.OPENAI_API_KEY
        if self.openai_api_key:
            self.openai_client = openai.OpenAI(api_key=self.openai_api_key)
        else:
            self.openai_client = None
        # Responses API conversation tracking (simple)
        self.redis = get_redis_client()
        self.conversations: Dict[str, str] = {}  # chat_id -> conversation_id
        self.last_response_id: Dict[str, str] = {}  # chat_id -> last response id
        logger.debug("ChatbotCore initialized with %d analysis engines", len(self.engines))
        logger.debug("Active odds providers: %s", ", ".join([f.__class__.__name__ for f in self.feeds]))

    def add_engine(self, engine: AnalysisEngine) -> None:
        self.engines.append(engine)
        logger.debug("Added analysis engine: %s", engine.__class__.__name__)
        
    def start(self) -> None:
        """Register handlers and start the messaging platform."""
        # self.platform.register_command_handler("ask", self._handle_ask)
        # self.platform.register_command_handler("explain", self._handle_explain)
        self.platform.register_message_handler(lambda msg: True, self._handle_message)
        self.platform.start()

    # ------------------------------------------------------------------
    # OpenAI helpers
    # ------------------------------------------------------------------

    def _openai_tools(self):
        # Use your Pydantic v2 models
        FEEDQUERY_SCHEMA = FeedQuery.model_json_schema()
        FEEDQUERY_PARAMS = {
            "type": "object",
            "additionalProperties": True,
            "properties": FEEDQUERY_SCHEMA.get("properties", {}),
            "title": FEEDQUERY_SCHEMA.get("title", "FeedQuery"),
        }

        EMPTY_OBJ = {"type": "object", "properties": {}}

        GET_EVENT_ODDS_PARAMS = {
            "type": "object",
            "additionalProperties": True,
            "properties": {
                "event_id": {"type": "string"},
                "query": FEEDQUERY_SCHEMA,
            },
            "required": ["event_id"],
        }

        return [
            {
                "type": "function",
                "name": "list_sports",
                "description": "List supported sports (SportKey values).",
                "parameters": EMPTY_OBJ,
            },
            {
                "type": "function",
                "name": "list_bookmakers",
                "description": "List supported bookmakers.",
                "parameters": EMPTY_OBJ,
            },
            {
                "type": "function",
                "name": "list_markets",
                "description": "List markets; optionally scoped by sport.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "sport": {
                            "type": "string",
                            "description": "SportKey (e.g., 'basketball_nba')",
                        }
                    },
                },
            },
            {
                "type": "function",
                "name": "get_events",
                "description": "Find upcoming events matching the query (maps to feed.get_events_cached).",
                # Flattened FeedQuery (no 'query' wrapper)
                "parameters": FEEDQUERY_PARAMS,
            },
            {
                "type": "function",
                "name": "get_event_odds",
                "description": "Get odds for a single event (maps to feed.get_event_odds_cached).",
                "parameters": GET_EVENT_ODDS_PARAMS,
            },
            {
                "type": "function",
                "name": "get_odds",
                "description": "Get odds for many events matching the query (maps to feed.get_odds_cached).",
                # Flattened FeedQuery (no 'query' wrapper)
                "parameters": FEEDQUERY_PARAMS,
            },
        ]

    def run_turn(self, user_input: str, user_id: str, chat_id: str) -> str:
        conv_id = None

        if self.redis:
            try:
                session_data_raw = self.redis.get(f"session:{chat_id}")
                if session_data_raw:
                    session_data = json.loads(session_data_raw)
                    conv_id = session_data.get("conversation_id")
                    self.last_response_id[chat_id] = session_data.get("last_response_id")
            except Exception as e:
                logger.exception(f"Redis failed to retrieve session data for {chat_id}: {e}")
        else:
            conv_id = self.conversations.get(chat_id)

        # ---------- First request (user message) ----------
        create_args = dict(
            model=self.model,
            instructions=Config.SYSTEM_PROMPT,
            input=[{"role": "user", "content": [{"type": "input_text", "text": user_input}]}],
            tools=self._openai_tools(),
            tool_choice="auto",
        )
        if conv_id:
            create_args["conversation"] = conv_id

        # Log the exact model input payload (redact any obvious secrets if needed)
        try:
            safe_args = {k: v for k, v in create_args.items() if k not in {"openai_api_key"}}
            logger.debug("[model-input][first-turn] chat_id=%s conversation=%s payload=%s", chat_id, conv_id, json.dumps(safe_args, default=str)[:8000])
        except Exception:
            logger.exception("Failed to serialize model input for logging")

        # Log the outbound model request (truncated if huge)
        try:
            import copy as _copy, json as _json
            _safe_args = _copy.deepcopy(create_args)
            # Remove api key references implicitly via client (not in dict) and large tool schemas truncation
            tools_repr = []
            for t in _safe_args.get('tools', [])[:10]:  # cap
                tools_repr.append({k: (v if k != 'parameters' else '...schema omitted...') for k, v in t.items()})
            _safe_args['tools'] = tools_repr
            payload_txt = _json.dumps(_safe_args, default=str)
            if len(payload_txt) > 8000:
                payload_txt = payload_txt[:8000] + f"...TRUNCATED({len(payload_txt)} chars total)"  # keep log concise
            logger.debug("\n===== MODEL REQUEST (initial) chat_id=%s =====\n%s\n===== END MODEL REQUEST =====", chat_id, payload_txt)
        except Exception:
            logger.exception("Failed to log model request payload")

        resp = self.openai_client.responses.create(**create_args)
        self._debug_response("first", resp)

        # Save conversation if present
        if getattr(resp, "conversation", None) and getattr(resp.conversation, "id", None):
            self.conversations[chat_id] = resp.conversation.id

        # Always save response.id for bridging
        if not getattr(resp, "id", None):
            return "Error: server didn’t return a response id."
        self.last_response_id[chat_id] = resp.id

        if self.redis:
            try:
                session_data = {
                    "conversation_id": self.conversations.get(chat_id),
                    "last_response_id": self.last_response_id.get(chat_id)
                }
                self.redis.set(f"session:{chat_id}", json.dumps(session_data), ex=86400)
            except Exception as e:
                logger.exception(f"Redis failed to save session data for {chat_id}: {e}")

        # ---------- Tool loop ----------
        tool_calls = self.collect_tool_calls(resp)
        while tool_calls:
            # Execute ALL pending calls from *this* response
            pending_ids = [self._fc_id(fc) for fc in tool_calls]
            logger.debug(f"[tool-loop] pending function_call ids: {pending_ids}")
            results = [self.execute_tool_call(fc) for fc in tool_calls]
            result_ids = [r.get("call_id") for r in results]
            logger.debug(f"[tool-loop] produced outputs for call_ids: {result_ids}")

            # ------------------------------------------------------------------
            # Fallback: deep raw scan for ANY function/tool call ids that were not
            # captured by collect_tool_calls (SDK structural variance safeguard).
            # If we find additional ids, emit stub outputs so the API is satisfied
            # and log loudly for later forensic improvement.
            # ------------------------------------------------------------------
            try:
                raw_missing_ids = []
                try:
                    if hasattr(resp, "model_dump"):
                        raw_repr = resp.model_dump()
                    elif hasattr(resp, "to_dict"):
                        raw_repr = resp.to_dict()
                    else:
                        raw_repr = None
                except Exception:
                    raw_repr = None

                def _gather(o, out: set):
                    try:
                        if o is None:
                            return
                        if isinstance(o, dict):
                            otype = o.get("type")
                            cid = o.get("id") or o.get("call_id")
                            # Treat only genuine call_* ids; ignore placeholders and internal fc_ ids.
                            if (
                                (
                                    (otype in {"function_call", "tool_call"}) and cid and isinstance(cid, str) and cid.startswith("call_")
                                )
                                or (
                                    cid and isinstance(cid, str) and cid.startswith("call_") and (
                                        "arguments" in o or "function" in o or "name" in o
                                    )
                                )
                            ) and cid not in {"call_id"}:
                                out.add(cid)
                            for v in o.values():
                                _gather(v, out)
                            return
                        if isinstance(o, (list, tuple)):
                            for v in o:
                                _gather(v, out)
                            return
                        # object fallback
                        otype = getattr(o, "type", None)
                        cid = getattr(o, "id", None) or getattr(o, "call_id", None)
                        if (
                            (
                                (otype in {"function_call", "tool_call"}) and cid and isinstance(cid, str) and cid.startswith("call_")
                            )
                            or (
                                cid and isinstance(cid, str) and cid.startswith("call_") and hasattr(o, "arguments")
                            )
                        ) and cid not in {"call_id"}:
                            out.add(cid)
                        for attr in ("content", "output", "parts", "items"):
                            if hasattr(o, attr):
                                _gather(getattr(o, attr), out)
                    except Exception:
                        pass

                all_ids = set(pending_ids)
                if raw_repr is not None:
                    extra_ids = set()
                    _gather(raw_repr, extra_ids)
                    # Regex sweep over stringified payload to catch any orphan 'call_' ids that aren't structured
                    try:
                        import re, json as _json
                        payload_txt = _json.dumps(raw_repr, separators=(",", ":"))[:500000]  # cap size
                        regex_ids = set(re.findall(r'"(call_[A-Za-z0-9_]+)"', payload_txt))
                        for rid in regex_ids:
                            if rid not in extra_ids:
                                extra_ids.add(rid)
                    except Exception:
                        pass
                    raw_missing_ids = [
                        cid for cid in sorted(extra_ids)
                        if cid not in all_ids and isinstance(cid, str) and cid.startswith("call_") and cid not in {"call_id"}
                    ]
                if raw_missing_ids:
                    logger.error(
                        f"[tool-loop][raw-scan] Detected additional function_call ids not captured structurally: {raw_missing_ids}. Emitting filtered stub outputs."
                    )
                    for mid in raw_missing_ids:
                        results.append({"call_id": mid, "output": json.dumps({"warning": "raw_scan_stub_output", "note": "Call not captured structurally; investigate collect_tool_calls."})})
                        pending_ids.append(mid)
                # Update result_ids including stubs
                result_ids = [r.get("call_id") for r in results]
            except Exception:
                logger.exception("[tool-loop][raw-scan] fallback raw scan failed")

            # Backfill any missing outputs with an explicit error payload so API never complains
            missing = [pid for pid in pending_ids if pid not in result_ids]
            if missing:
                logger.error(f"[tool-loop] Missing outputs for call ids {missing}; generating stub error outputs.")
                for mid in missing:
                    results.append({"call_id": mid, "output": json.dumps({"error": "missing_execution_output"})})

            # Final safety: ensure no None call_id slips through
            filtered_results = []
            for r in results:
                cid = r.get("call_id")
                if not cid:
                    logger.error("[tool-loop] Dropping result without call_id (avoid fabricating).")
                    continue
                if not (isinstance(cid, str) and cid.startswith("call_") and cid not in {"call_id"}):
                    logger.debug(f"[tool-loop] Skipping non-call_* id from outputs: {cid}")
                    continue
                filtered_results.append(r)
            results = filtered_results

            follow_inputs = [
                {
                    "type": "function_call_output",
                    "call_id": r["call_id"],
                    "output": r["output"],
                }
                for r in results
            ]
            logger.debug(f"[tool-loop] sending function_call_output ids: {[fi['call_id'] for fi in follow_inputs]}")

            # Log follow-up model input (function_call_output bridging)
            try:
                logger.debug(
                    "[model-input][follow-up] chat_id=%s prev_resp=%s call_ids=%s payload=%s",
                    chat_id,
                    self.last_response_id[chat_id],
                    [fi['call_id'] for fi in follow_inputs],
                    json.dumps({"input": follow_inputs}, default=str)[:8000]
                )
            except Exception:
                logger.exception("Failed to serialize follow-up input for logging")

            # Log follow-up submission with function_call_output items
            try:
                import json as _json
                preview = [
                    {"call_id": fi['call_id'], "output_len": len(fi.get('output',''))}
                    for fi in follow_inputs
                ]
                logger.debug("===== MODEL FOLLOW-UP SUBMISSION chat_id=%s prev_resp=%s outputs=%s =====", chat_id, self.last_response_id[chat_id], preview)
            except Exception:
                logger.exception("Failed logging follow-up submission")

            follow = self.openai_client.responses.create(
                model=self.model,
                previous_response_id=self.last_response_id[chat_id],  # <-- point to the SAME response that issued those calls
                input=follow_inputs,
                tools=self._openai_tools(),  # keep tools available for additional calls
                tool_choice="auto",
                # NOTE: Do NOT pass conversation together with previous_response_id (mutually exclusive per API)
            )

            if getattr(follow, "id", None):
                self.last_response_id[chat_id] = follow.id
                if self.redis:
                    try:
                        session_data = {
                            "conversation_id": self.conversations.get(chat_id),
                            "last_response_id": self.last_response_id.get(chat_id)
                        }
                        self.redis.set(f"session:{chat_id}", json.dumps(session_data), ex=86400)
                    except Exception as e:
                        logger.exception(f"Redis failed to save session data for {chat_id}: {e}")
            resp = follow
            tool_calls = self.collect_tool_calls(resp)


        # ---------- Final text ----------
        return resp.output_text or "Error: No response generated."



    def _debug_response(self, tag, resp):
        try:
            items = getattr(resp, "output", None) or []
            fcs = [it for it in items if getattr(it, "type", None) == "function_call"]
            logger.debug(
                f"[{tag}] conv={getattr(getattr(resp,'conversation',None),'id',None)} "
                f"resp_id={getattr(resp,'id',None)} "
                f"output_text={getattr(resp,'output_text',None)!r} "
                f"tool_calls={[getattr(fc,'id',None) for fc in fcs]} "
                f"raw_types={[getattr(it,'type',None) for it in items]}"
            )
        except Exception:
            logger.exception(f"[{tag}] debug failed")

    def collect_tool_calls(self, response) -> list:
        """Return only function_call items requiring outputs.
        Some SDKs also expose tool_call items; we ignore those for bridging because
        the Responses API expects outputs strictly for function_call ids."""
        items = getattr(response, "output", None) or []
        flat_calls = []
        nested_calls = []
        deep_calls = []  # captured via recursive structural traversal (may duplicate)

        # Helper to register a call if not already present (dedupe by id)
        def _add_call(obj, origin: str):
            cid = getattr(obj, "id", None) or getattr(obj, "call_id", None)
            ctype = getattr(obj, "type", None)
            if ctype not in {"function_call", "tool_call"}:
                return
            # Avoid duplicates (some SDK objects may appear both top-level and nested)
            existing_ids = {getattr(c, "id", None) or getattr(c, "call_id", None) for c in flat_calls + nested_calls}
            if cid and cid in existing_ids:
                return
            (flat_calls if origin == "top" else nested_calls).append(obj)

        # Top-level scan
        for it in items:
            _add_call(it, "top")
            # Dive into .content for nested parts (SDK dependent)
            content = getattr(it, "content", None)
            if isinstance(content, list):
                for part in content:
                    _add_call(part, "nested")

        # Deep recursive scan through dict / object graph as a safety net.
        # This addresses any missed calls nested more than one level deep
        # (some SDK variants may embed calls inside message.content elements).
        visited_ids = set()

        def _extract(obj):
            try:
                if obj is None:
                    return
                # Handle primitive containers
                if isinstance(obj, (str, int, float, bool)):
                    return
                # If dict-like
                if isinstance(obj, dict):
                    otype = obj.get("type")
                    cid = obj.get("id") or obj.get("call_id")
                    if otype in {"function_call", "tool_call"} and cid and cid not in visited_ids:
                        deep_calls.append(obj)
                        visited_ids.add(cid)
                    for v in obj.values():
                        _extract(v)
                    return
                # If list/tuple
                if isinstance(obj, (list, tuple)):
                    for v in obj:
                        _extract(v)
                    return
                # Fallback: generic object introspection
                otype = getattr(obj, "type", None)
                cid = getattr(obj, "id", None) or getattr(obj, "call_id", None)
                if otype in {"function_call", "tool_call"} and cid and cid not in visited_ids:
                    deep_calls.append(obj)
                    visited_ids.add(cid)
                # Recurse into common container-ish attributes
                for attr in ("content", "output", "parts", "items"):
                    if hasattr(obj, attr):
                        _extract(getattr(obj, attr))
            except Exception:
                # Never let diagnostics traversal break main flow
                pass

        # Attempt to serialize response to dict if possible for broader traversal
        raw_dict = None
        try:
            if hasattr(response, "model_dump"):
                raw_dict = response.model_dump()
            elif hasattr(response, "to_dict"):
                raw_dict = response.to_dict()
        except Exception:
            raw_dict = None

        _extract(items)
        if raw_dict:
            _extract(raw_dict)

        # Merge deep_calls into primary call list (ensuring no duplicates)
        existing_ids = {getattr(c, 'id', None) or getattr(c, 'call_id', None) for c in flat_calls + nested_calls}
        for dc in deep_calls:
            cid = dc.get("id") if isinstance(dc, dict) else (getattr(dc, 'id', None) or getattr(dc, 'call_id', None))
            if not cid or cid in existing_ids:
                continue
            # Represent dict deep call as a simple lightweight shim object for uniform downstream handling
            if isinstance(dc, dict):
                # Create a minimal shim with attribute access
                class _Shim:  # local ephemeral
                    def __init__(self, d):
                        self.__dict__.update(d)
                dc_obj = _Shim(dc)
            else:
                dc_obj = dc
            nested_calls.append(dc_obj)
            existing_ids.add(cid)

        calls = flat_calls + nested_calls

        if calls:
            logger.debug(
                "[collect_tool_calls] captured %d calls (top=%d nested=%d deep_extra=%d) -> ids=%s types=%s all_output_types=%s deep_only_ids=%s", 
                len(calls), len(flat_calls), len(nested_calls), len(deep_calls),
                [getattr(c, 'id', None) or getattr(c, 'call_id', None) for c in calls],
                [getattr(c, 'type', None) for c in calls],
                [getattr(it, 'type', None) for it in items],
                [ (dc.get('id') if isinstance(dc, dict) else (getattr(dc,'id',None) or getattr(dc,'call_id',None))) for dc in deep_calls ]
            )
        else:
            logger.debug(
                "[collect_tool_calls] no callable items found. output_types=%s raw_item_reprs_sample=%s", 
                [getattr(it, 'type', None) for it in items],
                [repr(items[i])[:120] for i in range(min(3, len(items)))]
            )
        return calls

    def _fc_id(self, fc):
        """Return the externally valid function_call id (call_*), never the internal fc_* id.

        Some SDK objects expose both an internal id (fc_...) and the actual call id (call_...).
        The Responses API expects we echo back the call_* identifier. This function attempts
        multiple extraction strategies before falling back. If we can't find a call_* id we
        return whatever exists so upstream logging can surface the anomaly, but downstream
        filtering will drop non-call_* outputs and the raw scan will still attempt stubs.
        """
        try:
            # First try model_dump for a stable dict view
            if hasattr(fc, "model_dump"):
                d = fc.model_dump()
                for key in ("call_id", "id"):
                    cid = d.get(key)
                    if isinstance(cid, str) and cid.startswith("call_"):
                        return cid
                # Fallback: scan values for a call_* token
                for v in d.values():
                    if isinstance(v, str) and v.startswith("call_"):
                        return v
        except Exception:
            pass
        # Attribute access preference: call_id over id
        cid_attr = getattr(fc, "call_id", None)
        if isinstance(cid_attr, str) and cid_attr.startswith("call_"):
            return cid_attr
        id_attr = getattr(fc, "id", None)
        if isinstance(id_attr, str) and id_attr.startswith("call_"):
            return id_attr
        # Last resort: return whichever exists (likely fc_*) for logging/diagnostics
        return cid_attr or id_attr

    def _fc_name(self, fc):
        return getattr(fc, "name", None) or getattr(getattr(fc, "function", None), "name", None)

    def _fc_args(self, fc):
        raw = getattr(fc, "arguments", None) or getattr(getattr(fc, "function", None), "arguments", None)
        import json
        return json.loads(raw or "{}")
    
    def pack_json(self, data: Any) -> str:
        """Always return a JSON string (no truncation; pagination keeps payloads small)."""
        return json.dumps(data, ensure_ascii=False)

    def pack_json_with_guard(self, data: Any, *, char_limit: Optional[int] = None) -> str:
        """Optional safety guard if you still want a hard cap."""
        limit = char_limit or getattr(Config, "MAX_TOOL_OUTPUT_CHARS", 45000)
        raw = json.dumps(data, ensure_ascii=False)
        if len(raw) <= limit:
            return raw
        # Fallback wrapper if someone disables pagination by mistake
        safe = {
            "data_prefix": raw[:limit],
            "meta": {
                "truncated": True,
                "original_length": len(raw),
                "kept": limit,
                "note": "Payload exceeded limit; enable/use pagination."
            }
        }
        return json.dumps(safe, ensure_ascii=False)

    def _b64e(self, d: Dict[str, Any]) -> str:
        return base64.urlsafe_b64encode(json.dumps(d).encode("utf-8")).decode("ascii")

    def _b64d(self, s: str) -> Dict[str, Any]:
        return json.loads(base64.urlsafe_b64decode(s.encode("ascii")).decode("utf-8"))

    def _parse_pagination_args(self, args: Dict[str, Any]) -> Tuple[int, Optional[Dict[str, Any]]]:
        limit = int(args.get("limit") or 1000)
        limit = max(1, min(limit, getattr(Config, "MAX_PAGE_SIZE", 2000)))  # clamp
        cursor = args.get("cursor")
        state = self._b64d(cursor) if cursor else None
        return limit, state

    def _slice_with_cursor(self, seq: List[Any], limit: int, state: Optional[Dict[str, Any]]) -> Tuple[List[Any], Optional[str]]:
        """Generic cursor over an in-memory list. Cursor stores the next start index."""
        start = int(state.get("pos", 0)) if state else 0
        end = start + limit
        items = seq[start:end]
        next_cursor = None
        if end < len(seq):
            next_cursor = self._b64e({"pos": end})
        return items, next_cursor

    def _page_dict(self, items: List[Any], next_cursor: Optional[str]) -> Dict[str, Any]:
        return {"items": items, "next": next_cursor}
    
    def execute_tool_call(self, fc) -> dict:
        """Execute a single function_call item with cursor-based pagination."""
        feed = self.main_feed
        call_id = self._fc_id(fc)
        name = self._fc_name(fc)
        try:
            args = self._fc_args(fc)
        except Exception as e:
            logger.exception(f"Failed to parse arguments for call {call_id}: {e}")
            return {"call_id": call_id or "unknown_call", "output": self.pack_json({"error": f"arg_parse_failed: {e}"})}

        if not call_id:
            logger.error(f"Function call missing id/name={name} - cannot safely bridge; sending placeholder.")

        try:
            # ---- get_odds (paged) ----
            if name == "get_odds":
                q = FeedQuery.model_validate(self._normalize_feedquery_args(args))
                limit, state = self._parse_pagination_args(args)

                # If your feed supports native paging, use it (preferred)
                if hasattr(feed, "get_odds_paged"):
                    rows, next_state = feed.get_odds_paged(q, limit=limit, cursor_state=state)
                    out = self._page_dict([eo.model_dump() for eo in (rows or [])], self._b64e(next_state) if next_state else None)
                    return {"call_id": call_id, "output": self.pack_json(out)}

                # Fallback: fetch then slice (works today; swap to native when ready)
                eos = feed.get_odds_cached(q) or []
                items, next_cur = self._slice_with_cursor([eo.model_dump() for eo in eos], limit, state)
                return {"call_id": call_id, "output": self.pack_json(self._page_dict(items, next_cur))}

            # ---- get_events (paged) ----
            if name == "get_events":
                q = FeedQuery.model_validate(self._normalize_feedquery_args(args))
                limit, state = self._parse_pagination_args(args)

                if hasattr(feed, "get_events_paged"):
                    rows, next_state = feed.get_events_paged(q, limit=limit, cursor_state=state)
                    out = self._page_dict([e.model_dump() for e in (rows or [])], self._b64e(next_state) if next_state else None)
                    return {"call_id": call_id, "output": self.pack_json(out)}

                events = feed.get_events_cached(q) or []
                items, next_cur = self._slice_with_cursor([e.model_dump() for e in events], limit, state)
                return {"call_id": call_id, "output": self.pack_json(self._page_dict(items, next_cur))}

            # ---- get_event_odds (paged within a big object) ----
            if name == "get_event_odds":
                event_id = args.get("event_id")
                if not event_id:
                    raise ValueError("event_id required")

                q_raw = args.get("query", {}) or {}
                q = FeedQuery.model_validate(self._normalize_feedquery_args(q_raw))
                limit, state = self._parse_pagination_args(args)

                # first we constuct a minimal event object from the id and the sport in q
                event = self._event_from_minimal({"event_id": event_id, "sport_key": q.sports[0]})


                # If feed supports native paging for event odds, prefer it
                if hasattr(feed, "get_event_odds_paged"):
                    rows, next_state = feed.get_event_odds_paged(event, q, limit=limit, cursor_state=state)
                    out = self._page_dict([r.model_dump() if hasattr(r, "model_dump") else r for r in (rows or [])],
                                    self._b64e(next_state) if next_state else None)
                    return {"call_id": call_id, "output": self.pack_json(out)}

                # Fallback: paginate a large odds object by its list fields (e.g., prices)
                eo = feed.get_event_odds_cached(event, q)
                d = eo.model_dump()

                # Try the common large fields in order; first one found gets paginated.
                list_fields = ["prices", "bookmakers", "markets", "outcomes"]
                paged_field = next((f for f in list_fields if isinstance(d.get(f), list)), None)

                if paged_field:
                    items, next_cur = self._slice_with_cursor(d[paged_field], limit, state)
                    d[paged_field] = items
                    out = {"item": d, "next": next_cur}
                else:
                    # Nothing large to paginate; return as single item
                    out = {"item": d, "next": None}

                return {"call_id": call_id, "output": self.pack_json(out)}

            # ---- list_bookmakers (tiny; no paging needed, but allow it for consistency) ----
            if name == "list_bookmakers":
                limit, state = self._parse_pagination_args(args)
                arr = [getattr(b, "value", str(b)) for b in (feed.list_bookmakers() or [])]
                items, next_cur = self._slice_with_cursor(arr, limit, state)
                return {"call_id": call_id, "output": self.pack_json(self._page_dict(items, next_cur))}

            # ---- list_markets (optional paging) ----
            if name == "list_markets":
                sport = args.get("sport")
                sport_enum = SportKey(sport) if sport else None
                limit, state = self._parse_pagination_args(args)
                arr = [m.value for m in feed.list_markets(sport_enum)]
                items, next_cur = self._slice_with_cursor(arr, limit, state)
                return {"call_id": call_id, "output": self.pack_json(self._page_dict(items, next_cur))}

            # ---- list_sports (optional paging) ----
            if name == "list_sports":
                limit, state = self._parse_pagination_args(args)
                arr = [s.value for s in (feed.list_sports() or [])]
                items, next_cur = self._slice_with_cursor(arr, limit, state)
                return {"call_id": call_id, "output": self.pack_json(self._page_dict(items, next_cur))}

            return {"call_id": call_id, "output": self.pack_json({"error": f"Unknown tool {name}"})}

        except Exception as e:
            logger.exception(f"Tool execution failed for {name} ({call_id}): {e}")
            return {"call_id": call_id, "output": self.pack_json({"error": f"execution_failed: {str(e)}"})}

    def _event_from_minimal(self, ev: Dict[str, Any]):
        """Option A: re-fetch by id; Option B: construct a thin Event object your adapter accepts."""
        # simplest: try by id
        try:
            q = FeedQuery(event_ids=[ev["event_id"]], limit=1)
            found = self.main_feed.get_events_cached(q) or []
            if found:
                return found[0]
        except Exception:
            pass
        return Event(
            event_id=ev["event_id"],
            sport_key=SportKey(ev["sport_key"]),
            start_time=ev.get("start_time"),
            status=ev.get("status"),
            competitors=[Competitor(name=ev.get("home","TBD"), role="home"),
                        Competitor(name=ev.get("away","TBD"), role="away")],
            league=ev.get("league")
        )
    
    def _coerce_enum(self, val, EnumCls, mapping: dict[str, str] | None = None):
        """Try to coerce val to EnumCls. Accepts existing enums, their value strings,
        and optional alias mapping ('NFL' -> 'americanfootball_nfl')."""
        if val is None:
            return None
        if isinstance(val, EnumCls):
            return val
        s = str(val).strip()
        if mapping and s in mapping:
            s = mapping[s]
        try:
            return EnumCls(s)  # works with exact .value strings
        except Exception:
            # also try name lookup (e.g., 'H2H' -> MarketType.H2H)
            try:
                return EnumCls[s]  # type: ignore[index]
            except Exception:
                raise TypeError(f"Cannot coerce {val!r} to {EnumCls.__name__}")

    def _coerce_list(self, seq, fn):
        if not seq:
            return seq
        return [fn(v) for v in seq]

    def _normalize_feedquery_args(self, args: dict) -> dict:
        """Coerce tool-call args into proper enums expected by FeedQuery & adapters."""

        # Accept some common aliases (you can add more as needed)
        sport_alias = {
            "NFL": SportKey.NFL.value,
            "NCAAF": SportKey.NCAAF.value,
            "NBA": SportKey.NBA.value,
            "NCAAB": SportKey.NCAAB.value,
            "WNBA": SportKey.WNBA.value,
            "MLB": SportKey.MLB.value,
            "NHL": SportKey.NHL.value,
            "MMA": SportKey.MMA.value,
            "SOCCER": SportKey.FOOTBALL.value,
            "FOOTBALL": SportKey.FOOTBALL.value,
            "BOXING": SportKey.BOXING.value,
            "TENNIS": SportKey.TENNIS.value,
        }

        out = dict(args or {})

        # Coerce sports/markets/periods/regions
        if "sports" in out and out["sports"] is not None:
            out["sports"] = self._coerce_list(
                out["sports"], lambda v: self._coerce_enum(v, SportKey, sport_alias)
            )
        if "markets" in out and out["markets"] is not None:
            out["markets"] = self._coerce_list(
                out["markets"], lambda v: self._coerce_enum(v, MarketType)
            )
        if "periods" in out and out["periods"] is not None:
            out["periods"] = self._coerce_list(
                out["periods"], lambda v: self._coerce_enum(v, Period)
            )
        if "regions" in out and out["regions"] is not None:
            out["regions"] = self._coerce_list(
                out["regions"], lambda v: self._coerce_enum(v, Region)
            )

        # event_ids/teams/players/bookmakers can remain strings
        return out
    
    # ------------------------------------------------------------------
    # Messaging platform integration
    # ------------------------------------------------------------------
    
    async def _handle_message(self, update, context) -> None:
        """Handle general messages."""
        text = update.message.text.strip() or ""
        chat_id = str(update.effective_chat.id)
        user = None

        with get_db_session() as db:
            standardized_phone = standardize_phone_number(chat_id)
            user = db.query(User).filter(User.phone == standardized_phone).first()

        if not user:
            logger.warning("Could not find user")
            await self.platform.send_message(chat_id, f"Sorry, I couldn't identify your account. Purchase a subscription here: {self.payment_url}")
            return
        print(user)
        if not user:
            logger.warning(f"Could not find user")
            await self.platform.send_message(chat_id, f"Sorry, I couldn't identify your account. Purchase a subscription here: {self.payment_url}")
            return
        user_id = str(user.id)
        active_subscription = db.query(UserSubscription).filter(UserSubscription.user_id == user.id, UserSubscription.active == True, UserSubscription.product_id == self.product_id).first()
        if not active_subscription:
            raise SubscriptionError(f"User {user_id} does not have an active subscription. Please visit {self.payment_url} to subscribe.")
        try:
            answer = self.run_turn(text, user_id=user_id, chat_id=chat_id)
            await self.platform.send_message(chat_id, answer)
        except SubscriptionError as e:
            logger.info(f"Subscription error for user {user_id}: {e}")
            subscribe_message = (
                "It looks like your subscription has expired or is inactive. "
                f"Please renew or subscribe here: {self.payment_url}"
            )
            await self.platform.send_message(chat_id, subscribe_message)
        except Exception as e:
            logger.exception(f"Error processing message from user {user_id}: {e}")
            await self.platform.send_message(chat_id, "Sorry, something went wrong while processing your request.")