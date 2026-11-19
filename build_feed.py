
import calendar
import datetime
import email.utils
import html
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from html.parser import HTMLParser

import feedparser


# --------------------------------------------------
# SETTINGS
# --------------------------------------------------

DAYS_BACK = 14
MAX_ARTICLES = 60
USER_AGENT = "Mozilla/5.0 (compatible; RageTherapyCODNews/1.0)"

# General RSS feeds are filtered so that only COD
# articles can enter the final feed.
RSS_SOURCES = {
    "Dexerto": "https://www.dexerto.com/feed/",
    "GamesRadar+": "https://www.gamesradar.com/feeds.xml",
    "Eurogamer": "https://www.eurogamer.net/feed",
    "VGC": "https://www.videogameschronicle.com/feed/",
}

# These pages contain Call of Duty-specific articles.
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
    "dmz",
    "ricochet anti-cheat",
    "mw4",
    "bo7",
    "blackout",
]

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
]


# --------------------------------------------------
# HTML HELPERS
# --------------------------------------------------

class LinkParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []
        self.current_link = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)

        if tag == "a" and attrs.get("href"):
            self.current_link = {
                "url": attrs["href"],
                "title": "",
            }

        if tag == "br" and self.current_link:
            self.current_link["title"] += " "

    def handle_data(self, data):
        if self.current_link:
            self.current_link["title"] += data

    def handle_endtag(self, tag):
        if tag == "a" and self.current_link:
            title = clean_text(self.current_link["title"])

            if title:
                self.current_link["title"] = title
                self.links.append(self.current_link)

            self.current_link = None


class ArticleMetadataParser(HTMLParser):
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


# --------------------------------------------------
# GENERAL HELPERS
# --------------------------------------------------

def clean_text(value):
    value = html.unescape(str(value or ""))
    value = re.sub(r"<[^>]+>", " ", value)
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def fetch_url(url):
    request = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT}
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
            value.replace("Z", "+00:00")
        )

        if parsed.tzinfo is None:
            parsed = parsed.replace(
                tzinfo=datetime.timezone.utc
            )

        return parsed.astimezone(datetime.timezone.utc)

    except Exception:
        return None


def is_call_of_duty(title, description=""):
    text = (title + " " + description).lower()

    return any(term in text for term in COD_TERMS)


def is_excluded(title, description=""):
    text = (title + " " + description).lower()

    return any(term in text for term in EXCLUDED_TERMS)


def is_recent(published):
    if not published:
        return False

    now = datetime.datetime.now(datetime.timezone.utc)
    cutoff = now - datetime.timedelta(days=DAYS_BACK)

    return cutoff <= published <= now + datetime.timedelta(days=1)


def make_article(title, link, description, published, source):
    title = clean_text(title)
    description = clean_text(description)

    if not title or not link or not published:
        return None

    if not is_recent(published):
        return None

    if not is_call_of_duty(title, description):
        return None

    if is_excluded(title, description):
        return None

    return {
        "title": title,
        "link": link,
        "description": description,
        "published": published,
        "source": source,
    }


# --------------------------------------------------
# RSS SOURCES
# --------------------------------------------------

def read_rss_source(source, url):
    articles = []

    print("\nSOURCE:", source)
    print("URL:", url)

    try:
        content = fetch_url(url)
        feed = feedparser.parse(content)

        print("Articles received:", len(feed.entries))

        for entry in feed.entries:
            title = clean_text(entry.get("title", ""))
            link = entry.get("link", "")

            description = clean_text(
                entry.get("summary", "")
            )

            date_value = (
                entry.get("published")
                or entry.get("updated")
            )

            published = parse_date(date_value)

            article = make_article(
                title,
                link,
                description,
                published,
                source
            )

            if article:
                articles.append(article)

    except Exception as error:
        print("SOURCE ERROR:", source, error)

    print("COD articles accepted:", len(articles))

    return articles


# --------------------------------------------------
# COD-SPECIFIC WEBSITE PAGES
# --------------------------------------------------

