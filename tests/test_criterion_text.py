"""Tests for criterion text field names.

The story task never mandated a field name, so a real agent run
wrote acceptance criteria with "description", not "text". That
content is complete; only the field name differs, so validation
must accept both. An id with neither is still invalid.
"""

from scrum_crew.pipeline import criterion_text, validate_story


def story(criteria):
    return {
        "id": "ST001",
        "title": "Home Page Hero Section",
        "description": "Display hero video with fallback image.",
        "acceptance_criteria": criteria,
        "dependencies": [],
        "risks": [],
        "testable": True,
    }


def test_description_form_is_valid():
    criteria = [{"id": "AC001",
                 "description": "Hero video plays with fallback image"}]
    assert criterion_text(criteria[0]) == \
        "Hero video plays with fallback image"
    assert validate_story(story(criteria)) == []


def test_text_form_still_valid():
    criteria = [{"id": "AC001", "text": "Hero video plays"}]
    assert criterion_text(criteria[0]) == "Hero video plays"
    assert validate_story(story(criteria)) == []


def test_id_only_criterion_still_fails():
    criteria = [{"id": "AC001"}]
    assert criterion_text(criteria[0]) is None
    errors = validate_story(story(criteria))
    assert errors and "AC001" in errors[0]
