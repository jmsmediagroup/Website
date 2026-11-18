# jmstruijk.com

A hand-built static site about ADHD and autism: `build.py` renders `content/` into the
committed HTML at the repo root, and the repo root is what gets served.

- Host: Cloudflare Workers (`worker.js`, `wrangler.jsonc`), since 2026-11-18. Deploy with
  `npx wrangler deploy` from this directory. Netlify hosted it until 2026-11-18; that project is
  deleted and its config is out of the repo.
- DNS: Cloudflare (zone `jmstruijk.com`, account Jstruijk@me.com). Namecheap is registrar only,
  and the nameservers are `macy.ns.cloudflare.com` and `nico.ns.cloudflare.com`. Do not remove the
  `google-site-verification` TXT record: the Search Console property is verified through it.
- The site is published whole, so source and private working material must never be served.
  `.assetsignore` keeps `.git`, `docs/`, `content/`, `templates/`, `netlify/` and the `.py` files
  out of the Worker's asset store, and `PRIVATE` in `worker.js` refuses the same paths at request
  time in case something new slips past the list. Check both when adding a directory.
- Two endpoints used to be Netlify functions and now live in `worker.js`:
  `/api/visit` writes a line to the Worker logs for each arrival and departure (read them under
  Workers, jmstruijk, Logs), and `/api/subscribe`, also served at the old
  `/.netlify/functions/subscribe` path the pages still call, adds an email to MailerLite.
  The MailerLite key is a Worker secret, not in this repo: `npx wrangler secret put
  MAILERLITE_API_KEY`. Without it that endpoint answers "Email service not configured."
- One address per page: `worker.js` sends www and plain http to `https://jmstruijk.com` in a single
  301, and the workers.dev subdomain is off so the site has no second indexable copy.
- Cache and security headers are set in `worker.js` (`cacheControl`), carried over from the old
  `netlify.toml`: HTML always revalidates, fingerprinted fonts are immutable for a year, pictures
  and downloads are cached hard.
