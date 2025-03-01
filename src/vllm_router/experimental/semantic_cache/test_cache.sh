#!/bin/bash

# Configuration
API_KEY="abcd"
BASE_URL="http://localhost:8001/v1"
MODEL="phi4"

# Function to call OpenAI API
call_openai() {
    local msg="$1"
    local prompt="$2"
    local stream="$3"

    echo "Running $msg query with stream=$([ "$stream" = "true" ] && echo "enabled" || echo "disabled")..."

    if [ "$stream" = "true" ]; then
        # Make a completion request with streaming enabled
        curl -s "$BASE_URL/chat/completions" \
            -H "Content-Type: application/json" \
            -H "Authorization: Bearer $API_KEY" \
            -d "{
                \"model\": \"$MODEL\",
                \"messages\": [{\"role\": \"user\", \"content\": \"$prompt\"}],
                \"stream\": true
            }" | while read -r line; do
                # Process each line of the streamed response
                if [[ "$line" == "data: "* ]]; then
                    # Extract content from the line if it exists
                    local chunk
                    chunk=$(echo "$line" | sed 's/^data: //' | jq -r '.choices[0].delta.content // empty' 2>/dev/null)
                    if [ -n "$chunk" ]; then
                        echo -n "$chunk"
                    fi
                elif [[ "$line" == "data: [DONE]" ]]; then
                    # End of stream
                    echo ""
                fi
            done
    else
        # Make a completion request with streaming disabled
        response=$(curl -s "$BASE_URL/chat/completions" \
            -H "Content-Type: application/json" \
            -H "Authorization: Bearer $API_KEY" \
            -d "{
                \"model\": \"$MODEL\",
                \"messages\": [{\"role\": \"user\", \"content\": \"$prompt\"}],
                \"stream\": false
            }")

        # Extract and print the response content
        echo "$response" | jq -r '.choices[0].message.content'
    fi
}

# Test the Simple query without streaming
call_openai "Simple chat" "What is the capital of France?" "false"
echo ""

# Test the Complex query without streaming
call_openai "Complex chat" "Explain transformer architecture in simple terms" "false"
