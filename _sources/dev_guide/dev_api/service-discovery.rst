.. _service-discovery:

Service Discovery
=================

Batch Service
++++++++++++++

.. autoclass:: vllm_router.services.batch_service.batch.BatchStatus
    :members:
    :show-inheritance:

.. autoclass:: vllm_router.services.batch_service.batch.BatchEndpoint
    :members:
    :show-inheritance:

.. autoclass:: vllm_router.services.batch_service.batch.BatchRequest
    :members:
    :show-inheritance:

.. autoclass:: vllm_router.services.batch_service.batch.BatchInfo
    :members:
    :show-inheritance:

File Service
++++++++++++

.. autoclass:: vllm_router.services.files_service.file_storage.FileStorage
    :members:
    :show-inheritance:

Request Service
+++++++++++++++

.. autofunction:: vllm_router.services.request_service.request.process_request

.. autofunction:: vllm_router.services.request_service.request.route_general_request
