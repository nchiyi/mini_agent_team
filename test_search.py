import asyncio
import sys
from duckduckgo_search import DDGS

def get_ddgs(query):
    ddgs = DDGS()
    print(f"Query: {query}")
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

if __name__ == "__main__":
    # Fix console encoding on Windows for testing
    if sys.platform == 'win32':
        sys.stdout.reconfigure(encoding='utf-8')
        
    get_ddgs("今天台灣股票走勢狀態")
    print("\n================================================\n")
    get_ddgs("台灣加權指數 收盤 2026-03-06")
