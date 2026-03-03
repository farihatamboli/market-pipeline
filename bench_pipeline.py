"""
benchmarks/bench_pipeline.py — Latency profiling for the pipeline.

Measures:
  1. Signal detection throughput (signals/second)
  2. Per-detector latency breakdown
  3. Storage write/read latency
  4. End-to-end tick processing latency
  5. Memory usage under load

Run:
    python benchmarks/bench_pipeline.py
    python benchmarks/bench_pipeline.py --ticks 10000 --symbols 10

Output:
    - Console summary table
    - benchmarks/results/latest.json (machine-readable)
    - benchmarks/results/latest.png  (latency histogram)
"""

import sys
import time
import random
import argparse
import json
import statistics
import tracemalloc
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.fetcher  import Tick
from src.signals  import SignalDetector, SignalType
from src.storage  import DataStore


# ── Tick factory ──────────────────────────────────────────────────────────────

def make_ticks(n: int, symbol: str = "AAPL", base: float = 150.0) -> list[Tick]:
    ticks = []
    p = base
    now = datetime.utcnow()
    for i in range(n):
        p += random.gauss(0, base * 0.001)
        vol = int(random.lognormvariate(11, 0.8))
        ticks.append(Tick(
            symbol    = symbol,
            timestamp = now + timedelta(minutes=i),
            price     = round(p, 4),
            volume    = vol,
            open      = round(p - 0.1, 4),
            high      = round(p + abs(random.gauss(0, 0.2)), 4),
            low       = round(p - abs(random.gauss(0, 0.2)), 4),
            vwap      = round(p + random.gauss(0, 0.1), 4),
        ))
    return ticks


# ── Benchmark functions ───────────────────────────────────────────────────────

def bench_signal_detection(ticks: list[Tick], warmup: int = 20) -> dict:
    """Measure signal detection throughput and per-call latency."""
    detector = SignalDetector()
    latencies = []

    for i in range(warmup, len(ticks)):
        history = ticks[max(0, i - 50): i + 1]
        tick    = ticks[i]
        t0 = time.perf_counter_ns()
        detector.detect(tick, history)
        latencies.append((time.perf_counter_ns() - t0) / 1e6)  # → ms

    return {
        "name":        "Signal Detection",
        "n":           len(latencies),
        "mean_ms":     round(statistics.mean(latencies), 4),
        "median_ms":   round(statistics.median(latencies), 4),
        "p95_ms":      round(sorted(latencies)[int(len(latencies) * 0.95)], 4),
        "p99_ms":      round(sorted(latencies)[int(len(latencies) * 0.99)], 4),
        "max_ms":      round(max(latencies), 4),
        "throughput":  round(1000 / statistics.mean(latencies)),
    }


def bench_per_detector(ticks: list[Tick], warmup: int = 20) -> list[dict]:
    """Micro-benchmark each detector individually."""
    from src.signals import SignalDetector

    results = []
    detector = SignalDetector()
    methods  = [
        ("_check_price_spike",      "Price Spike"),
        ("_check_volume_surge",     "Volume Surge"),
        ("_check_volatility_burst", "Volatility Burst"),
        ("_check_vwap_deviation",   "VWAP Deviation"),
    ]

    for method_name, label in methods:
        fn  = getattr(detector, method_name)
        lats = []
        for i in range(warmup, len(ticks)):
            history = ticks[max(0, i - 50): i]
            tick    = ticks[i]
            # VWAP deviation only needs tick
            if method_name == "_check_vwap_deviation":
                t0 = time.perf_counter_ns()
                fn(tick)
                lats.append((time.perf_counter_ns() - t0) / 1e6)
            else:
                t0 = time.perf_counter_ns()
                fn(tick, history)
                lats.append((time.perf_counter_ns() - t0) / 1e6)

        results.append({
            "detector":  label,
            "mean_us":   round(statistics.mean(lats) * 1000, 2),
            "p99_us":    round(sorted(lats)[int(len(lats) * 0.99)] * 1000, 2),
        })
    return results


