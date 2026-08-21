// proxy-exchange.js
//
// Roda nessa VPS (fora dos EUA) e repassa chamadas às APIs de exchange
// que bloqueiam IPs da AWS/Netlify por país (Bybit e Binance bloqueiam
// via CloudFront geo-restriction). O Netlify manda a requisição já
// pronta (URL de destino, método, headers com a assinatura, corpo) e
// esse proxy só repassa de verdade pra exchange, devolvendo a resposta
// exatamente como veio.
//
// SEGURANÇA:
//   - Exige o header x-proxy-secret batendo com PROXY_SECRET (variável
//     de ambiente) — sem isso, qualquer um que descobrisse essa URL
//     poderia usar como "proxy aberto" pra qualquer requisição HTTP
//     (risco de SSRF). NUNCA rode isso sem PROXY_SECRET configurado.
//   - Só repassa pra domínios na lista branca (Bybit/Binance) — não
//     aceita repassar pra qualquer URL arbitrária.
//
// Como rodar (com pm2, recomendado — reinicia sozinho se cair):
//   npm install -g pm2          (se ainda não tiver)
//   PROXY_SECRET=<gere uma string aleatória longa> pm2 start proxy-exchange.js --name exchange-proxy
//   pm2 save
//   pm2 startup                 (deixa rodando mesmo se a VPS reiniciar)
//
// Ou direto, pra testar:
//   PROXY_SECRET=minha-senha-de-teste PORT=8181 node proxy-exchange.js
//
// IMPORTANTE — abra a porta no firewall da VPS (ex: ufw allow 8181), mas
// SEM expor pra internet sem HTTPS na frente se possível. O ideal é
// colocar um nginx com certificado TLS (Let's Encrypt) na frente dessa
// porta e apontar o Netlify pra https://seu-dominio/proxy em vez do IP
// direto na porta 8181 — assim a senha (x-proxy-secret) não trafega em
// texto puro pela internet. Se não tiver domínio disponível pra isso
// ainda, pelo menos troque PROXY_SECRET por algo bem longo e aleatório
// enquanto usa só HTTP.

const http = require('http');
const https = require('https');
const { URL } = require('url');

const PORT = process.env.PORT || 8181;
const PROXY_SECRET = process.env.PROXY_SECRET;

const DOMINIOS_PERMITIDOS = [
  'api.bybit.com', 'api-testnet.bybit.com',
  'fapi.binance.com', 'testnet.binancefuture.com',
];

if (!PROXY_SECRET) {
  console.error('[proxy-exchange] PROXY_SECRET não configurado — defina a variável de ambiente antes de rodar. Encerrando.');
  process.exit(1);
}

const server = http.createServer((req, res) => {
  if (req.method !== 'POST' || req.url !== '/proxy') {
    res.writeHead(404, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({ erro: 'not found' }));
    return;
  }
  if (req.headers['x-proxy-secret'] !== PROXY_SECRET) {
    res.writeHead(401, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({ erro: 'unauthorized' }));
    return;
  }

  let corpoRecebido = '';
  req.on('data', (chunk) => { corpoRecebido += chunk; });
  req.on('end', () => {
    let payload;
    try {
      payload = JSON.parse(corpoRecebido);
    } catch (e) {
      res.writeHead(400, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ erro: 'corpo não é JSON válido' }));
      return;
    }

    let alvo;
    try {
      alvo = new URL(payload.url);
    } catch (e) {
      res.writeHead(400, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ erro: 'url inválida' }));
      return;
    }
    if (!DOMINIOS_PERMITIDOS.includes(alvo.hostname)) {
      res.writeHead(403, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ erro: 'domínio não permitido: ' + alvo.hostname }));
      return;
    }

    const mod = alvo.protocol === 'https:' ? https : http;
    const upstreamReq = mod.request(alvo, {
      method: payload.method || 'GET',
      headers: payload.headers || {},
      timeout: 15000,
    }, (upstreamRes) => {
      let dados = '';
      upstreamRes.on('data', (c) => { dados += c; });
      upstreamRes.on('end', () => {
        res.writeHead(upstreamRes.statusCode || 502, { 'Content-Type': 'application/json' });
        res.end(dados);
      });
    });

    upstreamReq.on('timeout', () => upstreamReq.destroy(new Error('timeout')));
    upstreamReq.on('error', (err) => {
      if (res.headersSent) return;
      res.writeHead(502, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ erro: 'Falha ao repassar pra exchange: ' + err.message }));
    });

    if (payload.body) upstreamReq.write(payload.body);
    upstreamReq.end();
  });
});

server.listen(PORT, () => {
  console.log('[proxy-exchange] rodando na porta ' + PORT + ' — domínios permitidos: ' + DOMINIOS_PERMITIDOS.join(', '));
});
