from quality.metrics import evaluate

# «Ворота качества»: если правка ухудшит Guard ниже порога — тесты упадут


def test_recall_structured():
    assert evaluate()["recall_structured"] >= 0.95


def test_false_positive_rate():
    assert evaluate()["fpr"] <= 0.05


def test_latency():
    assert evaluate()["latency_avg_ms"] < 5