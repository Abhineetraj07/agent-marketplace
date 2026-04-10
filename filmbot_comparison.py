"""
FilmBot Benchmark Comparison — Direct vs A2A
Runs the same 10 benchmark questions through both modes and generates
a side-by-side comparison report (CSV + console summary).
Includes A2A overhead breakdown logging.
"""

import asyncio
import csv
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime

from filmbot_agent import (
    BENCHMARK_QUESTIONS_10,
    get_ground_truth,
    check_accuracy,
    invoke_agent,
    OLLAMA_MODEL,
)

# Use 10 questions for benchmarking

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TOKEN_LOG_PATH = os.path.join(BASE_DIR, "a2a_token_log.json")
SERVER_SCRIPT = os.path.join(BASE_DIR, "filmbot_a2a_server.py")


# ============================================================
# PHASE 1: DIRECT MODE BENCHMARK
# ============================================================

def run_direct_benchmark(questions: list[str], ground_truth: dict) -> list[dict]:
    print("\n" + "=" * 70)
    print("   PHASE 1: Direct Mode Benchmark")
    print("=" * 70)

    results = []
    for i, question in enumerate(questions, 1):
        print(f"  [{i}/{len(questions)}] {question[:50]}...")

        try:
            result = invoke_agent(question)
            is_accurate, details = check_accuracy(question, result["response"], ground_truth)

            status_icon = "+" if is_accurate else "x"
            print(f"    {status_icon} Latency: {result['latency']:.2f}s | Tokens: {result['prompt_tokens']}+{result['completion_tokens']} | Tools: {result['tool_calls']} | {details}")

            results.append({
                "question_id": i,
                "question": question,
                "response": result["response"][:500],
                "latency": result["latency"],
                "prompt_tokens": result["prompt_tokens"],
                "completion_tokens": result["completion_tokens"],
                "tool_calls": result["tool_calls"],
                "is_accurate": is_accurate,
                "accuracy_details": details,
                "status": "SUCCESS",
            })

        except Exception as e:
            print(f"    x ERROR: {e}")
            results.append({
                "question_id": i,
                "question": question,
                "response": f"ERROR: {e}",
                "latency": 0,
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "tool_calls": 0,
                "is_accurate": False,
                "accuracy_details": f"Error: {str(e)[:100]}",
                "status": "ERROR",
            })

    return results


# ============================================================
# PHASE 2: A2A MODE BENCHMARK
# ============================================================

def _wait_for_server(url: str, timeout: float = 30.0):
    """Poll the agent card endpoint until the server is ready."""
    import httpx
    start = time.time()
    while time.time() - start < timeout:
        try:
            resp = httpx.get(f"{url}/.well-known/agent-card.json", timeout=5.0)
            if resp.status_code == 200:
                return True
        except (httpx.ConnectError, httpx.ReadTimeout):
            pass
        time.sleep(1)
    raise TimeoutError(f"A2A server at {url} did not start within {timeout}s")


def _extract_api_key(server_output: str) -> str:
    """Extract the API key from the server's startup output."""
    for line in server_output.split("\n"):
        if "API Key:" in line:
            return line.split("API Key:")[-1].strip()
    return ""


