import json

from openai import OpenAI


def get_weather(location: str, unit: str):
    """Mock weather function for demonstration."""
    return f"Getting the weather for {location} in {unit}..."


def main():
    # Initialize the client
    client = OpenAI(
        base_url="http://localhost:8000/v1",
        api_key="dummy",  # Not needed for local vLLM server
    )

    # Define the tool function
    tool_functions = {"get_weather": get_weather}

    # Define the tools that the model can use
    tools = [
        {
            "type": "function",
            "function": {
                "name": "get_weather",
                "description": "Get the current weather in a given location",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "location": {
                            "type": "string",
                            "description": "City and state, e.g., 'San Francisco, CA'",
                        },
                        "unit": {
                            "type": "string",
                            "enum": ["celsius", "fahrenheit"],
                            "description": "The unit of temperature to use",
                        },
                    },
                    "required": ["location", "unit"],
                },
            },
        }
    ]

    # Make a request to the model
    response = client.chat.completions.create(
        model="meta-llama/Llama-3.1-8B-Instruct",  # Use the model we deployed
        messages=[
            {"role": "user", "content": "What's the weather like in San Francisco?"}
        ],
        tools=tools,
        tool_choice="auto",
    )

    # Extract and process the tool call
    tool_call = response.choices[0].message.tool_calls[0].function
    print(f"Function called: {tool_call.name}")
    print(f"Arguments: {tool_call.arguments}")

    # Execute the tool with the provided arguments
    result = get_weather(**json.loads(tool_call.arguments))
    print(f"Result: {result}")


if __name__ == "__main__":
    main()
