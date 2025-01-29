from openai import OpenAI

# Modify OpenAI's API key and API base to use vLLM's API server.
openai_api_key = "EMPTY"
openai_api_base = "http://localhost:30080/"

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
