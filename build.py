#!/usr/bin/env python3
"""Build the generated parts of jmstruijk.com.

    python3 build.py            pages, feed, sitemap, llms files, homepage blocks
    python3 build.py --og       also render share images that are missing (needs Chrome)
    python3 build.py --og-all   re-render every share image

Content lives in content/. Output is committed, because Netlify serves this repo
as static files with no build step. Everything is rendered in memory and every
internal link is checked before anything is written, so a broken link fails the
build instead of shipping.
"""

import glob
import html
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
from datetime import datetime, timezone

import yaml

ROOT = os.path.dirname(os.path.abspath(__file__))
CONTENT = os.path.join(ROOT, "content")
TEMPLATES = os.path.join(ROOT, "templates")
SITE = "https://jmstruijk.com"
AUTHOR = "J.M. Struijk"
PERSON_ID = SITE + "/#person"
PUBLISHER_ID = SITE + "/#publisher"
WEBSITE_ID = SITE + "/#website"
DEFAULT_OG = SITE + "/og-image.jpg"
AMAZON_AUTHOR = "https://www.amazon.com/stores/J.M.-Struijk/author/B0G1ZFQ5HR"

# What an article, book or glossary term can be "about". Each is a canonical
# Wikipedia article, checked to be a real article and not a redirect, so the
# schema names the right entity. Leave a topic out rather than point it at a
# near match.
WIKI = "https://en.wikipedia.org/wiki/"
ENTITIES = {
    "adhd": ("Attention deficit hyperactivity disorder", "Attention_deficit_hyperactivity_disorder"),
    "autism": ("Autism", "Autism"),
    "executive-dysfunction": ("Executive dysfunction", "Executive_dysfunction"),
    "hyperfocus": ("Hyperfocus", "Hyperfocus"),
    "stimming": ("Stimming", "Stimming"),
    "body-doubling": ("Body doubling", "Body_doubling"),
    "sensory-overload": ("Sensory overload", "Sensory_overload"),
    "monotropism": ("Monotropism", "Monotropism"),
    "interoception": ("Interoception", "Interoception"),
    "masking": ("Masking (behavior)", "Masking_(behavior)"),
    "analysis-paralysis": ("Analysis paralysis", "Analysis_paralysis"),
    "rumination": ("Rumination (psychology)", "Rumination_(psychology)"),
    "arfid": ("Avoidant/restrictive food intake disorder", "Avoidant/restrictive_food_intake_disorder"),
    "neurodiversity": ("Neurodiversity", "Neurodiversity"),
    "spoon-theory": ("Spoon theory", "Spoon_theory"),
    "special-interest": ("Special interest", "Special_interest"),
    "alexithymia": ("Alexithymia", "Alexithymia"),
    "double-empathy": ("Double empathy problem", "Double_empathy_problem"),
    "emotional-dysregulation": ("Emotional dysregulation", "Emotional_dysregulation"),
    "echolalia": ("Echolalia", "Echolalia"),
}

# Display order, homepage anchor, accent colour, and a short name for share images.
SERIES = {
    "The ADHD Money Mastery Series": ("money", "var(--coral)", "ADHD Money Mastery"),
    "The ADHD Reset Series": ("reset", "var(--sage)", "ADHD Reset Series"),
    "The Late-Diagnosed Workbooks": ("late-diagnosed", "var(--gold)", "Late-Diagnosed Workbooks"),
    "Standalone": ("standalone", "var(--ink)", "Standalone guide"),
}
BADGES = {"start": ("badge-start", "Start here"), "new": ("badge-new", "New")}

DISCLAIMER = (
    "I write from lived experience as a late-diagnosed ADHD and autistic adult, "
    "not as a clinician. Nothing here diagnoses anything or replaces working with "
    "a doctor, therapist, or ADHD coach. If something in your life has become "
    "unmanageable, please talk to someone qualified."
)


def fail(message):
    sys.exit("build.py: " + message)


def esc(value):
    return html.escape(str(value))


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
                  lambda m: stash(link(m.group(2), inline(m.group(1)))), text)
    text = re.sub(r"\*\*([^*]+)\*\*",
                  lambda m: stash("<strong>%s</strong>" % inline(m.group(1))), text)
    text = re.sub(r"(?<![*\w])\*([^*]+)\*(?!\w)",
                  lambda m: stash("<em>%s</em>" % inline(m.group(1))), text)

    text = html.escape(text)
    return re.sub(r"\x00(\d+)\x00", lambda m: placeholders[int(m.group(1))], text)


def link(href, label):
    if href.startswith("http"):
        return '<a href="%s" target="_blank" rel="noopener">%s</a>' % (html.escape(href), label)
    return '<a href="%s">%s</a>' % (html.escape(href), label)


def plain(text):
    """Strip inline Markdown down to readable text, for schema and llms files."""
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    return re.sub(r"[*`]", "", text).strip()


def slugify(text):
    text = re.sub(r"<[^>]+>", "", text).lower()
    text = re.sub(r"[^a-z0-9\s-]", "", text)
    return re.sub(r"[\s-]+", "-", text).strip("-")


def render_markdown(body):
    """Render the Markdown subset the content uses.

    Returns (html, headings, takeaways, faq). A "Key takeaways" list becomes the
    summary box and a "Common questions" section becomes the FAQ, so the schema
    built from them always matches what is on the page.
    """
    out, headings, takeaways, faq = [], [], [], []
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
                answer, j = [], i + 1
                while j < len(lines) and not re.match(r"^#{2,3}\s", lines[j].rstrip()):
                    if lines[j].strip():
                        answer.append(lines[j].strip())
                    j += 1
                faq.append((text, plain(" ".join(answer))))
                out.append('<details class="post-faq-item"><summary><h3 id="%s">%s</h3></summary>'
                           '<div class="post-faq-answer">%s</div></details>'
                           % (hid, inline(text), "".join("<p>%s</p>" % inline(p) for p in answer)))
                i = j
                continue
            out.append('<h%d id="%s">%s</h%d>' % (level, hid, inline(text), level))
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
                takeaways.extend(plain(it) for it in items)
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


