#!/usr/bin/env python3
"""Throughput performance test for the Bonsai Ternary MIG deployment (3 instances, 64K context, q8_0 KV, parallel=2)."""
import requests
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

URL = "http://100.115.213.88:4000/v1/completions"
MODEL = "bonsai-ternary-8b"
PROMPT = "Once upon a time"
MAX_TOKENS = 4000
CONCURRENCY = 6
TOTAL_REQUESTS = 6
TIMEOUT = 600

def make_request(i):
    payload = {
        "model": MODEL,
        "prompt": PROMPT,
        "max_tokens": MAX_TOKENS,
        "temperature": 0.0,
    }
    start = time.perf_counter()
    try:
        resp = requests.post(URL, json=payload, timeout=TIMEOUT)
        latency = time.perf_counter() - start
        if resp.status_code != 200:
            return {"error": f"status {resp.status_code}: {resp.text[:200]}", "latency": latency}
        data = resp.json()
        tokens = data.get("tokens_predicted", 0)
        tps = data.get("timings", {}).get("predicted_per_second", 0.0)
        return {
            "req": i,
            "tokens": tokens,
            "latency": latency,
            "tps": tps,
        }
    except Exception as e:
        return {"error": str(e), "latency": time.perf_counter() - start}


def main():
    print(f"Target: {URL}")
    print(f"Model: {MODEL}")
    print(f"Context: 65536 (q8_0 KV, parallel=2, 3 MIG instances), Concurrency: {CONCURRENCY}, Total requests: {TOTAL_REQUESTS}, max_tokens: {MAX_TOKENS}")
    print("-" * 60)

    results = []
    errors = []
    overall_start = time.perf_counter()

    with ThreadPoolExecutor(max_workers=CONCURRENCY) as ex:
        futures = {ex.submit(make_request, i): i for i in range(TOTAL_REQUESTS)}
        for fut in as_completed(futures):
            res = fut.result()
            if "error" in res:
                errors.append(res)
                print(f"Request {res.get('req', '?')} ERROR: {res['error']}")
            else:
                results.append(res)
                print(f"Request {res['req']:2d}: {res['tokens']:4d} tokens in {res['latency']:6.2f}s "
                      f"({res['tps']:6.2f} tok/s single-stream)")

    overall_elapsed = time.perf_counter() - overall_start
    total_tokens = sum(r["tokens"] for r in results)
    avg_latency = sum(r["latency"] for r in results) / len(results) if results else 0
    aggregate_tps = total_tokens / overall_elapsed if overall_elapsed > 0 else 0

    print("-" * 60)
    print(f"Completed requests: {len(results)}/{TOTAL_REQUESTS}")
    print(f"Failed requests: {len(errors)}")
    print(f"Total tokens generated: {total_tokens}")
    print(f"Total wall-clock time: {overall_elapsed:.2f}s")
    print(f"Aggregate throughput: {aggregate_tps:.2f} tokens/s")
    print(f"Average latency per request: {avg_latency:.2f}s")


if __name__ == "__main__":
    main()
