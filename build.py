#!/usr/bin/env python3
"""Render content/posts/*.md into the static blog, then refresh sitemap and llms.txt.

Run from the repo root:

    python3 build.py

Netlify serves this repo as plain files, so the output is committed rather than
built on deploy.
"""

import html
import json
import os
import re
import sys
from datetime import datetime, timezone

import yaml

ROOT = os.path.dirname(os.path.abspath(__file__))
POSTS_DIR = os.path.join(ROOT, "content", "posts")
TEMPLATES = os.path.join(ROOT, "templates")
BLOG_DIR = os.path.join(ROOT, "blog")
SITE = "https://jmstruijk.com"
AUTHOR = "J.M. Struijk"

# Every book the articles can point at. Keeping it here means an article's
# frontmatter only has to name the slug.
BOOKS = {
    "adhd-tax": ("The ADHD Tax", "Stop impulsive spending, forgotten bills & subscription chaos", "B0FX3M9838"),
    "adhd-budget-workbook": ("The ADHD Budget Workbook", "90-day financial reset for adults with ADHD", "B0G1HH2M25"),
    "adhd-side-hustle": ("The ADHD Side Hustle", "Turn your hyperfocus into extra income without burning out", "B0G2HRQTWJ"),
    "adhd-debt-payoff-workbook": ("The ADHD Debt Payoff Workbook", "Pay off debt, build momentum, and create financial freedom", "B0HDK1RYSW"),
    "adhd-budget-planner": ("The ADHD Budget Planner", "The undated 12-month money management system", "B0HDK4TZGF"),
    "adhd-overthinking-reset": ("The ADHD Overthinking Reset", "Break mental loops, quiet intrusive thoughts, stop spiraling", "B0GDGK3RLK"),
    "adhd-eating-reset": ("The ADHD Eating Reset", "End meal paralysis, stop forgetting to eat, build food habits that stick", "B0GDH6R4DL"),
    "adhd-decision-reset": ("The ADHD Decision Reset", "Break analysis paralysis, make choices faster, stop overthinking", "B0GDMWFDZ7"),
    "adhd-burnout-recovery": ("The ADHD Burnout Recovery Guide", "Triage, recovery, and prevention for the brain you actually have", "B0GDLRFXQ3"),
    "late-diagnosed-adhd-workbook": ("The Late-Diagnosed ADHD Workbook", "Practical tools for focus, time, big feelings, and burnout", "B0HBLVP38R"),
    "late-diagnosed-autistic-workbook": ("The Late-Diagnosed Autistic Workbook", "Practical tools for sensory overload, masking, and burnout", "B0HBNKNWZC"),
}

DISCLAIMER = (
    "I write from lived experience as a late-diagnosed ADHD and autistic adult, "
    "not as a clinician. Nothing here diagnoses anything or replaces working with "
    "a doctor, therapist, or ADHD coach. If something in your life has become "
    "unmanageable, please talk to someone qualified."
)


# ---------------------------------------------------------------- markdown

def inline(text):
    """Inline Markdown: links, bold, italic, code. Escapes everything else."""
    placeholders = []

    def stash(markup):
        placeholders.append(markup)
        return "\x00%d\x00" % (len(placeholders) - 1)

    # Pull constructs out before escaping so their punctuation survives.
    text = re.sub(r"`([^`]+)`",
                  lambda m: stash("<code>%s</code>" % html.escape(m.group(1))), text)
    text = re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)",
                  lambda m: stash('<a href="%s">%s</a>' % (html.escape(m.group(2)), inline(m.group(1)))), text)
    text = re.sub(r"\*\*([^*]+)\*\*",
                  lambda m: stash("<strong>%s</strong>" % inline(m.group(1))), text)
    text = re.sub(r"(?<![*\w])\*([^*]+)\*(?!\w)",
                  lambda m: stash("<em>%s</em>" % inline(m.group(1))), text)

    text = html.escape(text)
    return re.sub(r"\x00(\d+)\x00", lambda m: placeholders[int(m.group(1))], text)