# ---------------------------------------------------------------- loading

def read_source(path):
    raw = open(path, encoding="utf-8").read()
    m = re.match(r"^---\n(.*?)\n---\n(.*)$", raw, re.S)
    if not m:
        fail("%s is missing frontmatter." % os.path.relpath(path, ROOT))
    return yaml.safe_load(m.group(1)) or {}, m.group(2).strip()


def require(meta, fields, where):
    for field in fields:
        if meta.get(field) in (None, ""):
            fail("%s is missing '%s'." % (where, field))


def check_about(keys, where):
    for key in keys or []:
        if key not in ENTITIES:
            fail("%s is about unknown topic '%s'. Add it to ENTITIES first." % (where, key))


def mtime_date(path):
    return datetime.fromtimestamp(os.path.getmtime(path)).strftime("%Y-%m-%d")


def jpeg_size(path):
    """(width, height) of a JPEG, read from its frame header."""
    data = open(path, "rb").read()
    i = 2
    while i < len(data):
        if data[i] != 0xFF:
            i += 1
            continue
        marker = data[i + 1]
        if marker in (0xC0, 0xC1, 0xC2):
            h, w = struct.unpack(">HH", data[i + 5:i + 9])
            return w, h
        i += 2 + struct.unpack(">H", data[i + 2:i + 4])[0]
    return 700, 1050


def load_books():
    books = []
    for path in sorted(glob.glob(os.path.join(CONTENT, "books", "*.md"))):
        name = os.path.relpath(path, ROOT)
        meta, body = read_source(path)
        require(meta, ("slug", "title", "subtitle", "asin", "series", "order",
                       "published", "tagline", "description"), name)
        if meta["series"] not in SERIES:
            fail("%s has unknown series '%s'." % (name, meta["series"]))
        if meta.get("badge") and meta["badge"] not in BADGES:
            fail("%s has unknown badge '%s'." % (name, meta["badge"]))
        cover = os.path.join(ROOT, "assets", "covers", meta["slug"] + ".jpg")
        if not os.path.exists(cover):
            fail("%s has no cover at assets/covers/%s.jpg." % (name, meta["slug"]))
        check_about(meta.get("about"), name)
        body_html, _, _, faq = render_markdown(body)
        meta.update(body=body_html, faq=faq, markdown=body, source=name,
                    cover_size=jpeg_size(cover), modified=mtime_date(path))
        books.append(meta)

    slugs = [b["slug"] for b in books]
    if len(set(slugs)) != len(slugs):
        fail("duplicate book slugs.")
    books.sort(key=lambda b: b["order"])
    return books


def load_posts(by_book):
    posts = []
    for path in sorted(glob.glob(os.path.join(CONTENT, "posts", "*.md"))):
        name = os.path.relpath(path, ROOT)
        meta, body = read_source(path)
        require(meta, ("title", "slug", "description", "date"), name)
        if meta.get("book") and meta["book"] not in by_book:
            fail("%s names unknown book '%s'." % (name, meta["book"]))
        if len(meta.get("related") or []) > 3:
            fail("%s has more than three related posts." % name)
        check_about(meta.get("about"), name)
        body_html, headings, takeaways, faq = render_markdown(body)
        words = len(re.sub(r"<[^>]+>", " ", body_html).split())
        meta.update(body=body_html, headings=headings, takeaways=takeaways, faq=faq,
                    words=words, markdown=body, source=os.path.basename(path))
        posts.append(meta)

    slugs = [p["slug"] for p in posts]
    dupes = {s for s in slugs if slugs.count(s) > 1}
    if dupes:
        fail("duplicate post slugs: %s" % ", ".join(sorted(dupes)))
    for p in posts:
        for rel in p.get("related") or []:
            if rel not in slugs:
                fail("%s links to unknown related post '%s'." % (p["source"], rel))

    # Newest first. Posts sharing a date keep their filename order, so the
    # numbered prefixes in content/posts control the running order.
    posts.sort(key=lambda p: p["source"])
    posts.sort(key=lambda p: str(p["date"]), reverse=True)
    return posts


def load_glossary():
    path = os.path.join(CONTENT, "glossary.yaml")
    terms = yaml.safe_load(open(path, encoding="utf-8")) or []
    for t in terms:
        require(t, ("term", "slug", "definition"), "glossary term %r" % t.get("term"))
        if t.get("entity") and t["entity"] not in ENTITIES:
            fail("glossary term '%s' has unknown entity '%s'." % (t["term"], t["entity"]))
    slugs = [t["slug"] for t in terms]
    if len(set(slugs)) != len(slugs):
        fail("duplicate glossary slugs.")
    terms.sort(key=lambda t: re.sub(r"^the\s+", "", t["term"].lower()))
    return terms, mtime_date(path)


# ---------------------------------------------------------------- shared

PARTIALS = {}


def render(template, **values):
    if not PARTIALS:
        for name in ("head", "header", "footer"):
            PARTIALS[name] = open(os.path.join(TEMPLATES, "partials", name + ".html"),
                                  encoding="utf-8").read().rstrip()
    for name, markup in PARTIALS.items():
        values.setdefault(name, markup)
    return open(os.path.join(TEMPLATES, template), encoding="utf-8").read().format(**values)


def seo_head(title, description, path, image=None, og_type="website"):
    url = SITE + path
    t, d, image = esc(title), esc(description), image or DEFAULT_OG
    return "\n".join([
        "<title>%s</title>" % t,
        '<meta name="description" content="%s">' % d,
        '<link rel="canonical" href="%s">' % url,
        '<meta name="robots" content="index, follow, max-image-preview:large, max-snippet:-1, max-video-preview:-1">',
        '<meta property="og:type" content="%s">' % og_type,
        '<meta property="og:url" content="%s">' % url,
        '<meta property="og:title" content="%s">' % t,
        '<meta property="og:description" content="%s">' % d,
        '<meta property="og:image" content="%s">' % image,
        '<meta property="og:image:width" content="1200">',
        '<meta property="og:image:height" content="630">',
        '<meta property="og:site_name" content="J.M. Struijk">',
        '<meta property="og:locale" content="en_US">',
        '<meta name="twitter:card" content="summary_large_image">',
        '<meta name="twitter:title" content="%s">' % t,
        '<meta name="twitter:description" content="%s">' % d,
        '<meta name="twitter:image" content="%s">' % image,
    ])


