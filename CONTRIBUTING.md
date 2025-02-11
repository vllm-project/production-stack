# Contributing 

<p>Thank you for your contribution to production-stack! Before submitting the pull request, please ensure the PR meets the following criteria. This helps us maintain the code quality and improve the efficiency of the review process.</p>

Please follow the standard GitHub flow:

1. Fork the repository.
2. Create a feature branch.
3. Submit a pull request with detailed descriptions.

<h3>PR Title and Classification</h3>
<p>Please try to classify PRs for easy understanding of the type of changes. The PR title is prefixed appropriately to indicate the type of change. Please use one of the following:</p>
<ul>
    <li><code>[Bugfix]</code> for bug fixes.</li>
    <li><code>[CI/Build]</code> for build or continuous integration improvements.</li>
    <li><code>[Doc]</code> for documentation fixes and improvements.</li>
    <li><code>[Feat]</code> for new features in the cluster (e.g., autoscaling, disaggregated prefill, etc.).</li>
    <li><code>[Router]</code> for changes to the <code>vllm_router</code> (e.g., routing algorithm, router observability, etc.).</li>
    <li><code>[Misc]</code> for PRs that do not fit the above categories. Please use this sparingly.</li>
</ul>
<p><strong>Note:</strong> If the PR spans more than one category, please include all relevant prefixes.</p>

<h3>Code Quality</h3>

<p>The PR need to meet the following code quality standards:</p>

<ul>
    <li>Pass all linter checks. Please use <code>pre-commit</code> to format your code.</li>
    <li>The code need to be well-documented to ensure future contributors can easily understand the code.</li>
    <li> Please include sufficient tests to ensure the change is stay correct and robust. This includes both unit tests and integration tests.</li>
</ul>

### Formatting

We use `pre-commit` for formatting, it is installed as follows:

```bash
pip install -r requirements-lint.txt
pre-commit install
```

It will run automatically before every commit. You can also run it manually on
all files with:

```bash
pre-commit run --all-files
```

There are a subset of hooks which require additional dependencies that you may
not have installed in your development environment (i.e. Docker and non-Python
packages). These are configured to only run in the `manual` `pre-commit` stage.
In CI they are run in the `pre-commit-manual` job, and locally they can be run
with:

```bash
# Runs all hooks including manual stage hooks
pre-commit run --all-files --hook-stage manual
# Runs only the manual stage hook shellcheck
pre-commit run --all-files --hook-stage manual shellcheck
```

If any of these hooks are failing in CI but you cannot run them locally, you
can identify what needs changing by examining the GitHub Actions logs in your
pull request.

> You can read more about `pre-commit` at <https://pre-commit.com>.


<h3>DCO and Signed-off-by</h3>
<p>When contributing changes to this project, you must agree to the <a href="https://github.com/vllm-project/vllm/blob/main/DCO">DCO</a>. Commits must include a <code>Signed-off-by:</code> header which certifies agreement with the terms of the DCO.</p>
<p>Using <code>-s</code> with <code>git commit</code> will automatically add this header.</p>

<h3>What to Expect for the Reviews</h3>

We aim to address all PRs in a timely manner. If no one reviews your PR within 5 days, please @-mention one of YuhanLiu11
, Shaoting-Feng or ApostaC.