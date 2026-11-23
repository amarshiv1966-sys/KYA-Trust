"""P5: run browser-use 1.0.x once against the local bank and print what it cost.

Needs the bank + frontend running and a key in .env.
Run from the repo root, inside bots/.venv-agents:
    python bots/agents/smoke_browser_use.py
Uses its own Chromium (Browser('chromium')), never your personal Chrome.
"""
import os
import time

from dotenv import load_dotenv
from browser_use import Agent, Browser

load_dotenv()

TASK = ("Open http://localhost:5173/login . Log in with the customer id cust_0001 and the password "
        "demo1234. When you are on the home page, tell me the account balance shown there. Then log out.")


def make_llm():
    provider = os.environ.get("KYA_LLM", "openai")
    model = os.environ["KYA_LLM_MODEL"]
    if provider == "openai":
        from browser_use import ChatOpenAI
        return ChatOpenAI(model=model)
    if provider == "anthropic":
        from browser_use import ChatAnthropic
        return ChatAnthropic(model=model)
    if provider == "google":
        from browser_use import ChatGoogle
        return ChatGoogle(model=model)
    raise SystemExit(f"unknown KYA_LLM {provider}")


def main():
    agent = Agent(task=TASK, llm=make_llm(), browser=Browser("chromium"), judge=False)
    start = time.time()
    result = agent.run_sync()
    print("final result:", result.final_result())
    print("steps:", result.number_of_steps())
    print("seconds:", round(time.time() - start, 1))
    print("usage:", dict(result.usage))      # input / output / cache_read / cache_write / requests
    print("cost usd:", result.cost_usd)


if __name__ == "__main__":
    main()
