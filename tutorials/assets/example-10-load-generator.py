import argparse

from openai import OpenAI

# Set up argument parsing
parser = argparse.ArgumentParser(description="Use OpenAI API with custom base URL")
parser.add_argument(
    "--openai_api_base",
    type=str,
    default="http://localhost:30080/v1/",
    help="The base URL for the OpenAI API",
)
parser.add_argument(
    "--openai_api_key", type=str, default="EMPTY", help="The API key for OpenAI"
)
parser.add_argument(
    "--num-requests", type=int, default=100, help="Number of requests to send"
)
parser.add_argument(
    "--prompt-len", type=int, default=10000, help="Length of the prompt"
)

# Parse the arguments
args = parser.parse_args()

# Modify OpenAI's API key and API base to use vLLM's API server.
openai_api_key = args.openai_api_key
openai_api_base = args.openai_api_base

client = OpenAI(
    api_key=openai_api_key,
    base_url=openai_api_base,
)

models = client.models.list()


def generate_prompt(index, length):
    return f"Prompt {index} with dummy text " + "Hi " * length + "how are you?"


def send_requests(num_requests, prompt_len, modelname, client):
    completions = []
    for i in range(num_requests):
        print(f"Sending request {i} to model {modelname}")
        completion = client.completions.create(
            model=modelname,
            prompt=generate_prompt(i, prompt_len),
            echo=False,
            temperature=0,
            max_tokens=80,
            stream=True,
        )
        completions.append(completion)

    for idx, completion in enumerate(completions):
        print(f"Completion results for request {idx}: ", end="")
        for chunk in completion:
            print(chunk.choices[0].text, end="")
        print()


# Completion API
for model in models:
    send_requests(args.num_requests, args.prompt_len, model.id, client)
