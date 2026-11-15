"""The translations match strings.json, which hassfest checks.

hassfest only validates strings.json; en.json has to be an exact copy and
every other language needs the same keys and placeholders.
"""
import json
import re
from pathlib import Path

import pytest

COMPONENT = Path(__file__).parent.parent / "custom_components" / "wow_blizzard"
STRINGS = json.loads((COMPONENT / "strings.json").read_text(encoding="utf-8"))
LANGUAGES = sorted(p.stem for p in (COMPONENT / "translations").glob("*.json") if p.stem != "en")


def _flatten(data, prefix=""):
    """{"a": {"b": "x"}} -> {"a.b": "x"}."""
    items = {}
    for key, value in data.items():
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            items.update(_flatten(value, path))
        else:
            items[path] = value
    return items


def _placeholders(text):
    return sorted(re.findall(r"\{(\w+)\}", text)) if isinstance(text, str) else []


def _load(language):
    return json.loads((COMPONENT / "translations" / f"{language}.json").read_text(encoding="utf-8"))


def test_english_is_strings_json():
    assert _load("en") == STRINGS


@pytest.mark.parametrize("language", LANGUAGES)
def test_language_has_every_key(language):
    expected = _flatten(STRINGS)
    actual = _flatten(_load(language))
    assert sorted(set(expected) - set(actual)) == [], "missing translations"
    assert sorted(set(actual) - set(expected)) == [], "translations without an English text"


@pytest.mark.parametrize("language", LANGUAGES)
def test_language_keeps_placeholders(language):
    expected = _flatten(STRINGS)
    actual = _flatten(_load(language))
    wrong = {
        key: (_placeholders(text), _placeholders(actual[key]))
        for key, text in expected.items()
        if key in actual and _placeholders(text) != _placeholders(actual[key])
    }
    assert wrong == {}
