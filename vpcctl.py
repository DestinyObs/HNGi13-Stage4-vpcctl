#!/usr/bin/env python3
"""vpcctl - single-host VPC 

This script is my practical toolkit for creating reproducible, isolated VPC-like
environments on a single Linux host. It uses network namespaces, veth pairs and
bridges plus iptables for access control. The design goals were:

- Be small and explicit: each operation prints the commands it runs and stores
    a minimal JSON metadata file in `.vpcctl_data/` so the state is reproducible.
- Keep operations idempotent where reasonable (creation skips existing things,
    iptables rules are checked before insertion).
- Make cleanup deterministic: metadata records host-level iptables commands so
    delete can try to remove exactly what was added.

File organization (logical parts)
1) Small helpers and filesystem/arg parsing utilities
2) iptables helpers (existence checks, comment injection, add/delete wrappers)
3) Core VPC lifecycle: create_vpc, add_subnet, delete_vpc, cleanup_all
4) Features: enable_nat, create_peer, apply_policy
5) App lifecycle: deploy_app, stop_app, test_connectivity
6) Verification, demo orchestration and CLI wiring

Important safety notes
- This script must be run as root. It modifies host networking (interfaces, rules)
    and can break connectivity if misused. Use `--dry-run` to preview commands.
- iptables comment matching is relied upon for robust deletion; if you manually
    edit rules, delete may not remove them automatically.

No behavior changes are made in this refactor — only comments and structural
organization to make the code easier to reason about years from now.
"""

import argparse
import json
import os
import subprocess
import sys
import ipaddress
from pathlib import Path

WORKDIR = Path.cwd() / ".vpcctl_data"
WORKDIR.mkdir(parents=True, exist_ok=True)


def safe_ifname(parts, prefix="", suffix="", maxlen=15):
    """Create a safe interface name: join parts with '-', replace invalid chars,
    and truncate so prefix+name+suffix <= maxlen.

    parts: list or tuple of string parts to join
    prefix: string to prepend (e.g., 'v-' or 'vbr-')
    suffix: string to append (e.g., 'a' or 'b')
    maxlen: maximum total length (kernel limit ~15)
    """
    import re
    if isinstance(parts, (list, tuple)):
        core = '-'.join(str(p) for p in parts if p is not None)
    else:
        core = str(parts)
    # replace invalid chars with '-'
    core = re.sub(r'[^A-Za-z0-9-]', '-', core)
    # collapse multiple dashes
    core = re.sub(r'-{2,}', '-', core)
    # calculate available length for core
    avail = maxlen - len(prefix) - len(suffix)
    if avail <= 0:
        # fallback: return truncated prefix+suffix
        return (prefix + suffix)[:maxlen]
    if len(core) > avail:
        core = core[:avail]
    return f"{prefix}{core}{suffix}"


# ---------------------------------------------------------------------------
# Helpers: small, reusable utility functions
# These are intentionally compact and documented for future-me. They do not
# change system state and are safe to read/execute in --dry-run mode.
# ---------------------------------------------------------------------------


def run(cmd, check=True, capture_output=False, dry=False):
    print(f">>> {' '.join(cmd)}")
    if dry:
        return None
    return subprocess.run(cmd, check=check, capture_output=capture_output)


def require_root():
    if os.geteuid() != 0:
        print("vpcctl: must be run as root (sudo)")
        sys.exit(2)


def check_commands():
    for c in ("ip", "bridge", "iptables"):
        if not shutil.which(c):
            print(f"vpcctl: required command '{c}' not found in PATH")
            sys.exit(2)


import shutil


# ---------------------------------------------------------------------------
# iptables helpers
# Small wrappers to keep iptables usage consistent across the script. They
# provide: existence checks, optional comment injection (for deterministic
# removal), and robust deletion attempts. These helpers avoid changing the
# command semantics used elsewhere in the file.
# ---------------------------------------------------------------------------


def vpc_metadata_path(name: str) -> Path:
    p = WORKDIR / f"vpc_{name}.json"
    return p


def vpc_exists(name: str) -> bool:
    return vpc_metadata_path(name).exists()


def save_vpc_meta(name: str, meta: dict):
    p = vpc_metadata_path(name)
    with open(p, "w") as f:
        json.dump(meta, f, indent=2)


def load_vpc_meta(name: str) -> dict:
    p = vpc_metadata_path(name)
    if not p.exists():
        raise FileNotFoundError(p)
    return json.load(open(p))


def list_vpcs():
    return [p.stem.replace("vpc_", "") for p in WORKDIR.glob("vpc_*.json")]


def _iptables_rule_exists(cmd: list) -> bool:
    """Return True if the provided iptables command (with -A/-I) already exists.

    This replaces the first -A/-I with -C and runs it. Returns True if returncode == 0.
    """
    cmdc = cmd.copy()
    for i, t in enumerate(cmdc):
        if t in ("-A", "-I"):
            cmdc[i] = "-C"
            break
    try:
        r = subprocess.run(cmdc, check=False, capture_output=True)
        return r.returncode == 0
    except Exception:
        return False


def _insert_comment_into_cmd(cmd: list, comment: str) -> list:
    """Return a copy of cmd with a comment match inserted before -j (if present).

    Example: ['iptables','-A','CHAIN','-s','x','-d','y','-j','ACCEPT'] ->
    ['iptables','-A','CHAIN','-s','x','-d','y','-m','comment','--comment','<comment>','-j','ACCEPT']
    """
    c = cmd.copy()
    try:
        j = c.index("-j")
    except ValueError:
        j = len(c)
    c[j:j] = ["-m", "comment", "--comment", comment]
    return c


def _add_iptables_rule(cmd: list, comment: str = None, dry: bool = False) -> bool:
    """Add an iptables rule if it doesn't already exist.

    If `comment` is provided, insert a comment match for easier later deletion.
    Returns True if the rule was added, False if it already existed.
    """
    if comment:
        cmd_to_use = _insert_comment_into_cmd(cmd, comment)
    else:
        cmd_to_use = cmd.copy()

    if _iptables_rule_exists(cmd_to_use):
        print("iptables: rule exists, skipping:", ' '.join(cmd_to_use))
        return False

    run(cmd_to_use, dry=dry)
    return True


