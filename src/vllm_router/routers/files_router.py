from fastapi import APIRouter, Request, UploadFile
from fastapi.responses import JSONResponse, Response

from vllm_router.services.files_service import Storage

files_router = APIRouter()


# --- File Endpoints ---
@files_router.post("/v1/files")
async def route_files(request: Request):
    """
    Handle file upload requests and save the files to the configured storage.

    Args:
        request (Request): The incoming HTTP request.

    Returns:
        JSONResponse: A JSON response containing the file metadata.

    Raises:
        JSONResponse: A JSON response with a 400 status code if the request is invalid,
            or a 500 status code if an error occurs during file saving.
    """
    form = await request.form()
    purpose = form.get("purpose", "unknown")
    if "file" not in form:
        return JSONResponse(
            status_code=400, content={"error": "Missing required parameter 'file'"}
        )
    file_obj: UploadFile = form["file"]
    file_content = await file_obj.read()
    try:
        storage: Storage = request.app.state.batch_storage
        file_info = await storage.save_file(
            file_name=file_obj.filename, content=file_content, purpose=purpose
        )
        return JSONResponse(content=file_info.metadata())
    except Exception as e:
        return JSONResponse(
            status_code=500, content={"error": f"Failed to save file: {str(e)}"}
        )


@files_router.get("/v1/files/{file_id}")
async def route_get_file(request: Request, file_id: str):
    try:
        storage: Storage = request.app.state.batch_storage
        file = await storage.get_file(file_id)
        return JSONResponse(content=file.metadata())
    except FileNotFoundError:
        return JSONResponse(
            status_code=404, content={"error": f"File {file_id} not found"}
        )


@files_router.get("/v1/files/{file_id}/content")
async def route_get_file_content(request: Request, file_id: str):
    try:
        # TODO(gaocegege): Stream the file content with chunks to support
        # openai uploads interface.
        storage: Storage = request.app.state.batch_storage
        file_content = await storage.get_file_content(file_id)
        return Response(content=file_content)
    except FileNotFoundError:
        return JSONResponse(
            status_code=404, content={"error": f"File {file_id} not found"}
        )
