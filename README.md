# Dataset Explorer MCP Server

A lightweight **Model Context Protocol (MCP) server** for exploring and analyzing CSV datasets.

I built this project while learning MCP to understand how external capabilities can be exposed to AI applications through a standardized protocol.

Instead of relying on an LLM to perform dataset operations itself, the server exposes deterministic Python/Pandas functions as MCP tools that compatible clients can discover and invoke.

## Certified Badge 

[![M8ven Score](https://m8ven.ai/badge/mcp/khanarmaghanrasheed-18-mcp-dataset-explorer-15ss4l)](https://m8ven.ai/mcp/khanarmaghanrasheed-18-mcp-dataset-explorer-15ss4l)

## Why I Built This

While learning MCP, I wanted to build something more practical than basic file-reading or document-editing tools.

Dataset exploration was a natural use case because many common exploratory data analysis operations can be implemented as reusable tools.

For example, instead of manually writing Pandas code to inspect every new dataset, an MCP-compatible client can discover capabilities such as:

- inspecting dataset structure
- analyzing individual features
- identifying missing values
- detecting duplicate observations
- finding strongly correlated features
- detecting numerical outliers

The project helped me understand the relationship between:

**LLM → MCP Client → MCP Server → Tools → External computation/data**

## Architecture

```text
             MCP Client
          (MCP Inspector)
                 │
                 │ MCP
                 ▼
       ┌─────────────────────┐
       │   Dataset Explorer  │
       │     MCP Server      │
       └──────────┬──────────┘
                  │
          ┌───────┴────────┐
          │                │
       MCP Tools        Pandas
          │                │
          └───────┬────────┘
                  ▼
             CSV Dataset
```

During development, **MCP Inspector acts as the client** and is used to discover and invoke the capabilities exposed by the server.

## MCP Tools

### `get_dataset_overview`

Returns a general overview of the dataset, including:

- feature names
- missing-value counts
- categorical columns
- numerical columns
- data types

### `dataset_shape`

Returns the number of rows and columns in the dataset.

### `dataset_statistical_summary`

Calculates the mean and median of numerical features.

### `inspect_column`

Provides detailed information about a selected feature.

For numerical columns, this includes information such as:

- data type
- missing values
- unique values
- minimum
- maximum
- mean

For categorical columns, it reports the most common values.

### `analyze_target`

Analyzes a selected target variable and provides a heuristic indication of whether the problem is likely:

- Classification
- Regression

It also reports relevant statistics about the target.

> The classification/regression determination is heuristic and should not replace understanding of the actual problem statement.

### `duplicate_finder`

Detects duplicate observations and reports:

- duplicate count
- duplicate percentage
- example duplicate rows

### `analyze_missing_values`

Analyzes columns containing missing values and reports:

- missing count
- missing percentage
- affected row indices
- basic handling suggestions

### `find_correlations`

Calculates correlations between numerical features and returns strongly correlated feature pairs above a configurable threshold.

Default threshold:

```text
|correlation| >= 0.8
```

### `detect_outliers`

Detects potential numerical outliers using the **Interquartile Range (IQR)** method.

For each affected feature, the tool reports:

- number of detected outliers
- percentage of observations
- row indices
- outlier values
- lower bound
- upper bound

The IQR rule used is:

```text
IQR = Q3 - Q1

Lower Bound = Q1 - 1.5 × IQR
Upper Bound = Q3 + 1.5 × IQR
```

Values outside these bounds are reported as potential outliers.

## MCP Resource

The server also exposes a dataset exploration guide as an MCP resource.

```text
dataset://guide
```

The resource describes the capabilities and limitations of the Dataset Explorer server.

## MCP Prompt

A reusable MCP prompt provides a structured workflow for exploring a dataset using the available tools.

```text
explore_dataset
```

The prompt guides an LLM through dataset structure, missing values, duplicates, correlations, outliers, and optional target analysis.

## Project Structure

```text
DatasetExplorer-MCP/
│
├── mcp_server.py
│
├── data/
│   └── sample.csv
│
├── README.md
├── pyproject.toml
├── uv.lock
└── .gitignore
```

## Installation

### 1. Clone the repository

```bash
git clone <repository-url>
cd DatasetExplorer-MCP
```

### 2. Install dependencies

This project uses `uv` for dependency and environment management.

```bash
uv sync
```

This recreates the project's virtual environment using the dependencies defined in `pyproject.toml` and locked in `uv.lock`.

## Running the MCP Server

The MCP server uses **stdio transport**.

The server entry point is:

```python
if __name__ == "__main__":
    mcp.run(transport="stdio")
```

The server can then be launched/configured through an MCP-compatible client such as **MCP Inspector**.

## Testing with MCP Inspector

MCP Inspector was used during development to verify:

- server connectivity
- tool discovery
- tool schemas
- tool execution
- structured responses
- resources
- prompts

Example workflow:

```text
MCP Inspector
      │
      │ calls detect_outliers
      ▼
Dataset Explorer Server
      │
      │ executes Pandas/IQR analysis
      ▼
Structured MCP Response
```

## Current Limitations

The current version intentionally focuses on exploratory analysis.

- Only CSV datasets are supported.
- Correlation analysis currently uses Pearson correlation.
- Outlier detection currently uses the IQR method.
- Classification/regression detection is heuristic.
- The server does not train machine-learning models.
- The server does not automatically modify or clean datasets.
- Preprocessing decisions still require understanding of the dataset and problem domain.

## Future Improvements

Possible future versions include:

- Support for Excel and JSON datasets
- Additional outlier detection methods
- More advanced target analysis
- Data visualization tools
- Automated preprocessing recommendations
- A custom MCP client
- LLM integration for natural-language dataset exploration

A future client could enable a workflow such as:

```text
User
  │
  ▼
LLM
  │
  ▼
MCP Client
  │
  ▼
Dataset Explorer MCP Server
  │
  ▼
Pandas / Dataset
```

This would allow a user to ask natural-language questions while the LLM dynamically selects and invokes the appropriate dataset-analysis tools.

## Tech Stack

- Python
- Pandas
- Model Context Protocol (MCP)
- FastMCP
- uv
- MCP Inspector

## Purpose

This project was primarily built to understand MCP from first principles by implementing a practical server, exposing custom tools, and testing tool discovery and execution through an MCP client.

It is intended as a learning and portfolio project rather than a production-grade automated data analysis system.