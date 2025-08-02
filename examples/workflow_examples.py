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

"""Example workflows demonstrating workflow-aware routing capabilities."""

import asyncio
import json
import time
import uuid
from typing import List, Dict, Any

import httpx


class WorkflowClient:
    """Client for interacting with workflow-aware vLLM router."""
    
    def __init__(self, router_url: str = "http://localhost:8001"):
        """Initialize workflow client.
        
        Args:
            router_url: URL of the vLLM router
        """
        self.router_url = router_url
        
    async def send_completion(
        self,
        prompt: str,
        workflow_id: str,
        agent_id: str,
        model: str = "meta-llama/Llama-3.1-8B-Instruct",
        max_tokens: int = 150,
        **kwargs
    ) -> Dict[str, Any]:
        """Send a completion request with workflow metadata."""
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                f"{self.router_url}/v1/completions",
                json={
                    "model": model,
                    "prompt": prompt,
                    "max_tokens": max_tokens,
                    "temperature": 0.7,
                    "workflow_metadata": {
                        "workflow_id": workflow_id,
                        "agent_id": agent_id,
                        "context_sharing_strategy": "auto"
                    },
                    **kwargs
                }
            )
            return response.json()
    
    async def send_agent_message(
        self,
        workflow_id: str,
        source_agent: str,
        target_agent: str,
        payload: Dict[str, Any],
        message_type: str = "data",
        ttl: int = 300
    ) -> Dict[str, Any]:
        """Send message between agents."""
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.router_url}/v1/workflows/{workflow_id}/messages",
                json={
                    "source_agent": source_agent,
                    "target_agent": target_agent,
                    "message_type": message_type,
                    "payload": payload,
                    "ttl": ttl
                }
            )
            return response.json()
    
    async def receive_agent_messages(
        self,
        workflow_id: str,
        agent_id: str,
        timeout: float = 5.0,
        max_messages: int = 10
    ) -> Dict[str, Any]:
        """Receive messages for an agent."""
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.router_url}/v1/workflows/{workflow_id}/agents/{agent_id}/messages",
                params={
                    "timeout": timeout,
                    "max_messages": max_messages
                }
            )
            return response.json()
    
    async def get_workflow_status(self, workflow_id: str) -> Dict[str, Any]:
        """Get workflow status and statistics."""
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.router_url}/v1/workflows/{workflow_id}/status"
            )
            return response.json()


async def financial_analysis_workflow():
    """Example: Financial analysis workflow with multiple agents."""
    print("=== Financial Analysis Workflow ===")
    
    client = WorkflowClient()
    workflow_id = f"financial-analysis-{uuid.uuid4().hex[:8]}"
    
    # Sample financial data
    financial_data = """
    Q4 2024 Financial Results:
    - Revenue: $2.5M (15% growth YoY)
    - Expenses: $1.8M (8% increase YoY) 
    - Net Profit: $700K (35% growth YoY)
    - Customer Acquisition: 1,200 new customers
    - Churn Rate: 5.2% (down from 6.1%)
    """
    
    # Agent 1: Data Analyst
    print("1. Data Analyst: Processing raw financial data...")
    analysis_result = await client.send_completion(
        prompt=f"As a financial data analyst, analyze this financial data and identify key metrics and trends:\n{financial_data}\n\nProvide a structured analysis:",
        workflow_id=workflow_id,
        agent_id="data-analyst"
    )
    print(f"   Result: {analysis_result['choices'][0]['text'][:100]}...")
    
    # Agent 2: Risk Assessor (benefits from shared context)
    print("2. Risk Assessor: Evaluating financial risks...")
    risk_result = await client.send_completion(
        prompt="Based on the financial data analysis, assess potential risks and provide risk mitigation recommendations:",
        workflow_id=workflow_id,
        agent_id="risk-assessor"
    )
    print(f"   Result: {risk_result['choices'][0]['text'][:100]}...")
    
    # Agent 3: Strategic Advisor (benefits from shared context)
    print("3. Strategic Advisor: Generating strategic recommendations...")
    strategy_result = await client.send_completion(
        prompt="Based on the financial analysis and risk assessment, provide strategic recommendations for the next quarter:",
        workflow_id=workflow_id,
        agent_id="strategic-advisor"
    )
    print(f"   Result: {strategy_result['choices'][0]['text'][:100]}...")
    
    # Get workflow statistics
    stats = await client.get_workflow_status(workflow_id)
    print(f"\nWorkflow Statistics:")
    print(f"  - Total requests: {stats.get('total_requests', 0)}")
    print(f"  - Cache hit rate: {stats.get('cache_hit_rate', 0):.1%}")
    print(f"  - Active agents: {stats.get('active_agents', 0)}")
    
    return workflow_id


