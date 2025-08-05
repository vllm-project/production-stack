#!/usr/bin/env python3
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

"""Benchmark script for workflow-aware routing performance."""

import asyncio
import argparse
import json
import time
import statistics
from typing import List, Dict, Any
import uuid

import aiohttp


class WorkflowBenchmark:
    """Benchmark suite for multi-agent workflows."""
    
    def __init__(self, base_url: str = "http://localhost:8000"):
        """Initialize benchmark.
        
        Args:
            base_url: Base URL of vLLM router
        """
        self.base_url = base_url
        self.session: aiohttp.ClientSession = None
        
    async def __aenter__(self):
        """Start HTTP session."""
        self.session = aiohttp.ClientSession()
        return self
        
    async def __aexit__(self, *args):
        """Close HTTP session."""
        if self.session:
            await self.session.close()
            
    async def send_completion_request(
        self,
        prompt: str,
        model: str = "meta-llama/Llama-3.1-8B-Instruct",
        max_tokens: int = 100,
        workflow_metadata: Dict = None
    ) -> Dict[str, Any]:
        """Send completion request.
        
        Args:
            prompt: Input prompt
            model: Model name
            max_tokens: Maximum tokens to generate
            workflow_metadata: Workflow metadata (optional)
            
        Returns:
            Request result with timing
        """
        start_time = time.time()
        
        request_data = {
            "model": model,
            "prompt": prompt,
            "max_tokens": max_tokens,
            "temperature": 0.7
        }
        
        if workflow_metadata:
            request_data["workflow_metadata"] = workflow_metadata
            
        try:
            async with self.session.post(
                f"{self.base_url}/v1/completions",
                json=request_data,
                timeout=aiohttp.ClientTimeout(total=60)
            ) as response:
                result = await response.json()
                latency = time.time() - start_time
                
                # Safely count tokens
                tokens = 0
                if result.get("choices") and len(result["choices"]) > 0:
                    text = result["choices"][0].get("text", "")
                    if text and isinstance(text, str):
                        tokens = len(text.split())
                
                return {
                    "status": "success",
                    "latency": latency,
                    "status_code": response.status,
                    "tokens": tokens,
                    "workflow_metadata": workflow_metadata
                }
                
        except Exception as e:
            return {
                "status": "error",
                "latency": time.time() - start_time,
                "error": str(e),
                "workflow_metadata": workflow_metadata
            }
    
    async def benchmark_sequential_agents(
        self,
        num_agents: int = 5,
        shared_context: str = "Analyze the following sales data: Q1: $100k, Q2: $150k, Q3: $120k, Q4: $200k"
    ) -> Dict[str, Any]:
        """Benchmark sequential agent execution.
        
        Args:
            num_agents: Number of agents in sequence
            shared_context: Shared context for all agents
            
        Returns:
            Benchmark results
        """
        workflow_id = f"sequential-{uuid.uuid4().hex[:8]}"
        results = []
        
        print(f"Running sequential benchmark with {num_agents} agents...")
        
        for i in range(num_agents):
            prompt = f"{shared_context}\n\nAgent {i+1}: What is your analysis of this data?"
            
            result = await self.send_completion_request(
                prompt=prompt,
                workflow_metadata={
                    "workflow_id": workflow_id,
                    "agent_id": f"agent-{i+1}",
                    "parent_request_id": results[-1].get("request_id") if results else None
                }
            )
            results.append(result)
            
            if result["status"] == "success":
                print(f"  Agent {i+1}: {result['latency']:.2f}s")
            else:
                print(f"  Agent {i+1}: ERROR - {result['error']}")
        
        total_latency = sum(r["latency"] for r in results)
        successful_results = [r for r in results if r["status"] == "success"]
        
        return {
            "type": "sequential",
            "workflow_id": workflow_id,
            "num_agents": num_agents,
            "total_latency": total_latency,
            "avg_latency": statistics.mean(r["latency"] for r in successful_results) if successful_results else 0,
            "success_rate": len(successful_results) / len(results) if results else 0.0,
            "results": results
        }
    
    async def benchmark_parallel_agents(
        self,
        num_agents: int = 5,
        shared_context: str = "Analyze the following sales data: Q1: $100k, Q2: $150k, Q3: $120k, Q4: $200k"
    ) -> Dict[str, Any]:
        """Benchmark parallel agent execution.
        
        Args:
            num_agents: Number of parallel agents
            shared_context: Shared context for all agents
            
        Returns:
            Benchmark results
        """
        workflow_id = f"parallel-{uuid.uuid4().hex[:8]}"
        
        print(f"Running parallel benchmark with {num_agents} agents...")
        
        # Create tasks for parallel execution
        async def agent_task(agent_id: str, agent_num: int):
            prompt = f"{shared_context}\n\nAgent {agent_num}: What is your analysis of this data?"
            return await self.send_completion_request(
                prompt=prompt,
                workflow_metadata={
                    "workflow_id": workflow_id,
                    "agent_id": agent_id
                }
            )
        
        start_time = time.time()
        tasks = [
            agent_task(f"agent-{i+1}", i+1)
            for i in range(num_agents)
        ]
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        total_time = time.time() - start_time
        
        # Process results
        successful_results = []
        for i, result in enumerate(results):
            if isinstance(result, dict) and result["status"] == "success":
                successful_results.append(result)
                print(f"  Agent {i+1}: {result['latency']:.2f}s")
            else:
                print(f"  Agent {i+1}: ERROR")
        
        avg_latency = statistics.mean(r["latency"] for r in successful_results) if successful_results else 0
        speedup = (avg_latency * num_agents) / total_time if total_time > 0 else 0
        
        return {
            "type": "parallel",
            "workflow_id": workflow_id,
            "num_agents": num_agents,
            "total_time": total_time,
            "avg_latency": avg_latency,
            "speedup": speedup,
            "success_rate": len(successful_results) / len(results) if results else 0.0,
            "results": results
        }
    
    async def benchmark_cache_efficiency(
        self,
        context_size: int = 1000,
        num_iterations: int = 10
    ) -> Dict[str, Any]:
        """Benchmark KV-cache reuse efficiency.
        
        Args:
            context_size: Size of shared context (in tokens approximately)
            num_iterations: Number of iterations to test
            
        Returns:
            Cache efficiency benchmark results
        """
        print(f"Running cache efficiency benchmark ({num_iterations} iterations)...")
        
        # Generate shared context
        shared_context = " ".join(["data"] * context_size)
        
        workflow_id = f"cache-test-{uuid.uuid4().hex[:8]}"
        
        latencies_with_workflow = []
        latencies_without_workflow = []
        
        for i in range(num_iterations):
            # Request with workflow (should benefit from cache)
            prompt = f"{shared_context}\n\nIteration {i+1}: Analyze this data pattern."
            
            result_with_workflow = await self.send_completion_request(
                prompt=prompt,
                workflow_metadata={
                    "workflow_id": workflow_id,
                    "agent_id": f"agent-cache-{i}"
                }
            )
            
            if result_with_workflow["status"] == "success":
                latencies_with_workflow.append(result_with_workflow["latency"])
            
            # Request without workflow (no cache benefit)
            result_without_workflow = await self.send_completion_request(
                prompt=prompt
                # No workflow metadata
            )
            
            if result_without_workflow["status"] == "success":
                latencies_without_workflow.append(result_without_workflow["latency"])
            
            print(f"  Iteration {i+1}: workflow={result_with_workflow['latency']:.2f}s, "
                  f"no-workflow={result_without_workflow['latency']:.2f}s")
        
        avg_with_workflow = statistics.mean(latencies_with_workflow) if latencies_with_workflow else 0
        avg_without_workflow = statistics.mean(latencies_without_workflow) if latencies_without_workflow else 0
        
        cache_speedup = avg_without_workflow / avg_with_workflow if avg_with_workflow > 0 else 0
        saved_ms = (avg_without_workflow - avg_with_workflow) * 1000
        
        return {
            "type": "cache_efficiency",
            "workflow_id": workflow_id,
            "context_size": context_size,
            "iterations": num_iterations,
            "avg_latency_with_workflow": avg_with_workflow,
            "avg_latency_without_workflow": avg_without_workflow,
            "cache_speedup": cache_speedup,
            "saved_ms": saved_ms,
            "with_workflow_results": latencies_with_workflow,
            "without_workflow_results": latencies_without_workflow
        }
    
    async def benchmark_a2a_communication(
        self,
        num_messages: int = 50,
        message_size: int = 1024
    ) -> Dict[str, Any]:
        """Benchmark agent-to-agent communication.
        
        Args:
            num_messages: Number of messages to send
            message_size: Size of each message payload
            
        Returns:
            A2A communication benchmark results
        """
        print(f"Running A2A communication benchmark ({num_messages} messages)...")
        
        workflow_id = f"a2a-test-{uuid.uuid4().hex[:8]}"
        
        # Generate test payload
        payload = {"data": "x" * message_size}
        
        send_latencies = []
        receive_latencies = []
        
        for i in range(num_messages):
            try:
                # Send message
                start_send = time.time()
                
                async with self.session.post(
                    f"{self.base_url}/v1/workflows/{workflow_id}/messages",
                    json={
                        "source_agent": "sender",
                        "target_agent": "receiver",
                        "payload": payload,
                        "message_type": "data"
                    }
                ) as response:
                    await response.json()
                    send_latency = time.time() - start_send
                    send_latencies.append(send_latency)
                
                # Receive message
                start_receive = time.time()
                
                async with self.session.get(
                    f"{self.base_url}/v1/workflows/{workflow_id}/agents/receiver/messages",
                    params={"timeout": 1.0}
                ) as response:
                    result = await response.json()
                    receive_latency = time.time() - start_receive
                    receive_latencies.append(receive_latency)
                    
                    messages_received = len(result.get("messages", []))
                    if i % 10 == 0:
                        print(f"  Message {i+1}: send={send_latency*1000:.1f}ms, "
                              f"receive={receive_latency*1000:.1f}ms, received={messages_received}")
            
            except Exception as e:
                print(f"  Message {i+1}: ERROR - {e}")
                # Add zero latencies for failed messages to maintain count
                send_latencies.append(0)
                receive_latencies.append(0)
        
        return {
            "type": "a2a_communication",
            "workflow_id": workflow_id,
            "num_messages": num_messages,
            "message_size": message_size,
            "avg_send_latency_ms": statistics.mean(send_latencies) * 1000 if send_latencies else 0,
            "avg_receive_latency_ms": statistics.mean(receive_latencies) * 1000 if receive_latencies else 0,
            "p95_send_latency_ms": statistics.quantiles(send_latencies, n=20)[18] * 1000 if len(send_latencies) >= 20 else (max(send_latencies) * 1000 if send_latencies else 0),
            "p95_receive_latency_ms": statistics.quantiles(receive_latencies, n=20)[18] * 1000 if len(receive_latencies) >= 20 else (max(receive_latencies) * 1000 if receive_latencies else 0),
            "throughput_msgs_per_sec": num_messages / sum(send_latencies) if send_latencies and sum(send_latencies) > 0 else 0
        }
    
    async def get_workflow_stats(self) -> Dict[str, Any]:
        """Get workflow system statistics."""
        try:
            async with self.session.get(f"{self.base_url}/v1/workflows/stats") as response:
                return await response.json()
        except Exception as e:
            return {"error": str(e)}


