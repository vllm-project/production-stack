.. production-stack documentation master file, created by
   sphinx-quickstart on Mon Mar  3 12:36:28 2025.
   You can adapt this file completely to your liking, but it should at least
   contain the root `toctree` directive.

.. role:: raw-html(raw)
    :format: html

Welcome to production-stack!
==================================

.. figure:: ./assets/prodstack.png
  :width: 60%
  :align: center
  :alt: production-stack
  :class: no-scaled-link

.. raw:: html

   <p style="text-align:center">
   <strong> K8S-native cluster-wide deployment for vLLM.
   </strong>
   </p>

.. raw:: html

   <p style="text-align:center">
   <script async defer src="https://buttons.github.io/buttons.js"></script>
   <a class="github-button" href="https://github.com/vllm-project/production-stack" data-show-count="true" data-size="large" aria-label="Star">Star</a>
   <a class="github-button" href="https://github.com/vllm-project/production-stack/subscription" data-icon="octicon-eye" data-size="large" aria-label="Watch">Watch</a>
   <a class="github-button" href="https://github.com/vllm-project/production-stack/fork" data-show-count="true" data-icon="octicon-repo-forked" data-size="large" aria-label="Fork">Fork</a>
   </p>

**vLLM Production Stack** project provides a reference implementation on how to build an inference stack on top of vLLM, which allows you to:

- 🚀 Scale from single vLLM instance to distributed vLLM deployment without changing any application code
- 💻 Monitor the metrics through a web dashboard
- 😄 Enjoy the performance benefits brought by request routing and KV cache offloading
- 📈 Easily deploy the stack on AWS, GCP, or any other cloud provider


Documentation
==============================

.. Add your content using ``reStructuredText`` syntax. See the
.. `reStructuredText <https://www.sphinx-doc.org/en/master/usage/restructuredtext/index.html>`_
.. documentation for details.


.. toctree::
   :maxdepth: 2
   :caption: Getting Started

   getting_started/prerequisite
   getting_started/quickstart
   getting_started/faq

.. toctree::
   :maxdepth: 2
   :caption: Deployment

   deployment/index

.. toctree::
   :maxdepth: 2
   :caption: Use Cases

   use_cases/kv-cache-aware-routing
   use_cases/prefix-aware-routing
   use_cases/disaggregated-prefill
   use_cases/sharing-kv-cache
   use_cases/benchmarking
   use_cases/distributed-tracing
   use_cases/tool-enabled-installation
   use_cases/pipeline-parallelism-kuberay
   use_cases/sleep-wakeup-mode
   use_cases/autoscaling-keda

.. toctree::
   :maxdepth: 2
   :caption: Developer Guide

   developer_guide/contributing
   developer_guide/docker

.. toctree::
   :maxdepth: 2
   :caption: Community

   community/meetings
