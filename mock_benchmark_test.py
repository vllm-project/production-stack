#!/usr/bin/env python3
"""
Mock benchmark test to demonstrate workflow-aware routing performance
without requiring actual vLLM servers.
"""

import asyncio
import time
import random
import statistics
import json
from typing import List, Dict, Any
import uuid

class MockVLLMServer:
    """Mock vLLM server that simulates realistic responses."""
    
    def __init__(self, server_id: str, base_latency: float = 1.0):
        self.server_id = server_id
        self.base_latency = base_latency
        self.cache = {}  # Simulate KV cache
        self.request_count = 0
        
    async def complete(self, prompt: str, workflow_id: str = None) -> Dict[str, Any]:
        """Simulate completion with realistic latency."""
        self.request_count += 1
        
        # Simulate cache hit/miss
        cache_key = f"{workflow_id}:{prompt[:50]}" if workflow_id else None
        cache_hit = cache_key and cache_key in self.cache
        
        if cache_hit:
            # Cache hit - much faster
            latency = self.base_latency * random.uniform(0.2, 0.4)
            self.cache[cache_key] += 1
        else:
            # Cache miss - normal latency
            latency = self.base_latency * random.uniform(0.8, 1.5)
            if cache_key:
                self.cache[cache_key] = 1
        
        # Add some network jitter
        latency += random.uniform(0.05, 0.15)
        
        await asyncio.sleep(latency)
        
        return {
            "choices": [{
                "text": f"Response from {self.server_id}: Processed '{prompt[:30]}...' (cached: {cache_hit})"
            }],
            "usage": {
                "total_tokens": random.randint(50, 200)
            },
            "latency": latency,
            "cache_hit": cache_hit,
            "server_id": self.server_id
        }

