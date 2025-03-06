"""
Envoy External Processing (extproc) service implementation for vllm_router.

This module provides the implementation of the Envoy External Processing service
that integrates with vllm_router's semantic cache functionality.
"""

import asyncio
import json
import logging
import time
import uuid
import signal
from typing import Dict, List, Optional, Any, Tuple

import grpc
from grpc.aio import server as aio_server

try:
    # Import the generated Envoy extproc protobuf code
    from envoy_data_plane.envoy.service.ext_proc.v3 import (
        ProcessingRequest,
        ProcessingResponse,
        HeadersResponse,
        BodyResponse,
        CommonResponse,
        HeaderMutation,
        ImmediateResponse,
        ExternalProcessorBase
    )
    # Import the core and type modules directly
    from envoy_data_plane.envoy.config.core.v3 import HeaderMap, HeaderValue
    from envoy_data_plane.envoy.type.v3 import HttpStatus
    extproc_available = True
except ImportError as e:
    import traceback
    print("Import error in service.py")
    traceback.print_exc()
    exit(1)
    extproc_available = False

try:
    # Semantic cache integration
    from vllm_router.experimental.semantic_cache import (
        GetSemanticCache,
        enable_semantic_cache,
        initialize_semantic_cache,
        is_semantic_cache_enabled,
    )
    from vllm_router.experimental.semantic_cache_integration import (
        check_semantic_cache,
        semantic_cache_hit_ratio,
        semantic_cache_hits,
        semantic_cache_latency,
        semantic_cache_misses,
        semantic_cache_size,
    )

    semantic_cache_available = True
except ImportError:
    semantic_cache_available = False

logger = logging.getLogger("vllm_router.extproc")


