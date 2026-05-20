# Licensed under the Apache License, Version 2.0 (the "License"). You may not use this file except in compliance
# with the License. A copy of the License is located at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# or in the 'license' file accompanying this file. This file is distributed on an 'AS IS' BASIS, WITHOUT WARRANTIES
# OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions
# and limitations under the License.
"""Utility functions for OCI Documentation MCP Server."""

import json
import markdownify
import re
import time
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx

DEFAULT_HEADERS = {
    'user-agent': "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36",
    'accept': 'application/text',
}
DOCUMENT_CACHE_TTL_SECONDS = 24 * 60 * 60
DOCUMENT_CACHE_MAX_ITEMS = 128
DOCUMENT_CACHE: dict[str, dict[str, Any]] = {}


def is_html_content(page_raw: str, content_type: str) -> bool:
    """Determine if content is HTML.

    Args:
        page_raw: Raw page content
        content_type: Content-Type header

    Returns:
        True if content is HTML, False otherwise
    """
    return '<html' in page_raw[:100] or 'text/html' in content_type or not content_type

def extract_content_from_html(html_string: str) -> str:
    """Extract and convert HTML content to Markdown format.

    Args:
        html: Raw HTML content to process

    Returns:
        Simplified markdown version of the content
    """
    if not html_string:
        return '<e>Empty HTML content</e>'

    try:
        # First use BeautifulSoup to clean up the HTML
        from bs4 import BeautifulSoup
        import html

        html_content = html.unescape(html_string)
        utf8_encoded_html = html_content.encode('utf-8')
        # Parse HTML with BeautifulSoup
        soup = BeautifulSoup(utf8_encoded_html, 'html.parser')

        # Try to find the main content area
        main_content = None

        # Common content container selectors for OCI documentation
        content_selectors = [
            'main',
            'article',
            '#main-content',
            '.main-content',
            '#content',
            '.content',
            "div[role='main']"
        ]

        # Try to find the main content using common selectors
        for selector in content_selectors:
            content = soup.select_one(selector)
            if content:
                main_content = content
                break

        # If no main content found, use the body
        if not main_content:
            main_content = soup.body if soup.body else soup

        # Define tags to strip - these are elements we don't want in the output
        tags_to_strip = [
            'script',
            'style',
            'noscript',
            'meta',
            'link',
            'footer',
            'nav',
            'aside',
            'header',
            # Common unnecessary elements
            'js-show-more-buttons',
            'js-show-more-text',
            'feedback-container',
            'feedback-section',
            'doc-feedback-container',
            'doc-feedback-section',
            'warning-container',
            'warning-section',
            'cookie-banner',
            'cookie-notice',
            'copyright-section',
            'legal-section',
            'terms-section',
        ]

        # Use markdownify on the cleaned HTML content
        content = markdownify.markdownify(
            str(main_content),
            heading_style=markdownify.ATX,
            autolinks=True,
            default_title=True,
            escape_asterisks=True,
            escape_underscores=True,
            newline_style="SPACE",
            strip=tags_to_strip,
        )

        if not content:
            return '<e>Page failed to be simplified from HTML</e>'

        return content
    except Exception as e:
        return f'<e>Error converting HTML to Markdown: {str(e)}</e>'


def _extract_markdown_links(base_page_url: str, markdown_text: str) -> str:
    """
    Extract markdown links from text.
    
    Args:
        base_page_url: Base URL of the page
        markdown_text: Markdown text to extract links from
        
    Returns:
        List of dictionaries containing link information
    """
    pattern = r'\[([^\]]+)\]\(\s*([^\s)]+)(?:\s+["\'][^"\']*["\'])?\s*\)'
    matches = re.findall(pattern, markdown_text)
    related_links = f"""Related Links:
    
    Full url is constructed by concatenating the `base URL` with the `href`.
    Base URL: {base_page_url}
    
    | Title | Href |
    | -------- | -------- |"""
    for match in matches:
        related_links += f"\n| {match[0]} | {match[1]} |"
    return related_links

def _normalize_documentation_url(url: str) -> str:
    """Normalize URL for cache lookup while preserving the document identity."""
    return str(url).strip()


def _base_page_url(url: str) -> str:
    """Return the page directory URL used with relative hrefs."""
    parts = urlsplit(url)
    path = parts.path
    if path.lower().endswith(('.html', '.htm')):
        path = path.rsplit('/', 1)[0] + '/'
    elif path and not path.endswith('/'):
        path = path + '/'
    elif not path:
        path = '/'
    return urlunsplit((parts.scheme, parts.netloc, path, '', ''))

