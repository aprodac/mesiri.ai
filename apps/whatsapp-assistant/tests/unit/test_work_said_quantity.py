"""Live gate 29 Oct, case 2: a figure the model left out of save_work_done is taken
from the words ("wall putty 200 sqft" lost its 200 sqft on the card)."""

from runtime.agent.toolbox import with_said_quantity

PUTTY = {"narrative": "ground floor wall putty 200 sqft", "work_type": "wall putty", "location": "ground floor"}


def test_a_figure_left_out_is_taken_from_the_narrative():
    args = with_said_quantity("Green Villa ground floor wall putty 200 sqft", PUTTY)
    assert args["quantities"] == [{"work_type": "wall putty", "quantity": 200, "unit": "sqft"}]


def test_the_message_is_used_when_the_narrative_has_no_figure():
    args = with_said_quantity("tiling 12.5 sq m done", {"narrative": "tiling done", "work_type": "tiling"})
    assert args["quantities"] == [{"work_type": "tiling", "quantity": 12.5, "unit": "sq m"}]


def test_quantities_the_model_gave_are_kept():
    given = {**PUTTY, "quantities": [{"quantity": 180, "unit": "sqft"}]}
    assert with_said_quantity("wall putty 200 sqft", given) is given


def test_two_figures_in_the_message_are_not_shared_between_works():
    args = {"narrative": "tiling done", "work_type": "tiling"}
    assert with_said_quantity("tiling 200 sqft, plastering 100 sqft", args) is args


def test_people_floors_and_percents_are_not_quantities():
    for text in ("5 mason 3 helper, 2nd floor tiling", "tiling 70% aayi", "3 masons today"):
        args = {"narrative": text, "work_type": "tiling"}
        assert with_said_quantity(text, args) is args, text
