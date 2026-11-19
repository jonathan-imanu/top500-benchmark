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

# Each tuple is (nodes, P, Q)
SCALING_RUNS = (
    (1, 2, 2),
    (2, 2, 4),
    (4, 4, 4),
    (8, 4, 8),
)
SUMMARY_COLUMNS = (
    "nodes",
    "Rmax_GFLOPS",
    "N",
    "NB",
    "P",
    "Q",
    "CPU0_mean_MHz_by_host",
    "samples_by_host",
)
# HPL column order: variant, N, NB, P, Q, seconds, GFLOPS
TIMING_ROW = re.compile(
    r"^\s*W\S+\s+"
    r"(?P<n>\d+)\s+(?P<nb>\d+)\s+"
    r"(?P<p>\d+)\s+(?P<q>\d+)\s+"
    r"[\d.]+\s+(?P<gflops>[\d.eE+-]+)\s*$",
    re.MULTILINE,
)
RESIDUAL_PASSED = re.compile(r"\.\.\.\s+PASSED\b")
CLOCK_SAMPLE = re.compile(r"^HPL_CLOCK (\S+) (\d+)$", re.MULTILINE)
CLOCK_ERROR = re.compile(r"^HPL_CLOCK_ERROR (.+)$", re.MULTILINE)


def run_benchmark(repo: Path, results: Path, nodes: int, p: int, q: int) -> dict:
    log = results / f"{nodes}-nodes.log"
    variables = {
        "scaling_nodes": nodes,
        "scaling_p": p,
        "scaling_q": q,
        "scaling_output": str(log),
    }
    command = [
        "ansible-playbook",
        "-i",
        "hosts.ini",
        "main.yml",
        "--tags",
        "benchmark",
        "--limit",
        f"cluster[0:{nodes - 1}]",
        "-e",
        json.dumps(variables),
    ]
    subprocess.run(command, cwd=repo, check=True)
    return summarize(log.read_text(encoding="utf-8"), nodes, p, q)


def parse_clocks(output: str, nodes: int) -> dict:
    error = CLOCK_ERROR.search(output)
    if error:
        raise ValueError(f"Incomplete CPU frequency data: {error[1]}")
    samples = defaultdict(list)
    for host, khz in CLOCK_SAMPLE.findall(output):
        samples[host].append(int(khz))

    if len(samples) != nodes:
        raise ValueError(
            f"Expected CPU frequency samples from {nodes} nodes, got {len(samples)}"
        )

    return samples


def format_hosts(values: dict) -> str:
    return ", ".join(f"{host}={values[host]}" for host in sorted(values))


def summarize(output: str, nodes: int, p: int, q: int) -> dict:
    timings = list(TIMING_ROW.finditer(output))
    if len(timings) != 1 or not RESIDUAL_PASSED.search(output):
        raise ValueError("Missing HPL timing row or passing residual check")

    timing = timings[0]
    if (int(timing["p"]), int(timing["q"])) != (p, q):
        raise ValueError("Unexpected HPL process grid")

    samples = parse_clocks(output, nodes)
    mean_mhz = {host: f"{mean(khz) / 1000:.1f}" for host, khz in samples.items()}
    sample_counts = {host: len(khz) for host, khz in samples.items()}

    return {
        "nodes": nodes,
        "Rmax_GFLOPS": timing["gflops"],
        "N": timing["n"],
        "NB": timing["nb"],
        "P": p,
        "Q": q,
        "CPU0_mean_MHz_by_host": format_hosts(mean_mhz),
        "samples_by_host": format_hosts(sample_counts),
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