def _delete_iptables_rule(cmd: list, dry: bool = False) -> bool:
    """Attempt to delete an iptables rule robustly.

    Strategy:
    1. If dry, print and return True.
    2. Try `iptables -C` (check) on the recorded rule; if it exists, run -D to delete it.
    3. If not found, list current rules with `iptables -t <table> -S` and try to find a matching
       rule line that contains the key tokens (src/dst/-o/-i/-j). Transform the '-A' line to '-D'
       and execute it. This reduces `Bad rule` noise when comment quoting or backend differences
       (iptables-nft) change the exact rule text.
    4. As a last resort, strip comment matchers and attempt a -D variant.

    Returns True if a deletion attempt was made; success is best-effort.
    """
    if dry:
        print("(dry) would delete:", cmd)
        return True

    def try_check_and_delete(base_cmd: list) -> bool:
        # Replace first -A/-I with -C to check existence
        check_cmd = base_cmd.copy()
        for i, t in enumerate(check_cmd):
            if t in ("-A", "-I"):
                check_cmd[i] = "-C"
                break
        try:
            run(check_cmd, check=True)
            # exists -> delete using -D
            del_cmd = base_cmd.copy()
            for i, t in enumerate(del_cmd):
                if t in ("-A", "-I"):
                    del_cmd[i] = "-D"
                    break
            run(del_cmd, check=True)
            return True
        except Exception:
            return False

    # 1) try direct check+delete (preserves comments)
    try:
        if try_check_and_delete(cmd):
            return True
    except Exception:
        pass

    # 2) inspect current iptables -S for a matching rule line and delete that exact line
    import shlex
    table = 'filter'
    if '-t' in cmd:
        try:
            t_idx = cmd.index('-t')
            table = cmd[t_idx + 1]
        except Exception:
            table = 'filter'

    try:
        out = subprocess.run(['iptables', '-t', table, '-S'], capture_output=True, text=True)
        rules_text = out.stdout or ''
    except Exception:
        rules_text = ''

    # build key tokens to match (ignore comment tokens and iptables binary/table markers)
    key_tokens = []
    skip_next = False
    for i, t in enumerate(cmd):
        if skip_next:
            skip_next = False
            continue
        if t == 'iptables':
            continue
        if t == '-t':
            skip_next = True
            continue
        if t in ('-A', '-I', '-D'):
            continue
        if t == '-m' and i + 1 < len(cmd) and cmd[i + 1] == 'comment':
            skip_next = True
            continue
        if t == '--comment':
            skip_next = True
            continue
        key_tokens.append(t)

    for line in rules_text.splitlines():
        if not line.strip():
            continue
        ok = True
        for kt in key_tokens:
            if kt not in line:
                ok = False
                break
        if not ok:
            continue
        # transform '-A' into '-D' and attempt deletion using shell-split tokens
        try:
            parts = shlex.split(line)
            if parts[0] == '-A':
                parts[0] = '-D'
            del_cmd = ['iptables', '-t', table] + parts
            try:
                run(del_cmd, check=True)
                return True
            except Exception:
                # try without explicit table prefix
                try:
                    run(['iptables'] + parts, check=True)
                    return True
                except Exception:
                    continue
        except Exception:
            continue

    # 3) last resort: strip comment matchers and try a -D
    no_comment = []
    i = 0
    while i < len(cmd):
        tok = cmd[i]
        if tok == '-m' and i + 1 < len(cmd) and cmd[i + 1] == 'comment':
            i += 4
            continue
        if tok == '--comment':
            i += 2
            continue
        no_comment.append(tok)
        i += 1

    # replace -A/-I with -D in no_comment and try
    for i, t in enumerate(no_comment):
        if t in ('-A', '-I'):
            no_comment[i] = '-D'
            break
    try:
        run(no_comment, check=True)
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Core VPC lifecycle
# create_vpc / add_subnet / delete_vpc / cleanup_all are the primary user
# operations. They manipulate bridges, namespaces and record metadata in
# `.vpcctl_data/` so deletion and inspection are deterministic.
# ---------------------------------------------------------------------------



def create_vpc(args):
    """Create a VPC.

    Responsibilities:
    - create a bridge for the VPC
    - enable ip_forward
    - create a per-VPC iptables chain and allow intra-VPC traffic
    - write metadata to `.vpcctl_data/vpc_<name>.json`

    The implementation is careful to be idempotent: it will skip creating a
    VPC if metadata already exists. Host iptables rules are added using the
    iptables helper above so duplicates are avoided.
    """
    require_root()
    name = args.name
    # accept either positional cidr (legacy) or --cidr flag
    cidr = getattr(args, 'cidr_flag', None) or getattr(args, 'cidr', None)
    dry = args.dry

    try:
        net = ipaddress.ip_network(cidr)
    except Exception as e:
        print(f"Invalid CIDR: {cidr}: {e}")
        sys.exit(1)

    if vpc_exists(name):
        print(f"VPC '{name}' already exists (idempotent).")
        return

    # create a safe bridge name (bridge names also limited)
    bridge = safe_ifname([name], prefix="br-", maxlen=15)
    # create bridge
    run(["ip", "link", "add", "name", bridge, "type", "bridge"], dry=dry)
    run(["ip", "link", "set", bridge, "up"], dry=dry)

    run(["sysctl", "-w", "net.ipv4.ip_forward=1"], dry=dry)

    # Create a per-VPC iptables chain to make host-level cleanup and policy insertion deterministic.
    # Chain name must be reasonably short; use prefix vpc- with a sanitized suffix
    chain = f"vpc-{safe_ifname([name], prefix='', maxlen=10)}"
    # create chain (non-fatal if exists)
    run(["iptables", "-N", chain], check=False, dry=dry)
    # insert a jump from FORWARD into this chain for packets coming from the VPC bridge
    jump_cmd = ["iptables", "-I", "FORWARD", "-i", bridge, "-j", chain]
    # try to add jump rule idempotently; record if added
    if _add_iptables_rule(jump_cmd, comment=f"vpcctl:{name}:jump", dry=dry):
        host_rules = [_insert_comment_into_cmd(jump_cmd, f"vpcctl:{name}:jump")]
    else:
        host_rules = []

    # Allow intra-VPC routing: accept packets whose source and destination are
    # within the VPC CIDR. This makes inter-subnet traffic (different IP
    # subnets on the same bridge) work even when the host FORWARD policy is
    # restrictive (e.g., DROP by default). Record the rule so it can be
    accept_cmd = ["iptables", "-A", chain, "-s", cidr, "-d", cidr, "-j", "ACCEPT"]
    if _add_iptables_rule(accept_cmd, comment=f"vpcctl:{name}:intra", dry=dry):
        host_rules.append(_insert_comment_into_cmd(accept_cmd, f"vpcctl:{name}:intra"))

    meta = {
        "name": name,
        "cidr": cidr,
        "bridge": bridge,
        "subnets": [],
        "host_iptables": host_rules,
        "chain": chain,
        "apps": [],
        "peers": []
    }
    save_vpc_meta(name, meta)
    print(f"Created VPC '{name}' with bridge '{bridge}' and CIDR {cidr}")


