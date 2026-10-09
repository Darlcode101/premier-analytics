"""Check that each configured Foundry deployment answers. Run: python scripts/smoke_models.py"""
import os
import sys
import time

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()
endpoint = os.environ["AZURE_OPENAI_ENDPOINT"].rstrip("/")
client = OpenAI(base_url=f"{endpoint}/openai/v1/", api_key=os.environ["AZURE_OPENAI_API_KEY"])

failed = False
for var in ("LIVE_MODEL_DEPLOYMENT", "RECAP_MODEL_DEPLOYMENT"):
    deployment = os.environ[var]
    start = time.perf_counter()
    try:
        resp = client.chat.completions.create(
            model=deployment,
            messages=[{"role": "user", "content": "Reply with exactly: OK"}],
        )
        elapsed = time.perf_counter() - start
        print(f"PASS {var}={deployment}: {resp.choices[0].message.content!r} in {elapsed:.2f}s, "
              f"{resp.usage.total_tokens} tokens")
    except Exception as e:  # report every deployment, not just the first failure
        failed = True
        print(f"FAIL {var}={deployment}: {type(e).__name__}: {e}")
sys.exit(1 if failed else 0)
