import openai

BASE_URL = "http://localhost:8080/"
MODEL = "mistralai/Mistral-7B-Instruct-v0.2"

client = openai.OpenAI(api_key="EMPTY", base_url=BASE_URL)
custom_headers = {
    "HERE": "THERE",
}

response = client.chat.completions.create(
    messages=[
        # {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "Tell me a joke about artificial intelligence."}
    ],
    model=MODEL,
    temperature=0,
    stream=True,
    max_tokens=100,
    extra_headers=custom_headers,
)


for tok in response:
    if not tok.choices:
        continue
    chunk_message = tok.choices[0].delta.content
    if chunk_message is not None:
        print(chunk_message, end="", flush=True)
        # if first_token_time is None and chunk_message != "":
        #    first_token_time = time.time()
        # words += chunk_message

print("")
