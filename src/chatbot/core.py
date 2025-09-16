from __future__ import annotations

from functools import wraps
import json, redis
from types import SimpleNamespace
import os
import logging
from datetime import datetime, timedelta, UTC
from typing import Iterable, Sequence, Dict, Any, Optional, List

import openai

from config.config import Config
from src.database import get_db_session
from src.database.models import UserSubscription
from src.database.session import get_user_by_phone
from src.messaging.base import BaseMessagingClient
from src.feeds.base import OddsFeed
from src.feeds.api.the_odds_api import TheOddsApiAdapter
from src.feeds.api.unabated_api import UnabatedApiAdapter
from src.feeds.models import Event, SportKey, MarketType, EventOdds
from src.analysis.base import AnalysisEngine
from src.feeds.query import FeedQuery
from src.feeds.models import Event, Competitor


logger = logging.getLogger(__name__)

def require_subscription(fn):
    @wraps(fn)
    async def wrapper(self, update, context):
        # 1. Get the unique chat identifier from the messaging platform.
        # This works for the mock client, Telegram (integer ID), and iMessage (phone number).
        chat_id = getattr(update.effective_chat, "id", None) or getattr(update, "chat_id", None)
        if not chat_id:
            logger.warning("Could not determine chat_id from update.")
            return

        db = next(get_db_session())
        try:
            # 2. Find the user record using the chat_id.
            user = get_user_by_phone(db, chat_id)

            # 3. Check if the user exists and has a phone number registered.
            if not user or not user.phone:
                await self.platform.send_message(
                    chat_id,
                    "Your account is not fully set up. Please register your phone number on our website to continue."
                )
                return

            # 4. Check for a specific, active subscription for that user.
            active_subscription = db.query(UserSubscription).filter(
                UserSubscription.user_id == user.id,
                UserSubscription.active == True,
                UserSubscription.product_id == self.product_id
            ).first()

            if not active_subscription:
                await self.platform.send_message(
                    chat_id,
                    "🚫 You don't have an active subscription for this service. Please visit our website to subscribe."
                )
                return

            # 5. If all checks pass, proceed to the original handler.
            return await fn(self, update, context)
        finally:
            db.close()
    return wrapper

