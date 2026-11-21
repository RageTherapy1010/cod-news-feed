
import calendar
import datetime
import email.utils
import re
import time
import urllib.request
import xml.etree.ElementTree as ET

import feedparser


# SETTINGS
DAYS_BACK = 14
MAX_ARTICLES = 50
OUTPUT_FILE = "cod-rumours.xml"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 Chrome/120.0 Safari/537.36"
)

# Use the same four RSS sources as the existing COD news feed.
# This script reads their RSS feeds only.
RSS_SOURCES = {
    "Dexerto": "https://www.dexerto.com/feed/",
    "GamesRadar+": "https://www.gamesradar.com/feeds.xml",
    "Eurogamer": "https://www.eurogamer.net/feed",
    "VGC": "https://www.videogameschronicle.com/feed/",
}

COD_TERMS = [
    "call of duty",
    "modern warfare",
    "black ops",
    "warzone",
    "cod mobile",
    "codm",
    "mw4",
    "mwiii",
    "mw3",
    "mw2",
    "dmz",
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
    "alleged",
    "allegedly",
    "supposedly",
    "speculation",
    "speculated",
    "insider claims",
    "insider says",
    "according to insider",
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


def fetch_url(url):
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/rss+xml,application/xml,*/*",
        },
    )

    with urllib.request.urlopen(request, timeout=25) as response:
        return response.read()


def clean_text(value):
    from html import unescape

    value = unescape(str(value or ""))
    value = re.sub(r"<[^>]+>", " ", value)
    value = re.sub(r"\s+", " ", value)

    return value.strip()


def normalise_url(url):
    from urllib.parse import urlparse

    if not url:
        return ""

    parsed = urlparse(url.strip())

    if parsed.scheme not in ("http", "https"):
        return ""

    return parsed._replace(
        fragment="",
        query="",
    ).geturl().rstrip("/")


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


def read_sources():
    articles = {}

    for source, feed_url in RSS_SOURCES.items():
        print()
        print("SOURCE:", source)
        print("URL:", feed_url)

        try:
            feed_data = fetch_url(feed_url)
            feed = feedparser.parse(feed_data)

            print("Articles received:", len(feed.entries))

            accepted_before = len(articles)

            for entry in feed.entries:
                title = clean_text(entry.get("title", ""))
                url = normalise_url(entry.get("link", ""))

                # Use the feed description for filtering only.
                # We do not republish the original article text.
                description = clean_text(
                    entry.get("summary", entry.get("description", ""))
                )

                searchable_text = title + " " + description

                if not title or not url:
                    continue

                if not contains_term(searchable_text, COD_TERMS):
                    continue

                if not contains_term(searchable_text, RUMOUR_TERMS):
                    continue

                article_date = parse_date(entry)

                if not is_recent(article_date):
                    continue

                if url in articles:
                    continue

                kind = (
                    "LEAK"
                    if contains_term(searchable_text, LEAK_TERMS)
                    else "RUMOUR"
                )

                mode = get_game_mode(searchable_text)

                articles[url] = {
                    "title": title,
                    "url": url,
                    "source": source,
                    "date": article_date,
                    "kind": kind,
                    "mode": mode,
                }

            print(
                "COD rumours/leaks accepted:",
                len(articles) - accepted_before,
            )

        except Exception as error:
            print("Source could not be read:", error)

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
        "Unconfirmed Call of Duty rumours and leaks. "
        "All posts are unverified unless officially confirmed."
    )

    ET.SubElement(channel, "language").text = "en"

    sorted_articles = sorted(
        articles.values(),
        key=lambda item: item["date"],
        reverse=True,
    )[:MAX_ARTICLES]

    for article in sorted_articles:
        item = ET.SubElement(channel, "item")

        post_title = (
            f"[{article['kind']}] "
            f"[{article['mode']}] "
            f"{article['title']}"
        )

        ET.SubElement(item, "title").text = post_title

        ET.SubElement(item, "link").text = article["url"]

        ET.SubElement(item, "guid").text = article["url"]

        ET.SubElement(item, "pubDate").text = (
            email.utils.format_datetime(article["date"])
        )

        ET.SubElement(item, "source").text = article["source"]

        ET.SubElement(item, "category").text = article["kind"]

        ET.SubElement(item, "category").text = article["mode"]

        ET.SubElement(item, "description").text = (
            "UNCONFIRMED: This is a rumour or leak and has not "
            "been officially confirmed. "
            f"Original source: {article['source']}. "
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
    print("TOTAL COD RUMOURS & LEAKS:", len(sorted_articles))
    print("RSS feed successfully generated:", OUTPUT_FILE)

    print()
    print("FINAL ARTICLE LIST:")

    for article in sorted_articles:
        print(
            article["date"].strftime("%Y-%m-%d"),
            "|",
            article["kind"],
            "|",
            article["mode"],
            "|",
            article["source"],
            "|",
            article["title"],
        )


def main():
    print("Starting COD Rumours & Leaks feed build...")

    print(
        "Only Call of Duty-related rumours and leaks are included."
    )

    print(
        "Articles are labelled as unconfirmed."
    )

    print(
        f"Only articles from the last {DAYS_BACK} days are included."
    )

    articles = read_sources()

    create_rss(articles)


if __name__ == "__main__":
    main()