class ExtProcService(ExternalProcessorBase):
    """
    Envoy External Processing service implementation for vllm_router.
    
    This service processes requests and responses from Envoy, integrating with
    vllm_router's semantic cache functionality to provide cache hits when possible.
    """
    
    def __init__(self, name: str = "VLLMRouterExtProc"):
        """
        Initialize the ExtProcService.
        
        Args:
            name: The name of the service
        """
        self.name = name
        self.request_contexts: Dict[str, Dict[str, Any]] = {}
        
        if not semantic_cache_available:
            logger.warning("Semantic cache is not available. The extproc service will pass through all requests.")
        elif not is_semantic_cache_enabled():
            logger.warning("Semantic cache is not enabled. The extproc service will pass through all requests.")
    
    async def Process(self, request_iterator, context):
        """
        Process requests from Envoy.
        
        This is the main gRPC method that Envoy calls to process requests and responses.
        
        Args:
            request_iterator: Iterator of ProcessingRequest messages from Envoy
            context: gRPC context
            
        Yields:
            ProcessingResponse messages to Envoy
        """
        # Generate a unique ID for this request
        request_id = str(uuid.uuid4())
        self.request_contexts[request_id] = {
            "headers": {},
            "body": b"",
            "is_chat_completion": False,
            "model": "",
            "messages": [],
            "skip_cache": False,
        }
        
        try:
            async for request in request_iterator:
                response = await self._handle_processing_request(request_id, request)
                if response:
                    yield response
                    
        except Exception as e:
            logger.error(f"Error processing request {request_id}: {str(e)}")
            # Return an immediate response to avoid hanging Envoy
            yield self._create_immediate_response()
        finally:
            # Clean up the request context
            if request_id in self.request_contexts:
                del self.request_contexts[request_id]
    
    async def _handle_processing_request(self, request_id: str, request: ProcessingRequest) -> Optional[ProcessingResponse]:
        """
        Handle a single processing request from Envoy.
        
        Args:
            request_id: The unique ID for this request
            request: The ProcessingRequest from Envoy
            
        Returns:
            A ProcessingResponse or None if no response is needed
        """
        # Determine which part of the request/response we're processing
        if request.HasField("request_headers"):
            return await self._handle_request_headers(request_id, request.request_headers)
        elif request.HasField("request_body"):
            return await self._handle_request_body(request_id, request.request_body)
        elif request.HasField("response_headers"):
            return await self._handle_response_headers(request_id, request.response_headers)
        elif request.HasField("response_body"):
            return await self._handle_response_body(request_id, request.response_body)
        
        # For any other message types, just continue processing
        return self._create_immediate_response()
    
    async def _handle_request_headers(self, request_id: str, headers) -> ProcessingResponse:
        """
        Handle request headers from Envoy.
        
        Args:
            request_id: The unique ID for this request
            headers: The request headers
            
        Returns:
            A ProcessingResponse
        """
        context = self.request_contexts[request_id]
        
        # Extract headers into a dictionary
        for header in headers.headers.headers:
            key = header.key.lower()
            value = header.value
            context["headers"][key] = value
        
        # Check if this is a chat completion request
        path = context["headers"].get(":path", "")
        method = context["headers"].get(":method", "")
        
        if path == "/v1/chat/completions" and method == "POST":
            context["is_chat_completion"] = True
            # Request the body to check for cache
            return self._create_body_request_response()
        
        # For non-chat completion requests, just continue processing
        return self._create_immediate_response()
    
    async def _handle_request_body(self, request_id: str, body) -> ProcessingResponse:
        """
        Handle request body from Envoy.
        
        Args:
            request_id: The unique ID for this request
            body: The request body
            
        Returns:
            A ProcessingResponse
        """
        context = self.request_contexts[request_id]
        
        # Append the body chunk to the existing body
        if body.body:
            context["body"] += body.body
        
        # If this is the end of the body and it's a chat completion request,
        # check if we can serve from cache
        if body.end_of_stream and context["is_chat_completion"]:
            try:
                # Parse the JSON body
                body_json = json.loads(context["body"])
                
                # Extract relevant fields
                context["model"] = body_json.get("model", "")
                context["messages"] = body_json.get("messages", [])
                context["skip_cache"] = body_json.get("skip_cache", False)
                
                # Check if we can serve from cache
                if semantic_cache_available and is_semantic_cache_enabled() and not context["skip_cache"]:
                    cache_start_time = time.time()
                    
                    # Get the semantic cache
                    semantic_cache = GetSemanticCache()
                    if semantic_cache:
                        # Search the cache
                        similarity_threshold = body_json.get("cache_similarity_threshold", None)
                        cache_result = semantic_cache.search(
                            messages=context["messages"],
                            model=context["model"],
                            similarity_threshold=similarity_threshold
                        )
                        
                        # Record cache lookup latency
                        cache_latency = time.time() - cache_start_time
                        semantic_cache_latency.labels(server="router").set(cache_latency)
                        
                        if cache_result:
                            # Cache hit
                            semantic_cache_hits.labels(server="router").inc()
                            
                            # Construct the response
                            response_json = {
                                "id": f"chatcmpl-{uuid.uuid4()}",
                                "object": "chat.completion",
                                "created": int(time.time()),
                                "model": context["model"],
                                "choices": [
                                    {
                                        "index": i,
                                        "message": response_msg,
                                        "finish_reason": "stop"
                                    } for i, response_msg in enumerate(cache_result["response_messages"])
                                ],
                                "usage": cache_result["usage"],
                                "cached": True,
                                "similarity_score": cache_result["similarity_score"]
                            }
                            
                            # Return an immediate response with the cached result
                            return self._create_immediate_response_with_body(
                                json.dumps(response_json).encode(),
                                headers=[
                                    (":status", "200"),
                                    ("content-type", "application/json"),
                                    ("x-cache-hit", "true"),
                                    ("x-similarity-score", str(cache_result["similarity_score"]))
                                ]
                            )
                        else:
                            # Cache miss
                            semantic_cache_misses.labels(server="router").inc()
            except Exception as e:
                logger.error(f"Error checking cache for request {request_id}: {str(e)}")
        
        # If we get here, either it's not a chat completion request, or there was no cache hit
        return self._create_immediate_response()
    
    async def _handle_response_headers(self, request_id: str, headers) -> ProcessingResponse:
        """
        Handle response headers from Envoy.
        
        Args:
            request_id: The unique ID for this request
            headers: The response headers
            
        Returns:
            A ProcessingResponse
        """
        context = self.request_contexts[request_id]
        
        # For chat completion requests, we want to see the response body
        # so we can cache it for future requests
        if context["is_chat_completion"]:
            return self._create_body_request_response()
        
        # For non-chat completion requests, just continue processing
        return self._create_immediate_response()
    
    async def _handle_response_body(self, request_id: str, body) -> ProcessingResponse:
        """
        Handle response body from Envoy.
        
        Args:
            request_id: The unique ID for this request
            body: The response body
            
        Returns:
            A ProcessingResponse
        """
        context = self.request_contexts[request_id]
        
        # If this is a chat completion request and we have the full body,
        # store it in the cache for future requests
        if body.end_of_stream and context["is_chat_completion"] and semantic_cache_available and is_semantic_cache_enabled():
            try:
                # Parse the JSON response
                response_json = json.loads(body.body)
                
                # Extract response messages and usage
                response_messages = []
                if "choices" in response_json:
                    for choice in response_json["choices"]:
                        if "message" in choice:
                            response_messages.append(choice["message"])
                
                usage = response_json.get("usage", {
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "total_tokens": 0
                })
                
                # Store in the cache
                semantic_cache = GetSemanticCache()
                if semantic_cache and not context["skip_cache"]:
                    semantic_cache.store(
                        request_messages=context["messages"],
                        response_messages=response_messages,
                        model=context["model"],
                        usage=usage
                    )
                    
                    # Update cache size metric
                    if hasattr(semantic_cache, "db") and hasattr(semantic_cache.db, "index"):
                        semantic_cache_size.labels(server="router").set(
                            semantic_cache.db.index.ntotal
                        )
            except Exception as e:
                logger.error(f"Error storing in cache for request {request_id}: {str(e)}")
        
        # Continue processing
        return self._create_immediate_response()
    
    def _create_immediate_response(self) -> ProcessingResponse:
        """
        Create an immediate response to continue processing.
        
        Returns:
            A ProcessingResponse
        """
        return ProcessingResponse(
            immediate_response=ImmediateResponse()
        )
    
    def _create_body_request_response(self) -> ProcessingResponse:
        """
        Create a response that requests the body.
        
        Returns:
            A ProcessingResponse
        """
        return ProcessingResponse(
            request_body=BodyResponse()
        )
    
    def _create_immediate_response_with_body(self, body: bytes, headers: List[Tuple[str, str]]) -> ProcessingResponse:
        """
        Create an immediate response with a custom body and headers.
        
        Args:
            body: The response body
            headers: List of headers to add
            
        Returns:
            A ProcessingResponse
        """
        # Create header mutations
        header_mutations = []
        for name, value in headers:
            header_mutations.append(
                HeaderValue(
                    key=name,
                    value=value
                )
            )
        
        return ProcessingResponse(
            immediate_response=ImmediateResponse(
                status=HttpStatus(code=200),
                headers=HeaderMutation(
                    set_headers=header_mutations
                ),
                body=body
            )
        )