def og_image(kind, slug):
    for ext in ("jpg", "png"):
        rel = "assets/og/%s-%s.%s" % (kind, slug, ext)
        if os.path.exists(os.path.join(ROOT, rel)):
            return "%s/%s" % (SITE, rel)
    return DEFAULT_OG


def human_date(value):
    return datetime.strptime(str(value), "%Y-%m-%d").strftime("%d %B %Y").lstrip("0")


def minutes(words):
    return max(1, round(words / 220))


def amazon(asin):
    return "https://www.amazon.com/dp/%s" % asin


def schema(graph):
    text = json.dumps({"@context": "https://schema.org", "@graph": graph}, indent=2, ensure_ascii=False)
    return text.replace("</", "<\\/")


def person_node():
    return {"@type": "Person", "@id": PERSON_ID, "name": AUTHOR, "url": SITE + "/",
            "sameAs": [AMAZON_AUTHOR]}


def publisher_ref():
    return {"@type": "Organization", "@id": PUBLISHER_ID, "name": "JMS Media Group LLC", "url": SITE + "/"}


def about_nodes(keys):
    return [{"@type": "Thing", "name": ENTITIES[k][0], "sameAs": WIKI + ENTITIES[k][1]}
            for k in keys or []]


def breadcrumbs(*trail):
    return {"@type": "BreadcrumbList", "itemListElement": [
        {"@type": "ListItem", "position": i + 1, "name": name, "item": SITE + path}
        for i, (name, path) in enumerate(trail)]}


def faq_node(url, faq):
    return {"@type": "FAQPage", "@id": url + "#faq", "mainEntity": [
        {"@type": "Question", "name": q, "acceptedAnswer": {"@type": "Answer", "text": a}}
        for q, a in faq]}


def series_label(book):
    if book["series"] == "Standalone":
        return "Standalone guide"
    if book.get("position"):
        return "Book %d of %s" % (book["position"], book["series"])
    return "Part of " + book["series"]


AUTHOR_BOX = """<section class="author-box">
      <img src="/assets/images/author.jpg" alt="J.M. Struijk" width="562" height="900" loading="lazy" decoding="async">
      <div>
        <div class="author-label">About the author</div>
        <p><strong>J.M. Struijk</strong> is a late-diagnosed ADHD and autistic author. I write practical companions for the brain you actually have, published independently through JMS Media Group LLC. <a href="/books/">See all the books</a> or <a href="/#about">read more about me</a>.</p>
      </div>
    </section>"""

SIGNUP = """<section class="post-signup">
      <div>
        <h2>The ADHD Survival Kit</h2>
        <p>Six printable tools I keep coming back to myself. Free PDF, sent to your inbox.</p>
      </div>
      <form class="signup-form" action="#" method="post" novalidate>
        <input type="email" name="email" placeholder="your@email.com" required aria-label="Email address">
        <button type="submit">Send me the kit</button>
      </form>
    </section>"""


def book_card(book, heading="h3"):
    w, h = book["cover_size"]
    return ('<a class="shelf-book" href="/books/{slug}/">'
            '<span class="shelf-cover"><img src="/assets/covers/{slug}.jpg" alt="{title} book cover" '
            'width="{w}" height="{h}" loading="lazy" decoding="async"></span>'
            '<{hd} class="shelf-title">{title}</{hd}><span class="shelf-tagline">{tagline}</span></a>'
            ).format(slug=book["slug"], title=esc(book["title"]), tagline=esc(book["tagline"]),
                     w=w, h=h, hd=heading)


def post_cards(posts, heading):
    if not posts:
        return ""
    cards = "".join(
        '<a class="related-card" href="/blog/%s/"><span class="related-kicker">Article</span>'
        '<span class="related-title">%s</span><span class="related-desc">%s</span></a>'
        % (p["slug"], esc(p["title"]), esc(p["description"])) for p in posts)
    return '<section class="related"><h2>%s</h2><div class="related-grid">%s</div></section>' % (heading, cards)


# ---------------------------------------------------------------- articles

def book_cta(book):
    if not book:
        return ""
    w, h = book["cover_size"]
    return """<aside class="book-cta">
      <a class="book-cta-cover" href="/books/{slug}/">
        <img src="/assets/covers/{slug}.jpg" alt="{title} book cover" width="{w}" height="{h}" loading="lazy" decoding="async">
      </a>
      <div class="book-cta-body">
        <div class="book-cta-label">The book on this</div>
        <h2 class="book-cta-title"><a href="/books/{slug}/">{title}</a></h2>
        <p>{tagline}.</p>
        <div class="book-cta-actions">
          <a class="book-cta-link" href="{amazon}" target="_blank" rel="noopener">View on Amazon &rarr;</a>
          <a class="book-cta-more" href="/books/{slug}/">About the book</a>
        </div>
      </div>
    </aside>""".format(slug=book["slug"], title=esc(book["title"]), tagline=esc(book["tagline"]),
                       amazon=amazon(book["asin"]), w=w, h=h)