def slugify(text):
    text = re.sub(r"<[^>]+>", "", text).lower()
    text = re.sub(r"[^a-z0-9\s-]", "", text)
    return re.sub(r"[\s-]+", "-", text).strip("-")


def render_markdown(body):
    """Render the Markdown subset the articles use.

    Returns (html, sections) where sections lists (level, text, id) for headings
    and carries the parsed key-takeaways and FAQ back to the caller.
    """
    out, headings = [], []
    takeaways, faq = [], []
    lines = body.split("\n")
    i = 0
    current_h2 = None

    while i < len(lines):
        line = lines[i].rstrip()

        if not line.strip():
            i += 1
            continue

        m = re.match(r"^(#{2,3})\s+(.*)$", line)
        if m:
            level, text = len(m.group(1)), m.group(2).strip()
            hid = slugify(text)
            if level == 2:
                current_h2 = text.lower()
                headings.append((text, hid))
            if current_h2 and current_h2.startswith("common questions") and level == 3:
                # Collect the question, then its answer paragraphs.
                answer, j = [], i + 1
                while j < len(lines) and not re.match(r"^#{2,3}\s", lines[j].rstrip()):
                    if lines[j].strip():
                        answer.append(lines[j].strip())
                    j += 1
                faq.append((text, " ".join(answer)))
                out.append('<details class="post-faq-item"><summary><h3 id="%s">%s</h3></summary>'
                           '<div class="post-faq-answer">%s</div></details>'
                           % (hid, inline(text), "".join("<p>%s</p>" % inline(p) for p in answer)))
                i = j
                continue
            out.append("<h%d id=\"%s\">%s</h%d>" % (level, hid, inline(text), level))
            i += 1
            continue

        if line.startswith("> "):
            quote = []
            while i < len(lines) and lines[i].startswith("> "):
                quote.append(lines[i][2:].strip())
                i += 1
            out.append("<blockquote><p>%s</p></blockquote>" % inline(" ".join(quote)))
            continue

        if re.match(r"^[-*]\s+", line):
            items = []
            while i < len(lines) and re.match(r"^[-*]\s+", lines[i].rstrip()):
                items.append(re.sub(r"^[-*]\s+", "", lines[i].rstrip()))
                i += 1
            if current_h2 and current_h2.startswith("key takeaways"):
                takeaways.extend(items)
                out.append('<ul class="post-takeaways-list">%s</ul>'
                           % "".join("<li>%s</li>" % inline(it) for it in items))
            else:
                out.append("<ul>%s</ul>" % "".join("<li>%s</li>" % inline(it) for it in items))
            continue

        if re.match(r"^\d+\.\s+", line):
            items = []
            while i < len(lines) and re.match(r"^\d+\.\s+", lines[i].rstrip()):
                items.append(re.sub(r"^\d+\.\s+", "", lines[i].rstrip()))
                i += 1
            out.append("<ol>%s</ol>" % "".join("<li>%s</li>" % inline(it) for it in items))
            continue

        para = []
        while i < len(lines) and lines[i].strip() and not re.match(r"^(#{2,3}\s|[-*]\s|\d+\.\s|>\s)", lines[i]):
            para.append(lines[i].strip())
            i += 1
        out.append("<p>%s</p>" % inline(" ".join(para)))

    return "\n".join(out), headings, takeaways, faq


# ---------------------------------------------------------------- posts