async def _serve_extproc_async(service, port: int = 50051, grace_period: int = 5):
    """
    Start the gRPC server for the ExtProcService.
    
    Args:
        service: The ExtProcService instance
        port: The port to listen on
        grace_period: Grace period in seconds for shutdown
    """
    if not extproc_available:
        logger.error("Envoy extproc protobuf definitions not available. Cannot start extproc service.")
        return
    
    # Import necessary modules
    from grpc import ServicerContext
    from grpc.aio import server as aio_server
    
    # Create a gRPC server
    server = aio_server()
    
    # Add the service to the server
    # For grpc.aio server, we need to use add_generic_rpc_handlers
    
    # Create a generic handler for the service
    generic_handler = grpc.method_handlers_generic_handler(
        "envoy.service.ext_proc.v3.ExternalProcessor",
        {
            "Process": grpc.stream_stream_rpc_method_handler(
                service.process,
                request_deserializer=ProcessingRequest.FromString if hasattr(ProcessingRequest, "FromString") else None,
                response_serializer=ProcessingResponse.SerializeToString if hasattr(ProcessingResponse, "SerializeToString") else None,
            )
        }
    )
    
    # Add the generic handler to the server
    server.add_generic_rpc_handlers((generic_handler,))
    
    # Add a port to the server
    server_address = f"[::]:{port}"
    server.add_insecure_port(server_address)
    
    # Start the server
    await server.start()
    logger.info(f"ExtProcService listening on {server_address}")
    
    # Function to handle graceful shutdown
    async def _shutdown():
        logger.info("Shutting down ExtProcService...")
        # Give clients time to disconnect
        await asyncio.sleep(grace_period)
        await server.stop(None)
        logger.info("ExtProcService shutdown complete")
    
    # Handle signals for graceful shutdown
    for signal_name in ('SIGINT', 'SIGTERM'):
        loop = asyncio.get_running_loop()
        try:
            loop.add_signal_handler(
                getattr(signal, signal_name),
                lambda: asyncio.create_task(_shutdown())
            )
        except NotImplementedError:
            # Windows doesn't support add_signal_handler
            pass
    
    # Keep the server running
    await server.wait_for_termination()


def serve_extproc(service=None, port: int = 50051, grace_period: int = 5):
    """
    Start the gRPC server for the ExtProcService.
    
    Args:
        service: The ExtProcService instance, or None to create a new one
        port: The port to listen on
        grace_period: Grace period in seconds for shutdown
    """
    if service is None:
        service = ExtProcService()
    
    # Run the server
    asyncio.run(_serve_extproc_async(service, port, grace_period)) 