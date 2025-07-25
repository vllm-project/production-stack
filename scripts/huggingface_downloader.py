import logging
import os

import fastapi
import uvicorn
from fastapi import HTTPException
from huggingface_hub import snapshot_download

logger = logging.getLogger(__name__)

app = fastapi.FastAPI()


@app.post("/model/download")
async def download(request: fastapi.Request):
    try:
        data = await request.json()
        model_id = data.get("model_id")
        local_dir = data.get("local_dir")
        token = data.get("hf_token")
        logger.info(f"Downloading {model_id} to {local_dir}")
        os.makedirs(local_dir, exist_ok=True)
        snapshot_download(model_id, local_dir=local_dir, token=token)
        return {"message": f"Successfully downloaded {model_id} to {local_dir}"}
    except Exception as e:
        logger.error(f"Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
