
import calendar
import datetime
import email.utils
import html
import json
import re
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from html.parser import HTMLParser

import feedparser


DAYS_BACK = 14
MAX_ARTICLES = 60
OUTPUT_FILE = "rss.xml"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0 Safari/537.36"
)

RSS_SOURCES = {
    "Dexerto": "https://www.dexerto.com/feed/",
    "GamesRadar+": "https://www.gamesradar.com/feeds.xml",
    "Eurogamer": "https://www.eurogamer.net/feed",
    "VGC": "https://www.videogameschronicle.com/feed/",
    "Insider Gaming": "https://insider-gaming.com/feed/",
}

COD_PAGES = {
    "Official Call of Duty": "https://www.callofduty.com/blog",
    "Dexerto": "https://www.dexerto.com/call-of-duty/",
    "GamesRadar+": "https://www.gamesradar.com/games/fps/call-of-duty/",
    "Insider Gaming MW4": (
        "https://insider-gaming.com/games/call-of-duty-modern-warfare-4/"
    ),
}

# Important COD articles to check directly.
PRIORITY_ARTICLES = {
    "Insider Gaming": [
        (
            "https://insider-gaming.com/"
            "modern-warfare-4-ranked-mode-coming-in-season-2/"
        ),
    ],
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
    "mwii",
    "mw3",
    "mw2",
    "black ops 7",
    "black ops 6",
]

EXCLUDED_TERMS = [
    "rumour",
    "rumor",
    "rumoured",
    "rumored",
    "leak",
    "leaked",
    "leaker",
    "unconfirmed",
    "unverified",
    "supposedly",
    "allegedly",
    "reportedly",
    "speculation",
    "speculated",
    "lays off",
    "laid off",
    "layoffs",
    "layoff",
    "job cuts",
    "staff cuts",
    "restructuring",
    "hiring",
    "job opening",
    "bomb scare",
    "bomb threat",
    "airport evacuated",
    "airport evacuation",
    "plane evacuated",
    "terminal evacuated",
    "police investigation",
    "criminal investigation",
    "medieval",
    "prototype",
    "historical experiment",
    "scrapped project",
    "cancelled project",
    "canceled project",
]

HISTORICAL_SPECULATION_PATTERNS = [
    r"\b(might|could|would)\s+have\b.*\b(experiment|prototype|concept)\b",
    r"\b(if|had)\b.*\b(experiment|prototype|concept)\b.*\b(panned out|worked out|gone ahead)\b",
    r"\b(experiment|prototype|concept)\b.*\b(panned out|worked out|never happened|scrapped)\b",
    r"\bwhat if\b.*\b(call of duty|modern warfare|black ops|warzone)\b",
]

CATEGORY_TITLES = [
    "call of duty series news",
    "call of duty news, reviews and guides",
    "news, reviews and guides for games",
    "call of duty |",
]

EXCLUDED_URL_PARTS = [
    "/tag/",
    "/author/",
    "/category/",
    "/search/",
    "/page/",
]


def clean_text(value):
    value = html.unescape(str(value or ""))
    value = re.sub(r"<[^>]+>", " ", value)
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def normalise_url(url):
    if not url:
        return ""

    parsed = urllib.parse.urlparse(html.unescape(url.strip()))

    if parsed.scheme not in ("http", "https"):
        return ""

    return parsed._replace(
        fragment="",
        query="",
    ).geturl().rstrip("/")


