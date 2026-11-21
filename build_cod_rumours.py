
import calendar
import datetime
import email.utils
import re
import urllib.request
import xml.etree.ElementTree as ET
from html import unescape
from urllib.parse import urlencode

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

# These terms are only used to identify clearly speculative headlines.
EXPLICIT_LEAK_TERMS = [
    "leak",
    "leaked",
    "leaker",
    "leaks",
    "datamine",
    "datamined",
]

EXPLICIT_RUMOUR_TERMS = [
    "rumour",
    "rumours",
    "rumor",
    "rumors",
    "unconfirmed",
    "unverified",
    "allegedly",
    "reportedly",
    "speculation",
    "speculative",
    "according to sources",
    "sources claim",
    "sources say",
    "sources suggest",
    "report claims",
    "report says",
    "reports suggest",
    "reports claim",
    "reportedly set to",
    "reportedly getting",
    "reportedly adding",
]

# These are rejected even if the article also mentions leaks or rumours.
REJECTION_TERMS = [
    "debunked",
    "fake leak",
    "fake rumour",
    "fake rumor",
    "false leak",
    "known issues",
    "known issue",
    "patch notes",
    "patch note",
    "hotfix notes",
    "full patch notes",
    "update notes",
    "maintenance update",
    "bug fixes",
    "bug fix",
    "how to",
    "guide:",
    "guide -",
    "walkthrough",
    "best loadout",
    "best settings",
    "all rewards",
    "where to find",
    "how to get",
    "how to unlock",
]

# Strong wording that usually indicates an official or confirmed announcement.
CONFIRMED_TERMS = [
    "officially announced",
    "official announcement",
    "officially confirmed",
    "official confirmation",
    "activision confirms",
    "activision confirmed",
    "activision announces",
    "activision announced",
    "infinity ward confirms",
    "infinity ward confirmed",
    "infinity ward announces",
    "infinity ward announced",
    "developers confirm",
    "developer confirms",
    "developers confirmed",
    "developer confirmed",
    "devs confirm",
    "devs confirmed",
    "now available",
    "now live",
    "is now live",
    "has launched",
    "official reveal",
    "officially revealed",
]

# These phrases identify confirmed information in a description.
CONFIRMED_DESCRIPTION_TERMS = [
    "the developers confirmed",
    "the developer confirmed",
    "activision confirmed",
    "infinity ward confirmed",
    "officially confirmed",
    "official announcement",
    "has been officially announced",
    "was officially announced",
    "the official patch notes",
    "according to the official patch notes",
]

# A speculative report needs a meaningful subject and uncertainty wording.
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
    "ranked",
    "dmz",
    "content",
    "feature",
    "features",
    "mode",
    "modes",
]