def _extract_table_of_contents(lines: list[str]) -> str:
    """Extract markdown headings and their line numbers."""
    table_of_contents = """Table of Contents:
    | Title | Line Number |
    | -------- | -------- |"""
    pattern = re.compile(r'^(#{1,6})\s+(.+?)\s*$')
    for line_number, line in enumerate(lines):
        match = pattern.match(line)
        if match:
            table_of_contents += f"| {match.group(2).strip()} | {line_number} |\n"
            
    return table_of_contents


def _word_count(lines: list[str]) -> int:
    """Count words in markdown lines."""
    return sum(len(re.findall(r'\S+', line)) for line in lines)


def _is_cache_entry_fresh(cache_entry: dict[str, Any], now: float) -> bool:
    """Return True when a cache entry is still inside its TTL."""
    created_at = cache_entry.get('created_at', 0)
    return now - created_at <= DOCUMENT_CACHE_TTL_SECONDS


def _prune_document_cache(now: float) -> None:
    """Remove expired entries and oldest entries above the cache size limit."""
    expired_keys = [
        key for key, entry in DOCUMENT_CACHE.items() if not _is_cache_entry_fresh(entry, now)
    ]
    for key in expired_keys:
        DOCUMENT_CACHE.pop(key, None)

    while len(DOCUMENT_CACHE) >= DOCUMENT_CACHE_MAX_ITEMS:
        oldest_key = min(
            DOCUMENT_CACHE,
            key=lambda key: DOCUMENT_CACHE[key].get('created_at', 0),
        )
        DOCUMENT_CACHE.pop(oldest_key, None)


async def _fetch_documentation_page(url: str) -> tuple[str, str]:
    """Fetch a documentation page and return raw text plus content type."""
    async with httpx.AsyncClient() as client:
        response = await client.get(
            url,
            follow_redirects=True,
            headers=DEFAULT_HEADERS,
            timeout=30,
        )

    if response.status_code >= 400:
        raise ValueError(f'Failed to fetch {url} - status code {response.status_code}')

    response.encoding = 'utf-8'
    return response.text, response.headers.get('content-type', '')


async def _load_document_cache_entry(url: str) -> dict[str, Any]:
    """Load and cache a documentation page."""
    now = time.time()
    cache_key = _normalize_documentation_url(url)
    cached = DOCUMENT_CACHE.get(cache_key)
    if cached and _is_cache_entry_fresh(cached, now):
        return cached

    page_raw, content_type = await _fetch_documentation_page(url)
    if is_html_content(page_raw, content_type):
        markdown_text = extract_content_from_html(page_raw)
    else:
        markdown_text = page_raw

    lines = markdown_text.splitlines()
    base_page_url = _base_page_url(url)
    entry = {
        'source_url': url,
        'base_page_url': base_page_url,
        'lines': lines,
        'table_of_contents': _extract_table_of_contents(lines),
        # 'related_links': _extract_markdown_links(base_page_url, markdown_text),
        'created_at': now
    }

    _prune_document_cache(now)
    DOCUMENT_CACHE[cache_key] = entry
    return entry


def _format_line_window(entry: dict[str, Any], start_index: int, max_lines: int) -> str:
    """Format cached documentation as a line-window JSON response."""
    lines = entry['lines']
    total_lines = len(lines)
    start_line = min(start_index, total_lines)
    end_line = min(start_line + max_lines, total_lines)
    returned_lines = lines[start_line:end_line]
    remaining_lines = max(total_lines - end_line, 0)

    result: dict[str, Any] = {
        'stats': {
            'total_lines': total_lines,
            'total_words': _word_count(lines),
            'start_line': start_index,
            'returned_lines': len(returned_lines),
            'remaining_lines': remaining_lines,
            'remaining_words': _word_count(lines[end_line:]),
        }
    }

    if start_index == 0:
        result['table_of_contents'] = entry['table_of_contents']
        # result['related_links'] = entry['related_links']

    result["content"] ='\n'.join(returned_lines)

    return json.dumps(result, ensure_ascii=False)


async def format_documentation_result(url: str, start_index: int, max_lines: int) -> str:
    """Fetch or read cached documentation and return a line-window JSON response."""
    cache_entry = await _load_document_cache_entry(url)
    return _format_line_window(cache_entry, start_index, max_lines)