def add_subnet(args):
    """Add a subnet (namespace) to an existing VPC.

    Steps:
    - create a network namespace
    - create a veth pair and attach the peer to the VPC bridge
    - assign gateway IP on bridge and host IP inside namespace
    - add default route inside the namespace
    """
    require_root()
    name = args.vpc
    subnet_name = args.name
    # accept either positional cidr (legacy) or --cidr flag
    cidr = getattr(args, 'cidr_flag', None) or getattr(args, 'cidr', None)
    dry = args.dry

    if not vpc_exists(name):
        print(f"VPC '{name}' not found. Create it first.")
        sys.exit(1)

    try:
        net = ipaddress.ip_network(cidr)
    except Exception as e:
        print(f"Invalid CIDR: {cidr}: {e}")
        sys.exit(1)

    meta = load_vpc_meta(name)
    bridge = meta["bridge"]

    # namespace name can be descriptive; keep veth names strictly short/safe
    ns = f"ns-{name}-{subnet_name}"
    # veth names are limited (~15 chars). Create sanitized, truncated names.
    v_host = safe_ifname([name, subnet_name], prefix="v-", maxlen=15)
    v_peer = safe_ifname([name, subnet_name], prefix="vbr-", maxlen=15)

    if any(s.get("name") == subnet_name for s in meta.get("subnets", [])):
        print(f"Subnet '{subnet_name}' already exists in VPC '{name}' (idempotent).")
        return

    # Create namespace
    run(["ip", "netns", "add", ns], dry=dry)

    # Create veth pair
    run(["ip", "link", "add", v_host, "type", "veth", "peer", "name", v_peer], dry=dry)

    # Attach peer to bridge
    run(["ip", "link", "set", v_peer, "master", bridge], dry=dry)
    run(["ip", "link", "set", v_peer, "up"], dry=dry)

    # Move host end into namespace
    run(["ip", "link", "set", v_host, "netns", ns], dry=dry)

    # Compute gateway IP (assign to bridge) and host IP for namespace
    hosts = list(net.hosts())
    if len(hosts) < 2:
        print(f"CIDR {cidr} too small to allocate gateway and host addresses")
        sys.exit(1)
    prefix = net.prefixlen
    # allow optional explicit gateway from user (--gw). Otherwise pick the first usable host.
    if getattr(args, 'gw', None):
        bridge_gw = args.gw
        # pick the first host address that's not the provided gateway
        host_ip = None
        for h in hosts:
            if str(h) != bridge_gw:
                host_ip = str(h)
                break
        if not host_ip:
            print(f"Could not allocate host IP for CIDR {cidr} with gateway {bridge_gw}")
            sys.exit(1)
    else:
        bridge_gw = str(hosts[0])
        host_ip = str(hosts[1])

    # Assign gateway IP to bridge (so it acts as subnet gateway)
    # If bridge already has this IP, the command may fail; we let run() handle dry-run and errors are non-fatal
    run(["ip", "addr", "add", f"{bridge_gw}/{prefix}", "dev", bridge], check=False, dry=dry)

    # Inside namespace: set interface up and assign host IP
    run(["ip", "netns", "exec", ns, "ip", "addr", "add", f"{host_ip}/{prefix}", "dev", v_host], dry=dry)
    run(["ip", "netns", "exec", ns, "ip", "link", "set", v_host, "up"], dry=dry)

    # Set loopback
    run(["ip", "netns", "exec", ns, "ip", "link", "set", "lo", "up"], dry=dry)

    # Add default route inside namespace via bridge gateway
    run(["ip", "netns", "exec", ns, "ip", "route", "add", "default", "via", bridge_gw], dry=dry)

    # Record
    meta["subnets"].append({"name": subnet_name, "cidr": cidr, "ns": ns, "gw": bridge_gw, "host_ip": host_ip, "veth": v_host})
    save_vpc_meta(name, meta)
    print(f"Created subnet '{subnet_name}' ({cidr}) in VPC '{name}' with namespace '{ns}' and gateway {bridge_gw}")


def list_command(args):
    # List known VPCs from metadata directory
    vpcs = list_vpcs()
    if not vpcs:
        print("No VPCs found")
        return
    for v in vpcs:
        print(v)


def inspect_command(args):
    # Dump VPC metadata (JSON) for inspection or debugging
    name = args.name
    try:
        meta = load_vpc_meta(name)
    except FileNotFoundError:
        print(f"VPC '{name}' not found")
        return
    print(json.dumps(meta, indent=2))


