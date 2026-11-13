import importlib.util
import sys
from pathlib import Path

import pytest

# policy.py lives with the example server in docs/
_path = Path(__file__).resolve().parents[2] / "docs" / "local-image-server" / "policy.py"
_spec = importlib.util.spec_from_file_location("local_image_policy", _path)
policy = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = policy
_spec.loader.exec_module(policy)

P = policy.load()


@pytest.mark.parametrize(
    "prompt, rule, scene",
    [
        ("Prophet Muhammad in Mecca", "prophet_muhammad", "desert valley"),
        ("the Prophet's mosque in Medina", "prophet_muhammad", "palm oasis"),
        ("Muhammad's teachings", "prophet_muhammad", "desert landscape"),
        ("Prophet Muhammad receiving revelation in cave Hira", "prophet_muhammad", "cave entrance"),
        ("God creating the world", "god", "rays of soft light"),
        ("Allah's mercy", "god", "rays of soft light"),
        ("Prophet Musa at Mount Sinai", "islamic_prophets", "granite desert mountains"),
        ("Yusuf in the Quran", "islamic_prophets", "desert landscape"),
        ("Abu Bakr leading the community", "companions_and_family_of_the_prophet", "desert landscape"),
        ("Baha'u'llah in exile", "bahai_central_figures", "terraced gardens"),
        ("Guru Nanak travelling", "sikh_gurus", "golden temple"),
        ("Holocaust survivors", "atrocities", "memorial with candles"),
        ("starving children in a refugee camp", "children_in_distress", "worn toy"),
        ("President Biden giving a speech", "living_public_figures", "government building"),
    ],
)
def test_replaced_with_people_free_scene(prompt, rule, scene):
    r = P.apply(prompt)
    assert rule in r.rules
    assert scene in r.prompt
    assert r.no_people
    assert "person" in r.negative


@pytest.mark.parametrize(
    "prompt, rule, expected",
    [
        ("Jesus teaching on a hill", "revered_figures", "depicted reverently"),
        ("Moses parting the Red Sea", "revered_figures", "depicted reverently"),
        ("Lord Shiva meditating", "revered_figures", "depicted reverently"),
        ("Buddha statue in a temple", "revered_figures", "depicted reverently"),
        ("Quran on a wooden stand", "holy_books", "shown closed"),
        ("Arabic calligraphy in a mosque", "sacred_script", "ornate geometric patterns in a mosque"),
    ],
)
def test_kept_but_adjusted(prompt, rule, expected):
    r = P.apply(prompt)
    assert rule in r.rules
    assert expected in r.prompt
    assert not r.no_people


@pytest.mark.parametrize(
    "prompt",
    [
        "Mansa Musa pilgrimage to Mecca",
        "statue of the Greek god Zeus",
        "Isaac Newton under an apple tree",
        "Battle of Badr cavalry charge",
        "spice market in medieval Baghdad",
    ],
)
def test_unrelated_prompts_unchanged(prompt):
    r = P.apply(prompt)
    assert r.rules == []
    assert r.prompt == prompt
    assert "gore" in r.negative


def test_shared_prophets_off_by_default():
    assert "islamic_prophets_english_names" not in [r["name"] for r in P.rules]


def test_policy_can_be_switched_off():
    assert policy.load("off") is None