async def collaborative_research_workflow():
    """Example: Collaborative research workflow with A2A communication."""
    print("\n=== Collaborative Research Workflow ===")
    
    client = WorkflowClient()
    workflow_id = f"research-collab-{uuid.uuid4().hex[:8]}"
    
    # Agent 1: Literature Researcher
    print("1. Literature Researcher: Gathering background information...")
    research_result = await client.send_completion(
        prompt="Research and summarize the current state of large language model optimization techniques, focusing on inference acceleration:",
        workflow_id=workflow_id,
        agent_id="literature-researcher"
    )
    
    # Extract key findings for sharing
    research_findings = {
        "techniques": ["KV-cache optimization", "Dynamic batching", "Quantization"],
        "performance_gains": "2-5x speedup typical",
        "challenges": ["Memory constraints", "Hardware compatibility"]
    }
    
    # Send findings to other agents
    await client.send_agent_message(
        workflow_id=workflow_id,
        source_agent="literature-researcher",
        target_agent="technical-analyst",
        payload={"research_findings": research_findings}
    )
    print("   Shared findings with Technical Analyst")
    
    # Agent 2: Technical Analyst
    print("2. Technical Analyst: Receiving research data and analyzing...")
    
    # Receive messages from researcher
    messages = await client.receive_agent_messages(
        workflow_id=workflow_id,
        agent_id="technical-analyst",
        timeout=2.0
    )
    
    received_data = messages.get("messages", [])
    print(f"   Received {len(received_data)} messages from other agents")
    
    # Analyze based on received data and context
    analysis_result = await client.send_completion(
        prompt="Based on the literature research findings, perform a technical feasibility analysis for implementing these optimization techniques:",
        workflow_id=workflow_id,
        agent_id="technical-analyst"
    )
    
    # Share technical analysis
    technical_insights = {
        "feasibility_score": 0.85,
        "implementation_complexity": "Medium-High",
        "recommended_approach": "Gradual rollout with A/B testing"
    }
    
    await client.send_agent_message(
        workflow_id=workflow_id,
        source_agent="technical-analyst", 
        target_agent="project-manager",
        payload={"technical_analysis": technical_insights}
    )
    print("   Shared technical analysis with Project Manager")
    
    # Agent 3: Project Manager
    print("3. Project Manager: Creating implementation plan...")
    
    # Receive technical analysis
    pm_messages = await client.receive_agent_messages(
        workflow_id=workflow_id,
        agent_id="project-manager",
        timeout=2.0
    )
    
    # Create project plan
    plan_result = await client.send_completion(
        prompt="Based on the research findings and technical analysis, create a detailed project implementation plan with timeline and resources:",
        workflow_id=workflow_id,
        agent_id="project-manager"
    )
    print(f"   Result: {plan_result['choices'][0]['text'][:100]}...")
    
    # Get final workflow statistics
    stats = await client.get_workflow_status(workflow_id)
    print(f"\nCollaborative Workflow Statistics:")
    print(f"  - Total requests: {stats.get('total_requests', 0)}")
    print(f"  - Cache hit rate: {stats.get('cache_hit_rate', 0):.1%}")
    print(f"  - Active agents: {stats.get('active_agents', 0)}")
    
    return workflow_id


async def customer_support_workflow():
    """Example: Customer support workflow with escalation."""
    print("\n=== Customer Support Workflow ===")
    
    client = WorkflowClient()
    workflow_id = f"support-{uuid.uuid4().hex[:8]}"
    
    # Customer inquiry
    customer_query = """
    Customer Issue: I'm having trouble with my account login. 
    I keep getting an error message saying 'Invalid credentials' 
    even though I'm sure my password is correct. I've tried 
    resetting it twice but the problem persists. This is very 
    frustrating as I need to access my account urgently for 
    a business presentation tomorrow.
    """
    
    # Agent 1: First-line Support
    print("1. First-line Support: Initial triage...")
    triage_result = await client.send_completion(
        prompt=f"As a first-line customer support agent, analyze this customer issue and provide initial troubleshooting steps:\n{customer_query}\n\nResponse:",
        workflow_id=workflow_id,
        agent_id="first-line-support"
    )
    
    # Determine if escalation is needed
    escalation_needed = "password reset" in customer_query.lower() and "urgent" in customer_query.lower()
    
    if escalation_needed:
        print("2. Escalating to Technical Specialist...")
        
        # Share context with technical specialist
        await client.send_agent_message(
            workflow_id=workflow_id,
            source_agent="first-line-support",
            target_agent="technical-specialist",
            payload={
                "escalation_reason": "Complex login issue with failed password resets",
                "customer_priority": "high",
                "initial_analysis": triage_result['choices'][0]['text'][:200]
            }
        )
        
        # Agent 2: Technical Specialist
        specialist_result = await client.send_completion(
            prompt="As a technical specialist, provide advanced troubleshooting for this complex login issue. Consider account security, database issues, and provide a comprehensive solution:",
            workflow_id=workflow_id,
            agent_id="technical-specialist"
        )
        
        # Agent 3: Customer Success Manager (for high-priority issues)
        print("3. Customer Success Manager: Follow-up planning...")
        followup_result = await client.send_completion(
            prompt="As a customer success manager, create a follow-up plan to ensure customer satisfaction and prevent future issues:",
            workflow_id=workflow_id,
            agent_id="customer-success"
        )
        print(f"   Follow-up plan: {followup_result['choices'][0]['text'][:100]}...")
    
    # Get workflow statistics
    stats = await client.get_workflow_status(workflow_id)
    print(f"\nSupport Workflow Statistics:")
    print(f"  - Total requests: {stats.get('total_requests', 0)}")
    print(f"  - Cache hit rate: {stats.get('cache_hit_rate', 0):.1%}")
    print(f"  - Active agents: {stats.get('active_agents', 0)}")
    
    return workflow_id


