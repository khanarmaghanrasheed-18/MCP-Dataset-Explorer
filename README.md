# Dataset Explorer MCP

Dataset Explorer helps your AI assistant understand data files saved on your
computer. Ask it to summarize a dataset, check missing values, find repeated
rows, or spot unusual patterns. It calculates answers from your file and leaves
the original unchanged.

It works with **CSV, TSV, Excel, JSON, and Parquet** files. Your assistant starts
this small local server when needed. You don't need a web app, a hosting account,
or a Gemini API key. Your assistant may send the results to its AI provider
according to that client's settings.

The connection uses **MCP over stdio**, which simply means your assistant talks
directly to the server running on your computer.

## How it finds relationships

The server calculates statistics from your dataset rather than guessing them:

- **Pearson correlation** checks how two numeric columns move together.
- **Eta squared** compares numeric values across groups, such as scores across categories.
- **Cramer's V** measures the relationship between two category columns.

It chooses the method based on the types of columns being compared. These
statistics show associations; they don't prove that one feature causes another.

<!-- mcp-name: io.github.khanarmaghanrasheed-18/dataset-explorer -->

## Install

Available on [PyPI](https://pypi.org/project/dataset-explorer-mcp/).

You need Python 3.10 or newer.

```sh
python -m pip install dataset-explorer-mcp
```

The command to start the server is:

```sh
dataset-explorer-mcp
```

Your MCP client normally runs this command for you. If you run it in a terminal,
it waits quietly for messages from a client. That is expected.

If you use [uv](https://docs.astral.sh/uv/), you can run it without a separate installation:

```sh
uvx dataset-explorer-mcp
```

## Connect your assistant

Use an MCP client that supports local stdio servers, such as **Claude Desktop**,
**VS Code with Copilot**, or **Cursor**. The settings file differs by client.

For Claude Desktop or Cursor, add this to your MCP configuration:

```json
{
  "mcpServers": {
    "dataset-explorer": {
      "command": "uvx",
      "args": ["dataset-explorer-mcp"]
    }
  }
}
```

For VS Code, use `.vscode/mcp.json`:

```json
{
  "servers": {
    "dataset-explorer": {
      "type": "stdio",
      "command": "uvx",
      "args": ["dataset-explorer-mcp"]
    }
  }
}
```

If you installed with pip, use `"command": "dataset-explorer-mcp"` and `"args": []`
instead. An absolute path to the executable also works. Reload your client after
changing its configuration.

## Use a local file

Give your assistant the full path to your dataset. For example:

> Explore `C:/Users/YourName/Downloads/customers.csv`. Check missing values and duplicates.

> Summarize `/home/yourname/data/sales.xlsx` and inspect the revenue column.

> In `/Users/yourname/data/results.parquet`, which features are associated with the target column `score`?

All tools take a `path`. A direct tool call looks like:

```json
{"path": "C:/Users/YourName/Downloads/customers.csv"}
```

Use forward slashes in Windows paths, or double backslashes when writing JSON.
The file must be available on the computer where the server runs.

## Supported files and tools

Supported files: **CSV, TSV, Excel (`.xlsx`, `.xls`), JSON, and Parquet**.
Excel reads the first worksheet. JSON must contain tabular data that Pandas can read.

| Tool | What it does |
| --- | --- |
| `get_dataset_overview` | Lists columns, types, and missing-value counts |
| `dataset_shape` | Counts rows and columns |
| `dataset_statistical_summary` | Calculates numeric means and medians |
| `inspect_Column` | Summarizes one column; also takes `col_name` |
| `analyze_target` | Inspects a target column; also takes `target_name` |
| `duplicate_finder` | Finds repeated rows |
| `analyze_missing_values` | Reports missing data |
| `find_correlations` | Finds related numeric columns; optional `threshold` defaults to `0.8` |
| `detect_outliers` | Finds unusual numeric values |
| `screen_target_relationships` | Compares features with a target; also takes `target` |

The server also offers the `dataset://guide` resource and an `explore_dataset`
prompt. These results help you explore data; they don't prove causes or train a model.
Large files need enough RAM because each tool loads the dataset into memory.

## Troubleshooting

- **Command not found:** use the full path to `dataset-explorer-mcp`, or install uv
  and use the `uvx` configuration above.
- **File not found:** use an absolute path and check that the server can read it.
- **No tools appear:** check your client's server logs and reload its MCP settings.
- **Server seems idle:** it is waiting for the MCP client; connect it through your
  assistant rather than typing questions into the server terminal.
- **Unsupported file:** save the data in one of the formats listed above.
- **Missing values in statistics:** empty or constant columns may have undefined
  statistics. Check the overview and missing-value tools first.

Normal server output is reserved for MCP messages. Diagnostics go to stderr,
which your client's server logs usually display.

## Run from source

```sh
git clone https://github.com/khanarmaghanrasheed-18/MCP-Dataset-Explorer.git
cd MCP-Dataset-Explorer
python -m pip install -e ".[dev]"
python -m pytest -q
python mcp_server.py
```

Build the downloadable package with `python -m build`.

## License

MIT. See [LICENSE](LICENSE).
