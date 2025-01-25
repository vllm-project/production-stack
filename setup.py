from setuptools import setup, find_packages

setup(
    name="vllm-router",
    version="0.1.0",
    packages=find_packages(where="src"),
    package_dir={"": "src"},
    # Should be the same as src/router/requirements.txt
    install_requires=[
        "numpy",
        "fastapi",
        "httpx",
        "uvicorn",
        "kubernetes",
        "prometheus_client",
        "uhashring",
    ],
    entry_points={
        "console_scripts": [
            "vllm-router=vllm_router.router:main",
        ],
    },
    description="The router for vLLM",
    license="Apache 2.0",
    url="https://github.com/vllm-project/production-stack",
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
    python_requires='>=3.7',
)
