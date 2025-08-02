# Copyright 2024-2025 The vLLM Production Stack Authors.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Message queue for agent-to-agent communication."""

import asyncio
from typing import Dict, List, Optional, Tuple
import time
import logging

from vllm_router.models.workflow import AgentMessage
from vllm_router.log import init_logger

logger = init_logger(__name__)


class WorkflowMessageQueue:
    """Message queue for agent communication within workflows."""
    
    def __init__(
        self,
        max_queue_size: int = 1000,
        max_message_size: int = 1024 * 1024,  # 1MB
        cleanup_interval: int = 60
    ):
        """Initialize message queue.
        
        Args:
            max_queue_size: Maximum messages per agent queue
            max_message_size: Maximum message size in bytes
            cleanup_interval: Interval for cleanup task in seconds
        """
        # Queues indexed by (workflow_id, agent_id)
        self.queues: Dict[Tuple[str, str], asyncio.Queue] = {}
        self.max_queue_size = max_queue_size
        self.max_message_size = max_message_size
        self.cleanup_interval = cleanup_interval
        
        # Metrics
        self.total_messages_sent = 0
        self.total_messages_received = 0
        self.total_messages_expired = 0
        
        self._cleanup_task: Optional[asyncio.Task] = None
        self._lock = asyncio.Lock()
        
    async def start(self):
        """Start background cleanup task."""
        if self._cleanup_task is None:
            self._cleanup_task = asyncio.create_task(self._cleanup_loop())
            logger.info("Started message queue cleanup task")
            
    async def stop(self):
        """Stop background cleanup task."""
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
            self._cleanup_task = None
            logger.info("Stopped message queue cleanup task")
            
    async def _cleanup_loop(self):
        """Background task to clean up expired messages and empty queues."""
        while True:
            try:
                await asyncio.sleep(self.cleanup_interval)
                await self._cleanup_expired_messages()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in message cleanup loop: {e}")
                
    async def _cleanup_expired_messages(self):
        """Remove expired messages from all queues."""
        async with self._lock:
            empty_queues = []
            
            for key, queue in self.queues.items():
                # Check and remove expired messages
                temp_messages = []
                expired_count = 0
                
                # Get all messages from queue
                while not queue.empty():
                    try:
                        message = queue.get_nowait()
                        if not message.is_expired():
                            temp_messages.append(message)
                        else:
                            expired_count += 1
                    except asyncio.QueueEmpty:
                        break
                        
                # Put non-expired messages back
                for message in temp_messages:
                    await queue.put(message)
                    
                self.total_messages_expired += expired_count
                
                # Mark empty queues for removal
                if queue.empty():
                    empty_queues.append(key)
                    
            # Remove empty queues
            for key in empty_queues:
                del self.queues[key]
                
            if empty_queues or self.total_messages_expired > 0:
                logger.debug(
                    f"Cleaned up {len(empty_queues)} empty queues and "
                    f"{self.total_messages_expired} expired messages"
                )
                
    async def send_message(self, message: AgentMessage) -> bool:
        """Send message to agent.
        
        Args:
            message: Agent message to send
            
        Returns:
            True if sent successfully, False otherwise
        """
        # Validate message size
        import sys
        message_size = sys.getsizeof(message.payload)
        if message_size > self.max_message_size:
            logger.warning(
                f"Message too large ({message_size} bytes) for "
                f"agent {message.target_agent} in workflow {message.workflow_id}"
            )
            return False
            
        key = (message.workflow_id, message.target_agent)
        
        async with self._lock:
            # Create queue if it doesn't exist
            if key not in self.queues:
                self.queues[key] = asyncio.Queue(maxsize=self.max_queue_size)
                
            queue = self.queues[key]
            
            # Check if queue is full
            if queue.full():
                logger.warning(
                    f"Message queue full for agent {message.target_agent} "
                    f"in workflow {message.workflow_id}"
                )
                return False
                
            # Add message to queue
            try:
                await queue.put(message)
                self.total_messages_sent += 1
                
                logger.debug(
                    f"Sent message from {message.source_agent} to "
                    f"{message.target_agent} in workflow {message.workflow_id}"
                )
                return True
                
            except asyncio.QueueFull:
                logger.error("Queue full despite check")
                return False
                
    async def receive_messages(
        self,
        workflow_id: str,
        agent_id: str,
        timeout: Optional[float] = None,
        max_messages: int = 100
    ) -> List[AgentMessage]:
        """Receive messages for agent.
        
        Args:
            workflow_id: Workflow ID
            agent_id: Agent ID
            timeout: Maximum time to wait for messages
            max_messages: Maximum messages to return
            
        Returns:
            List of messages for the agent
        """
        key = (workflow_id, agent_id)
        
        async with self._lock:
            if key not in self.queues:
                return []
                
            queue = self.queues[key]
            
        messages = []
        deadline = time.time() + timeout if timeout else None
        
        while len(messages) < max_messages:
            try:
                # Calculate remaining timeout
                remaining_timeout = None
                if deadline:
                    remaining_timeout = deadline - time.time()
                    if remaining_timeout <= 0:
                        break
                        
                # Try to get message with timeout
                message = await asyncio.wait_for(
                    queue.get(),
                    timeout=remaining_timeout or 0.1
                )
                
                # Skip expired messages
                if not message.is_expired():
                    messages.append(message)
                    self.total_messages_received += 1
                else:
                    self.total_messages_expired += 1
                    
            except asyncio.TimeoutError:
                break
                
        if messages:
            logger.debug(
                f"Delivered {len(messages)} messages to agent {agent_id} "
                f"in workflow {workflow_id}"
            )
            
        return messages
        
    async def get_queue_stats(self) -> Dict[str, Any]:
        """Get message queue statistics."""
        async with self._lock:
            queue_sizes = {
                f"{wf_id}:{agent_id}": queue.qsize()
                for (wf_id, agent_id), queue in self.queues.items()
            }
            
            return {
                "total_queues": len(self.queues),
                "total_messages_sent": self.total_messages_sent,
                "total_messages_received": self.total_messages_received,
                "total_messages_expired": self.total_messages_expired,
                "queue_sizes": queue_sizes,
                "max_queue_size": max(queue_sizes.values()) if queue_sizes else 0,
                "total_pending_messages": sum(queue_sizes.values())
            }
            
    async def clear_workflow_messages(self, workflow_id: str):
        """Clear all messages for a workflow."""
        async with self._lock:
            keys_to_remove = [
                key for key in self.queues.keys()
                if key[0] == workflow_id
            ]
            
            for key in keys_to_remove:
                del self.queues[key]
                
            logger.info(f"Cleared {len(keys_to_remove)} queues for workflow {workflow_id}")