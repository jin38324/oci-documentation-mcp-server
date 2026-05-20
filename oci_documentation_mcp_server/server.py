# This is an implementation of https://github.com/awslabs/mcp/tree/main/src/aws-documentation-mcp-server
#
# Licensed under the Apache License, Version 2.0 (the "License"). You may not use this file except in compliance
# with the License. A copy of the License is located at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# or in the 'license' file accompanying this file. This file is distributed on an 'AS IS' BASIS, WITHOUT WARRANTIES
# OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions
# and limitations under the License.
"""OCI Documentation MCP Server implementation."""

import argparse
import os
import re
import sys

from oci_documentation_mcp_server.ohc_search import search_oci_documentation
from oci_documentation_mcp_server.util import (
    format_documentation_result,
)
from fastmcp import Context, FastMCP
from loguru import logger
from pydantic import Field


# Set up logging
logger.remove()
logger.add(sys.stderr, level=os.getenv('FASTMCP_LOG_LEVEL', 'WARNING'))

mcp = FastMCP(
    'oci-documentation-mcp-server',
    instructions="""
    # OCI Documentation MCP Server

    This server provides tools to access public OCI documentation and search for content.

    ## Best Practices

    - For long documentation pages, make multiple calls to `oci_read_documentation` with different `start_index` line numbers for pagination
    - For very long documents, stop reading if you've found the needed information
    - When searching, use specific technical terms rather than general phrases
    - Always cite the documentation URL when providing information to users

    ## Tool Selection Guide

    - Use `oci_search_documentation` when: You need to find documentation about a specific OCI service or feature
    - Use `oci_read_documentation` when: You have a specific documentation URL and need its content
    """,
)



@mcp.tool()
async def oci_search_documentation(
    ctx: Context,
    search_phrase: str = Field(description='Search phrase to use'),
    limit: int = Field(
        default=3,
        description='Maximum number of results to return',
        ge=1,
        le=10,
        ),
    page: int = Field(
        default=1,
        description='Page number to return',
        ge=1,
        ),
    ) -> str:
    """Search OCI documentation based on a search phrase.

    ## Usage

    This tool searches OCI documentation pages matching your search phrase.
    Use it to find relevant documentation urls about OCI Productswhen you don't have a specific URL.

    ## Search Tips

    - Use specific product name/technical terms rather than general phrases
    - Include service names to narrow results (e.g., "OCI Object Storage bucket versioning" instead of just "versioning")
    - Use quotes for exact phrase matching (e.g., "Using Instance Configurations and Instance Pools")
 
    Args:
        search_phrase: The backend breaks up the search string to find content with the most matching words. The order of terms can impact the results. Quotes can be used to indicate required terms.
        limit: Maximum number of results to return
        page: Page number to return

    Returns:
    - pagination: Pagination information
    - results: List of search results with URLs, titles, and descriptions
    """
    logger.info(f'Searching OCI documentation for: {search_phrase}')

    try:
        ohc_search_response = await search_oci_documentation(
            search_phrase,
            limit,
            page,
        )
        logger.info(f'Found {len(ohc_search_response.results)} search results for: {search_phrase}')
        return ohc_search_response.model_dump_json()
    except Exception as e:
        error_msg = f'Error searching OCI docs: {str(e)}'
        logger.error(error_msg)
        await ctx.error(error_msg)
        return "No search results found. Please try a different search phrase."    


@mcp.tool()
async def oci_read_documentation(
    ctx: Context,
    url: str = Field(description='URL of the OCI documentation page to read'),
    start_index: int = Field(
        default=0,
        description='On return output starting at this line number, useful if a previous fetch was truncated and more content is required.',
        ge=0,
    ),
    max_lines: int = Field(
        default=10,
        description='Maximum number of lines to return.',
        gt=0,
        lt=1000000,
    )
) -> str:
    """Fetch an OCI documentation page url and return content partially as markdown.

    ## Handling Long Documents

    If the response indicates the document was truncated, you have several options:

    1. **Continue Reading**: Make another call with `start_index` set to retrieve the next portion of the document.
    2. **Stop Early**: If you've already found the specific information needed, you can stop reading

    Args:
        url: URL of the OCI documentation page to read        
        start_index: On return output starting at this character index
        max_lines: Maximum number of lines to return

    Returns:
        Markdown content of the OCI documentation
    """
    # Validate that URL is from docs.oracle.com and ends with .htm
    url_str = str(url)
    if not re.match(r'^https?://docs\.oracle\.com/', url_str):
        await ctx.error(f'Invalid URL: {url_str}. URL must be from the docs.oracle.com domain')
        raise ValueError('URL must be from the docs.oracle.com domain')
    if not url_str.endswith('.htm') and not url_str.endswith('.html'):
        await ctx.error(f'Invalid URL: {url_str}. URL must end with .htm or .html')
        raise ValueError('URL must end with .htm or .html')

    logger.debug(f'Reading documentation from {url_str} starting at line {start_index}')
    try:
        return await format_documentation_result(url_str, start_index, max_lines)
    except Exception as e:
        error_msg = f'Failed to read {url_str}: {str(e)}'
        logger.error(error_msg)
        await ctx.error(error_msg)
        return error_msg




def main():
    """Run the MCP server with CLI argument support."""
    parser = argparse.ArgumentParser(
        description='An OCI Labs Model Context Protocol (MCP) server for OCI Documentation'
    )
    parser.add_argument('--transport', type=str, default='stdio',
                        choices=['stdio', 'sse', 'streamable-http'],
                        help='Transport protocol to use (default: stdio)')
    parser.add_argument('--host', type=str, default='0.0.0.0',
                        help='Host to bind the server to (default: 0.0.0.0)')
    parser.add_argument('--port', type=int, default=8000,
                        help='Port to run the server on (default: 8000)')
    parser.add_argument('--path', type=str, default='/mcp',
                        help='HTTP endpoint path when using --transport sse or streamable-http (default: /mcp)')

    args = parser.parse_args()

    # Log startup information
    logger.info('Starting OCI Documentation MCP Server')
    logger.info(f'Transport: {args.transport}')

    # Run server with appropriate transport
    if args.transport == 'stdio':
        logger.info('Using stdio transport')
        mcp.run()
    elif args.transport in {'sse', 'streamable-http'}:
        logger.info(f'Using {args.transport} transport on {args.host}:{args.port}{args.path}')
        mcp.run(
            transport=args.transport,
            host=args.host,
            port=args.port,
            path=args.path,
        )
    else:
        logger.error(f'Invalid transport: {args.transport}')
        sys.exit(1)


if __name__ == '__main__':
    main()
