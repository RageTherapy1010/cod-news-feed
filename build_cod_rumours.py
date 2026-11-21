
import calendar
import datetime
import email.utils
import re
import urllib.request
import xml.etree.ElementTree as ET
from html import unescape
from urllib.parse import urlsplit, urlunsplit

import feedparser


DAYS_BACK = 14
MAX_ARTICLES = 50
OUTPUT_FILE = "cod-rumours.xml"

USER_AGENT = "Mozilla/5.0 (compatible; RageTherapyRSS/1.0)"

# GameRiv has a dedicated Call of Duty feed.
# The other sources are general gaming RSS feeds.
RSS_SOURCES = {
    "GameRiv COD": {
        "url": "https://gameriv.com/call-of-duty/feed/",
        "cod_specific": True,
    },
    "Dexerto": {
        "url": "https://www.dexerto.com/feed/",
        "cod_specific": False,
    },
    "GamesRadar+": {
        "url": "https://www.gamesradar.com/feeds.xml",
        "cod_specific": False,
    },
    "Eurogamer": {
        "url": "https://www.eurogamer.net/feed",
        "cod_specific": False,
    },
    "VGC": {
        "url": "https://www.videogameschronicle.com/feed/",
        "cod_specific": False,
    },
}

COD_TERMS = [
    "call of duty",
    "black ops",
    "modern warfare",
    "warzone",
    "cod mobile",
    "codm",
    "dmz",
    "mw4",
    "mw3",
    "mw2",
]

RUMOUR_TERMS = [
    "rumour",
    "rumor",
    "rumoured",
    "rumored",
    "leak",
    "leaked",
    "leaker",
    "leaks",
    "datamine",
    "datamined",
    "data mine",
    "unconfirmed",
    "unverified",
    "allegedly",
    "alleged",
    "supposedly",
    "speculation",
    "speculated",
    "insider claims",
    "insider says",
    "reportedly",
    "could be coming",
    "may be coming",
    "might be coming",
    "is said to be",
]

LEAK_TERMS = [
    "leak",
    "leaked",
    "leaker",
    "leaks",
    "datamine",
    "datamined",
    "data mine",
]

REJECTION_TERMS = [
    "rumour debunked",
    "rumor debunked",
    "leak debunked",
    "fake leak",
    "false rumour",
    "false rumor",
    "rumour is false",
    "rumor is false",
    "denies rumours",
    "denies rumors",
    "denies report",
    "officially confirmed",
    "official announcement",
    "officially announced",
    "officially revealed",
    "confirmed by activision",
    "activision confirms",
    "treyarch confirms",
    "infinity ward confirms",
]


def clean_text(value):
    value = unescape(str(value or ""))
    value = re.sub(r"<[^>]+>", " ", value)
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def normalise_url(url):
    if not url:
        return ""

    parts = urlsplit(url.strip())

    if parts.scheme not in ("http", "https"):
        return ""

    return urlunsplit((
        parts.scheme,
        parts.netloc,
        parts.path.rstrip("/"),
        "",
        "",
    ))


def contains_term(text, terms):
    text = text.lower()

    for term in terms:
        pattern = r"(?<!\w)" + re.escape(term) + r"(?!\w)"

        if re.search(pattern, text):
            return True

    return False


def parse_date(entry):
    if entry.get("published_parsed"):
        return datetime.datetime.fromtimestamp(
            calendar.timegm(entry.published_parsed),
            datetime.timezone.utc,
        )

    if entry.get("updated_parsed"):
        return datetime.datetime.fromtimestamp(
            calendar.timegm(entry.updated_parsed),
            datetime.timezone.utc,
        )

    value = entry.get("published") or entry.get("updated")

    if not value:
        return None

    try:
        parsed = datetime.datetime.fromisoformat(
            value.replace("Z", "+00:00")
        )

        if parsed.tzinfo is None:
            parsed = parsed.replace(
                tzinfo=datetime.timezone.utc
            )

        return parsed.astimezone(datetime.timezone.utc)

    except (ValueError, TypeError):
        try:
            parsed = email.utils.parsedate_to_datetime(value)

            if parsed.tzinfo is None:
                parsed = parsed.replace(
                    tzinfo=datetime.timezone.utc
                )

            return parsed.astimezone(datetime.timezone.utc)

        except (ValueError, TypeError, OverflowError):
            return None


def is_recent(article_date):
    if not article_date:
        return False

    cutoff = datetime.datetime.now(
        datetime.timezone.utc
    ) - datetime.timedelta(days=DAYS_BACK)

    return article_date >= cutoff


def get_game_mode(text):
    text = text.lower()

    if "dmz" in text:
        return "DMZ"

    if "warzone" in text:
        return "WARZONE"

    if "zombies" in text:
        return "ZOMBIES"

    if "multiplayer" in text:
        return "MULTIPLAYER"

    return "CALL OF DUTY"