def delete_vpc(args):
    """Delete a VPC and perform deterministic cleanup.

    It tries to stop recorded apps, flush namespace-local iptables, remove
    namespaces and bridge interfaces, and delete recorded host iptables
    rules using the recorded command tokens. This is best-effort but aims
    to leave the host clean.
    """
    require_root()
    name = args.name
    dry = args.dry

    if not vpc_exists(name):
        print(f"VPC '{name}' not found; nothing to delete.")
        return

    meta = load_vpc_meta(name)

    # Delete subnets
    # First, attempt to stop any started apps recorded in metadata
    for app in meta.get("apps", []):
        pid = app.get("pid")
        if not pid:
            continue
        try:
            print(f"Killing app pid {pid} (namespace {app.get('ns')})")
            run(["kill", "-TERM", str(pid)], check=False, dry=dry)
        except Exception:
            pass

    for s in meta.get("subnets", []):
        ns = s.get("ns")
        # flush iptables inside namespace then delete namespace
        run(["ip", "netns", "exec", ns, "iptables", "-F"], check=False, dry=dry)
        run(["ip", "netns", "exec", ns, "iptables", "-t", "nat", "-F"], check=False, dry=dry)
        # delete namespace (which also removes veth inside it)
        run(["ip", "netns", "del", ns], check=False, dry=dry)

    # Delete bridge
    bridge = meta.get("bridge")
    run(["ip", "link", "set", bridge, "down"], check=False, dry=dry)
    run(["ip", "link", "del", bridge, "type", "bridge"], check=False, dry=dry)

    # Remove NAT rules if present
    nat = meta.get("nat")
    if nat:
        intf = nat.get("interface")
        cidr = meta.get("cidr")
        # If we recorded host_iptables rules, try to remove them precisely
        for r in list(meta.get("host_iptables", [])):
            if not r:
                continue
            try:
                _delete_iptables_rule(r, dry=dry)
            except Exception:
                pass
        # clear recorded host_iptables
        meta["host_iptables"] = []
        save_vpc_meta(name, meta)

    # Remove the per-VPC chain jump and delete chain itself (if recorded)
    chain = meta.get("chain")
    bridge = meta.get("bridge")
    if chain:
        # attempt to delete the jump from FORWARD
        jump_del = ["iptables", "-D", "FORWARD", "-i", bridge, "-j", chain]
        run(jump_del, check=False, dry=dry)
        # delete chain (will fail if rules still reference it)
        run(["iptables", "-F", chain], check=False, dry=dry)
        run(["iptables", "-X", chain], check=False, dry=dry)

    # Remove metadata
    p = vpc_metadata_path(name)
    if not dry:
        try:
            p.unlink()
        except Exception:
            pass

    print(f"Deleted VPC '{name}' and cleaned up resources")


def cleanup_all(args):
    """Delete all VPCs recorded in metadata directory.

    Re-uses the single-VPC delete flow to ensure consistent cleanup.
    """
    require_root()
    dry = args.dry
    vpcs = list_vpcs()
    if not vpcs:
        print("No VPCs to clean up")
        return
    for v in vpcs:
        print(f"Cleaning VPC: {v}")
        # reuse delete flow by creating a fake args
        a = argparse.Namespace()
        a.name = v
        a.dry = dry
        delete_vpc(a)
    print("All recorded VPCs cleaned up")


def verify(args):
    """Report vpcctl-related resources and potential orphans.

    Helpful to run after tests to detect leftover namespaces or bridges that
    aren't reflected in metadata.
    """
    # list namespaces and bridges that look like vpcctl-created
    out = subprocess.run(["ip", "netns", "list"], capture_output=True, text=True)
    ns_lines = out.stdout.strip().splitlines() if out.stdout else []
    vpc_ns = [l.split()[0] for l in ns_lines if l.startswith("ns-")]

    out2 = subprocess.run(["ip", "link", "show", "type", "bridge"], capture_output=True, text=True)
    br_lines = out2.stdout.strip().splitlines() if out2.stdout else []
    vpc_bridges = []
    for line in br_lines:
        # lines like: 3: br-myvpc: <BROADCAST,...>
        parts = line.split()
        if len(parts) >= 2 and parts[1].startswith("br-"):
            vpc_bridges.append(parts[1].rstrip(':'))

    print("vpcctl-looking namespaces:", vpc_ns)
    print("vpcctl-looking bridges:", vpc_bridges)
    # check metadata vs actual
    recorded = list_vpcs()
    print("Recorded VPCs:", recorded)
    # quick orphan check
    orphans = []
    for ns in vpc_ns:
        found = False
        for v in recorded:
            meta = load_vpc_meta(v)
            for s in meta.get("subnets", []):
                if s.get("ns") == ns:
                    found = True
                    break
            if found:
                break
        if not found:
            orphans.append(ns)
    if orphans:
        print("Orphan namespaces (no metadata):", orphans)
    else:
        print("No orphan namespaces detected")


