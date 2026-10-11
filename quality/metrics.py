import time

from guard.pii import mask_pii
from quality.pii_dataset import SAMPLES

# Типы ПД, которые Guard обязан ловить сейчас (имена пока не умеем — их считаем отдельно)
STRUCTURED = {"PHONE", "EMAIL", "CARD", "IP"}


def label_kind(label: str) -> str:
    """[PHONE_1] → PHONE"""
    return label.strip("[]").rsplit("_", 1)[0]


def evaluate() -> dict:
    """Прогоняет Guard по контрольному набору и считает recall, FPR и задержку."""
    per_kind: dict[str, dict[str, int]] = {}  # тип → {"tp": нашли, "fn": пропустили}
    false_entities = 0                         # нашли то, чего нет в разметке
    negatives = flagged_negatives = 0          # чистые фразы / из них ложно «нашли ПД»
    durations_ms = []

    for text, expected in SAMPLES:
        start = time.perf_counter()
        _, found = mask_pii(text)
        durations_ms.append((time.perf_counter() - start) * 1000)

        found_pairs = {(label_kind(label), value) for label, value in found.items()}
        for kind, value in expected:
            stats = per_kind.setdefault(kind, {"tp": 0, "fn": 0})
            if (kind, value) in found_pairs:
                stats["tp"] += 1
            else:
                stats["fn"] += 1
        false_entities += len(found_pairs - set(expected))

        if not expected:
            negatives += 1
            if found:
                flagged_negatives += 1

    tp = sum(s["tp"] for k, s in per_kind.items() if k in STRUCTURED)
    fn = sum(s["fn"] for k, s in per_kind.items() if k in STRUCTURED)
    return {
        "per_kind": {k: s["tp"] / (s["tp"] + s["fn"]) for k, s in sorted(per_kind.items())},
        "recall_structured": tp / (tp + fn),
        "fpr": flagged_negatives / negatives,
        "false_entities": false_entities,
        "latency_avg_ms": sum(durations_ms) / len(durations_ms),
        "latency_max_ms": max(durations_ms),
    }


if __name__ == "__main__":
    # Отчёт: python -m quality.metrics
    m = evaluate()
    print(f"Фраз в наборе: {len(SAMPLES)}\n")
    print("Recall по типам:")
    for kind, recall in m["per_kind"].items():
        mark = "" if kind in STRUCTURED else "  (пока не ловим)"
        print(f"  {kind:<6} {recall:6.0%}{mark}")
    print(f"\nRecall (телефон, почта, карта, IP): {m['recall_structured']:.0%}  цель ≥ 95%")
    print(f"FPR (чистые фразы с ложным срабатыванием): {m['fpr']:.0%}  цель ≤ 5%")
    print(f"Лишних находок всего: {m['false_entities']}")
    print(f"Задержка Guard: в среднем {m['latency_avg_ms']:.3f} мс, максимум {m['latency_max_ms']:.3f} мс")