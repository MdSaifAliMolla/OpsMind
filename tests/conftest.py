import os

# Tests pin the deterministic engine: no network, no keys, no quota.
# The LLM path is exercised by app/evaluation/ablate.py instead.
os.environ["OPSMIND_DISABLE_LLM"] = "1"
