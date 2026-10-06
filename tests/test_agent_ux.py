from press_chrome.agent_ux import compact_rows, select_fields, wants_json


def test_select_fields():
    rows = [{"id": 1, "title": "a", "url": "u"}]
    assert select_fields(rows, "id,title") == [{"id": 1, "title": "a"}]


def test_compact_rows():
    rows = [{"id": 1, "title": "a", "url": "u", "extra": 9}]
    assert compact_rows(rows, ["id", "title"]) == [{"id": 1, "title": "a"}]