def read_posts():
    posts = []
    if not os.path.isdir(POSTS_DIR):
        sys.exit("No content/posts directory.")
    for name in sorted(os.listdir(POSTS_DIR)):
        if not name.endswith(".md"):
            continue
        raw = open(os.path.join(POSTS_DIR, name), encoding="utf-8").read()
        m = re.match(r"^---\n(.*?)\n---\n(.*)$", raw, re.S)
        if not m:
            sys.exit("%s is missing frontmatter." % name)
        meta = yaml.safe_load(m.group(1))
        body_html, headings, takeaways, faq = render_markdown(m.group(2).strip())

        for field in ("title", "slug", "description", "date"):
            if not meta.get(field):
                sys.exit("%s is missing '%s'." % (name, field))
        if meta.get("book") and meta["book"] not in BOOKS:
            sys.exit("%s names unknown book '%s'." % (name, meta["book"]))

        meta.update(body=body_html, headings=headings, takeaways=takeaways,
                    faq=faq, words=len(re.sub(r"<[^>]+>", " ", body_html).split()),
                    source=name)
        posts.append(meta)

    slugs = [p["slug"] for p in posts]
    dupes = {s for s in slugs if slugs.count(s) > 1}
    if dupes:
        sys.exit("Duplicate slugs: %s" % ", ".join(sorted(dupes)))
    for p in posts:
        for rel in p.get("related") or []:
            if rel not in slugs:
                sys.exit("%s links to unknown related post '%s'." % (p["source"], rel))

    # Newest first. Posts sharing a date keep their filename order, so the
    # numbered prefixes in content/posts control the running order.
    posts.sort(key=lambda p: p["source"])
    posts.sort(key=lambda p: str(p["date"]), reverse=True)
    return posts


# ---------------------------------------------------------------- rendering

def book_cta(slug):
    if not slug:
        return ""
    title, subtitle, asin = BOOKS[slug]
    return """
<aside class="book-cta">
  <a class="book-cta-cover" href="https://www.amazon.com/dp/{asin}" target="_blank" rel="noopener">
    <img src="/assets/covers/{slug}.jpg" alt="{title} book cover" width="700" height="1050" loading="lazy" decoding="async">
  </a>
  <div class="book-cta-body">
    <div class="book-cta-label">The book on this</div>
    <h2 class="book-cta-title">{title}</h2>
    <p>{subtitle}.</p>
    <a class="book-cta-link" href="https://www.amazon.com/dp/{asin}" target="_blank" rel="noopener">View on Amazon &rarr;</a>
  </div>
</aside>""".format(asin=asin, slug=slug, title=html.escape(title), subtitle=html.escape(subtitle))


def schema_for(post):
    url = "%s/blog/%s/" % (SITE, post["slug"])
    date = str(post["date"])
    graph = [
        {
            "@type": "BlogPosting",
            "@id": url + "#article",
            "headline": post["title"],
            "description": post["description"],
            "datePublished": date,
            "dateModified": str(post.get("updated") or date),
            "wordCount": post["words"],
            "inLanguage": "en-US",
            "url": url,
            "mainEntityOfPage": {"@type": "WebPage", "@id": url},
            "author": {"@type": "Person", "name": AUTHOR, "url": SITE + "/"},
            "publisher": {"@type": "Organization", "name": "JMS Media Group LLC", "url": SITE + "/"},
            "image": SITE + "/og-image.jpg",
            "isAccessibleForFree": True,
        },
        {
            "@type": "BreadcrumbList",
            "itemListElement": [
                {"@type": "ListItem", "position": 1, "name": AUTHOR, "item": SITE + "/"},
                {"@type": "ListItem", "position": 2, "name": "Blog", "item": SITE + "/blog/"},
                {"@type": "ListItem", "position": 3, "name": post["title"], "item": url},
            ],
        },
    ]
    if post["faq"]:
        graph.append({
            "@type": "FAQPage",
            "@id": url + "#faq",
            "mainEntity": [
                {"@type": "Question", "name": q,
                 "acceptedAnswer": {"@type": "Answer", "text": a}}
                for q, a in post["faq"]
            ],
        })
    if post.get("book"):
        title, _, asin = BOOKS[post["book"]]
        graph[0]["mentions"] = {"@type": "Book", "name": title,
                                "url": "https://www.amazon.com/dp/%s" % asin,
                                "author": {"@type": "Person", "name": AUTHOR}}
    return json.dumps({"@context": "https://schema.org", "@graph": graph},
                      indent=2, ensure_ascii=False)


