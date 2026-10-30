#!/usr/bin/env python3
"""Build the generated parts of jmstruijk.com.

    python3 build.py            pages, feed, sitemap, llms files, homepage blocks
    python3 build.py --og       also render share images that are missing (needs Chrome)
    python3 build.py --og-all   re-render every share image
    python3 build.py --check-links   also open every directory link and report breakage

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
# Filled from content/profiles.yaml. These become sameAs on the Person, which is
# how a search engine connects the profiles to this site.
PROFILES = []

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

# How the site describes its author, written once. The author box, the Person in
# structured data, llms.txt and /about/ all read from here, because four hand
# written copies of a bio drift apart the moment one of them changes.
BIO_THIRD = (
    "an autistic author with ADHD, originally diagnosed with Asperger's, and a "
    "single father who raised a child with autism and ADHD"
)
BIO_PERSON = (
    "J.M. Struijk is " + BIO_THIRD + ". He writes practical, non-clinical books "
    "for adults working out what a late diagnosis means day to day."
)

DISCLAIMER = (
    "I write from lived experience as an autistic adult with ADHD, "
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

        # Pipe tables. Comparison tables are the format answer engines and
        # featured snippets quote most readily, so they earn their keep.
        if line.startswith("|") and i + 1 < len(lines) and re.match(r"^\|[\s:|-]+\|$", lines[i + 1].strip()):
            def cells(row):
                return [c.strip() for c in row.strip().strip("|").split("|")]

            head = cells(line)
            i += 2
            body_rows = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                body_rows.append(cells(lines[i]))
                i += 1
            thead = "".join("<th scope=\"col\">%s</th>" % inline(c) for c in head)
            tbody = "".join(
                "<tr>%s</tr>" % "".join(
                    ("<th scope=\"row\">%s</th>" if n == 0 else "<td>%s</td>") % inline(c)
                    for n, c in enumerate(row))
                for row in body_rows)
            out.append('<div class="table-wrap"><table><thead><tr>%s</tr></thead><tbody>%s</tbody></table></div>'
                       % (thead, tbody))
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


def load_posts(by_book, topic_slugs):
    posts = []
    for path in sorted(glob.glob(os.path.join(CONTENT, "posts", "*.md"))):
        name = os.path.relpath(path, ROOT)
        meta, body = read_source(path)
        require(meta, ("title", "slug", "description", "date", "topics"), name)
        if meta.get("book") and meta["book"] not in by_book:
            fail("%s names unknown book '%s'." % (name, meta["book"]))
        for t in meta["topics"]:
            if t not in topic_slugs:
                fail("%s is filed under unknown topic '%s'." % (name, t))
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


def load_profiles():
    entries, _ = load_yaml_list("profiles.yaml")
    for e in entries:
        require(e, ("name", "url"), "profile %r" % e.get("name"))
        if not e["url"].startswith("https://"):
            fail("profile '%s' must use https." % e["name"])
        if "REPLACE" in e["url"]:
            fail("profile '%s' still has a placeholder URL." % e["name"])
    urls = [e["url"] for e in entries]
    if len(set(urls)) != len(urls):
        fail("duplicate profile URLs.")
    return entries


def load_yaml_list(name):
    path = os.path.join(CONTENT, name)
    return yaml.safe_load(open(path, encoding="utf-8")) or [], mtime_date(path)


def load_resources():
    sections, modified = load_yaml_list("resources.yaml")
    ids = [s["id"] for s in sections]
    if len(set(ids)) != len(ids):
        fail("duplicate resource section ids.")
    for s in sections:
        require(s, ("id", "title", "intro", "items"), "resource section %r" % s.get("id"))
        for item in s["items"]:
            require(item, ("name", "url", "description"), "resource %r" % item.get("name"))
            if not item["url"].startswith("https://"):
                fail("resource '%s' must use https." % item["name"])
    return sections, modified


def load_topics(by_book, term_slugs, resource_ids):
    topics = []
    for path in sorted(glob.glob(os.path.join(CONTENT, "topics", "*.md"))):
        name = os.path.relpath(path, ROOT)
        meta, body = read_source(path)
        require(meta, ("slug", "title", "order", "description"), name)
        for b in meta.get("books") or []:
            if b not in by_book:
                fail("%s lists unknown book '%s'." % (name, b))
        for t in meta.get("terms") or []:
            if t not in term_slugs:
                fail("%s lists unknown glossary term '%s'." % (name, t))
        for r in meta.get("resources") or []:
            if r not in resource_ids:
                fail("%s lists unknown resource section '%s'." % (name, r))
        check_about(meta.get("about"), name)
        meta.update(body=render_markdown(body)[0], markdown=body, modified=mtime_date(path))
        topics.append(meta)
    topics.sort(key=lambda t: t["order"])
    return topics


# ---------------------------------------------------------------- shared

PARTIALS = {}
# Filled in by main(): page path -> page title, and topic slug -> topic. Lets any
# page link to any other by path and get the right label.
TITLES = {}
TOPICS = {}


AUTOLINK = []  # (compiled pattern, glossary slug), longest term first.
# Tags whose text should never be turned into a link.
NO_LINK_INSIDE = {"a", "h1", "h2", "h3", "h4", "code", "summary", "figcaption"}


def build_autolinks(terms):
    """Patterns for linking the first mention of each glossary term in a body."""
    names = []
    for t in terms:
        if t.get("autolink") is False:
            continue
        for name in [t["term"]] + list(t.get("aka") or []):
            names.append((name, t["slug"]))
    # Longest first, so "sensory overload" wins before a shorter overlapping term.
    names.sort(key=lambda n: -len(n[0]))
    return [(re.compile(r"\b%s\b" % re.escape(name).replace(r"\ ", r"[\s ]+"), re.I), slug)
            for name, slug in names]


def _link_run(text, used, remaining):
    """Link the first mention of each unused term in one run of plain text.

    All matches are found against the original text and spliced in one pass, so
    a later term can never match inside a link this function just inserted.
    """
    spans = []
    for pattern, slug in AUTOLINK:
        if slug in used:
            continue
        m = pattern.search(text)
        if m:
            spans.append((m.start(), m.end(), slug))
    spans.sort()

    chosen, end_of_last = [], 0
    for start, end, slug in spans:
        if start >= end_of_last and slug not in used and len(chosen) < remaining:
            chosen.append((start, end, slug))
            used.add(slug)
            end_of_last = end
    if not chosen:
        return text, 0

    out, prev = [], 0
    for start, end, slug in chosen:
        out.append(text[prev:start])
        out.append('<a class="gloss" href="/glossary/#%s">%s</a>' % (slug, text[start:end]))
        prev = end
    out.append(text[prev:])
    return "".join(out), len(chosen)


def autolink_glossary(body, skip_slug=None, limit=9):
    """Link first mentions of glossary terms, skipping headings and existing links."""
    if not AUTOLINK:
        return body
    used = {skip_slug} if skip_slug else set()
    out, pos, depth, linked = [], 0, 0, 0

    for tag in re.finditer(r"<[^>]+>", body):
        run = body[pos:tag.start()]
        if depth == 0 and linked < limit and run.strip():
            run, n = _link_run(run, used, limit - linked)
            linked += n
        out.append(run)
        out.append(tag.group(0))
        name = re.match(r"</?([a-zA-Z0-9]+)", tag.group(0))
        if name and name.group(1).lower() in NO_LINK_INSIDE:
            if tag.group(0).startswith("</"):
                depth = max(0, depth - 1)
            elif not tag.group(0).endswith("/>"):
                depth += 1
        pos = tag.end()

    tail = body[pos:]
    if depth == 0 and linked < limit:
        tail, _ = _link_run(tail, used, limit - linked)
    out.append(tail)
    return "".join(out)


def internal_link(path, label=None):
    # Anchored paths such as /resources/#money can have their own title.
    title = TITLES.get(path) or TITLES.get(path.split("#")[0])
    if title is None:
        fail("link to unknown page %s" % path)
    return '<a href="%s">%s</a>' % (path, esc(label or title))


def topic_tags(slugs):
    if not slugs:
        return ""
    return ('<div class="topic-tags"><span>Filed under</span>%s</div>'
            % "".join('<a href="/topics/%s/">%s</a>' % (s, esc(TOPICS[s]["title"])) for s in slugs))


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
            "description": BIO_PERSON,
            "sameAs": [e["url"] for e in PROFILES] or [AMAZON_AUTHOR]}


def publisher_ref():
    return {"@type": "Organization", "@id": PUBLISHER_ID, "name": "JMS Media Group LLC", "url": SITE + "/",
            "logo": {"@type": "ImageObject", "url": SITE + "/assets/images/logo.png",
                     "width": 512, "height": 512}}


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
        <p><strong>J.M. Struijk</strong> is %s. He writes practical companions for the brain you actually have, published independently through JMS Media Group LLC. <a href="/books/">See all the books</a> or read <a href="/about/">more about the author</a>.</p>
      </div>
    </section>""" % BIO_THIRD

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


