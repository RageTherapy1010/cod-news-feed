
import calendar
import datetime
import email.utils
import re
import urllib.request
import xml.etree.ElementTree as ET
from html import unescape
from urllib.parse import urlsplit, urlunsplit, urlencode

import feedparser


DAYS_BACK = 14
MAX_ARTICLES = 50
OUTPUT_FILE = "cod-rumours.xml"

USER_AGENT = "Mozilla/5.0 (compatible; RageTherapyMW4RSS/1.0)"

GOOGLE_NEWS_SEARCHES = [
    '"Modern Warfare 4" (leak OR leaked OR datamine OR rumour OR rumor OR unconfirmed)',
    '"MW4" (leak OR leaked OR datamine OR rumour OR rumor OR unconfirmed)',
    '"Modern Warfare IV" (leak OR leaked OR datamine OR rumour OR rumor)',
]

RSS_SOURCES = {
    "GameRiv COD": "https://gameriv.com/call-of-duty/feed/",
}


MW4_TERMS = [
    "modern warfare 4",
    "modern warfare iv",
    "mw4",
]

RUMOUR_TERMS = [
    "rumour", "rumor", "rumoured", "rumored",
    "leak", "leaked", "leaker", "leaks",
    "datamine", "datamined", "data mine",
    "unconfirmed", "unverified",
    "allegedly", "alleged", "supposedly",
    "speculation", "speculated",
    "insider claims", "insider says",
    "reportedly",
]

LEAK_TERMS = [
    "leak", "leaked", "leaker", "leaks",
    "datamine", "datamined", "data mine",
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
    "debunked leak",
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


def is_mw4_article(text):
    return contains_term(text, MW4_TERMS)


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

    if "campaign" in text:
        return "CAMPAIGN"

    return "MODERN WARFARE 4"


def get_rss_sources():
    sources = dict(RSS_SOURCES)

    for index, query in enumerate(GOOGLE_NEWS_SEARCHES, start=1):
        search_query = query + " when:14d"

        url = (
            "https://news.google.com/rss/search?"
            + urlencode({
                "q": search_query,
                "hl": "en-US",
                "gl": "US",
                "ceid": "US:en",
            })
        )

        sources[f"Google News MW4 Search {index}"] = url

    return sources


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


def get_source_name(entry, fallback):
    source_info = entry.get("source")

    if source_info:
        try:
            name = clean_text(source_info.get("title", ""))

            if name:
                return name
        except AttributeError:
            pass

    return fallback


def read_sources():
    articles = {}

    for source, feed_url in get_rss_sources().items():

        print()
        print("=" * 55)
        print("SOURCE:", source)

        stats = {
            "received": 0,
            "recent": 0,
            "mw4": 0,
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

                searchable = title + " " + description

                if not title or not url:
                    stats["rejected"] += 1
                    continue

                article_date = parse_date(entry)

                if not is_recent(article_date):
                    stats["rejected"] += 1
                    continue

                stats["recent"] += 1

                # Only Modern Warfare 4 content is allowed.
                if not is_mw4_article(searchable):
                    stats["rejected"] += 1
                    continue

                stats["mw4"] += 1

                # Reject articles explicitly describing fake
                # or debunked claims.
                if contains_term(title, REJECTION_TERMS):
                    stats["rejected"] += 1
                    continue

                # Only actual rumour, leak or datamine reports.
                if not contains_term(searchable, RUMOUR_TERMS):
                    stats["rejected"] += 1
                    continue

                stats["rumour"] += 1

                kind = (
                    "LEAK"
                    if contains_term(searchable, LEAK_TERMS)
                    else "RUMOUR"
                )

                mode = get_game_mode(searchable)
                article_source = get_source_name(entry, source)

                if url in articles:
                    continue

                articles[url] = {
                    "title": title,
                    "url": url,
                    "source": article_source,
                    "date": article_date,
                    "kind": kind,
                    "mode": mode,
                }

                stats["accepted"] += 1

                print("ACCEPTED:", title)
                print("TYPE:", kind)
                print("MODE:", mode)
                print("SOURCE:", article_source)

        except Exception as error:
            print("SOURCE ERROR:", error)

        print()
        print("SOURCE RESULTS:")
        for name, value in stats.items():
            print(name.upper() + ":", value)

    return articles


def create_rss(articles):
    root = ET.Element(
        "rss",
        {"version": "2.0"},
    )

    channel = ET.SubElement(root, "channel")

    ET.SubElement(channel, "title").text = (
        "Rage Therapy - MW4 Rumours & Leaks"
    )

    ET.SubElement(channel, "link").text = (
        "https://github.com/RageTherapy1010/cod-news-feed"
    )

    ET.SubElement(channel, "description").text = (
        "Modern Warfare 4 rumours, leaks and datamines. "
        "All unverified claims are clearly labelled."
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
            f"[MW4 - {article['mode']}] "
            f"{article['title']}"
        )

        ET.SubElement(item, "link").text = article["url"]
        ET.SubElement(item, "guid").text = article["url"]

        ET.SubElement(item, "pubDate").text = (
            email.utils.format_datetime(article["date"])
        )

        ET.SubElement(item, "source").text = article["source"]

        ET.SubElement(item, "category").text = article["kind"]
        ET.SubElement(item, "category").text = "MODERN WARFARE 4"
        ET.SubElement(item, "category").text = article["mode"]

        ET.SubElement(item, "description").text = (
            "UNCONFIRMED: This Modern Warfare 4 report "
            "has not been officially verified. "
            f"Reported by: {article['source']}. "
            "Open the source link for the original report."
        )

    tree = ET.ElementTree(root)
    ET.indent(tree, space="  ")

    tree.write(
        OUTPUT_FILE,
        encoding="utf-8",
        xml_declaration=True,
    )

    print()
    print("=" * 55)
    print("TOTAL MW4 RUMOURS & LEAKS:", len(sorted_articles))
    print("RSS FEED GENERATED:", OUTPUT_FILE)

    if not sorted_articles:
        print("No articles passed the MW4 filters.")


def main():
    print("Starting MW4 Rumours & Leaks collector...")
    print("Game filter: MODERN WARFARE 4 ONLY")
    print("Period: Last", DAYS_BACK, "days")
    print("Official news and unrelated COD games are excluded.")
    print("Unverified claims will be labelled.")

    articles = read_sources()
    create_rss(articles)


if __name__ == "__main__":
    main()
