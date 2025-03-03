from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from vllm_router.services.batch_service.processor import BatchProcessor
from vllm_router.services.files_service import Storage

batches_router = APIRouter()


@batches_router.post("/v1/batches")
async def route_batches(request: Request):
    """Handle batch requests that process files with specified endpoints."""
    try:
        request_json = await request.json()

        # Validate required fields
        if "input_file_id" not in request_json:
            return JSONResponse(
                status_code=400,
                content={"error": "Missing required parameter 'input_file_id'"},
            )
        if "endpoint" not in request_json:
            return JSONResponse(
                status_code=400,
                content={"error": "Missing required parameter 'endpoint'"},
            )

        # Verify file exists
        storage: Storage = request.app.state.batch_storage
        file_id = request_json["input_file_id"]
        try:
            await storage.get_file(file_id)
        except FileNotFoundError:
            return JSONResponse(
                status_code=404, content={"error": f"File {file_id} not found"}
            )

        batch_processor: BatchProcessor = request.app.state.batch_processor
        batch = await batch_processor.create_batch(
            input_file_id=file_id,
            endpoint=request_json["endpoint"],
            completion_window=request_json.get("completion_window", "5s"),
            metadata=request_json.get("metadata", None),
        )

        # Return metadata as attribute, not a callable.
        return JSONResponse(content=batch.to_dict())

    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"error": f"Failed to process batch request: {str(e)}"},
        )


@batches_router.get("/v1/batches/{batch_id}")
async def route_get_batch(request: Request, batch_id: str):
    try:
        batch_processor: BatchProcessor = request.app.state.batch_processor
        batch = await batch_processor.retrieve_batch(batch_id)
        return JSONResponse(content=batch.to_dict())
    except FileNotFoundError:
        return JSONResponse(
            status_code=404, content={"error": f"Batch {batch_id} not found"}
        )


@batches_router.get("/v1/batches")
async def route_list_batches(request: Request, limit: int = 20, after: str = None):
    try:
        batch_processor: BatchProcessor = request.app.state.batch_processor
        batches = await batch_processor.list_batches(limit=limit, after=after)

        # Convert batches to response format
        batch_data = [batch.to_dict() for batch in batches]

        response = {
            "object": "list",
            "data": batch_data,
            "first_id": batch_data[0]["id"] if batch_data else None,
            "last_id": batch_data[-1]["id"] if batch_data else None,
            "has_more": len(batch_data)
            == limit,  # If we got limit items, there may be more
        }

        return JSONResponse(content=response)
    except FileNotFoundError:
        return JSONResponse(status_code=404, content={"error": "No batches found"})


@batches_router.delete("/v1/batches/{batch_id}")
async def route_cancel_batch(request: Request, batch_id: str):
    try:
        batch_processor: BatchProcessor = request.app.state.batch_processor
        batch = await batch_processor.cancel_batch(batch_id)
        return JSONResponse(content=batch.to_dict())
    except FileNotFoundError:
        return JSONResponse(
            status_code=404, content={"error": f"Batch {batch_id} not found"}
        )
