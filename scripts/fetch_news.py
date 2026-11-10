#!/usr/bin/env python3
"""Coleta os feeds RSS e grava news.json para o painel.

Roda no GitHub Actions (ver .github/workflows/news.yml) a cada ~15 min. Fazer a coleta no servidor
resolve três problemas do navegador: CORS dos portais, limite de taxa do rss2json e a codificação
ISO-8859-1 do UOL. Só usa a biblioteca padrão do Python.

Uso: python3 scripts/fetch_news.py [saida.json]
"""
import email.utils
import gzip
import time
import html
import json
import re
import sys
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FEEDS = json.loads((ROOT / "feeds.json").read_text("utf-8"))
OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "news.json"

MAX_PER_FEED = 15          # notícias mais recentes por fonte
MAX_AGE = timedelta(days=3)  # ignora o que for mais velho (ex.: feed G1 Brasil parado desde 2023)
MAX_OG_LOOKUPS = 45        # páginas abertas por execução para achar imagem (og:image)
UA = "Mozilla/5.0 (compatible; painel-ipad/2.0; +https://github.com/fcval5000/painel-ipad)"
TZ_BR = timezone(timedelta(hours=-3))

# Datas do UOL vêm com dia/mês em português ("Ter, 10 Nov 2026 08:38:14 -0300")
PT = {"Dom": "Sun", "Seg": "Mon", "Ter": "Tue", "Qua": "Wed", "Qui": "Thu", "Sex": "Fri", "Sáb": "Sat", "Sab": "Sat",
      "Fev": "Feb", "Abr": "Apr", "Mai": "May", "Ago": "Aug", "Set": "Sep", "Out": "Oct", "Dez": "Dec"}
US_TZ = {"EST": "-0500", "EDT": "-0400", "CST": "-0600", "CDT": "-0500", "PST": "-0800", "PDT": "-0700", "BRT": "-0300"}


def get(url, timeout=20, tries=2):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Encoding": "gzip"})
    for n in range(tries):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw = r.read()
                charset = r.headers.get_content_charset()
            if raw[:2] == b"\x1f\x8b":  # a Globo às vezes manda gzip mesmo sem pedir
                raw = gzip.decompress(raw)
            return raw, charset
        except Exception:
            if n == tries - 1:
                raise
            time.sleep(2)


def decode(raw, charset):
    m = re.match(rb"<\?xml[^>]*encoding=['\"]([\w-]+)", raw)
    for enc in filter(None, [charset, m and m.group(1).decode(), "utf-8"]):
        try:
            return raw.decode(enc)
        except (LookupError, UnicodeDecodeError):
            continue
    return raw.decode("latin-1")


def parse_date(s):
    if not s:
        return None
    s = s.strip()
    for pt, en in PT.items():
        s = re.sub(rf"\b{pt}\b", en, s)
    s = re.sub(r"-0000$", "+0000", s)  # email.utils trata -0000 como "fuso desconhecido"
    s = re.sub(r"\b(EST|EDT|CST|CDT|PST|PDT|BRT)\b", lambda m: US_TZ[m.group(1)], s)
    try:
        d = email.utils.parsedate_to_datetime(s)
    except (TypeError, ValueError):
        try:
            d = datetime.fromisoformat(s.replace("Z", "+00:00"))
        except ValueError:
            return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=TZ_BR)
    return d.astimezone(timezone.utc)


def text_of(fragment):
    if not fragment or fragment.strip().lower() in ("null", "none"):
        return ""
    t = re.sub(r"<[^>]+>", " ", fragment)
    t = html.unescape(t)
    t = re.sub(r"\s+", " ", t).strip()
    t = re.sub(r"(^|(?<=[\s(\"“]))\?(?=\w)", "", t)  # UOL troca caracteres invisíveis por "?" ("O ?ministro")
    return re.sub(r"\s+([.,;:!?)])", r"\1", t)  # "Switch 2 ." -> "Switch 2."


def first_img(fragment):
    m = re.search(r"<img[^>]+src=['\"]([^'\"]+)['\"]", fragment or "", re.I)
    return m.group(1) if m else None


def upgrade_img(url):
    """Pede uma versão maior quando o portal entrega miniatura."""
    if not url:
        return None
    url = html.unescape(url).replace("http://", "https://", 1)
    url = re.sub(r"_v2_\d+x\d+(\.\w+)$", r"_v2_900x506\1", url)  # UOL: 142x100 -> 900x506
    return url


def local(tag):
    return tag.rsplit("}", 1)[-1]


def child(el, *names):
    for c in el:
        if local(c.tag) in names:
            return c
    return None


