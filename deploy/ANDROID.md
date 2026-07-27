# KYGSMOTO — Android access

KYGSMOTO is a Progressive Web App (PWA). No Play Store build is required.

## On Android phone/tablet

1. Deploy the server on Proxmox LXC or a Windows PC (see README).
2. Open Chrome on Android and go to `http://<server-ip>:8000`.
3. Tap **Add to Home screen** / **Install app**.
4. Launch from the home screen — it runs fullscreen like a native app.

## Tips for shop floor use

- Use landscape for POS / inventory tables.
- Sales File Import accepts camera-uploaded CSV/Excel from Downloads.
- Keep the phone on the same LAN/Wi-Fi as the LXC/Windows host, or expose via reverse proxy (nginx/Caddy) with HTTPS for remote use.