def pretty_date(value):
    return datetime.strptime(str(value), "%Y-%m-%d").strftime("%d %B %Y").lstrip("0")


def render_post(post, by_slug, template):
    toc = ""
    if len(post["headings"]) > 2:
        toc = ('<nav class="post-toc" aria-label="On this page"><h2>On this page</h2><ol>%s</ol></nav>'
               % "".join('<li><a href="#%s">%s</a></li>' % (hid, html.escape(text))
                         for text, hid in post["headings"]))

    related = ""
    rel_slugs = post.get("related") or []
    if rel_slugs:
        cards = "".join(
            '<a class="related-card" href="/blog/%s/"><span class="related-kicker">Related</span>'
            '<span class="related-title">%s</span><span class="related-desc">%s</span></a>'
            % (s, html.escape(by_slug[s]["title"]), html.escape(by_slug[s]["description"]))
            for s in rel_slugs)
        related = '<section class="related"><h2>Keep reading</h2><div class="related-grid">%s</div></section>' % cards

    return template.format(
        title=html.escape(post["title"]),
        description=html.escape(post["description"]),
        keywords=html.escape(post.get("keywords", "")),
        slug=post["slug"],
        date_iso=str(post["date"]),
        date_human=pretty_date(post["date"]),
        reading_time=max(1, round(post["words"] / 220)),
        toc=toc,
        body=post["body"],
        book_cta=book_cta(post.get("book")),
        related=related,
        schema=schema_for(post),
        disclaimer=html.escape(DISCLAIMER),
    )


def render_index(posts, template):
    cards = []
    for p in posts:
        book = ""
        if p.get("book"):
            book = '<span class="card-book">%s</span>' % html.escape(BOOKS[p["book"]][0])
        cards.append(
            '<article class="card"><a class="card-link" href="/blog/%s/">'
            '<div class="card-meta"><time datetime="%s">%s</time>'
            '<span class="card-dot">&middot;</span><span>%d min read</span>%s</div>'
            '<h2 class="card-title">%s</h2><p class="card-desc">%s</p>'
            '<span class="card-cta">Read the article &rarr;</span></a></article>'
            % (p["slug"], str(p["date"]), pretty_date(p["date"]),
               max(1, round(p["words"] / 220)), book,
               html.escape(p["title"]), html.escape(p["description"])))
    return template.format(cards="\n".join(cards), count=len(posts))


def render_feed(posts):
    items = []
    for p in posts:
        url = "%s/blog/%s/" % (SITE, p["slug"])
        pub = datetime.strptime(str(p["date"]), "%Y-%m-%d").replace(tzinfo=timezone.utc)
        items.append(
            "    <item>\n"
            "      <title>%s</title>\n"
            "      <link>%s</link>\n"
            "      <guid isPermaLink=\"true\">%s</guid>\n"
            "      <pubDate>%s</pubDate>\n"
            "      <description>%s</description>\n"
            "    </item>"
            % (html.escape(p["title"]), url, url,
               pub.strftime("%a, %d %b %Y %H:%M:%S +0000"), html.escape(p["description"])))
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">\n'
            '  <channel>\n'
            '    <title>J.M. Struijk on ADHD and autism</title>\n'
            '    <link>%s/blog/</link>\n'
            '    <atom:link href="%s/blog/feed.xml" rel="self" type="application/rss+xml"/>\n'
            '    <description>Practical writing on ADHD, autism, and AuDHD from a late-diagnosed author.</description>\n'
            '    <language>en-us</language>\n%s\n  </channel>\n</rss>\n'
            % (SITE, SITE, "\n".join(items)))


