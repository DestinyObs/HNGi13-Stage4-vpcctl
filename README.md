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

Using the plain `vpcctl` command
--------------------------------

You can also invoke the CLI as a simple command `vpcctl` (no `python3` prefix). The repository includes a script with a shebang, so installing or symlinking it into a directory on your PATH enables this UX:

```bash
# Option A: copy into /usr/local/bin (system-wide)
sudo cp vpcctl.py /usr/local/bin/vpcctl
sudo sed -i 's/\r$//' /usr/local/bin/vpcctl   # ensure LF line endings on Linux
sudo chmod +x /usr/local/bin/vpcctl

# Option B: create a symlink to the repo copy (keeps one editable copy)
sudo ln -s "$(pwd)/vpcctl.py" /usr/local/bin/vpcctl
sudo chmod +x vpcctl.py
```

Notes:
- Privileged actions still require root. Use `sudo vpcctl ...` for operations that create namespaces, bridges or iptables rules.
- If you see an error like `/usr/bin/env: 'python3\r': No such file or directory` when running `vpcctl`, normalize line endings with `dos2unix` or `sed -i 's/\r$//' vpcctl.py` before copying.

Automatic policy generation
---------------------------
When you add a subnet (`vpcctl add-subnet`) the CLI will automatically generate a default JSON policy and apply it to the new subnet. Defaults are chosen to make demo HTTP services reachable:

- Ingress: allow TCP 80 and 443; deny TCP 22
- Egress: none by default (keeps outbound open for demos)

The generated policy files are stored in `.vpcctl_data/` and can be inspected or re-applied with `vpcctl apply-policy`.


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