def bench_storage(ticks: list[Tick], db_path: str = ":memory:") -> dict:
    """Measure SQLite write and read latency."""
    import tempfile
    from pathlib import Path

    tmp = Path(tempfile.mktemp(suffix=".db"))
    store = DataStore(db_path=tmp)
    store.initialize()

    # Write latency
    write_lats = []
    for tick in ticks[:500]:
        t0 = time.perf_counter_ns()
        store.insert_tick(tick)
        write_lats.append((time.perf_counter_ns() - t0) / 1e6)

    # Read latency (after writes)
    read_lats = []
    for _ in range(200):
        t0 = time.perf_counter_ns()
        store.get_recent("AAPL", 50)
        read_lats.append((time.perf_counter_ns() - t0) / 1e6)

    store.close()
    try: tmp.unlink()
    except: pass

    return {
        "write": {
            "name":      "SQLite Write",
            "n":         len(write_lats),
            "mean_ms":   round(statistics.mean(write_lats), 4),
            "p99_ms":    round(sorted(write_lats)[int(len(write_lats)*0.99)], 4),
            "throughput":round(1000 / statistics.mean(write_lats)),
        },
        "read": {
            "name":    "SQLite Read (get_recent 50)",
            "n":       len(read_lats),
            "mean_ms": round(statistics.mean(read_lats), 4),
            "p99_ms":  round(sorted(read_lats)[int(len(read_lats)*0.99)], 4),
        }
    }


def bench_memory(ticks: list[Tick]) -> dict:
    """Measure memory usage of the full detection loop."""
    tracemalloc.start()
    detector = SignalDetector()
    history  = []

    for tick in ticks:
        history.append(tick)
        if len(history) > 50:
            history.pop(0)
        detector.detect(tick, history)

    current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    return {
        "current_kb": round(current / 1024, 1),
        "peak_kb":    round(peak / 1024, 1),
    }


def bench_e2e(ticks: list[Tick]) -> dict:
    """End-to-end: fetch → store → detect → (no alert dispatch)."""
    import tempfile
    from pathlib import Path

    tmp = Path(tempfile.mktemp(suffix=".db"))
    store    = DataStore(db_path=tmp)
    store.initialize()
    detector = SignalDetector()
    lats     = []

    for tick in ticks[:300]:
        t0 = time.perf_counter_ns()
        store.insert_tick(tick)
        history = store.get_recent(tick.symbol, 50)
        detector.detect(tick, history)
        lats.append((time.perf_counter_ns() - t0) / 1e6)

    store.close()
    try: tmp.unlink()
    except: pass

    return {
        "name":       "End-to-End (store+detect)",
        "n":          len(lats),
        "mean_ms":    round(statistics.mean(lats), 4),
        "median_ms":  round(statistics.median(lats), 4),
        "p95_ms":     round(sorted(lats)[int(len(lats) * 0.95)], 4),
        "p99_ms":     round(sorted(lats)[int(len(lats) * 0.99)], 4),
        "max_ms":     round(max(lats), 4),
        "throughput": round(1000 / statistics.mean(lats)),
    }


# ── Report ────────────────────────────────────────────────────────────────────

def print_table(rows: list[tuple], headers: list[str], title: str):
    widths = [max(len(h), max(len(str(r[i])) for r in rows)) for i, h in enumerate(headers)]
    sep    = "─" * (sum(widths) + len(widths) * 3 + 1)
    print(f"\n  {title}")
    print(f"  {sep}")
    print("  │ " + " │ ".join(h.ljust(w) for h, w in zip(headers, widths)) + " │")
    print(f"  {sep}")
    for row in rows:
        print("  │ " + " │ ".join(str(v).ljust(w) for v, w in zip(row, widths)) + " │")
    print(f"  {sep}")


