import asyncio
from core.ollama_client import OllamaClient
from core.engine import Engine
from skills.web_search import WebSearchSkill

async def main():
    try:
        engine = Engine(OllamaClient(), None, None)
        skill = WebSearchSkill(engine)
        queries = await skill._formulate_queries("今天台灣股票走勢狀態")
        print(f"Formulated queries: {queries}")
    except Exception as e:
        print("Error:", e)

if __name__ == "__main__":
    asyncio.run(main())
