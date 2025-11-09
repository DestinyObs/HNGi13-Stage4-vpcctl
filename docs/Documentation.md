vpcctl — single-host VPC simulator (namespaces, bridges, veths, iptables)
==============================================================

Purpose
vpcctl — single-host VPC simulator (namespaces, bridges, veths, iptables)
==============================================================

Purpose
-------
This repository implements a minimal, single‑host Virtual Private Cloud (VPC) simulator called `vpcctl`. It uses Linux network namespaces, veth pairs and bridges, plus iptables and NAT, to emulate isolated VPCs on one host. It's designed for teaching, testing and demos — not production networking.

What changed since the previous README
-------------------------------------
You asked for a README that exactly matches the current `vpcctl.py` behavior and documents flags, idempotency, and policy features. This file has been audited and corrected to reflect the script's actual capabilities:

- Matches the implemented CLI flags (positional and preferred flag forms).
- Documents the global `--dry-run` behavior and `flag-check` parser-only command.
- Explains idempotency: iptables existence checks and comment matches, and the recorded host rule format used for deletion.
- Documents `apply-policy` supporting both `ingress` and `egress` rules, with an example JSON in `policy_examples/`.

Prerequisites
-------------
Host: a Linux machine (Ubuntu VM recommended). You must run the commands as root (sudo). The script is written for Python 3.

Install common packages (run on the Linux VM):

```bash
sudo apt update
sudo apt install -y python3 python3-pip iproute2 iptables curl tcpdump
```

Quick sanity checks (no changes)
-------------------------------

Parser-only check (safe — no system changes):

```bash
sudo python3 vpcctl.py flag-check
```

Automatic policy generation
---------------------------

When a subnet is created with `add-subnet`, `vpcctl` now auto-generates a default JSON policy and applies it to the new subnet. This ensures the subnet has a sensible default for demos and graders so services like HTTP work immediately.

Defaults applied on `add-subnet`:
- Ingress: allow TCP ports 80 and 443; deny TCP port 22
- Egress: none by default (to avoid blocking outbound connectivity during demos)

The generated policy files are saved under the workspace `.vpcctl_data/` directory with names like `policy_<vpc>_<subnet>_<cidr>.json`. You can inspect, modify or re-apply them using the `apply-policy` subcommand.

To view the auto-generated policy for a specific subnet:

```bash
ls -l .vpcctl_data/policy_<vpc>_<subnet>_*.json
cat .vpcctl_data/policy_<vpc>_<subnet>_10.11.1.0_24.json
```

To re-apply or test a policy manually:

```bash
sudo python3 vpcctl.py apply-policy <vpc> .vpcctl_data/policy_<vpc>_<subnet>_<cidr>.json
```

Dry-run mode (global `--dry-run`) prints commands without executing them:

```bash
python3 vpcctl.py --dry-run create myvpc --cidr 10.10.0.0/16
```

Command reference (full, with flags)
-----------------------------------
The CLI accepts both legacy positional arguments and preferred flag forms for ergonomics. The most important commands and their flag variants:

- create <name> [cidr]
	- Positional: sudo python3 vpcctl.py create myvpc 10.10.0.0/16
	- Flag:       sudo python3 vpcctl.py create myvpc --cidr 10.10.0.0/16

- add-subnet <vpc> <name> [cidr] [--gw <ip>]
	- Positional: sudo python3 vpcctl.py add-subnet myvpc public 10.10.1.0/24
	- Flag:       sudo python3 vpcctl.py add-subnet myvpc public --cidr 10.10.1.0/24 --gw 10.10.1.1

- deploy-app <vpc> <subnet> [port]
	- Positional: sudo python3 vpcctl.py deploy-app myvpc public 8080
	- Flag:       sudo python3 vpcctl.py deploy-app myvpc public --port 8080
	- Note: launched with `nohup` inside the namespace; PID and cmd are recorded.

- enable-nat <vpc> <iface>
	- Positional: sudo python3 vpcctl.py enable-nat myvpc eth0
	- Flag:       sudo python3 vpcctl.py enable-nat myvpc --interface eth0

- peer <vpc1> <vpc2> [--allow-cidrs x,y]
	- sudo python3 vpcctl.py peer vpcA vpcB --allow-cidrs 10.10.1.0/24,10.20.1.0/24
	- Default allow-list: both VPC CIDRs when omitted.

- apply-policy <vpc> <policy.json>
	- sudo python3 vpcctl.py apply-policy myvpc policy_examples/example_ingress_egress_policy.json
	- Policy supports `ingress` (INPUT) and `egress` (OUTPUT).

- test-connectivity <target> [port] [--from-ns <ns>]
	- sudo python3 vpcctl.py test-connectivity 10.10.1.5 80 --from-ns ns-myvpc-public

- stop-app <vpc> [--ns <ns>] [--pid <pid>]
- delete <vpc>
- cleanup-all
- list, inspect, verify, run-demo, flag-check

Behavioral details and safety
------------------------------------

