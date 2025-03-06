## Install Prerequisites
```
pip install -r requirements-docs.txt
```
## Build docs locally from source

First run 

``` 
make clean
```

To build HTML

```
make html
```

Serve documentation page locally

```
python -m http.server 8000 -d build/html/
```

#### Launch your browser and open localhost:8000.
