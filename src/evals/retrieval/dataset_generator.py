"""
Synthetic dataset generator for retrieval evaluation.

Generates term-based queries from OBP endpoint documentation and creates
ground truth labels based on tag relationships.
"""

import os
import sys
import json
import asyncio
import httpx
import random
from dataclasses import dataclass, field, asdict
from typing import Optional
from dotenv import load_dotenv

# Add src to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

load_dotenv()

from agent.utils.model_factory import get_model


@dataclass
class MinimalEndpoint:
    """Minimal representation of an endpoint for query generation."""
    operation_id: str
    request_verb: str
    request_url: str
    summary: str
    tags: list[str]
    
    def to_prompt_str(self) -> str:
        """Format for LLM prompt."""
        return (
            f"- {self.request_verb} {self.request_url}\n"
            f"  operation_id: {self.operation_id}\n"
            f"  summary: {self.summary}\n"
            f"  tags: {', '.join(self.tags)}"
        )


@dataclass 
class EvalQuery:
    """A single evaluation query with ground truth."""
    query_terms: str  # e.g. "authentication, oauth, directlogin"
    source_endpoint_id: str  # The endpoint this query was generated from
    definitely_relevant: list[str]  # endpoint IDs that must be retrieved
    possibly_relevant: list[str] = field(default_factory=list)  # same-tag endpoints


@dataclass
class EvalDataset:
    """Complete evaluation dataset."""
    queries: list[EvalQuery]
    endpoints: list[MinimalEndpoint]
    metadata: dict = field(default_factory=dict)
    
    def save(self, path: str):
        """Save dataset to JSON."""
        data = {
            "metadata": self.metadata,
            "endpoints": [asdict(e) for e in self.endpoints],
            "queries": [asdict(q) for q in self.queries]
        }
        with open(path, 'w') as f:
            json.dump(data, f, indent=2)
        print(f"Saved {len(self.queries)} queries to {path}")
    
    @classmethod
    def load(cls, path: str) -> "EvalDataset":
        """Load dataset from JSON."""
        with open(path) as f:
            data = json.load(f)
        return cls(
            metadata=data.get("metadata", {}),
            endpoints=[MinimalEndpoint(**e) for e in data["endpoints"]],
            queries=[EvalQuery(**q) for q in data["queries"]]
        )


class EndpointFetcher:
    """Fetches and processes OBP endpoint documentation."""
    
    def __init__(self, base_url: Optional[str] = None, api_version: Optional[str] = None):
        self.base_url = base_url or os.getenv("OBP_BASE_URL", "http://127.0.0.1:8080")
        self.api_version = api_version or os.getenv("OBP_API_VERSION", "v6.0.0")
    
    @property
    def resource_docs_url(self) -> str:
        return f"{self.base_url}/obp/{self.api_version}/resource-docs/{self.api_version}/obp"
    
    async def fetch_endpoints(self) -> list[MinimalEndpoint]:
        """Fetch all endpoints and return minimal representations."""
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.get(self.resource_docs_url)
            response.raise_for_status()
            data = response.json()
        
        docs = data.get("resource_docs", [])
        endpoints = []
        
        for doc in docs:
            endpoint = MinimalEndpoint(
                operation_id=doc.get("operation_id", ""),
                request_verb=doc.get("request_verb", ""),
                request_url=doc.get("request_url", ""),
                summary=doc.get("summary", ""),
                tags=doc.get("tags", [])
            )
            endpoints.append(endpoint)
        
        print(f"Fetched {len(endpoints)} endpoints")
        return endpoints
    
    def get_tag_index(self, endpoints: list[MinimalEndpoint]) -> dict[str, list[str]]:
        """Build index of tag -> endpoint IDs for ground truth generation."""
        tag_index: dict[str, list[str]] = {}
        for ep in endpoints:
            for tag in ep.tags:
                if tag not in tag_index:
                    tag_index[tag] = []
                tag_index[tag].append(ep.operation_id)
        return tag_index