def cover_frame(book, badge="", eager=False):
    """A cover image in a frame that hugs it, so badges sit on the artwork.

    Covers are not all 2:3; sizing by height keeps every one of them edge to edge.
    """
    w, h = book["cover_size"]
    loading = 'fetchpriority="high"' if eager else 'loading="lazy"'
    # Covers render between about 130px and 250px wide, so a phone should not
    # download the 700px file.
    return ('<span class="cover-frame"><img src="/assets/covers/{slug}.jpg" '
            'srcset="/assets/covers/{slug}-400.jpg 400w, /assets/covers/{slug}.jpg 700w" '
            'sizes="(max-width: 520px) 170px, (max-width: 880px) 220px, 260px" '
            'alt="{title} book cover" width="{w}" height="{h}" {loading} decoding="async">{badge}</span>'
            ).format(slug=book["slug"], title=esc(book["title"]), w=w, h=h,
                     loading=loading, badge=badge)


def book_card(book, heading="h3"):
    return ('<a class="shelf-book" href="/books/{slug}/">'
            '<span class="shelf-cover">{frame}</span>'
            '<{hd} class="shelf-title">{title}</{hd}><span class="shelf-tagline">{tagline}</span></a>'
            ).format(slug=book["slug"], title=esc(book["title"]), tagline=esc(book["tagline"]),
                     frame=cover_frame(book), hd=heading)


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
    return """<aside class="book-cta">
      <a class="book-cta-cover" href="/books/{slug}/">{frame}</a>
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
                       amazon=amazon(book["asin"]), frame=cover_frame(book))


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
            + ('\n<meta property="article:modified_time" content="%s">' % post["updated"] if post.get("updated") else "")
            + '\n<meta property="article:author" content="J.M. Struijk">'
            + '\n<meta property="article:section" content="%s">' % esc(TOPICS[post["topics"][0]]["title"])
            + "".join('\n<meta property="article:tag" content="%s">' % esc(t.strip())
                      for t in post.get("keywords", "").split(",") if t.strip())
            + '\n<meta name="keywords" content="%s">' % esc(post.get("keywords", "")),
        schema=schema(graph),
        title=esc(post["title"]),
        description=esc(post["description"]),
        date_iso=str(post["date"]),
        date_human=human_date(post["date"]),
        reading_time=minutes(post["words"]),
        updated=('<span class="post-dot">·</span><span class="post-updated">Updated %s</span>'
                 % human_date(post["updated"])) if post.get("updated") else "",
        topics=topic_tags(post["topics"]),
        toc=toc,
        body=autolink_glossary(post["body"]),
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
        schema=schema(graph), count=len(posts), cards="\n".join(cards),
        topic_chips='<nav class="topic-chips" aria-label="Browse by topic">%s</nav>'
                    % "".join('<a href="/topics/%s/">%s</a>' % (t["slug"], esc(t["title"]))
                              for t in TOPICS.values()))


# ---------------------------------------------------------------- books

def render_book(book, posts, books):
    path = "/books/%s/" % book["slug"]
    url = SITE + path
    image = og_image("book", book["slug"])
    title = "%s — Book by J.M. Struijk" % book["title"]

    facts = ['<span>Published %s</span>' % human_date(book["published"])]
    if book.get("pages"):
        facts.append("<span>%d pages</span>" % book["pages"])
    facts.append('<span>By <a href="/about/">J.M. Struijk</a></span>')

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
        cover=cover_frame(book, eager=True),
        title=esc(book["title"]),
        subtitle=esc(book["subtitle"]),
        series_label=esc(series_label(book)),
        facts='<span class="book-facts-sep">·</span>'.join(facts),
        asin=book["asin"],
        body=autolink_glossary(book["body"]),
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

        see = [internal_link(target) for target in t.get("see") or []]

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


# ---------------------------------------------------------------- directory

def resource_item(item):
    region = '<span class="res-region">%s</span>' % esc(item["region"]) if item.get("region") else ""
    detail = '<p class="res-detail">%s</p>' % esc(item["detail"]) if item.get("detail") else ""
    return ('<li class="res-item"><div class="res-head"><a class="res-name" href="%s" target="_blank" '
            'rel="noopener">%s</a>%s</div>%s<p class="res-desc">%s</p></li>'
            % (esc(item["url"]), esc(item["name"]), region, detail, esc(item["description"])))


def resource_section(section, heading="h2"):
    see = '<p class="res-see">Related: %s</p>' % internal_link(section["see"]) if section.get("see") else ""
    return ('<section class="res-section%s" id="%s"><%s>%s</%s><p class="res-intro">%s</p>'
            '<ul class="res-list">%s</ul>%s</section>'
            % (" res-crisis" if section["id"] == "crisis" else "", section["id"], heading,
               esc(section["title"]), heading, esc(section["intro"]),
               "".join(resource_item(i) for i in section["items"]), see))


def render_resources(sections):
    path = "/resources/"
    url = SITE + path
    count = sum(len(s["items"]) for s in sections)
    checked_file = os.path.join(CONTENT, "resources-checked.txt")
    checked = ""
    if os.path.exists(checked_file):
        checked = '<p class="res-checked">Links last checked %s.</p>' % human_date(open(checked_file).read().strip())
    items, n = [], 0
    for s in sections:
        for i in s["items"]:
            n += 1
            node = {"@type": "WebPage", "name": i["name"], "url": i["url"], "description": i["description"]}
            items.append({"@type": "ListItem", "position": n, "item": node})
    graph = [
        {"@type": "CollectionPage", "@id": url, "url": url,
         "name": "ADHD and Autism Resources for Adults", "isPartOf": {"@id": WEBSITE_ID},
         "inLanguage": "en-US", "about": about_nodes(["adhd", "autism"]),
         "mainEntity": {"@type": "ItemList", "numberOfItems": count, "itemListElement": items}},
        person_node(),
        breadcrumbs((AUTHOR, "/"), ("Resources", path)),
    ]
    return render(
        "resources.html",
        seo=seo_head("ADHD & Autism Resources for Adults: Helplines, Assessment, Work",
                     "A checked directory of ADHD and autism organisations, crisis lines, assessment "
                     "guidance, screeners, peer support, work rights and free debt advice.", path),
        schema=schema(graph), count=count, checked=checked,
        jump="".join('<a href="#%s">%s</a>' % (s["id"], esc(s["title"])) for s in sections),
        sections="\n".join(resource_section(s) for s in sections),
        disclaimer=esc(DISCLAIMER))


# ---------------------------------------------------------------- start here

def render_start(situations, by_book):
    path = "/start/"
    chips = "\n".join('      <a href="#%s">%s</a>' % (s["id"], esc(s["chip"])) for s in situations)
    blocks = []
    for s in situations:
        book = by_book[s["book"]]
        blocks.append(
            '    <section class="situation" id="%s"><div class="situation-text"><h2>%s</h2><p>%s</p>'
            '<ul class="situation-links">%s</ul></div>'
            '<a class="situation-book" href="/books/%s/">%s<span><span class="situation-book-label">'
            'The book on this</span><strong>%s</strong></span></a></section>'
            % (s["id"], esc(s["question"]), esc(s["answer"]),
               "".join("<li>%s</li>" % internal_link(l) for l in s["links"]),
               book["slug"], cover_frame(book), esc(book["title"])))
    graph = [
        {"@type": "WebPage", "@id": SITE + path, "url": SITE + path, "name": "Start here",
         "description": "A guide to where to begin, by situation.", "isPartOf": {"@id": WEBSITE_ID},
         "inLanguage": "en-US", "about": about_nodes(["adhd", "autism"])},
        person_node(),
        breadcrumbs((AUTHOR, "/"), ("Start here", path)),
    ]
    return render(
        "start.html",
        seo=seo_head("Start Here: Where to Begin With ADHD, Autism or AuDHD",
                     "Not sure where to start? Pick what is costing you most, from money and burnout to "
                     "overthinking and work, and find the right article and book.", path),
        schema=schema(graph), chips=chips, situations="\n".join(blocks), disclaimer=esc(DISCLAIMER))


# ---------------------------------------------------------------- topics

def render_topic(topic, posts, books, by_book, terms_by_slug, resources_by_id):
    path = "/topics/%s/" % topic["slug"]
    url = SITE + path
    articles = [p for p in posts if topic["slug"] in p["topics"]]

    tool = ""
    if topic.get("tool"):
        tool = ('<aside class="tool-cta"><div><span class="tool-cta-label">Free tool</span>'
                '<strong>%s</strong><p>See roughly what late fees, forgotten subscriptions and impulse buys '
                'cost you, by category.</p></div><a class="btn-amazon" href="%s">Open the calculator</a></aside>'
                % (esc(TITLES[topic["tool"]]), topic["tool"]))

    shelf = ""
    if topic.get("books"):
        shelf = ('<section class="related"><h2>Books</h2><div class="shelf-grid shelf-grid-small">%s</div></section>'
                 % "".join(book_card(by_book[b]) for b in topic["books"]))

    terms = ""
    if topic.get("terms"):
        terms = ('<section class="related"><h2>Key terms</h2><dl class="topic-terms">%s</dl></section>'
                 % "".join('<div><dt><a href="/glossary/#%s">%s</a></dt><dd>%s</dd></div>'
                           % (t, esc(terms_by_slug[t]["term"]), esc(first_sentence(terms_by_slug[t]["definition"])))
                           for t in topic["terms"]))

    help_ = ""
    if topic.get("resources"):
        help_ = ('<section class="related topic-resources"><h2>Organisations and help</h2>%s</section>'
                 % "".join(resource_section(resources_by_id[r], "h3") for r in topic["resources"]))

    others = ('<nav class="topic-chips topic-chips-end" aria-label="Other topics"><span>Other topics</span>%s</nav>'
              % "".join('<a href="/topics/%s/">%s</a>' % (t["slug"], esc(t["title"]))
                        for t in TOPICS.values() if t["slug"] != topic["slug"]))

    graph = [
        {"@type": "CollectionPage", "@id": url, "url": url, "name": topic["title"],
         "description": topic["description"], "isPartOf": {"@id": WEBSITE_ID}, "inLanguage": "en-US",
         "about": about_nodes(topic.get("about")),
         "hasPart": [{"@type": "BlogPosting", "headline": p["title"], "url": SITE + "/blog/%s/" % p["slug"]}
                     for p in articles]},
        person_node(),
        breadcrumbs((AUTHOR, "/"), ("Topics", "/topics/"), (topic["title"], path)),
    ]
    return render(
        "topic.html",
        seo=seo_head("%s — J.M. Struijk" % topic["title"], topic["description"], path,
                     og_image("topic", topic["slug"])),
        schema=schema(graph), title=esc(topic["title"]), description=esc(topic["description"]),
        body=autolink_glossary(topic["body"]), tool=tool, articles=post_cards(articles, "Articles"), books=shelf,
        terms=terms, resources=help_, other_topics=others, disclaimer=esc(DISCLAIMER))


def render_topics_index(topics, posts):
    cards = []
    for t in topics:
        n = sum(1 for p in posts if t["slug"] in p["topics"])
        cards.append('    <a class="topic-card" href="/topics/%s/"><h2>%s</h2><p>%s</p>'
                     '<span class="topic-count">%d article%s · %d book%s</span></a>'
                     % (t["slug"], esc(t["title"]), esc(t["description"]), n, "" if n == 1 else "s",
                        len(t.get("books") or []), "" if len(t.get("books") or []) == 1 else "s"))
    graph = [
        {"@type": "CollectionPage", "@id": SITE + "/topics/", "url": SITE + "/topics/",
         "name": "Topics", "isPartOf": {"@id": WEBSITE_ID}, "inLanguage": "en-US",
         "hasPart": [{"@type": "CollectionPage", "name": t["title"], "url": SITE + "/topics/%s/" % t["slug"]}
                     for t in topics]},
        person_node(),
        breadcrumbs((AUTHOR, "/"), ("Topics", "/topics/")),
    ]
    return render(
        "topics.html",
        seo=seo_head("Topics: ADHD, Autism, Money and Burnout — J.M. Struijk",
                     "Browse articles, books and tools on ADHD and autism by subject: money, everyday ADHD, "
                     "late diagnosis, autism in adults, and burnout.", "/topics/"),
        schema=schema(graph), cards="\n".join(cards))


# ---------------------------------------------------------------- calculator

CALC_PATH = "/tools/adhd-tax-calculator/"

CALC_EXPLAINER = """## What counts as the ADHD tax

