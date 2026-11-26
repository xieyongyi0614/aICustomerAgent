from __future__ import annotations

import pytest

from app.services.ledger import ensure_user_bootstrap
from app.services.ledger.category_metrics import Sample, evaluate
from tests.v40.fixtures.ledger_category_samples import LEDGER_CATEGORY_SAMPLES

USER = "cat-metric-user"


@pytest.fixture()
def seeded():
    ensure_user_bootstrap(USER)
    return USER


def test_sample_set_size():
    assert len(LEDGER_CATEGORY_SAMPLES) >= 120


def test_hit_rate_and_consistency(seeded):
    samples = [Sample(hint=h, expected_name=e) for h, e in LEDGER_CATEGORY_SAMPLES]
    report = evaluate(samples, user_id=seeded)
    assert report.consistent is True
    assert report.hit_rate >= 0.8
    assert report.fallback_rate <= 0.15


def test_same_hint_always_same_result(seeded):
    samples = [Sample(hint="快餐", expected_name="餐饮")] * 5
    report = evaluate(samples, user_id=seeded)
    assert report.consistent is True
    assert report.hits == 5
