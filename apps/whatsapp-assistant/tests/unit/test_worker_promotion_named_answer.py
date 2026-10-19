"""Typing a name at "is it the same person?" (owner's decision, 19 Oct): the
look-alike's own name = a new person; the existing worker's name = the same one."""

from workflows.worker_promotion.nodes import _named_answer

HELD = {"name": "Ravi", "_similar_to": "Ravi Kumar"}


def test_the_new_name_means_a_new_person():
    assert _named_answer("Ravi", HELD) == "new"
    assert _named_answer("  ravi ", HELD) == "new"


def test_the_existing_name_means_the_same_person():
    assert _named_answer("Ravi Kumar", HELD) == "same"


def test_anything_else_is_not_an_answer():
    assert _named_answer("Anil", HELD) is None
    assert _named_answer("", HELD) is None
    assert _named_answer("Ravi", {"name": "Ravi", "_similar_to": "Ravi"}) is None