def create_peer(args):
    """Create peering between two VPCs by connecting their bridges with a veth pair

    Access control: only allow traffic between the specified CIDRs (default: both VPC CIDRs).
    Implementation: create veth pair, attach each end to each bridge, add iptables FORWARD rules
    that ACCEPT allowed CIDR pairs and DROP other traffic between the two bridges.
    """
    require_root()
    vpc1 = args.vpc1
    vpc2 = args.vpc2
    dry = args.dry

    if not vpc_exists(vpc1) or not vpc_exists(vpc2):
        print("Both VPCs must exist to create a peer")
        sys.exit(1)

    if vpc1 == vpc2:
        print("Cannot peer a VPC to itself")
        sys.exit(1)

    meta1 = load_vpc_meta(vpc1)
    meta2 = load_vpc_meta(vpc2)

    bridge1 = meta1.get("bridge")
    bridge2 = meta2.get("bridge")

    # determine allowed cidrs
    if args.allow_cidrs:
        allow_list = [c.strip() for c in args.allow_cidrs.split(',') if c.strip()]
    else:
        allow_list = [meta1.get("cidr"), meta2.get("cidr")]

    # create veth pair names (sanitized + truncated to fit kernel IFNAMSIZ)
    # allocate base name then append suffix a/b
    base = safe_ifname([vpc1, vpc2], prefix="pv-", suffix="", maxlen=14)
    # ensure room for final 'a' or 'b'
    veth_a = safe_ifname([vpc1, vpc2], prefix="pv-", suffix="a", maxlen=15)
    veth_b = safe_ifname([vpc1, vpc2], prefix="pv-", suffix="b", maxlen=15)

    # idempotency: if links already exist, skip creation
    existing_links = subprocess.run(["ip", "link", "show"], capture_output=True, text=True).stdout
    if veth_a in existing_links or veth_b in existing_links:
        print(f"Peering links {veth_a}/{veth_b} appear to already exist; skipping link creation")
    else:
        run(["ip", "link", "add", veth_a, "type", "veth", "peer", "name", veth_b], dry=dry)
        # attach to bridges
        run(["ip", "link", "set", veth_a, "master", bridge1], dry=dry)
        run(["ip", "link", "set", veth_b, "master", bridge2], dry=dry)
        run(["ip", "link", "set", veth_a, "up"], dry=dry)
        run(["ip", "link", "set", veth_b, "up"], dry=dry)

    # Use per-VPC chains (created at VPC creation) to insert rules deterministically.
    chain1 = meta1.get("chain")
    chain2 = meta2.get("chain")
    if not chain1 or not chain2:
        print("Per-VPC iptables chains not found; ensure VPCs were created by vpcctl")

    # Accept rules: append rules into each VPC's chain allowing traffic to the peer bridge
    for src in allow_list:
        for dst in allow_list:
            # allow from vpc1->vpc2 by adding rule into chain1
            cmd1 = ["iptables", "-A", chain1, "-o", bridge2, "-s", src, "-d", dst, "-j", "ACCEPT"]
            cmd2 = ["iptables", "-A", chain2, "-o", bridge1, "-s", src, "-d", dst, "-j", "ACCEPT"]
            # add idempotently and record only when added
            comment = f"vpcctl:peer:{vpc1}:{vpc2}"
            if _add_iptables_rule(cmd1, comment=comment, dry=dry):
                meta1.setdefault("host_iptables", []).append(_insert_comment_into_cmd(cmd1, comment))
            if _add_iptables_rule(cmd2, comment=comment, dry=dry):
                meta2.setdefault("host_iptables", []).append(_insert_comment_into_cmd(cmd2, comment))

    # Drop other traffic between bridges by adding a final DROP rule in each chain
    drop1 = ["iptables", "-A", chain1, "-o", bridge2, "-j", "DROP"]
    drop2 = ["iptables", "-A", chain2, "-o", bridge1, "-j", "DROP"]
    if _add_iptables_rule(drop1, comment=f"vpcctl:peer-drop:{vpc1}:{vpc2}", dry=dry):
        meta1.setdefault("host_iptables", []).append(_insert_comment_into_cmd(drop1, f"vpcctl:peer-drop:{vpc1}:{vpc2}"))
    if _add_iptables_rule(drop2, comment=f"vpcctl:peer-drop:{vpc1}:{vpc2}", dry=dry):
        meta2.setdefault("host_iptables", []).append(_insert_comment_into_cmd(drop2, f"vpcctl:peer-drop:{vpc1}:{vpc2}"))

    # Record peering metadata in both VPC meta (avoid duplicates)
    peer_record = {"peer_vpc": vpc2, "veth_a": veth_a, "veth_b": veth_b, "allowed": allow_list}
    existing = [p for p in meta1.get("peers", []) if p.get("peer_vpc") == vpc2 and p.get("veth_a") == veth_a]
    if not existing:
        meta1.setdefault("peers", []).append(peer_record)
        save_vpc_meta(vpc1, meta1)

    peer_record_rev = {"peer_vpc": vpc1, "veth_a": veth_b, "veth_b": veth_a, "allowed": allow_list}
    existing_rev = [p for p in meta2.get("peers", []) if p.get("peer_vpc") == vpc1 and p.get("veth_a") == veth_b]
    if not existing_rev:
        meta2.setdefault("peers", []).append(peer_record_rev)
        save_vpc_meta(vpc2, meta2)

    print(f"Peered VPC '{vpc1}' <-> '{vpc2}' with veths {veth_a}/{veth_b}. Allowed CIDRs: {allow_list}")


# ---------------------------------------------------------------------------
# Demo / orchestration helpers
# These provide a simple end-to-end scenario useful for manual acceptance testing.
# ---------------------------------------------------------------------------


def run_demo(args):
    """Run a demo scenario creating two VPCs, subnets, deploying apps and testing connectivity.

    Dry-run by default. Use --execute and provide --internet-iface to run for real.
    """
    execute = args.execute
    iface = args.iface
    dry = not execute

    # Demo configuration
    a = {"name": "demo-a", "cidr": "10.10.0.0/16", "public": "10.10.1.0/24", "private": "10.10.2.0/24"}
    b = {"name": "demo-b", "cidr": "10.20.0.0/16", "public": "10.20.1.0/24"}

    steps = []
    # create VPCs
    steps.append(("create", [a['name'], a['cidr']]))
    steps.append(("add-subnet", [a['name'], "public", a['public']]))
    steps.append(("add-subnet", [a['name'], "private", a['private']]))
    steps.append(("create", [b['name'], b['cidr']]))
    steps.append(("add-subnet", [b['name'], "public", b['public']]))

    # deploy an app in demo-a public
    steps.append(("deploy-app", [a['name'], "public", "8080"]))

    # enable NAT on demo-a if executing and iface provided
    if execute:
        if not iface:
            print("--internet-iface is required when --execute is used")
            return
        steps.append(("enable-nat", [a['name'], iface]))

    # peer demo-a and demo-b but only allow their public CIDRs
    steps.append(("peer", [a['name'], b['name'], "--allow-cidrs", f"{a['public']},{b['public']}"]))

    # tests will be executed after orchestration
    # run steps
    for cmd, argv in steps:
        print(f"\n=== STEP: {cmd} {' '.join(argv)} ===")
        # build args namespace for dispatch
        ns = argparse.Namespace()
        ns.dry = dry
        try:
            if cmd == "create":
                ns.name, ns.cidr = argv
                create_vpc(ns)
            elif cmd == "add-subnet":
                ns.vpc, ns.name, ns.cidr = argv
                add_subnet(ns)
            elif cmd == "deploy-app":
                ns.vpc, ns.subnet, ns.port = argv
                deploy_app(ns)
            elif cmd == "enable-nat":
                ns.name, ns.iface = argv
                enable_nat(ns)
            elif cmd == "peer":
                # handle optional allow-cidrs
                ns.vpc1 = argv[0]
                ns.vpc2 = argv[1]
                if len(argv) > 2 and argv[2] == "--allow-cidrs":
                    ns.allow_cidrs = argv[3]
                else:
                    ns.allow_cidrs = None
                ns.dry = dry
                create_peer(ns)
        except Exception as e:
            print(f"Step failed: {e}")

    # perform some connectivity tests (dry-run prints commands)
    print("\n=== DEMO TESTS ===")
    # Inspect metadata to find IPs
    if not dry:
        try:
            meta_a = load_vpc_meta(a['name'])
            meta_b = load_vpc_meta(b['name'])
            # find public gw ips
            gw_a = next(s['gw'] for s in meta_a['subnets'] if s['name'] == 'public')
            gw_b = next(s['gw'] for s in meta_b['subnets'] if s['name'] == 'public')
            # test from demo-a private to demo-a public
            ns_from = next(s['ns'] for s in meta_a['subnets'] if s['name'] == 'private')
            print(f"Test: from {ns_from} -> {gw_a}:8080")
            test_connectivity(argparse.Namespace(target=gw_a, port=8080, from_ns=ns_from, dry=False))
            # test cross-vpc before/after peering is not straightforward here; assume peer created
            print(f"Test: from {ns_from} -> {gw_b}:8080 (cross-VPC, should work after peering for allowed CIDRs)")
            test_connectivity(argparse.Namespace(target=gw_b, port=8080, from_ns=ns_from, dry=False))
        except Exception as e:
            print(f"Demo checks skipped/failed: {e}")
    else:
        print("Demo ran in dry-run mode. Use --execute to perform the demo for real.")


