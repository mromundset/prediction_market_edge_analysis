# Deploying the Phase-0 recorder on an always-on host

Goal: run `recorder.py` 24/7 for ≥1–2 weeks (longer is better) so the Phase-1 simulator
has tape spanning full days **through settlement**. The recorder is tiny (~100 MB RAM,
trivial CPU, ~0.5–1.5 GB tape over two weeks) and read-only / no-auth.

> **Do NOT run this on UC Berkeley resources** (OCF, EECS, Savio, SCF, DataHub). Campus
> shells kill post-logout processes and hubs cull idle sessions — and, decisively, the
> Berkeley Acceptable Use Policy prohibits using University IT resources for *personal
> financial gain / commercial purposes*, which a trading-data collector is. Use your own
> cloud account.

## Recommended hosts (pick one)

| Host | Why | Cost |
|---|---|---|
| **DigitalOcean $4 droplet** (via GitHub Student Pack $200 credit) | real VM, systemd, local files, **NYC = us-east for the later live phase** | free ~1 yr |
| **GCP e2-micro** (us-east1), always-free | truly free forever, 1 GB RAM ample | free |
| **Hetzner CAX11** | most reliable budget VM (EU-centric) | ~$3.79/mo |

All three are a normal Ubuntu box; the steps below are identical.

## One-time setup (Ubuntu 22.04/24.04)

```bash
# 1. create a non-root user (skip if your host already gives you one)
sudo adduser --disabled-password --gecos "" mm

# 2. clone the repo
sudo -u mm git clone https://github.com/mromundset/prediction_market_edge_analysis.git /home/mm/repo

# 3. python3 is preinstalled on Ubuntu; the recorder uses only the stdlib. verify:
python3 --version

# 4. tape dir
sudo -u mm mkdir -p /home/mm/tape

# 5. install the service
sudo cp /home/mm/repo/weather_mm_feasibility_exploration/system/deploy/recorder.service \
        /etc/systemd/system/recorder.service
# (edit User/paths in the unit if your username isn't 'mm')
sudo systemctl daemon-reload
sudo systemctl enable --now recorder
```

`Restart=always` + `WantedBy=multi-user.target` means it restarts on crash **and** on
reboot — true unattended operation.

## Operate

```bash
systemctl status recorder          # is it up?
journalctl -u recorder -f          # live log (cycle heartbeats, settlements)
ls -la /home/mm/tape               # books_*.jsonl / trades_*.jsonl / meta.jsonl growing
du -sh /home/mm/tape               # disk usage
```

Heartbeat lines look like: `[HH:MM:SSZ] cycle N: 30 mkts, 30 books, +K trades`, and
`[settle] KXHIGHNY-26JUN12-... -> yes` when a market resolves (this is what unlocks H2).

## Pull the tape back to analyze

Run the simulator on the host directly, or copy the tape to your laptop:

```bash
# on your laptop:
scp -r mm@<host-ip>:/home/mm/tape ./weather_mm_feasibility_exploration/system/tape
cd weather_mm_feasibility_exploration/system && python simulator.py
```

After ~1–2 weeks `meta.jsonl` will hold dozens of settled markets and the simulator's
**H2 PnL/contract** becomes meaningful across all six mode×queue cells.

## Notes / gotchas
- **Disk:** ~0.5–1.5 GB over two weeks at default cadence. Smallest VMs (10–25 GB) are fine.
  To shrink: raise `BOOK_CADENCE_S` (e.g. 30) or lower `BOOK_DEPTH` in `recorder.py`.
- **Crash safety:** the recorder rebuilds its trade-dedup set from the day's file on
  restart, so a reboot loses no trades and creates no duplicates.
- **Heroku / ephemeral-FS PaaS:** not suitable as-is — the local JSONL tape would be wiped
  on dyno restart. Use a real VM (above) for the local-file design.
- **Time:** the recorder uses UTC for file rotation; the VM's clock zone doesn't matter.
