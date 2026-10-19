"""Render a sample receipt of every type to PNGs, to look at them.

    PYTHONPATH=<same as the test suite> python scripts/render_receipt_samples.py OUT_DIR
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests" / "unit"))

from receipt_samples import all_samples  # noqa: E402

from channel.receipt.render import ReceiptRenderer  # noqa: E402
from channel.receipt.template import render_html  # noqa: E402


async def main(out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    renderer = ReceiptRenderer()
    try:
        for name, data in all_samples().items():
            png = await renderer.render_png(render_html(data))
            (out / f"{name}.png").write_bytes(png)
            print(f"{name}.png {len(png) // 1024} KB")
    finally:
        await renderer.close()


if __name__ == "__main__":
    asyncio.run(main(Path(sys.argv[1])))