def fetch_feed(url):
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/rss+xml, application/xml, text/xml",
        },
    )

    with urllib.request.urlopen(request, timeout=30) as response:
        return feedparser.parse(response.read())


def read_sources():
    articles = {}

    for source, settings in RSS_SOURCES.items():
        feed_url = settings["url"]
        cod_specific = settings["cod_specific"]

        print()
        print("=" * 50)
        print("SOURCE:", source)
        print("URL:", feed_url)

        stats = {
            "received": 0,
            "recent": 0,
            "cod": 0,
            "rumour": 0,
            "accepted": 0,
            "rejected": 0,
        }

        try:
            feed = fetch_feed(feed_url)
            stats["received"] = len(feed.entries)

            print("Articles received:", stats["received"])

            for entry in feed.entries:
                title = clean_text(entry.get("title", ""))
                url = normalise_url(entry.get("link", ""))

                description = clean_text(
                    entry.get(
                        "summary",
                        entry.get("description", ""),
                    )
                )

                searchable = (title + " " + description).lower()

                if not title or not url:
                    stats["rejected"] += 1
                    continue

                article_date = parse_date(entry)

                if not is_recent(article_date):
                    stats["rejected"] += 1
                    continue

                stats["recent"] += 1

                if not cod_specific and not contains_term(
                    searchable, COD_TERMS
                ):
                    stats["rejected"] += 1
                    continue

                stats["cod"] += 1

                if not contains_term(searchable, RUMOUR_TERMS):
                    stats["rejected"] += 1
                    continue

                stats["rumour"] += 1

                if contains_term(searchable, REJECTION_TERMS):
                    stats["rejected"] += 1
                    print("Excluded as confirmed/debunked:", title)
                    continue

                kind = (
                    "LEAK"
                    if contains_term(searchable, LEAK_TERMS)
                    else "RUMOUR"
                )

                mode = get_game_mode(searchable)

                if url in articles:
                    continue

                articles[url] = {
                    "title": title,
                    "url": url,
                    "source": source,
                    "date": article_date,
                    "kind": kind,
                    "mode": mode,
                }

                stats["accepted"] += 1

                print("ACCEPTED:", title)
                print("TYPE:", kind)
                print("MODE:", mode)

        except Exception as error:
            print("SOURCE ERROR:", error)

        print()
        print("SOURCE RESULTS:")
        print("Received:", stats["received"])
        print("Recent:", stats["recent"])
        print("COD-related:", stats["cod"])
        print("Rumour/leak matches:", stats["rumour"])
        print("Accepted:", stats["accepted"])
        print("Rejected:", stats["rejected"])

    return articles


def create_rss(articles):
    root = ET.Element(
        "rss",
        {"version": "2.0"},
    )

    channel = ET.SubElement(root, "channel")

    ET.SubElement(channel, "title").text = (
        "Rage Therapy - COD Rumours & Leaks"
    )

    ET.SubElement(channel, "link").text = (
        "https://github.com/RageTherapy1010/cod-news-feed"
    )

    ET.SubElement(channel, "description").text = (
        "Call of Duty rumours and leaks. "
        "All posts are unconfirmed unless officially verified."
    )

    ET.SubElement(channel, "language").text = "en"

    sorted_articles = sorted(
        articles.values(),
        key=lambda item: item["date"],
        reverse=True,
    )[:MAX_ARTICLES]

    for article in sorted_articles:
        item = ET.SubElement(channel, "item")

        ET.SubElement(item, "title").text = (
            f"[{article['kind']}] "
            f"[{article['mode']}] "
            f"{article['title']}"
        )

        ET.SubElement(item, "link").text = article["url"]
        ET.SubElement(item, "guid").text = article["url"]

        ET.SubElement(item, "pubDate").text = (
            email.utils.format_datetime(article["date"])
        )

        ET.SubElement(item, "source").text = article["source"]

        ET.SubElement(item, "category").text = article["kind"]
        ET.SubElement(item, "category").text = article["mode"]

        ET.SubElement(item, "description").text = (
            "UNCONFIRMED: This report has not been officially "
            "confirmed by Call of Duty. "
            f"Source: {article['source']}. "
            "Open the original article for details."
        )

    tree = ET.ElementTree(root)
    ET.indent(tree, space="  ")

    tree.write(
        OUTPUT_FILE,
        encoding="utf-8",
        xml_declaration=True,
    )

    print()
    print("=" * 50)
    print("TOTAL COD RUMOURS & LEAKS:", len(sorted_articles))
    print("RSS feed generated:", OUTPUT_FILE)

    if not sorted_articles:
        print(
            "No articles passed the filters. "
            "Check the source results above."
        )


def main():
    print("Starting COD Rumours & Leaks feed build...")
    print("Only recent COD rumours and leaks are included.")
    print("Officially confirmed and debunked stories are excluded.")
    print("Articles are labelled as unconfirmed.")

    articles = read_sources()
    create_rss(articles)


if __name__ == "__main__":
    main()