def render_post(post, by_post, by_book):
    path = "/blog/%s/" % post["slug"]
    url = SITE + path
    book = by_book.get(post.get("book"))
    image = og_image("post", post["slug"])

    toc = ""
    if len(post["headings"]) > 2:
        toc = ('<nav class="post-toc" aria-label="On this page"><h2>On this page</h2><ol>%s</ol></nav>'
               % "".join('<li><a href="#%s">%s</a></li>' % (hid, esc(text))
                         for text, hid in post["headings"]))

    article = {
        "@type": "BlogPosting",
        "@id": url + "#article",
        "headline": post["title"],
        "description": post["description"],
        "datePublished": str(post["date"]),
        "dateModified": str(post.get("updated") or post["date"]),
        "wordCount": post["words"],
        "timeRequired": "PT%dM" % minutes(post["words"]),
        "inLanguage": "en-US",
        "url": url,
        "mainEntityOfPage": {"@type": "WebPage", "@id": url},
        "isPartOf": {"@type": "Blog", "@id": SITE + "/blog/#blog"},
        "author": {"@id": PERSON_ID},
        "publisher": publisher_ref(),
        "image": {"@type": "ImageObject", "url": image, "width": 1200, "height": 630},
        "keywords": post.get("keywords", ""),
        "isAccessibleForFree": True,
    }
    if post.get("about"):
        article["about"] = about_nodes(post["about"])
    if post["takeaways"]:
        article["abstract"] = " ".join(post["takeaways"])
    if book:
        article["mentions"] = {"@type": "Book", "@id": SITE + "/books/%s/#book" % book["slug"],
                               "name": book["title"], "url": SITE + "/books/%s/" % book["slug"],
                               "sameAs": amazon(book["asin"]), "author": {"@id": PERSON_ID}}
    graph = [article, person_node(),
             breadcrumbs((AUTHOR, "/"), ("Blog", "/blog/"), (post["title"], path))]
    if post["faq"]:
        graph.append(faq_node(url, post["faq"]))

    return render(
        "post.html",
        # seo_title is an optional shorter <title> for search results; the page keeps the full headline.
        seo=seo_head(post.get("seo_title") or post["title"], post["description"], path, image, "article")
            + '\n<meta property="article:published_time" content="%s">' % post["date"]
            + '\n<meta property="article:author" content="J.M. Struijk">'
            + '\n<meta name="keywords" content="%s">' % esc(post.get("keywords", "")),
        schema=schema(graph),
        title=esc(post["title"]),
        description=esc(post["description"]),
        date_iso=str(post["date"]),
        date_human=human_date(post["date"]),
        reading_time=minutes(post["words"]),
        toc=toc,
        body=post["body"],
        book_cta=book_cta(book),
        author_box=AUTHOR_BOX,
        disclaimer=esc(DISCLAIMER),
        related=post_cards([by_post[s] for s in post.get("related") or []], "Keep reading"),
        signup=SIGNUP,
    )


def render_blog_index(posts, by_book):
    cards = []
    for p in posts:
        book = ""
        if p.get("book"):
            book = '<span class="card-book">%s</span>' % esc(by_book[p["book"]]["title"])
        cards.append(
            '<article class="card"><a class="card-link" href="/blog/%s/">'
            '<div class="card-meta"><time datetime="%s">%s</time>'
            '<span class="card-dot">&middot;</span><span>%d min read</span>%s</div>'
            '<h2 class="card-title">%s</h2><p class="card-desc">%s</p>'
            '<span class="card-cta">Read the article &rarr;</span></a></article>'
            % (p["slug"], p["date"], human_date(p["date"]), minutes(p["words"]), book,
               esc(p["title"]), esc(p["description"])))

    graph = [
        {"@type": "Blog", "@id": SITE + "/blog/#blog", "url": SITE + "/blog/",
         "name": "J.M. Struijk on ADHD and autism",
         "description": "Practical writing on ADHD, autism and AuDHD from a late-diagnosed author.",
         "inLanguage": "en-US", "author": {"@id": PERSON_ID}, "publisher": publisher_ref(),
         "blogPost": [{"@type": "BlogPosting", "headline": p["title"],
                       "url": SITE + "/blog/%s/" % p["slug"], "datePublished": str(p["date"])}
                      for p in posts]},
        person_node(),
        breadcrumbs((AUTHOR, "/"), ("Blog", "/blog/")),
    ]
    return render(
        "blog.html",
        seo=seo_head("Blog: Writing on ADHD, Autism & AuDHD — J.M. Struijk",
                     "Practical articles on ADHD, autism and AuDHD by a late-diagnosed author: "
                     "the ADHD tax, rejection sensitivity, masking, burnout and task paralysis.", "/blog/"),
        schema=schema(graph), count=len(posts), cards="\n".join(cards))


# ---------------------------------------------------------------- books

def render_book(book, posts, books):
    path = "/books/%s/" % book["slug"]
    url = SITE + path
    image = og_image("book", book["slug"])
    title = "%s — Book by J.M. Struijk" % book["title"]

    facts = ['<span>Published %s</span>' % human_date(book["published"])]
    if book.get("pages"):
        facts.append("<span>%d pages</span>" % book["pages"])
    facts.append('<span>By <a href="/#about">J.M. Struijk</a></span>')

    node = {
        "@type": "Book",
        "@id": url + "#book",
        "name": book["title"],
        "alternateName": "%s: %s" % (book["title"], book["subtitle"]),
        "description": book["description"],
        "author": {"@id": PERSON_ID},
        "publisher": publisher_ref(),
        "datePublished": str(book["published"]),
        "inLanguage": "en",
        "url": url,
        "sameAs": [amazon(book["asin"])],
        "image": "%s/assets/covers/%s.jpg" % (SITE, book["slug"]),
        "identifier": {"@type": "PropertyValue", "propertyID": "ASIN", "value": book["asin"]},
    }
    if book.get("pages"):
        node["numberOfPages"] = book["pages"]
    if book["series"] != "Standalone":
        node["isPartOf"] = {"@type": "BookSeries", "name": book["series"]}
        if book.get("position"):
            node["position"] = book["position"]
    if book.get("about"):
        node["about"] = about_nodes(book["about"])

    graph = [
        {"@type": "WebPage", "@id": url, "url": url, "name": title,
         "description": book["description"], "isPartOf": {"@id": WEBSITE_ID},
         "mainEntity": {"@id": url + "#book"}, "inLanguage": "en-US"},
        node, person_node(),
        breadcrumbs((AUTHOR, "/"), ("Books", "/books/"), (book["title"], path)),
    ]
    if book["faq"]:
        graph.append(faq_node(url, book["faq"]))

    on_topic = [p for p in posts if p.get("book") == book["slug"]]
    siblings = [b for b in books if b["series"] == book["series"] and b["slug"] != book["slug"]]
    series_more = ""
    if siblings:
        heading = "Also in this series" if book["series"] != "Standalone" else "Other books"
        series_more = ('<section class="related"><h2>%s</h2><div class="shelf-grid shelf-grid-small">%s</div></section>'
                       % (heading, "".join(book_card(b) for b in siblings)))

    return render(
        "book.html",
        seo=seo_head(title, book["description"], path, image, "book")
            + '\n<meta property="book:author" content="J.M. Struijk">'
            + '\n<meta property="book:release_date" content="%s">' % book["published"]
            + '\n<meta name="keywords" content="%s">' % esc(book.get("keywords", "")),
        schema=schema(graph),
        slug=book["slug"],
        title=esc(book["title"]),
        subtitle=esc(book["subtitle"]),
        series_label=esc(series_label(book)),
        facts='<span class="book-facts-sep">·</span>'.join(facts),
        asin=book["asin"],
        body=book["body"],
        articles=post_cards(on_topic, "Articles on this subject"),
        series_more=series_more,
        author_box=AUTHOR_BOX,
        disclaimer=esc(DISCLAIMER),
    )