The ADHD tax is money that leaves your account because of how your brain works rather than because of anything you chose to buy. Late fees on bills you could afford, subscriptions you meant to cancel, a second charger because the first one is somewhere in the house. None of it is a decision, which is why it rarely shows up as a line in a budget.

The seven categories here come from the ADHD Tax Calculator worksheet in Chapter 1 of [The ADHD Tax](/books/adhd-tax/). If you prefer paper, the same worksheet is in the free [printable worksheets](/adhd-tax-worksheets/).

## Reading your result

The ten-year figure is there to make the number concrete, not to make you feel bad. Most people find the total is larger than they expected and more fixable than they feared, because a handful of sources usually account for most of it.

Start with your top category and nothing else. For most people that means putting bills on autopay or doing one subscription audit. One change that sticks is worth more than a plan to fix everything. The article on [what the ADHD tax costs](/blog/adhd-tax-what-it-costs/) explains each category in more depth.

## Common questions

### What is the ADHD tax?

A community term for the money lost to ADHD-related difficulties: late fees, forgotten subscriptions, replacing things you already own, and paying extra for convenience when the cheaper option had too many steps. It is not an official financial or clinical term.

### Is my information stored or sent anywhere?

Nothing you enter is sent anywhere. The calculation happens in your browser, and your numbers are remembered only on this device, if your browser allows it, so you can come back to them. The Clear button removes them.

