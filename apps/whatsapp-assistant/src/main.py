"""WhatsApp assistant application entrypoint."""

from __future__ import annotations

import uvicorn

from runtime.lifecycle import create_app

raise RuntimeError("deliberately broken build: proves the staging gate stops it (3 Nov, never on main)")
app = create_app()


def main() -> None:
    """Run the WhatsApp assistant HTTP server."""
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=False)


if __name__ == "__main__":
    main()
