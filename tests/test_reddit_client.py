"""Tests de lógica pura en reddit_client.py. Sin red, sin OAuth real."""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import reddit_client

RESPUESTA_FAKE = {
    "data": {
        "children": [
            {"data": {
                "title": "AAPL earnings beat expectations",
                "subreddit": "stocks",
                "score": 150,
                "num_comments": 40,
                "permalink": "/r/stocks/comments/abc123/",
                "created_utc": 1755000000
            }},
            {"data": {
                "title": "YOLO'd my savings into AAPL calls",
                "subreddit": "wallstreetbets",
                "score": 900,
                "num_comments": 300,
                "permalink": "/r/wallstreetbets/comments/xyz789/",
                "created_utc": 1755001000
            }}
        ]
    }
}


def test_parse_reddit_listing_extrae_posts():
    posts = reddit_client._parse_reddit_listing(RESPUESTA_FAKE)
    assert len(posts) == 2
    assert posts[0]["subreddit"] in ("stocks", "wallstreetbets")


def test_parse_reddit_listing_ordena_por_score_descendente():
    posts = reddit_client._parse_reddit_listing(RESPUESTA_FAKE)
    assert posts[0]["score"] == 900  # el de wallstreetbets, mas upvotes
    assert posts[1]["score"] == 150


def test_parse_reddit_listing_url_completa():
    posts = reddit_client._parse_reddit_listing(RESPUESTA_FAKE)
    assert all(p["url"].startswith("https://reddit.com/r/") for p in posts)


def test_parse_reddit_listing_vacio():
    assert reddit_client._parse_reddit_listing({"data": {"children": []}}) == []


def test_sin_credenciales_devuelve_error_claro(monkeypatch):
    monkeypatch.delenv("REDDIT_CLIENT_ID", raising=False)
    monkeypatch.delenv("REDDIT_CLIENT_SECRET", raising=False)
    reddit_client._token_cache["access_token"] = None
    reddit_client._token_cache["expira"] = 0
    resultado = reddit_client.search_reddit("AAPL")
    assert resultado["ok"] is False
    assert "REDDIT_CLIENT_ID" in resultado["error"]