1) Idempotent host iptables changes
 - Before adding a host-level iptables rule the script checks for existence (it replaces `-A`/`-I` with `-C` and runs iptables to detect presence). If the rule exists the add is skipped.
 - When adding host rules the script injects a comment matcher (`-m comment --comment "vpcctl:<info>"`) and records that exact tokenized command in metadata. That makes deletion more reliable.

2) Deletion strategy
 - `delete` reads recorded `host_iptables` command lists and attempts deletion by replacing `-A`/`-I` with `-D`. If comments are present it also tries variants with the comment stripped. This is a robust, best-effort removal.

3) Policies
 - `apply_policy` writes rules inside the namespace (so they're scoped to the subnet). It supports `ingress` and `egress` sections in JSON.

4) Naming & truncation
 - The helper `safe_ifname()` sanitizes and truncates names to respect kernel interface name limits (~15 chars). Use short logical names for VPCs/subnets to keep generated names readable.

5) Background apps
 - `deploy-app` uses a shell `nohup` invocation and echoes the background PID; that PID is parsed and recorded. Logs written to `/tmp/vpcctl-<ns>-http.log`.

Metadata format (precisely)
---------------------------
Each VPC metadata file `.vpcctl_data/vpc_<name>.json` contains keys:

- name (str)
- cidr (str)
- bridge (str)
- subnets (list of {name, cidr, ns, gw, host_ip, veth})
- host_iptables (list of token lists; includes comment tokens when added)
- chain (str) — per-VPC iptables chain name
- apps (list of {ns, port, pid, cmd})
- peers (list of peer records)
- nat (dict with interface)

Policy JSON example
-------------------
File: `policy_examples/example_ingress_egress_policy.json`

```json
{
	"subnet": "10.10.1.0/24",
	"ingress": [
		{"port": 80, "protocol": "tcp", "action": "allow"},
		{"port": 22, "protocol": "tcp", "action": "deny"}
	],
	"egress": [
		{"port": 80, "protocol": "tcp", "action": "allow"},
		{"port": 25, "protocol": "tcp", "action": "deny"}
	]
}
```

Precise testing steps (run as root)
----------------------------------

1) Parser and dry-run

```bash
sudo python3 vpcctl.py flag-check
python3 vpcctl.py --dry-run create demo --cidr 10.11.0.0/16
```

2) Create VPC and subnet, deploy app

```bash
sudo python3 vpcctl.py create t1_vpc --cidr 10.30.0.0/16
sudo python3 vpcctl.py add-subnet t1_vpc public --cidr 10.30.1.0/24
sudo python3 vpcctl.py deploy-app t1_vpc public --port 8080
```

3) Enable NAT and verify

```bash
sudo python3 vpcctl.py enable-nat t1_vpc --interface eth0
sudo iptables -t nat -L -n -v | grep MASQUERADE
```

4) Peer idempotency check

```bash
sudo python3 vpcctl.py create t2_vpc --cidr 10.40.0.0/16
sudo python3 vpcctl.py add-subnet t2_vpc public --cidr 10.40.1.0/24
sudo python3 vpcctl.py peer t1_vpc t2_vpc --allow-cidrs 10.30.1.0/24,10.40.1.0/24
# repeat: second run should skip adding duplicates
sudo python3 vpcctl.py peer t1_vpc t2_vpc --allow-cidrs 10.30.1.0/24,10.40.1.0/24
sudo iptables -S vpc-t1_vpc | sed -n '1,200p'
```

5) Policy test (ingress+egress)

```bash
sudo python3 vpcctl.py apply-policy t1_vpc policy_examples/example_ingress_egress_policy.json
chmod +x policy_test.sh
sudo ./policy_test.sh ns-t1_vpc-public 10.30.1.1 80   # expected OK
sudo ./policy_test.sh ns-t1_vpc-public 10.30.1.1 25   # expected FAIL if policy denies
```

6) Cleanup

```bash
sudo python3 vpcctl.py delete t1_vpc
sudo python3 vpcctl.py delete t2_vpc
# or
sudo python3 vpcctl.py cleanup-all
```

Troubleshooting
-----------------------

- Must run as root: many operations require capabilities only root has.
- iptables comment support: host rules are added with `-m comment --comment` — ensure `xt_comment` is available on your kernel (usually true on mainstream distros).
- IFNAMSIZ: interface name too long — use shorter VPC/subnet names to avoid truncation surprises.
- Deploy-app PID not present: check `/tmp/vpcctl-<ns>-http.log` for server errors.
- If delete fails to remove a rule because it was manually changed, inspect `sudo iptables -S` and remove by hand.

Files you should know
---------------------

- `vpcctl.py` — main CLI (read top-of-file docstring and function comments)
- `.vpcctl_data/` — recorded metadata per VPC
- `policy_examples/example_ingress_egress_policy.json` — example policy
- `policy_test.sh` — small helper to curl from a namespace
- `docs/demo_checklist.md` — one-page demo script

Safety considerations
---------------------
- This tool modifies the host network stack and requires root. Use in disposable test VMs.
- NAT and iptables changes affect global host firewall rules. The script tries to be conservative and record what it changes for cleanup, but manual inspection is recommended before running on production hosts.
