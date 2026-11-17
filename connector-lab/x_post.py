"""Fetch the public source Post using X's oEmbed endpoint, without a model key."""
import re
from urllib.parse import urlsplit

import httpx
from bs4 import BeautifulSoup


class PostError(RuntimeError):
    pass


HOSTS = {"x.com", "www.x.com", "mobile.x.com", "twitter.com", "www.twitter.com", "mobile.twitter.com"}


def is_x_url(url):
    try:
        return urlsplit(url).hostname in HOSTS
    except ValueError:
        return False


def post_identity(url):
    try:
        u = urlsplit(url)
        if (u.scheme != "https" or u.hostname not in HOSTS or u.username or u.password
                or u.port not in (None, 443) or any(ord(c) < 33 for c in url) or "\\" in url):
            raise ValueError()
        match = re.fullmatch(r"/(?:[A-Za-z0-9_]+|i/web)/status/([1-9][0-9]{0,19})(?:/(?:photo|video)/[0-9]+)?/?", u.path)
        if not match or int(match[1]) >= 2**63:
            raise ValueError()
        return match[1], "https://x.com" + u.path.split("/status/", 1)[0] + "/status/" + match[1]
    except (ValueError, TypeError, AttributeError):
        raise PostError("URL harus menunjuk ke satu posting X publik yang valid") from None


def extract_post(client, url):
    post_id, normalized = post_identity(url)
    lookup = f"https://x.com/i/status/{post_id}" if "/i/web/status/" in normalized else normalized
    try:
        response = client.get("https://publish.x.com/oembed", params={"url": lookup,
                              "omit_script": "true", "hide_thread": "true"})
        response.raise_for_status()
        value = response.json()
        if post_identity(value["url"])[0] != post_id or not isinstance(value["html"], str):
            raise PostError("Respons X tidak cocok dengan ID posting")
        if len(value["html"]) > 250_000:
            raise PostError("Respons X terlalu besar")
    except httpx.HTTPStatusError as exc:
        raise PostError(f"Posting publik X tidak dapat dibaca (HTTP {exc.response.status_code})") from None
    except (httpx.RequestError, KeyError, TypeError, ValueError):
        raise PostError("Respons posting X tidak tersedia atau tidak valid") from None

    soup = BeautifulSoup(value["html"], "html.parser")
    matches = []
    for quote in soup.select("blockquote.twitter-tweet"):
        for link in quote.find_all("a", href=True, recursive=False):
            try:
                if post_identity(link["href"])[0] == post_id:
                    matches.append(quote)
                    break
            except PostError:
                continue
    if len(matches) != 1:
        raise PostError("Identitas posting tidak terverifikasi di embed X")
    paras = matches[0].find_all("p", recursive=False)
    for para in paras:
        for br in para.find_all("br"):
            br.replace_with("\n")
    # Some embeds contain excerpts. Only send text the source returned.
    text = "\n\n".join(p.get_text().strip() for p in paras).strip()
    if not text or text.endswith(("…", "...")):
        raise PostError("Teks posting kosong atau terpotong pada embed X")
    return {"id": post_id, "text": text, "source_url": post_identity(value["url"])[1]}
