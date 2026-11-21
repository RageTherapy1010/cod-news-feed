
import calendar
import datetime
import email.utils
import re
import urllib.request
import xml.etree.ElementTree as ET
from html import unescape
from urllib.parse import urlencode, urlparse

import feedparser


DAYS_BACK = 14
MAX_ARTICLES = 50
OUTPUT_FILE = "cod-rumours.xml"

USER_AGENT = "Mozilla/5.0 (compatible: RageTherapyMW4RSS/1.0)"

GOOGLE_NEWS_SEARCHES = [
    '"Modern Warfare 4" (leak OR leaked OR leaker OR datamine OR rumour OR rumor OR insider OR unconfirmed)',
    '"MW4" (leak OR leaked OR leaker OR datamine OR rumour OR rumor OR insider OR unconfirmed)',
    '"Modern Warfare IV" (leak OR leaked OR datamine OR rumour OR rumor OR insider)',
]

RSS_SOURCES = {
    "GameRiv COD": "https://gameriv.com/call-of-duty/feed/",
}

MW4_TERMS = [
    "modern warfare 4",
    "modern warfare iv",
    "mw4",
]

# These phrases indicate ordinary news or confirmed information.
# They take priority over general rumour wording.
ORDINARY_NEWS_TERMS = [
    "known issues",
    "patch notes",
    "patch note",
    "patch update",
    "title update",
    "update notes",
    "hotfix",
    "bug fixes",
    "bug fix",
    "how to",
    "guide:",
    "guide -",
    "walkthrough",
    "best loadout",
    "best weapon build",
    "weapon build",
    "all rewards",
    "all locations",
    "where to find",
    "how to get",
    "how to unlock",
    "review:",
    "review -",
    "sales",
    "player count",
    "campaign review",
    "official trailer",
    "official reveal",
    "official announcement",
    "officially announced",
    "officially confirmed",
    "developer confirmed",
    "developers confirmed",
    "activision confirmed",
    "infinity ward confirmed",
    "treyarch confirmed",
    "sledgehammer confirmed",
    "developer reveals",
    "developers reveal",
    "activision reveals",
    "infinity ward reveals",
    "treyarch reveals",
    "sledgehammer reveals",
    "announces",
    "announced",
    "revealed",
    "release date announced",
    "released and detailed",
    "season arrives",
    "season is live",
    "now available",
]

# These are strong signs that a report is not an unverified rumour.
CONFIRMED_TERMS = [
    "officially confirmed",
    "official confirmation",
    "confirmed by activision",
    "confirmed by infinity ward",
    "confirmed by treyarch",
    "confirmed by sledgehammer",
    "developer confirmed",
    "developers confirmed",
    "activision confirmed",
    "infinity ward confirmed",
    "treyarch confirmed",
    "sledgehammer confirmed",
    "officially announced",
    "official announcement",
    "official reveal",
    "officially revealed",
]

RUMOUR_TITLE_TERMS = [
    "rumour",
    "rumours",
    "rumor",
    "rumors",
    "leak",
    "leaked",
    "leaker",
    "leaks",
    "datamine",
    "datamined",
    "unconfirmed",
    "unverified",
    "allegedly",
    "speculation",
    "speculative",
]

LEAK_TERMS = [
    "leak",
    "leaked",
    "leaker",
    "leaks",
    "datamine",
    "datamined",
]

REJECTION_TERMS = [
    "debunked",
    "fake leak",
    "fake rumour",
    "fake rumor",
    "false leak",
    "disproven leak",
    "debunk",
]

REPORT_TERMS = [
    "report",
    "reports",
    "reportedly",
    "according to sources",
    "according to an insider",
    "sources claim",
    "sources say",
    "insider claims",
    "insiders claim",
    "could",
    "might",
    "may",
    "potential",
    "possible",
    "expected",
    "early",
]

REPORT_SUBJECTS = [
    "release date",
    "season",
    "map",
    "maps",
    "weapon",
    "weapons",
    "operator",
    "operators",
    "perk",
    "perks",
    "game mode",
    "game modes",
    "mode",
    "modes",
    "dmz",
    "ranked",
    "multiplayer",
    "warzone",
]


def clean_text(value):
    value = unescape(str(value or ""))
    value = re.sub(r"<[^>]+>", " ", value)
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def normalise(value):
    return clean_text(value).lower()


def contains_any(text, terms):
    return any(term in text for term in terms)


