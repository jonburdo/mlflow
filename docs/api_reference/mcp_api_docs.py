import json
from pathlib import Path

from mlflow.server.fastapi_app import create_fastapi_app

# This HTML mirrors the gateway Swagger wrapper, but points at the OpenAPI JSON
# generated from the main MLflow FastAPI app on the current branch.
API_HTML = """
<!DOCTYPE html>
<html>
  <head>
    <link
      type="text/css"
      rel="stylesheet"
      href="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui.css"
    />
    <link
      rel="shortcut icon"
      href="../theme/mlflow/static/favicon.ico"
    />
    <title>MLflow MCP Registry - Swagger UI</title>
  </head>
  <body>
    <div id="swagger-ui"></div>
    <script src="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui-bundle.js"></script>
    <script>
      const ui = SwaggerUIBundle({
        supportedSubmitMethods: [],
        url: "./openapi.json",
        dom_id: "#swagger-ui",
        layout: "BaseLayout",
        deepLinking: true,
        showExtensions: true,
        showCommonExtensions: true,
        oauth2RedirectUrl: window.location.origin + "/docs/oauth2-redirect",
        presets: [
          SwaggerUIBundle.presets.apis,
          SwaggerUIBundle.SwaggerUIStandalonePreset,
        ],
      });
    </script>
  </body>
</html>
"""


def main():
    docs_build = Path(__file__).resolve().parent / "mcp_registry"
    docs_build.mkdir(parents=True, exist_ok=True)

    app = create_fastapi_app()

    with docs_build.joinpath("openapi.json").open("w") as f:
        json.dump(app.openapi(), f, indent=2, sort_keys=True)
        f.write("\n")

    with docs_build.joinpath("api.html").open("w") as f:
        f.write(API_HTML)


if __name__ == "__main__":
    main()