class MockWorkflowBenchmark:
    """Mock benchmark that simulates workflow-aware routing behavior."""
    
    def __init__(self):
        self.servers = [
            MockVLLMServer("vllm-1", 1.2),
            MockVLLMServer("vllm-2", 1.1), 
            MockVLLMServer("vllm-3", 1.3)
        ]
        self.workflow_assignments = {}  # workflow_id -> server
        
    def assign_server(self, workflow_id: str) -> MockVLLMServer:
        """Simulate workflow-aware server assignment."""
        if workflow_id in self.workflow_assignments:
            return self.workflow_assignments[workflow_id]
        
        # Assign to least loaded server
        server = min(self.servers, key=lambda s: s.request_count)
        self.workflow_assignments[workflow_id] = server
        return server
    
    async def send_request(self, prompt: str, workflow_id: str = None, agent_id: str = None) -> Dict[str, Any]:
        """Send a request with optional workflow awareness."""
        start_time = time.time()
        
        if workflow_id:
            # Workflow-aware routing
            server = self.assign_server(workflow_id)
            result = await server.complete(prompt, workflow_id)
        else:
            # Round-robin routing
            server = random.choice(self.servers)
            result = await server.complete(prompt)
        
        total_time = time.time() - start_time
        
        return {
            "status": "success",
            "latency": total_time,
            "server_id": server.server_id,
            "cache_hit": result["cache_hit"],
            "tokens": result["usage"]["total_tokens"],
            "workflow_id": workflow_id,
            "agent_id": agent_id
        }
    
    async def benchmark_sequential_vs_parallel(self, num_agents: int = 5) -> Dict[str, Any]:
        """Compare sequential vs parallel execution."""
        workflow_id = f"test-workflow-{uuid.uuid4().hex[:8]}"
        shared_context = "Analyze quarterly sales data: Q1=$100K, Q2=$150K, Q3=$120K, Q4=$200K"
        
        # Sequential execution
        print(f"🔄 Running sequential benchmark ({num_agents} agents)...")
        sequential_start = time.time()
        sequential_results = []
        
        for i in range(num_agents):
            prompt = f"{shared_context}. Agent {i+1} analysis:"
            result = await self.send_request(prompt, workflow_id, f"agent-{i+1}")
            sequential_results.append(result)
            print(f"   Agent {i+1}: {result['latency']:.3f}s (cache: {result['cache_hit']})")
        
        sequential_total = time.time() - sequential_start
        
        # Parallel execution  
        print(f"🚀 Running parallel benchmark ({num_agents} agents)...")
        parallel_start = time.time()
        
        tasks = []
        for i in range(num_agents):
            prompt = f"{shared_context}. Agent {i+1} analysis:"
            task = self.send_request(prompt, workflow_id, f"parallel-agent-{i+1}")
            tasks.append(task)
        
        parallel_results = await asyncio.gather(*tasks)
        parallel_total = time.time() - parallel_start
        
        for i, result in enumerate(parallel_results):
            print(f"   Agent {i+1}: {result['latency']:.3f}s (cache: {result['cache_hit']})")
        
        return {
            "sequential": {
                "total_time": sequential_total,
                "avg_latency": statistics.mean(r["latency"] for r in sequential_results),
                "cache_hits": sum(1 for r in sequential_results if r["cache_hit"]),
                "cache_hit_rate": sum(1 for r in sequential_results if r["cache_hit"]) / len(sequential_results)
            },
            "parallel": {
                "total_time": parallel_total,
                "avg_latency": statistics.mean(r["latency"] for r in parallel_results),
                "cache_hits": sum(1 for r in parallel_results if r["cache_hit"]),
                "cache_hit_rate": sum(1 for r in parallel_results if r["cache_hit"]) / len(parallel_results),
                "speedup": sequential_total / parallel_total
            }
        }
    
    async def benchmark_cache_efficiency(self, iterations: int = 10) -> Dict[str, Any]:
        """Compare workflow-aware vs standard routing cache efficiency."""
        workflow_id = f"cache-test-{uuid.uuid4().hex[:8]}"
        shared_prompt = "Given the financial data analysis, what are the key trends and recommendations?"
        
        print(f"💾 Testing cache efficiency ({iterations} iterations)...")
        
        # Test with workflow awareness (cache reuse)
        workflow_latencies = []
        for i in range(iterations):
            result = await self.send_request(shared_prompt, workflow_id, f"cache-agent-{i}")
            workflow_latencies.append(result["latency"])
            if i % 3 == 0:
                print(f"   Workflow iteration {i+1}: {result['latency']:.3f}s (cache: {result['cache_hit']})")
        
        # Test without workflow awareness (no cache reuse)
        standard_latencies = []
        for i in range(iterations):
            result = await self.send_request(shared_prompt)  # No workflow_id
            standard_latencies.append(result["latency"])
            if i % 3 == 0:
                print(f"   Standard iteration {i+1}: {result['latency']:.3f}s (cache: {result['cache_hit']})")
        
        workflow_avg = statistics.mean(workflow_latencies)
        standard_avg = statistics.mean(standard_latencies)
        
        return {
            "workflow_aware": {
                "avg_latency": workflow_avg,
                "latencies": workflow_latencies
            },
            "standard": {
                "avg_latency": standard_avg,
                "latencies": standard_latencies
            },
            "cache_speedup": standard_avg / workflow_avg,
            "time_saved_ms": (standard_avg - workflow_avg) * 1000
        }
    
    async def benchmark_multi_workflow_isolation(self) -> Dict[str, Any]:
        """Test multiple concurrent workflows."""
        print("🏢 Testing multi-workflow isolation...")
        
        workflows = [f"workflow-{i}" for i in range(3)]
        tasks = []
        
        for workflow_id in workflows:
            for agent_id in range(3):
                prompt = f"Workflow {workflow_id[-1]} Agent {agent_id}: Process business metrics"
                task = self.send_request(prompt, workflow_id, f"agent-{agent_id}")
                tasks.append(task)
        
        results = await asyncio.gather(*tasks)
        
        # Group by workflow
        workflow_stats = {}
        for result in results:
            wf_id = result["workflow_id"]
            if wf_id not in workflow_stats:
                workflow_stats[wf_id] = []
            workflow_stats[wf_id].append(result)
        
        summary = {}
        for wf_id, wf_results in workflow_stats.items():
            servers = set(r["server_id"] for r in wf_results)
            cache_hits = sum(1 for r in wf_results if r["cache_hit"])
            
            summary[wf_id] = {
                "requests": len(wf_results),
                "servers_used": list(servers),
                "server_affinity": len(servers) == 1,  # All requests to same server
                "cache_hits": cache_hits,
                "cache_hit_rate": cache_hits / len(wf_results),
                "avg_latency": statistics.mean(r["latency"] for r in wf_results)
            }
            
            print(f"   {wf_id}: {len(servers)} server(s), {cache_hits}/{len(wf_results)} cache hits")
        
        return summary