### How accurate is the result?

As accurate as your estimates. Working from three months of bank and card statements and dividing by three gives a fair monthly figure. Rough numbers are fine, because the point is to see the pattern.

### Where do the categories come from?

From the ADHD Tax Calculator worksheet in Chapter 1 of The ADHD Tax by J.M. Struijk. The calculator uses the same seven categories so the tool and the book give the same answer.

### What should I do with my total?

Pick the single largest category and fix one thing in it, usually autopay for late fees or a subscription audit for forgotten renewals. The tip shown for each of your top categories is a good first move."""


def render_calculator(categories, by_book):
    fieldsets = []
    for cat in categories:
        rows = "".join(
            '<label class="calc-row"><span>%s</span><input type="text" inputmode="decimal" autocomplete="off" '
            'name="%s-%d" data-cat="%s" placeholder="0"></label>' % (esc(item), cat["id"], i, cat["id"])
            for i, item in enumerate(cat["items"]))
        fieldsets.append(
            '        <fieldset class="calc-cat"><legend>%s</legend><p class="calc-blurb">%s</p>'
            '<div class="calc-rows">%s</div><div class="calc-subtotal">Monthly subtotal '
            '<strong data-subtotal="%s">0</strong></div></fieldset>'
            % (esc(cat["name"]), esc(cat["blurb"]), rows, cat["id"]))
        if cat["link"] not in TITLES:
            fail("calculator category '%s' links to unknown page %s." % (cat["id"], cat["link"]))

    data = json.dumps([{"id": c["id"], "name": c["name"], "tip": c["tip"], "link": c["link"]} for c in categories],
                      ensure_ascii=False).replace("</", "<\\/")
    body, _, _, faq = render_markdown(CALC_EXPLAINER)
    url = SITE + CALC_PATH
    graph = [
        {"@type": "WebApplication", "@id": url + "#app", "name": "ADHD Tax Calculator", "url": url,
         "description": "Estimate what late fees, forgotten subscriptions, impulse buys and lost items cost you "
                        "each month, by category, using the worksheet from The ADHD Tax.",
         "applicationCategory": "FinanceApplication", "operatingSystem": "Any",
         "browserRequirements": "Requires JavaScript", "isAccessibleForFree": True,
         "offers": {"@type": "Offer", "price": "0", "priceCurrency": "USD"},
         "author": {"@id": PERSON_ID}, "about": about_nodes(["adhd"]),
         "isBasedOn": {"@id": SITE + "/books/adhd-tax/#book"}},
        person_node(),
        breadcrumbs((AUTHOR, "/"), ("ADHD and money", "/topics/adhd-and-money/"), ("ADHD Tax Calculator", CALC_PATH)),
        faq_node(url, faq),
    ]
    return render(
        "calculator.html",
        seo=seo_head("ADHD Tax Calculator: What Is ADHD Costing You?",
                     "Free ADHD Tax Calculator: add up late fees, forgotten subscriptions, impulse buys and lost "
                     "items to see your monthly, yearly and ten-year cost.", CALC_PATH, og_image("tool", "adhd-tax-calculator")),
        schema=schema(graph), fieldsets="\n".join(fieldsets), explainer=body, data=data,
        book_cta=book_cta(by_book["adhd-tax"]), author_box=AUTHOR_BOX, disclaimer=esc(DISCLAIMER))


# ---------------------------------------------------------------- about

def render_about(books, posts):
    path = "/about/"
    url = SITE + path
    meta, body = read_source(os.path.join(CONTENT, "about.md"))
    require(meta, ("title", "description"), "content/about.md")
    check_about(meta.get("about"), "content/about.md")
    rendered, _, _, faq = render_markdown(body)

    person = person_node()
    person.update({
        "description": meta["description"],
        "jobTitle": "Author",
        "image": SITE + "/assets/images/author.jpg",
        "mainEntityOfPage": {"@id": url},
        "worksFor": {"@id": PUBLISHER_ID},
        "knowsAbout": ["ADHD in adults", "Autism in adults", "AuDHD", "Late diagnosis of ADHD",
                       "Late diagnosis of autism", "Executive dysfunction", "Autistic burnout",
                       "Masking", "Sensory overload", "ADHD and personal finance"],
    })
    graph = [
        {"@type": "AboutPage", "@id": url, "url": url, "name": meta["title"],
         "description": meta["description"], "isPartOf": {"@id": WEBSITE_ID},
         "inLanguage": "en-US", "mainEntity": {"@id": PERSON_ID}},
        person, publisher_ref(),
        breadcrumbs((AUTHOR, "/"), ("About", path)),
    ]
    shelf = ('<section class="related"><h2>The books</h2><div class="shelf-grid shelf-grid-small">%s</div></section>'
             % "".join(book_card(b) for b in books))
    if len(PROFILES) > 1:
        shelf += ('<section class="related"><h2>Find me elsewhere</h2><ul class="profile-list">%s</ul></section>'
                  % "".join('<li><a href="%s" target="_blank" rel="noopener me">%s</a></li>'
                            % (esc(e["url"]), esc(e["name"])) for e in PROFILES))
    return render(
        "about.html",
        seo=seo_head("About J.M. Struijk, ADHD & Autistic Author", meta["description"], path,
                     og_image("page", "about"), "profile")
            + '\n<meta name="keywords" content="%s">' % esc(meta.get("keywords", "")),
        schema=schema(graph), description=esc(meta["description"]),
        body=autolink_glossary(rendered), shelf=shelf,
        book_count=len(books), post_count=len(posts), disclaimer=esc(DISCLAIMER))


# ---------------------------------------------------------------- tools

SUB_PATH = "/tools/subscription-audit/"

SUB_EXPLAINER = """## Why subscriptions are the ADHD tax at its purest

