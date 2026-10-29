from workflows.material_inventory_query.nodes import generate_inventory_reply
from workflows.state import WorkflowGraphState


def test_generate_inventory_reply_single_material():
    state: WorkflowGraphState = {
        "collected_fields": {
            "material_name": "cement",
            "inventory_levels": [
                {
                    "material_name": "cement",
                    "unit": "bags",
                    "received": 50.0,
                    "used": 20.0,
                    "current_stock": 30.0,
                }
            ],
        }
    }

    result = generate_inventory_reply(state)
    prompt = result["pending_prompt"]

    assert "Cement" in prompt
    assert "In stock: 30 bags" in prompt
    assert "Received  50 bags" in prompt
    assert "Used      20 bags" in prompt


def test_generate_inventory_reply_all_materials():
    state: WorkflowGraphState = {
        "collected_fields": {
            "inventory_levels": [
                {
                    "material_name": "cement",
                    "unit": "bags",
                    "received": 50.0,
                    "used": 20.0,
                    "current_stock": 30.0,
                },
                {
                    "material_name": "steel",
                    "unit": "kg",
                    "received": 100.0,
                    "used": 0.0,
                    "current_stock": 100.0,
                },
            ],
        }
    }

    result = generate_inventory_reply(state)
    prompt = result["pending_prompt"]

    assert "Cement" in prompt
    assert "Steel" in prompt
    assert "30 bags" in prompt
    assert "100 kg" in prompt


def test_generate_inventory_reply_no_data_for_named_material():
    state: WorkflowGraphState = {
        "collected_fields": {"material_name": "sand", "inventory_levels": []}
    }
    result = generate_inventory_reply(state)
    assert "sand" in result["pending_prompt"]
    assert "don't have" in result["pending_prompt"]


def test_generate_inventory_reply_no_data_at_all():
    state: WorkflowGraphState = {"collected_fields": {}}
    result = generate_inventory_reply(state)
    assert "don't have any recorded material stock" in result["pending_prompt"]


def test_fractional_quantity_formats_without_trailing_zero():
    state: WorkflowGraphState = {
        "collected_fields": {
            "material_name": "steel",
            "inventory_levels": [
                {
                    "material_name": "steel",
                    "unit": "kg",
                    "received": 12.5,
                    "used": 2.5,
                    "current_stock": 10.0,
                }
            ],
        }
    }
    result = generate_inventory_reply(state)
    prompt = result["pending_prompt"]
    assert "In stock: 10 kg" in prompt
    assert "Received  12.5 kg" in prompt
    assert "Used      2.5 kg" in prompt


def test_mat03_a_periods_reply_names_what_moved_and_the_stock_now():
    from workflows.material_inventory_query.nodes import _period_reply

    levels = [
        {"material_name": "cement", "unit": "bags", "current_stock": 495.0, "period_used": 10.0, "period_received": 0.0},
        {"material_name": "sand", "unit": "cum", "current_stock": 12.0, "period_used": 0.0, "period_received": 0.0},
        {"material_name": "steel", "unit": "kg", "current_stock": 900.0, "period_used": 0.0, "period_received": 400.0},
    ]
    one = _period_reply("yesterday (24 Oct)", levels[:1], "cement")
    assert one == "Yesterday (24 Oct): 10 bags cement used. 495 bags left now."
    many = _period_reply("this week", levels, None)
    assert "Cement — 10 bags used · 495 bags now" in many and "Steel — 400 kg received" in many
    assert "Sand" not in many  # nothing moved
    assert _period_reply("today", levels[1:2], None) == "Nothing was received or used today."
    assert "no sand was used or received" in _period_reply("today", levels[1:2], "sand")


def test_request114_a_question_about_used_leads_with_used_even_when_it_is_zero():
    from workflows.material_inventory_query.nodes import _period_reply

    cement = {"material_name": "cement", "unit": "bags", "current_stock": 545.0, "period_used": 0.0, "period_received": 50.0}
    # Live 25 Oct: "cement used yesterday?" answered only "50 bags received ... 545 left".
    assert _period_reply("yesterday (24 Oct)", [cement], "cement", "used") == (
        "Yesterday (24 Oct): No cement used. 50 bags received. 545 bags left now."
    )
    used = {**cement, "period_used": 10.0}
    assert _period_reply("yesterday (24 Oct)", [used], "cement", "used") == (
        "Yesterday (24 Oct): 10 bags cement used. 50 bags received. 545 bags left now."
    )
    assert _period_reply("today", [cement], "cement", "received") == "Today: 50 bags cement received. 545 bags left now."
    nothing = {**cement, "period_received": 0.0}
    assert _period_reply("today", [nothing], "cement", "used") == "Today: No cement used. 545 bags left now."
    # No side asked: the answer is as before.
    assert _period_reply("today", [cement], "cement") == "Today: 50 bags cement received. 545 bags left now."


def test_request114_the_used_side_reaches_the_workflow_from_the_tool():
    from runtime.agent.tools import to_candidate

    candidate = to_candidate("query_materials", {"material": "cement", "date": "yesterday", "asking": "used"}, None)
    assert candidate.fields["asking"] == "used"
    other = to_candidate("query_materials", {"material": "cement", "asking": "sideways"}, None)
    assert "asking" not in other.fields