# ---------------------------------------------------------------------------
# Feature implementations (NAT, policies)
# Each function here focuses on a single host-level feature and records any
# host-level iptables commands into the metadata so deletion can be deterministic.
# ---------------------------------------------------------------------------


def enable_nat(args):
    """Enable NAT (MASQUERADE) for a VPC's bridge via given internet interface.

    Example: vpcctl enable-nat myvpc eth0
    """
    require_root()
    name = args.name
    # accept either positional iface (legacy) or --interface flag
    intf = getattr(args, 'iface_flag', None) or getattr(args, 'iface', None)
    dry = args.dry

    if not vpc_exists(name):
        print(f"VPC '{name}' not found")
        sys.exit(1)

    meta = load_vpc_meta(name)
    bridge = meta.get("bridge")

    # enable forwarding
    run(["sysctl", "-w", "net.ipv4.ip_forward=1"], dry=dry)

    # add MASQUERADE rule for traffic from VPC CIDR going out via interface
    cidr = meta.get("cidr")
    # try to add MASQUERADE rule for traffic from VPC CIDR going out via interface
    cidr = meta.get("cidr")
    nat_cmd = ["iptables", "-t", "nat", "-A", "POSTROUTING", "-s", cidr, "-o", intf, "-j", "MASQUERADE"]
    if _add_iptables_rule(nat_cmd, comment=f"vpcctl:{name}:nat", dry=dry):
        meta.setdefault("host_iptables", []).append(_insert_comment_into_cmd(nat_cmd, f"vpcctl:{name}:nat"))

    # ensure iptables FORWARD policy allows established connections (best-effort)
    fwd1 = ["iptables", "-A", "FORWARD", "-i", bridge, "-o", intf, "-j", "ACCEPT"]
    if _add_iptables_rule(fwd1, comment=f"vpcctl:{name}:fwd-out", dry=dry):
        meta.setdefault("host_iptables", []).append(_insert_comment_into_cmd(fwd1, f"vpcctl:{name}:fwd-out"))

    fwd2 = ["iptables", "-A", "FORWARD", "-i", intf, "-o", bridge, "-m", "state", "--state", "ESTABLISHED,RELATED", "-j", "ACCEPT"]
    if _add_iptables_rule(fwd2, comment=f"vpcctl:{name}:fwd-in", dry=dry):
        meta.setdefault("host_iptables", []).append(_insert_comment_into_cmd(fwd2, f"vpcctl:{name}:fwd-in"))

    # record NAT config
    meta["nat"] = {"interface": intf}
    save_vpc_meta(name, meta)
    print(f"Enabled NAT for VPC '{name}' via interface '{intf}'")




def apply_policy(args):
    """Apply a JSON policy to subnets in a VPC.

    Policy JSON format example:
    {
      "subnet": "10.10.1.0/24",
      "ingress": [
         {"port": 80, "protocol": "tcp", "action": "allow"},
         {"port": 22, "protocol": "tcp", "action": "deny"}
      ]
    }
    """
    require_root()
    vpc = args.vpc
    policy_file = args.policy_file
    dry = args.dry

    if not vpc_exists(vpc):
        print(f"VPC '{vpc}' not found")
        sys.exit(1)

    try:
        policies = json.load(open(policy_file))
    except Exception as e:
        print(f"Failed to read policy file: {e}")
        sys.exit(1)

    # normalize to list
    if isinstance(policies, dict):
        policies = [policies]

    meta = load_vpc_meta(vpc)

    for p in policies:
        subnet_cidr = p.get("subnet")
        if not subnet_cidr:
            print("Policy missing 'subnet' field; skipping")
            continue

        # find subnet metadata by cidr
        target = None
        for s in meta.get("subnets", []):
            if s.get("cidr") == subnet_cidr:
                target = s
                break

        if not target:
            print(f"No subnet in VPC '{vpc}' matches CIDR {subnet_cidr}; skipping")
            continue

        ns = target.get("ns")

        # Flush existing rules inside namespace (filter table)
        run(["ip", "netns", "exec", ns, "iptables", "-F"], dry=dry)
        # basic protections: allow loopback and established
        run(["ip", "netns", "exec", ns, "iptables", "-A", "INPUT", "-i", "lo", "-j", "ACCEPT"], dry=dry)
        run(["ip", "netns", "exec", ns, "iptables", "-A", "INPUT", "-m", "state", "--state", "ESTABLISHED,RELATED", "-j", "ACCEPT"], dry=dry)

        ingress = p.get("ingress", [])
        # Apply ingress rules: follows order in file
        for r in ingress:
            proto = r.get("protocol", "tcp")
            port = r.get("port")
            action = r.get("action", "allow").lower()
            if port is None:
                print(f"Skipping rule without port: {r}")
                continue
            if action == "allow":
                cmd = ["ip", "netns", "exec", ns, "iptables", "-A", "INPUT", "-p", proto, "--dport", str(port), "-j", "ACCEPT"]
            else:
                cmd = ["ip", "netns", "exec", ns, "iptables", "-A", "INPUT", "-p", proto, "--dport", str(port), "-j", "DROP"]
            run(cmd, dry=dry)

        # Apply egress (OUTPUT) rules if provided. Similar to ingress.
        egress = p.get("egress", [])
        for r in egress:
            proto = r.get("protocol", "tcp")
            port = r.get("port")
            action = r.get("action", "allow").lower()
            if port is None:
                print(f"Skipping egress rule without port: {r}")
                continue
            if action == "allow":
                cmd = ["ip", "netns", "exec", ns, "iptables", "-A", "OUTPUT", "-p", proto, "--dport", str(port), "-j", "ACCEPT"]
            else:
                cmd = ["ip", "netns", "exec", ns, "iptables", "-A", "OUTPUT", "-p", proto, "--dport", str(port), "-j", "DROP"]
            run(cmd, dry=dry)

        print(f"Applied policy to subnet {subnet_cidr} (namespace {ns})")