Nothing about a forgotten subscription was ever a decision. You signed up once, for a reason that was good at the time, and the charge kept arriving because cancelling needs you to remember something boring at a moment when nothing is prompting you.

That is why they are also the most recoverable part. Unlike impulse spending, which needs a system and some self-knowledge, this one is a single afternoon's work with a permanent result. One pass through a statement, a handful of cancellations, and the money stops leaving for good.

## Doing it properly

Work from statements, not memory. Almost everyone underestimates, because the ones you forget are precisely the ones you cannot recall. Check a second card and any payment service you use, since those are where the oldest ones hide.

Watch for annual charges. A yearly renewal will not appear on one month's statement and is usually the largest single item people find. If you can, scan a full year.

Treat "unsure" as a real answer rather than a reason to stop. Mark it, finish the list, and come back. Unsure items are often free trials you forgot converted, and the decision is easier once you can see the yearly figure next to it.

Then cancel the same day. This is the part that fails. A list of subscriptions you intend to cancel is just another [doom pile](/blog/adhd-doom-piles/), and it will still be there in six months. If a cancellation needs a phone call, put that call in the calendar before you close the laptop.

## What to do with the money

Something automatic, ideally the same week, or it will quietly be absorbed. Moving the saved amount into a separate account on a standing order is the version most likely to survive, because it does not depend on you deciding again next month.

## Common questions

### How do I find subscriptions I have forgotten about?

Work through bank and credit card statements line by line rather than from memory, including any second card and payment services such as PayPal. Scan a full year if you can, because annual renewals will not show up in a single month and are usually the biggest items.

### Is my information stored or sent anywhere?

No. The tool runs entirely in your browser, and your list is kept only on this device, if your browser allows it, so you can come back to it. The Clear button removes it.

### Why do people with ADHD accumulate subscriptions?

Because cancelling requires remembering a boring task with no deadline and no prompt, which is the exact shape of task ADHD finds hardest. Each individual charge is small enough to feel not worth the friction, and they compound for the same reason.

### What counts as a subscription?

Anything that recurs without you deciding again: streaming, music, cloud storage, apps, software, memberships, delivery services, insurance add-ons, phone extras, and donations you set up once. Small recurring charges count, since they are the ones that survive.

### What should I do after the audit?

Cancel the cancels the same day, then move the saved amount somewhere automatically. [The ADHD Tax](/books/adhd-tax/) covers the wider pattern, and the [ADHD Tax Calculator](/tools/adhd-tax-calculator/) adds up the rest of it."""


def render_subscription_audit(by_book):
    url = SITE + SUB_PATH
    body, _, _, faq = render_markdown(SUB_EXPLAINER)
    graph = [
        {"@type": "WebApplication", "@id": url + "#app", "name": "Subscription Audit", "url": url,
         "description": "List recurring charges, mark what to cancel, and see what cancelling is worth "
                        "over a year. Built for finding forgotten subscriptions.",
         "applicationCategory": "FinanceApplication", "operatingSystem": "Any",
         "browserRequirements": "Requires JavaScript", "isAccessibleForFree": True,
         "offers": {"@type": "Offer", "price": "0", "priceCurrency": "USD"},
         "author": {"@id": PERSON_ID}, "about": about_nodes(["adhd"])},
        person_node(),
        breadcrumbs((AUTHOR, "/"), ("Tools", "/tools/"), ("Subscription Audit", SUB_PATH)),
        faq_node(url, faq),
    ]
    return render(
        "subscription-audit.html",
        seo=seo_head("Subscription Audit: Find What You Forgot You Pay For",
                     "Free subscription audit tool. List recurring charges, mark what to cancel, and see "
                     "the yearly saving. Nothing leaves your browser.", SUB_PATH,
                     og_image("tool", "subscription-audit")),
        schema=schema(graph), explainer=autolink_glossary(body),
        book_cta=book_cta(by_book["adhd-tax"]), author_box=AUTHOR_BOX, disclaimer=esc(DISCLAIMER))


# The spreadsheet is written by make_budget_xlsx.py and follows The ADHD Budget
# Planner's own structure, so the online tool, the file and the book agree.
BUDGET_PATH = "/tools/adhd-budget-template/"
BUDGET_XLSX = "/assets/downloads/adhd-budget-planner/ADHD-Budget-Template.xlsx"

BUDGET_EXPLAINER = """## Why budgets fail with ADHD

