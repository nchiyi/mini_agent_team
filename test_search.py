import asyncio
import sys
import os
from dotenv import load_dotenv
from duckduckgo_search import DDGS

try:
    from tavily import TavilyClient
except ImportError:
    TavilyClient = None

def get_ddgs(query):
    ddgs = DDGS()
    print(f"Query (DDGS fallback): {query}")
    try:
        # Get standard web results
        print("\n--- Web Results ---")
        results = list(ddgs.text(query, max_results=3, timelimit='y', region='wt-wt'))
        for r in results:
            print(f"URL: {r.get('href')}")
            print(f"Title: {r.get('title')}")
            print("---")
            
        # Get news results
        print("\n--- News Results ---")
        news_results = list(ddgs.news(query, max_results=3, timelimit='y', region='wt-wt'))
        for r in news_results:
            print(f"URL: {r.get('url')}")
            print(f"Title: {r.get('title')}")
            print("---")

    except Exception as e:
        print(f"Error: {e}")

def test_tavily(query):
    tavily_key = os.getenv("TAVILY_API_KEY")
    if not tavily_key or not TavilyClient:
        print("Tavily not configured.")
        return
        
    print(f"Query (Tavily): {query}")
    try:
        client = TavilyClient(api_key=tavily_key)
        response = client.search(query, search_depth="advanced", max_results=3)
        tavily_results = response.get("results", [])
        print("\n--- Tavily Results ---")
        for r in tavily_results:
            print(f"URL: {r.get('url')}")
            print(f"Title: {r.get('title')}")
            print("---")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    load_dotenv()
    # Fix console encoding on Windows for testing
    if sys.platform == 'win32':
        sys.stdout.reconfigure(encoding='utf-8')
        
    print("================== DDGS TEST ==================")
    os.environ.pop("TAVILY_API_KEY", None) # temporarily remove to test DDGS or just call func
    get_ddgs("今天台灣股票走勢狀態")
    
    print("\n================== TAVILY TEST ==================")
    load_dotenv(override=True) # reload env
    test_tavily("台灣加權指數 收盤 2026-03-06")
