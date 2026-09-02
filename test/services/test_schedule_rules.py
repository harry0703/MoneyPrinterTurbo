from datetime import date, datetime, time

import pytest

from app.services import schedule_rules


def test_once_returns_single_occurrence():
    result = schedule_rules.expand_occurrences(
        start_date=date(2026, 3, 5),
        time_of_day=time(9, 0),
        interval_type="once",
    )
    assert result == [datetime(2026, 3, 5, 9, 0)]


def test_daily_with_occurrence_count():
    result = schedule_rules.expand_occurrences(
        start_date=date(2026, 3, 5),
        time_of_day=time(9, 0),
        interval_type="daily",
        occurrence_count=3,
    )
    assert result == [
        datetime(2026, 3, 5, 9, 0),
        datetime(2026, 3, 6, 9, 0),
        datetime(2026, 3, 7, 9, 0),
    ]


def test_daily_with_end_date_inclusive():
    result = schedule_rules.expand_occurrences(
        start_date=date(2026, 3, 5),
        time_of_day=time(9, 0),
        interval_type="daily",
        end_date=date(2026, 3, 7),
    )
    assert result == [
        datetime(2026, 3, 5, 9, 0),
        datetime(2026, 3, 6, 9, 0),
        datetime(2026, 3, 7, 9, 0),
    ]


def test_daily_with_step_skips_days():
    result = schedule_rules.expand_occurrences(
        start_date=date(2026, 3, 5),
        time_of_day=time(9, 0),
        interval_type="daily",
        interval_step=2,
        occurrence_count=3,
    )
    assert result == [
        datetime(2026, 3, 5, 9, 0),
        datetime(2026, 3, 7, 9, 0),
        datetime(2026, 3, 9, 9, 0),
    ]


def test_weekly_advances_by_seven_days_times_step():
    result = schedule_rules.expand_occurrences(
        start_date=date(2026, 3, 5),  # a Thursday
        time_of_day=time(15, 0),
        interval_type="weekly",
        occurrence_count=3,
    )
    assert result == [
        datetime(2026, 3, 5, 15, 0),
        datetime(2026, 3, 12, 15, 0),
        datetime(2026, 3, 19, 15, 0),
    ]


def test_weekly_with_step_two_skips_a_week():
    result = schedule_rules.expand_occurrences(
        start_date=date(2026, 3, 5),
        time_of_day=time(9, 0),
        interval_type="weekly",
        interval_step=2,
        occurrence_count=2,
    )
    assert result == [
        datetime(2026, 3, 5, 9, 0),
        datetime(2026, 3, 19, 9, 0),
    ]


def test_monthly_keeps_day_of_month():
    result = schedule_rules.expand_occurrences(
        start_date=date(2026, 1, 31),
        time_of_day=time(9, 0),
        interval_type="monthly",
        occurrence_count=3,
    )
    # Fev/2026 nao tem dia 31 (nao bissexto): cai no ultimo dia do mes.
    assert result == [
        datetime(2026, 1, 31, 9, 0),
        datetime(2026, 2, 28, 9, 0),
        datetime(2026, 3, 31, 9, 0),
    ]


def test_exceptions_remove_matching_dates():
    result = schedule_rules.expand_occurrences(
        start_date=date(2026, 3, 5),
        time_of_day=time(9, 0),
        interval_type="daily",
        occurrence_count=3,
        exceptions={date(2026, 3, 6)},
    )
    assert result == [
        datetime(2026, 3, 5, 9, 0),
        datetime(2026, 3, 7, 9, 0),
    ]


def test_extra_dates_are_added_and_sorted():
    result = schedule_rules.expand_occurrences(
        start_date=date(2026, 3, 5),
        time_of_day=time(9, 0),
        interval_type="once",
        extra_dates=[datetime(2026, 3, 1, 8, 0)],
    )
    assert result == [
        datetime(2026, 3, 1, 8, 0),
        datetime(2026, 3, 5, 9, 0),
    ]


def test_requires_end_date_or_occurrence_count_for_recurring_rules():
    with pytest.raises(ValueError):
        schedule_rules.expand_occurrences(
            start_date=date(2026, 3, 5),
            time_of_day=time(9, 0),
            interval_type="daily",
        )


def test_rejects_unknown_interval_type():
    with pytest.raises(ValueError):
        schedule_rules.expand_occurrences(
            start_date=date(2026, 3, 5),
            time_of_day=time(9, 0),
            interval_type="yearly",
        )


def test_rejects_non_positive_interval_step():
    with pytest.raises(ValueError):
        schedule_rules.expand_occurrences(
            start_date=date(2026, 3, 5),
            time_of_day=time(9, 0),
            interval_type="daily",
            occurrence_count=2,
            interval_step=0,
        )


def test_occurrence_count_is_capped_to_a_sane_maximum():
    with pytest.raises(ValueError):
        schedule_rules.expand_occurrences(
            start_date=date(2026, 3, 5),
            time_of_day=time(9, 0),
            interval_type="daily",
            occurrence_count=schedule_rules.MAX_OCCURRENCES + 1,
        )