def run_benchmarks(n_ticks: int = 2000, n_symbols: int = 5):
    random.seed(42)
    symbols = ["AAPL", "MSFT", "NVDA", "TSLA", "SPY"][:n_symbols]
    all_ticks = []
    for sym in symbols:
        all_ticks.extend(make_ticks(n_ticks, sym))

    print(f"""
╔══════════════════════════════════════════╗
║     Market Data Pipeline — Benchmarks    ║
╚══════════════════════════════════════════╝
  Ticks: {len(all_ticks):,} ({n_ticks:,} × {n_symbols} symbols)
  Python {sys.version.split()[0]}
""")

    # 1. Signal detection
    ticks_aapl = [t for t in all_ticks if t.symbol == "AAPL"]
    det = bench_signal_detection(ticks_aapl)
    print_table(
        [(det["n"], det["mean_ms"], det["median_ms"], det["p95_ms"], det["p99_ms"], det["max_ms"], f"{det['throughput']:,}/s")],
        ["N", "Mean ms", "P50 ms", "P95 ms", "P99 ms", "Max ms", "Throughput"],
        "Signal Detection Latency"
    )

    # 2. Per-detector
    per_det = bench_per_detector(ticks_aapl)
    print_table(
        [(r["detector"], r["mean_us"], r["p99_us"]) for r in per_det],
        ["Detector", "Mean µs", "P99 µs"],
        "Per-Detector Latency"
    )

    # 3. Storage
    stor = bench_storage(ticks_aapl)
    print_table(
        [
            ("Write", stor["write"]["mean_ms"], stor["write"]["p99_ms"], f"{stor['write']['throughput']:,}/s"),
            ("Read (get_recent 50)", stor["read"]["mean_ms"], stor["read"]["p99_ms"], "—"),
        ],
        ["Operation", "Mean ms", "P99 ms", "Throughput"],
        "SQLite Storage Latency"
    )

    # 4. E2E
    e2e = bench_e2e(ticks_aapl)
    print_table(
        [(e2e["n"], e2e["mean_ms"], e2e["p95_ms"], e2e["p99_ms"], f"{e2e['throughput']:,}/s")],
        ["N", "Mean ms", "P95 ms", "P99 ms", "Throughput"],
        "End-to-End Latency (store + detect)"
    )

    # 5. Memory
    mem = bench_memory(ticks_aapl)
    print(f"\n  Memory (detection loop over {len(ticks_aapl):,} ticks):")
    print(f"    Peak:    {mem['peak_kb']} KB")
    print(f"    Current: {mem['current_kb']} KB\n")

    # Save JSON results
    results_dir = Path(__file__).parent / "results"
    results_dir.mkdir(exist_ok=True)
    results = {
        "timestamp":        datetime.utcnow().isoformat(),
        "config":           {"n_ticks": n_ticks, "n_symbols": n_symbols},
        "signal_detection": det,
        "per_detector":     per_det,
        "storage":          stor,
        "e2e":              e2e,
        "memory":           mem,
    }
    out = results_dir / "latest.json"
    out.write_text(json.dumps(results, indent=2))
    print(f"  Results saved to {out}\n")

    # Optional: plot histogram
    try:
        import matplotlib.pyplot as plt
        import matplotlib
        matplotlib.use("Agg")

        fig, axes = plt.subplots(1, 2, figsize=(12, 4))
        fig.patch.set_facecolor("#0d1117")
        for ax in axes:
            ax.set_facecolor("#0d1117")
            ax.tick_params(colors="#5a7a96")
            for spine in ax.spines.values():
                spine.set_color("#1e2a36")

        # Re-generate latencies for histogram
        detector = SignalDetector()
        lats = []
        for i in range(20, len(ticks_aapl)):
            h = ticks_aapl[max(0,i-50):i+1]
            t0 = time.perf_counter_ns()
            detector.detect(ticks_aapl[i], h)
            lats.append((time.perf_counter_ns()-t0)/1e6)

        axes[0].hist(lats, bins=50, color="#00e5a0", alpha=0.8, edgecolor="none")
        axes[0].set_title("Signal Detection Latency (ms)", color="#c9d8e8", fontsize=10)
        axes[0].set_xlabel("ms", color="#5a7a96"); axes[0].set_ylabel("Count", color="#5a7a96")
        axes[0].axvline(statistics.mean(lats), color="#f5a623", linewidth=1.5, label=f"mean={statistics.mean(lats):.3f}ms")
        axes[0].legend(fontsize=8, labelcolor="#c9d8e8")

        detectors = [r["detector"] for r in per_det]
        means     = [r["mean_us"] for r in per_det]
        colors    = ["#00e5a0","#38bdf8","#f5a623","#a78bfa"]
        bars = axes[1].barh(detectors, means, color=colors, alpha=0.8)
        axes[1].set_title("Per-Detector Mean Latency (µs)", color="#c9d8e8", fontsize=10)
        axes[1].set_xlabel("µs", color="#5a7a96")
        for bar, val in zip(bars, means):
            axes[1].text(val+0.1, bar.get_y()+bar.get_height()/2, f"{val}µs", va="center", fontsize=8, color="#c9d8e8")

        plt.tight_layout()
        img_path = results_dir / "latest.png"
        plt.savefig(img_path, dpi=120, bbox_inches="tight", facecolor="#0d1117")
        print(f"  Plot saved to {img_path}")
    except ImportError:
        print("  (Install matplotlib for latency plots)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Pipeline latency benchmarks")
    parser.add_argument("--ticks",   type=int, default=2000, help="Ticks per symbol")
    parser.add_argument("--symbols", type=int, default=5,    help="Number of symbols")
    args = parser.parse_args()
    run_benchmarks(args.ticks, args.symbols)