# ---------------------------------------------------------------------------
# App lifecycle helpers
# Quick helpers to deploy a simple HTTP server inside a namespace and stop it.
# PIDs and the launch command are recorded in metadata so the main delete path
# can stop running servers during cleanup.
# ---------------------------------------------------------------------------


def deploy_app(args):
    """Deploy a simple Python HTTP server inside a subnet namespace."""
    require_root()
    vpc = args.vpc
    subnet = args.subnet
    # accept either positional port (legacy) or --port flag
    port = getattr(args, 'port_flag', None) or getattr(args, 'port', None)
    dry = args.dry

    if not vpc_exists(vpc):
        print(f"VPC '{vpc}' not found")
        sys.exit(1)

    meta = load_vpc_meta(vpc)
    target = None
    for s in meta.get("subnets", []):
        if s.get("name") == subnet:
            target = s
            break

    if not target:
        print(f"Subnet '{subnet}' not found in VPC '{vpc}'")
        sys.exit(1)

    ns = target.get("ns")

    cmd = ["ip", "netns", "exec", ns, "python3", "-m", "http.server", str(port)]
    print(f"Starting HTTP server in namespace {ns} on port {port}")
    if dry:
        print('DRY:', ' '.join(cmd))
        return
    # launch as a background process and capture PID so we can stop it later
    try:
        # use nohup in a shell, background it and echo the PID
        shell_cmd = f"ip netns exec {ns} nohup python3 -m http.server {port} >/tmp/vpcctl-{ns}-http.log 2>&1 & echo $!"
        out = subprocess.check_output(shell_cmd, shell=True, text=True).strip()
        pid = int(out.splitlines()[-1]) if out else None
        print(f"HTTP server started in namespace {ns}; pid={pid}; logs: /tmp/vpcctl-{ns}-http.log")

        # record pid in vpc metadata so cleanup can stop it
        meta.setdefault("apps", []).append({"ns": ns, "port": port, "pid": pid, "cmd": cmd})
        save_vpc_meta(vpc, meta)
    except Exception as e:
        print(f"Failed to start HTTP server: {e}")




def stop_app(args):
    """Stop a previously started app by namespace or PID."""
    require_root()
    vpc = args.vpc
    ns = args.ns
    pid = args.pid
    dry = args.dry

    if not vpc_exists(vpc):
        print(f"VPC '{vpc}' not found")
        return

    meta = load_vpc_meta(vpc)
    removed = []
    for app in list(meta.get("apps", [])):
        if ns and app.get("ns") != ns:
            continue
        if pid and str(app.get("pid")) != str(pid):
            continue
        apid = app.get("pid")
        if apid:
            run(["kill", "-TERM", str(apid)], check=False, dry=dry)
        meta.get("apps", []).remove(app)
        removed.append(app)

    save_vpc_meta(vpc, meta)
    if removed:
        print(f"Stopped apps: {removed}")
    else:
        print("No matching apps found to stop")




def test_connectivity(args):
    target = args.target
    port = args.port
    from_ns = args.from_ns
    dry = args.dry

    # try HTTP GET using curl if available, fallback to ping
    if from_ns:
        # run from namespace
        cmd = ["ip", "netns", "exec", from_ns, "curl", "-sS", f"http://{target}:{port}"]
    else:
        cmd = ["curl", "-sS", f"http://{target}:{port}"]

    print(f"Testing connectivity: {' '.join(cmd)}")
    if dry:
        return

    try:
        r = subprocess.run(cmd, check=True, capture_output=True, timeout=5)
        out = r.stdout.decode(errors='ignore')
        print("Connectivity OK — response snapshot:\n", out[:200])
    except subprocess.CalledProcessError as e:
        print("Connectivity test failed (non-zero exit)")
    except Exception as e:
        print(f"Connectivity test error: {e}")


# ---------------------------------------------------------------------------
# CLI parsing helpers
# build_parser() and run_flag_check() exist so callers (and CI) can validate
# flag handling without performing any network changes.
# ---------------------------------------------------------------------------


def parse_args():
    # Build and return an argparse.ArgumentParser so other code can reuse it for
    # parser-only checks. The heavy-lifting parser builder is implemented in
    # `build_parser()` so it can be reused by `run_flag_check()` below.
    parser = build_parser()
    return parser.parse_args()


