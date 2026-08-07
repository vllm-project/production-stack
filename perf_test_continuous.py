#!/usr/bin/env python3
"""Continuous throughput performance test for the Bonsai Ternary MIG deployment."""
import requests
import time
from concurrent.futures import ThreadPoolExecutor

URL = "http://100.115.213.88:4000/v1/completions"
MODEL = "bonsai-ternary-8b"
PROMPT = "Once upon a time"
MAX_TOKENS = 4000
CONCURRENCY = 4
DURATION_SECONDS = 120
TIMEOUT = 300

results = []
errors = []

def worker(i):
    while not stop_event.is_set():
        payload = {
            "model": MODEL,
            "prompt": PROMPT,
            "max_tokens": MAX_TOKENS,
            "temperature": 0.0,
        }
        try:
            start = time.perf_counter()
            resp = requests.post(URL, json=payload, timeout=TIMEOUT)
            latency = time.perf_counter() - start
            if resp.status_code == 200:
                data = resp.json()
                tokens = data.get("tokens_predicted", 0)
                tps = data.get("timings", {}).get("predicted_per_second", 0.0)
                results.append({"tokens": tokens, "latency": latency, "tps": tps})
                print(f"Worker {i}: {tokens} tokens in {latency:.2f}s ({tps:.2f} tok/s)")
            else:
                errors.append(f"worker {i} status {resp.status_code}: {resp.text[:100]}")
                print(f"Worker {i} ERROR: status {resp.status_code}")
        except Exception as e:
            errors.append(f"worker {i}: {e}")
            print(f"Worker {i} ERROR: {e}")


class StopEvent:
    def __init__(self):
        self._stop = False
    def is_set(self):
        return self._stop
    def set(self):
        self._stop = True


def main():
    global stop_event
    stop_event = StopEvent()
    print(f"Target: {URL}")
    print(f"Model: {MODEL}")
    print(f"Concurrency: {CONCURRENCY}, max_tokens: {MAX_TOKENS}, duration: {DURATION_SECONDS}s")
    print("-" * 60)

    start = time.perf_counter()
    with ThreadPoolExecutor(max_workers=CONCURRENCY) as ex:
        futures = [ex.submit(worker, i) for i in range(CONCURRENCY)]
        time.sleep(DURATION_SECONDS)
        stop_event.set()
        for fut in futures:
            fut.result()

    elapsed = time.perf_counter() - start
    total_tokens = sum(r["tokens"] for r in results)
    avg_latency = sum(r["latency"] for r in results) / len(results) if results else 0
    avg_tps = sum(r["tps"] for r in results) / len(results) if results else 0
    aggregate_tps = total_tokens / elapsed if elapsed > 0 else 0

    print("-" * 60)
    print(f"Completed requests: {len(results)}")
    print(f"Failed requests: {len(errors)}")
    print(f"Total tokens generated: {total_tokens}")
    print(f"Wall-clock time: {elapsed:.2f}s")
    print(f"Aggregate throughput: {aggregate_tps:.2f} tokens/s")
    print(f"Average single-stream throughput: {avg_tps:.2f} tokens/s")
    print(f"Average latency per request: {avg_latency:.2f}s")


if __name__ == "__main__":
    main()