def render_books_index(books):
    shelves = []
    for series, (anchor, colour, _) in SERIES.items():
        group = [b for b in books if b["series"] == series]
        if not group:
            continue
        shelves.append(
            '<section class="shelf" id="%s"><div class="series-header"><h2 class="series-name">'
            '<span class="series-color-dot" style="background:%s;"></span>%s</h2>'
            '<span class="series-meta">%d book%s</span></div><div class="shelf-grid">%s</div></section>'
            % (anchor, colour, esc(series), len(group), "" if len(group) == 1 else "s",
               "".join(book_card(b) for b in group)))

    graph = [
        {"@type": "CollectionPage", "@id": SITE + "/books/", "url": SITE + "/books/",
         "name": "Books by J.M. Struijk", "isPartOf": {"@id": WEBSITE_ID}, "inLanguage": "en-US",
         "mainEntity": {"@type": "ItemList", "numberOfItems": len(books),
                        "itemListElement": [{"@type": "ListItem", "position": i + 1,
                                             "url": SITE + "/books/%s/" % b["slug"], "name": b["title"]}
                                            for i, b in enumerate(books)]}},
        person_node(),
        breadcrumbs((AUTHOR, "/"), ("Books", "/books/")),
    ]
    return render(
        "books.html",
        seo=seo_head("Books by J.M. Struijk: ADHD, Autism & AuDHD",
                     "All %d books by J.M. Struijk for adults with ADHD, autism and AuDHD: the ADHD "
                     "Money Mastery Series, the ADHD Reset Series and the Late-Diagnosed Workbooks."
                     % len(books), "/books/"),
        schema=schema(graph), count=len(books), shelves="\n".join(shelves))


# ---------------------------------------------------------------- glossary

def render_glossary(terms, by_post, by_book):
    path = "/glossary/"
    url = SITE + path
    letters, blocks, current = [], [], None

    for t in terms:
        letter = re.sub(r"^the\s+", "", t["term"], flags=re.I)[0].upper()
        if letter != current:
            if current:
                blocks.append("    </section>")
            current = letter
            letters.append(letter)
            blocks.append('    <section class="az-letter" id="letter-%s"><h2>%s</h2>' % (letter.lower(), letter))

        see = []
        for target in t.get("see") or []:
            m = re.match(r"^/(blog|books)/([^/]+)/$", target)
            if not m:
                fail("glossary term '%s' links to '%s', which is not a /blog/ or /books/ page." % (t["term"], target))
            source = by_post if m.group(1) == "blog" else by_book
            if m.group(2) not in source:
                fail("glossary term '%s' links to missing page %s." % (t["term"], target))
            see.append('<a href="%s">%s</a>' % (target, esc(source[m.group(2)]["title"])))

        aka = ""
        if t.get("aka"):
            aka = '<p class="term-aka">Also called: %s</p>' % esc(", ".join(t["aka"]))
        blocks.append(
            '      <div class="term" id="%s"><h3><a href="#%s">%s</a></h3>%s<p>%s</p>%s</div>'
            % (t["slug"], t["slug"], esc(t["term"]), aka, inline(t["definition"]),
               '<p class="term-see">Read more: %s</p>' % " · ".join(see) if see else ""))
    if current:
        blocks.append("    </section>")

    defined = []
    for t in terms:
        node = {"@type": "DefinedTerm", "@id": url + "#" + t["slug"], "name": t["term"],
                "description": plain(t["definition"]), "url": url + "#" + t["slug"],
                "inDefinedTermSet": {"@id": url + "#terms"}}
        if t.get("aka"):
            node["alternateName"] = t["aka"]
        if t.get("entity"):
            node["sameAs"] = WIKI + ENTITIES[t["entity"]][1]
        defined.append(node)

    graph = [
        {"@type": "DefinedTermSet", "@id": url + "#terms",
         "name": "Glossary of ADHD and autism terms", "url": url,
         "description": "Plain-language definitions of ADHD, autism and AuDHD terms.",
         "inLanguage": "en-US", "creator": {"@id": PERSON_ID}, "hasDefinedTerm": defined},
        {"@type": "WebPage", "@id": url, "url": url, "name": "ADHD and Autism Glossary",
         "isPartOf": {"@id": WEBSITE_ID}, "mainEntity": {"@id": url + "#terms"}, "inLanguage": "en-US"},
        person_node(),
        breadcrumbs((AUTHOR, "/"), ("Glossary", path)),
    ]
    return render(
        "glossary.html",
        seo=seo_head("ADHD & Autism Glossary: %d Terms in Plain Words — J.M. Struijk" % len(terms),
                     "Plain definitions of %d ADHD and autism terms: masking, stimming, AuDHD, rejection "
                     "sensitive dysphoria, time blindness, the ADHD tax and more." % len(terms), path),
        schema=schema(graph),
        count=len(terms),
        az="".join('<a href="#letter-%s">%s</a>' % (l.lower(), l) for l in letters),
        terms="\n".join(blocks),
        disclaimer=esc(DISCLAIMER),
    )


