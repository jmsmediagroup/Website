// Netlify serverless function: subscribe an email to MailerLite.
// The API key is read from the MAILERLITE_API_KEY environment variable and
// never exposed to the browser. Configure it in the Netlify dashboard or via
//   netlify env:set MAILERLITE_API_KEY "<key>"
// Optionally set MAILERLITE_GROUP_ID to assign subscribers to a group.

const GROUP_ID = process.env.MAILERLITE_GROUP_ID || '188108700315027037'; // JMStruijk Readers

exports.handler = async (event) => {
  const headers = { 'Content-Type': 'application/json' };

  if (event.httpMethod !== 'POST') {
    return { statusCode: 405, headers, body: JSON.stringify({ error: 'Method not allowed' }) };
  }

  const apiKey = process.env.MAILERLITE_API_KEY;
  if (!apiKey) {
    return { statusCode: 500, headers, body: JSON.stringify({ error: 'Email service not configured.' }) };
  }

  let email;
  try {
    ({ email } = JSON.parse(event.body || '{}'));
  } catch (e) {
    return { statusCode: 400, headers, body: JSON.stringify({ error: 'Invalid request.' }) };
  }

  const valid = typeof email === 'string' && /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email);
  if (!valid) {
    return { statusCode: 400, headers, body: JSON.stringify({ error: 'Please enter a valid email address.' }) };
  }

  try {
    const res = await fetch('https://connect.mailerlite.com/api/subscribers', {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${apiKey}`,
        'Content-Type': 'application/json',
        'Accept': 'application/json',
      },
      body: JSON.stringify({ email, groups: [GROUP_ID], status: 'active' }),
    });

    // MailerLite returns 200/201 on success, 200 when the subscriber already exists.
    if (res.ok) {
      return { statusCode: 200, headers, body: JSON.stringify({ ok: true }) };
    }

    const detail = await res.text();
    console.error('MailerLite error', res.status, detail);
    return { statusCode: 502, headers, body: JSON.stringify({ error: 'Could not subscribe right now. Please try again.' }) };
  } catch (err) {
    console.error('MailerLite request failed', err);
    return { statusCode: 502, headers, body: JSON.stringify({ error: 'Could not subscribe right now. Please try again.' }) };
  }
};
