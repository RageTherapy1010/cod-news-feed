
import calendar
import datetime
import email.utils
import html
import json
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from html.parser import HTMLParser

import feedparser


# ==================================================
# SETTINGS
# ==================================================

DAYS_BACK = 14
MAX_ARTICLES = 60
MAX_PAGE_ARTICLES = 15

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 Chrome/120.0 Safari/537.36"
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
    "GamesRadar+": (
        "https://www.gamesradar.com/games/fps/call-of-duty/"
    ),
}

# Specific COD names and titles.
# We deliberately do not accept vague terms like
# "DMZ" or "Zombies" on their own.

COD_TITLE_TERMS = [
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

# Exclude unconfirmed information and leaks.
EXCLUDED_TERMS = [
    "rumour",
    "rumor",
    "rumoured",
    "rumored",
    "leak",
    "leaked",
    "leaks",
    "datamine",
    "datamined",
    "unconfirmed",
    "unverified",
    "supposedly",
    "allegedly",
    "reportedly",
    "rumored to",
    "rumoured to",
]

# Exclude general industry/personnel stories.
EXCLUDED_INDUSTRY_TERMS = [
    "laid off",
    "layoffs",
    "layoff",
    "job cuts",
    "jobs cut",
    "hiring",
    "hired",
    "hire",
    "restructuring",
    "former boss",
    "former producer",
    "former developer",
    "former director",
]

# Exclude hypothetical or speculative headlines.
EXCLUDED_SPECULATION_TERMS = [
    "might have",
    "could have",
    "would have",
    "what if",
    "if an experiment",
]


# ==================================================
# HTML PARSERS
# ==================================================

class LinkParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []
        self.current = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)

        if tag == "a" and attrs.get("href"):
            self.current = {
                "url": attrs["href"],
                "title": "",
            }

    def handle_data(self, data):
        if self.current is not None:
            self.current["title"] += data + " "

    def handle_endtag(self, tag):
        if tag == "a" and self.current is not None:
            title = clean_text(self.current["title"])

            if title:
                self.links.append({
                    "url": self.current["url"],
                    "title": title,
                })

            self.current = None


class MetadataParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.metadata = {}

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)

        if tag == "meta":
            key = (
                attrs.get("property")
                or attrs.get("name")
                or ""
            ).lower()

            value = attrs.get("content", "")

            if key and value:
                self.metadata[key] = value

        if tag == "time" and attrs.get("datetime"):
            self.metadata.setdefault(
                "time",
                attrs["datetime"]
            )


# ==================================================
# GENERAL HELPERS
# ==================================================

def clean_text(value):
    value = html.unescape(str(value or ""))
    value = re.sub(r"<[^>]+>", " ", value)
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def fetch_url(url):
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": (
                "text/html,application/rss+xml,"
                "application/xml;q=0.9,*/*;q=0.8"
            ),
        },
    )

    with urllib.request.urlopen(request, timeout=25) as response:
        return response.read()


def parse_date(value):
    if not value:
        return None

    try:
        parsed = email.utils.parsedate_to_datetime(value)

        if parsed.tzinfo is None:
            parsed = parsed.replace(
                tzinfo=datetime.timezone.utc
            )

        return parsed.astimezone(datetime.timezone.utc)

    except Exception:
        pass

    try:
        parsed = datetime.datetime.fromisoformat(
            str(value).replace("Z", "+00:00")
        )

        if parsed.tzinfo is None:
            parsed = parsed.replace(
                tzinfo=datetime.timezone.utc
            )

        return parsed.astimezone(datetime.timezone.utc)

    except Exception:
        return None


def feedparser_date(entry):
    for key in ("published_parsed", "updated_parsed"):
        value = entry.get(key)

        if value:
            try:
                timestamp = calendar.timegm(value)
                return datetime.datetime.fromtimestamp(
                    timestamp,
                    datetime.timezone.utc
                )
            except Exception:
                pass

    return parse_date(
        entry.get("published") or entry.get("updated")
    )