async def parallel_analysis_workflow():
    """Example: Parallel analysis workflow for performance comparison."""
    print("\n=== Parallel Analysis Workflow ===")
    
    client = WorkflowClient()
    workflow_id = f"parallel-analysis-{uuid.uuid4().hex[:8]}"
    
    # Dataset for analysis
    dataset_description = """
    E-commerce Performance Dataset:
    - 100K transactions over 3 months
    - 5K unique customers
    - 20 product categories
    - Metrics: conversion rate, avg order value, customer lifetime value
    """
    
    # Launch parallel analyses
    print("Launching parallel agents for different analysis perspectives...")
    
    tasks = [
        # Agent 1: Statistical Analysis
        client.send_completion(
            prompt=f"Perform statistical analysis on this e-commerce dataset. Focus on trends, correlations, and statistical significance:\n{dataset_description}",
            workflow_id=workflow_id,
            agent_id="statistical-analyst"
        ),
        
        # Agent 2: Customer Behavior Analysis  
        client.send_completion(
            prompt=f"Analyze customer behavior patterns in this e-commerce dataset. Focus on segmentation and purchasing patterns:\n{dataset_description}",
            workflow_id=workflow_id,
            agent_id="behavior-analyst"
        ),
        
        # Agent 3: Revenue Optimization Analysis
        client.send_completion(
            prompt=f"Analyze revenue optimization opportunities in this e-commerce dataset. Focus on pricing and upselling:\n{dataset_description}",
            workflow_id=workflow_id,
            agent_id="revenue-analyst"
        ),
        
        # Agent 4: Market Trends Analysis
        client.send_completion(
            prompt=f"Analyze market trends and competitive insights from this e-commerce dataset:\n{dataset_description}",
            workflow_id=workflow_id,
            agent_id="market-analyst"
        )
    ]
    
    # Execute all analyses in parallel
    start_time = time.time()
    results = await asyncio.gather(*tasks)
    execution_time = time.time() - start_time
    
    print(f"Parallel execution completed in {execution_time:.2f} seconds")
    print(f"Generated {len(results)} analysis reports")
    
    # Agent 5: Synthesis Agent (benefits from all previous context)
    print("5. Synthesis Agent: Combining all analyses...")
    synthesis_result = await client.send_completion(
        prompt="Based on all the previous analyses (statistical, behavioral, revenue, and market), provide a comprehensive synthesis and actionable recommendations:",
        workflow_id=workflow_id,
        agent_id="synthesis-agent"
    )
    print(f"   Synthesis: {synthesis_result['choices'][0]['text'][:150]}...")
    
    # Get final statistics
    stats = await client.get_workflow_status(workflow_id)
    print(f"\nParallel Workflow Statistics:")
    print(f"  - Total requests: {stats.get('total_requests', 0)}")
    print(f"  - Cache hit rate: {stats.get('cache_hit_rate', 0):.1%}")
    print(f"  - Active agents: {stats.get('active_agents', 0)}")
    print(f"  - Execution time: {execution_time:.2f}s")
    
    return workflow_id


async def main():
    """Run all workflow examples."""
    print("Workflow-Aware Routing Examples")
    print("=" * 50)
    
    try:
        # Run examples sequentially
        workflow_ids = []
        
        workflow_ids.append(await financial_analysis_workflow())
        await asyncio.sleep(1)
        
        workflow_ids.append(await collaborative_research_workflow()) 
        await asyncio.sleep(1)
        
        workflow_ids.append(await customer_support_workflow())
        await asyncio.sleep(1)
        
        workflow_ids.append(await parallel_analysis_workflow())
        
        print(f"\n=== Summary ===")
        print(f"Completed {len(workflow_ids)} workflow examples:")
        for i, wf_id in enumerate(workflow_ids, 1):
            print(f"  {i}. {wf_id}")
        
        print("\nThese examples demonstrate:")
        print("- Context sharing between agents in the same workflow")
        print("- KV-cache reuse for improved performance")
        print("- Agent-to-agent message passing")
        print("- Parallel agent execution with shared context")
        print("- Workflow monitoring and statistics")
        
    except Exception as e:
        print(f"Error running examples: {e}")
        print("Make sure the vLLM router is running with workflow-aware routing enabled:")
        print("python -m vllm_router.app --routing-logic workflow_aware ...")


if __name__ == "__main__":
    asyncio.run(main())