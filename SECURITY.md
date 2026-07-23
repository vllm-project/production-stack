# Security Policy

## Reporting security issues

Please report security issues privately using [the vulnerability submission form](https://github.com/vllm-project/production-stack/security/advisories/new).

## Issue triage

Reports will be triaged by the production-stack maintainers in coordination with the [vLLM vulnerability management team](https://docs.vllm.ai/en/latest/contributing/vulnerability_management.html).

## Threat model

The production-stack provides deployment and orchestration tooling for vLLM inference clusters. Security considerations include:

- **Cluster security**: Helm charts, Kubernetes configurations, and network policies must follow secure deployment practices
- **Router security**: The vLLM router handles request routing and load balancing, requiring proper authentication and authorization
- **Configuration security**: Secrets, credentials, and sensitive configuration must be properly managed
- **Deployment security**: Container images and dependencies should be kept up-to-date with security patches

Please see the [vLLM Security Guide](https://docs.vllm.ai/en/latest/usage/security.html) for more information on vLLM's security assumptions and recommendations.

Please see [PyTorch's Security Policy](https://github.com/pytorch/pytorch/blob/main/SECURITY.md) for more information on how to securely interact with models.

## Issue severity

We use the same severity categories as the vLLM project:

### CRITICAL Severity

Vulnerabilities that allow remote attackers to execute arbitrary code, take full control of the system, or significantly compromise confidentiality, integrity, or availability without any interaction or privileges needed. Generally those issues which are rated as CVSS ≥ 9.0.

### HIGH Severity

Serious security flaws that allow elevated impact—like RCE in specific, limited contexts or significant data loss—but require advanced conditions or some trust. Examples include RCE in advanced deployment modes or high impact issues where some sort of privileged network access is required. These issues typically have CVSS scores between 7.0 and 8.9.

### MODERATE Severity

Vulnerabilities that cause denial of service or partial disruption, but do not allow arbitrary code execution or data breach and have limited impact. These issues have a CVSS rating between 4.0 and 6.9.

### LOW Severity

Minor issues such as informational disclosures, logging errors, non-exploitable flaws, or weaknesses that require local or high-privilege access and offer negligible impact. These issues often have CVSS scores less than 4.0.

## Fix disclosure policy

When a security report is accepted, the fix process depends on the severity:

* **CRITICAL and HIGH severity**: Fixes are developed in a private security fork and coordinated with the prenotification group before public disclosure.
* **MODERATE and LOW severity**: Fixes are developed and submitted as public pull requests. These issues do not require embargo since they do not enable arbitrary code execution or significant data breach, and public visibility accelerates community review and adoption of the fix.

The vulnerability management team reserves the right to adjust the disclosure approach on a case-by-case basis, taking into account factors such as active exploitation, unusual attack surface, or coordination requirements with downstream vendors.

## Prenotification policy

For certain security issues of CRITICAL, HIGH, or MODERATE severity level, we may prenotify certain organizations or vendors that ship production-stack or vLLM. The purpose of this prenotification is to allow for a coordinated release of fixes for severe issues.

* This prenotification will be in the form of a private email notification. It may also include adding security contacts to the GitHub security advisory, typically a few days before release.

* If you wish to be added to the prenotification group, please send an email to the members of the [vLLM vulnerability management team](https://docs.vllm.ai/en/latest/contributing/vulnerability_management.html).
