import subprocess
import time

from fastapi import Request
from prometheus_client import CONTENT_TYPE_LATEST, REGISTRY, Counter, Histogram, generate_latest
from prometheus_client.core import GaugeMetricFamily
from prometheus_client.registry import Collector
from starlette.responses import Response

# --- Метрики гейтвея (их будет собирать Prometheus) ---

# Сколько HTTP-запросов пришло: по адресу, методу и коду ответа
HTTP_REQUESTS = Counter("gateway_http_requests_total", "HTTP-запросы к гейтвею", ["path", "method", "status"])
# Сколько секунд занял запрос (гистограмма: можно посчитать среднее и 95-й процентиль)
HTTP_LATENCY = Histogram(
    "gateway_http_request_seconds", "Время ответа гейтвея, сек", ["path"],
    buckets=(0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 30, 60),
)
# LLM-токены по модели: input — вопрос, output — ответ
LLM_TOKENS = Counter("gateway_llm_tokens_total", "LLM-токены", ["model", "direction"])
# Сколько ПД спрятал Guard: на входе (input) и на выходе (output), по типу
PII_MASKED = Counter("gateway_pii_masked_total", "Замаскированные ПД", ["stage", "kind"])
# Сколько раз ответила запасная модель
FALLBACKS = Counter("gateway_fallbacks_total", "Ответы запасной моделью", ["requested", "answered"])


def record_pii(stage: str, labels: list[str]) -> None:
    """[PHONE_1], [OUT_EMAIL_2] → +1 к счётчику нужного типа."""
    for label in labels:
        kind = label.strip("[]").removeprefix("OUT_").rsplit("_", 1)[0]
        PII_MASKED.labels(stage=stage, kind=kind).inc()


async def metrics_middleware(request: Request, call_next):
    """Замеряет каждый запрос: время и код ответа."""
    start = time.perf_counter()
    response = await call_next(request)
    route = request.scope.get("route")
    # Шаблон адреса (/admin/models/{model}/down), а не сам адрес — иначе меток станет бесконечно много
    path = route.path if route else "other"
    if path != "/metrics":
        HTTP_REQUESTS.labels(path=path, method=request.method, status=response.status_code).inc()
        HTTP_LATENCY.labels(path=path).observe(time.perf_counter() - start)
    return response


# --- Видеокарта: читаем nvidia-smi в момент, когда Prometheus приходит за метриками ---

GPU_QUERY = "utilization.gpu,memory.used,memory.total,temperature.gpu,power.draw"


def to_float(value: str) -> float | None:
    """'45' → 45.0; '[N/A]' (карта не сообщает) → None."""
    try:
        return float(value)
    except ValueError:
        return None


class GpuCollector(Collector):
    """Свой «сборщик» метрик: при каждом опросе спрашивает nvidia-smi о загрузке GPU."""

    def collect(self):
        try:
            out = subprocess.run(
                ["nvidia-smi", f"--query-gpu={GPU_QUERY}", "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=5, check=True,
            ).stdout
        except (OSError, subprocess.SubprocessError):
            return  # нет nvidia-smi или ошибка — просто не отдаём метрики GPU
        util, used, total, temp, power = (to_float(v.strip()) for v in out.splitlines()[0].split(","))
        metrics = [
            ("gpu_utilization_percent", "Загрузка GPU, %", util),
            ("gpu_memory_used_mb", "Занято видеопамяти, МБ", used),
            ("gpu_memory_total_mb", "Всего видеопамяти, МБ", total),
            ("gpu_temperature_celsius", "Температура GPU, °C", temp),
            ("gpu_power_watts", "Потребление GPU, Вт", power),
        ]
        for name, help_text, value in metrics:
            if value is not None:
                yield GaugeMetricFamily(name, help_text, value=value)


REGISTRY.register(GpuCollector())


def metrics_endpoint() -> Response:
    """Отдаёт все метрики в текстовом формате Prometheus."""
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)