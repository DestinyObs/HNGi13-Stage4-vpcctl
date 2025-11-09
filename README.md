---
# vpcctl — single‑host VPC simulator
---

vpcctl is a small Python CLI that emulates Virtual Private Clouds on a single Linux host using native Linux networking primitives: network namespaces, veth pairs, bridges and iptables. It's intended for learning, demoing, and local experimentation — not production use.

Table of contents
- Features
- Prerequisites
- Quick start (recommended)
- Common workflows
- Project layout
- Documentation & samples
- Contributing
- License

Features
- Create isolated VPCs (per‑VPC bridge + metadata)
- Create subnets as network namespaces attached to a VPC bridge
- Deploy simple apps (Python HTTP server) inside a namespace for testing
- Peer VPCs (bridge/veth peering + controlled iptables rules)
- NAT (MASQUERADE) for public subnets
- Apply JSON policies (ingress & egress) inside namespaces
- Idempotent host iptables management and deterministic cleanup

Prerequisites
- A Linux host (Ubuntu/Debian recommended) — you must run commands as root (sudo).
- Tools: iproute2 (`ip`, `ip netns`), `iptables`, `bridge-utils` (or iproute2 bridge support), Python 3.

Install on Debian/Ubuntu:

```bash
sudo apt update
sudo apt install -y python3 iproute2 iptables curl tcpdump
```

Quick start (recommended)
1) Run the parser-only check (safe — does not change system state):

```bash
sudo python3 vpcctl.py flag-check
```

2) Dry-run a create to preview commands:

```bash
python3 vpcctl.py --dry-run create demo --cidr 10.11.0.0/16
```

3) Create a VPC, add a subnet and run a test app:

```bash
sudo python3 vpcctl.py create demo --cidr 10.11.0.0/16
sudo python3 vpcctl.py add-subnet demo public --cidr 10.11.1.0/24
sudo python3 vpcctl.py deploy-app demo public --port 8080
```

4) Cleanup when done:

```bash
sudo python3 vpcctl.py delete demo
```

Common workflows
- See `docs/Documentation.md` for the full command reference, policy examples, idempotency notes, and troubleshooting.
- Samples: `docs/samples/` contains example snapshots (iptables, `ip netns`, curl results) that graders can compare against.

Project layout
- `vpcctl.py` — main CLI implementation
- `.vpcctl_data/` — per‑VPC JSON metadata written at runtime
- `policy_examples/` — example policy JSON files
- `docs/` — full documentation and demo checklist

Documentation & samples
- Full usage and examples: `docs/Documentation.md`
- Example outputs to compare against: `docs/samples/`

Contributing
- Pull requests welcome. If you change behavior, please update `docs/README_FULL.md` and add sample outputs to `docs/samples/`.

License
- This project is provided for learning and demonstration; add your preferred license file.