def run_a2a_benchmark(questions: list[str], ground_truth: dict) -> list[dict]:
    print("\n" + "=" * 70)
    print("   PHASE 2: A2A Mode Benchmark")
    print("=" * 70)

    # Clear old token log
    if os.path.exists(TOKEN_LOG_PATH):
        os.remove(TOKEN_LOG_PATH)

    # Start the A2A server as a subprocess
    env = os.environ.copy()
    api_key = os.environ.get("FILMBOT_A2A_API_KEY", "benchmark-secret-key")
    env["FILMBOT_A2A_API_KEY"] = api_key

    print("  Starting A2A server...")
    server_proc = subprocess.Popen(
        [sys.executable, SERVER_SCRIPT],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )

    try:
        _wait_for_server("http://localhost:9999")
        print("  Server is ready.")

        # Run the A2A client benchmark
        from filmbot_a2a_client import run_a2a_benchmark as _client_benchmark
        a2a_results = asyncio.run(_client_benchmark(api_key, questions, ground_truth))

        # Load token log to merge server-side metrics
        token_log = []
        if os.path.exists(TOKEN_LOG_PATH):
            with open(TOKEN_LOG_PATH, "r") as f:
                token_log = json.load(f)

        # Merge token data into results (order matches since server processes sequentially)
        for i, result in enumerate(a2a_results):
            if i < len(token_log):
                entry = token_log[i]
                result["prompt_tokens"] = entry.get("prompt_tokens", 0)
                result["completion_tokens"] = entry.get("completion_tokens", 0)
                result["tool_calls"] = entry.get("tool_calls", 0)
                result["server_latency"] = entry.get("latency_server", 0)
                result["overhead"] = entry.get("overhead", {})
            else:
                result["prompt_tokens"] = 0
                result["completion_tokens"] = 0
                result["tool_calls"] = result.get("tool_calls", 0)
                result["server_latency"] = 0
                result["overhead"] = {}

        # Print A2A overhead breakdown
        print("\n" + "-" * 70)
        print("   A2A OVERHEAD BREAKDOWN (server-side, per question)")
        print("-" * 70)
        print(f"   {'Q#':<5} {'Parse (ms)':>12} {'Agent (ms)':>12} {'Serialize (ms)':>16} {'Overhead (ms)':>14}")
        print("-" * 70)
        total_overhead_ms = 0
        for i, r in enumerate(a2a_results):
            oh = r.get("overhead", {})
            parse = oh.get("parse_context_ms", 0)
            agent = oh.get("agent_execution_ms", 0)
            serialize = oh.get("serialize_response_ms", 0)
            overhead_ms = parse + serialize
            total_overhead_ms += overhead_ms
            print(f"   Q{i+1:<4} {parse:>12.2f} {agent:>12.2f} {serialize:>16.2f} {overhead_ms:>14.2f}")

        avg_overhead = total_overhead_ms / len(a2a_results) if a2a_results else 0
        print("-" * 70)
        print(f"   {'AVG':<5} {'':>12} {'':>12} {'':>16} {avg_overhead:>14.2f}")
        print(f"\n   Average A2A server overhead: {avg_overhead:.2f} ms ({avg_overhead/1000:.4f} s)")
        print("-" * 70)

        return a2a_results

    finally:
        print("  Stopping A2A server...")
        server_proc.terminate()
        server_proc.wait(timeout=10)


# ============================================================
# PHASE 3: COMPARISON REPORT
# ============================================================

def _calc_stats(results: list[dict]) -> dict:
    successful = [r for r in results if r["status"] == "SUCCESS"]
    latencies = [r["latency"] for r in successful]
    return {
        "total": len(results),
        "successful": len(successful),
        "accurate": sum(1 for r in results if r["is_accurate"]),
        "avg_latency": round(sum(latencies) / len(latencies), 2) if latencies else 0,
        "min_latency": round(min(latencies), 2) if latencies else 0,
        "max_latency": round(max(latencies), 2) if latencies else 0,
        "total_prompt_tokens": sum(r.get("prompt_tokens", 0) for r in results),
        "total_completion_tokens": sum(r.get("completion_tokens", 0) for r in results),
        "total_tool_calls": sum(r.get("tool_calls", 0) for r in results),
        "avg_tool_calls": round(sum(r.get("tool_calls", 0) for r in results) / len(results), 1) if results else 0,
    }


def _overhead_pct(direct_val, a2a_val) -> str:
    if direct_val == 0:
        return "N/A"
    pct = ((a2a_val - direct_val) / direct_val) * 100
    sign = "+" if pct >= 0 else ""
    return f"{sign}{pct:.1f}%"


