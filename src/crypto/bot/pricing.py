from __future__ import annotations

_PRICING_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Ayumi Copy Trading — Pricing</title>
<style>
  *{margin:0;padding:0;box-sizing:border-box}
  body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:#0d1117;color:#c9d1d9;padding:1rem}
  h1{font-size:2rem;margin-bottom:1.5rem;color:#58a6ff;text-align:center}
  .subtitle{font-size:1.1rem;margin-bottom:2rem;color:#8b949e;text-align:center}
  .grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:1.5rem;max-width:1200px;margin:0 auto;padding:1rem 0}
  .card{background:#161b22;border:1px solid #30363d;border-radius:12px;padding:1.5rem;transition:transform .2s,border-color .2s}
  .card:hover{transform:translateY(-4px);border-color:#58a6ff}
  .card.elite{border:2px solid #f0883e}
  .card.pro{border:2px solid #d29922}
  .tier{font-size:1.5rem;font-weight:700;margin-bottom:.5rem}
  .tier.elite{color:#f0883e}
  .tier.pro{color:#d29922}
  .tier.starter{color:#58a6ff}
  .tier.free{color:#8b949e}
  .price{font-size:2.5rem;font-weight:700;margin-bottom:.5rem}
  .price.free{font-size:2rem}
  .period{font-size:1rem;color:#8b949e;margin-bottom:1.5rem}
  .cta{width:100%;padding:.875rem 1.5rem;border:none;border-radius:6px;font-size:1rem;font-weight:600;cursor:pointer;transition:background .2s;margin-top:1rem}
  .cta:hover{opacity:.9}
  .cta.free{background:#30363d;color:#c9d1d9}
  .cta.starter{background:#58a6ff;color:#0d1117}
  .cta.pro{background:#d29922;color:#0d1117}
  .cta.elite{background:#f0883e;color:#0d1117}
  .features{margin:1.5rem 0}
  .feature{display:flex;align-items:flex-start;padding:.5rem 0;border-bottom:1px solid #21262d}
  .feature:last-child{border-bottom:none}
  .check{color:#3fb950;font-weight:700;margin-right:.5rem;font-size:1.1rem}
  .feature-text{font-size:.95rem}
  .feature.disabled{color:#484f58;text-decoration:line-through}
  .feature.disabled .check{color:#484f58}
  .highlight{background:#1f2937;border-radius:6px;padding:1rem;margin-top:1rem}
  .highlight-text{font-size:.85rem;color:#58a6ff}
  .popular{position:absolute;top:-12px;left:50%;transform:translateX(-50%);background:#f0883e;color:#0d1117;padding:.25rem .75rem;border-radius:4px;font-size:.85rem;font-weight:600}
  .card-container{position:relative}
  .comparison{max-width:900px;margin:2rem auto;padding:1.5rem;background:#161b22;border-radius:12px;border:1px solid #30363d}
  .comparison h2{font-size:1.3rem;margin-bottom:1rem;color:#58a6ff}
  table{width:100%;border-collapse:collapse}
  th,td{padding:.75rem .5rem;text-align:left;border-bottom:1px solid #21262d}
  th{font-weight:600;color:#58a6ff}
  td{text-align:center}
  td:first-child{text-align:left}
  .yes{color:#3fb950;font-weight:600}
  .no{color:#f85149}
  .limited{color:#d29922}
  @media (max-width:768px){
    h1{font-size:1.5rem}
    .price{font-size:2rem}
    .grid{grid-template-columns:1fr}
    table{font-size:.85rem}
    th,td{padding:.5rem .25rem}
  }
</style>
</head>
<body>
<h1>Ayumi Copy Trading — Pricing</h1>
<p class="subtitle">Choose the plan that fits your trading journey</p>

<div class="grid">
  <div class="card-container">
    <div class="card free">
      <div class="tier free">Free</div>
      <div class="price free">$0<span class="period">/month</span></div>
      <button class="cta free">Get Started</button>
      <div class="features">
        <div class="feature"><span class="check">✓</span><span class="feature-text">Delayed signals (15 min)</span></div>
        <div class="feature"><span class="check">✓</span><span class="feature-text">Basic education content</span></div>
        <div class="feature"><span class="check">✓</span><span class="feature-text">Community read-only access</span></div>
        <div class="feature disabled"><span class="check">✗</span><span class="feature-text">Real-time signals</span></div>
        <div class="feature disabled"><span class="check">✗</span><span class="feature-text">Copy trading</span></div>
        <div class="feature disabled"><span class="check">✗</span><span class="feature-text">Analytics dashboard</span></div>
      </div>
    </div>
  </div>

  <div class="card-container">
    <div class="card starter">
      <div class="tier starter">Starter</div>
      <div class="price">$29<span class="period">/month</span></div>
      <button class="cta starter">Start Free Trial</button>
      <div class="features">
        <div class="feature"><span class="check">✓</span><span class="feature-text">Real-time signals</span></div>
        <div class="feature"><span class="check">✓</span><span class="feature-text">Full community access</span></div>
        <div class="feature"><span class="check">✓</span><span class="feature-text">Daily market updates</span></div>
        <div class="feature"><span class="check">✓</span><span class="feature-text">Signal history</span></div>
        <div class="feature disabled"><span class="check">✗</span><span class="feature-text">Copy trading</span></div>
        <div class="feature disabled"><span class="check">✗</span><span class="feature-text">1-on-1 coaching</span></div>
      </div>
    </div>
  </div>

  <div class="card-container">
    <div class="card pro">
      <div class="tier pro">Pro</div>
      <div class="price">$99<span class="period">/month</span></div>
      <button class="cta pro">Start Free Trial</button>
      <div class="features">
        <div class="feature"><span class="check">✓</span><span class="feature-text">Premium real-time signals</span></div>
        <div class="feature"><span class="check">✓</span><span class="feature-text">Full community access</span></div>
        <div class="feature"><span class="check">✓</span><span class="feature-text">Daily market updates</span></div>
        <div class="feature"><span class="check">✓</span><span class="feature-text">Advanced analytics dashboard</span></div>
        <div class="feature"><span class="check">✓</span><span class="feature-text">1-on-1 coaching (2 hrs/mo)</span></div>
        <div class="feature"><span class="check">✓</span><span class="feature-text">Strategy breakdowns</span></div>
      </div>
      <div class="highlight">
        <div class="highlight-text">Most Popular — Best for serious traders</div>
      </div>
    </div>
  </div>

  <div class="card-container">
    <div class="card elite">
      <div class="tier elite">Elite</div>
      <div class="price">$299<span class="period">/month</span></div>
      <button class="cta elite">Start Free Trial</button>
      <div class="features">
        <div class="feature"><span class="check">✓</span><span class="feature-text">Full portfolio copying</span></div>
        <div class="feature"><span class="check">✓</span><span class="feature-text">Priority real-time signals</span></div>
        <div class="feature"><span class="check">✓</span><span class="feature-text">Full community access</span></div>
        <div class="feature"><span class="check">✓</span><span class="feature-text">Advanced analytics dashboard</span></div>
        <div class="feature"><span class="check">✓</span><span class="feature-text">Priority support</span></div>
        <div class="feature"><span class="check">✓</span><span class="feature-text">1-on-1 coaching (4 hrs/mo)</span></div>
      </div>
      <div class="highlight">
        <div class="highlight-text">For maximum automation and personalized attention</div>
      </div>
    </div>
  </div>
</div>

<div class="comparison">
  <h2>Feature Comparison</h2>
  <table>
    <thead>
      <tr>
        <th>Feature</th>
        <th>Free</th>
        <th>Starter</th>
        <th>Pro</th>
        <th>Elite</th>
      </tr>
    </thead>
    <tbody>
      <tr>
        <td>Real-time signals</td>
        <td class="no">✗</td>
        <td class="yes">✓</td>
        <td class="yes">✓ Premium</td>
        <td class="yes">✓ Priority</td>
      </tr>
      <tr>
        <td>Signal delay</td>
        <td class="limited">15 min</td>
        <td class="yes">None</td>
        <td class="yes">None</td>
        <td class="yes">None</td>
      </tr>
      <tr>
        <td>Daily market updates</td>
        <td class="yes">✓</td>
        <td class="yes">✓</td>
        <td class="yes">✓</td>
        <td class="yes">✓</td>
      </tr>
      <tr>
        <td>Community access</td>
        <td class="limited">Read-only</td>
        <td class="yes">✓</td>
        <td class="yes">✓</td>
        <td class="yes">✓</td>
      </tr>
      <tr>
        <td>Analytics dashboard</td>
        <td class="no">✗</td>
        <td class="no">✗</td>
        <td class="yes">✓ Advanced</td>
        <td class="yes">✓ Advanced</td>
      </tr>
      <tr>
        <td>Copy trading</td>
        <td class="no">✗</td>
        <td class="no">✗</td>
        <td class="no">✗</td>
        <td class="yes">✓ Full</td>
      </tr>
      <tr>
        <td>1-on-1 coaching</td>
        <td class="no">✗</td>
        <td class="no">✗</td>
        <td class="yes">2 hrs/mo</td>
        <td class="yes">4 hrs/mo</td>
      </tr>
      <tr>
        <td>Priority support</td>
        <td class="no">✗</td>
        <td class="no">✗</td>
        <td class="no">✗</td>
        <td class="yes">✓</td>
      </tr>
      <tr>
        <td>Monthly cost</td>
        <td class="yes">$0</td>
        <td class="yes">$29</td>
        <td class="yes">$99</td>
        <td class="yes">$299</td>
      </tr>
    </tbody>
  </table>
</div>

<div style="text-align:center;margin-top:2rem;padding:1rem;color:#8b949e;font-size:.9rem">
  <p>All plans include a 7-day free trial. Cancel anytime.</p>
  <p style="margin-top:.5rem">Questions? Contact us at support@ayumi.com</p>
</div>

<script>
document.querySelectorAll('.cta').forEach(btn => {
  btn.addEventListener('click', (e) => {
    const tier = e.target.closest('.card').querySelector('.tier').textContent.trim();
    alert(`Starting free trial for ${tier} plan. Redirecting to signup...`);
  });
});
</script>
</body>
</html>"""