def get_entry_date(entry):
    parsed = (
        entry.get("published_parsed")
        or entry.get("updated_parsed")
    )

    if parsed:
        return datetime.datetime.fromtimestamp(
            calendar.timegm(parsed),
            tz=datetime.timezone.utc,
        )

    for field in ("published", "updated"):
        value = entry.get(field)

        if value:
            try:
                parsed_date = email.utils.parsedate_to_datetime(value)

                if parsed_date.tzinfo is None:
                    parsed_date = parsed_date.replace(
                        tzinfo=datetime.timezone.utc
                    )

                return parsed_date.astimezone(datetime.timezone.utc)

            except (TypeError, ValueError):
                pass

    return None


def get_rss_sources():
    sources = dict(RSS_SOURCES)

    for number, search in enumerate(GOOGLE_NEWS_SEARCHES, start=1):
        params = {
            "q": f"{search} when:{DAYS_BACK}d",
            "hl": "en-US",
            "gl": "US",
            "ceid": "US:en",
        }

        url = (
            "https://news.google.com/rss/search?"
            + urlencode(params)
        )

        sources[f"Google News MW4 Search {number}"] = url

    return sources


def fetch_feed(url):
    request = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT},
    )

    with urllib.request.urlopen(request, timeout=30) as response:
        return feedparser.parse(response.read())


def resolve_article_link(url):
    """
    Try to follow Google News redirects to the publisher's article.
    If that fails, retain the original feed link.
    """
    if not url:
        return url

    if "news.google.com" not in urlparse(url).netloc.lower():
        return url

    try:
        request = urllib.request.Request(
            url,
            headers={"User-Agent": USER_AGENT},
        )

        with urllib.request.urlopen(request, timeout=12) as response:
            resolved = response.geturl()

        host = urlparse(resolved).netloc.lower()

        if host and "news.google.com" not in host:
            return resolved

    except Exception:
        pass

    return url


def is_mw4_article(searchable):
    return contains_any(searchable, MW4_TERMS)


def is_ordinary_news(title, searchable):
    """
    Reject ordinary news before checking whether something looks
    like a rumour. This prevents words in a news description from
    accidentally making a confirmed article look unconfirmed.
    """
    title_text = normalise(title)

    if contains_any(searchable, CONFIRMED_TERMS):
        return True

    if contains_any(title_text, ORDINARY_NEWS_TERMS):
        return True

    # Common ordinary-news headline patterns.
    ordinary_patterns = [
        r"\bpatch notes?\b",
        r"\bknown issues?\b",
        r"\bhow to\b",
        r"\bwhere to find\b",
        r"\ball rewards\b",
        r"\ball locations\b",
        r"\bguide\b",
        r"\bwalkthrough\b",
        r"\breview\b",
        r"\bnow available\b",
        r"\breleased and detailed\b",
        r"\bupdate adds\b",
        r"\bupdate released\b",
    ]

    if any(re.search(pattern, title_text) for pattern in ordinary_patterns):
        return True

    return False


def identify_rumour(title, searchable):
    """
    Only accept clear leak/rumour wording or a properly attributed
    speculative report. A question by itself is not enough.
    """
    title_text = normalise(title)

    # Strongest signal: the headline itself says leak or rumour.
    if contains_any(title_text, RUMOUR_TITLE_TERMS):
        if contains_any(title_text, LEAK_TERMS):
            return "LEAK"

        return "RUMOUR"

    # A report must contain both a relevant MW4 subject and
    # wording that indicates uncertainty or attribution.
    if (
        contains_any(searchable, REPORT_TERMS)
        and contains_any(searchable, REPORT_SUBJECTS)
    ):
        if contains_any(searchable, LEAK_TERMS):
            return "LEAK"

        return "RUMOUR"

    return None


