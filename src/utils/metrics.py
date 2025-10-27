# src/utils/metrics.py
import time
from collections import defaultdict

# Implementasi sederhana untuk metrik
metrics_data = defaultdict(lambda: {"count": 0, "total_time": 0.0, "value": 0}) # Tambah 'value' untuk counter

def record_latency(metric_name, start_time):
    """Mencatat latensi untuk sebuah operasi."""
    duration = time.time() - start_time
    metrics_data[metric_name]["count"] += 1
    metrics_data[metric_name]["total_time"] += duration

# TAMBAHKAN FUNGSI INI
def increment_counter(metric_name, value=1):
    """Menambah nilai sebuah counter."""
    metrics_data[metric_name]["value"] += value

def get_metrics():
    """Mendapatkan metrik yang terkumpul."""
    report = {}
    for name, data in metrics_data.items():
        if data["count"] > 0: # Ini metrik latensi
            avg_latency = data["total_time"] / data["count"]
            report[name] = {
                "requests_count": data["count"],
                "average_latency_ms": avg_latency * 1000
            }
        elif data["value"] > 0: # Ini metrik counter
             report[name] = {"count": data["value"]}
        # Tambahkan perhitungan cache hit rate jika data tersedia
        
    # Hitung Cache Hit Rate
    cache_hits = metrics_data["cache_hits"]["value"]
    cache_gets = metrics_data["cache_get_requests"]["value"] # atau metrics_data["cache_get"]["count"] jika pakai record_latency
    if cache_gets > 0:
         hit_rate = (cache_hits / cache_gets) * 100
         report["cache_hit_rate_percent"] = round(hit_rate, 2)
    else:
         report["cache_hit_rate_percent"] = 0

    return report