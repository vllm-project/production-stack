from setuptools import find_packages, setup

setup(
    name="vllm-router",
    use_scm_version=True,
    setup_requires=["setuptools_scm"],
    packages=find_packages(where="src"),
    package_dir={"": "src"},
    # Should be the same as src/router/requirements.txt
    install_requires=[
        "numpy==1.26.4",
        "fastapi==0.115.8",
        "httpx==0.28.1",
        "uvicorn==0.34.0",
        "kubernetes==32.0.0",
        "prometheus_client==0.21.1",
        "uhashring==2.3",
        "aiofiles==24.1.0",
        "python-multipart==0.0.20",
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
    python_requires=">=3.7",
)