def render_404(posts, books):
    recent = "\n".join('      <li><a href="/blog/%s/">%s</a></li>' % (p["slug"], esc(p["title"]))
                       for p in posts[:6])
    return render("404.html", book_count=len(books), post_count=len(posts), recent=recent)


# ---------------------------------------------------------------- homepage

def replace_block(text, name, inner):
    start, end = "<!-- BUILD:%s:START -->" % name, "<!-- BUILD:%s:END -->" % name
    if start not in text or end not in text:
        fail("index.html is missing the %s markers." % name)
    pattern = re.escape(start) + r".*?" + re.escape(end)
    return re.sub(pattern, lambda m: start + "\n" + inner + "\n    " + end, text, count=1, flags=re.S)


def home_catalogue(books):
    blocks = []
    for series, (anchor, colour, _) in SERIES.items():
        group = [b for b in books if b["series"] == series]
        if not group:
            continue
        cards = []
        for b in group:
            badge = ""
            if b.get("badge"):
                cls, label = BADGES[b["badge"]]
                badge = '\n            <div class="badge %s">%s</div>' % (cls, label)
            w, h = b["cover_size"]
            cards.append("""        <a href="/books/{slug}/" class="book" aria-label="{title}">
          <div class="book-cover">
            <img src="/assets/covers/{slug}.jpg" alt="{title} book cover" loading="lazy" width="{w}" height="{h}">{badge}
          </div>
          <div class="book-meta">
            <div class="book-title">{title}</div>
            <div class="book-subtitle">{tagline}</div>
            <div class="book-link">About the book</div>
          </div>
        </a>""".format(slug=b["slug"], title=esc(b["title"]), tagline=esc(b["tagline"]),
                       w=w, h=h, badge=badge))
        blocks.append("""    <div class="series-block" id="{anchor}" data-reveal>
      <div class="series-header">
        <h3 class="series-name"><span class="series-color-dot" style="background:{colour};"></span>{series}</h3>
        <span class="series-meta">{n} book{s}</span>
      </div>
      <div class="book-grid">

{cards}

      </div>
    </div>""".format(anchor=anchor, colour=colour, series=esc(series), n=len(group),
                     s="" if len(group) == 1 else "s", cards="\n\n".join(cards)))
    return "\n\n".join(blocks)


def home_posts(posts):
    # Hand-picked articles first (featured: 1, 2, ...), then the newest.
    featured = sorted((p for p in posts if p.get("featured")), key=lambda p: p["featured"])
    rest = [p for p in posts if not p.get("featured")]
    chosen = (featured + rest)[:6]
    cards = "\n".join(
        """      <a class="home-post" href="/blog/{slug}/">
        <span class="home-post-meta">{mins} min read</span>
        <span class="home-post-title">{title}</span>
        <span class="home-post-desc">{desc}</span>
      </a>""".format(slug=p["slug"], mins=minutes(p["words"]), title=esc(p["title"]),
                     desc=esc(p["description"])) for p in chosen)
    return """  <section class="home-posts" id="articles">
    <div class="section-intro" data-reveal>
      <span class="section-tag">From the blog</span>
      <h2>Writing on ADHD and autism, <em>from the inside.</em></h2>
      <p>
        Long-form articles on the things nobody explained to me plainly: the ADHD tax, rejection sensitivity, masking, burnout, and why starting is the hardest part.
      </p>
    </div>
    <div class="home-posts-grid" data-reveal>
{cards}
    </div>
    <div class="home-posts-more"><a href="/blog/">All {n} articles &rarr;</a> <a href="/glossary/">The glossary &rarr;</a></div>
  </section>""".format(cards=cards, n=len(posts))


def home_schema(text, books):
    m = re.search(r'(<script type="application/ld\+json">\n)(.*?)(\n</script>)', text, re.S)
    if not m:
        fail("index.html has no JSON-LD block.")
    data = json.loads(m.group(2))
    graph = [n for n in data["@graph"] if n.get("@type") not in ("Book", "ItemList")]

    book_nodes = []
    for b in books:
        node = {"@type": "Book", "@id": SITE + "/books/%s/#book" % b["slug"], "name": b["title"],
                "alternateName": "%s: %s" % (b["title"], b["subtitle"]),
                "author": {"@id": PERSON_ID}, "publisher": {"@id": PUBLISHER_ID},
                "url": SITE + "/books/%s/" % b["slug"], "sameAs": [amazon(b["asin"])],
                "image": "%s/assets/covers/%s.jpg" % (SITE, b["slug"]),
                "datePublished": str(b["published"]), "inLanguage": "en",
                "identifier": {"@type": "PropertyValue", "propertyID": "ASIN", "value": b["asin"]}}
        if b["series"] != "Standalone":
            node["isPartOf"] = {"@type": "BookSeries", "name": b["series"]}
            if b.get("position"):
                node["position"] = b["position"]
        book_nodes.append(node)
    itemlist = {"@type": "ItemList", "@id": SITE + "/#books", "name": "Books by J.M. Struijk",
                "numberOfItems": len(books),
                "itemListElement": [{"@type": "ListItem", "position": i + 1,
                                     "url": SITE + "/books/%s/" % b["slug"], "name": b["title"]}
                                    for i, b in enumerate(books)]}

    at = next((i + 1 for i, n in enumerate(graph) if n.get("@type") == "WebPage"), len(graph))
    graph[at:at] = book_nodes + [itemlist]
    for n in graph:
        if n.get("@type") == "Person":
            n["sameAs"] = [AMAZON_AUTHOR]
    data["@graph"] = graph
    block = json.dumps(data, indent=2, ensure_ascii=False).replace("</", "<\\/")
    return text[:m.start(2)] + block + text[m.end(2):]


def build_homepage(posts, books):
    text = open(os.path.join(ROOT, "index.html"), encoding="utf-8").read()
    text = replace_block(text, "CATALOGUE", home_catalogue(books))
    text = replace_block(text, "POSTS", home_posts(posts))
    return home_schema(text, books)


# ------------------------------------------------- feeds, sitemap, llms

