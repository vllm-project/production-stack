import argparse
import multiprocessing
import os
import threading
import time
import uuid

import openai


def response_consumer(response_stream, start_time):
    chunk_messages = []
    token_time = None
    try:
        for tok in response_stream:
            if not tok.choices:
                continue
            chunk_message = tok.choices[0].delta.content
            if chunk_message is not None:
                if token_time is None:
                    token_time = time.time()
                chunk_messages.append(chunk_message)
    except Exception as e:
        print(
            f"Error in consumer thread {threading.current_thread().name} of process {os.getpid()}: {e}"
        )
    final_words = "".join(chunk_messages)
    end_time = time.time()
    response_len = len(final_words.split(" "))
    throughput = response_len / (end_time - start_time)
    print(
        f"Process {os.getpid()} got a response of: {response_len} words in {end_time-start_time:.2f} seconds (throughput: {throughput:.2f} w/s, ttft: {token_time - start_time:.4f}) at {end_time}"
    )


def worker(api_key, base_url, model, qps_per_worker):
    client = openai.OpenAI(api_key=api_key, base_url=base_url)
    interval = 1 / qps_per_worker

    while True:
        start = time.time()
        print("Send request at ", start)
        try:
            request_id = str(uuid.uuid4())
            custom_headers = {
                "x-user-id": str(os.getpid()),  # Unique user ID for each process
                "x-request-id": str(os.getpid())
                + f"req-{request_id}",  # Unique session ID for each process
            }
            response_stream = client.chat.completions.create(
                messages=[
                    {
                        "role": "user",
                        "content": "Tell me a joke about artificial intelligence.",
                    }
                ],
                model=model,
                temperature=0,
                stream=True,
                max_tokens=500,
                extra_headers=custom_headers,
            )
            start_time = time.time()
            print(
                "Process {} sent a request at {:.4f}, connection overhead: {:.4f}".format(
                    os.getpid(), start_time, start_time - start
                )
            )

            consumer_thread = threading.Thread(
                target=response_consumer,
                args=(response_stream, start_time),
                daemon=True,
            )
            consumer_thread.start()
        except Exception as e:
            print(f"Error in process {os.getpid()}: {e}")
        elapsed = time.time() - start
        if elapsed < interval:
            time.sleep(interval - elapsed)
        else:
            print("WARNING: Process {} is too slow".format(os.getpid()))


def main():
    parser = argparse.ArgumentParser(description="Stress test an OpenAI API server")
    parser.add_argument(
        "--qps", type=float, required=True, help="Total queries per second"
    )
    parser.add_argument(
        "--num-workers", type=int, required=True, help="Number of worker processes"
    )

    args = parser.parse_args()
    qps_per_worker = args.qps / args.num_workers

    processes = []
    api_key = "YOUR_API_KEY_HERE"
    base_url = "http://localhost:8000/v1"
    model = "fake_model_name"

    for _ in range(args.num_workers):
        p = multiprocessing.Process(
            target=worker, args=(api_key, base_url, model, qps_per_worker)
        )
        p.start()
        processes.append(p)

    for p in processes:
        p.join()


if __name__ == "__main__":
    main()
