"""A-8: deterministic evaluation metrics (the AI-judge metrics run in scripts/run_evals.py)."""
import pytest

from premier_analytics.evals import detect_language, flesch_reading_ease, mode_gap, number_density


def test_number_density_counts_digit_runs_per_100_chars():
    text = "Northgate lead 1-0 after 23 shots and 2.15 xG"
    assert number_density(text) == pytest.approx(100 * 4 / len(text))
    assert number_density("What a goal!") == 0


def test_flesch_scores_simple_text_higher_than_dense_text():
    simple = "What a goal. Greaves hits it hard. The fans love it."
    dense = "Northgate's sustained territorial dominance, quantified by an overwhelming field-tilt differential, culminated inevitably."
    assert flesch_reading_ease(simple) > flesch_reading_ease(dense) + 30


@pytest.mark.parametrize("text, lang", [
    ("Kai Greaves gives Northgate the lead with a fine finish", "en"),
    ("Kai Greaves adelanta al Northgate con un gran disparo desde el área", "es"),
    ("Kai Greaves يمنح Northgate التقدم بتسديدة رائعة", "ar"),
])
def test_detect_language(text, lang):
    assert detect_language(text) == lang


def test_mode_gap_checks_analysts_get_more_numbers_and_fans_simpler_text():
    fan = {"headline": "Northgate strike first!", "body": "Kai Greaves gives them the lead with a lovely finish."}
    analyst = {"headline": "Greaves 1-0", "body": "Northgate lead 1-0: 0.23 xG chance, 6 shots, 0.47 xG in total."}
    gap = mode_gap(fan, analyst)
    assert gap["more_numbers"] and gap["simpler_for_fans"]


def test_minutes_and_scorelines_are_not_statistics_for_fans():
    from premier_analytics.evals import is_plain_for_fans
    assert is_plain_for_fans("Greaves scores at 42' to make it 1-0 in the last 10 minutes")
    assert is_plain_for_fans("Greaves fires in from 8 metres")
    assert not is_plain_for_fans("Greaves hits it at 111 km/h with 84% of passes in the final third")