def fetch_url(url, timeout=20):
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/rss+xml,application/xml,*/*",
        },
    )

    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def contains_cod_term(title):
    title = title.lower()
    return any(term in title for term in COD_TERMS)


def contains_any(text, terms):
    text = text.lower()
    return any(term in text for term in terms)


def is_historical_speculation(title):
    lower_title = clean_text(title).lower()

    for pattern in HISTORICAL_SPECULATION_PATTERNS:
        if re.search(pattern, lower_title):
            return True

    return False


def is_valid_cod_news(title, url=""):
    title = clean_text(title)
    lower_title = title.lower()

    if not title:
        return False

    if not contains_cod_term(title):
        return False

    if contains_any(lower_title, EXCLUDED_TERMS):
        return False

    if is_historical_speculation(title):
        return False

    if any(
        phrase in lower_title
        for phrase in CATEGORY_TITLES
    ):
        return False

    opinion_patterns = [
        r"\bformer\b.*\b(producer|developer|director|boss)\b",
        r"\b(opinion|editorial)\b",
        r"\bwhy i think\b",
        r"\bi believe\b",
    ]

    for pattern in opinion_patterns:
        if re.search(pattern, lower_title):
            return False

    url_lower = url.lower()

    if any(part in url_lower for part in EXCLUDED_URL_PARTS):
        return False

    return True


def is_recent(date_value):
    if not date_value:
        return False

    cutoff = datetime.datetime.now(
        datetime.timezone.utc
    ) - datetime.timedelta(days=DAYS_BACK)

    return date_value >= cutoff


def parse_date(value):
    if not value:
        return None

    if isinstance(value, time.struct_time):
        return datetime.datetime.fromtimestamp(
            calendar.timegm(value),
            datetime.timezone.utc,
        )

    value = str(value).strip()

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
        pass

    try:
        parsed = email.utils.parsedate_to_datetime(value)

        if parsed.tzinfo is None:
            parsed = parsed.replace(
                tzinfo=datetime.timezone.utc
            )

        return parsed.astimezone(datetime.timezone.utc)

    except (ValueError, TypeError, OverflowError):
        return None


class PageParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []
        self.meta = {}
        self.dates = []
        self.json_blocks = []
        self.in_json = False
        self.current_json = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)

        if tag == "a":
            href = attrs.get("href")

            if href:
                self.links.append(href)

        if tag == "meta":
            key = (
                attrs.get("property")
                or attrs.get("name")
                or attrs.get("itemprop")
            )

            value = attrs.get("content")

            if key and value:
                self.meta[key.lower()] = value

        if tag == "time":
            date_value = attrs.get("datetime")

            if date_value:
                self.dates.append(date_value)

        if tag == "script" and (
            attrs.get("type") == "application/ld+json"
        ):
            self.in_json = True
            self.current_json = []

    def handle_data(self, data):
        if self.in_json:
            self.current_json.append(data)

    def handle_endtag(self, tag):
        if tag == "script" and self.in_json:
            self.json_blocks.append(
                "".join(self.current_json)
            )
            self.in_json = False
            self.current_json = []


def extract_json_dates(data):
    found = []

    if isinstance(data, dict):
        for key, value in data.items():
            if key in (
                "datePublished",
                "dateCreated",
                "dateModified",
            ):
                if isinstance(value, str):
                    found.append(value)

            found.extend(extract_json_dates(value))

    elif isinstance(data, list):
        for item in data:
            found.extend(extract_json_dates(item))

    return found


def get_page_details(url):
    try:
        raw = fetch_url(url)
        page = raw.decode("utf-8", errors="replace")

        parser = PageParser()
        parser.feed(page)

        title = (
            parser.meta.get("og:title")
            or parser.meta.get("twitter:title")
            or ""
        )

        description = (
            parser.meta.get("og:description")
            or parser.meta.get("description")
            or ""
        )

        date_values = list(parser.dates)

        for key in (
            "article:published_time",
            "datepublished",
            "date",
            "pubdate",
            "datecreated",
        ):
            if parser.meta.get(key):
                date_values.append(parser.meta[key])

        for block in parser.json_blocks:
            try:
                data = json.loads(block)
                date_values.extend(
                    extract_json_dates(data)
                )
            except (json.JSONDecodeError, TypeError):
                continue

        article_date = None

        for value in date_values:
            parsed = parse_date(value)

            if parsed:
                article_date = parsed
                break

        if not title:
            match = re.search(
                r"<title[^>]*>(.*?)</title>",
                page,
                flags=re.IGNORECASE | re.DOTALL,
            )

            if match:
                title = clean_text(match.group(1))

        return {
            "title": clean_text(title),
            "description": clean_text(description),
            "date": article_date,
        }

    except Exception as error:
        print(f"Could not read article page: {url}")
        print(f"Reason: {error}")
        return None


def is_article_url(source, url):
    parsed = urllib.parse.urlparse(url)
    path = parsed.path.lower().strip("/")
    parts = [part for part in path.split("/") if part]

    if any(
        part in parsed.path.lower()
        for part in EXCLUDED_URL_PARTS
    ):
        return False

    if source == "Official Call of Duty":
        return (
            re.search(r"/(blog|patchnotes)/\d{4}/\d{2}/", parsed.path)
            is not None
        )

    if source == "Dexerto":
        return (
            len(parts) >= 2
            and parts[0] == "call-of-duty"
            and re.search(r"-\d{5,}$", parts[-1]) is not None
        )

    if source == "GamesRadar+":
        try:
            index = parts.index("call-of-duty")
        except ValueError:
            return False

        return len(parts) > index + 1

    if source == "Insider Gaming MW4":
        return (
            parsed.netloc.lower().endswith("insider-gaming.com")
            and len(parts) == 1
            and "-" in parts[0]
        )

    return False


def add_article(
    articles,
    title,
    url,
    source,
    date_value,
    description="",
):
    title = clean_text(title)
    url = normalise_url(url)

    if not url or not title:
        return

    if not is_valid_cod_news(title, url):
        return

    if not date_value or not is_recent(date_value):
        return

    articles[url] = {
        "title": title,
        "url": url,
        "source": source,
        "date": date_value,
        "description": clean_text(description),
    }


def read_rss_sources(articles):
    for source, feed_url in RSS_SOURCES.items():
        print()
        print(f"SOURCE: {source}")
        print(f"URL: {feed_url}")

        try:
            feed_data = fetch_url(feed_url)
            feed = feedparser.parse(feed_data)

            print(f"Articles received: {len(feed.entries)}")

            accepted_before = len(articles)

            for entry in feed.entries:
                title = clean_text(entry.get("title", ""))
                url = entry.get("link", "")

                date_value = None

                if entry.get("published_parsed"):
                    date_value = parse_date(
                        entry.published_parsed
                    )
                elif entry.get("updated_parsed"):
                    date_value = parse_date(
                        entry.updated_parsed
                    )
                else:
                    date_value = parse_date(
                        entry.get("published")
                        or entry.get("updated")
                    )

                description = entry.get(
                    "summary",
                    entry.get("description", ""),
                )

                add_article(
                    articles,
                    title,
                    url,
                    source,
                    date_value,
                    description,
                )

            print(
                "COD articles accepted: "
                f"{len(articles) - accepted_before}"
            )

        except Exception as error:
            print(f"Source could not be read: {error}")


def read_cod_pages(articles):
    for source, page_url in COD_PAGES.items():
        print()
        print(f"COD PAGE: {source}")
        print(f"URL: {page_url}")

        try:
            raw = fetch_url(page_url)
            page = raw.decode("utf-8", errors="replace")

            parser = PageParser()
            parser.feed(page)

            accepted_before = len(articles)
            checked = set()
            article_links = []

            for link in parser.links:
                full_url = normalise_url(
                    urllib.parse.urljoin(page_url, link)
                )

                if not full_url or full_url in checked:
                    continue

                checked.add(full_url)

                if not is_article_url(source, full_url):
                    continue

                article_links.append(full_url)

            print(
                f"Possible article links found: {len(article_links)}"
            )

            for article_url in article_links[:100]:
                details = get_page_details(article_url)

                if not details:
                    continue

                add_article(
                    articles,
                    details["title"],
                    article_url,
                    source,
                    details["date"],
                    details["description"],
                )

                time.sleep(0.1)

            print(
                "COD articles accepted: "
                f"{len(articles) - accepted_before}"
            )

        except Exception as error:
            print(f"COD page could not be read: {error}")


def read_priority_articles(articles):
    print()
    print("CHECKING PRIORITY COD ARTICLES")

    for source, article_urls in PRIORITY_ARTICLES.items():
        for article_url in article_urls:
            print()
            print(f"PRIORITY ARTICLE: {source}")
            print(f"URL: {article_url}")

            details = get_page_details(article_url)

            if not details:
                print("Could not retrieve priority article.")
                continue

            accepted_before = len(articles)

            add_article(
                articles,
                details["title"],
                article_url,
                source,
                details["date"],
                details["description"],
            )

            if len(articles) > accepted_before:
                print(f"ACCEPTED: {details['title']}")
            elif normalise_url(article_url) in articles:
                print("Already collected.")
            else:
                print(
                    "Not added. It may be outside the date window "
                    "or may not pass the COD news filter."
                )


def create_rss(articles):
    root = ET.Element(
        "rss",
        {
            "version": "2.0",
            "xmlns:content": (
                "http://purl.org/rss/1.0/modules/content/"
            ),
        },
    )

    channel = ET.SubElement(root, "channel")

    ET.SubElement(channel, "title").text = (
        "Rage Therapy - COD News"
    )

    ET.SubElement(channel, "link").text = (
        "https://github.com/RageTherapy1010/cod-news-feed"
    )

    ET.SubElement(channel, "description").text = (
        "Recent Call of Duty news, updates, guides and tips."
    )

    ET.SubElement(channel, "language").text = "en"

    # One priority reannouncement for Ranked Play.
    # Its unique GUID stays the same on every build.
    ranked_url = (
        "https://insider-gaming.com/"
        "modern-warfare-4-ranked-mode-coming-in-season-2"
    )

    priority_article = {
        "title": (
            "[RANKED PLAY UPDATE] "
            "Modern Warfare 4 Ranked Mode Coming in Season 2"
        ),
        "url": ranked_url,
        "guid": ranked_url + "#rage-therapy-ranked-priority",
        "source": "Rage Therapy Priority Update",
        "date": datetime.datetime.now(datetime.timezone.utc),
        "description": (
            "Priority reannouncement for Ranked Play. "
            "Originally published by Insider Gaming on "
            "11 November 2026. "
            "Original source: " + ranked_url
        ),
    }

    all_articles = list(articles.values()) + [priority_article]

    sorted_articles = sorted(
        all_articles,
        key=lambda item: item["date"],
        reverse=True,
    )[:MAX_ARTICLES]

    for article in sorted_articles:
        item = ET.SubElement(channel, "item")

        ET.SubElement(item, "title").text = (
            article["title"]
        )

        ET.SubElement(item, "link").text = (
            article["url"]
        )

        ET.SubElement(item, "guid").text = (
            article.get("guid", article["url"])
        )

        ET.SubElement(item, "pubDate").text = (
            email.utils.format_datetime(article["date"])
        )

        ET.SubElement(item, "source").text = (
            article["source"]
        )

        if article["description"]:
            ET.SubElement(item, "description").text = (
                article["description"]
            )

    tree = ET.ElementTree(root)
    ET.indent(tree, space="  ")

    tree.write(
        OUTPUT_FILE,
        encoding="utf-8",
        xml_declaration=True,
    )

    print()
    print(f"TOTAL COD ARTICLES: {len(sorted_articles)}")
    print("RSS feed successfully generated.")

    print()
    print("FINAL ARTICLE LIST:")

    for article in sorted_articles:
        print(
            article["date"].strftime("%Y-%m-%d"),
            "|",
            article["source"],
            "|",
            article["title"],
        )


def main():
    print("Starting COD news feed build...")
    print("COD news and guide filtering is enabled.")
    print(
        "Rumours, leaks, employment stories, unrelated incidents "
        "and historical speculation are excluded."
    )
    print(
        "News, updates, patch notes, guides and tips are included."
    )
    print(
        "Insider Gaming MW4 page and priority Ranked article checks "
        "are enabled."
    )
    print("Ranked Play priority reannouncement is enabled.")
    print(f"Only articles from the last {DAYS_BACK} days are included.")

    articles = {}

    read_rss_sources(articles)
    read_cod_pages(articles)
    read_priority_articles(articles)
    create_rss(articles)


if __name__ == "__main__":
    main()