# ------------------------------------------------- sitemap and llms.txt

def write_sitemap(posts):
    covers = sorted(os.listdir(os.path.join(ROOT, "assets", "covers")))
    images = "".join(
        "\n    <image:image><image:loc>%s/assets/covers/%s</image:loc></image:image>" % (SITE, c)
        for c in covers if c.endswith(".jpg"))
    today = datetime.now().strftime("%Y-%m-%d")
    urls = [
        '  <url>\n    <loc>%s/</loc>\n    <lastmod>%s</lastmod>\n'
        '    <changefreq>weekly</changefreq>\n    <priority>1.0</priority>%s\n  </url>' % (SITE, today, images),
        '  <url>\n    <loc>%s/blog/</loc>\n    <lastmod>%s</lastmod>\n'
        '    <changefreq>weekly</changefreq>\n    <priority>0.9</priority>\n  </url>' % (SITE, today),
    ]
    for p in posts:
        urls.append('  <url>\n    <loc>%s/blog/%s/</loc>\n    <lastmod>%s</lastmod>\n'
                    '    <changefreq>monthly</changefreq>\n    <priority>0.8</priority>\n  </url>'
                    % (SITE, p["slug"], str(p.get("updated") or p["date"])))
    urls.append('  <url>\n    <loc>%s/adhd-tax-worksheets/</loc>\n    <lastmod>%s</lastmod>\n'
                '    <changefreq>monthly</changefreq>\n    <priority>0.6</priority>\n  </url>' % (SITE, today))

    open(os.path.join(ROOT, "sitemap.xml"), "w", encoding="utf-8").write(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"\n'
        '        xmlns:image="http://www.google.com/schemas/sitemap-image/1.1">\n'
        + "\n".join(urls) + "\n</urlset>\n")


def write_llms(posts):
    path = os.path.join(ROOT, "llms.txt")
    text = open(path, encoding="utf-8").read()
    section = ["## Articles", "",
               "Long-form writing on ADHD and autism, from lived experience. Not clinical guidance.",
               ""]
    for p in posts:
        section.append("- [%s](%s/blog/%s/): %s. Published %s."
                       % (p["title"], SITE, p["slug"], p["description"].rstrip("."), str(p["date"])))
    block = "\n".join(section) + "\n"

    if "## Articles" in text:
        text = re.sub(r"## Articles\n.*?(?=\n## |\Z)", block, text, flags=re.S)
    else:
        text = text.replace("## Free resources", block + "\n## Free resources")
    open(path, "w", encoding="utf-8").write(text)


# ---------------------------------------------------------------- main

def main():
    posts = read_posts()
    by_slug = {p["slug"]: p for p in posts}
    post_tpl = open(os.path.join(TEMPLATES, "post.html"), encoding="utf-8").read()
    index_tpl = open(os.path.join(TEMPLATES, "index.html"), encoding="utf-8").read()

    os.makedirs(BLOG_DIR, exist_ok=True)
    for p in posts:
        out_dir = os.path.join(BLOG_DIR, p["slug"])
        os.makedirs(out_dir, exist_ok=True)
        open(os.path.join(out_dir, "index.html"), "w", encoding="utf-8").write(
            render_post(p, by_slug, post_tpl))

    open(os.path.join(BLOG_DIR, "index.html"), "w", encoding="utf-8").write(
        render_index(posts, index_tpl))
    open(os.path.join(BLOG_DIR, "feed.xml"), "w", encoding="utf-8").write(render_feed(posts))
    write_sitemap(posts)
    write_llms(posts)

    total = sum(p["words"] for p in posts)
    print("%d posts, %d words, %d with FAQ schema"
          % (len(posts), total, sum(1 for p in posts if p["faq"])))
    for p in posts:
        print("  %-44s %5d words  %d q  %s"
              % (p["slug"], p["words"], len(p["faq"]), p["date"]))


if __name__ == "__main__":
    main()
