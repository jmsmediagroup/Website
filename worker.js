// Serves jmstruijk.com from Cloudflare Workers: the static files in this repo, plus the two
// endpoints that used to be Netlify functions.
//
// The repo is published whole, so anything that is source or private working material is refused
// here and, more importantly, never uploaded at all (see .assetsignore). The refusal below is the
// second lock: a file added to the repo later cannot leak just because .assetsignore missed it.

const PRIVATE = [/^\/\.git/, /^\/docs\//, /^\/content\//, /^\/templates\//, /^\/netlify\//, /\.py$/];

const SECURITY = {
  'X-Content-Type-Options': 'nosniff',
  'Referrer-Policy': 'strict-origin-when-cross-origin',
  'X-Frame-Options': 'SAMEORIGIN',
  'Permissions-Policy': 'geolocation=(), microphone=(), camera=(), interest-cohort=()',
};

const YEAR = 31536000;
const WEEK = 604800;
const HOUR = 3600;

// Filenames carry no content hash except the fonts, so HTML is always revalidated while the
// pictures and downloads around it are cached hard. These are the netlify.toml rules.
function cacheControl(p) {
  if (p.startsWith('/assets/fonts/')) return `public, max-age=${YEAR}, immutable`;
  if (p.startsWith('/assets/covers/') || p.startsWith('/assets/images/')) return `public, max-age=${YEAR}`;
  if (p.startsWith('/assets/downloads/') || p.startsWith('/assets/og/') || p === '/og-image.jpg') return `public, max-age=${WEEK}`;
  if (p.endsWith('.css') || p.endsWith('.js')) return `public, max-age=${HOUR}, must-revalidate`;
  if (p === '/robots.txt' || p === '/sitemap.xml' || p === '/llms.txt' || p === '/llms-full.txt' || p === '/blog/feed.xml') {
    return `public, max-age=${HOUR}`;
  }
  return 'public, max-age=0, must-revalidate';
}

// Content types the asset server does not get right on its own.
function contentType(p) {
  if (p === '/blog/feed.xml') return 'application/rss+xml; charset=utf-8';
  if (p === '/sitemap.xml') return 'application/xml; charset=utf-8';
  if (p === '/llms.txt' || p === '/llms-full.txt') return 'text/plain; charset=utf-8';
  return null;
}

const clip = (v, n = 300) => String(v ?? '').slice(0, n);

/** A minimal visitor log, written to the Worker logs. No cookies and no third-party lookups. */
async function visit(request) {
  if (request.method !== 'POST') return new Response(null, { status: 405 });
  let c = {};
  try {
    c = JSON.parse((await request.text()) || '{}');
  } catch {
    return new Response(null, { status: 400 });
  }
  const cf = request.cf || {};
  const record = {
    t: new Date().toISOString(),
    ip: request.headers.get('cf-connecting-ip'),
    city: cf.city,
    region: cf.region,
    country: cf.country,
    page: clip(c.page),
    ref: clip(c.ref),
    ua: clip(request.headers.get('user-agent')),
    langs: clip(c.langs || request.headers.get('accept-language'), 120),
    screen: clip(c.screen, 40),
    viewport: clip(c.viewport, 40),
    tz: clip(c.tz, 60),
    net: clip(c.net, 20),
    touch: Number(c.touch) || 0,
    automated: Boolean(c.webdriver),
  };
  if (c.kind === 'leave') {
    record.seconds = Math.round(Number(c.seconds) || 0);
    record.scroll = Math.round(Number(c.scroll) || 0) + '%';
  }
  console.log((c.kind === 'leave' ? 'LEAVE ' : 'VISIT ') + JSON.stringify(record));
  return new Response(null, { status: 204 });
}

/** Subscribe an email to MailerLite. The key is a Worker secret and never reaches the browser. */
async function subscribe(request, env) {
  const headers = { 'Content-Type': 'application/json' };
  if (request.method !== 'POST') {
    return new Response(JSON.stringify({ error: 'Method not allowed' }), { status: 405, headers });
  }
  const apiKey = env.MAILERLITE_API_KEY;
  if (!apiKey) {
    return new Response(JSON.stringify({ error: 'Email service not configured.' }), { status: 500, headers });
  }
  let email;
  try {
    ({ email } = JSON.parse((await request.text()) || '{}'));
  } catch {
    return new Response(JSON.stringify({ error: 'Invalid request.' }), { status: 400, headers });
  }
  if (!(typeof email === 'string' && /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email))) {
    return new Response(JSON.stringify({ error: 'Please enter a valid email address.' }), { status: 400, headers });
  }
  const groupId = env.MAILERLITE_GROUP_ID || '188108700315027037'; // JMStruijk Readers
  try {
    const res = await fetch('https://connect.mailerlite.com/api/subscribers', {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${apiKey}`,
        'Content-Type': 'application/json',
        Accept: 'application/json',
      },
      // Do NOT send status:'active'. A pre-set status makes MailerLite treat the subscriber as an
      // import, which does not fire "subscriber joins group" automations such as the welcome email.
      body: JSON.stringify({ email, fields: { source: 'jmstruijk.com' }, groups: [groupId] }),
    });
    if (res.ok) return new Response(JSON.stringify({ ok: true }), { status: 200, headers });
    console.error('MailerLite error', res.status, await res.text());
  } catch (err) {
    console.error('MailerLite request failed', err);
  }
  return new Response(JSON.stringify({ error: 'Could not subscribe right now. Please try again.' }), { status: 502, headers });
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const path = url.pathname;

    // One address per page: www and plain http go to https on the bare domain in a single hop.
    const live = url.hostname.endsWith('jmstruijk.com');
    if (live && (url.hostname.startsWith('www.') || url.protocol === 'http:')) {
      url.hostname = url.hostname.replace(/^www\./, '');
      url.protocol = 'https:';
      return Response.redirect(url.toString(), 301);
    }

    if (path === '/api/visit') return visit(request);
    if (path === '/api/subscribe' || path === '/.netlify/functions/subscribe') return subscribe(request, env);

    if (PRIVATE.some((r) => r.test(path))) {
      const res = await env.ASSETS.fetch(new Request(new URL('/404.html', url), request));
      return new Response(res.body, { status: 404, headers: { 'Content-Type': 'text/html; charset=utf-8', ...SECURITY } });
    }

    // Every page lives at a trailing slash. The books print jmstruijk.com/toolkit and link to
    // jmstruijk.com/books/<slug> without one, so those, and any other path without a file
    // extension, get a single permanent redirect instead of the asset server's temporary one.
    if (!path.endsWith('/') && !/\.[a-z0-9]+$/i.test(path)) {
      url.pathname = path + '/';
      return Response.redirect(url.toString(), 301);
    }

    const res = await env.ASSETS.fetch(request);
    const out = new Response(res.body, res);
    for (const [k, v] of Object.entries(SECURITY)) out.headers.set(k, v);
    out.headers.set('Cache-Control', res.status >= 400 ? 'no-cache' : cacheControl(path));
    const ct = contentType(path);
    if (ct) out.headers.set('Content-Type', ct);
    if (path.startsWith('/assets/fonts/')) out.headers.set('Access-Control-Allow-Origin', '*');
    return out;
  },
};
