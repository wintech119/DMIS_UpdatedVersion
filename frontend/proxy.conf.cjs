const http = require('node:http');

const backendTarget = 'http://localhost:8001';
const backendAgent = new http.Agent();

function formatUpstream(req) {
  const rawUrl = typeof req.url === 'string' ? req.url : '';
  try {
    const { pathname } = new URL(rawUrl, backendTarget);
    return `${backendTarget}${pathname}`;
  } catch {
    return backendTarget;
  }
}

function createProxyConfig() {
  return {
    target: backendTarget,
    agent: backendAgent,
    secure: false,
    changeOrigin: true,
    ws: false,
    logLevel: 'debug',
    configure(proxy) {
      proxy.on('proxyReq', (proxyReq, req) => {
        console.log(`[proxy] ${req.method} ${formatUpstream(req)}`);
      });

      proxy.on('proxyRes', (proxyRes, req) => {
        console.log(
          `[proxy] ${req.method} ${formatUpstream(req)} (${proxyRes.statusCode})`
        );
      });

      proxy.on('error', (error, req) => {
        const message = error instanceof Error ? error.message : String(error);
        console.error(`[proxy] error ${req.method} ${formatUpstream(req)}: ${message}`);
      });
    },
  };
}

module.exports = {
  '/api': createProxyConfig(),
  '/relief-requests': createProxyConfig(),
  '/eligibility': createProxyConfig(),
  '/packaging': createProxyConfig(),
  '/dashboard': createProxyConfig(),
  '/static': createProxyConfig(),
};
