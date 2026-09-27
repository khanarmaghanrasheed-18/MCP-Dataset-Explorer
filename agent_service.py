import copy
import json
import os
from typing import Any

from google import genai
from google.genai import types

from state_store import StateStore


def compact_value(value: Any, list_limit: int = 12) -> Any:
    if isinstance(value, dict):
        compacted = {}
        for key, item in value.items():
            compacted[key] = compact_value(item, list_limit)
        return compacted

    if isinstance(value, list):
        compacted = []
        for item in value[:list_limit]:
            compacted.append(compact_value(item, list_limit))
        if len(value) > list_limit:
            compacted.append({"omitted_items": len(value) - list_limit})
        return compacted

    return value


class AgentService:
    def __init__(self, mcp_session: Any, store: StateStore):
        self.mcp_session = mcp_session
        self.store = store
        self.model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash-lite")
        api_key = os.getenv("GEMINI_API_KEY")
        self.llm = genai.Client(api_key=api_key) if api_key else None
        self.max_tools_per_question = 4

    async def llm_tools(self) -> list[types.Tool]:
        result = await self.mcp_session.list_tools()
        declarations = []

        for tool in result.tools:
            schema = copy.deepcopy(tool.inputSchema)
            schema.get("properties", {}).pop("path", None)

            if "required" in schema:
                required_fields = []
                for field in schema["required"]:
                    if field != "path":
                        required_fields.append(field)
                schema["required"] = required_fields

            declarations.append(types.FunctionDeclaration(
                name=tool.name,
                description=tool.description,
                parameters_json_schema=schema,
            ))

        return [types.Tool(function_declarations=declarations)]

    def system_instruction(
        self, state: dict[str, Any], messages: list[dict[str, Any]]
    ) -> str:
        context = {
            "analysis_state": state,
            "recent_messages": messages,
        }
        context_text = json.dumps(context, ensure_ascii=False, default=str)

        return (
            "You are an evidence-driven dataset analyst. The application owns durable memory; "
            "the JSON context below is the current trusted session state. Decide which MCP tools "
            "are necessary and call only tools that materially answer the current question. You "
            "may request multiple tools in one response. Never invent statistics, columns, or "
            "causal claims. Use no more than four tools. When enough evidence is available, return "
            "JSON only with this shape: {\"answer\": string, \"state_update\": {\"goal\": "
            "string|null, \"target\": string|null, \"plan\": string[], \"findings\": object[], "
            "\"hypotheses\": string[], \"next_action\": string|null, \"status\": "
            "\"active\"|\"complete\"}}. Findings must cite evidence IDs when evidence is supplied. "
            f"Current context: {context_text}"
        )

    async def execute_tool(
        self,
        session: dict[str, Any],
        tool_name: str,
        arguments: dict[str, Any],
    ) -> tuple[dict[str, Any], str, bool]:
        clean_arguments = copy.deepcopy(arguments)
        cache_key = self.store.cache_key(
            session["dataset"]["file_hash"], tool_name, clean_arguments
        )
        result = self.store.get_cached_result(cache_key)
        cache_hit = result is not None

        if result is None:
            call_arguments = copy.deepcopy(clean_arguments)
            call_arguments["path"] = session["dataset"]["stored_path"]
            response = await self.mcp_session.call_tool(tool_name, call_arguments)

            if response.isError:
                raise RuntimeError(f"Tool '{tool_name}' failed.")

            if response.structuredContent is not None:
                result = response.structuredContent
            else:
                content = []
                for part in response.content:
                    if hasattr(part, "text"):
                        content.append(part.text)
                result = {"content": content}

            self.store.save_cached_result(
                cache_key,
                session["dataset_id"],
                tool_name,
                clean_arguments,
                result,
            )

        evidence_id = self.store.save_evidence(
            session["id"], tool_name, clean_arguments, result
        )
        return result, evidence_id, cache_hit

    def parse_final_response(self, text: str) -> dict[str, Any]:
        cleaned = text.strip()

        if cleaned.startswith("```"):
            lines = cleaned.splitlines()
            if lines:
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            cleaned = "\n".join(lines)

        try:
            parsed = json.loads(cleaned)
        except json.JSONDecodeError:
            return {"answer": text.strip(), "state_update": {}}

        if not isinstance(parsed, dict):
            return {"answer": text.strip(), "state_update": {}}

        answer = parsed.get("answer")
        if not isinstance(answer, str) or not answer.strip():
            answer = "The analysis completed, but Gemini returned no readable explanation."

        update = parsed.get("state_update")
        if not isinstance(update, dict):
            update = {}
        return {"answer": answer.strip(), "state_update": update}

    def merge_state(
        self,
        state: dict[str, Any],
        update: dict[str, Any],
        completed_actions: list[dict[str, Any]],
    ) -> dict[str, Any]:
        scalar_fields = ["goal", "target", "next_action", "status"]
        list_fields = ["plan", "findings", "hypotheses"]

        for field in scalar_fields:
            if field in update:
                state[field] = update[field]

        for field in list_fields:
            if field in update and isinstance(update[field], list):
                state[field] = update[field]

        for action in completed_actions:
            state["completed_actions"].append(action)

        if state["status"] == "new":
            state["status"] = "active"
        return state

    async def ask(self, session_id: str, question: str) -> dict[str, Any]:
        if self.llm is None:
            raise RuntimeError("GEMINI_API_KEY is not configured on the server.")

        session = self.store.get_session(session_id)
        if session is None:
            raise ValueError("Analysis session was not found.")

        self.store.add_message(session_id, "user", question)
        recent_messages = self.store.recent_messages(session_id, limit=4)
        instruction = self.system_instruction(session["state"], recent_messages)
        tools = await self.llm_tools()
        contents = [types.Content(
            role="user",
            parts=[types.Part.from_text(text=question)],
        )]

        response = await self.llm.aio.models.generate_content(
            model=self.model,
            contents=contents,
            config=types.GenerateContentConfig(
                tools=tools,
                system_instruction=instruction,
            ),
        )
        candidate = response.candidates[0] if response.candidates else None
        if candidate is None or candidate.content is None:
            raise RuntimeError("Gemini returned an empty response.")

        model_content = candidate.content
        function_calls = []

        for part in getattr(model_content, "parts", []):
            if getattr(part, "function_call", None):
                function_calls.append(part.function_call)

        completed_actions = []

        if function_calls:
            contents.append(model_content)
            response_parts = []
            seen_calls = set()

            for function_call in function_calls[:self.max_tools_per_question]:
                arguments = dict(function_call.args or {})
                call_key = json.dumps(
                    {"name": function_call.name, "arguments": arguments},
                    sort_keys=True,
                    default=str,
                )

                if call_key in seen_calls:
                    continue
                seen_calls.add(call_key)

                result, evidence_id, cache_hit = await self.execute_tool(
                    session, function_call.name, arguments
                )
                completed_actions.append({
                    "tool": function_call.name,
                    "arguments": arguments,
                    "evidence_id": evidence_id,
                    "cache_hit": cache_hit,
                })
                response_parts.append(types.Part.from_function_response(
                    name=function_call.name,
                    response={
                        "evidence_id": evidence_id,
                        "result": compact_value(result),
                    },
                ))

            contents.append(types.Content(role="user", parts=response_parts))
            contents.append(types.Content(
                role="user",
                parts=[types.Part.from_text(
                    text="Synthesize the evidence now and return the required JSON only."
                )],
            ))
            response = await self.llm.aio.models.generate_content(
                model=self.model,
                contents=contents,
                config=types.GenerateContentConfig(system_instruction=instruction),
            )

        final_text = (response.text or "").strip()
        parsed = self.parse_final_response(final_text)
        state = self.merge_state(
            session["state"], parsed["state_update"], completed_actions
        )
        self.store.save_state(session_id, state)
        self.store.add_message(session_id, "assistant", parsed["answer"])

        return {
            "answer": parsed["answer"],
            "state": state,
            "tool_calls": completed_actions,
        }
