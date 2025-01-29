# Testing scripts

This folder contains the test-related scripts to test the performance and functionality of the stack. Currently, it includes:

- `test-openai.py`: a basic test that sends a request to a URL by OpenAI API
- `perftest/`: performance test of the router

## Basic test

To run `test-openai.py`, you should first change the `BASE_URL` and `MODEL` in the script:

```python
BASE_URL = "http://<IP>:<PORT>/"  # Fill in <IP> and <PORT> according to your deployment
MODEL = "meta-llama/Llama-3.1-8B-Instruct"
```

Then, execute the following command in terminal:

```bash
python3 test-openai.py
```

You should see the output is streamed out in the terminal.

## Performance test of the router

The `perftest/` folder contains the performance test scripts for the router. Specifically, it has:

- `fake_openai_server.py`: a mock-up version of the OpenAI API server that accepts chat completion requests
- `request_generator.py`: the script that generates chat competition requests using multiple processes.
- `run-server.sh` and `run-multi-server.sh`: launches one or multiple mock-up OpenAI API server
- `clean-up.sh`: kills the mock-up OpenAI API server processes.

### Example router performance test

Here's an example setup of running the router performance test:

<img src="https://github.com/user-attachments/assets/ef680a8f-6c0c-48a9-a309-44a10dfd1e71" alt="Example setup of router's performance test" width="800"/>

- **Step 1**: launch the mock-up OpenAI API server by `bash run-multi-server.sh 4 500`
- **Step 2**: launch the router locally. See `src/router/perf-test.sh`
- **Step 3**: launch the request generator by `python3 request_generator.py --qps 10 --num-workers 32`