def is_recent(published):
    if not published:
        return False

    now = datetime.datetime.now(datetime.timezone.utc)
    cutoff = now - datetime.timedelta(days=DAYS_BACK)

    return cutoff <= published <= (
        now + datetime.timedelta(days=1)
    )


def is_cod_title(title):
    title = clean_text(title).lower()

    return any(
        term in title
        for term in COD_TITLE_TERMS
    )


def is_excluded(title):
    title = clean_text(title).lower()

    excluded = (
        EXCLUDED_TERMS
        + EXCLUDED_INDUSTRY_TERMS
        + EXCLUDED_SPECULATION_TERMS
    )

    return any(term in title for term in excluded)


def clean_link(url):
    parsed = urllib.parse.urlsplit(url)

    return urllib.parse.urlunsplit((
        parsed.scheme,
        parsed.netloc,
        parsed.path,
        "",
        "",
    ))


def make_article(title, link, description, published, source):
    title = clean_text(title)
    description = clean_text(description)

    if not title or not link or not published:
        return None

    # Only COD-specific headlines are accepted.
    if not is_cod_title(title):
        return None

    if is_excluded(title):
        return None

    if not is_recent(published):
        return None

    return {
        "title": title,
        "link": clean_link(link),
        "description": description,
        "published": published,
        "source": source,
    }


# ==================================================
# RSS FEEDS
# ==================================================

def read_rss_source(source, url):
    articles = []

    print("\nSOURCE:", source)
    print("URL:", url)

    try:
        content = fetch_url(url)
        feed = feedparser.parse(content)

        print("Articles received:", len(feed.entries))

        for entry in feed.entries:
            title = entry.get("title", "")
            link = entry.get("link", "")
            description = entry.get("summary", "")

            published = feedparser_date(entry)

            article = make_article(
                title,
                link,
                description,
                published,
                source,
            )

            if article:
                articles.append(article)

    except Exception as error:
        print("SOURCE ERROR:", source, error)

    print("COD articles accepted:", len(articles))

    return articles


# ==================================================
# JSON-LD PUBLICATION DATE EXTRACTION
# ==================================================

def find_json_dates(data):
    dates = []

    if isinstance(data, dict):
        for key, value in data.items():
            if key.lower() in (
                "datepublished",
                "datecreated",
            ):
                parsed = parse_date(value)

                if parsed:
                    dates.append(parsed)

            elif isinstance(value, (dict, list)):
                dates.extend(find_json_dates(value))

    elif isinstance(data, list):
        for item in data:
            dates.extend(find_json_dates(item))

    return dates


def get_jsonld_dates(page_html):
    dates = []

    scripts = re.findall(
        r'<script[^>]*type=["\']application/ld\+json'
        r'["\'][^>]*>(.*?)</script>',
        page_html,
        flags=re.IGNORECASE | re.DOTALL,
    )

    for script in scripts:
        try:
            data = json.loads(script.strip())
            dates.extend(find_json_dates(data))
        except Exception:
            continue

    return dates


def get_article_metadata(page_html):
    parser = MetadataParser()
    parser.feed(page_html)

    metadata = parser.metadata

    title = (
        metadata.get("og:title")
        or metadata.get("twitter:title")
        or metadata.get("title")
        or ""
    )

    description = (
        metadata.get("og:description")
        or metadata.get("description")
        or ""
    )

    date_value = (
        metadata.get("article:published_time")
        or metadata.get("datepublished")
        or metadata.get("date")
        or metadata.get("time")
    )

    published = parse_date(date_value)

    if not published:
        json_dates = get_jsonld_dates(page_html)

        if json_dates:
            published = max(json_dates)

    return title, description, published


# ==================================================
# COD-SPECIFIC WEBSITE PAGES
# ==================================================

