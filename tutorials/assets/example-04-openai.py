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

# Completion API
for model in models:
    completion = client.completions.create(
        model=model.id,
        prompt="The result of 1 + 1 is ",
        echo=False,
        temperature=0,
        max_tokens=10,
    )

    print("Completion results from model: ", model.id)
    print(completion.choices[0].text)
    print("--------------------")