def render_feed(posts):
    items = []
    for p in posts:
        url = "%s/blog/%s/" % (SITE, p["slug"])
        pub = datetime.strptime(str(p["date"]), "%Y-%m-%d").replace(tzinfo=timezone.utc)
        body = re.sub(r'href="/', 'href="%s/' % SITE, p["body"]).replace("]]>", "]]&gt;")
        items.append(
            "    <item>\n"
            "      <title>%s</title>\n"
            "      <link>%s</link>\n"
            '      <guid isPermaLink="true">%s</guid>\n'
            "      <pubDate>%s</pubDate>\n"
            "      <dc:creator>J.M. Struijk</dc:creator>\n"
            "      <description>%s</description>\n"
            "      <content:encoded><![CDATA[%s]]></content:encoded>\n"
            "    </item>"
            % (esc(p["title"]), url, url, pub.strftime("%a, %d %b %Y %H:%M:%S +0000"),
               esc(p["description"]), body))
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom" '
            'xmlns:content="http://purl.org/rss/1.0/modules/content/" '
            'xmlns:dc="http://purl.org/dc/elements/1.1/">\n'
            "  <channel>\n"
            "    <title>J.M. Struijk on ADHD and autism</title>\n"
            "    <link>%s/blog/</link>\n"
            '    <atom:link href="%s/blog/feed.xml" rel="self" type="application/rss+xml"/>\n'
            "    <description>Practical writing on ADHD, autism, and AuDHD from a late-diagnosed author.</description>\n"
            "    <language>en-us</language>\n%s\n  </channel>\n</rss>\n"
            % (SITE, SITE, "\n".join(items)))


def render_sitemap(posts, books, glossary_date):
    home_date = mtime_date(os.path.join(ROOT, "index.html"))
    newest_post = max(str(p.get("updated") or p["date"]) for p in posts)
    newest_book = max(b["modified"] for b in books)

    def entry(path, lastmod, freq, priority, images=()):
        imgs = "".join("\n    <image:image><image:loc>%s</image:loc></image:image>" % i for i in images)
        return ("  <url>\n    <loc>%s%s</loc>\n    <lastmod>%s</lastmod>\n"
                "    <changefreq>%s</changefreq>\n    <priority>%s</priority>%s\n  </url>"
                % (SITE, path, lastmod, freq, priority, imgs))

    cover = lambda b: "%s/assets/covers/%s.jpg" % (SITE, b["slug"])
    urls = [entry("/", max(home_date, newest_post, newest_book), "weekly", "1.0", [cover(b) for b in books]),
            entry("/books/", newest_book, "monthly", "0.9", [cover(b) for b in books])]
    urls += [entry("/books/%s/" % b["slug"], b["modified"], "monthly", "0.9", [cover(b)]) for b in books]
    urls.append(entry("/blog/", newest_post, "weekly", "0.9"))
    urls += [entry("/blog/%s/" % p["slug"], str(p.get("updated") or p["date"]), "monthly", "0.8",
                   [og_image("post", p["slug"])] if og_image("post", p["slug"]) != DEFAULT_OG else [])
             for p in posts]
    urls.append(entry("/glossary/", glossary_date, "monthly", "0.8"))
    urls.append(entry("/adhd-tax-worksheets/",
                      mtime_date(os.path.join(ROOT, "adhd-tax-worksheets", "index.html")), "yearly", "0.5"))
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"\n'
            '        xmlns:image="http://www.google.com/schemas/sitemap-image/1.1">\n'
            + "\n".join(urls) + "\n</urlset>\n")


def first_sentence(text):
    text = plain(text)
    m = re.match(r"(.+?[.!?])(\s|$)", text)
    return m.group(1) if m else text


def render_llms(posts, books, terms):
    groups = []
    for series in SERIES:
        group = [b for b in books if b["series"] == series]
        if not group:
            continue
        lines = ["### " + series, ""]
        for b in group:
            extra = " Book %d." % b["position"] if b.get("position") else ""
            lines.append("- [%s](%s/books/%s/): %s.%s Published %s. Amazon: %s"
                         % (b["title"], SITE, b["slug"], b["tagline"], extra, b["published"], amazon(b["asin"])))
        groups.append("\n".join(lines))
    books_md = "## Books\n\n" + "\n\n".join(groups)
    articles_md = "\n".join("- [%s](%s/blog/%s/): %s. Published %s."
                            % (p["title"], SITE, p["slug"], p["description"].rstrip("."), p["date"])
                            for p in posts)
    glossary_md = "\n".join("- [%s](%s/glossary/#%s): %s" % (t["term"], SITE, t["slug"], first_sentence(t["definition"]))
                            for t in terms)
    tpl = open(os.path.join(TEMPLATES, "llms.md"), encoding="utf-8").read()
    return tpl.format(book_count=len(books), post_count=len(posts), term_count=len(terms),
                      books=books_md, articles=articles_md, glossary=glossary_md)


def absolute_links(markdown):
    return re.sub(r"\]\(/", "](%s/" % SITE, markdown)


def render_llms_full(llms, posts, books, terms):
    parts = [llms.rstrip(), "", "---", "", "# Full text", ""]
    for b in books:
        parts += ["## Book: %s" % b["title"], "",
                  "URL: %s/books/%s/" % (SITE, b["slug"]),
                  "Subtitle: %s" % b["subtitle"],
                  "Series: %s" % series_label(b),
                  "Published: %s" % b["published"],
                  "Amazon: %s" % amazon(b["asin"]), "",
                  absolute_links(b["markdown"]).replace("\n## ", "\n### "), ""]
    for p in posts:
        parts += ["## Article: %s" % p["title"], "",
                  "URL: %s/blog/%s/" % (SITE, p["slug"]),
                  "Published: %s" % p["date"],
                  "Summary: %s" % p["description"], "",
                  absolute_links(p["markdown"]).replace("\n## ", "\n### "), ""]
    parts += ["## Glossary", ""]
    for t in terms:
        parts += ["### %s" % t["term"], "", plain(t["definition"]), ""]
    return "\n".join(parts).rstrip() + "\n"


# ---------------------------------------------------------------- checks

