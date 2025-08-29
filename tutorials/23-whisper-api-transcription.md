# Tutorial: Whisper Transcription API in vLLM Production Stack

## Overview

This tutorial introduces the newly added `/v1/audio/transcriptions` endpoint in the `vllm-router`, enabling users to transcribe `.wav` audio files using OpenAI’s `whisper-small` model.

## Prerequisites

* Access to a machine with a GPU (e.g. via [RunPod](https://runpod.io/))
* Python 3.12 environment (recommended with `uv`)
* `vllm` and `production-stack` cloned and installed
* `vllm` installed with audio support:

  ```bash
  pip install vllm[audio]
  ```

## 1. Serving the Whisper Model

Start a vLLM backend with the `whisper-small` model:

```bash
vllm serve \
  --task transcription openai/whisper-small \
  --host 0.0.0.0 --port 8002
```

## 2. Running the Router

Create and run a router connected to the Whisper backend:

```bash
#!/bin/bash
if [[ $# -ne 2 ]]; then
    echo "Usage: $0 <router_port> <backend_url>"
    exit 1
fi

uv run python3 -m vllm_router.app \
  --host 0.0.0.0 --port "$1" \
  --service-discovery static \
  --static-backends "$2" \
  --static-models "openai/whisper-small" \
  --static-model-types "transcription" \
  --routing-logic roundrobin \
  --log-stats \
  --engine-stats-interval 10 \
  --request-stats-window 10
```

Example usage:

```bash
./run-router.sh 8000 http://localhost:8002
```

## 3. Sending a Transcription Request

Use `curl` to send a `.wav` file to the transcription endpoint:

* You can test with any `.wav` audio file of your choice.

```bash
curl -v http://localhost:8000/v1/audio/transcriptions \
  -F 'file=@/path/to/audio.wav;type=audio/wav' \
  -F 'model=openai/whisper-small' \
  -F 'response_format=json' \
  -F 'language=en'
```

### Supported Parameters

| Parameter         | Description                                            |
| ----------------- | ------------------------------------------------------ |
| `file`            | Path to a `.wav` audio file                            |
| `model`           | Whisper model to use (e.g., `openai/whisper-small`)    |
| `prompt`          | *(Optional)* Text prompt to guide the transcription    |
| `response_format` | One of `json`, `text`, `srt`, `verbose_json`, or `vtt` |
| `temperature`     | *(Optional)* Sampling temperature as a float           |
| `language`        | ISO 639-1 code (e.g., `en`, `fr`, `zh`)                |

## 4. Sample Output

```json
{
  "text": "Testing testing testing the whisper small model testing testing testing the audio transcription function testing testing testing the whisper small model"
}
```

## 5. Notes

* Router uses extended aiohttp timeouts to support long transcription jobs.
* This implementation dynamically discovers valid transcription backends and routes requests accordingly.

## 6. Resources

* [PR #469 – Add Whisper Transcription API](https://github.com/vllm-project/production-stack/pull/469)
* [OpenAI Whisper GitHub](https://github.com/openai/whisper)
* [Blog: vLLM Whisper Transcription Walkthrough](https://davidgao7.github.io/posts/vllm-v1-whisper-transcription/)
