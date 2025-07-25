Contributing
============

Thank you for your contribution to production-stack! As a potential contributor, your changes and ideas are welcome at any hour of the day or night, weekdays, weekends, and holidays. Please do not ever hesitate to ask a question or send a pull request.

Submitting a Proposal
---------------------

For **major changes, new features, or significant architectural modifications**, please **submit a proposal** under `proposals/ <https://github.com/vllm-project/production-stack/tree/main/proposals>`_ folder using the `designated template <https://github.com/vllm-project/production-stack/blob/main/proposals/TEMPLATE.md>`_ before contributing code. This ensures alignment with the project's goals, allows maintainers and contributors to provide feedback early, and helps prevent unnecessary rework.

Once submitted, your proposal will be reviewed by the maintainers, and discussions may take place before approval. We encourage open collaboration, so feel free to participate in the discussion and refine your proposal based on feedback.

*For small changes like bug fixes, documentation updates, minor optimizations, and simple features, feel free to directly create an issue or PR without the proposal.*

Opening a Pull Request
----------------------

Before submitting your pull request, please ensure it meets the following criteria. This helps maintain code quality and streamline the review process.

Follow the standard GitHub workflow:

1. Fork the repository.
2. Create a feature branch.
3. Submit a pull request with a detailed description.

PR Title and Classification
~~~~~~~~~~~~~~~~~~~~~~~~~~~

Please try to classify PRs for easy understanding of the type of changes. The PR title is prefixed appropriately to indicate the type of change. Please use one of the following:

- ``[Bugfix]`` for bug fixes.
- ``[CI/Build]`` for build or continuous integration improvements.
- ``[Doc]`` for documentation fixes and improvements.
- ``[Feat]`` for new features in the cluster (e.g., autoscaling, disaggregated prefill, etc.).
- ``[Router]`` for changes to the ``vllm_router`` (e.g., routing algorithm, router observability, etc.).
- ``[Misc]`` for PRs that do not fit the above categories. Please use this sparingly.

**Note:** If the PR spans more than one category, please include all relevant prefixes.

Code Quality and Validation
---------------------------

Linter Checks
~~~~~~~~~~~~~

Linter checks are parts of our github workflows. To pass all linter checks, please use ``pre-commit`` to format your code. It is installed as follows:

.. code-block:: bash

   uv sync --all-extras --all-groups
   uv run pre-commit install

It will run automatically before every commit. You can also run it manually on all files with:

.. code-block:: bash

   uv run pre-commit run --all-files

There are a subset of hooks which require additional dependencies that you may not have installed in your development environment (i.e. Docker and non-Python packages). These are configured to only run in the ``manual`` ``pre-commit`` stage. In CI they are run in the ``pre-commit-manual`` job, and locally they can be run with:

.. code-block:: bash

   # Runs all hooks including manual stage hooks
   uv run pre-commit run --all-files --hook-stage manual
   # Runs only the manual stage hook shellcheck
   uv run pre-commit run --all-files --hook-stage manual shellcheck

If any of these hooks are failing in CI but you cannot run them locally, you can identify what needs changing by examining the GitHub Actions logs in your pull request.

.. note::
   You can read more about ``pre-commit`` at https://pre-commit.com.

Github Workflows
~~~~~~~~~~~~~~~~

The PR must pass all GitHub workflows, which include:

- Router E2E tests
- Functionality tests of the helm chart

If any test fails, please check GitHub Actions for details on the failure. If you believe the error is unrelated to your PR, please explain your reasoning in the PR comments.

Adding Examples and Tests
-------------------------

Please include sufficient examples in your PR. Unit tests and integrations are also welcome, and you're encouraged to contribute them in future PRs.

DCO and Signed-off-by
---------------------

When contributing changes to this project, you must agree to the `DCO <https://github.com/vllm-project/vllm/blob/main/DCO>`_. Commits must include a ``Signed-off-by:`` header which certifies agreement with the terms of the DCO.

Using ``-s`` with ``git commit`` will automatically add this header.

What to Expect for the Reviews
------------------------------

We aim to address all PRs in a timely manner. If no one reviews your PR within 5 days, please @-mention one of YuhanLiu11, Shaoting-Feng or ApostaC.
