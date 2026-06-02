# MCP Registry Swagger Artifacts

This directory contains a shareable Swagger UI page and its companion OpenAPI JSON
for the MCP Registry REST API work on the current branch.

## Generate / refresh

From the `mlflow` repo root:

```bash
python docs/api_reference/mcp_api_docs.py
```

Or from `docs/api_reference`:

```bash
make mcp-api-docs
```

## Open locally

Serve the `docs/api_reference` directory and open the MCP page:

```bash
cd docs/api_reference
python -m http.server
```

Then open:

```text
http://localhost:8000/mcp_registry/api.html
```

## Notes

- `api.html` is a small Swagger UI wrapper that loads `./openapi.json`
- `openapi.json` is generated from the current branch's full MLflow FastAPI app
- MCP endpoints are under `/ajax-api/3.0/mlflow/mcp-servers...`