def generate_report(direct_results: list[dict], a2a_results: list[dict]):
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = os.path.join(BASE_DIR, f"filmbot_comparison_{timestamp}.csv")

    ds = _calc_stats(direct_results)
    a2s = _calc_stats(a2a_results)

    # === Console Summary ===
    print("\n" + "=" * 70)
    print("   COMPARISON SUMMARY: Direct vs A2A")
    print("=" * 70)
    print(f"   {'Metric':<30} {'Direct':>10} {'A2A':>10} {'Overhead':>10}")
    print("-" * 70)
    print(f"   {'Accuracy':<30} {ds['accurate']}/{ds['total']:>7} {a2s['accurate']}/{a2s['total']:>7} {'—':>10}")
    print(f"   {'Avg Latency (s)':<30} {ds['avg_latency']:>10} {a2s['avg_latency']:>10} {_overhead_pct(ds['avg_latency'], a2s['avg_latency']):>10}")
    print(f"   {'Min Latency (s)':<30} {ds['min_latency']:>10} {a2s['min_latency']:>10} {_overhead_pct(ds['min_latency'], a2s['min_latency']):>10}")
    print(f"   {'Max Latency (s)':<30} {ds['max_latency']:>10} {a2s['max_latency']:>10} {_overhead_pct(ds['max_latency'], a2s['max_latency']):>10}")
    print(f"   {'Total Prompt Tokens':<30} {ds['total_prompt_tokens']:>10} {a2s['total_prompt_tokens']:>10} {_overhead_pct(ds['total_prompt_tokens'], a2s['total_prompt_tokens']):>10}")
    print(f"   {'Total Completion Tokens':<30} {ds['total_completion_tokens']:>10} {a2s['total_completion_tokens']:>10} {_overhead_pct(ds['total_completion_tokens'], a2s['total_completion_tokens']):>10}")
    print(f"   {'Avg Tool Calls':<30} {ds['avg_tool_calls']:>10} {a2s['avg_tool_calls']:>10} {'—':>10}")
    print(f"   {'Model':<30} {OLLAMA_MODEL:>10}")
    print("=" * 70)

    # === CSV Report ===
    fieldnames = [
        "question_id", "question",
        "direct_latency", "a2a_latency", "latency_overhead",
        "direct_accurate", "a2a_accurate",
        "direct_prompt_tokens", "a2a_prompt_tokens",
        "direct_completion_tokens", "a2a_completion_tokens",
        "direct_tool_calls", "a2a_tool_calls",
    ]

    with open(filename, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()

        for d, a in zip(direct_results, a2a_results):
            writer.writerow({
                "question_id": d["question_id"],
                "question": d["question"],
                "direct_latency": d["latency"],
                "a2a_latency": a["latency"],
                "latency_overhead": _overhead_pct(d["latency"], a["latency"]),
                "direct_accurate": d["is_accurate"],
                "a2a_accurate": a["is_accurate"],
                "direct_prompt_tokens": d.get("prompt_tokens", 0),
                "a2a_prompt_tokens": a.get("prompt_tokens", 0),
                "direct_completion_tokens": d.get("completion_tokens", 0),
                "a2a_completion_tokens": a.get("completion_tokens", 0),
                "direct_tool_calls": d.get("tool_calls", 0),
                "a2a_tool_calls": a.get("tool_calls", 0),
            })

        # Summary rows
        writer.writerow({k: "" for k in fieldnames})
        summary_fields = {k: "" for k in fieldnames}
        summary_fields["question_id"] = "SUMMARY"

        for label, d_val, a_val, show_overhead in [
            ("Avg Latency (s)", ds["avg_latency"], a2s["avg_latency"], True),
            ("Accuracy", f"{ds['accurate']}/{ds['total']}", f"{a2s['accurate']}/{a2s['total']}", False),
            ("Total Prompt Tokens", ds["total_prompt_tokens"], a2s["total_prompt_tokens"], True),
            ("Total Completion Tokens", ds["total_completion_tokens"], a2s["total_completion_tokens"], True),
            ("Avg Tool Calls", ds["avg_tool_calls"], a2s["avg_tool_calls"], False),
            ("Model", OLLAMA_MODEL, OLLAMA_MODEL, False),
        ]:
            row = {k: "" for k in fieldnames}
            row["question"] = label
            row["direct_latency"] = d_val
            row["a2a_latency"] = a_val
            if show_overhead and isinstance(d_val, (int, float)):
                row["latency_overhead"] = _overhead_pct(d_val, a_val)
            writer.writerow(row)

    print(f"\n   Report saved to: {filename}")
    return filename


def save_individual_csv(results: list[dict], mode: str, timestamp: str):
    """Save individual benchmark results (direct or a2a) to their own CSV."""
    filename = os.path.join(BASE_DIR, f"filmbot_{mode}_{timestamp}.csv")

    fieldnames = [
        "question_id", "question", "response",
        "latency_seconds", "prompt_tokens", "completion_tokens",
        "tool_calls", "is_accurate", "accuracy_details", "status",
    ]

    with open(filename, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()

        for r in results:
            writer.writerow({
                "question_id": r["question_id"],
                "question": r["question"],
                "response": r.get("response", ""),
                "latency_seconds": r["latency"],
                "prompt_tokens": r.get("prompt_tokens", 0),
                "completion_tokens": r.get("completion_tokens", 0),
                "tool_calls": r.get("tool_calls", 0),
                "is_accurate": r["is_accurate"],
                "accuracy_details": r.get("accuracy_details", ""),
                "status": r.get("status", ""),
            })

        # Summary section
        writer.writerow({k: "" for k in fieldnames})
        successful = [r for r in results if r.get("status") == "SUCCESS"]
        latencies = [r["latency"] for r in successful]
        accurate = sum(1 for r in results if r["is_accurate"])

        summary_rows = [
            ("SUMMARY", f"=== {mode.upper()} MODE BENCHMARK ==="),
            ("", f"Total Questions: {len(results)}"),
            ("", f"Successful: {len(successful)}/{len(results)}"),
            ("", f"Accurate: {accurate}/{len(results)} ({accurate/len(results)*100:.0f}%)"),
            ("", f"Avg Latency: {sum(latencies)/len(latencies):.2f}s" if latencies else "Avg Latency: N/A"),
            ("", f"Min Latency: {min(latencies):.2f}s" if latencies else "Min Latency: N/A"),
            ("", f"Max Latency: {max(latencies):.2f}s" if latencies else "Max Latency: N/A"),
            ("", f"Total Prompt Tokens: {sum(r.get('prompt_tokens', 0) for r in results)}"),
            ("", f"Total Completion Tokens: {sum(r.get('completion_tokens', 0) for r in results)}"),
            ("", f"Total Tool Calls: {sum(r.get('tool_calls', 0) for r in results)}"),
            ("", f"Model: {OLLAMA_MODEL}"),
        ]

        # Add A2A overhead info if available
        if mode == "a2a":
            overheads = [r.get("overhead", {}) for r in results if r.get("overhead")]
            if overheads:
                avg_parse = sum(o.get("parse_context_ms", 0) for o in overheads) / len(overheads)
                avg_serialize = sum(o.get("serialize_response_ms", 0) for o in overheads) / len(overheads)
                avg_total_oh = avg_parse + avg_serialize
                summary_rows.append(("", f"Avg A2A Parse Overhead: {avg_parse:.2f}ms"))
                summary_rows.append(("", f"Avg A2A Serialize Overhead: {avg_serialize:.2f}ms"))
                summary_rows.append(("", f"Avg A2A Total Overhead: {avg_total_oh:.2f}ms"))

        for qid, info in summary_rows:
            row = {k: "" for k in fieldnames}
            row["question_id"] = qid
            row["question"] = info
            writer.writerow(row)

    print(f"   {mode.upper()} results saved to: {filename}")
    return filename


# ============================================================
# MAIN
# ============================================================

def main():
    print("Loading ground truth from database...")
    ground_truth = get_ground_truth()

    # Warm-up: run 1 throwaway question to load Ollama model into memory
    print("\n" + "=" * 70)
    print("   WARM-UP: Loading model into memory (results discarded)")
    print("=" * 70)
    invoke_agent("How many movies are in the dataset?")
    print("  Warm-up complete.\n")

    # Phase 1: Direct (10 questions)
    direct_results = run_direct_benchmark(BENCHMARK_QUESTIONS_10, ground_truth)

    # Phase 2: A2A (10 questions)
    a2a_results = run_a2a_benchmark(BENCHMARK_QUESTIONS_10, ground_truth)

    # Phase 3: Save individual CSVs + comparison report
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    print("\n" + "=" * 70)
    print("   SAVING RESULTS")
    print("=" * 70)
    save_individual_csv(direct_results, "direct", timestamp)
    save_individual_csv(a2a_results, "a2a", timestamp)
    generate_report(direct_results, a2a_results)


if __name__ == "__main__":
    main()
