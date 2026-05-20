*Inspired by: https://github.com/awslabs/mcp/tree/main/src/aws-documentation-mcp-server*

# OCI Documentation MCP Server

Model Context Protocol (MCP) server for OCI Documentation

This MCP server provides tools to search for content, and access OCI documentation.

## Change log

- 2026-05-20: support transport: stdio,sse,streamable-http
- 2026-05-19: change search engine to oracle help center search
- 2025-04-21: Initial release

## Features

### `oci_search_documentation`

Searches OCI documentation through the Oracle Help Center Search API and returns
structured page results. This tool is intended for the first step of a documentation
workflow: finding the most relevant Oracle documentation URL before reading the page.

Parameters:

- `search_phrase`: Search text. Use specific OCI service names, product terms, error
  messages, or feature names for better results.
- `limit`: Maximum number of results to return. Defaults to `3`.
- `page`: Search result page number. Defaults to `1`.

Returns:

- Pagination metadata from the Oracle Help Center result set.
- A list of documentation results with title, URL, and description.

Design notes:

- Uses the public Oracle Help Center pages endpoint.

### `oci_read_documentation`

Reads one OCI documentation page, converts it from HTML to Markdown, indexes it by
line number, and returns a window of content. This tool is intended for controlled
reading of long documentation pages without flooding the MCP response.

Parameters:

- `url`: OCI documentation page URL. The URL must be from `docs.oracle.com` and must
  end with `.htm` or `.html`.
- `start_index`: 0-based line number to start reading from. Defaults to `0`.
- `max_lines`: Maximum number of Markdown lines to return. Defaults to `10`.

Returns:

- `stats`: Total lines, total words, start line, returned lines, remaining lines, and
  remaining words.
- `content`: Markdown text for the requested line window.
- `table_of_contents`: Returned only when `start_index == 0`; includes heading level,
  title, and 0-based line number.

Design notes:

- Long documents are paged by Markdown line number rather than character offset, which
  makes follow-up reads easier for agents.
- Converted pages are cached in process memory for 24 hours, up to 128 pages. The cache
  stores a single line-list representation to avoid duplicating full Markdown text and
  split lines.
- Table of contents and related links are returned only for the first read to avoid
  repeating metadata during follow-up reads.


## Use

### Option 1: Run from pypi package

Defalt output through `stdio`, change that use `--transport` if you want.


```json
{
  "mcpServers": {
    "oci-documentation-mcp-server": {
      "command": "uvx",
      "args": [
        "--from",
        "oci-documentation-mcp-server@latest",
        "python",
        "-m",
        "oci_documentation_mcp_server.server",
        "--transport",
        "stdio"
      ],
      "env": {
        "FASTMCP_LOG_LEVEL": "ERROR"
      }
    }
  }
}
```

### Option 2: Run locally from source code and output through stdio

**Installation Requirements**

1. Doenload this repo. 
2.Install `uv` from [Astral](https://docs.astral.sh/uv/getting-started/installation/) or the [GitHub README](https://github.com/astral-sh/uv#installation)


```json
{
  "mcpServers": {
    "oci-documentation-mcp-server": {
      "command": "uv",
      "args": [
        "--directory",
        "path/to/oci-documentation-mcp-server"
        "run",
        "python",
        "-m",
        "oci_documentation_mcp_server.server",
        "--transport",
        "stdio"
      ],
      "env": {
        "FASTMCP_LOG_LEVEL": "ERROR"
      }
    }
  }
}
```

### Option 3: Run as server 

Run as server use `Streamable HTTP`:

```bash
uv run python -m oci_documentation_mcp_server.server --transport "streamable-http" --port 8000 --path "/mcp"
```

Config on agent tools:

```json
{
  "mcpServers": {
      "oci-documentation-mcp-server": {
      "type": "streamable-http",
      "url": "http://localhost:8000/mcp"
    }
  }
}

```