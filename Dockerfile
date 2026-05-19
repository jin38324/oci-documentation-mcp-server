FROM python:3.13-slim-trixie

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

ENV PYTHONUNBUFFERED=1
ENV UV_COMPILE_BYTECODE=1
ENV UV_LINK_MODE=copy
ENV FASTMCP_LOG_LEVEL=ERROR

COPY pyproject.toml uv.lock README.md ./
COPY oci_documentation_mcp_server ./oci_documentation_mcp_server

RUN /bin/uv sync --frozen --no-dev

EXPOSE 8888

CMD ["/bin/uv", "run", "python", "-m", "oci_documentation_mcp_server.server", "--sse", "--port", "8888"]
