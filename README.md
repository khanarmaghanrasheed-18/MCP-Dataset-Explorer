# Dataset Explorer MCP — Version 2

A lightweight **Model Context Protocol (MCP)** project for exploring CSV datasets through natural-language questions.

Version 1 focused on building the MCP server and testing its tools through MCP Inspector. Version 2 adds a **custom MCP client with Google Gemini**, allowing the LLM to dynamically choose and use dataset-analysis tools.

## Certified Badge

[![M8ven Score](https://m8ven.ai/badge/mcp/khanarmaghanrasheed-18-mcp-dataset-explorer-15ss4l)](https://m8ven.ai/mcp/khanarmaghanrasheed-18-mcp-dataset-explorer-15ss4l)

## What It Does

The user selects a CSV dataset at runtime and asks questions in natural language. Gemini sees the tools exposed by the MCP server, decides which tool is appropriate, the custom client executes it, and the result is returned to Gemini for a readable answer.

The client also maintains in-memory conversation context for follow-up questions and includes safeguards to reduce unnecessary or repeated tool calls.

## Architecture

```text
User
  ↓
Google Gemini
  ↓  chooses tool
Custom MCP Client
  ↓  MCP
Dataset Explorer Server
  ↓
Python / Pandas
  ↓
CSV Dataset
  ↓
Tool Result → Gemini → User
```

The key idea is separation of responsibilities: **Gemini handles reasoning and tool selection, the MCP client handles orchestration, and the MCP server provides deterministic dataset capabilities.**

## MCP Tools

| Tool | What it does |
|---|---|
| `get_dataset_overview` | Returns feature names, data types, missing-value counts, and numerical/categorical columns. |
| `dataset_shape` | Returns the number of rows and columns. |
| `dataset_statistical_summary` | Calculates basic statistics such as mean, median, and mode. |
| `inspect_Column` | Summarizes one feature including data type, missing values, unique values, min/max/mean or common categorical values. |
| `analyze_target` | Analyzes a target variable and heuristically identifies classification or regression. |
| `duplicate_finder` | Finds duplicate observations in the dataset. |
| `analyze_missing_values` | Reports missing-value counts, percentages, affected rows, and basic suggestions. |
| `find_correlations` | Finds strongly correlated numerical feature pairs above a configurable threshold. |
| `detect_outliers` | Detects numerical outliers using the IQR method. |

## Dynamic Tool Selection

The client discovers tools from the MCP server and converts their schemas into Gemini-compatible function declarations.

There are no hardcoded rules such as:

```python
if "outlier" in question:
    call_detect_outliers()
```

Instead, Gemini decides which available tool best answers the user's question.

```text
"How many rows are there?"
        ↓
Gemini chooses dataset_shape
        ↓
MCP client executes it
        ↓
Server returns structured result
        ↓
Gemini produces the final answer
```

## Conversation Context

Conversation history is maintained in memory during the session, allowing follow-up questions such as **"Can this column be used for a machine-learning model?"** to refer to a column discussed previously.

The client also limits repeated and unnecessary tool calls so simple questions generally require only the minimum analysis needed.

## Project Structure

```text
MCP-Dataset-Explorer/
├── mcp_server.py
├── mcp_client.py
├── README.md
├── pyproject.toml
├── uv.lock
└── .gitignore
```

## Running the Project

Install the project dependencies and run:

```bash
python mcp_client.py
```

The client starts the MCP server through stdio, asks for a CSV dataset path, and opens the interactive natural-language query loop.

## Tech Stack

**Python · Pandas · Model Context Protocol (MCP) · FastMCP · Google Gemini · Google GenAI SDK · uv · MCP Inspector**

## Current Limitations

The project currently supports CSV datasets and focuses on exploratory analysis rather than training or modifying machine-learning models.

## Future Improvements

- Add visualizations generated from dataset analysis.
- Build a simple web interface on top of the MCP client.

## Purpose

This project was built to understand MCP beyond the server side by implementing the complete flow from **LLM reasoning → MCP client orchestration → MCP server tools → external data**.

Version 1 taught me how to expose capabilities through MCP. Version 2 helped me understand how an LLM-powered application can dynamically discover and use those capabilities.
