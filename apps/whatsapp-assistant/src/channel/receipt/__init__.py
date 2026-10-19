"""Post-confirmation receipt image -- one shared visual template for every
confirmed record type. See AGENTS.md's Module Placement Log for the
architecture decision (Python + playwright, in-process, no new service)."""

from __future__ import annotations

from .builder import RecordReceiptBuilder
from .data import ReceiptData, build_receipt_data, combine_receipts
from .render import ReceiptRenderer
from .template import render_html

__all__ = [
    "ReceiptData",
    "build_receipt_data",
    "combine_receipts",
    "ReceiptRenderer",
    "render_html",
    "RecordReceiptBuilder",
]
