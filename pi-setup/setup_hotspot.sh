#!/bin/bash
# Iron Sight — Pi Zero W2 WiFi Hotspot Setup
# Run once on the Pi: bash setup_hotspot.sh
# After reboot, Pi broadcasts "ironside" network on 192.168.4.1
# Connect game laptop to "ironside", open shooting-gallery.html — done.

set -e

SSID="ironside"
PASS="ironsight"   # change if you want
COUNTRY="GB"       # change to your country code

echo "==> Installing hostapd + dnsmasq..."
sudo apt update -q
sudo apt install -y hostapd dnsmasq

echo "==> Stopping services while we configure..."
sudo systemctl stop hostapd 2>/dev/null || true
sudo systemctl stop dnsmasq 2>/dev/null || true

# ── Static IP for wlan0 (AP interface) ──────────────────
echo "==> Setting static IP 192.168.4.1 on wlan0..."
sudo tee /etc/dhcpcd.conf.d/ironside.conf > /dev/null <<EOF
interface wlan0
    static ip_address=192.168.4.1/24
    nohook wpa_supplicant
EOF

# dhcpcd reads /etc/dhcpcd.conf — append if not already there
if ! grep -q "ironside.conf" /etc/dhcpcd.conf; then
    echo "conf-dir=/etc/dhcpcd.conf.d" | sudo tee -a /etc/dhcpcd.conf
fi
sudo mkdir -p /etc/dhcpcd.conf.d

# ── DHCP server (gives laptop an IP when it connects) ───
echo "==> Configuring dnsmasq..."
sudo mv /etc/dnsmasq.conf /etc/dnsmasq.conf.bak 2>/dev/null || true
sudo tee /etc/dnsmasq.conf > /dev/null <<EOF
interface=wlan0
dhcp-range=192.168.4.10,192.168.4.50,255.255.255.0,24h
EOF

# ── Access point config ──────────────────────────────────
echo "==> Configuring hostapd (SSID: $SSID)..."
sudo tee /etc/hostapd/hostapd.conf > /dev/null <<EOF
interface=wlan0
driver=nl80211
ssid=$SSID
hw_mode=g
channel=6
wmm_enabled=0
macaddr_acl=0
auth_algs=1
ignore_broadcast_ssid=0
wpa=2
wpa_passphrase=$PASS
wpa_key_mgmt=WPA-PSK
wpa_pairwise=TKIP
rsn_pairwise=CCMP
country_code=$COUNTRY
EOF

sudo sed -i 's|#DAEMON_CONF=""|DAEMON_CONF="/etc/hostapd/hostapd.conf"|' \
    /etc/default/hostapd

# ── Enable and start ─────────────────────────────────────
echo "==> Enabling services..."
sudo systemctl unmask hostapd
sudo systemctl enable hostapd
sudo systemctl enable dnsmasq

echo ""
echo "==> Done. Rebooting in 5 seconds..."
echo "    After reboot:"
echo "    - WiFi network: $SSID"
echo "    - Password:     $PASS"
echo "    - Pi IP:        192.168.4.1 (fixed, always)"
echo "    - WebSocket:    ws://192.168.4.1:8765"
echo ""
sleep 5
sudo reboot