def read_cod_page(source, page_url):
    articles = []

    print("\nCOD PAGE:", source)
    print("URL:", page_url)

    try:
        page_html = fetch_url(page_url).decode(
            "utf-8",
            errors="replace",
        )

        parser = LinkParser()
        parser.feed(page_html)

        page_host = urllib.parse.urlparse(
            page_url
        ).netloc.lower()

        candidates = []
        seen = set()

        for item in parser.links:
            link = urllib.parse.urljoin(
                page_url,
                item["url"],
            )

            parsed = urllib.parse.urlparse(link)
            host = parsed.netloc.lower()

            if host != page_host:
                continue

            if not is_cod_title(item["title"]):
                continue

            # Avoid the category page itself.
            if clean_link(link) == clean_link(page_url):
                continue

            link = clean_link(link)

            if link in seen:
                continue

            seen.add(link)

            candidates.append({
                "title": item["title"],
                "link": link,
            })

        print("COD article links found:", len(candidates))

        for item in candidates[:MAX_PAGE_ARTICLES]:
            try:
                article_html = fetch_url(
                    item["link"]
                ).decode(
                    "utf-8",
                    errors="replace",
                )

                title, description, published = (
                    get_article_metadata(article_html)
                )

                # Use the page link's title if metadata
                # does not provide an article headline.
                if not title:
                    title = item["title"]

                article = make_article(
                    title,
                    item["link"],
                    description,
                    published,
                    source,
                )

                if article:
                    articles.append(article)

            except Exception as error:
                print(
                    "ARTICLE ERROR:",
                    item["link"],
                    error,
                )

    except Exception as error:
        print("PAGE ERROR:", source, error)

    print("COD articles accepted:", len(articles))

    return articles


# ==================================================
# BUILD RSS FILE
# ==================================================

def build_feed():
    all_articles = []

    print("Starting COD news feed build...")
    print("Strict COD headline filtering is enabled.")
    print("Rumours, leaks and industry-only stories are excluded.")

    # Read RSS feeds.
    for source, url in RSS_SOURCES.items():
        all_articles.extend(
            read_rss_source(source, url)
        )

    # Read COD-specific pages.
    for source, url in COD_PAGES.items():
        all_articles.extend(
            read_cod_page(source, url)
        )

    # Deduplicate articles.
    unique_articles = {}

    for article in all_articles:
        unique_articles[article["link"]] = article

    articles = list(unique_articles.values())

    # Newest articles first.
    articles.sort(
        key=lambda article: article["published"],
        reverse=True,
    )

    articles = articles[:MAX_ARTICLES]

    # Create RSS document.
    rss = ET.Element("rss", version="2.0")
    channel = ET.SubElement(rss, "channel")

    ET.SubElement(
        channel,
        "title",
    ).text = "Rage Therapy - Call of Duty News"

    ET.SubElement(
        channel,
        "link",
    ).text = (
        "https://github.com/RageTherapy1010/cod-news-feed"
    )

    ET.SubElement(
        channel,
        "description",
    ).text = (
        "Recent Call of Duty news from official "
        "and reputable gaming sources."
    )

    ET.SubElement(
        channel,
        "language",
    ).text = "en"

    for article in articles:
        item = ET.SubElement(channel, "item")

        ET.SubElement(
            item,
            "title",
        ).text = article["title"]

        ET.SubElement(
            item,
            "link",
        ).text = article["link"]

        ET.SubElement(
            item,
            "guid",
        ).text = article["link"]

        ET.SubElement(
            item,
            "description",
        ).text = (
            article["description"]
            + " | Source: "
            + article["source"]
        )

        ET.SubElement(
            item,
            "pubDate",
        ).text = email.utils.format_datetime(
            article["published"]
        )

    tree = ET.ElementTree(rss)
    ET.indent(tree, space="  ")

    tree.write(
        "rss.xml",
        encoding="utf-8",
        xml_declaration=True,
    )

    print("\n--------------------------------")
    print("TOTAL COD ARTICLES:", len(articles))
    print("RSS feed successfully generated.")
    print("--------------------------------")

    for article in articles:
        print(
            article["published"].strftime("%Y-%m-%d"),
            "|",
            article["source"],
            "|",
            article["title"],
        )


if __name__ == "__main__":
    build_feed()
