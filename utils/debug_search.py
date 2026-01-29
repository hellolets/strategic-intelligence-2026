
import asyncio
import os
from deep_research.searcher import execute_search_multi_layer
from deep_research.config import tavily_client, TAVILY_ENABLED, search_policy

async def test_search():
    print(f"TAVILY_ENABLED: {TAVILY_ENABLED}")
    print(f"tavily_client: {tavily_client is not None}")
    
    queries = [
        '"Ferrovial" opportunities satellite aerospace defense applications',
        '"Ferrovial" market trends satellite aerospace infrastructure',
        'Ferrovial aerospace defense sector'
    ]
    
    topic = "5.3 Opportunities in satellite, aerospace, and secure facilities"
    report_type = "General"
    
    print(f"\nTesting search for topic: {topic}")
    results = await execute_search_multi_layer(
        queries=queries,
        topic=topic,
        report_type=report_type
    )
    
    print(f"\nFinal Results count: {len(results)}")
    for r in results[:3]:
        print(f"- {r.get('url')} ({r.get('search_engine')})")

if __name__ == "__main__":
    asyncio.run(test_search())
