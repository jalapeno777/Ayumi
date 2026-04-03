from __future__ import annotations

import json
from dataclasses import dataclass
from http.server import HTTPServer, SimpleHTTPRequestHandler
from typing import Any, Optional

from ..services.repository import TradeRepository


_LEADERBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Ayumi Copy Trading — Leaderboard</title>
<style>
  *{margin:0;padding:0;box-sizing:border-box}
  body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:#0d1117;color:#c9d1d9;padding:1rem}
  h1{font-size:1.4rem;margin-bottom:1rem;color:#58a6ff}
  .grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:1rem}
  .card{background:#161b22;border:1px solid #30363d;border-radius:8px;padding:1rem}
  .card h3{color:#58a6ff;font-size:1rem;margin-bottom:.5rem}
  .rank{font-size:1.6rem;font-weight:700;color:#f0883e;margin-bottom:.25rem}
  .stat{display:flex;justify-content:space-between;padding:.25rem 0;border-bottom:1px solid #21262d}
  .stat-label{color:#8b949e;font-size:.85rem}
  .stat-value{font-weight:600;font-size:.85rem}
  .profit{color:#3fb950}
  .loss{color:#f85149}
  .wr{color:#d29922}
  .empty{text-align:center;padding:2rem;color:#8b949e}
</style>
</head>
<body>
<h1>Ayumi Copy Trading Leaderboard</h1>
<div class="grid" id="leaderboard"></div>
<script>
fetch("/api/leaderboard").then(r=>r.json()).then(data=>{
  const el=document.getElementById("leaderboard");
  if(!data.length){el.innerHTML='<div class=\"empty\">No provider data yet</div>';return}
  el.innerHTML=data.map((p,i)=>`
    <div class="card">
      <div class="rank">#${i+1}</div>
      <h3>${p.provider_name}</h3>
      ${p.strategy?`<div style="font-size:.8rem;color:#8b949e;margin-bottom:.5rem">${p.strategy}</div>`:""}
      <div class="stat"><span class="stat-label">Win Rate</span><span class="stat-value wr">${p.win_rate}%</span></div>
      <div class="stat"><span class="stat-label">Total Trades</span><span class="stat-value">${p.total_trades}</span></div>
      <div class="stat"><span class="stat-label">W / L</span><span class="stat-value">${p.wins} / ${p.losses}</span></div>
      <div class="stat"><span class="stat-label">Profit</span><span class="stat-value ${p.total_profit>=0?'profit':'loss'}">$${p.total_profit}</span></div>
      <div class="stat"><span class="stat-label">Followers</span><span class="stat-value">${p.followers_count}</span></div>
    </div>
  `).join("")
}).catch(()=>{document.getElementById("leaderboard").innerHTML='<div class=\"empty\">Error loading data</div>'});
</script>
</body>
</html>"""


@dataclass
class DashboardServer:
    repo: TradeRepository
    host: str = "0.0.0.0"
    port: int = 8080

    def _handler(self) -> type:
        repo = self.repo

        class Handler(SimpleHTTPRequestHandler):
            def do_GET(self) -> None:
                if self.path == "/" or self.path == "/index.html":
                    self._respond(200, "text/html", _LEADERBOARD_HTML)
                elif self.path == "/api/leaderboard":
                    data = repo.get_leaderboard(10)
                    self._respond(200, "application/json", json.dumps(data))
                elif self.path == "/api/signals":
                    data = repo.get_recent_signals(20)
                    self._respond(200, "application/json", json.dumps(data))
                else:
                    self._respond(404, "application/json", '{"error":"not found"}')

            def _respond(self, code: int, content_type: str, body: str) -> None:
                self.send_response(code)
                self.send_header("Content-Type", content_type)
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(body.encode())

            def log_message(self, format: str, *args: Any) -> None:
                pass

        return Handler

    def run(self) -> None:
        server = HTTPServer((self.host, self.port), self._handler())
        print(f"Dashboard running on http://{self.host}:{self.port}")
        server.serve_forever()
