.. _dev_interfaces:

Interfaces
================

Adding a new router using ``RoutingInterface``
----------------------------------------------

The following class provides the structure of the ``RoutingInterface``. This strategy cycles through the available endpoints in order.

.. code-block:: python

    class RoutingInterface(metaclass=SingletonABCMeta):
    @abc.abstractmethod
    def route_request(
        self,
        endpoints: List[EndpointInfo],
        engine_stats: Dict[str, EngineStats],
        request_stats: Dict[str, RequestStats],
        request: Request,
    ) -> str:
        """
        Route the request to the appropriate engine URL

        Args:
            endpoints (List[EndpointInfo]): The list of engine URLs
            engine_stats (Dict[str, EngineStats]): The engine stats indicating
                the 'physical' load of each engine
            request_stats (Dict[str, RequestStats]): The request stats
                indicating the request-level performance of each engine
            request (Request): The incoming request
        """
        raise NotImplementedError()

Implementing a Custom Router
----------------------------

To add a new routing strategy, follow these steps:

1. Create a new class that inherits from ``RoutingInterface``.
2. Implement the ``route_request`` method to define custom routing logic.
3. Ensure the new class maintains the expected method signature.

Example: Least Connections Router
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Below is an example implementation of a ``LeastConnectionsRouter`` that routes requests to the endpoint with the fewest active connections.

.. code-block:: python

    class LeastConnectionsRouter(RoutingInterface):
        def __init__(self):
            if hasattr(self, "_initialized"):
                return
            self._initialized = True

        def route_request(
            self,
            endpoints: List[EndpointInfo],
            engine_stats: Dict[str, EngineStats],
            request_stats: Dict[str, RequestStats],
            request: Request,
        ) -> str:
            """
            Route the request to the engine with the least active connections.

            Args:
                endpoints (List[EndpointInfo]): The list of engine URLs.
                engine_stats (Dict[str, EngineStats]): The engine stats indicating
                    the 'physical' load of each engine.
                request_stats (Dict[str, RequestStats]): The request stats
                    indicating the request-level performance of each engine.
                request (Request): The incoming request.
            """
            chosen = min(endpoints, key=lambda e: engine_stats[e.url].active_connections)
            return chosen.url

Usage
~~~~~

To use a custom router, instantiate it and call ``route_request`` with the required parameters:

.. code-block:: python

    router = LeastConnectionsRouter()
    selected_url = router.route_request(endpoints, engine_stats, request_stats, request)
    print(f"Routing to: {selected_url}")

By following this approach, you can extend the routing system with custom logic tailored to different workload distribution strategies.