def read_cod_page(source, page_url):
    articles = []

    print("\nCOD PAGE:", source)
    print("URL:", page_url)

    try:
        page_content = fetch_url(page_url).decode(
            "utf-8",
            errors="replace"
        )

        parser = LinkParser()
        parser.feed(page_content)

        candidates = []
        seen_links = set()

        for item in parser.links:
            title = item["title"]

            link = urllib.parse.urljoin(
                page_url,
                item["url"]
            )

            if not link.startswith("http"):
                continue

            if link in seen_links:
                continue

            seen_links.add(link)

            if not is_call_of_duty(title):
                continue

            # Only inspect article links from the
            # website being checked.
            if urllib.parse.urlparse(link).netloc != (
                urllib.parse.urlparse(page_url).netloc
            ):
                continue

            candidates.append({
                "title": title,
                "link": link,
            })

        print("COD article links found:", len(candidates))

        # Limit requests so the workflow does not
        # overload the websites.
        for item in candidates[:12]:
            try:
                article_html = fetch_url(
                    item["link"]
                ).decode("utf-8", errors="replace")

                metadata_parser = ArticleMetadataParser()
                metadata_parser.feed(article_html)

                metadata = metadata_parser.metadata

                title = (
                    metadata.get("og:title")
                    or metadata.get("twitter:title")
                    or item["title"]
                )

                description = (
                    metadata.get("og:description")
                    or metadata.get("description")
                    or ""
                )

                date_value = (
                    metadata.get("article:published_time")
                    or metadata.get("date")
                    or metadata.get("time")
                )

                published = parse_date(date_value)

                article = make_article(
                    title,
                    item["link"],
                    description,
                    published,
                    source
                )

                if article:
                    articles.append(article)

            except Exception as error:
                print("ARTICLE ERROR:", item["link"], error)

    except Exception as error:
        print("PAGE ERROR:", source, error)

    print("COD articles accepted:", len(articles))

    return articles


# --------------------------------------------------
# BUILD FINAL RSS FEED
# --------------------------------------------------

def build_feed():
    all_articles = []

    print("Starting COD news feed build...")
    print("Only recent Call of Duty articles are accepted.")

    # Read RSS sources.
    for source, url in RSS_SOURCES.items():
        all_articles.extend(
            read_rss_source(source, url)
        )

    # Read COD-specific pages.
    for source, url in COD_PAGES.items():
        all_articles.extend(
            read_cod_page(source, url)
        )

    # Remove duplicate links.
    unique_articles = {}

    for article in all_articles:
        unique_articles[article["link"]] = article

    articles = list(unique_articles.values())

    # Newest articles first.
    articles.sort(
        key=lambda item: item["published"],
        reverse=True
    )

    articles = articles[:MAX_ARTICLES]

    # Create RSS document.
    rss = ET.Element("rss", version="2.0")
    channel = ET.SubElement(rss, "channel")

    ET.SubElement(
        channel, "title"
    ).text = "Rage Therapy - Call of Duty News"

    ET.SubElement(
        channel, "link"
    ).text = "https://github.com/RageTherapy1010/cod-news-feed"

    ET.SubElement(
        channel, "description"
    ).text = (
        "Recent Call of Duty news from official "
        "and reputable gaming sources."
    )

    ET.SubElement(
        channel, "language"
    ).text = "en"

    for article in articles:
        item = ET.SubElement(channel, "item")

        ET.SubElement(
            item, "title"
        ).text = article["title"]

        ET.SubElement(
            item, "link"
        ).text = article["link"]

        ET.SubElement(
            item, "guid"
        ).text = article["link"]

        ET.SubElement(
            item, "description"
        ).text = (
            article["description"]
            + " | Source: "
            + article["source"]
        )

        ET.SubElement(
            item, "pubDate"
        ).text = email.utils.format_datetime(
            article["published"]
        )

    tree = ET.ElementTree(rss)
    ET.indent(tree, space="  ")

    tree.write(
        "rss.xml",
        encoding="utf-8",
        xml_declaration=True
    )

    print("\n--------------------------------")
    print("TOTAL COD ARTICLES:", len(articles))
    print("RSS feed successfully generated.")
    print("--------------------------------")

    for article in articles[:10]:
        print(
            article["published"].strftime("%Y-%m-%d"),
            "|",
            article["source"],
            "|",
            article["title"]
        )


if __name__ == "__main__":
    build_feed()
