# Publishing Dataset Explorer

## One-time PyPI setup

The release workflow is `.github/workflows/release.yml`. It uses PyPI Trusted Publishing, so no API token needs to be stored in the repository.

In [the project's Publishing settings](https://pypi.org/manage/project/dataset-explorer-mcp/settings/publishing/), add a GitHub publisher with:

- Owner: `khanarmaghanrasheed-18`
- Repository: `MCP-Dataset-Explorer`
- Workflow filename: `release.yml`
- Environment: `pypi`

See [PyPI's setup instructions](https://docs.pypi.org/trusted-publishers/adding-a-publisher/).

## Publish a version

1. Set the same new version in `pyproject.toml`, `server.json.version`, and `server.json.packages[0].version`.
2. Keep the package name `dataset-explorer-mcp`, registry name `io.github.khanarmaghanrasheed-18/dataset-explorer`, and README `mcp-name` comment unchanged.
3. Commit to `main`. This runs validation, tests, the package build, and `twine check`, but does not publish.
4. Open [Validate and publish package](https://github.com/khanarmaghanrasheed-18/MCP-Dataset-Explorer/actions/workflows/release.yml), choose **Run workflow**, select `main`, enable **Publish this version to PyPI and the MCP Registry**, and run it. Alternatively, push a version tag such as `v0.2.2` matching the metadata.
5. Confirm that `build`, `publish-pypi`, and `publish-registry` all succeed. A successful build with skipped publishing jobs is not a published release.
6. Check the version on [PyPI](https://pypi.org/project/dataset-explorer-mcp/) and in the [official MCP Registry](https://registry.modelcontextprotocol.io/?q=io.github.khanarmaghanrasheed-18%2Fdataset-explorer).

The workflow uploads the package to PyPI first, then publishes `server.json` with GitHub OIDC authentication. If registry publishing fails after a successful PyPI upload, use **Re-run failed jobs** after resolving the cause. Published metadata is immutable; use a new version for later metadata changes.

The LinkedIn/share link stays https://pypi.org/project/dataset-explorer-mcp/ across releases. Updating GitHub files alone does not update either published service.

## GitHub repository discovery

In the repository's **About** settings, use:

- Description: `Local MCP analysis for CSV, TSV, Excel, JSON and Parquet: summaries, outliers and relationships.`
- Website: `https://pypi.org/project/dataset-explorer-mcp/`
- Topics: `mcp`, `mcp-server`, `model-context-protocol`, `data-analysis`, `exploratory-data-analysis`, `pandas`, `csv`, `parquet`

## Directory maintenance

- **Glama:** Manage the [existing listing](https://glama.ai/mcp/servers/khanarmaghanrasheed-18/MCP-Dataset-Explorer) by signing in with the owning GitHub account. Update the old CSV-only/Gemini description to local stdio, CSV/TSV/Excel/JSON/Parquet support, ten tools, and no required Gemini key. Request reindexing if its code, tools or MIT license information stays stale. Do not create a duplicate listing.
- **GitHub gallery:** This is separate from the official MCP Registry. A nomination has already been sent to `partnerships@github.com` (request 166247). After a new version is actually published, any useful update belongs in that existing email thread; a PyPI or registry publication is not proof of gallery acceptance.
- **mcpservers.org:** Check existing listings and submission receipts before using [the free submission form](https://mcpservers.org/submit). Use name `Dataset Explorer`, the About description above, the repository URL, the official registry identifier, and the maintainer's contact email. Choose the matching data-analysis category and leave remote connections unchecked.