def read_sources():
    articles = []

    cutoff = datetime.datetime.now(
        datetime.timezone.utc
    ) - datetime.timedelta(days=DAYS_BACK)

    for source_name, feed_url in get_rss_sources().items():
        print()
        print("=" * 60)
        print("SOURCE:", source_name)

        try:
            feed = fetch_feed(feed_url)
        except Exception as error:
            print("SOURCE ERROR:", error)
            continue

        entries = feed.entries
        print("Articles received:", len(entries))

        stats = {
            "recent": 0,
            "mw4": 0,
            "rumour": 0,
            "accepted": 0,
            "rejected": 0,
        }

        for entry in entries:
            title = clean_text(entry.get("title", ""))

            description = clean_text(
                entry.get("summary", "")
                or entry.get("description", "")
            )

            url = entry.get("link", "")
            searchable = normalise(title + " " + description)

            published = get_entry_date(entry)

            if published and published < cutoff:
                stats["rejected"] += 1
                continue

            stats["recent"] += 1

            if not is_mw4_article(searchable):
                stats["rejected"] += 1
                continue

            stats["mw4"] += 1

            print()
            print("MW4 ARTICLE:", title)

            if contains_any(searchable, REJECTION_TERMS):
                print("REJECTED: debunked or fake report")
                stats["rejected"] += 1
                continue

            if is_ordinary_news(title, searchable):
                print("REJECTED: confirmed news, guide or update")
                stats["rejected"] += 1
                continue

            category = identify_rumour(title, searchable)

            if not category:
                print("REJECTED: no clear evidence of a rumour or leak")
                stats["rejected"] += 1
                continue

            original_source = source_name

            if entry.get("source", {}).get("title"):
                original_source = clean_text(
                    entry.get("source", {}).get("title")
                )

            resolved_url = resolve_article_link(url)

            article = {
                "title": title,
                "description": description,
                "link": resolved_url,
                "published": published,
                "source": original_source,
                "category": category,
            }

            articles.append(article)
            stats["rumour"] += 1
            stats["accepted"] += 1

            print("ACCEPTED:", category)
            print("SOURCE:", original_source)
            print("LINK:", resolved_url)

        print()
        print("SOURCE RESULTS:")
        print("RECENT:", stats["recent"])
        print("MW4:", stats["mw4"])
        print("RUMOUR:", stats["rumour"])
        print("ACCEPTED:", stats["accepted"])
        print("REJECTED:", stats["rejected"])

    unique_articles = {}

    for article in articles:
        unique_articles[article["link"]] = article

    articles = list(unique_articles.values())

    articles.sort(
        key=lambda article: article["published"]
        or datetime.datetime.min.replace(
            tzinfo=datetime.timezone.utc
        ),
        reverse=True,
    )

    return articles[:MAX_ARTICLES]


def create_rss(articles):
    rss = ET.Element("rss", version="2.0")
    channel = ET.SubElement(rss, "channel")

    ET.SubElement(channel, "title").text = (
        "Rage Therapy - MW4 Rumours & Leaks"
    )

    ET.SubElement(channel, "link").text = (
        "https://github.com/RageTherapy1010/cod-news-feed"
    )

    ET.SubElement(channel, "description").text = (
        "Modern Warfare 4 rumours and leaks. "
        "All unverified claims are clearly labelled."
    )

    ET.SubElement(channel, "language").text = "en"

    for article in articles:
        item = ET.SubElement(channel, "item")

        title = (
            f"[{article['category']}] "
            f"[MW4] {article['title']}"
        )

        ET.SubElement(item, "title").text = title
        ET.SubElement(item, "link").text = article["link"]
        ET.SubElement(item, "guid").text = article["link"]

        description = (
            "UNCONFIRMED - This report has not been independently "
            "verified. Treat it as a rumour or leak.\n\n"
            f"Source: {article['source']}\n\n"
            f"{article['description']}"
        )

        ET.SubElement(item, "description").text = description

        if article["published"]:
            ET.SubElement(item, "pubDate").text = (
                email.utils.format_datetime(article["published"])
            )

    tree = ET.ElementTree(rss)
    ET.indent(tree, space="  ")

    tree.write(
        OUTPUT_FILE,
        encoding="utf-8",
        xml_declaration=True,
    )

    print()
    print("=" * 60)
    print("TOTAL MW4 RUMOURS & LEAKS:", len(articles))
    print("RSS FEED GENERATED:", OUTPUT_FILE)

    if not articles:
        print("No articles passed the MW4 filters.")


def main():
    print("Starting MW4 Rumours & Leaks collector...")
    print("Game filter: MODERN WARFARE 4 ONLY")
    print("Period: Last", DAYS_BACK, "days")
    print("Only clear leaks and attributed speculation are accepted.")
    print("Confirmed news, guides and ordinary updates are excluded.")
    print("Unverified claims will be labelled.")

    articles = read_sources()
    create_rss(articles)


if __name__ == "__main__":
    main()
