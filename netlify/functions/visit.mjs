// Netlify function: a minimal visitor log, written to the function logs.
// Read it in the Netlify dashboard under Logs, Functions, visit. Each line is
// "VISIT {...}" on arrival and "LEAVE {...}" when the tab closes, with the
// network (IP), city, browser, device, referrer and, on leave, time and scroll.
// No cookies and no third-party lookups: paste an IP into ipinfo.io by hand to
// see which network or company it belongs to. Netlify keeps function logs only
// briefly, so nothing accumulates here.

const clip = (v, n = 300) => String(v ?? '').slice(0, n);

export default async (req, context) => {
  if (req.method !== 'POST') return new Response(null, { status: 405 });

  let c = {};
  try {
    c = JSON.parse((await req.text()) || '{}');
  } catch (e) {
    return new Response(null, { status: 400 });
  }

  const geo = context.geo || {};
  const record = {
    t: new Date().toISOString(),
    ip: context.ip,
    city: geo.city,
    region: geo.subdivision?.name,
    country: geo.country?.name,
    page: clip(c.page),
    ref: clip(c.ref),
    ua: clip(req.headers.get('user-agent')),
    langs: clip(c.langs || req.headers.get('accept-language'), 120),
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
};

export const config = { path: '/api/visit' };
