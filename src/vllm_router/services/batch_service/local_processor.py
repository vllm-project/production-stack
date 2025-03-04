import asyncio
import datetime
import json
import os
import time
from typing import List, Optional
from uuid import uuid4

import aiosqlite

from vllm_router.batch.batch import BatchInfo, BatchStatus
from vllm_router.log import init_logger
from vllm_router.services.batch_service.processor import BatchProcessor
from vllm_router.services.files_service import Storage

logger = init_logger(__name__)


class LocalBatchProcessor(BatchProcessor):
    """SQLite-backed batch processor with background processing."""

    def __init__(self, db_dir: str, storage: Storage):
        super().__init__(storage)
        os.makedirs(db_dir, exist_ok=True)
        self.db_path = os.path.join(db_dir, "batch_queue.db")
        self._initialized = False

    async def initialize(self):
        if not self._initialized:
            logger.info(
                "Initializing LocalBatchProcessor with SQLite DB at %s", self.db_path
            )
            await self.setup_db()
            asyncio.create_task(self.process_batches())
            self._initialized = True

    async def setup_db(self):
        """Setup the SQLite table for all batch fields."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "CREATE TABLE IF NOT EXISTS batch_queue ("
                "batch_id TEXT PRIMARY KEY, "
                "status TEXT, "
                "input_file_id TEXT, "
                "created_at INTEGER, "
                "endpoint TEXT, "
                "completion_window TEXT, "
                "output_file_id TEXT, "
                "completed_at INTEGER, "
                "metadata TEXT"
                ")"
            )
            await db.commit()

    async def create_batch(
        self,
        input_file_id: str,
        endpoint: str,
        completion_window: str,
        metadata: Optional[dict] = None,
    ) -> BatchInfo:
        batch_id = "batch_" + uuid4().hex[:6]
        ts_now = int(time.time())
        batch_info = BatchInfo(
            id=batch_id,
            status=BatchStatus.PENDING,
            input_file_id=input_file_id,
            created_at=ts_now,
            endpoint=endpoint,
            completion_window=completion_window,
            output_file_id=None,
            completed_at=None,
            metadata=metadata or {},
        )
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "INSERT INTO batch_queue (batch_id, status, input_file_id, created_at, endpoint, completion_window, output_file_id, completed_at, metadata) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    batch_id,
                    BatchStatus.PENDING,
                    input_file_id,
                    ts_now,
                    endpoint,
                    completion_window,
                    None,
                    None,
                    json.dumps(batch_info.metadata),
                ),
            )
            await db.commit()
        logger.info("Created batch job %s", batch_id)
        return batch_info

    async def retrieve_batch(self, batch_id: str) -> BatchInfo:
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                "SELECT status, input_file_id, created_at, endpoint, completion_window, output_file_id, completed_at, metadata FROM batch_queue WHERE batch_id = ?",
                (batch_id,),
            ) as cursor:
                row = await cursor.fetchone()
                if row is None:
                    raise ValueError(f"Batch {batch_id} not found")
                (
                    status,
                    input_file_id,
                    created_at,
                    endpoint,
                    completion_window,
                    output_file_id,
                    completed_at,
                    metadata,
                ) = row
                # Convert status string to BatchStatus enum.
                from vllm_router.batch.batch import BatchStatus

                return BatchInfo(
                    id=batch_id,
                    status=BatchStatus(status),
                    input_file_id=input_file_id,
                    created_at=created_at,
                    endpoint=endpoint,
                    completion_window=completion_window,
                    output_file_id=output_file_id,
                    completed_at=completed_at,
                    metadata=json.loads(metadata) if metadata else {},
                )

    async def list_batches(
        self, limit: int = 100, after: str = None
    ) -> List[BatchInfo]:
        async with aiosqlite.connect(self.db_path) as db:
            query = "SELECT batch_id FROM batch_queue"
            params = ()
            if after:
                query += " WHERE created_at > ?"
                params = (after,)
            query += " ORDER BY created_at DESC LIMIT ?"
            params += (limit,)
            async with db.execute(query, params) as cursor:
                rows = await cursor.fetchall()
                return [await self.retrieve_batch(row[0]) for row in rows]

    async def cancel_batch(self, batch_id: str) -> BatchInfo:
        # Retrieve current batch info
        batch_info = await self.retrieve_batch(batch_id)
        if batch_info.status not in [BatchStatus.COMPLETED, BatchStatus.FAILED]:
            batch_info.status = "cancelled"
            batch_info.completed_at = int(time.time())
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute(
                    "UPDATE batch_queue SET status = ?, completed_at = ? WHERE batch_id = ?",
                    (batch_info.status, batch_info.completed_at, batch_id),
                )
                await db.commit()
        return batch_info

    async def process_batches(self):
        """Continuously poll the DB for pending batches and process them."""
        while True:
            async with aiosqlite.connect(self.db_path) as db:
                async with db.execute(
                    "SELECT batch_id FROM batch_queue WHERE status = ? ORDER BY created_at LIMIT 1",
                    (BatchStatus.PENDING,),
                ) as cursor:
                    row = await cursor.fetchone()
                    if row is None:
                        # No pending batch; pause briefly
                        await asyncio.sleep(1)
                        continue
                    batch_id = row[0]
                    # Mark as processing
                    await db.execute(
                        "UPDATE batch_queue SET status = ? WHERE batch_id = ?",
                        ("running", batch_id),
                    )
                    await db.commit()
            try:
                logger.info("Processing batch %s", batch_id)
                # TODO(gaocegege): Replace with actual processing logic
                # Simulate processing delay
                await asyncio.sleep(1)
                # Simulate generating output file via storage
                result_content = (
                    f"Processed batch {batch_id} at {datetime.datetime.utcnow()}"
                )
                file_info = await self.storage.save_file(
                    file_name=f"{batch_id}_result.txt",
                    content=result_content.encode("utf-8"),
                    purpose="batch_output",
                )
                completed_at = int(time.time())
                new_status = BatchStatus.COMPLETED
                output_file_id = (
                    file_info.id if hasattr(file_info, "id") else "output_id"
                )
            except Exception as e:
                logger.error("Failed processing batch %s: %s", batch_id, e)
                new_status = BatchStatus.FAILED
                completed_at = int(time.time())
                output_file_id = None
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute(
                    "UPDATE batch_queue SET status = ?, completed_at = ?, output_file_id = ? WHERE batch_id = ?",
                    (new_status, completed_at, output_file_id, batch_id),
                )
                await db.commit()
            # Short sleep to avoid tight polling loop if many jobs are queued
            await asyncio.sleep(0.1)