class ChatbotCore:
    """Coordinate messaging, odds feeds and analysis engines."""

    def __init__(
        self,
        platform: BaseMessagingClient,
        provider_names: Optional[str] = Config.ACTIVE_ODDS_PROVIDERS,
        analysis_engines: Optional[Sequence[AnalysisEngine]] = None,
        openai_api_key: Optional[str] = None,
        model: str = Config.OPENAI_MODEL,
        product_id: Optional[str] = None
    ) -> None:
        self.platform = platform
        self.provider_names = provider_names
        self.feeds = [self.create_feed_adapter(name) for name in (provider_names if isinstance(provider_names, list) else [provider_names])]
        self.main_feed = self.feeds[0] if self.feeds else self.create_feed_adapter("unabated")
        self.engines: list[AnalysisEngine] = list(analysis_engines or [])
        self.model = model
        self.product_id = product_id or Config.PRODUCT_IDS.get('betting_assistant', {}).get('test', 'default')
        self.openai_api_key = openai_api_key or Config.OPENAI_API_KEY
        if self.openai_api_key:
            self.openai_client = openai.OpenAI(api_key=self.openai_api_key)
        else:
            self.openai_client = None
        # Responses API conversation tracking (simple)
        self.conversations: Dict[str, str] = {}  # chat_id -> conversation_id
        self.last_response_id: Dict[str, str] = {}  # chat_id -> last response id
        logger.debug("ChatbotCore initialized with %d analysis engines", len(self.engines))
        logger.debug("Active odds providers: %s", ", ".join([f.__class__.__name__ for f in self.feeds]))

    def create_feed_adapter(self, name: str) -> OddsFeed:
        if name == "theoddsapi":
            return TheOddsApiAdapter()
        elif name == "unabated":
            return UnabatedApiAdapter()
        else:
            raise ValueError(f"Unknown odds provider: {name}")

    def add_engine(self, engine: AnalysisEngine) -> None:
        self.engines.append(engine)
        logger.debug("Added analysis engine: %s", engine.__class__.__name__)

    # ------------------------------------------------------------------
    # OpenAI helpers
    # ------------------------------------------------------------------

    def _debug_response(self, tag, resp):
        """Unified debug helper (single implementation)."""
        try:
            items = getattr(resp, "output", None) or []
            fcs = [it for it in items if getattr(it, "type", None) == "function_call"]
            logger.debug(
                f"[{tag}] conv={getattr(getattr(resp,'conversation',None),'id',None)} "
                f"resp_id={getattr(resp,'id',None)} "
                f"output_text={getattr(resp,'output_text',None)!r} "
                f"function_calls={[getattr(fc,'id',None) or getattr(fc,'call_id',None) for fc in fcs]} "
                f"raw_types={[getattr(it,'type',None) for it in items]}"
            )
        except Exception:
            logger.exception(f"[{tag}] debug failed")


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
                "description": "Find upcoming events matching the query (maps to feed.get_events).",
                # Flattened FeedQuery (no 'query' wrapper)
                "parameters": FEEDQUERY_PARAMS,
            },
            {
                "type": "function",
                "name": "get_event_odds",
                "description": "Get odds for a single event (maps to feed.get_event_odds).",
                "parameters": GET_EVENT_ODDS_PARAMS,
            },
            {
                "type": "function",
                "name": "get_odds",
                "description": "Get odds for many events matching the query (maps to feed.get_odds).",
                # Flattened FeedQuery (no 'query' wrapper)
                "parameters": FEEDQUERY_PARAMS,
            },
        ]

    
    def run_turn(self, user_input: str, chat_id: str) -> str:
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


    def create_responses(self, **kwargs):
        return self.openai_client.responses.create(**kwargs)
    
    def execute_tool_call(self, fc) -> dict:
        """Execute a single function_call item safely, always returning an output.

        Guarantees returning a mapping with the original call_id so the
        Responses API never complains about missing tool outputs."""
        feed = self.main_feed
        call_id = self._fc_id(fc)
        name = self._fc_name(fc)
        try:
            args = self._fc_args(fc)
        except Exception as e:
            logger.exception(f"Failed to parse arguments for call {call_id}: {e}")
            return {"call_id": call_id or "unknown_call", "output": json.dumps({"error": f"arg_parse_failed: {e}"})}

        # Safety: ensure we have a call_id; if not, fabricate one (still won't match server's expectation,
        # but we log loudly so we can debug rather than silently sending None)
        if not call_id:
            logger.error(f"Function call missing id/name={name} - cannot safely bridge; sending placeholder.")
        try:
            # Helper to serialize and truncate large outputs
            def _pack(data):
                raw = json.dumps(data)
                limit = getattr(Config, "MAX_TOOL_OUTPUT_CHARS", 45000)
                if len(raw) > limit:
                    truncated = raw[:limit]
                    meta_suffix = json.dumps({
                        "truncated": True,
                        "original_length": len(raw),
                        "kept": limit,
                        "note": "Output truncated to fit context window. Adjust query (narrow markets/events) for full data."
                    })
                    # Ensure JSON remains valid: wrap truncated string with metadata
                    safe = json.dumps({"data_prefix": truncated, "meta": json.loads(meta_suffix)})
                    return safe
                return raw

            if name == "get_odds":
                q = FeedQuery.model_validate(self._normalize_feedquery_args(args))
                eos = feed.get_odds(q) or []
                out = [eo.model_dump() for eo in eos]
                return {"call_id": call_id, "output": _pack(out)}

            if name == "get_events":
                q = FeedQuery.model_validate(self._normalize_feedquery_args(args))
                events = feed.get_events(q) or []
                out = [e.model_dump() for e in events]
                return {"call_id": call_id, "output": _pack(out)}

            if name == "get_event_odds":
                event_id = args.get("event_id")
                if not event_id:
                    raise ValueError("event_id required")
                q_raw = args.get("query", {}) or {}
                q = FeedQuery.model_validate(self._normalize_feedquery_args(q_raw))
                event = self._get_event_by_id(event_id)
                eo = feed.get_event_odds(event, q)
                out = eo.model_dump()
                return {"call_id": call_id, "output": _pack(out)}

            if name == "list_bookmakers":
                out = [getattr(b, "value", str(b)) for b in (feed.list_bookmakers() or [])]
                return {"call_id": call_id, "output": _pack(out)}

            if name == "list_markets":
                sport = args.get("sport")
                sport_enum = SportKey(sport) if sport else None
                out = [m.value for m in feed.list_markets(sport_enum)]
                return {"call_id": call_id, "output": _pack(out)}

            if name == "list_sports":
                out = [s.value for s in (feed.list_sports() or [])]
                return {"call_id": call_id, "output": _pack(out)}

            return {"call_id": call_id, "output": json.dumps({"error": f"Unknown tool {name}"})}
        except Exception as e:
            logger.exception(f"Tool execution failed for {name} ({call_id}): {e}")
            return {"call_id": call_id, "output": json.dumps({"error": f"execution_failed: {str(e)}"})}


    def _event_from_minimal(self, ev: Dict[str, Any]):
        """Option A: re-fetch by id; Option B: construct a thin Event object your adapter accepts."""
        # simplest: try by id
        try:
            q = FeedQuery(event_ids=[ev["event_id"]], limit=1)
            found = self.main_feed.get_events(q) or []
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
        from src.feeds.models import SportKey, MarketType, Period, Region

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


    def ask_question(self, question: str, chat_id: Optional[str] = None) -> str:
        """Ask a question with conversation context."""
        chat_id = chat_id or "default"
        
        if not self.openai_client:
            # Fallback to smart odds if no AI
            try:
                return self.get_smart_odds(question)
            except Exception as e:
                return f"Error: {e}"
        
        # Get odds context if relevant
        odds_context = ""
        try:
            if any(word in question.lower() for word in ["odds", "picks", "bets", "spread", "total", "moneyline"]):
                odds_context = self.get_smart_odds(question)
        except Exception as e:
            logger.warning(f"Failed to get odds context: {e}")
        
        # Prepare input with context
        full_question = f"{question}\n\nOdds Context:\n{odds_context}" if odds_context else question
        
        # Simple conversation history management
        if not hasattr(self, '_manual_history'):
            self._manual_history = {}
        if chat_id not in self._manual_history:
            self._manual_history[chat_id] = []
        
        # Add current question to history
        self._manual_history[chat_id].append({"role": "user", "content": full_question})
        
        # Keep only last 10 messages for context
        messages = self._manual_history[chat_id][-10:]
        
        try:
            # Use Chat Completions API with conversation history
            response = self.openai_client.responses.create(
                model=self.model,
                instructions=Config.SYSTEM_PROMPT,
                messages=messages,
                tools=self._openai_tools(),
                tool_choice="auto"
            )
            
            # Handle response
            message = response.choices[0].message
            
            # Handle tool calls
            if message.tool_calls:
                result = self._handle_tool_calls(message.tool_calls)
                self._manual_history[chat_id].append({"role": "assistant", "content": result})
                return result
            
            content = message.content.strip() if message.content else "No response generated."
            self._manual_history[chat_id].append({"role": "assistant", "content": content})
            return content
            
        except Exception as e:
            logger.error(f"OpenAI API error: {e}")
            # Fallback to odds context if available
            return odds_context or f"Error: {e}"

    def _handle_tool_calls(self, tool_calls):
        """Handle tool calls from OpenAI response."""
        for tool_call in tool_calls:
            function = tool_call.function
            if function.name == "best_picks":
                try:
                    args = json.loads(function.arguments or "{}")
                    return self.get_smart_odds("best picks", hours=args.get("hours", 24))
                except Exception as e:
                    logger.error(f"Error in best_picks tool: {e}")
                    return f"Error getting best picks: {e}"
            elif function.name == "build_parlay":
                return "Sorry, parlay building is not yet supported with the new feed system."
        
        return "Tool call completed"

    def explain_line(self, line_desc: str) -> str:
        """Ask OpenAI to explain a betting line."""
        prompt = f"Explain the following betting line in simple terms: {line_desc}"
        if not self.openai_api_key:
            logger.warning("OpenAI API key not configured")
            return "OpenAI API key not configured."
        resp = self.openai_client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
        )
        if not resp.choices:
            logger.warning("OpenAI API returned an empty choices array for line description: %s", line_desc)
            return "I'm sorry, I couldn't generate an explanation for the given line."
        explanation = resp.choices[0].message.content.strip()
        logger.debug("OpenAI explanation: %s", explanation)
        return explanation

    # ------------------------------------------------------------------
    # Messaging integration
    # ------------------------------------------------------------------

    @require_subscription
    async def _handle_ask(self, update, context) -> None:  # pragma: no cover - Telegram interface
        question = " ".join(getattr(context, "args", []) or [])
        if not question:
            await self.platform.send_message(update.effective_chat.id, "Please provide a question after /ask")
            return
        chat_id = str(update.effective_chat.id)
        answer = self.ask_question(question, chat_id=chat_id)
        await self.platform.send_message(update.effective_chat.id, answer)

    @require_subscription
    async def _handle_explain(self, update, context) -> None:  # pragma: no cover - Telegram interface
        desc = " ".join(getattr(context, "args", []) or [])
        if not desc:
            await self.platform.send_message(update.effective_chat.id, "Provide a line description after /explain")
            return
        explanation = self.explain_line(desc)
        await self.platform.send_message(update.effective_chat.id, explanation)
    
    @require_subscription
    async def _handle_message(self, update, context) -> None:
        """Handle general messages."""
        text = update.message.text.strip() or ""
        chat_id = str(update.effective_chat.id)
        answer = self.run_turn(text, chat_id)
        await self.platform.send_message(update.effective_chat.id, answer)

    def reset_conversation(self, chat_id: str):
        """Reset conversation context for a specific chat."""
        self.conversations.pop(chat_id, None)
        if hasattr(self, '_manual_history'):
            self._manual_history.pop(chat_id, None)
        logger.info(f"Reset conversation for chat_id: {chat_id}")

    # ------------------------------------------------------------------
    # AI-Powered Smart Query Building
    # ------------------------------------------------------------------
    
    def _analyze_query_with_ai(self, question: str) -> Dict[str, Any]:
        """
        Use AI to comprehensively analyze a user query and extract all betting intent.
        Returns structured data about sports, teams, players, markets, timing, etc.
        """
        if not self.openai_client:
            logger.warning("OpenAI client not available, falling back to basic parsing")
            return self._fallback_query_analysis(question)
        
        try:
            system_prompt = """You are an expert sports betting query analyzer with comprehensive knowledge of ALL team names, nicknames, abbreviations, and variations across ALL sports.

Return a JSON object with these fields:
{
  "sports": ["NBA", "NFL", "MLB", "NHL", "NCAAF", "NCAAB", "WNBA", "MMA", "FOOTBALL", "BOXING", "TENNIS"],
  "teams": ["NORMALIZED full team names"],
  "players": ["full player names"], 
  "markets": ["H2H", "SPREAD", "TOTAL", "PLAYER_PROPS"],
  "timeframe": {
    "type": "tonight|today|tomorrow|weekend|week|specific_date|general",
    "hours": 24,
    "description": "human readable time description"
  },
  "intent": "general_picks|team_specific|player_props|market_specific|analysis",
  "confidence": 0.95
}

CRITICAL: For teams, ALWAYS return the FULL OFFICIAL NAME that would appear in betting APIs:
- "Lakers", "LAL", "LA" → "Los Angeles Lakers"
- "Warriors", "GSW", "Dubs" → "Golden State Warriors"  
- "Knicks", "NYK" → "New York Knicks"
- "Sixers", "76ers" → "Philadelphia 76ers"
- "Cavs" → "Cleveland Cavaliers"
- "Bucs" → "Tampa Bay Buccaneers"
- "Chiefs", "KC" → "Kansas City Chiefs"
- "Pats" → "New England Patriots"
- "Dodgers", "LAD" → "Los Angeles Dodgers"
- "Yankees", "NYY" → "New York Yankees"
- "Sox" (context needed) → "Boston Red Sox" or "Chicago White Sox"

Handle ALL possible team variations intelligently. You know every team in every major sport.

Examples:
- "Lakers odds tonight" → teams:["Los Angeles Lakers"], sports:["NBA"]
- "Dubs spread" → teams:["Golden State Warriors"], sports:["NBA"], markets:["SPREAD"]
- "KC Chiefs this weekend" → teams:["Kansas City Chiefs"], sports:["NFL"]
- "Pats vs Bills" → teams:["New England Patriots", "Buffalo Bills"], sports:["NFL"]

ALWAYS normalize team names to their full official names for API compatibility."""

            response = self.openai_client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"Analyze this betting query: {question}"}
                ]
            )
            
            content = response.choices[0].message.content.strip()
            analysis = json.loads(content)
            
            logger.info(f"AI query analysis for '{question}': {analysis}")
            return analysis
            
        except Exception as e:
            logger.warning(f"AI query analysis failed: {e}, falling back to basic parsing")
            return self._fallback_query_analysis(question)
    
    def _fallback_query_analysis(self, question: str) -> Dict[str, Any]:
        """Minimal fallback when AI is completely unavailable - return generic search."""
        return {
            "sports": ["NBA", "NFL", "MLB", "NHL"],  # All major sports
            "teams": [],
            "players": [],
            "markets": ["H2H", "SPREAD", "TOTAL"],
            "timeframe": {"type": "general", "hours": 24, "description": "next 24 hours"},
            "intent": "general_picks",
            "confidence": 0.3  # Very low confidence for generic fallback
        }
    
    def build_smart_query(self, question: str, hours: int = 24) -> FeedQuery:
        """
        Parse a user question using AI and build an appropriate FeedQuery.
        Handles all scenarios: time-based, player props, team-specific, etc.
        """
        # Get comprehensive AI analysis
        analysis = self._analyze_query_with_ai(question)
        
        # Convert sports strings to SportKey enums
        detected_sports = []
        sport_mapping = {
            "NFL": SportKey.NFL, "NBA": SportKey.NBA, "MLB": SportKey.MLB, "NHL": SportKey.NHL,
            "NCAAF": SportKey.NCAAF, "NCAAB": SportKey.NCAAB, "WNBA": SportKey.WNBA, "MMA": SportKey.MMA,
            "football": SportKey.FOOTBALL, "boxing": SportKey.BOXING, "tennis": SportKey.TENNIS
        }
        
        for sport_str in analysis.get("sports", []):
            if sport_str in sport_mapping:
                detected_sports.append(sport_mapping[sport_str])
        
        # If no sports detected, use all available sports
        if not detected_sports:
            detected_sports = self.main_feed.list_sports()
        
        # Convert market strings to MarketType enums
        detected_markets = []
        market_mapping = {
            "H2H": MarketType.H2H, "SPREAD": MarketType.SPREAD, "TOTAL": MarketType.TOTAL,
            "TEAM_TOTAL": MarketType.TEAM_TOTAL, "PLAYER_PROPS": MarketType.PLAYER_PROPS
        }
        
        for market_str in analysis.get("markets", []):
            if market_str in market_mapping:
                detected_markets.append(market_mapping[market_str])

            elif "PLAYER" in market_str:
                detected_markets.append(MarketType.PLAYER_PROPS)
        
        # If no markets detected, use main game markets
        if not detected_markets:
            detected_markets = [MarketType.H2H, MarketType.SPREAD, MarketType.TOTAL]
        
        # Use AI-detected timeframe or default
        timeframe = analysis.get("timeframe", {})
        query_hours = timeframe.get("hours") or hours  # Handle None case
        
        # Build time range
        end_time = datetime.now(UTC) + timedelta(hours=query_hours)
        
        # Store analysis for later use in filtering
        query = FeedQuery(
            sports=detected_sports,
            markets=detected_markets,
            start_time_to=end_time
        )
        
        # Store AI analysis in query for later filtering
        query._ai_analysis = analysis
        
        logger.info(f"Built AI-powered query from '{question}': "
                   f"sports={[s.value for s in detected_sports]}, "
                   f"markets={[m.value for m in detected_markets]}, "
                   f"hours={query_hours}, "
                   f"teams={analysis.get('teams', [])}, "
                   f"players={analysis.get('players', [])}")
        
        return query

    def start(self) -> None:
        """Register handlers and start the messaging platform."""
        # self.platform.register_command_handler("ask", self._handle_ask)
        # self.platform.register_command_handler("explain", self._handle_explain)
        self.platform.register_message_handler(lambda msg: True, self._handle_message)
        self.platform.start()

    def get_smart_odds(self, question: str, hours: int = 24) -> str:
        """
        Unified method to get odds based on a natural language question.
        Now with comprehensive AI-powered analysis and filtering.
        """
        try:
            # Build the query from the question (now fully AI-powered)
            query = self.build_smart_query(question, hours)
            analysis = getattr(query, '_ai_analysis', {})

            sports = query.sports
            event_odds_list: List[EventOdds] = []

            if not sports:
                logger.info("No sports detected by AI, using all available sports")
                event_odds_list = self.main_feed.get_odds(query) or []
            else:
                # Main feed first, then others
                feeds_order = [self.main_feed] + [f for f in self.feeds if f is not self.main_feed]
                feed_support = {feed: set(feed.list_sports() or []) for feed in feeds_order}

                # Assign each requested sport to the first feed that supports it
                per_feed_sports: Dict[OddsFeed, set] = {}
                unsupported: set = set()

                for sport in sports:
                    for feed in feeds_order:
                        if sport in feed_support[feed]:
                            per_feed_sports.setdefault(feed, set()).add(sport)
                            break
                    else:
                        unsupported.add(sport)

                # Query each feed once with only the sports it supports
                for feed, sports_bucket in per_feed_sports.items():
                    sub_query = FeedQuery(
                        sports=list(sports_bucket),
                        markets=query.markets,
                        start_time_from=getattr(query, "start_time_from", None),
                        start_time_to=getattr(query, "start_time_to", None),
                    )
                    results = feed.get_odds(sub_query) or []
                    event_odds_list.extend(results)

                # Graceful message if nothing supported
                if unsupported and not event_odds_list:
                    timeframe_desc = analysis.get("timeframe", {}).get("description", f"next {hours} hours")
                    missing = ", ".join(getattr(s, "value", str(s)) for s in unsupported)
                    return f"Sorry, no provider supports the requested sports: {missing}. Try a different sport or timeframe ({timeframe_desc})."
            
            if not event_odds_list:
                timeframe_desc = analysis.get("timeframe", {}).get("description", f"next {hours} hours")
                return f"No upcoming games found matching your request for {timeframe_desc}."
            
            # Apply AI-powered filtering
            filtered_odds = self._apply_ai_filters(event_odds_list, analysis)
            
            if not filtered_odds:
                teams = analysis.get("teams", [])
                players = analysis.get("players", [])
                if teams or players:
                    filter_desc = f"teams: {', '.join(teams)}" if teams else f"players: {', '.join(players)}"
                    return f"Found {len(event_odds_list)} games but none matching {filter_desc}"
                else:
                    filtered_odds = event_odds_list
            
            return self._format_odds_response(filtered_odds, question, analysis, limit=5)
            
        except Exception as e:
            logger.error(f"Error in get_smart_odds: {e}")
            return f"Sorry, I couldn't fetch odds right now. Error: {e}"
    
    def _apply_ai_filters(self, event_odds_list: List[EventOdds], analysis: Dict[str, Any]) -> List[EventOdds]:
        """
        Apply intelligent filtering based on AI analysis of the user query.
        Handles teams, players, and specific market preferences.
        """
        filtered_odds = event_odds_list
        
        # Filter by teams if specified
        teams = analysis.get("teams", [])
        if teams:
            filtered_odds = self._filter_odds_by_teams_ai(filtered_odds, teams)
            logger.info(f"Filtered by teams {teams}: {len(filtered_odds)} games remaining")
        
        # Filter by players if specified (for player props)
        players = analysis.get("players", [])
        if players:
            filtered_odds = self._filter_odds_by_players_ai(filtered_odds, players)
            logger.info(f"Filtered by players {players}: {len(filtered_odds)} games remaining")
        
        return filtered_odds
    
    def _filter_odds_by_teams_ai(self, event_odds_list: List[EventOdds], team_names: List[str]) -> List[EventOdds]:
        """
        Filter odds using AI-detected team names.
        AI handles ALL team variations - no manual mapping needed!
        """
        if not team_names:
            return event_odds_list
        
        filtered = []
        
        for event_odds in event_odds_list:
            competitor_names = [comp.name.lower() for comp in event_odds.event.competitors]
            
            # Check if any AI-detected team matches any competitor
            for team_name in team_names:
                team_lower = team_name.lower()
                
                # AI should have normalized team names, so just do fuzzy matching
                if any(team_lower in comp_name or comp_name in team_lower 
                       for comp_name in competitor_names):
                    filtered.append(event_odds)
                    break
        
        return filtered
    
    def _filter_odds_by_players_ai(self, event_odds_list: List[EventOdds], player_names: List[str]) -> List[EventOdds]:
        """
        Filter for games involving specific players.
        This would need roster data or player-team mapping.
        For now, we'll return games and let the market filtering handle player props.
        """
        # TODO: Implement player-to-team mapping for better filtering
        # For now, return all games as player props are market-specific
        logger.info(f"Player filtering not yet implemented for: {player_names}")
        return event_odds_list
    
    def _format_odds_response(self, event_odds_list: List[EventOdds], original_question: str, analysis: Dict[str, Any], limit: int = 5) -> str:
        """Format the odds response for display to the user with AI context."""
        limited_odds = event_odds_list[:limit]
        
        lines = []
        
        # Create contextual header based on AI analysis
        intent = analysis.get("intent", "general_picks")
        timeframe_desc = analysis.get("timeframe", {}).get("description", "upcoming")
        teams = analysis.get("teams", [])
        players = analysis.get("players", [])
        
        if players:
            lines.append(f"🎯 Found {len(event_odds_list)} games with player props for {', '.join(players)} ({timeframe_desc}):")
        elif teams:
            lines.append(f"🎯 Found {len(event_odds_list)} games involving {', '.join(teams)} ({timeframe_desc}):")
        else:
            lines.append(f"🎯 Found {len(event_odds_list)} {timeframe_desc} games:")
        
        for i, event_odds in enumerate(limited_odds, 1):
            event = event_odds.event
            
            home_team = next((c.name for c in event.competitors if c.role == 'home'), 'TBD')
            away_team = next((c.name for c in event.competitors if c.role == 'away'), 'TBD')
            
            # Format game time if available
            game_time = ""
            if hasattr(event, 'commence_time') and event.commence_time:
                game_time = f" - {event.commence_time.strftime('%I:%M %p')}"
            
            lines.append(f"\n{i}. **{away_team} @ {home_team}**{game_time}")
            
            for market in event_odds.markets:
                market_name = market.market_key.value.upper()
                lines.append(f"   📊 {market_name}:")
                
                outcomes_by_book = {}
                for outcome in market.outcomes:
                    book = outcome.bookmaker_key or "Unknown"
                    if book not in outcomes_by_book:
                        outcomes_by_book[book] = []
                    outcomes_by_book[book].append(outcome)
                
                for book_count, (book, outcomes) in enumerate(outcomes_by_book.items()):
                    if book_count >= 2:  # Limit to 2 bookmakers
                        break
                        
                    outcome_strs = []
                    for outcome in outcomes:
                        price_str = f"{outcome.price_american:+}" if outcome.price_american else "N/A"
                        if outcome.line:
                            outcome_strs.append(f"{outcome.outcome_key} {outcome.line} ({price_str})")
                        else:
                            outcome_strs.append(f"{outcome.outcome_key} ({price_str})")
                    
                    if outcome_strs:
                        lines.append(f"     • {book}: {' | '.join(outcome_strs)}")
        
        if len(event_odds_list) > limit:
            lines.append(f"\n... and {len(event_odds_list) - limit} more games")
        
        # Add confidence indicator if AI analysis has low confidence
        confidence = analysis.get("confidence", 1.0)
        if confidence < 0.7:
            lines.append(f"\n💡 Note: Query interpretation confidence: {confidence:.0%}")
        
        return "\n".join(lines)