async def main():
    """Run benchmark suite."""
    parser = argparse.ArgumentParser(description="Workflow benchmark suite")
    parser.add_argument("--url", default="http://localhost:8000", help="Router URL")
    parser.add_argument("--agents", type=int, default=5, help="Number of agents")
    parser.add_argument("--iterations", type=int, default=10, help="Number of iterations")
    parser.add_argument("--context-size", type=int, default=1000, help="Context size for cache test")
    parser.add_argument("--output", default="benchmark_results.json", help="Output file")
    parser.add_argument("--benchmarks", nargs="+", 
                       choices=["sequential", "parallel", "cache", "a2a", "all"],
                       default=["all"], help="Benchmarks to run")
    
    args = parser.parse_args()
    
    if "all" in args.benchmarks:
        benchmarks_to_run = ["sequential", "parallel", "cache", "a2a"]
    else:
        benchmarks_to_run = args.benchmarks
    
    print(f"Starting workflow benchmarks against {args.url}")
    print(f"Running benchmarks: {', '.join(benchmarks_to_run)}")
    print("-" * 60)
    
    async with WorkflowBenchmark(args.url) as benchmark:
        results = {
            "timestamp": time.time(),
            "config": {
                "url": args.url,
                "agents": args.agents,
                "iterations": args.iterations,
                "context_size": args.context_size
            },
            "benchmarks": {}
        }
        
        # Run benchmarks
        if "sequential" in benchmarks_to_run:
            print("\\n=== Sequential Agent Benchmark ===")
            results["benchmarks"]["sequential"] = await benchmark.benchmark_sequential_agents(
                num_agents=args.agents
            )
        
        if "parallel" in benchmarks_to_run:
            print("\\n=== Parallel Agent Benchmark ===")
            results["benchmarks"]["parallel"] = await benchmark.benchmark_parallel_agents(
                num_agents=args.agents
            )
        
        if "cache" in benchmarks_to_run:
            print("\\n=== Cache Efficiency Benchmark ===")
            results["benchmarks"]["cache"] = await benchmark.benchmark_cache_efficiency(
                context_size=args.context_size,
                num_iterations=args.iterations
            )
        
        if "a2a" in benchmarks_to_run:
            print("\\n=== A2A Communication Benchmark ===")
            results["benchmarks"]["a2a"] = await benchmark.benchmark_a2a_communication(
                num_messages=args.iterations
            )
        
        # Get system stats
        print("\\n=== System Statistics ===")
        results["system_stats"] = await benchmark.get_workflow_stats()
        
        # Print summary
        print("\\n=== BENCHMARK SUMMARY ===")
        
        if "sequential" in results["benchmarks"]:
            seq = results["benchmarks"]["sequential"]
            print(f"Sequential ({seq['num_agents']} agents):")
            print(f"  Total time: {seq['total_latency']:.2f}s")
            print(f"  Average latency: {seq['avg_latency']:.2f}s")
            print(f"  Success rate: {seq['success_rate']:.1%}")
        
        if "parallel" in results["benchmarks"]:
            par = results["benchmarks"]["parallel"]
            print(f"Parallel ({par['num_agents']} agents):")
            print(f"  Total time: {par['total_time']:.2f}s")
            print(f"  Average latency: {par['avg_latency']:.2f}s")
            print(f"  Speedup: {par['speedup']:.2f}x")
            print(f"  Success rate: {par['success_rate']:.1%}")
        
        if "cache" in results["benchmarks"]:
            cache = results["benchmarks"]["cache"]
            print(f"Cache efficiency ({cache['iterations']} iterations):")
            print(f"  With workflow: {cache['avg_latency_with_workflow']:.2f}s")
            print(f"  Without workflow: {cache['avg_latency_without_workflow']:.2f}s")
            print(f"  Cache speedup: {cache['cache_speedup']:.2f}x")
            print(f"  Time saved: {cache['saved_ms']:.0f}ms per request")
        
        if "a2a" in results["benchmarks"]:
            a2a = results["benchmarks"]["a2a"]
            print(f"A2A communication ({a2a['num_messages']} messages):")
            print(f"  Send latency: {a2a['avg_send_latency_ms']:.1f}ms (avg)")
            print(f"  Receive latency: {a2a['avg_receive_latency_ms']:.1f}ms (avg)")
            print(f"  Throughput: {a2a['throughput_msgs_per_sec']:.1f} msgs/sec")
        
        # Save results
        with open(args.output, 'w') as f:
            json.dump(results, f, indent=2)
        
        print(f"\\nResults saved to {args.output}")


if __name__ == "__main__":
    asyncio.run(main())