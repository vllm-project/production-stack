import os

from setuptools import find_packages, setup

# Semantic cache dependencies
semantic_cache_deps = [
    "sentence-transformers==2.2.2",
    "faiss-cpu==1.10.0",
    "huggingface-hub==0.25.2",  # downgrade to 0.25.2 to avoid breaking changes
]

install_requires = [
    "numpy==1.26.4",
    "fastapi==0.115.8",
    "httpx==0.28.1",
    "uvicorn==0.34.0",
    "kubernetes==32.0.0",
    "prometheus_client==0.21.1",
    "uhashring==2.3",
    "aiofiles==24.1.0",
    "python-multipart==0.0.20",
]

# Add semantic cache deps to install_requires if env var is set
if os.getenv("INSTALL_SENTENCE_TRANSFORMERS", "true") == "true":
    install_requires.extend(semantic_cache_deps)

# Optional dependencies
extras_require = {
    "semantic_cache": semantic_cache_deps,
}

setup(
    name="vllm-router",
    use_scm_version=True,
    setup_requires=["setuptools_scm"],
    packages=find_packages(where="src"),
    package_dir={"": "src"},
    # Should be the same as src/vllm_router/requirements.txt
    install_requires=install_requires,
    extras_require=extras_require,
    entry_points={
        "console_scripts": [
            "vllm-router=vllm_router.app:main",
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
    python_requires=">=3.12",
)
