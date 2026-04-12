---
name: Deployment Target — Oracle Cloud
description: User plans to deploy TreadingBot on Oracle Cloud and leave it running unattended for the month
type: project
---

User intends to deploy TreadingBot on Oracle Cloud (Oracle Free Tier or paid instance) and leave it running autonomously for the rest of the month.

**Why:** Fully hands-off operation — no daily login, no manual intervention after initial setup.

**How to apply:**
- Always design for unattended operation: no prompts, no interactive steps, no manual token refreshes
- Oracle Free Tier (Ampere A1 ARM) gives 4 OCPUs + 24 GB RAM at no cost — more than enough for this bot
- Ensure Docker `restart: unless-stopped` is on all containers so they survive instance reboots
- The automated Kite login (TOTP) is the critical enabler — emphasize ZERODHA_TOTP_SECRET setup
- When suggesting changes, consider that the user cannot SSH in and restart things easily mid-day
- Prefer in-process hot-reload (os.environ) over container restarts where possible
