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

        self.model = os.getenv(
            "GEMINI_MODEL",
            "gemini-3.6-flash"
        )

        self.llm = genai.Client(
            api_key=os.environ["GEMINI_API_KEY"]
        )

    def set_session(self, session):
        self.session = session

    def set_dataset(self, path):
        self.dataset_path = path

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

        tools = await self.get_llm_tools()

        contents = [
            types.Content(
                role="user",
                parts=[
                    types.Part.from_text(
                        text=user_query
                    )
                ]
            )
        ]

        while True:

            response = await self.llm.aio.models.generate_content(
                model=self.model,
                contents=contents,
                config=types.GenerateContentConfig(
                    tools=tools,
                    system_instruction=(
                        "You are a dataset analysis assistant. "
                        "Use the provided tools whenever dataset information is required. "
                        "After receiving tool results, answer the user's original question "
                        "in clear natural language. "
                        "Never expose raw tool calls, function responses, MCP objects, "
                        "or internal API syntax to the user. "
                        "Only call additional tools when they are necessary to answer "
                        "the user's question."
                    )
                )
            )

            candidate = response.candidates[0]
            model_content = candidate.content

            # Keep Gemini's response in conversation history
            contents.append(model_content)

            function_call = None

            for part in model_content.parts:
                if part.function_call:
                    function_call = part.function_call
                    break

            # If Gemini did not request a tool,
            # we have reached the final natural-language answer.
            if function_call is None:
                return response.text

            tool_name = function_call.name
            tool_arguments = dict(function_call.args or {})

            print(
                f"\n[Gemini chose tool: {tool_name}]"
            )

            # Execute the MCP tool
            tool_result = await self.call_tool(
                tool_name,
                tool_arguments
            )

            # Return the MCP result to Gemini
            function_response = types.Part.from_function_response(
                name=tool_name,
                response={
                    "result": tool_result
                }
            )

            contents.append(
                types.Content(
                    role="user",
                    parts=[function_response]
                )
            )

    
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