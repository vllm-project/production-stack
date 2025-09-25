
# Build documentation locally

## Install Prerequisites

```bash
pip install -r requirements-docs.txt
```

## Build docs

First run

```bash
make clean
```

To build HTML

```bash
make html
```

Serve documentation page locally

```bash
python -m http.server 8000 -d build/html/
```

### Launch your browser and open localhost:8000
