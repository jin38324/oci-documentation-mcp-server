"""OHC Search API client for OCI documentation."""

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

OHC_SEARCH_API_URL = 'https://docs.oracle.com/apps/ohcsearchclient/api/v1/search/pages/'

OHC_SEARCH_HEADERS = {
    'user-agent': "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36",
    'accept': 'application/json',
}

MAX_PAGE_SIZE = 20

class OHCSearchError(RuntimeError):
    """Raised when the OHC Search API cannot return usable search results."""


class OHCPageSearchParams(BaseModel):
    """Query parameters for the OHC pages endpoint."""

    model_config = ConfigDict(extra='forbid')

    q: str = Field(
        min_length=1,
        description=(
            'User search terms for the OHC pages endpoint. OHC tokenizes words and '
            'punctuation, and quoted text can be used for required phrases. The API also '
            'supports inline filters such as site:docs.oracle.com/en/cloud, before:2024, '
            'before:2024-01-30, after:2023, and after:2023-06-01.'
        ),
    )
    size: int = Field(
        default=5,
        ge=1,
        le=MAX_PAGE_SIZE,
        description=(
            'Number of outer page results to return for this page of search results. '
            'The OHC pages endpoint defaults to 10 and is limited to 100.'
        ),
    )
    pg: int = Field(
        default=1,
        ge=1,
        description=(
            'Search result page number to request. OHC page numbers start at 1; use '
            'pg=2 with the same q and size to retrieve the next page.'
        ),
    )
    lang: str = Field(
        default="en",
        description=(
            'Language code for indexed OHC records. Values are case-sensitive and lower '
            'case. Examples: en, ja, ko, zh-cn, zh-tw, pt-br, fr-ca.'
        ),
    )
    product: str = Field(
        default="",
        min_length=1,
        description=(
            'Product hierarchy filter matched against OHC lineage_ids. Documentation '
            'hierarchy values usually start with en/. Multiple values may be comma '
            'separated when broader matching is needed. Examples: '
            'en/cloud/oracle-cloud-infrastructure, '
            'en/cloud/oracle-cloud-infrastructure/object-storage, '
            'en/database/oracle/oracle-database/19.'
        ),
    )

    @field_validator('q')
    @classmethod
    def strip_query(cls, value: str) -> str:
        """Normalize user search input before sending it to OHC."""
        normalized = value.strip()
        if not normalized:
            raise ValueError('Search query cannot be empty')
        return normalized

    @classmethod
    def from_search(cls, search_phrase: str, limit: int) -> 'OHCPageSearchParams':
        """Create validated pages endpoint parameters from MCP search inputs."""
        page_size = max(1, min(limit, MAX_PAGE_SIZE))
        return cls(q=search_phrase, size=page_size)

    def to_query_params(self) -> dict[str, str | int]:
        """Return parameters in the wire shape expected by the OHC Search API."""
        params = {
            'q': self.q,
            'size': self.size,
            'pg': self.pg,
            'lang': self.lang
        }
        if self.product:
            params['product'] = self.product
        
        return params

class OHCSearchPagination(BaseModel):
    """OHC search pagination."""
    model_config = ConfigDict(extra='ignore')
    page: int | None = None
    pageSize: int | None = None
    totalPages: int | None = None

class OHCSearchResult(BaseModel):
    """OHC search result."""
    model_config = ConfigDict(extra='ignore')
    url: str
    title: str
    description: str | None = None

class OHCSearchResults(BaseModel):
    """OHC search results."""
    model_config = ConfigDict(extra='ignore')
    pagination: OHCSearchPagination | None = None
    results: list[OHCSearchResult] = []

def _extract_ohcresponse(response: dict) -> OHCSearchResults:
    """Extract OHC search results from response."""
    pagination = OHCSearchPagination(
        page=response.get('pagination', {}).get('page'),
        pageSize=response.get('pagination', {}).get('pageSize'),
        totalPages=response.get('pagination', {}).get('totalPages'),
    )
    hits = response.get('hits', [])

    ohc_search_result = OHCSearchResults(
        pagination=pagination,
        results=[]
    )
    for hit in hits:
        ohc_search_result.results.append(
            OHCSearchResult(
                url=hit.get('_source', {}).get('url',""),
                title=hit.get('_source', {}).get('title',""),
                description=hit.get('highlight', {}).get('description',""),
            )
        )

    return ohc_search_result


async def search_oci_documentation(
    search_phrase: str,
    page_size: int = 3,
    page: int = 1,
    client: httpx.AsyncClient | None = None
) -> OHCSearchResults:
    """Search OCI documentation with the public OHC Search API."""
    try:
        search_params = OHCPageSearchParams(
            q=search_phrase,
            size=page_size,
            pg=page
        )
    except ValidationError as exc:
        raise OHCSearchError(f'OHC search parameters validation failed: {exc}') from exc

    async def fetch(active_client: httpx.AsyncClient) -> httpx.Response:
        try:
            return await active_client.get(
                OHC_SEARCH_API_URL,
                params=search_params.to_query_params(),
            )
        except httpx.HTTPError as exc:
            raise OHCSearchError(f'Failed to call OHC search API: {exc}') from exc

    if client is None:
        async with httpx.AsyncClient(headers=OHC_SEARCH_HEADERS, timeout=30) as active_client:
            response = await fetch(active_client)
    else:
        response = await fetch(client)

    if response.status_code < 200 or response.status_code >= 300:
        raise OHCSearchError(f'OHC search API returned status code {response.status_code}')

    try:
        payload = response.json()
    except ValueError as exc:
        raise OHCSearchError('OHC search API returned invalid JSON') from exc

    try:
        search_response = _extract_ohcresponse(payload)
        return search_response
    except ValidationError as exc:
        raise OHCSearchError(f'OHC search API response validation failed: {exc}') from exc

    
