#!/usr/bin/env python3
"""
Iron Sight — WiFi captive portal
Runs when hotspot is active. Access at http://10.42.0.1
"""
import subprocess
import time
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import parse_qs

def scan_networks():
    result = subprocess.run(
        ['nmcli', '-t', '-f', 'SSID,SIGNAL,SECURITY', 'device', 'wifi', 'list', '--rescan', 'yes'],
        capture_output=True, text=True
    )
    networks = []
    seen = set()
    for line in result.stdout.strip().split('\n'):
        parts = line.split(':')
        ssid = parts[0].strip()
        signal = parts[1].strip() if len(parts) > 1 else '0'
        security = parts[2].strip() if len(parts) > 2 else ''
        if ssid and ssid not in seen and ssid != 'ironside':
            seen.add(ssid)
            networks.append({'ssid': ssid, 'signal': signal, 'security': security})
    networks.sort(key=lambda x: int(x['signal']) if x['signal'].isdigit() else 0, reverse=True)
    return networks

def connect_wifi(ssid, password):
    result = subprocess.run(
        ['nmcli', 'device', 'wifi', 'connect', ssid, 'password', password],
        capture_output=True, text=True, timeout=30
    )
    return result.returncode == 0

HTML = """<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Iron Sight — Add WiFi</title>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body { font-family: -apple-system, BlinkMacSystemFont, sans-serif; background: #0f0f0f; color: #e0e0e0; padding: 24px; max-width: 480px; margin: 0 auto; }
    h1 { font-size: 1.3rem; color: #fff; margin-bottom: 6px; }
    .sub { color: #666; font-size: 0.85rem; margin-bottom: 20px; }
    .rescan { font-size: 0.8rem; color: #555; text-align: right; margin-bottom: 10px; cursor: pointer; text-decoration: underline; }
    .network { background: #1a1a1a; border: 1px solid #2a2a2a; border-radius: 8px; padding: 14px 16px; margin-bottom: 8px; cursor: pointer; display: flex; align-items: center; justify-content: space-between; }
    .network:hover, .network.selected { border-color: #4caf50; background: #1b3a1e; }
    .ssid { font-size: 0.95rem; }
    .meta { font-size: 0.75rem; color: #666; text-align: right; }
    .pwform { margin-top: 20px; display: none; }
    .pwform.visible { display: block; }
    .pwform label { font-size: 0.8rem; color: #888; display: block; margin-bottom: 6px; }
    .pwform input { width: 100%; background: #1a1a1a; border: 1px solid #2a2a2a; color: #e0e0e0; padding: 10px 14px; border-radius: 6px; font-size: 0.95rem; margin-bottom: 14px; outline: none; }
    .pwform input:focus { border-color: #4caf50; }
    button { width: 100%; background: #4caf50; color: #fff; border: none; padding: 12px; border-radius: 6px; font-size: 1rem; cursor: pointer; font-weight: 600; }
    button:hover { background: #43a047; }
    .msg { padding: 12px 16px; border-radius: 6px; margin-bottom: 16px; font-size: 0.9rem; }
    .msg.err { background: #3a1010; color: #f44336; border: 1px solid #f44336; }
  </style>
</head>
<body>
  <h1>Iron Sight — Add WiFi</h1>
  <p class="sub">Pick a network to save on the Pi</p>
  {message}
  <p class="rescan" onclick="location.reload()">↻ Rescan networks</p>
  <form method="POST" action="/connect">
    <input type="hidden" name="ssid" id="ssid_input">
    {networks_html}
    <div class="pwform" id="pwform">
      <label>Password for <strong id="ssid_label"></strong></label>
      <input type="password" name="password" id="pw" placeholder="WiFi password" autocomplete="new-password">
      <button type="submit">Connect &amp; Save</button>
    </div>
  </form>
  <script>
    document.querySelectorAll('.network').forEach(function(n) {
      n.addEventListener('click', function() {
        document.querySelectorAll('.network').forEach(function(x) { x.classList.remove('selected'); });
        n.classList.add('selected');
        document.getElementById('ssid_input').value = n.dataset.ssid;
        document.getElementById('ssid_label').textContent = n.dataset.ssid;
        document.getElementById('pwform').classList.add('visible');
        document.getElementById('pw').focus();
      });
    });
  </script>
</body>
</html>"""

CONNECTING_PAGE = """<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Connecting…</title>
  <style>
    body {{ font-family: -apple-system, sans-serif; background: #0f0f0f; color: #e0e0e0; padding: 24px; max-width: 480px; margin: 0 auto; }}
    h1 {{ color: #fff; margin-bottom: 16px; }}
    .msg {{ padding: 16px; background: #1b3a1e; border: 1px solid #4caf50; border-radius: 8px; color: #4caf50; line-height: 1.6; }}
  </style>
</head>
<body>
  <h1>Connecting to {ssid}…</h1>
  <div class="msg">
    The Pi is connecting to <strong>{ssid}</strong>. This takes up to 30 seconds.<br><br>
    Once connected, the <strong>ironside</strong> hotspot will disappear.<br>
    Reconnect your device to <strong>{ssid}</strong> and SSH in as normal.
  </div>
</body>
</html>"""


class PortalHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def render(self, networks, message=''):
        nets_html = ''
        for n in networks:
            lock = '🔒 ' if n['security'] and n['security'] not in ('', '--') else ''
            sig = n['signal'] + '%' if n['signal'].isdigit() else '?'
            nets_html += f'<div class="network" data-ssid="{n["ssid"]}"><span class="ssid">{lock}{n["ssid"]}</span><span class="meta">{sig}</span></div>\n'
        html = HTML.replace('{networks_html}', nets_html).replace('{message}', message)
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.end_headers()
        self.wfile.write(html.encode())

    def do_GET(self):
        self.render(scan_networks())

    def do_POST(self):
        length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(length).decode()
        params = parse_qs(body)
        ssid = params.get('ssid', [''])[0]
        password = params.get('password', [''])[0]

        if not ssid or not password:
            self.render(scan_networks(), '<div class="msg err">Select a network and enter a password.</div>')
            return

        # Send response immediately, then connect in background
        page = CONNECTING_PAGE.format(ssid=ssid)
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.end_headers()
        self.wfile.write(page.encode())

        def do_connect():
            time.sleep(0.5)
            connect_wifi(ssid, password)

        threading.Thread(target=do_connect, daemon=True).start()


if __name__ == '__main__':
    print('Iron Sight portal running at http://10.42.0.1')
    HTTPServer(('0.0.0.0', 80), PortalHandler).serve_forever()