class QueryGenerator:
    """Generates term-based queries from endpoints using an LLM."""
    
    SYSTEM_PROMPT = """You are helping generate evaluation data for a retrieval system.

Given a batch of API endpoints, generate search term queries that would be used to find each endpoint.

IMPORTANT: These are NOT natural language questions. They are comma-separated keyword/term queries 
that an LLM assistant would formulate to search a vector database of API endpoints.

Examples of good term queries:
- "account balance, get balance, check funds"
- "create transaction, payment, transfer money"  
- "authentication, oauth, login, directlogin"
- "ATM locations, cash machines, bank ATM"

For each endpoint, generate 2-3 different term queries that would help find it.
Vary the queries - use synonyms, related concepts, and different phrasings."""

    USER_PROMPT_TEMPLATE = """Generate term queries for these API endpoints:

{endpoints}

Respond with a JSON object mapping operation_id to a list of term queries:
{{
  "operation_id_1": ["query1", "query2", "query3"],
  "operation_id_2": ["query1", "query2"],
  ...
}}

Only output valid JSON, no other text."""

    def __init__(self, batch_size: int = 50):
        self.llm = get_model("small", temperature=0.7)
        self.batch_size = batch_size
    
    async def generate_queries_for_batch(
        self, 
        endpoints: list[MinimalEndpoint]
    ) -> dict[str, list[str]]:
        """Generate term queries for a batch of endpoints."""
        endpoints_str = "\n\n".join(ep.to_prompt_str() for ep in endpoints)
        
        prompt = self.USER_PROMPT_TEMPLATE.format(endpoints=endpoints_str)
        
        messages = [
            {"role": "system", "content": self.SYSTEM_PROMPT},
            {"role": "user", "content": prompt}
        ]
        
        response = await self.llm.ainvoke(messages)
        
        # Parse JSON from response
        content = ""
        try:
            # Handle both AIMessage and string responses
            if hasattr(response, 'content'):
                content = response.content
            else:
                content = str(response)
            
            # Ensure content is a string
            if not isinstance(content, str):
                content = str(content)
            
            # Strip markdown code blocks if present
            content = content.strip()
            if content.startswith("```"):
                content = content.split("\n", 1)[1]  # Remove first line
                content = content.rsplit("```", 1)[0]  # Remove last ```
            return json.loads(content)
        except json.JSONDecodeError as e:
            print(f"Failed to parse LLM response: {e}")
            print(f"Response was: {content[:500]}...")
            return {}
    
    async def generate_all_queries(
        self, 
        endpoints: list[MinimalEndpoint],
        tag_index: dict[str, list[str]]
    ) -> list[EvalQuery]:
        """Generate queries for all endpoints with ground truth labels."""
        all_queries = []
        
        # Process in batches
        for i in range(0, len(endpoints), self.batch_size):
            batch = endpoints[i:i + self.batch_size]
            print(f"Processing batch {i // self.batch_size + 1}/{(len(endpoints) + self.batch_size - 1) // self.batch_size}")
            
            query_map = await self.generate_queries_for_batch(batch)
            
            # Convert to EvalQuery objects with ground truth
            for ep in batch:
                queries = query_map.get(ep.operation_id, [])
                
                # Find possibly relevant endpoints (same tags)
                possibly_relevant = set()
                for tag in ep.tags:
                    possibly_relevant.update(tag_index.get(tag, []))
                possibly_relevant.discard(ep.operation_id)  # Remove self
                
                for query_terms in queries:
                    all_queries.append(EvalQuery(
                        query_terms=query_terms,
                        source_endpoint_id=ep.operation_id,
                        definitely_relevant=[ep.operation_id],
                        possibly_relevant=list(possibly_relevant)
                    ))
            
            # Small delay between batches to avoid rate limits
            if i + self.batch_size < len(endpoints):
                await asyncio.sleep(1)
        
        return all_queries


async def generate_dataset(
    output_path: str = "src/evals/retrieval/eval_dataset.json",
    sample_size: Optional[int] = None
) -> EvalDataset:
    """Generate a complete evaluation dataset."""
    
    # Fetch endpoints
    fetcher = EndpointFetcher()
    endpoints = await fetcher.fetch_endpoints()
    tag_index = fetcher.get_tag_index(endpoints)
    
    # Optionally sample endpoints (for testing)
    if sample_size and sample_size < len(endpoints):
        print(f"Sampling {sample_size} endpoints for testing...")
        endpoints = random.sample(endpoints, sample_size)
    
    # Generate queries
    generator = QueryGenerator(batch_size=30)
    queries = await generator.generate_all_queries(endpoints, tag_index)
    
    # Build dataset
    dataset = EvalDataset(
        queries=queries,
        endpoints=endpoints,
        metadata={
            "total_endpoints": len(endpoints),
            "total_queries": len(queries),
            "unique_tags": len(tag_index),
            "queries_per_endpoint": len(queries) / len(endpoints) if endpoints else 0
        }
    )
    
    # Save
    dataset.save(output_path)
    return dataset


def cli():
    """Command-line interface for dataset generation."""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Generate synthetic evaluation dataset for retrieval testing"
    )
    parser.add_argument(
        "-o", "--output",
        default="src/evals/retrieval/eval_dataset.json",
        help="Output path for the dataset JSON"
    )
    parser.add_argument(
        "-n", "--sample-size",
        type=int,
        default=None,
        help="Number of endpoints to sample (default: all)"
    )
    parser.add_argument(
        "--stats-only",
        action="store_true",
        help="Only show endpoint stats, don't generate queries"
    )
    
    args = parser.parse_args()
    
    if args.stats_only:
        asyncio.run(show_stats())
    else:
        asyncio.run(generate_dataset(
            output_path=args.output,
            sample_size=args.sample_size
        ))


async def show_stats():
    """Show endpoint statistics without generating queries."""
    fetcher = EndpointFetcher()
    endpoints = await fetcher.fetch_endpoints()
    
    tag_index = fetcher.get_tag_index(endpoints)
    print(f"\nTag distribution ({len(tag_index)} unique tags):")
    for tag, ops in sorted(tag_index.items(), key=lambda x: -len(x[1]))[:15]:
        print(f"  {tag}: {len(ops)} endpoints")
    
    print(f"\nSample endpoint:\n{endpoints[0].to_prompt_str()}")
    
    total_chars = sum(len(ep.to_prompt_str()) for ep in endpoints)
    print(f"\nEstimated tokens for all endpoints: ~{total_chars // 4:,}")


if __name__ == "__main__":
    cli()
