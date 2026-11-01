"""Item 195 bug 4: the saved work card shows the work quantity it saved (it is under `quantities`)."""

from channel.receipt import data


def test_quantity_said_reads_the_quantities_list():
    fields = {"quantities": [{"quantity": 100, "unit": "sq ft", "work_type": "brickwork"}]}
    assert data._quantity_said(fields) == ("100", "sq ft")
    assert data._quantity_said({"narrative": "brickwork"}) is None
