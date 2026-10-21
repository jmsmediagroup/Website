# Blog for jmstruijk.com

Date: 2026-10-21

## Goal

Add a blog of 12 long-form articles on ADHD and autism, written in J.M.'s voice,
optimized for search and for citation by AI answer engines. Each article links to
the book that covers its subject in depth.

## Constraints

- The site is static, served by Netlify from the repo root with no build step.
  The blog must not introduce one, so pages are generated locally and committed.
- Python 3.9 locally. `yaml` is available, `markdown` is not, so the generator
  renders the Markdown subset the articles actually use.
- ADHD and autism are health-adjacent subjects. Nothing in these articles may
  present as clinical guidance, and no statistic, study, or citation may be
  invented. Articles draw on lived experience only.
- Prose follows blader/humanizer. Its §8 dash rule defers to the writer's own
  sample, and the existing site copy uses dashes freely, so dashes stay at about
  the site's rate. The other 25 patterns apply in full.

## Structure

```
content/posts/*.md        source, hand-written
templates/*.html          page shells
build.py                  run locally: python3 build.py
assets/blog.css           shared styles, reuses the site's design tokens
blog/index.html           generated listing
blog/<slug>/index.html    generated article
blog/feed.xml             generated RSS
```

`build.py` also rewrites `sitemap.xml` and the blog section of `llms.txt` so
neither can drift from the posts on disk.

## Deriving metadata from content

Schema is generated from the rendered article rather than written separately,
so what a crawler reads and what a reader sees cannot diverge:

- A `## Key takeaways` list becomes the summary box, and feeds the article
  description.
- A `## Common questions` section with `###` questions becomes the visible FAQ
  and the `FAQPage` schema.
- `##` headings become the table of contents.

Frontmatter carries only what cannot be derived: title, description, date,
keywords, the book the article belongs to, and related post slugs. Book details
(title, ASIN, cover, subtitle) live in one table in `build.py`.

## Per-article SEO and GEO

`BlogPosting`, `BreadcrumbList`, and `FAQPage` schema. Canonical, Open Graph,
and Twitter tags. Table of contents, key-takeaways box, author block for
E-E-A-T, internal links to the relevant book and to related articles, and a
visible non-clinical disclaimer in the footer of every post.

## Articles

Each maps to at least one book; all 11 books are covered.

1. What the ADHD tax actually is. The ADHD Tax.
2. Why ADHD brains overspend. The ADHD Tax, The ADHD Budget Workbook.
3. ADHD, debt, and why payoff plans fail. Debt Payoff Workbook, Budget Planner.
4. Hyperfocus without the crash. The ADHD Side Hustle.
5. Diagnosed with ADHD as an adult: the first year. Late-Diagnosed ADHD Workbook.
6. Finding out you are autistic in adulthood. Late-Diagnosed Autistic Workbook.
7. AuDHD: autistic and ADHD at once. Both Late-Diagnosed workbooks.
8. Autistic burnout, ADHD burnout, and depression. Burnout Recovery Guide.
9. Masking, and what it costs. Late-Diagnosed Autistic Workbook.
10. Meal paralysis and forgetting to eat. The ADHD Eating Reset.
11. The 2 a.m. overthinking spiral. The ADHD Overthinking Reset.
12. Decision paralysis. The ADHD Decision Reset.

## Decisions taken

- Posts are dated the day they are published. Backdating would make the blog
  look older than it is.
- The disclaimer is a visible block on each post rather than a linked page.
- No build step on Netlify. A failed build would take the whole site down, and
  the gain is only that Markdown could be committed alone.

## Out of scope

Comments, tags and category pages, author pages beyond the existing About
section, and pagination. Twelve posts do not need pagination, and it can be
added to the listing template when the count justifies it.

## Expansion: books, glossary, share images (same day)

The blog grew into a site-wide content build. `build.py` now also renders:

- `/books/` and a page per book from `content/books/*.md`. Book copy is written
  fresh from each Amazon description, never copied, and states nothing about a
  book's contents that the description does not. Print length appears only where
  Amazon labels it.
- `/glossary/` from `content/glossary.yaml`, with `DefinedTermSet` schema. A
  term's `sameAs` points at Wikipedia only when a dedicated, canonical article
  exists; redirects to a section of another article do not count.
- The homepage catalogue, a "From the blog" block, and the homepage `Book`
  schema, between `BUILD:` markers in `index.html`.
- `llms-full.txt`, `/404.html`, and an RSS feed carrying full article text.
- Share images per article and book (`--og`), rendered with headless Chrome.

Every internal link and glossary anchor is checked before anything is written.
`indexnow.py` submits URLs to IndexNow after a deploy. Six more articles cover
rejection sensitivity, body doubling, time blindness, task paralysis, stimming,
and meltdowns and shutdowns.
