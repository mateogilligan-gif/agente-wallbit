"""Tests de lógica pura en global_search.py. Sin red."""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import global_search

RSS_FAKE = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
<channel>
<item>
<title>Mining company signs new lithium contract - Australian Financial Review</title>
<link>https://news.google.com/rss/articles/fake123</link>
<pubDate>Wed, 20 Aug 2026 10:00:00 GMT</pubDate>
<source url="https://www.afr.com">Australian Financial Review</source>
</item>
<item>
<title>Segunda noticia de prueba</title>
<link>https://news.google.com/rss/articles/fake456</link>
<pubDate>Wed, 20 Aug 2026 09:00:00 GMT</pubDate>
<source url="https://www.reuters.com">Reuters</source>
</item>
</channel>
</rss>"""


def test_parse_google_news_xml_extrae_items():
    resultados = global_search._parse_google_news_xml(RSS_FAKE, pais="AU", idioma="en", count=10)
    assert len(resultados) == 2
    assert resultados[0]["fuente"] == "Australian Financial Review"
    assert resultados[0]["url"] == "https://news.google.com/rss/articles/fake123"
    assert resultados[0]["pais"] == "AU"


def test_parse_google_news_xml_respeta_count():
    resultados = global_search._parse_google_news_xml(RSS_FAKE, pais="US", idioma="en", count=1)
    assert len(resultados) == 1


def test_parse_google_news_xml_vacio():
    resultados = global_search._parse_google_news_xml("<rss><channel></channel></rss>", pais="US", idioma="en", count=10)
    assert resultados == []
