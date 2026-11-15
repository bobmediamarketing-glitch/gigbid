"""Long-term memory: only promoted knowledge, written to a LangGraph store by explicit rules.

- style.py    : rules learned from the user's edits to drafts
- outcomes.py : what got replies per job category
- store.py    : the store backend (Postgres in production, SQLite locally, in-memory in tests)
"""