def build_parser():
    p = argparse.ArgumentParser(prog="vpcctl", description="Minimal VPC controller using Linux namespaces and bridges")
    p.add_argument("--dry-run", dest="dry", action="store_true", help="Print commands without running")
    sub = p.add_subparsers(dest="cmd")

    p_create = sub.add_parser("create", help="Create a VPC")
    p_create.add_argument("name")
    # support both positional CIDR (legacy) and --cidr flag for friendliness
    p_create.add_argument("cidr", nargs="?", help="CIDR for the VPC (positional, legacy)")
    p_create.add_argument("--cidr", dest="cidr_flag", help="CIDR for the VPC (preferred flag)")

    p_add = sub.add_parser("add-subnet", help="Add a subnet to a VPC")
    p_add.add_argument("vpc")
    p_add.add_argument("name")
    # support positional CIDR or --cidr flag; allow optional --gw to override gateway
    p_add.add_argument("cidr", nargs="?", help="CIDR for the subnet (positional, legacy)")
    p_add.add_argument("--cidr", dest="cidr_flag", help="CIDR for the subnet (preferred flag)")
    p_add.add_argument("--gw", dest="gw", help="Optional gateway IP to assign to the bridge")

    p_list = sub.add_parser("list", help="List VPCs")

    p_inspect = sub.add_parser("inspect", help="Inspect a VPC")
    p_inspect.add_argument("name")

    p_delete = sub.add_parser("delete", help="Delete a VPC and clean resources")
    p_delete.add_argument("name")

    p_nat = sub.add_parser("enable-nat", help="Enable NAT for a VPC via host interface")
    p_nat.add_argument("name")
    # accept positional iface (legacy) or --interface flag for friendliness
    p_nat.add_argument("iface", nargs="?", help="Host outbound interface (positional, legacy, e.g., eth0)")
    p_nat.add_argument("--interface", dest="iface_flag", help="Host outbound interface (preferred flag, e.g., eth0)")

    p_peer = sub.add_parser("peer", help="Create a peering connection between two VPCs")
    p_peer.add_argument("vpc1")
    p_peer.add_argument("vpc2")
    p_peer.add_argument("--allow-cidrs", dest="allow_cidrs", help="Comma-separated CIDRs allowed across the peer (default: both VPC CIDRs)")

    p_policy = sub.add_parser("apply-policy", help="Apply JSON security group policy to a subnet")
    p_policy.add_argument("vpc")
    p_policy.add_argument("policy_file", help="Path to JSON policy file")

    p_deploy = sub.add_parser("deploy-app", help="Deploy a simple HTTP app inside a subnet namespace")
    p_deploy.add_argument("vpc")
    p_deploy.add_argument("subnet")
    # accept positional port (legacy) or --port flag for friendliness
    p_deploy.add_argument("port", nargs="?", default=8080, type=int, help="Port to run the HTTP server on (default 8080)")
    p_deploy.add_argument("--port", dest="port_flag", type=int, help="Port to run the HTTP server on (preferred flag)")

    p_stop = sub.add_parser("stop-app", help="Stop an app started with deploy-app (by vpc + namespace or pid)")
    p_stop.add_argument("vpc")
    p_stop.add_argument("--ns", dest="ns", help="Namespace of the app to stop")
    p_stop.add_argument("--pid", dest="pid", help="PID of the app to stop")

    p_test = sub.add_parser("test-connectivity", help="Test connectivity to an IP/port from host or a namespace")
    p_test.add_argument("target")
    p_test.add_argument("port", nargs="?", default=80, type=int)
    p_test.add_argument("--from-ns", dest="from_ns", help="Namespace to run the test from (optional)")

    p_cleanup = sub.add_parser("cleanup-all", help="Delete all VPCs recorded in metadata")

    p_verify = sub.add_parser("verify", help="Verify and report vpcctl-related resources on host")

    p_demo = sub.add_parser("run-demo", help="Run a demo scenario (dry-run by default). Use --execute to actually run")
    p_demo.add_argument("--execute", action="store_true", help="Execute the demo (will perform real changes, requires root)")
    p_demo.add_argument("--internet-iface", dest="iface", help="Host internet interface to use for NAT when executing demo (required with --execute)")

    # convenience: flag-check will run parser-only checks for common flag combinations
    p_flag = sub.add_parser("flag-check", help="Validate common flag/argument combinations (no changes)")

    return p


def run_flag_check():
    """Parse a set of example invocations to validate flag handling (no system changes).

    This function exercises common combinations (positional and flag forms) and
    prints the parsed argparse.Namespace for each example. It intentionally does
    not execute any operational commands.
    """
    parser = build_parser()
    examples = [
        ["create", "myvpc", "10.0.0.0/16"],
        ["create", "myvpc2", "--cidr", "10.1.0.0/16"],
        ["add-subnet", "myvpc", "public", "10.0.1.0/24"],
        ["add-subnet", "myvpc", "private", "10.0.2.0/24", "--gw", "10.0.2.1"],
        ["deploy-app", "myvpc", "public", "--port", "8080"],
        ["deploy-app", "myvpc", "public", "9090"],
        ["enable-nat", "myvpc", "--interface", "eth0"],
        ["enable-nat", "myvpc", "eth0"],
        ["peer", "vpcA", "vpcB", "--allow-cidrs", "10.0.1.0/24,10.1.1.0/24"],
        ["apply-policy", "myvpc", "policy.json"],
        ["test-connectivity", "10.0.1.5", "80", "--from-ns", "ns-myvpc-public"],
    ]

    print("flag-check: parsing example invocations (no changes will be made):")
    for ex in examples:
        try:
            ns = parser.parse_args(ex)
            print(f"  EXAMPLE: {' '.join(ex)}")
            print(f"    -> {ns}")
        except SystemExit as e:
            # argparse may call sys.exit on invalid combos; report but continue
            print(f"  EXAMPLE: {' '.join(ex)} -> parser exited with {e}")
    print("flag-check: done. If all examples parsed as expected, flag parsing looks OK.")


def main():
    args = parse_args()
    # map dry flag
    if hasattr(args, "dry"):
        args.dry = getattr(args, "dry")
    else:
        args.dry = False

    if args.cmd == "create":
        create_vpc(args)
    elif args.cmd == "add-subnet":
        add_subnet(args)
    elif args.cmd == "list":
        list_command(args)
    elif args.cmd == "inspect":
        inspect_command(args)
    elif args.cmd == "delete":
        delete_vpc(args)
    elif args.cmd == "enable-nat":
        enable_nat(args)
    elif args.cmd == "apply-policy":
        apply_policy(args)
    elif args.cmd == "deploy-app":
        deploy_app(args)
    elif args.cmd == "stop-app":
        stop_app(args)
    elif args.cmd == "test-connectivity":
        test_connectivity(args)
    elif args.cmd == "cleanup-all":
        cleanup_all(args)
    elif args.cmd == "verify":
        verify(args)
    elif args.cmd == "peer":
        create_peer(args)
    elif args.cmd == "run-demo":
        run_demo(args)
    elif args.cmd == "flag-check":
        # run parser-only checks to validate flag handling
        run_flag_check()
    else:
        print("No command given. Use --help for usage.")


if __name__ == "__main__":
    main()
