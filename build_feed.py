
import calendar
import datetime
import email.utils
import html
import re
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET

import feedparser

SOURCES = {
    "MP1st": "https://mp1st.com/feed",
    "Insider Gaming": "https://insider-gaming.com/feed/",
}

KEYWORDS = [
    "call of duty",
    "modern warfare",
    "black ops",
    "warzone",
    "cod:",
    "cod ",
    "cod-",
    "zombies",
    "dmz",
    "ricochet",
    "activision",
]

DAYS_BACK = 14
MAX_ITEMS = 50

now = datetime.datetime.now(datetime.timezone.utc)
cutoff = now - datetime.timedelta(days=DAYS_BACK)

articles = {}

for source, url in SOURCES.items():
    print(f"\nSOURCE: {source}")
    print(f"URL: {url}")

    try:
        request = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0"}
        )

        with urllib.request.urlopen(request, timeout=30) as response:
            print(f"HTTP status: {response.status}")
            feed_content = response.read()

        feed = feedparser.parse(feed_content)

        print(f"Articles received: {len(feed.entries)}")

        if feed.bozo:
            print(f"Feed warning: {feed.bozo_exception}")

        print(f"\nFIRST FIVE ARTICLES FROM {source}:")

        for entry in feed.entries[:5]:
            title = entry.get("title", "").strip()
            published = entry.get("published", "No publication date")
            print(f"TITLE: {title}")
            print(f"DATE: {published}")

        for entry in feed.entries:
            title = entry.get("title", "").strip()
            link = entry.get("link", "").strip()
            summary = entry.get("summary", "").strip()

            if not title or not link:
                continue

            text = (title + " " + summary).lower()

            if not any(word in text for word in KEYWORDS):
                continue

            published = (
                entry.get("published_parsed")
                or entry.get("updated_parsed")
            )

            if published:
                published_time = datetime.datetime.fromtimestamp(
                    calendar.timegm(published),
                    tz=datetime.timezone.utc
                )
            else:
                published_time = now

            if published_time < cutoff or published_time > now:
                continue

            articles[link] = {
                "title": html.unescape(title),
                "link": link,
                "summary": html.unescape(
                    re.sub(r"<[^>]+>", "", summary)
                ),
                "published": published_time,
                "source": source,
            }

    except urllib.error.HTTPError as error:
        print(f"HTTP status: {error.code}")
        print(f"Feed error: {error}")

    except Exception as error:
        print(f"Feed error: {error}")

sorted_articles = sorted(
    articles.values(),
    key=lambda item: item["published"],
    reverse=True
)[:MAX_ITEMS]

rss = ET.Element("rss", version="2.0")
channel = ET.SubElement(rss, "channel")

ET.SubElement(channel, "title").text = "Call of Duty News"
ET.SubElement(channel, "link").text = (
    "https://github.com/RageTherapy1010/cod-news-feed"
)
ET.SubElement(channel, "description").text = (
    "Latest Call of Duty news from MP1st and Insider Gaming"
)

for article in sorted_articles:
    item = ET.SubElement(channel, "item")

    ET.SubElement(item, "title").text = article["title"]
    ET.SubElement(item, "link").text = article["link"]
    ET.SubElement(item, "description").text = article["summary"]
    ET.SubElement(item, "pubDate").text = (
        email.utils.format_datetime(article["published"])
    )
    ET.SubElement(item, "guid").text = article["link"]
    ET.SubElement(item, "source").text = article["source"]

ET.indent(rss, space="  ")

tree = ET.ElementTree(rss)
tree.write(
    "rss.xml",
    encoding="utf-8",
    xml_declaration=True
)

print("\n------------------------------")
print(f"Total COD articles found: {len(sorted_articles)}")
print("RSS feed successfully generated.")
print("------------------------------")
