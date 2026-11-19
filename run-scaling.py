#!/usr/bin/env python3
"""Run HPL on 1, 2, 4, and 8 Pis."""

import csv
import json
import re
import subprocess
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from statistics import mean


# (nodes, P, Q), with one MPI rank per core
SCALING_RUNS = (
    (1, 2, 2),
    (2, 2, 4),
    (4, 4, 4),
    (8, 4, 8),
)
SUMMARY_COLUMNS = (
    "nodes", "Rmax_GFLOPS", "N", "NB", "P", "Q", "CPU0_mean_MHz_by_host",
    "samples_by_host", "reference_kHz_by_host", "cores_per_node",
    "FP64_FLOPs_per_core_cycle", "Rpeak_GFLOPS", "efficiency_percent",
)
PI4_CORES = 4
# One vector FMA per cycle on Cortex-A72, with a multiply and add in each of two FP64 lanes.
FP64_FLOPS_PER_CORE_CYCLE = 4

# HPL column order: variant, N, NB, P, Q, seconds, GFLOPS
TIMING_ROW = re.compile(
    r"^\s*W\S+\s+"
    r"(?P<n>\d+)\s+(?P<nb>\d+)\s+"
    r"(?P<p>\d+)\s+(?P<q>\d+)\s+"
    r"[\d.]+\s+(?P<gflops>[\d.eE+-]+)\s*$",
    re.MULTILINE,
)


def run_benchmark(repo: Path, results: Path, nodes: int, p: int, q: int) -> dict:
    log = results / f"{nodes}-nodes.log"
    variables = {
        "scaling_nodes": nodes,
        "scaling_p": p,
        "scaling_q": q,
        "scaling_output": str(log),
    }
    command = [
        "ansible-playbook", "-i", "hosts.ini", "main.yml",
        "--tags", "benchmark",
        "--limit", f"cluster[0:{nodes - 1}]",
        "-e", json.dumps(variables),
    ]
    subprocess.run(command, cwd=repo, check=True)
    return summarize(log.read_text(encoding="utf-8"), nodes, p, q)


def clock_summary(output: str, nodes: int) -> dict:
    error = re.search(r"^HPL_CLOCK_ERROR (.+)$", output, re.MULTILINE)
    if error:
        raise ValueError(f"Incomplete CPU frequency data: {error[1]}")
    samples = defaultdict(list)
    for host, khz in re.findall(r"^HPL_CLOCK (\S+) (\d+)$", output, re.MULTILINE):
        samples[host].append(int(khz))

    if len(samples) != nodes:
        raise ValueError(f"Expected CPU frequency samples from {nodes} nodes, got {len(samples)}")

    maxima = dict(re.findall(r"^HPL_MAX_KHZ (\S+) ([1-9]\d*)$", output, re.MULTILINE))
    if maxima.keys() != samples.keys():
        raise ValueError("Reference clocks and CPU samples must cover the same hosts")

    hosts = sorted(samples)
    total_ghz = sum(int(khz) for khz in maxima.values()) / 1_000_000
    return {
        "CPU0_mean_MHz_by_host": ", ".join(f"{h}={mean(samples[h]) / 1000:.1f}" for h in hosts),
        "samples_by_host": ", ".join(f"{h}={len(samples[h])}" for h in hosts),
        "reference_kHz_by_host": ", ".join(f"{h}={maxima[h]}" for h in hosts),
        "cores_per_node": PI4_CORES,
        "FP64_FLOPs_per_core_cycle": FP64_FLOPS_PER_CORE_CYCLE,
        "Rpeak_GFLOPS": total_ghz * PI4_CORES * FP64_FLOPS_PER_CORE_CYCLE,
    }


def summarize(output: str, nodes: int, p: int, q: int) -> dict:
    timings = list(TIMING_ROW.finditer(output))
    if len(timings) != 1 or not re.search(r"\.\.\.\s+PASSED\b", output):
        raise ValueError("Missing HPL timing row or passing residual check")

    timing = timings[0]
    if (int(timing["p"]), int(timing["q"])) != (p, q):
        raise ValueError("Unexpected HPL process grid")

    clocks = clock_summary(output, nodes)
    return {
        "nodes": nodes,
        "Rmax_GFLOPS": timing["gflops"],
        "N": timing["n"],
        "NB": timing["nb"],
        "P": p,
        "Q": q,
        **clocks,
        "efficiency_percent": round(100 * float(timing["gflops"]) / clocks["Rpeak_GFLOPS"], 3),
    }


def main() -> None:
    repo = Path(__file__).resolve().parent
    results = repo / datetime.now().strftime("hpl-scaling-%Y%m%d-%H%M%S")
    results.mkdir()
    print(f"Saving results in {results}", flush=True)

    with (results / "summary.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=SUMMARY_COLUMNS)
        writer.writeheader()
        for nodes, p, q in SCALING_RUNS:
            row = run_benchmark(repo, results, nodes, p, q)
            writer.writerow(row)
            stream.flush()
            print(row, flush=True)


if __name__ == "__main__":
    main()