def check_links(pages, known, anchors):
    """Every root-relative href must resolve to a page or a file on disk."""
    errors = []
    for page_path, page in pages.items():
        for href in set(re.findall(r'href="(/[^"]*)"', page)):
            target, _, anchor = href.partition("#")
            if target in known:
                if anchor and target in anchors and anchor not in anchors[target]:
                    errors.append("%s links to missing anchor %s" % (page_path, href))
                continue
            on_disk = os.path.join(ROOT, target.lstrip("/"))
            if target.endswith("/"):
                on_disk = os.path.join(on_disk, "index.html")
            if not os.path.exists(on_disk):
                errors.append("%s links to missing %s" % (page_path, href))
    if errors:
        fail("broken internal links:\n  " + "\n  ".join(sorted(errors)))


# ---------------------------------------------------------------- share images

def find_chrome():
    for candidate in (os.environ.get("CHROME"),
                      "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                      shutil.which("google-chrome"), shutil.which("chromium"),
                      shutil.which("chromium-browser")):
        if candidate and os.path.exists(candidate):
            return candidate
    return None


def topic_label(keys):
    keys = keys or []
    if "adhd" in keys and "autism" in keys:
        return "ADHD & autism"
    return "Autism" if "autism" in keys else "ADHD"


def render_og_images(posts, books, force):
    chrome = find_chrome()
    if not chrome:
        print("share images skipped: Chrome not found (set CHROME to its path)")
        return
    out_dir = os.path.join(ROOT, "assets", "og")
    os.makedirs(out_dir, exist_ok=True)
    tpl = open(os.path.join(TEMPLATES, "og.html"), encoding="utf-8").read()
    css = "file://" + os.path.join(TEMPLATES, "og.css")

    jobs = [("post", p["slug"], p["title"], "Article · " + topic_label(p.get("about")), p.get("book"))
            for p in posts]
    jobs += [("book", b["slug"], b["title"], "Book · " + SERIES[b["series"]][2], b["slug"]) for b in books]

    made = 0
    for kind, slug, title, kicker, cover_slug in jobs:
        out = os.path.join(out_dir, "%s-%s.jpg" % (kind, slug))
        if os.path.exists(out) and not force:
            continue
        cover = os.path.join(ROOT, "assets", "covers", "%s.jpg" % cover_slug) if cover_slug \
            else os.path.join(ROOT, "og-image.jpg")
        size = 66 if len(title) < 40 else 58 if len(title) < 60 else 50 if len(title) < 80 else 44
        doc = tpl.format(css=css, kicker=esc(kicker), title=esc(title), size=size, cover="file://" + cover)
        with tempfile.TemporaryDirectory() as tmp:
            src, png = os.path.join(tmp, "og.html"), os.path.join(tmp, "og.png")
            open(src, "w", encoding="utf-8").write(doc)
            subprocess.run([chrome, "--headless=new", "--disable-gpu", "--hide-scrollbars",
                            "--force-device-scale-factor=1", "--virtual-time-budget=9000",
                            "--window-size=1200,630", "--screenshot=" + png, "file://" + src],
                           capture_output=True, timeout=120)
            if not os.path.exists(png):
                print("share image failed: %s-%s" % (kind, slug))
                continue
            if shutil.which("sips"):
                subprocess.run(["sips", "-s", "format", "jpeg", "-s", "formatOptions", "82",
                                png, "--out", out], capture_output=True)
            else:
                shutil.copy(png, out[:-4] + ".png")
        made += 1
    print("share images rendered: %d" % made)


# ---------------------------------------------------------------- main

def write(rel_path, content):
    path = os.path.join(ROOT, rel_path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    open(path, "w", encoding="utf-8").write(content)


def prune(section, keep):
    """Remove generated directories whose source has been deleted."""
    base = os.path.join(ROOT, section)
    if not os.path.isdir(base):
        return
    for name in os.listdir(base):
        path = os.path.join(base, name)
        if os.path.isdir(path) and name not in keep and os.listdir(path) == ["index.html"]:
            shutil.rmtree(path)
            print("removed stale /%s/%s/" % (section, name))


def main():
    args = set(sys.argv[1:])
    books = load_books()
    by_book = {b["slug"]: b for b in books}
    posts = load_posts(by_book)
    by_post = {p["slug"]: p for p in posts}
    terms, glossary_date = load_glossary()

    if "--og" in args or "--og-all" in args:
        render_og_images(posts, books, force="--og-all" in args)

    pages = {"/blog/%s/" % p["slug"]: render_post(p, by_post, by_book) for p in posts}
    pages["/blog/"] = render_blog_index(posts, by_book)
    pages.update({"/books/%s/" % b["slug"]: render_book(b, posts, books) for b in books})
    pages["/books/"] = render_books_index(books)
    pages["/glossary/"] = render_glossary(terms, by_post, by_book)
    home = build_homepage(posts, books)
    not_found = render_404(posts, books)

    known = set(pages) | {"/", "/adhd-tax-worksheets/", "/blog/feed.xml", "/llms.txt", "/llms-full.txt"}
    anchors = {"/glossary/": {t["slug"] for t in terms} | {"letter-" + c for c in "abcdefghijklmnopqrstuvwxyz"}}
    check_links(dict(pages, **{"/": home, "/404.html": not_found}), known, anchors)

    for path, page in pages.items():
        write(path.lstrip("/") + "index.html", page)
    write("index.html", home)
    write("404.html", not_found)
    write("blog/feed.xml", render_feed(posts))
    write("sitemap.xml", render_sitemap(posts, books, glossary_date))
    llms = render_llms(posts, books, terms)
    write("llms.txt", llms)
    write("llms-full.txt", render_llms_full(llms, posts, books, terms))
    prune("blog", set(by_post))
    prune("books", set(by_book))

    words = sum(p["words"] for p in posts)
    print("%d articles (%d words), %d book pages, %d glossary terms, %d pages checked"
          % (len(posts), words, len(books), len(terms), len(pages) + 2))
    print("FAQ questions: %d in articles, %d on book pages"
          % (sum(len(p["faq"]) for p in posts), sum(len(b["faq"]) for b in books)))


if __name__ == "__main__":
    main()
