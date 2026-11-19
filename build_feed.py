
import calendar
import datetime
import email.utils
import html
import json
import re
import time
import urllib.error
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
}

COD_PAGES = {
    "Official Call of Duty": "https://www.callofduty.com/blog",
    "Dexerto": "https://www.dexerto.com/call-of-duty/",
    "GamesRadar+": "https://www.gamesradar.com/games/fps/call-of-duty/",
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

RUMOUR_TERMS = [
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
    "might be",
    "could be",
    "may be",
    "speculation",
    "speculated",
    "claims without evidence",
]

INDUSTRY_TERMS = [
    "layoff",
    "layoffs",
    "laid off",
    "lays off",
    "job cuts",
    "staff cuts",
    "restructuring",
    "hiring",
    "job opening",
    "former producer",
    "former developer",
    "former director",
    "former boss",
    "former studio head",
    "former call of duty",
    "left the studio",
    "leaves the studio",
    "leaving the studio",
]

INCIDENT_TERMS = [
    "bomb scare",
    "bomb threat",
    "airport evacuated",
    "airport evacuation",
    "plane evacuated",
    "terminal evacuated",
    "police investigation",
    "arrested after",
    "criminal investigation",
    "crime investigation",
    "evacuated after",
]

GUIDE_TERMS = [
    "how to",
    "where to find",
    "where to get",
    "where to unlock",
    "all locations",
    "all locations for",
    "location guide",
    "walkthrough",
    "best loadout",
    "best class setup",
    "how to complete",
    "how to access",
    "where to use",
    "all weapon locations",
    "all key locations",
]

EXCLUDED_URL_PARTS = [
    "/tag/",
    "/author/",
    "/category/",
    "/page/",
    "/search/",
]


def clean_text(value):
    value = html.unescape(str(value or ""))
    value = re.sub(r"<[^>]+>", " ", value)
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def normalise_url(url):
    if not url:
        return ""

    url = html.unescape(url.strip())
    parsed = urllib.parse.urlparse(url)

    if parsed.scheme not in ("http", "https"):
        return ""

    clean = parsed._replace(fragment="", query="")
    return urllib.parse.urlunparse(clean).rstrip("/")


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
    title_lower = title.lower()
    return any(term in title_lower for term in COD_TERMS)


def contains_any(text, terms):
    text = text.lower()
    return any(term in text for term in terms)


def is_valid_cod_news(title, url=""):
    title = clean_text(title)
    lower_title = title.lower()

    if not title or not contains_cod_term(title):
        return False

    if contains_any(lower_title, RUMOUR_TERMS):
        return False

    if contains_any(lower_title, INDUSTRY_TERMS):
        return False

    if contains_any(lower_title, INCIDENT_TERMS):
        return False

    if contains_any(lower_title, GUIDE_TERMS):
        return False

    # Exclude opinion pieces and personal commentary.
    opinion_patterns = [
        r"\bformer\b.*\b(producer|developer|director|boss)\b",
        r"\b(opinion|editorial|my thoughts)\b",
        r"\bwhy i think\b",
        r"\bi believe\b",
    ]

    for pattern in opinion_patterns:
        if re.search(pattern, lower_title):
            return False

    # Avoid category and search pages being treated as articles.
    url_lower = url.lower()

    if any(part in url_lower for part in EXCLUDED_URL_PARTS):
        return False

    return True


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
            parsed = parsed.replace(tzinfo=datetime.timezone.utc)

        return parsed.astimezone(datetime.timezone.utc)

    except (ValueError, TypeError):
        pass

    try:
        parsed = email.utils.parsedate_to_datetime(value)

        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=datetime.timezone.utc)

        return parsed.astimezone(datetime.timezone.utc)

    except (ValueError, TypeError, OverflowError):
        return None


def get_recent_cutoff():
    return datetime.datetime.now(
        datetime.timezone.utc
    ) - datetime.timedelta(days=DAYS_BACK)


def is_recent(date_value):
    if not date_value:
        return False

    return date_value >= get_recent_cutoff()


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
            self.json_blocks.append("".join(self.current_json))
            self.in_json = False
            self.current_json = []


def extract_json_dates(data):
    found = []

    if isinstance(data, dict):
        for key, value in data.items():
            if key in ("datePublished", "dateCreated", "dateModified"):
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
                json_data = json.loads(block)
                date_values.extend(extract_json_dates(json_data))
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


def add_article(articles, title, url, source, date_value, description=""):
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

            received = len(feed.entries)
            accepted_before = len(articles)

            print(f"Articles received: {received}")

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

            accepted = len(articles) - accepted_before
            print(f"COD articles accepted: {accepted}")

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

            base_url = urllib.parse.urlparse(page_url)
            accepted_before = len(articles)
            checked = set()

            print(f"COD article links found: {len(parser.links)}")

            for link in parser.links:
                full_url = urllib.parse.urljoin(page_url, link)
                full_url = normalise_url(full_url)

                if not full_url or full_url in checked:
                    continue

                checked.add(full_url)

                parsed_url = urllib.parse.urlparse(full_url)

                if parsed_url.netloc != base_url.netloc:
                    continue

                if full_url == normalise_url(page_url):
                    continue

                if any(
                    part in parsed_url.path.lower()
                    for part in EXCLUDED_URL_PARTS
                ):
                    continue

                details = get_page_details(full_url)

                if not details:
                    continue

                title = details["title"]
                article_date = details["date"]

                if not title or not article_date:
                    continue

                add_article(
                    articles,
                    title,
                    full_url,
                    source,
                    article_date,
                    details["description"],
                )

                # Avoid making too many requests to one site.
                time.sleep(0.15)

            accepted = len(articles) - accepted_before
            print(f"COD articles accepted: {accepted}")

        except Exception as error:
            print(f"COD page could not be read: {error}")


def create_rss(articles):
    root = ET.Element(
        "rss",
        {
            "version": "2.0",
            "xmlns:content": "http://purl.org/rss/1.0/modules/content/",
        },
    )

    channel = ET.SubElement(root, "channel")

    ET.SubElement(channel, "title").text = "Rage Therapy - COD News"
    ET.SubElement(channel, "link").text = (
        "https://github.com/RageTherapy1010/cod-news-feed"
    )
    ET.SubElement(channel, "description").text = (
        "Recent Call of Duty news, updates and announcements."
    )
    ET.SubElement(channel, "language").text = "en"

    sorted_articles = sorted(
        articles.values(),
        key=lambda item: item["date"],
        reverse=True,
    )[:MAX_ARTICLES]

    for article in sorted_articles:
        item = ET.SubElement(channel, "item")

        ET.SubElement(item, "title").text = article["title"]
        ET.SubElement(item, "link").text = article["url"]
        ET.SubElement(item, "guid").text = article["url"]

        ET.SubElement(item, "pubDate").text = email.utils.format_datetime(
            article["date"]
        )

        ET.SubElement(item, "source").text = article["source"]

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


def main():
    print("Starting COD news feed build...")
    print("Strict COD news filtering is enabled.")
    print("Rumours, leaks, guides, layoffs and unrelated incidents are excluded.")
    print(f"Only articles from the last {DAYS_BACK} days are included.")

    articles = {}

    read_rss_sources(articles)
    read_cod_pages(articles)
    create_rss(articles)


if __name__ == "__main__":
    main()