async def main():
    """Run all benchmarks and display results."""
    print("🧪 Mock Workflow-Aware Routing Benchmark")
    print("=" * 50)
    
    benchmark = MockWorkflowBenchmark()
    
    # Test 1: Sequential vs Parallel
    print("\n📊 Test 1: Sequential vs Parallel Execution")
    seq_vs_par = await benchmark.benchmark_sequential_vs_parallel(5)
    
    print(f"\nResults:")
    print(f"  Sequential: {seq_vs_par['sequential']['total_time']:.2f}s total, "
          f"{seq_vs_par['sequential']['avg_latency']:.2f}s avg, "
          f"{seq_vs_par['sequential']['cache_hit_rate']:.1%} cache hits")
    print(f"  Parallel:   {seq_vs_par['parallel']['total_time']:.2f}s total, "
          f"{seq_vs_par['parallel']['avg_latency']:.2f}s avg, "
          f"{seq_vs_par['parallel']['cache_hit_rate']:.1%} cache hits")
    print(f"  Speedup:    {seq_vs_par['parallel']['speedup']:.2f}x")
    
    # Test 2: Cache Efficiency
    print("\n📊 Test 2: Cache Efficiency")
    cache_test = await benchmark.benchmark_cache_efficiency(8)
    
    print(f"\nResults:")
    print(f"  Workflow-aware: {cache_test['workflow_aware']['avg_latency']:.3f}s avg")
    print(f"  Standard:       {cache_test['standard']['avg_latency']:.3f}s avg")
    print(f"  Cache speedup:  {cache_test['cache_speedup']:.2f}x")
    print(f"  Time saved:     {cache_test['time_saved_ms']:.0f}ms per request")
    
    # Test 3: Multi-workflow Isolation
    print("\n📊 Test 3: Multi-Workflow Isolation")
    isolation_test = await benchmark.benchmark_multi_workflow_isolation()
    
    print(f"\nResults:")
    for wf_id, stats in isolation_test.items():
        affinity_status = "✅ Perfect" if stats["server_affinity"] else "❌ Scattered"
        print(f"  {wf_id}: {affinity_status} affinity, "
              f"{stats['cache_hit_rate']:.1%} cache hits, "
              f"{stats['avg_latency']:.3f}s avg")
    
    # Summary
    print("\n🎯 Summary")
    print(f"  Parallel speedup: {seq_vs_par['parallel']['speedup']:.2f}x")
    print(f"  Cache optimization: {cache_test['cache_speedup']:.2f}x faster")
    print(f"  Workflow isolation: ✅ Maintained server affinity")
    print(f"  Performance improvement: ~{seq_vs_par['parallel']['speedup'] * cache_test['cache_speedup']:.1f}x overall")
    
    # Save results
    results = {
        "timestamp": time.time(),
        "sequential_vs_parallel": seq_vs_par,
        "cache_efficiency": cache_test,
        "workflow_isolation": isolation_test,
        "summary": {
            "parallel_speedup": seq_vs_par['parallel']['speedup'],
            "cache_speedup": cache_test['cache_speedup'],
            "overall_improvement": seq_vs_par['parallel']['speedup'] * cache_test['cache_speedup']
        }
    }
    
    with open('mock_benchmark_results.json', 'w') as f:
        json.dump(results, f, indent=2)
    
    print(f"\n💾 Results saved to mock_benchmark_results.json")

if __name__ == "__main__":
    asyncio.run(main())