from datetime import datetime, timezone
from app.example_queries import example_queries


def test_examples_use_shanghai_date_and_keep_experimental_out_of_defaults():
    cards=example_queries(datetime(2026,11,13,17,tzinfo=timezone.utc))
    assert len(cards)==6
    portfolio=next(c for c in cards if c['id']=='portfolio')
    assert '2026-11-14' in portfolio['query']
    assert all('未来一年的投资机会' not in c['query'] for c in cards)
