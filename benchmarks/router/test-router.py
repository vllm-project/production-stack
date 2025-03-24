# This script tests the routing overhead
import argparse
import time

import torch
from openai import OpenAI

p = argparse.ArgumentParser()
p.add_argument("--model", type=str, default="llama3")
p.add_argument("--url", type=str, default="http://localhost:8888/v1/")
args = p.parse_args()
# Modify OpenAI's API key and API base to use vLLM's API server.
openai_api_key = "EMPTY"
openai_api_base = args.url

client = OpenAI(
    # defaults to os.environ.get("OPENAI_API_KEY")
    api_key=openai_api_key,
    base_url=openai_api_base,
)

model = args.model
avg = []
for _ in range(50):
    # Completion API
    stream = False
    st = time.monotonic()
    completion = client.completions.create(
        model=model,
        prompt="hi" * 8,
        echo=False,
        n=1,
        stream=stream,
        logprobs=3,
        max_tokens=1,
    )
    # torch.cuda.synchronize()
    end = time.monotonic() - st
    avg += [end]
print("average time: ", sum(avg) / len(avg))
print("Completion results:")
if stream:
    for c in completion:
        print(c)
else:
    print(completion)
