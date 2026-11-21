
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

LEAK_TERMS = [
    "leak",
    "leaked",
    "leaker",
    "leaks",
    "datamine",
    "datamined",
]

RUMOUR_TITLE_TERMS = [
    "rumour",
    "rumours",
    "rumor",
    "rumors",
    "speculation",
    "speculative",
    "unconfirmed",
    "unverified",
    "allegedly",
    "reportedly",
]

REJECTION_TERMS = [
    "debunked",
    "fake leak",
    "fake rumour",
    "fake rumor",
    "false leak",
]

# These phrases indicate ordinary confirmed coverage.
# They are checked in the headline so a genuine rumour article
# is not rejected just because it mentions patch notes in its description.
CONFIRMED_TITLE_TERMS = [
    "patch notes",
    "patch update",
    "official patch",
    "hotfix",
    "known issues",
    "official update",
    "officially announced",
    "official announcement",
    "is now live",
    "are now live",
    "now available",
]

# A report must concern an actual MW4 subject.
REPORT_SUBJECTS = [
    "release date",
    "release window",
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
    "sbmm",
    "ranked",
    "ranked play",
    "zombies",
    "campaign",
    "aim assist",
    "movement",
    "omnimovement",
    "battle royale",
]

# These words can support a future-content rumour, but they
# are never enough on their own.
FUTURE_CONTENT_TERMS = [
    "early",
    "late",
    "expected",
    "possible",
    "potential",
    "may",
    "might",
    "could",
    "planned",
    "coming",
    "upcoming",
    "december",
    "january",
    "february",
    "march",
    "april",
    "may",
    "june",
    "july",
    "august",
    "september",
    "october",
    "november",
]

# Supporting reporting language for speculative future content.
# A named leaker is not required, but there must be some indication
# that the article is discussing a report or unconfirmed information.
REPORTING_EVIDENCE_TERMS = [
    "report",
    "reports",
    "reportedly",
    "according to",
    "sources say",
    "sources suggest",
    "sources claim",
    "unconfirmed",
    "rumour",
    "rumor",
    "insider",
    "leaker",
    "leak",
    "datamine",
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


def identify_rumour(title, searchable):
    """
    Decide whether an article is a genuine MW4 rumour or leak.

    LEAK:
        The headline clearly identifies a leak or datamine.

    RUMOUR:
        The headline clearly identifies a rumour or unconfirmed claim;
        OR it identifies a report about a relevant MW4 subject;
        OR it describes future content and has supporting reporting
        language.

    Ordinary confirmed updates, guides and patch-note coverage
    are not accepted just because their descriptions contain words
    such as could, might or possible.
    """

    title = normalise(title)
    searchable = normalise(searchable)

    # Reject headlines that clearly describe confirmed update coverage.
    if contains_any(title, CONFIRMED_TITLE_TERMS):
        return None

    # Reject headlines explicitly describing something as fake or debunked.
    if contains_any(searchable, REJECTION_TERMS):
        return None

    # A clear leak or datamine in the headline is a LEAK.
    if contains_any(title, LEAK_TERMS):
        return "LEAK"

    # A clear rumour or unconfirmed claim in the headline is a RUMOUR.
    if contains_any(title, RUMOUR_TITLE_TERMS):
        return "RUMOUR"

    # A report headline must also mention a relevant MW4 subject.
    # This keeps the Dexerto SBMM/DMZ report.
    has_report_headline = bool(
        re.search(r"\b(report|reports|reportedly)\b", title)
    )

    has_relevant_subject = contains_any(
        title + " " + searchable,
        REPORT_SUBJECTS,
    )

    if has_report_headline and has_relevant_subject:
        return "RUMOUR"

    # Future-content speculation can be included even without a
    # named leaker, but it needs a relevant subject in the headline,
    # a future-content signal in the headline, and reporting evidence.
    has_future_headline = contains_any(
        title,
        FUTURE_CONTENT_TERMS,
    )

    has_subject_in_title = contains_any(
        title,
        REPORT_SUBJECTS,
    )

    has_reporting_evidence = contains_any(
        searchable,
        REPORTING_EVIDENCE_TERMS,
    )

    if (
        has_future_headline
        and has_subject_in_title
        and has_reporting_evidence
    ):
        return "RUMOUR"

    # A speculative question alone is not enough.
    # Ordinary gameplay articles and guides are rejected.
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

            searchable = normalise(
                title + " " + description
            )

            published = get_entry_date(entry)

            # Ignore articles older than the collection window.
            if published and published < cutoff:
                stats["rejected"] += 1
                continue

            stats["recent"] += 1

            # Only Modern Warfare 4 content is allowed.
            if not contains_any(searchable, MW4_TERMS):
                stats["rejected"] += 1
                continue

            stats["mw4"] += 1

            print()
            print("MW4 ARTICLE:", title)

            # Reject debunked or fake reports.
            if contains_any(searchable, REJECTION_TERMS):
                print("REJECTED: possible debunk or fake report")
                stats["rejected"] += 1
                continue

            category = identify_rumour(
                title,
                searchable,
            )

            if not category:
                print(
                    "REJECTED: no clear rumour, leak "
                    "or qualifying report"
                )
                stats["rejected"] += 1
                continue

            # Keep the original publisher attribution when Google News
            # supplies it. Otherwise retain the feed source name.
            original_source = source_name

            entry_source = entry.get("source", {})

            if entry_source and entry_source.get("title"):
                original_source = clean_text(
                    entry_source.get("title")
                )

            article = {
                "title": title,
                "description": description,
                "link": url,
                "published": published,
                "source": original_source,
                "category": category,
            }

            articles.append(article)

            stats["accepted"] += 1

            print("ACCEPTED:", category)
            print("SOURCE:", original_source)
            print("LINK:", url)

        print()
        print("SOURCE RESULTS:")
        print("RECENT:", stats["recent"])
        print("MW4:", stats["mw4"])
        print("ACCEPTED:", stats["accepted"])
        print("REJECTED:", stats["rejected"])

    # Remove duplicate articles while preserving their original links.
    unique_articles = {}

    for article in articles:
        unique_articles[article["link"]] = article

    articles = list(unique_articles.values())

    # Newest articles first.
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
    print("Actual leaks and datamines are labelled LEAK.")
    print("Speculative reports are labelled RUMOUR.")
    print("Ordinary confirmed news, guides and updates are excluded.")
    print("Unverified claims will be labelled.")

    articles = read_sources()

    create_rss(articles)


if __name__ == "__main__":
    main()
