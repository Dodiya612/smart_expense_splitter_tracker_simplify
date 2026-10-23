"""Export OpenAPI specification to a formatted JSON file."""

import argparse
import json
import sys
from pathlib import Path

# Add backend directory to sys.path so app modules are resolvable
BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.main import app  # noqa: E402


def export_openapi(output_path: Path) -> Path:
    """Generate and export the application's OpenAPI schema."""
    schema = app.openapi()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(schema, f, indent=2)
    return output_path


def main():
    parser = argparse.ArgumentParser(
        description="Export Coinscious FastAPI OpenAPI specification."
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=BACKEND_DIR / "openapi.json",
        help=(
            "Target output file path for the OpenAPI JSON "
            "(default: backend/openapi.json)"
        ),
    )
    args = parser.parse_args()

    out_file = export_openapi(args.output.resolve())
    print(f"[SUCCESS] Successfully exported OpenAPI specification to: {out_file}")


if __name__ == "__main__":
    main()