def parse_feed(feed):
    raw, cs = get(feed["url"])
    xml = decode(raw, cs)
    xml = re.sub(r"^\s*<\?xml[^>]*\?>", "", xml)  # já decodificado; evita conflito de encoding
    root = ET.fromstring(xml)
    items = [e for e in root.iter() if local(e.tag) in ("item", "entry")]
    out = []
    for it in items:
        title = text_of((child(it, "title").text if child(it, "title") is not None else "") or "")
        if not title:
            continue
        link_el = child(it, "link")
        link = (link_el.text or link_el.get("href") or "").strip() if link_el is not None else ""
        desc_el = child(it, "description", "summary", "content", "encoded")
        desc_raw = desc_el.text if desc_el is not None else ""
        sub = child(it, "subtitle")
        summary = text_of(sub.text if sub is not None else "") or text_of(desc_raw)
        if summary.startswith(title):
            summary = summary[len(title):].strip(" -–—:")
        if summary.endswith(title):
            summary = summary[: -len(title)].strip(" -–—:")
        img = None
        for c in it:
            n = local(c.tag)
            if n in ("content", "thumbnail") and c.get("url") and (c.get("medium") == "image" or n == "thumbnail"
                                                                   or re.search(r"\.(jpe?g|png|webp)", c.get("url"), re.I)):
                img = c.get("url")
                break
            if n == "enclosure" and (c.get("type", "").startswith("image") or re.search(r"\.(jpe?g|png|webp)", c.get("url", ""), re.I)):
                img = c.get("url")
                break
        enc = child(it, "encoded")
        img = img or first_img(desc_raw) or first_img(enc.text if enc is not None else "")
        date_el = child(it, "pubDate", "published", "updated", "date")
        d = parse_date(date_el.text if date_el is not None else None)
        out.append({
            "source": feed["id"],
            "title": title,
            "summary": summary[:420],
            "link": link,
            "image": upgrade_img(img),
            "_orig": img,
            "date": d.isoformat().replace("+00:00", "Z") if d else None,
        })
    now = datetime.now(timezone.utc)
    out = [x for x in out if not x["date"] or now - parse_date(x["date"]) <= MAX_AGE]
    out.sort(key=lambda x: x["date"] or "", reverse=True)
    return out[:MAX_PER_FEED]


def og_image(url):
    try:
        raw, cs = get(url, timeout=12)
    except Exception:
        return None
    page = decode(raw[:300_000], cs)
    m = (re.search(r"<meta[^>]+property=['\"]og:image['\"][^>]+content=['\"]([^'\"]+)", page, re.I)
         or re.search(r"<meta[^>]+content=['\"]([^'\"]+)['\"][^>]+property=['\"]og:image['\"]", page, re.I))
    return upgrade_img(m.group(1)) if m else None


def main():
    previous = {}
    if OUT.exists():
        try:
            previous = {x["link"]: x.get("image") for x in json.loads(OUT.read_text("utf-8"))["items"] if x.get("image")}
        except Exception:
            pass

    items, status = [], {}

    def run(feed):
        try:
            return feed, parse_feed(feed), None
        except Exception as e:  # um feed fora do ar não derruba os outros
            return feed, [], f"{type(e).__name__}: {e}"[:200]

    with ThreadPoolExecutor(8) as ex:
        for feed, got, err in ex.map(run, FEEDS):
            status[feed["id"]] = {"ok": err is None, "count": len(got), **({"error": err} if err else {})}
            items += got
            print(f"{feed['id']:<14} {'OK ' if not err else 'ERR'} {len(got):>3}  {err or ''}")

    # dedup por link e por título
    seen, uniq = set(), []
    for x in sorted(items, key=lambda x: x["date"] or "", reverse=True):
        key = (x["link"].split("?")[0], x["title"].lower())
        if key[0] in seen or key[1] in seen:
            continue
        seen.update(key)
        uniq.append(x)

    missing = [x for x in uniq if not x["image"]]
    for x in missing:
        x["image"] = previous.get(x["link"])
    lookup = [x for x in missing if not x["image"] and x["link"]][:MAX_OG_LOOKUPS]
    with ThreadPoolExecutor(8) as ex:
        for x, img in zip(lookup, ex.map(lambda x: og_image(x["link"]), lookup)):
            x["image"] = img

    # a versão ampliada nem sempre existe (UOL): confere e volta para a original se der erro
    def check(x):
        if x.get("_orig") and x["image"] and "_v2_900x506" in x["image"]:
            try:
                urllib.request.urlopen(urllib.request.Request(x["image"], method="HEAD", headers={"User-Agent": UA}), timeout=8)
            except Exception:
                x["image"] = html.unescape(x["_orig"])
    with ThreadPoolExecutor(8) as ex:
        list(ex.map(check, uniq))
    for x in uniq:
        x.pop("_orig", None)

    data = {
        "generated": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "feeds": status,
        "items": uniq,
    }
    OUT.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), "utf-8")
    print(f"{len(uniq)} notícias -> {OUT}")
    if not uniq:
        sys.exit(1)


if __name__ == "__main__":
    main()
