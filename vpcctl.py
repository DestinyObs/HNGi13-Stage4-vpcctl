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
"""

from __future__ import annotations

import argparse, json, os, subprocess, sys, ipaddress, shutil, shlex
from pathlib import Path
from typing import List, Dict, Any, Callable, Optional

WORKDIR = Path.cwd() / ".vpcctl_data"
WORKDIR.mkdir(parents=True, exist_ok=True)

# ------------------------------------------------------------------
# Generic utilities
# ------------------------------------------------------------------

def run(cmd: List[str], *, check: bool = True, capture_output: bool = False, dry: bool = False):
    print(">>>", " ".join(cmd))
    if dry:
        return None
    return subprocess.run(cmd, check=check, capture_output=capture_output)


def require_root():
    if os.geteuid() != 0:
        print("vpcctl: must be run as root (sudo)")
        sys.exit(2)


def safe_ifname(parts, prefix="", suffix="", maxlen: int = 15):
    """Return safe interface name: join parts, sanitize, truncate."""
    import re
    if isinstance(parts, (list, tuple)):
        core = "-".join(str(p) for p in parts if p is not None)
    else:
        core = str(parts)
    core = re.sub(r"[^A-Za-z0-9-]", "-", core)
    core = re.sub(r"-{2,}", "-", core)
    avail = maxlen - len(prefix) - len(suffix)
    if avail <= 0:
        return (prefix + suffix)[:maxlen]
    if len(core) > avail:
        core = core[:avail]
    return f"{prefix}{core}{suffix}"


# ------------------------------------------------------------------
# Metadata helpers
# ------------------------------------------------------------------

def _meta_path(name: str) -> Path:
    return WORKDIR / f"vpc_{name}.json"


def vpc_exists(name: str) -> bool:
    return _meta_path(name).exists()


def load_meta(name: str) -> Dict[str, Any]:
    p = _meta_path(name)
    if not p.exists():
        raise FileNotFoundError(p)
    return json.load(open(p))


def save_meta(name: str, meta: Dict[str, Any]):
    with open(_meta_path(name), "w") as f:
        json.dump(meta, f, indent=2)


def list_vpcs() -> List[str]:
    return [p.stem.replace("vpc_", "") for p in WORKDIR.glob("vpc_*.json")]


# ------------------------------------------------------------------
# iptables helpers
# ------------------------------------------------------------------

def _iptables_rule_exists(cmd: List[str]) -> bool:
    test = cmd.copy()
    for i, t in enumerate(test):
        if t in ("-A", "-I"):
            test[i] = "-C"; break
    try:
        r = subprocess.run(test, check=False, capture_output=True)
        return r.returncode == 0
    except Exception:
        return False


def _insert_comment(cmd: List[str], comment: str) -> List[str]:
    c = cmd.copy()
    try:
        j = c.index("-j")
    except ValueError:
        j = len(c)
    c[j:j] = ["-m", "comment", "--comment", comment]
    return c


def _add_rule(cmd: List[str], *, comment: Optional[str], dry: bool) -> bool:
    use = _insert_comment(cmd, comment) if comment else cmd.copy()
    if _iptables_rule_exists(use):
        print("iptables: rule exists, skipping:", " ".join(use))
        return False
    run(use, dry=dry)
    return True


def _delete_rule(cmd: List[str], *, dry: bool) -> bool:
    if dry:
        print("(dry) would delete:", cmd)
        return True

    def try_cd(base: List[str]) -> bool:
        chk = base.copy()
        for i, t in enumerate(chk):
            if t in ("-A", "-I"):
                chk[i] = "-C"; break
        try:
            run(chk, check=True)
            d = base.copy()
            for i, t in enumerate(d):
                if t in ("-A", "-I"):
                    d[i] = "-D"; break
            run(d, check=True)
            return True
        except Exception:
            return False

    try:
        if try_cd(cmd):
            return True
    except Exception:
        pass

    table = 'filter'
    if '-t' in cmd:
        try:
            table = cmd[cmd.index('-t') + 1]
        except Exception:
            table = 'filter'
    try:
        out = subprocess.run(['iptables', '-t', table, '-S'], capture_output=True, text=True)
        rules_text = out.stdout or ''
    except Exception:
        rules_text = ''

    key = []
    skip = False
    for i, t in enumerate(cmd):
        if skip: skip = False; continue
        if t == 'iptables': continue
        if t == '-t': skip = True; continue
        if t in ('-A','-I','-D'): continue
        if t == '-m' and i+1 < len(cmd) and cmd[i+1]=='comment': skip = True; continue
        if t == '--comment': skip = True; continue
        key.append(t)

    for line in rules_text.splitlines():
        if not line.strip():
            continue
        if all(k in line for k in key):
            parts = shlex.split(line)
            if parts and parts[0] == '-A': parts[0] = '-D'
            full = ['iptables', '-t', table] + parts
            try:
                run(full, check=True); return True
            except Exception:
                try:
                    run(['iptables'] + parts, check=True); return True
                except Exception:
                    continue

    # last resort: strip comments
    stripped = []
    i = 0
    while i < len(cmd):
        tok = cmd[i]
        if tok == '-m' and i+1 < len(cmd) and cmd[i+1]=='comment': i += 4; continue
        if tok == '--comment': i += 2; continue
        stripped.append(tok); i += 1
    for i, t in enumerate(stripped):
        if t in ('-A','-I'): stripped[i] = '-D'; break
    try:
        run(stripped, check=True); return True
    except Exception:
        return False


# ------------------------------------------------------------------
# Small internal helpers
# ------------------------------------------------------------------

def _parse_network(cidr: str):
    try:
        return ipaddress.ip_network(cidr)
    except Exception as e:
        print(f"Invalid CIDR: {cidr}: {e}"); sys.exit(1)


def _find_subnet(meta: Dict[str, Any], *, name: Optional[str] = None, cidr: Optional[str] = None):
    for s in meta.get("subnets", []):
        if name and s.get("name") == name: return s
        if cidr and s.get("cidr") == cidr: return s
    return None


def _record_rule(meta: Dict[str, Any], cmd: List[str], comment: str):
    meta.setdefault("host_iptables", []).append(_insert_comment(cmd, comment))


# ------------------------------------------------------------------
# Core lifecycle
# ------------------------------------------------------------------

def create_vpc(args):
    require_root()
    name = args.name
    cidr = getattr(args, 'cidr_flag', None) or getattr(args, 'cidr', None)
    dry = args.dry
    _ = _parse_network(cidr)
    if vpc_exists(name):
        print(f"VPC '{name}' already exists (idempotent).")
        return
    bridge = safe_ifname([name], prefix="br-", maxlen=15)
    run(["ip", "link", "add", "name", bridge, "type", "bridge"], dry=dry)
    run(["ip", "link", "set", bridge, "up"], dry=dry)
    run(["sysctl", "-w", "net.ipv4.ip_forward=1"], dry=dry)
    chain = f"vpc-{safe_ifname([name], maxlen=10)}"
    run(["iptables", "-N", chain], check=False, dry=dry)
    host_rules = []
    jump = ["iptables", "-I", "FORWARD", "-i", bridge, "-j", chain]
    if _add_rule(jump, comment=f"vpcctl:{name}:jump", dry=dry):
        host_rules.append(_insert_comment(jump, f"vpcctl:{name}:jump"))
    intra = ["iptables", "-A", chain, "-s", cidr, "-d", cidr, "-j", "ACCEPT"]
    if _add_rule(intra, comment=f"vpcctl:{name}:intra", dry=dry):
        host_rules.append(_insert_comment(intra, f"vpcctl:{name}:intra"))
    meta = {"name": name, "cidr": cidr, "bridge": bridge, "subnets": [],
            "host_iptables": host_rules, "chain": chain, "apps": [], "peers": []}
    # Do not persist state in dry-run; keep dry-run side-effect free
    if not dry:
        save_meta(name, meta)
    else:
        print("(dry-run) metadata not written for VPC create")
    print(f"Created VPC '{name}' with bridge '{bridge}' and CIDR {cidr}")


def add_subnet(args):
    require_root()
    vpc = args.vpc; sub_name = args.name
    cidr = getattr(args, 'cidr_flag', None) or getattr(args, 'cidr', None)
    dry = args.dry
    if not vpc_exists(vpc):
        print(f"VPC '{vpc}' not found. Create it first."); sys.exit(1)
    net = _parse_network(cidr)
    meta = load_meta(vpc); bridge = meta["bridge"]
    # Compute namespace name early for repair checks
    ns = f"ns-{vpc}-{sub_name}"
    # If metadata says the subnet exists, verify the namespace truly exists; if not, repair
    existing = next((s for s in meta.get("subnets", []) if s.get("name") == sub_name), None)
    if existing:
        try:
            out = subprocess.run(["ip", "netns", "list"], capture_output=True, text=True)
            ns_list = out.stdout or ""
        except Exception:
            ns_list = ""
        if ns in ns_list:
            print(f"Subnet '{sub_name}' already exists in VPC '{vpc}' (idempotent).")
            return
        else:
            print(f"Subnet '{sub_name}' recorded but namespace missing; repairing…")
    v_host = safe_ifname([vpc, sub_name], prefix="v-", maxlen=15)
    v_peer = safe_ifname([vpc, sub_name], prefix="vbr-", maxlen=15)
    run(["ip", "netns", "add", ns], dry=dry)
    run(["ip", "link", "add", v_host, "type", "veth", "peer", "name", v_peer], dry=dry)
    run(["ip", "link", "set", v_peer, "master", bridge], dry=dry)
    run(["ip", "link", "set", v_peer, "up"], dry=dry)
    run(["ip", "link", "set", v_host, "netns", ns], dry=dry)
    hosts = list(net.hosts())
    if len(hosts) < 2:
        print(f"CIDR {cidr} too small for gateway+host"); sys.exit(1)
    prefix = net.prefixlen
    if getattr(args, 'gw', None):
        bridge_gw = args.gw
        host_ip = next((str(h) for h in hosts if str(h) != bridge_gw), None)
        if not host_ip:
            print("Could not allocate host IP"); sys.exit(1)
    else:
        bridge_gw, host_ip = str(hosts[0]), str(hosts[1])
    run(["ip", "addr", "add", f"{bridge_gw}/{prefix}", "dev", bridge], check=False, dry=dry)
    run(["ip", "netns", "exec", ns, "ip", "addr", "add", f"{host_ip}/{prefix}", "dev", v_host], dry=dry)
    run(["ip", "netns", "exec", ns, "ip", "link", "set", v_host, "up"], dry=dry)
    run(["ip", "netns", "exec", ns, "ip", "link", "set", "lo", "up"], dry=dry)
    run(["ip", "netns", "exec", ns, "ip", "route", "add", "default", "via", bridge_gw], dry=dry)
    # Persist only when not dry; update existing record if repairing
    if not dry:
        if existing:
            existing.update({"cidr": cidr, "ns": ns, "gw": bridge_gw, "host_ip": host_ip, "veth": v_host})
        else:
            meta.setdefault("subnets", []).append({"name": sub_name, "cidr": cidr, "ns": ns, "gw": bridge_gw,
                                                    "host_ip": host_ip, "veth": v_host})
        save_meta(vpc, meta)
    else:
        print("(dry-run) metadata not written for add-subnet")
    # Policy merge (preserves original behavior, just factored)
    try:
        _merge_and_apply_policy(vpc, sub_name, cidr, dry)
    except Exception as e:
        print(f"Warning: policy merge/apply failed: {e}")
    print(f"Created subnet '{sub_name}' ({cidr}) in VPC '{vpc}' ns='{ns}' gw={bridge_gw}")


def _merge_and_apply_policy(vpc: str, sub_name: str, cidr: str, dry: bool):
    default_path = WORKDIR / f"policy_{vpc}_default.json"
    subnet_path = WORKDIR / f"policy_{vpc}_{sub_name}_{cidr.replace('/', '_')}.json"
    if not subnet_path.exists():
        policy = {"subnet": cidr, "ingress": [
            {"port": 80, "protocol": "tcp", "action": "allow"},
            {"port": 443, "protocol": "tcp", "action": "allow"},
            {"port": 22, "protocol": "tcp", "action": "deny"}], "egress": []}
        json.dump(policy, open(subnet_path, "w"), indent=2)
    merged: List[Dict[str, Any]] = []
    if default_path.exists():
        try:
            dp = json.load(open(default_path))
            if isinstance(dp, dict): dp = [dp]
            for e in dp:
                e = dict(e)
                if not e.get("subnet") or e.get("subnet") in ("*", cidr):
                    e["subnet"] = cidr; merged.append(e)
        except Exception as e:
            print(f"Warning: read default policy failed: {e}")
    try:
        sp = json.load(open(subnet_path))
        if isinstance(sp, dict): sp = [sp]
        for e in sp:
            ee = dict(e); ee["subnet"] = cidr; merged.append(ee)
    except Exception as e:
        print(f"Warning: read subnet policy failed: {e}")
    merged_path = WORKDIR / f"policy_{vpc}_{sub_name}_{cidr.replace('/', '_')}_merged.json"
    with open(merged_path, "w") as mf:
        json.dump(merged[0] if len(merged) == 1 else merged, mf, indent=2)
    if dry:
        print(f"Would apply merged policy (dry-run): {merged_path}")
        return
    from types import SimpleNamespace
    apply_policy(SimpleNamespace(vpc=vpc, policy_file=str(merged_path), dry=dry))
    print(f"Applied merged policy -> {merged_path}")


def list_command(args):
    vpcs = list_vpcs()
    if not vpcs:
        print("No VPCs found"); return
    for v in vpcs: print(v)


def inspect_command(args):
    name = args.name
    try:
        meta = load_meta(name)
    except FileNotFoundError:
        print(f"VPC '{name}' not found"); return
    print(json.dumps(meta, indent=2))


def delete_vpc(args):
    require_root()
    name = args.name; dry = args.dry
    if not vpc_exists(name):
        print(f"VPC '{name}' not found; nothing to delete."); return
    meta = load_meta(name)
    for app in meta.get("apps", []):
        pid = app.get("pid")
        if pid: run(["kill", "-TERM", str(pid)], check=False, dry=dry)
    for s in meta.get("subnets", []):
        ns = s.get("ns")
        run(["ip", "netns", "exec", ns, "iptables", "-F"], check=False, dry=dry)
        run(["ip", "netns", "exec", ns, "iptables", "-t", "nat", "-F"], check=False, dry=dry)
        run(["ip", "netns", "del", ns], check=False, dry=dry)
    bridge = meta.get("bridge")
    run(["ip", "link", "set", bridge, "down"], check=False, dry=dry)
    run(["ip", "link", "del", bridge, "type", "bridge"], check=False, dry=dry)
    if meta.get("nat"):
        for r in list(meta.get("host_iptables", [])):
            try: _delete_rule(r, dry=dry)
            except Exception: pass
        meta["host_iptables"] = []; save_meta(name, meta)
    chain = meta.get("chain")
    if chain:
        run(["iptables", "-D", "FORWARD", "-i", bridge, "-j", chain], check=False, dry=dry)
        run(["iptables", "-F", chain], check=False, dry=dry)
        run(["iptables", "-X", chain], check=False, dry=dry)
    if not dry:
        try: _meta_path(name).unlink()
        except Exception: pass
    print(f"Deleted VPC '{name}' and cleaned up resources")


def cleanup_all(args):
    require_root(); dry = args.dry
    vpcs = list_vpcs()
    if not vpcs:
        print("No VPCs to clean up"); return
    for v in vpcs:
        a = argparse.Namespace(name=v, dry=dry)
        delete_vpc(a)
    print("All recorded VPCs cleaned up")


def verify(args):
    out = subprocess.run(["ip", "netns", "list"], capture_output=True, text=True)
    ns_lines = out.stdout.strip().splitlines() if out.stdout else []
    vpc_ns = [l.split()[0] for l in ns_lines if l.startswith("ns-")]
    out2 = subprocess.run(["ip", "link", "show", "type", "bridge"], capture_output=True, text=True)
    br_lines = out2.stdout.strip().splitlines() if out2.stdout else []
    bridges = [ln.split()[1].rstrip(':') for ln in br_lines if len(ln.split()) >= 2 and ln.split()[1].startswith("br-")]
    print("vpcctl-looking namespaces:", vpc_ns)
    print("vpcctl-looking bridges:", bridges)
    recorded = list_vpcs()
    print("Recorded VPCs:", recorded)
    orphans = []
    for ns in vpc_ns:
        found = False
        for v in recorded:
            meta = load_meta(v)
            if any(s.get("ns") == ns for s in meta.get("subnets", [])):
                found = True; break
        if not found: orphans.append(ns)
    print("Orphan namespaces (no metadata):", orphans if orphans else "None")


def create_peer(args):
    require_root()
    vpc1, vpc2, dry = args.vpc1, args.vpc2, args.dry
    if vpc1 == vpc2:
        print("Cannot peer a VPC to itself"); sys.exit(1)
    if not (vpc_exists(vpc1) and vpc_exists(vpc2)):
        print("Both VPCs must exist to create a peer"); sys.exit(1)
    m1, m2 = load_meta(vpc1), load_meta(vpc2)
    b1, b2 = m1["bridge"], m2["bridge"]
    allow = [c.strip() for c in args.allow_cidrs.split(',')] if args.allow_cidrs else [m1.get("cidr"), m2.get("cidr")]
    veth_a = safe_ifname([vpc1, vpc2], prefix="pv-", suffix="a", maxlen=15)
    veth_b = safe_ifname([vpc1, vpc2], prefix="pv-", suffix="b", maxlen=15)
    links = subprocess.run(["ip", "link", "show"], capture_output=True, text=True).stdout
    if veth_a not in links and veth_b not in links:
        run(["ip", "link", "add", veth_a, "type", "veth", "peer", "name", veth_b], dry=dry)
        run(["ip", "link", "set", veth_a, "master", b1], dry=dry)
        run(["ip", "link", "set", veth_b, "master", b2], dry=dry)
        run(["ip", "link", "set", veth_a, "up"], dry=dry)
        run(["ip", "link", "set", veth_b, "up"], dry=dry)
    c1, c2 = m1.get("chain"), m2.get("chain")
    if not (c1 and c2):
        print("Per-VPC chains not found; ensure VPCs were created by vpcctl")
    for src in allow:
        for dst in allow:
            r1 = ["iptables", "-A", c1, "-o", b2, "-s", src, "-d", dst, "-j", "ACCEPT"]
            r2 = ["iptables", "-A", c2, "-o", b1, "-s", src, "-d", dst, "-j", "ACCEPT"]
            if _add_rule(r1, comment=f"vpcctl:peer:{vpc1}:{vpc2}", dry=dry): _record_rule(m1, r1, f"vpcctl:peer:{vpc1}:{vpc2}")
            if _add_rule(r2, comment=f"vpcctl:peer:{vpc1}:{vpc2}", dry=dry): _record_rule(m2, r2, f"vpcctl:peer:{vpc1}:{vpc2}")
    d1 = ["iptables", "-A", c1, "-o", b2, "-j", "DROP"]
    d2 = ["iptables", "-A", c2, "-o", b1, "-j", "DROP"]
    if _add_rule(d1, comment=f"vpcctl:peer-drop:{vpc1}:{vpc2}", dry=dry): _record_rule(m1, d1, f"vpcctl:peer-drop:{vpc1}:{vpc2}")
    if _add_rule(d2, comment=f"vpcctl:peer-drop:{vpc1}:{vpc2}", dry=dry): _record_rule(m2, d2, f"vpcctl:peer-drop:{vpc1}:{vpc2}")
    pr = {"peer_vpc": vpc2, "veth_a": veth_a, "veth_b": veth_b, "allowed": allow}
    if not any(p.get("peer_vpc") == vpc2 for p in m1.get("peers", [])):
        m1.setdefault("peers", []).append(pr); save_meta(vpc1, m1)
    pr_rev = {"peer_vpc": vpc1, "veth_a": veth_b, "veth_b": veth_a, "allowed": allow}
    if not any(p.get("peer_vpc") == vpc1 for p in m2.get("peers", [])):
        m2.setdefault("peers", []).append(pr_rev); save_meta(vpc2, m2)
    print(f"Peered '{vpc1}' <-> '{vpc2}' via {veth_a}/{veth_b}. Allowed: {allow}")


def enable_nat(args):
    require_root()
    name = args.name
    intf = getattr(args, 'iface_flag', None) or getattr(args, 'iface', None)
    target_subnet = getattr(args, 'subnet', None)
    all_subnets = getattr(args, 'all_subnets', False)
    dry = args.dry
    if not vpc_exists(name):
        print(f"VPC '{name}' not found"); sys.exit(1)
    meta = load_meta(name)
    bridge = meta.get("bridge")
    run(["sysctl", "-w", "net.ipv4.ip_forward=1"], dry=dry)
    cidrs: List[str] = []
    if all_subnets:
        cidrs = [s.get("cidr") for s in meta.get("subnets", []) if s.get("cidr")]
        if not cidrs and meta.get("cidr"): cidrs = [meta.get("cidr")]
    elif target_subnet:
        for s in meta.get("subnets", []):
            if s.get("name") == target_subnet and s.get("cidr"): cidrs.append(s.get("cidr")); break
    else:
        for s in meta.get("subnets", []):
            if str(s.get("name", "")).lower() == "public" and s.get("cidr"): cidrs.append(s.get("cidr"))
    if not cidrs:
        print("No subnets matched for NAT (try --subnet or --all-subnets). Leaving NAT unchanged.")
    else:
        for c in cidrs:
            nat_cmd = ["iptables", "-t", "nat", "-A", "POSTROUTING", "-s", c, "-o", intf, "-j", "MASQUERADE"]
            if _add_rule(nat_cmd, comment=f"vpcctl:{name}:nat:{c}", dry=dry): _record_rule(meta, nat_cmd, f"vpcctl:{name}:nat:{c}")
        out_rule = ["iptables", "-A", "FORWARD", "-i", bridge, "-o", intf, "-j", "ACCEPT"]
        if _add_rule(out_rule, comment=f"vpcctl:{name}:fwd-out", dry=dry): _record_rule(meta, out_rule, f"vpcctl:{name}:fwd-out")
        in_rule = ["iptables", "-A", "FORWARD", "-i", intf, "-o", bridge, "-m", "state", "--state", "ESTABLISHED,RELATED", "-j", "ACCEPT"]
        if _add_rule(in_rule, comment=f"vpcctl:{name}:fwd-in", dry=dry): _record_rule(meta, in_rule, f"vpcctl:{name}:fwd-in")
    meta["nat"] = {"interface": intf, "cidrs": cidrs}
    save_meta(name, meta)
    print((f"Enabled NAT for '{name}' via '{intf}' -> {cidrs}" if cidrs else f"No CIDRs NATed for '{name}'"))


def apply_policy(args):
    require_root(); vpc = args.vpc; pf = args.policy_file; dry = args.dry
    if not vpc_exists(vpc): print(f"VPC '{vpc}' not found"); sys.exit(1)
    try:
        pol = json.load(open(pf))
    except Exception as e:
        print(f"Failed to read policy file: {e}"); sys.exit(1)
    if isinstance(pol, dict): pol = [pol]
    meta = load_meta(vpc)
    for p in pol:
        scidr = p.get("subnet")
        if not scidr:
            print("Policy missing 'subnet'; skipping"); continue
        target = _find_subnet(meta, cidr=scidr)
        if not target:
            print(f"No subnet in VPC '{vpc}' matches {scidr}; skipping"); continue
        ns = target.get("ns")
        run(["ip", "netns", "exec", ns, "iptables", "-F"], dry=dry)
        run(["ip", "netns", "exec", ns, "iptables", "-A", "INPUT", "-i", "lo", "-j", "ACCEPT"], dry=dry)
        run(["ip", "netns", "exec", ns, "iptables", "-A", "INPUT", "-m", "state", "--state", "ESTABLISHED,RELATED", "-j", "ACCEPT"], dry=dry)
        for r in p.get("ingress", []):
            proto = r.get("protocol", "tcp"); port = r.get("port"); act = r.get("action", "allow").lower()
            if port is None: print("Skipping ingress without port"); continue
            target_rule = "ACCEPT" if act == "allow" else "DROP"
            run(["ip","netns","exec",ns,"iptables","-A","INPUT","-p",proto,"--dport",str(port),"-j",target_rule], dry=dry)
        for r in p.get("egress", []):
            proto = r.get("protocol", "tcp"); port = r.get("port"); act = r.get("action", "allow").lower()
            if port is None: print("Skipping egress without port"); continue
            target_rule = "ACCEPT" if act == "allow" else "DROP"
            run(["ip","netns","exec",ns,"iptables","-A","OUTPUT","-p",proto,"--dport",str(port),"-j",target_rule], dry=dry)
        print(f"Applied policy to {scidr} (ns {ns})")


def deploy_app(args):
    require_root(); vpc = args.vpc; subnet = args.subnet; port = getattr(args,'port_flag', None) or getattr(args,'port', None)
    dry = args.dry
    if not vpc_exists(vpc): print(f"VPC '{vpc}' not found"); sys.exit(1)
    meta = load_meta(vpc)
    target = _find_subnet(meta, name=subnet)
    if not target: print(f"Subnet '{subnet}' not found in VPC '{vpc}'"); sys.exit(1)
    ns = target.get("ns")
    cmd = ["ip","netns","exec",ns,"python3","-m","http.server",str(port)]
    print(f"Starting HTTP server in {ns} port {port}")
    if dry: print("DRY:", " ".join(cmd)); return
    try:
        shell_cmd = f"ip netns exec {ns} nohup python3 -m http.server {port} >/tmp/vpcctl-{ns}-http.log 2>&1 & echo $!"
        out = subprocess.check_output(shell_cmd, shell=True, text=True).strip()
        pid = int(out.splitlines()[-1]) if out else None
        print(f"HTTP server started ns={ns} pid={pid} log=/tmp/vpcctl-{ns}-http.log")
        meta.setdefault("apps", []).append({"ns": ns, "port": port, "pid": pid, "cmd": cmd})
        save_meta(vpc, meta)
    except Exception as e:
        print(f"Failed to start HTTP server: {e}")


def stop_app(args):
    require_root(); vpc = args.vpc; ns = args.ns; pid = args.pid; dry = args.dry
    if not vpc_exists(vpc): print(f"VPC '{vpc}' not found"); return
    meta = load_meta(vpc)
    removed = []
    for app in list(meta.get("apps", [])):
        if ns and app.get("ns") != ns: continue
        if pid and str(app.get("pid")) != str(pid): continue
        apid = app.get("pid")
        if apid: run(["kill","-TERM",str(apid)], check=False, dry=dry)
        meta.get("apps", []).remove(app); removed.append(app)
    save_meta(vpc, meta)
    print(f"Stopped apps: {removed}" if removed else "No matching apps found to stop")


def test_connectivity(args):
    target, port, from_ns, dry = args.target, args.port, args.from_ns, args.dry
    cmd = ["ip","netns","exec",from_ns,"curl","-sS",f"http://{target}:{port}"] if from_ns else ["curl","-sS",f"http://{target}:{port}"]
    print("Testing connectivity:", " ".join(cmd))
    if dry: return
    try:
        r = subprocess.run(cmd, check=True, capture_output=True, timeout=5)
        out = r.stdout.decode(errors='ignore')
        print("Connectivity OK — response snapshot:\n", out[:200])
    except subprocess.CalledProcessError:
        print("Connectivity test failed (non-zero exit)")
    except Exception as e:
        print(f"Connectivity test error: {e}")


# ------------------------------------------------------------------
# Demo orchestration (kept same semantics)
# ------------------------------------------------------------------

def run_demo(args):
    execute = args.execute; iface = args.iface; dry = not execute
    a = {"name": "demo-a", "cidr": "10.10.0.0/16", "public": "10.10.1.0/24", "private": "10.10.2.0/24"}
    b = {"name": "demo-b", "cidr": "10.20.0.0/16", "public": "10.20.1.0/24"}
    steps = [
        ("create", [a['name'], a['cidr']]),
        ("add-subnet", [a['name'], "public", a['public']]),
        ("add-subnet", [a['name'], "private", a['private']]),
        ("create", [b['name'], b['cidr']]),
        ("add-subnet", [b['name'], "public", b['public']]),
        ("deploy-app", [a['name'], "public", "8080"]),
    ]
    if execute:
        if not iface:
            print("--internet-iface required with --execute"); return
        steps.append(("enable-nat", [a['name'], iface]))
    steps.append(("peer", [a['name'], b['name'], "--allow-cidrs", f"{a['public']},{b['public']}"]))
    for cmd_name, argv in steps:
        print(f"\n=== STEP: {cmd_name} {' '.join(argv)} ===")
        ns = argparse.Namespace(dry=dry)
        try:
            if cmd_name == "create": ns.name, ns.cidr = argv; create_vpc(ns)
            elif cmd_name == "add-subnet": ns.vpc, ns.name, ns.cidr = argv; add_subnet(ns)
            elif cmd_name == "deploy-app": ns.vpc, ns.subnet, ns.port = argv; deploy_app(ns)
            elif cmd_name == "enable-nat": ns.name, ns.iface = argv; enable_nat(ns)
            elif cmd_name == "peer": ns.vpc1, ns.vpc2 = argv[0], argv[1]; ns.allow_cidrs = argv[3]; create_peer(ns)
        except Exception as e:
            print(f"Step failed: {e}")
    print("\n=== DEMO TESTS ===")
    if dry:
        print("Demo ran in dry-run mode. Use --execute for real."); return
    try:
        ma, mb = load_meta(a['name']), load_meta(b['name'])
        gw_a = next(s['gw'] for s in ma['subnets'] if s['name'] == 'public')
        gw_b = next(s['gw'] for s in mb['subnets'] if s['name'] == 'public')
        ns_from = next(s['ns'] for s in ma['subnets'] if s['name'] == 'private')
        print(f"Test: {ns_from} -> {gw_a}:8080")
        test_connectivity(argparse.Namespace(target=gw_a, port=8080, from_ns=ns_from, dry=False))
        print(f"Test: {ns_from} -> {gw_b}:8080 (post-peering)")
        test_connectivity(argparse.Namespace(target=gw_b, port=8080, from_ns=ns_from, dry=False))
    except Exception as e:
        print(f"Demo checks skipped/failed: {e}")


# ------------------------------------------------------------------
# Flag / parser helpers
# ------------------------------------------------------------------

def build_parser():
    p = argparse.ArgumentParser(prog="vpcctl", description="Minimal VPC controller (refined)")
    p.add_argument("--dry-run", dest="dry", action="store_true", help="Print commands without running")
    sub = p.add_subparsers(dest="cmd")
    pc = sub.add_parser("create", help="Create a VPC")
    pc.add_argument("name"); pc.add_argument("cidr", nargs="?")
    pc.add_argument("--cidr", dest="cidr_flag")
    pa = sub.add_parser("add-subnet", help="Add a subnet to a VPC")
    pa.add_argument("vpc"); pa.add_argument("name"); pa.add_argument("cidr", nargs="?")
    pa.add_argument("--cidr", dest="cidr_flag"); pa.add_argument("--gw", dest="gw")
    sub.add_parser("list", help="List VPCs")
    pi = sub.add_parser("inspect", help="Inspect a VPC"); pi.add_argument("name")
    pd = sub.add_parser("delete", help="Delete a VPC"); pd.add_argument("name")
    pn = sub.add_parser("enable-nat", help="Enable NAT for a VPC")
    pn.add_argument("name"); pn.add_argument("iface", nargs="?")
    pn.add_argument("--interface", dest="iface_flag"); pn.add_argument("--subnet", dest="subnet")
    pn.add_argument("--all-subnets", dest="all_subnets", action="store_true")
    pp = sub.add_parser("peer", help="Peer two VPCs")
    pp.add_argument("vpc1"); pp.add_argument("vpc2"); pp.add_argument("--allow-cidrs", dest="allow_cidrs")
    pol = sub.add_parser("apply-policy", help="Apply subnet policy JSON")
    pol.add_argument("vpc"); pol.add_argument("policy_file")
    pdp = sub.add_parser("deploy-app", help="Deploy HTTP server")
    pdp.add_argument("vpc"); pdp.add_argument("subnet"); pdp.add_argument("port", nargs="?", default=8080, type=int)
    pdp.add_argument("--port", dest="port_flag", type=int)
    psa = sub.add_parser("stop-app", help="Stop app (by ns or pid)")
    psa.add_argument("vpc"); psa.add_argument("--ns", dest="ns"); psa.add_argument("--pid", dest="pid")
    pt = sub.add_parser("test-connectivity", help="Test connectivity")
    pt.add_argument("target"); pt.add_argument("port", nargs="?", default=80, type=int)
    pt.add_argument("--from-ns", dest="from_ns")
    sub.add_parser("cleanup-all", help="Delete all VPCs")
    sub.add_parser("verify", help="Report related resources")
    demo = sub.add_parser("run-demo", help="Run demo (dry-run default)")
    demo.add_argument("--execute", action="store_true")
    demo.add_argument("--internet-iface", dest="iface")
    sub.add_parser("flag-check", help="Validate flags only")
    return p


def run_flag_check():
    _ = build_parser(); print("flag-check: parser built successfully")


# ------------------------------------------------------------------
# Dispatch + main
# ------------------------------------------------------------------

def _ensure_dry(args):
    if not hasattr(args, "dry"): args.dry = False


DISPATCH: Dict[str, Callable] = {
    "create": create_vpc,
    "add-subnet": add_subnet,
    "list": list_command,
    "inspect": inspect_command,
    "delete": delete_vpc,
    "enable-nat": enable_nat,
    "apply-policy": apply_policy,
    "deploy-app": deploy_app,
    "stop-app": stop_app,
    "test-connectivity": test_connectivity,
    "cleanup-all": cleanup_all,
    "verify": verify,
    "peer": create_peer,
    "run-demo": run_demo,
    "flag-check": lambda _a: run_flag_check(),
}


def main():
    parser = build_parser(); args = parser.parse_args(); _ensure_dry(args)
    cmd = getattr(args, "cmd", None)
    if not cmd: parser.print_help(); sys.exit(0)
    h = DISPATCH.get(cmd)
    if not h: parser.print_help(); sys.exit(2)
    h(args)


if __name__ == "__main__":  # pragma: no cover (entry point)
    main()
