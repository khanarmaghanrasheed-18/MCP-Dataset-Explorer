import asyncio
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from google import genai
from google.genai import types

from dotenv import load_dotenv
load_dotenv()

import copy
import os
import json


class DatasetExplorerClient:
    def __init__(self):
        self.session = None
        self.dataset_path = None

        # Conversation history is kept in memory for the current session only.
        self.conversation_history = []
        self.max_tool_calls_per_request = 3
        self._request_tool_keys = set()
        self._request_tool_count = 0

        self.model = os.getenv(
            "GEMINI_MODEL",
            "gemini-3.5-flash-lite"
        )

        api_key = os.getenv("GEMINI_API_KEY")
        if api_key:
            self.llm = genai.Client(api_key=api_key)
        else:
            self.llm = None

    def reset_conversation(self):
        self.conversation_history = []

    def set_session(self, session):
        self.session = session

    def set_dataset(self, path):
        self.dataset_path = path

    def _start_request_tracking(self):
        self._request_tool_keys = set()
        self._request_tool_count = 0

    def _tool_call_key(self, tool_name, arguments):
        serialized = json.dumps(arguments or {}, sort_keys=True, default=str)
        return f"{tool_name}:{serialized}"

    def _build_system_instruction(self):
        return (
            "You are a dataset analysis assistant. "
            "Use the conversation history as the current session memory. "
            "Reuse prior user questions, assistant answers, and tool results when they answer the current request. "
            "Use the smallest set of MCP tools that can answer the question and do not repeat a tool call "
            "when the exact same tool and arguments are already known in this request. "
            "Before calling a tool, check whether the needed information is already available in history. "
            "Once enough information is known, answer directly without unnecessary tool calls. "
            "After receiving MCP tool results, answer the user's original question in clear natural language. "
            "Never expose raw tool calls, function responses, MCP objects, or internal API syntax to the user. "
            "Call no more than three tools per user request. "
            "If a tool result already answers the question, stop and answer instead of continuing to investigate."
        )

    def _safe_empty_response_fallback(self, message="I have enough information to answer, but the model returned an empty response."):
        return message

    async def list_tools(self):
        result = await self.session.list_tools()
        return result.tools

    async def call_tool(self, tool_name, arguments=None):

        if self.session is None:
            raise RuntimeError(
                "MCP session has not been initialized."
            )

        if self.dataset_path is None:
            raise RuntimeError(
                "No dataset has been selected."
            )

        if arguments is None:
            arguments = {}

        arguments["path"] = self.dataset_path

        result = await self.session.call_tool(
            tool_name,
            arguments
        )

        if result.isError:
            raise RuntimeError(
                f"Tool {tool_name} failed: {result.content}"
            )

        if result.structuredContent is not None:
            return result.structuredContent

        # Fallback
        return {
            "content": [
                part.text
                for part in result.content
                if hasattr(part, "text")
            ]
        }

    async def get_llm_tools(self):

        mcp_tools = await self.list_tools()

        function_declarations = []

        for tool in mcp_tools:

            schema = copy.deepcopy(tool.inputSchema)

            # We manage the dataset path ourselves,
            # so Gemini does not need to provide it.
            schema.get("properties", {}).pop("path", None)

            if "required" in schema:
                schema["required"] = [
                    field
                    for field in schema["required"]
                    if field != "path"
                ]

            function_declarations.append(
                types.FunctionDeclaration(
                    name=tool.name,
                    description=tool.description,
                    parameters_json_schema=schema
                )
            )

        return [
            types.Tool(
                function_declarations=function_declarations
            )
        ]

    async def ask_llm(self, user_query):
        if self.llm is None:
            raise RuntimeError("GEMINI_API_KEY is not set.")

        tools = await self.get_llm_tools()
        self._start_request_tracking()

        # Store the user message in the in-memory history for this session.
        user_content = types.Content(
            role="user",
            parts=[
                types.Part.from_text(text=user_query)
            ]
        )
        self.conversation_history.append(user_content)
        contents = list(self.conversation_history)

        while True:
            response = await self.llm.aio.models.generate_content(
                model=self.model,
                contents=contents,
                config=types.GenerateContentConfig(
                    tools=tools,
                    system_instruction=self._build_system_instruction()
                )
            )

            candidate = response.candidates[0] if response.candidates else None
            if candidate is None:
                return self._safe_empty_response_fallback("I could not get a response from Gemini.")

            model_content = candidate.content

            # Keep Gemini's response in conversation history.
            self.conversation_history.append(model_content)
            contents = list(self.conversation_history)

            function_call = None
            for part in getattr(model_content, "parts", []):
                if getattr(part, "function_call", None):
                    function_call = part.function_call
                    break

            if function_call is None:
                final_text = (response.text or "").strip()
                if final_text:
                    return final_text
                return self._safe_empty_response_fallback()

            tool_name = function_call.name
            tool_arguments = dict(function_call.args or {})

            # Maximum tool calls are enforced per request to avoid runaway loops.
            if self._request_tool_count >= self.max_tool_calls_per_request:
                print("\n[Stopping: max tool calls reached for this request.]")
                return self._safe_empty_response_fallback(
                    "I reached the maximum tool limit for this request, so I am stopping with the information already available."
                )

            tool_key = self._tool_call_key(tool_name, tool_arguments)

            # Duplicate tool calls are prevented within the current request.
            if tool_key in self._request_tool_keys:
                print(f"\n[Skipping duplicate tool call: {tool_name}]")
                return self._safe_empty_response_fallback(
                    "I already used that exact tool with the same arguments in this request, so there is no need to repeat it."
                )

            self._request_tool_keys.add(tool_key)
            self._request_tool_count += 1

            print(f"\n[Gemini chose tool: {tool_name}]")

            tool_result = await self.call_tool(
                tool_name,
                tool_arguments
            )

            # Gemini receives the tool result as a function response so it can decide whether more work is needed.
            function_response = types.Part.from_function_response(
                name=tool_name,
                response={"result": tool_result}
            )

            tool_response_content = types.Content(
                role="user",
                parts=[function_response]
            )
            self.conversation_history.append(tool_response_content)
            contents = list(self.conversation_history)

    
async def main():

    client = DatasetExplorerClient()

    server_params = StdioServerParameters(
        command=sys.executable,
        args=["mcp_server.py"]
    )

    async with stdio_client(server_params) as (read, write):

        async with ClientSession(read, write) as session:

            # 1. Initialize MCP connection
            await session.initialize()
            client.set_session(session)

            # 2. Select dataset once
            dataset_path = input(
                "Enter CSV dataset path: "
            ).strip()

            client.set_dataset(dataset_path)

            print(
                f"\nDataset selected: {dataset_path}"
            )

            # 3. Interactive conversation loop
            print(
                "\nDataset Explorer is ready."
                "\nAsk questions about your dataset."
                "\nType 'exit' to quit.\n"
            )

            while True:

                user_query = input("You: ").strip()

                if user_query.lower() in {
                    "exit",
                    "quit"
                }:
                    print("Closing Dataset Explorer...")
                    break

                if not user_query:
                    continue

                try:
                    response = await client.ask_llm(
                        user_query
                    )

                    print("\nGemini:")
                    print(response)

                except Exception as error:
                    print(
                        f"\nError: {error}"
                    )


if __name__ == "__main__":
    asyncio.run(main())