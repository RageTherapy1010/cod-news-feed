
import calendar
import datetime
import email.utils
import html
import re
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
checked = []

for source, url in SOURCES.items():
    try:
        feed = feedparser.parse(url)
        checked.append(source)

        if feed.bozo and not feed.entries:
            print(f"Warning: Could not read {source} feed.")
            continue

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

    except Exception as error:
        print(f"Error checking {source}: {error}")

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

print(f"Sources checked: {', '.join(checked)}")
print(f"Articles found: {len(sorted_articles)}")
print("RSS feed successfully generated.")
