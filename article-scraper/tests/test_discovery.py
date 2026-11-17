from contextlib import closing
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from discovery import (Discovery, DiscoveryError, Settings, candidate_url, clean_query,
                       date_window, feed_items, public_request)


def rss(count=15, title="Banjir Jakarta", date="Tue, 17 Nov 2026 10:00:00 +0700"):
    return ("<rss><channel>" + "".join(
        f"<item><title>{title} {i}</title><link>https://news.example/berita/{i}</link>"
        f"<pubDate>{date}</pubDate></item>" for i in range(count)
    ) + "</channel></rss>").encode()


class DiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.settings = Settings(("https://news.example/rss",), ("news.example",),
                                 str(Path(self.tmp.name) / "cache.sqlite"))

    def test_untrusted_urls(self):
        for url in ("http://news.example/abc", "https://news.example.evil/abc",
                    "https://user:pw@news.example/abc", "https://news.example:8080/abc",
                    "https://news.example/tag/a", "https://news.example/", "https://127.0.0.1/a"):
            with self.subTest(url=url):
                self.assertIsNone(candidate_url(url, self.settings.domains))
        self.assertEqual(candidate_url("https://id.news.example/abc#frag", self.settings.domains),
                         "https://id.news.example/abc")

    def test_private_network_blocked(self):
        for url in ("https://127.0.0.1/x", "https://[::1]/x", "https://169.254.169.254/x"):
            with self.subTest(url=url), self.assertRaises(DiscoveryError):
                public_request(url)

    def test_feed_validation(self):
        for raw in (b"<!DOCTYPE rss><rss/>", "<!DOCTYPE rss><rss/>".encode("utf-16"),
                    b"<html/>", b"<rss>"):
            with self.subTest(raw=raw), self.assertRaises(DiscoveryError):
                feed_items(raw, self.settings.domains)

    def test_atom_and_feed_dates(self):
        raw = b'<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>News</title><link href="https://news.example/a"/><published>2026-11-17T00:00:00Z</published></entry></feed>'
        self.assertEqual(feed_items(raw, self.settings.domains)[0]["day"], "2026-11-17")
        self.assertEqual(feed_items(rss(1), self.settings.domains)[0]["day"], "2026-11-17")

    def test_pagination_persists_across_restart(self):
        calls = []
        def source(url):
            calls.append(url)
            return rss()
        first = Discovery(self.settings, source)
        page1 = first.search("Banjir Jakarta (site:news.example)")
        self.assertEqual(len(page1["organic_results"]), 10)
        self.assertIn("serpapi_pagination", page1)
        def unavailable(url):
            raise DiscoveryError("offline")
        restarted = Discovery(self.settings, unavailable)
        page2 = restarted.search("Banjir Jakarta", 10)
        self.assertEqual(len(page2["organic_results"]), 5)
        self.assertNotIn("serpapi_pagination", page2)
        links = [row["link"] for page in (page1, page2) for row in page["organic_results"]]
        self.assertEqual(len(set(links)), 15)
        self.assertEqual(len(calls), 1)

    def test_history_dates_do_not_invent_old_articles(self):
        service = Discovery(self.settings, lambda _: rss())
        old = service.search("Banjir Jakarta", tbs="cdr:1,cd_min:01/01/2020,cd_max:01/31/2020")
        self.assertEqual(old, {"organic_results": []})

    def test_dates_and_worker_query(self):
        self.assertEqual(clean_query("banjir (site:news.example OR site:other.example)"), "banjir")
        self.assertEqual(date_window("cdr:1,cd_min:11/01/2026,cd_max:11/17/2026"),
                         ("2026-11-01", "2026-11-17"))
        for tbs in ("tomorrow", "cdr:1,cd_min:99/99/2026,cd_max:11/17/2026"):
            with self.assertRaises(DiscoveryError):
                date_window(tbs)

    def test_feed_outage_is_error_not_empty_success(self):
        def unavailable(_):
            raise DiscoveryError("offline")
        with self.assertRaises(DiscoveryError):
            Discovery(self.settings, unavailable).search("Banjir Jakarta")

    def test_literal_words_and_no_results(self):
        service = Discovery(self.settings, lambda _: rss())
        self.assertEqual(service.search("Tidak ditemukan"), {"organic_results": []})
        # "ban" should not accidentally match "banjir".
        self.assertEqual(service.search("ban Jakarta"), {"organic_results": []})

    def test_llm_cannot_invent_url_or_id(self):
        settings = Settings(self.settings.feeds, self.settings.domains, self.settings.cache,
                            "compatible", "test", "not-a-real-key", "https://llm.example/v1")
        for ids in ([9999], [True], ["https://evil.example/"]):
            def source(url, **kwargs):
                if kwargs:
                    return json.dumps({"choices": [{"message": {"content": json.dumps({"ids": ids})}}]}).encode()
                return rss(1)
            service = Discovery(settings, source)
            with self.subTest(ids=ids):
                # Invalid AI output falls back to real feed URLs.
                self.assertEqual(service.search("Banjir Jakarta")["organic_results"],
                                 [{"link": "https://news.example/berita/0"}])
            with closing(service.db()) as db, db:
                db.execute("DELETE FROM snapshots")

    def test_normal_llm_select_uses_only_candidates(self):
        settings = Settings(self.settings.feeds, self.settings.domains, self.settings.cache,
                            "gemini", "test", "not-a-real-key", "https://llm.example/v1")
        seen = []
        def source(url, **kwargs):
            if kwargs:
                seen.append(kwargs["payload"])
                return json.dumps({"choices": [{"message": {"content": '{"ids":[1,1,0]}'}}]}).encode()
            return rss(2)
        result = Discovery(settings, source).search("Banjir Jakarta")
        self.assertEqual(len(result["organic_results"]), 2)
        self.assertEqual(len(seen), 1)

    def test_gemini_only_accepts_grounded_links(self):
        settings = Settings(self.settings.feeds, self.settings.domains, self.settings.cache,
                            "gemini", "test", "fake-key", mode="gemini_search")
        raw = {"candidates": [{"content": {"parts": [{"text": "https://news.example/invented"}]},
                               "groundingMetadata": {"groundingChunks": [
                                   {"web": {"uri": "https://news.example/real"}},
                                   {"web": {"uri": "https://evil.example/article"}}]}}]}
        service = Discovery(settings, lambda *_, **__: json.dumps(raw).encode())
        self.assertEqual(service.search("Banjir Jakarta")["organic_results"],
                         [{"link": "https://news.example/real"}])


if __name__ == "__main__":
    unittest.main()
