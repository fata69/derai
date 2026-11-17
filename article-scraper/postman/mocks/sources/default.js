const http = require('http');
http.createServer(async (req, res) => {
  if (req.url === '/rss') {
    res.setHeader('Content-Type', 'application/rss+xml');
    return res.end('<rss><channel><item><title>Banjir Jakarta</title><link>https://news.example/berita/real</link><pubDate>Tue, 17 Nov 2026 10:00:00 +0700</pubDate></item></channel></rss>');
  }
  if (req.url === '/v1/chat/completions' && req.method === 'POST') {
    let raw = '';
    for await (const chunk of req) raw += chunk;
    const body = typeof req.body === 'object' ? req.body : JSON.parse(raw || '{}');
    if (!Array.isArray(body.messages) || body.model !== 'fixture') {
      res.writeHead(400, {'Content-Type': 'application/json'});
      return res.end(JSON.stringify({error: 'invalid_request'}));
    }
    res.setHeader('Content-Type', 'application/json');
    return res.end(JSON.stringify({choices: [{message: {content: '{"ids":[0]}'}}]}));
  }
  res.writeHead(501, {'Content-Type': 'application/json'});
  res.end(JSON.stringify({error: 'unmodeled_call'}));
}).listen(process.env.PORT);
