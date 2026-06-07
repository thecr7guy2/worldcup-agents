"""Read-only web layer: a FastAPI JSON API over the live competition state.

The site reuses db.py + leaderboard.py verbatim so there is one source of truth for
domain logic. Nothing here mutates the database; the connection is opened read-only.
"""