SPECULATION_TERMS = [
    "early",
    "expected",
    "expect",
    "possible",
    "possibly",
    "potential",
    "potentially",
    "may",
    "might",
    "could",
    "reportedly",
    "allegedly",
    "rumoured",
    "rumored",
    "according to",
    "sources say",
    "sources claim",
    "sources suggest",
    "reports suggest",
    "report claims",
    "report says",
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
    Try to follow Google News redirects so the RSS item links
    directly to the original publisher's article.
    If that fails, keep the supplied link.
    """
    if not url or "news.google.com/rss/articles/" not in url:
        return url

    try:
        request = urllib.request.Request(
            url,
            headers={"User-Agent": USER_AGENT},
        )

        with urllib.request.urlopen(request, timeout=15) as response:
            final_url = response.geturl()

        if final_url and "news.google.com" not in final_url:
            return final_url

    except Exception:
        pass

    return url


def is_mw4_article(searchable):
    return contains_any(searchable, MW4_TERMS)


def is_confirmed_or_ordinary_news(title, description):
    """
    Reject known issues, patch notes, guides and clear official
    announcements before considering an article a rumour.
    """
    title_text = normalise(title)
    description_text = normalise(description)

    if contains_any(title_text, REJECTION_TERMS):
        return "known issues, guide, patch notes or rejected wording"

    if contains_any(title_text, CONFIRMED_TERMS):
        return "confirmed or official announcement wording"

    if contains_any(description_text, CONFIRMED_DESCRIPTION_TERMS):
        return "description indicates an official confirmation"

    # Headlines containing these verbs are not automatically rumours.
    # They must also contain explicit uncertainty wording to qualify.
    official_verbs = [
        "activision reveals",
        "activision revealed",
        "infinity ward reveals",
        "infinity ward revealed",
        "developers reveal",
        "developer reveals",
        "devs reveal",
        "officially reveals",
        "officially revealed",
    ]

    if contains_any(title_text, official_verbs):
        return "official reveal wording"

    return None


def identify_rumour(title, description):
    """
    Be deliberately strict:
    - Explicit leak/datamine wording in the headline can qualify.
    - Explicit rumour/unconfirmed wording in the headline can qualify.
    - A speculative report needs uncertainty wording and a relevant subject.
    - Questions alone are never enough.
    """
    title_text = normalise(title)
    description_text = normalise(description)

    if contains_any(title_text, EXPLICIT_LEAK_TERMS):
        return "LEAK"

    if contains_any(title_text, EXPLICIT_RUMOUR_TERMS):
        return "RUMOUR"

    # A generic question is not evidence of a rumour.
    if "?" in title_text:
        return None

    # A report must have a relevant MW4 subject and clear uncertainty.
    if contains_any(title_text, ["report", "reports"]):
        if contains_any(title_text, REPORT_SUBJECTS):
            if contains_any(title_text, SPECULATION_TERMS):
                return "RUMOUR"

            # "Early December reports", for example.
            if re.search(r"\b(early|late)\s+[a-z]+\s+reports?\b", title_text):
                return "RUMOUR"

    # Some headlines use "expected" or "potential" without saying report.
    if contains_any(title_text, SPECULATION_TERMS):
        if contains_any(title_text, REPORT_SUBJECTS):
            return "RUMOUR"

    return None


def get_original_source(entry, fallback):
    source_info = entry.get("source", {})

    if isinstance(source_info, dict):
        source_title = source_info.get("title")

        if source_title:
            return clean_text(source_title)

    return fallback


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
            published = get_entry_date(entry)

            searchable = normalise(title + " " + description)

            # The feed is limited to the last 14 days.
            # Undated entries cannot be reliably checked, so reject them.
            if not published:
                stats["rejected"] += 1
                continue

            if published < cutoff:
                stats["rejected"] += 1
                continue

            stats["recent"] += 1

            if not is_mw4_article(searchable):
                stats["rejected"] += 1
                continue

            stats["mw4"] += 1

            print()
            print("MW4 ARTICLE:", title)

            rejection_reason = is_confirmed_or_ordinary_news(
                title,
                description,
            )

            if rejection_reason:
                print("REJECTED:", rejection_reason)
                stats["rejected"] += 1
                continue

            category = identify_rumour(title, description)

            if not category:
                print("REJECTED: no clear evidence of a rumour or leak")
                stats["rejected"] += 1
                continue

            original_source = get_original_source(
                entry,
                source_name,
            )

            original_link = resolve_article_link(url)

            article = {
                "title": title,
                "description": description,
                "link": original_link,
                "published": published,
                "source": original_source,
                "category": category,
            }

            articles.append(article)
            stats["rumour"] += 1
            stats["accepted"] += 1

            print("ACCEPTED:", category)
            print("SOURCE:", original_source)
            print("LINK:", original_link)

        print()
        print("SOURCE RESULTS:")
        print("RECENT:", stats["recent"])
        print("MW4:", stats["mw4"])
        print("RUMOUR:", stats["rumour"])
        print("ACCEPTED:", stats["accepted"])
        print("REJECTED:", stats["rejected"])

    # Remove duplicate articles that appeared in multiple searches.
    unique_articles = {}

    for article in articles:
        link = article["link"]

        if link not in unique_articles:
            unique_articles[link] = article

    articles = list(unique_articles.values())

    articles.sort(
        key=lambda article: article["published"],
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
        "Posts are speculative reports, leaks or datamines, "
        "not confirmed announcements."
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
            "UNCONFIRMED - This is a speculative report, rumour "
            "or leak and has not been independently verified. "
            "It is not an official confirmation.\n\n"
            f"Original source: {article['source']}\n\n"
            f"{article['description']}"
        )

        ET.SubElement(item, "description").text = description

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
    print("Only clearly speculative reports, leaks and datamines qualify.")
    print("Confirmed announcements, guides and updates are excluded.")
    print("All accepted posts will be labelled UNCONFIRMED.")

    articles = read_sources()
    create_rss(articles)


if __name__ == "__main__":
    main()
