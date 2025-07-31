import logging
import os
from typing import Optional

import fastapi
import uvicorn
from fastapi import HTTPException
from huggingface_hub import snapshot_download
from pydantic import BaseModel

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

app = fastapi.FastAPI()


class DownloadRequest(BaseModel):
    model_id: str
    local_dir: str
    token: Optional[str] = None


@app.post("/model/download")
async def download(request: DownloadRequest):
    try:
        DOWNLOAD_BASE_DIR = os.path.abspath(
            os.environ.get("LORA_DOWNLOAD_BASE_DIR", "/data/lora-adapters")
        )

        target_dir = os.path.abspath(os.path.join(DOWNLOAD_BASE_DIR, request.local_dir))
        model_id = request.model_id
        if not target_dir.startswith(DOWNLOAD_BASE_DIR):
            raise HTTPException(status_code=400, detail="Invalid 'local_dir' provided.")

        logger.info(f"Downloading {model_id} to {target_dir}")
        os.makedirs(target_dir, exist_ok=True)
        snapshot_download(model_id, local_dir=target_dir, token=request.token)
        return {"message": f"Successfully downloaded {model_id} to {target_dir}"}
    except Exception as e:
        logger.exception(f"Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