Most budgets ask for the same thing: record every purchase, in the right category, every day, with no end date. That is a daily memory task with no deadline and nothing prompting it, which is close to the worst possible task to hand an ADHD brain. So the budget lasts a few weeks, a busy week arrives, it falls behind, and catching up starts to feel worse than giving up.

The problem in that story is the design. A budget that only works while you are consistent will fail the first time you are not.

## What this template does differently

There are three flexible categories, and that is deliberate. Each category is a decision you have to make at the till, and decisions tend to run out before the money does.

The number you check is weekly. A month is long enough to lose track of entirely, while one figure for the week is something you can carry in your head from Monday to Sunday.

Bills get a due day and an autopay column in place of a daily spending log. For a lot of people with ADHD the costliest mistakes are bills paid late, so the template points your attention at the dates.

It has a line for the [ADHD tax](/blog/adhd-tax-what-it-costs/). Late fees, forgotten subscriptions and buying something twice are going to happen, and a plan that pretends otherwise breaks the first time one does. Giving them a figure means one late fee is already accounted for.

And missing a week costs nothing. The spreadsheet numbers its check-ins instead of dating them, so after a gap you carry on at the next row.

## How to use it

Setting it up takes one sitting, about an hour if you work from statements. Enter what arrives each month after tax, then list every bill with its due day. Use statements for this, not memory, because the bills you forget are exactly the ones you cannot recall.

Then move as many bills as you can onto autopay. Each one you move is a date you no longer have to remember.

After that it is ten minutes a week. Look at the weekly number, compare it with what you spent, and if it is off, change one thing and leave the rest alone. Rebuilding the whole system is usually how a budget gets abandoned.

## Using it in Google Sheets or Excel

Download the template and open it in Excel or Numbers directly. For Google Sheets, open Sheets, choose File, then Import, then Upload, and pick the file. Every total is a formula, so it keeps working once it is in your account.

The spreadsheet has two sheets the online version does not: a weekly check-in numbered for 52 weeks, and an ADHD Tax log for writing down late fees and replacement buys as they happen. A few months of that log shows you where the money actually leaks.

## Common questions

### What is an ADHD-friendly budget?

One designed around how ADHD affects follow-through, instead of one that assumes daily consistency. In practice that means few categories, a weekly figure in place of daily tracking, bills on autopay wherever possible, and a structure that survives a missed week without being rebuilt.

### Is there a free ADHD budget template for Google Sheets?

Yes. The template on this page is a free Excel file that imports into Google Sheets through File, Import, Upload, with its formulas intact. There is no sign-up and no email address needed.

### Does the template work in Excel?

Yes. It is a standard .xlsx file and opens directly in Excel and Numbers. The totals are formulas, so they update as you type.

### Why do I keep giving up on budgets?

Usually because the budget needs daily attention, and the first week that attention slips, the budget falls behind and becomes something to avoid. That is a design problem, not a personal failing. A budget built around a weekly check-in and automated bills has far less to fall behind on.

### How often should I check my budget if I have ADHD?

Once a week, for about ten minutes, is a rhythm a lot of people with ADHD can actually keep. Daily checking tends to collapse within a few weeks, and monthly leaves too long between looks to catch problems early.

### How much should the ADHD tax buffer be?

There is no standard figure, because it depends on your own pattern. The [ADHD Tax Calculator](/tools/adhd-tax-calculator/) adds up what late fees, forgotten subscriptions and replacements actually cost you, which gives a realistic starting number.

### Is my information stored or sent anywhere?

No. The online tool runs entirely in your browser and keeps your figures only on this device, if your browser allows it, so you can come back to them. The Clear button removes them. The spreadsheet lives wherever you save it."""


def render_budget_template(by_book):
    url = SITE + BUDGET_PATH
    body, _, _, faq = render_markdown(BUDGET_EXPLAINER)
    graph = [
        {"@type": "WebApplication", "@id": url + "#app", "name": "ADHD Budget Template", "url": url,
         "description": "A budget built for ADHD: bills with due days and autopay, three flexible "
                        "categories, an ADHD tax line and one weekly spending figure.",
         "applicationCategory": "FinanceApplication", "operatingSystem": "Any",
         "browserRequirements": "Requires JavaScript", "isAccessibleForFree": True,
         "offers": {"@type": "Offer", "price": "0", "priceCurrency": "USD"},
         "author": {"@id": PERSON_ID}, "about": about_nodes(["adhd", "executive-dysfunction"])},
        {"@type": "DigitalDocument", "@id": url + "#spreadsheet", "name": "ADHD Budget Template (.xlsx)",
         "url": SITE + BUDGET_XLSX, "isAccessibleForFree": True, "author": {"@id": PERSON_ID},
         "encodingFormat": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
         "description": "Spreadsheet version for Excel, Numbers and Google Sheets, with a bills list, "
                        "a money map, a 52-week check-in and an ADHD Tax log."},
        person_node(),
        breadcrumbs((AUTHOR, "/"), ("Tools", "/tools/"), ("ADHD Budget Template", BUDGET_PATH)),
        faq_node(url, faq),
    ]
    return render(
        "budget-template.html",
        seo=seo_head("Free ADHD Budget Template for Excel and Google Sheets",
                     "A free ADHD-friendly budget template: bills with due dates and autopay, three flexible "
                     "categories and one weekly number. Use it online or download the spreadsheet.",
                     BUDGET_PATH, og_image("tool", "adhd-budget-template")),
        schema=schema(graph), explainer=autolink_glossary(body),
        book_cta=book_cta(by_book["adhd-budget-planner"]), author_box=AUTHOR_BOX, disclaimer=esc(DISCLAIMER))


TOOLS = [
    (BUDGET_PATH, "ADHD Budget Template",
     "Bills with due days and autopay, three flexible categories and one weekly number. Use it online "
     "or download it for Excel and Google Sheets.", "Interactive and .xlsx"),
    (CALC_PATH, "ADHD Tax Calculator",
     "Add up what late fees, forgotten subscriptions, impulse buys and lost things cost you, by category, "
     "and see it over a year and over ten.", "Interactive"),
    (SUB_PATH, "Subscription Audit",
     "List every recurring charge, mark what goes, and see what cancelling is worth over a year.",
     "Interactive"),
    ("/adhd-tax-worksheets/", "The ADHD Tax printable worksheets",
     "Five printable worksheets from the book: the ADHD Tax Calculator, a money personality quiz, a trigger "
     "map, a 48-hour action plan and a monthly check-in.", "PDF, A4 and US Letter"),
]


def render_tools_index():
    cards = "\n".join(
        '    <a class="topic-card" href="%s"><span class="topic-count">%s</span><h2>%s</h2><p>%s</p></a>'
        % (path, esc(kind), esc(name), esc(blurb)) for path, name, blurb, kind in TOOLS)
    graph = [
        {"@type": "CollectionPage", "@id": SITE + "/tools/", "url": SITE + "/tools/",
         "name": "Free ADHD tools", "isPartOf": {"@id": WEBSITE_ID}, "inLanguage": "en-US",
         "about": about_nodes(["adhd"]),
         "mainEntity": {"@type": "ItemList", "numberOfItems": len(TOOLS),
                        "itemListElement": [{"@type": "ListItem", "position": i + 1,
                                             "url": SITE + p, "name": n}
                                            for i, (p, n, _, _) in enumerate(TOOLS)]}},
        person_node(),
        breadcrumbs((AUTHOR, "/"), ("Tools", "/tools/")),
    ]
    return render(
        "tools.html",
        seo=seo_head("Free ADHD Tools: Budget Template, Tax Calculator and More",
                     "Free tools for adults with ADHD: a budget template for Excel and Google Sheets, an ADHD tax "
                     "calculator, a subscription audit and printable worksheets. No sign-up.", "/tools/"),
        schema=schema(graph), cards=cards)


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
            cards.append("""        <a href="/books/{slug}/" class="book" aria-label="{title}">
          <div class="book-cover">{frame}</div>
          <div class="book-meta">
            <div class="book-title">{title}</div>
            <div class="book-subtitle">{tagline}</div>
            <div class="book-link">About the book</div>
          </div>
        </a>""".format(slug=b["slug"], title=esc(b["title"]), tagline=esc(b["tagline"]),
                       frame=cover_frame(b, badge)))
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
            n["sameAs"] = [e["url"] for e in PROFILES] or [AMAZON_AUTHOR]
        if n.get("@type") == "Organization":
            n["logo"] = {"@type": "ImageObject", "url": SITE + "/assets/images/logo.png",
                         "width": 512, "height": 512}
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


def render_sitemap(posts, books, glossary_date, extra):
    """extra: (path, lastmod, changefreq, priority) for pages outside posts and books."""
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
    urls += [entry(path, lastmod, freq, priority) for path, lastmod, freq, priority in extra]
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


def render_llms(posts, books, terms, topics, resources):
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
    topics_md = "\n".join("- [%s](%s/topics/%s/): %s" % (t["title"], SITE, t["slug"], t["description"])
                          for t in topics)
    resources_md = "\n".join("- [%s](%s/resources/#%s): %d entries, including %s."
                             % (s["title"], SITE, s["id"], len(s["items"]),
                                ", ".join(i["name"] for i in s["items"][:3]))
                             for s in resources)
    tpl = open(os.path.join(TEMPLATES, "llms.md"), encoding="utf-8").read()
    profiles_md = "\n".join("- %s: %s" % (e["name"], e["url"]) for e in PROFILES)
    return tpl.format(profiles=profiles_md,
                      book_count=len(books), post_count=len(posts), term_count=len(terms),
                      books=books_md, articles=articles_md, glossary=glossary_md,
                      topics=topics_md, resources=resources_md,
                      resource_count=sum(len(s["items"]) for s in resources))


def absolute_links(markdown):
    return re.sub(r"\]\(/", "](%s/" % SITE, markdown)


def render_llms_full(llms, posts, books, terms, topics, resources):
    parts = [llms.rstrip(), "", "---", "", "# Full text", ""]
    for t in topics:
        parts += ["## Topic: %s" % t["title"], "", "URL: %s/topics/%s/" % (SITE, t["slug"]), "",
                  absolute_links(t["markdown"]), ""]
    parts += ["## Tool: ADHD Tax Calculator", "", "URL: %s%s" % (SITE, CALC_PATH), "",
              absolute_links(CALC_EXPLAINER).replace("\n## ", "\n### "), ""]
    parts += ["## Tool: ADHD Budget Template", "", "URL: %s%s" % (SITE, BUDGET_PATH),
              "Spreadsheet: %s%s" % (SITE, BUDGET_XLSX), "",
              absolute_links(BUDGET_EXPLAINER).replace("\n## ", "\n### "), ""]
    parts += ["## Resource directory", "", "URL: %s/resources/" % SITE, ""]
    for s in resources:
        parts += ["### %s" % s["title"], "", s["intro"], ""]
        for i in s["items"]:
            region = " (%s)" % i["region"] if i.get("region") else ""
            detail = " %s." % i["detail"] if i.get("detail") else ""
            parts.append("- %s%s: %s%s %s" % (i["name"], region, i["description"], detail, i["url"]))
        parts.append("")
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


def check_external(resources):
    """Open every directory link and report anything moved, gone or unreachable.

    Sites marked blocked refuse automated requests, so a 403 from them is
    reported as unverifiable rather than broken. On a clean run the date is
    recorded and shown on the directory page.
    """
    import urllib.error
    import urllib.request

    ua = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
          "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
    broken, unverifiable, ok = [], [], 0
    for section in resources:
        for item in section["items"]:
            request = urllib.request.Request(item["url"], headers={"User-Agent": ua, "Accept-Language": "en-US,en;q=0.9"})
            try:
                with urllib.request.urlopen(request, timeout=25) as response:
                    final = response.geturl().rstrip("/")
                    if final != item["url"].rstrip("/"):
                        broken.append("%s redirects to %s (update the url)" % (item["url"], response.geturl()))
                    else:
                        ok += 1
            except urllib.error.HTTPError as e:
                if item.get("blocked") and e.code in (403, 429, 503):
                    unverifiable.append(item["url"])
                else:
                    broken.append("%s returned HTTP %d" % (item["url"], e.code))
            except Exception as e:  # DNS failure, timeout, TLS error
                broken.append("%s could not be reached (%s)" % (item["url"], e.__class__.__name__))

    print("external links: %d ok, %d unverifiable (bot protection), %d need attention"
          % (ok, len(unverifiable), len(broken)))
    for u in unverifiable:
        print("  unverifiable: " + u)
    for b in broken:
        print("  ATTENTION: " + b)
    if not broken:
        with open(os.path.join(CONTENT, "resources-checked.txt"), "w") as f:
            f.write(datetime.now().strftime("%Y-%m-%d") + "\n")
    return not broken


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


def render_og_images(posts, books, topics, force):
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
    jobs += [("topic", t["slug"], t["title"], "Topic · " + topic_label(t.get("about")), (t.get("books") or [None])[0])
             for t in topics]
    jobs.append(("tool", "adhd-tax-calculator", "The ADHD Tax Calculator", "Free tool", "adhd-tax"))
    jobs.append(("tool", "subscription-audit", "The Subscription Audit", "Free tool", "adhd-tax"))
    jobs.append(("tool", "adhd-budget-template", "The ADHD Budget Template", "Free tool", "adhd-budget-planner"))
    jobs.append(("page", "about", "J.M. Struijk", "About the author", "late-diagnosed-adhd-workbook"))

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

    # Load in dependency order: topics reference books, terms and resources;
    # posts reference books and topics.
    books = load_books()
    by_book = {b["slug"]: b for b in books}
    terms, glossary_date = load_glossary()
    terms_by_slug = {t["slug"]: t for t in terms}
    resources, resources_date = load_resources()
    resources_by_id = {s["id"]: s for s in resources}
    PROFILES.extend(load_profiles())
    AUTOLINK.extend(build_autolinks(terms))
    topics = load_topics(by_book, set(terms_by_slug), set(resources_by_id))
    TOPICS.update((t["slug"], t) for t in topics)
    posts = load_posts(by_book, set(TOPICS))
    by_post = {p["slug"]: p for p in posts}
    situations, start_date = load_yaml_list("start.yaml")
    for s in situations:
        require(s, ("id", "chip", "question", "answer", "links", "book"), "start situation %r" % s.get("id"))
        if s["book"] not in by_book:
            fail("start situation '%s' names unknown book '%s'." % (s["id"], s["book"]))
    calculator, calculator_date = load_yaml_list("calculator.yaml")

    TITLES.update({"/": "Home", "/blog/": "All articles", "/books/": "All books", "/topics/": "Topics",
                   "/glossary/": "Glossary", "/start/": "Start here", "/resources/": "Resources directory",
                   "/about/": "About J.M. Struijk", "/tools/": "Free tools",
                   CALC_PATH: "ADHD Tax Calculator", SUB_PATH: "Subscription Audit",
                   BUDGET_PATH: "ADHD Budget Template",
                   "/adhd-tax-worksheets/": "ADHD Tax printable worksheets"})
    TITLES.update(("/blog/%s/" % p["slug"], p["title"]) for p in posts)
    TITLES.update(("/books/%s/" % b["slug"], b["title"]) for b in books)
    TITLES.update(("/topics/%s/" % t["slug"], t["title"]) for t in topics)
    TITLES.update(("/resources/#%s" % s["id"], s["title"]) for s in resources)

    if "--check-links" in args:
        check_external(resources)
    if "--og" in args or "--og-all" in args:
        render_og_images(posts, books, topics, force="--og-all" in args)

    pages = {"/blog/%s/" % p["slug"]: render_post(p, by_post, by_book) for p in posts}
    pages["/blog/"] = render_blog_index(posts, by_book)
    pages.update({"/books/%s/" % b["slug"]: render_book(b, posts, books) for b in books})
    pages["/books/"] = render_books_index(books)
    pages["/glossary/"] = render_glossary(terms, by_post, by_book)
    pages.update({"/topics/%s/" % t["slug"]: render_topic(t, posts, books, by_book, terms_by_slug, resources_by_id)
                  for t in topics})
    pages["/topics/"] = render_topics_index(topics, posts)
    pages["/start/"] = render_start(situations, by_book)
    pages["/resources/"] = render_resources(resources)
    pages[CALC_PATH] = render_calculator(calculator, by_book)
    pages[SUB_PATH] = render_subscription_audit(by_book)
    pages[BUDGET_PATH] = render_budget_template(by_book)
    pages["/tools/"] = render_tools_index()
    pages["/about/"] = render_about(books, posts)
    home = build_homepage(posts, books)
    not_found = render_404(posts, books)

    known = set(pages) | {"/", "/adhd-tax-worksheets/", "/blog/feed.xml", "/llms.txt", "/llms-full.txt"}
    anchors = {"/glossary/": set(terms_by_slug) | {"letter-" + c for c in "abcdefghijklmnopqrstuvwxyz"},
               "/resources/": set(resources_by_id),
               "/start/": {s["id"] for s in situations}}
    check_links(dict(pages, **{"/": home, "/404.html": not_found}), known, anchors)

    for path, page in pages.items():
        write(path.lstrip("/") + "index.html", page)
    write("index.html", home)
    write("404.html", not_found)
    write("blog/feed.xml", render_feed(posts))
    newest_topic = max(t["modified"] for t in topics)
    write("sitemap.xml", render_sitemap(posts, books, glossary_date, [
        ("/start/", start_date, "monthly", "0.9"),
        ("/topics/", newest_topic, "monthly", "0.8"),
    ] + [("/topics/%s/" % t["slug"], t["modified"], "monthly", "0.8") for t in topics] + [
        ("/resources/", resources_date, "monthly", "0.8"),
        ("/about/", mtime_date(os.path.join(CONTENT, "about.md")), "monthly", "0.8"),
        ("/tools/", calculator_date, "monthly", "0.8"),
        (CALC_PATH, calculator_date, "monthly", "0.9"),
        (SUB_PATH, mtime_date(os.path.join(ROOT, "assets", "subscription-audit.js")), "monthly", "0.9"),
        (BUDGET_PATH, mtime_date(os.path.join(ROOT, "assets", "budget-template.js")), "monthly", "0.9"),
    ]))
    llms = render_llms(posts, books, terms, topics, resources)
    write("llms.txt", llms)
    write("llms-full.txt", render_llms_full(llms, posts, books, terms, topics, resources))
    prune("blog", set(by_post))
    prune("books", set(by_book))
    prune("topics", set(TOPICS))

    words = sum(p["words"] for p in posts)
    print("%d articles (%d words), %d book pages, %d topics, %d glossary terms, %d directory entries"
          % (len(posts), words, len(books), len(topics), len(terms), sum(len(s["items"]) for s in resources)))
    gloss_links = sum(p.count('class="gloss"') for p in pages.values())
    print("glossary cross-links inserted: %d" % gloss_links)
    print("%d pages link-checked; FAQ questions: %d in articles, %d on book pages"
          % (len(pages) + 2, sum(len(p["faq"]) for p in posts), sum(len(b["faq"]) for b in books)))


if __name__ == "__main__":
    main()
