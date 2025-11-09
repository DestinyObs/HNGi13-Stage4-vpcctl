#!/usr/bin/env bash
set -euo pipefail

# Acceptance test script for vpcctl
# - Captures outputs for graders under docs/samples/actual-<timestamp>/
# - Safe by default: does a dry-run first and prompts for confirmation before making changes
# - Must be run on a Linux host with sudo/root privileges

HERE=$(cd "$(dirname "$0")" && pwd)
REPO_ROOT=$(cd "$HERE/.." && pwd)
PY=vpcctl.py
OUTPUT_BASE="$REPO_ROOT/docs/samples"
TS=$(date -u +%Y%m%dT%H%M%SZ)
OUTDIR="$OUTPUT_BASE/actual-$TS"

usage(){
  cat <<EOF
Usage: sudo ./scripts/acceptance_test.sh [--apply] [--iface <host-iface>] [--keep]

By default the script runs a dry-run and shows the exact commands it will run.
Pass --apply to perform the test actions (will create namespaces, bridges, iptables rules).
--iface <host-iface> : specify the host interface to use for NAT (default: auto-detect)
--keep : do not delete created VPCs at the end (for debugging)
EOF
  exit 1
}

APPLY=0
KEEP=0
HOST_IFACE=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --apply) APPLY=1; shift;;
    --keep) KEEP=1; shift;;
    --iface) HOST_IFACE="$2"; shift 2;;
    -h|--help) usage;;
    *) echo "Unknown arg: $1"; usage;;
  esac
done

mkdir -p "$OUTDIR"
echo "Outputs will be written to: $OUTDIR"

echo "--- Step 0: quick python syntax check (compile-only) ---"
python3 -m py_compile "$REPO_ROOT/$PY" 2>&1 | tee "$OUTDIR/py_compile.txt" || true

echo "--- Step 1: parser-only validation (flag-check) ---"
sudo python3 "$REPO_ROOT/$PY" flag-check 2>&1 | tee "$OUTDIR/flag_check.txt" || true

echo "--- Step 2: dry-run create preview ---"
python3 "$REPO_ROOT/$PY" --dry-run create tst_vpc --cidr 10.99.0.0/16 2>&1 | tee "$OUTDIR/dryrun_create.txt" || true

if [[ $APPLY -ne 1 ]]; then
  echo "DRY RUN only. To actually run the test operations use: sudo ./scripts/acceptance_test.sh --apply"
  exit 0
fi

read -p "About to perform live test operations on this host (namespaces, iptables). Continue? [y/N] " -r
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
  echo "Aborted by user."; exit 1
fi

# detect host iface for NAT if not provided
if [[ -z "$HOST_IFACE" ]]; then
  HOST_IFACE=$(ip route get 8.8.8.8 2>/dev/null | awk '/dev/ {for(i=1;i<=NF;i++) if($i=="dev") print $(i+1)}' | head -n1 || true)
  if [[ -z "$HOST_IFACE" ]]; then
    echo "Could not auto-detect host interface for NAT. Use --iface <iface>"; exit 1
  fi
fi

echo "Using host interface: $HOST_IFACE"

logcmd(){
  echo "+ $*" | tee -a "$OUTDIR/commands.log"
  "$@" 2>&1 | tee -a "$OUTDIR/$(date -u +%Y%m%dT%H%M%SZ)-$(echo "$*" | tr ' /' '__' | tr -cs 'A-Za-z0-9_.' '_').txt"
}

echo "--- Step 3: create VPCs and subnets ---"
logcmd sudo python3 "$REPO_ROOT/$PY" create t1_vpc --cidr 10.30.0.0/16
logcmd sudo python3 "$REPO_ROOT/$PY" add-subnet t1_vpc public --cidr 10.30.1.0/24
logcmd sudo python3 "$REPO_ROOT/$PY" add-subnet t1_vpc private --cidr 10.30.2.0/24

echo "--- Step 4: deploy HTTP app in t1_vpc public ---"
logcmd sudo python3 "$REPO_ROOT/$PY" deploy-app t1_vpc public --port 8080

echo "--- Step 5: enable NAT for t1_vpc ---"
logcmd sudo python3 "$REPO_ROOT/$PY" enable-nat t1_vpc --interface "$HOST_IFACE"

echo "--- Step 6: create t2_vpc and deploy app ---"
logcmd sudo python3 "$REPO_ROOT/$PY" create t2_vpc --cidr 10.40.0.0/16
logcmd sudo python3 "$REPO_ROOT/$PY" add-subnet t2_vpc public --cidr 10.40.1.0/24
logcmd sudo python3 "$REPO_ROOT/$PY" deploy-app t2_vpc public --port 8080

echo "--- Step 7: peer VPCs (public CIDRs) ---"
logcmd sudo python3 "$REPO_ROOT/$PY" peer t1_vpc t2_vpc --allow-cidrs 10.30.1.0/24,10.40.1.0/24

echo "--- Step 8: apply sample policy to t1_vpc ---"
# Discover the actual network CIDR for the t1_vpc public subnet and generate
# a temporary policy file that targets that subnet so `apply-policy` is exercised.
T1_ADDR_CIDR=$(sudo ip netns exec ns-t1_vpc-public ip -4 -o addr show dev v-t1-vpc-public | awk '{print $4}' | head -n1 || true)
if [[ -n "$T1_ADDR_CIDR" ]]; then
  T1_NET=$(python3 - <<PY
import ipaddress,sys
addr=sys.argv[1]
print(ipaddress.ip_network(addr, strict=False))
PY
  "$T1_ADDR_CIDR")
  POLICY_TMP="$OUTDIR/policy_t1_vpc.json"
  cat > "$POLICY_TMP" <<JSON
{
  "subnet": "$T1_NET",
  "ingress": [ { "port": 80, "protocol": "tcp", "action": "allow" } ],
  "egress": [ { "port": 80, "protocol": "tcp", "action": "allow" } ]
}
JSON
  echo "Applying generated policy $POLICY_TMP (targets $T1_NET)" | tee -a "$OUTDIR/commands.log"
  logcmd sudo python3 "$REPO_ROOT/$PY" apply-policy t1_vpc "$POLICY_TMP"
else
  echo "Could not determine t1_vpc public address; applying example policy file instead" | tee -a "$OUTDIR/commands.log"
  logcmd sudo python3 "$REPO_ROOT/$PY" apply-policy t1_vpc "$REPO_ROOT/policy_examples/example_ingress_egress_policy.json"
fi

echo "--- Step 9: capture snapshots (ip netns, ip addr, iptables) ---"
sudo ip netns list | tee "$OUTDIR/ip_netns_list.txt"
sudo ip netns exec ns-t1_vpc-public ip addr | tee "$OUTDIR/ns-t1_vpc-public_ip_addr.txt"
sudo ip netns exec ns-t2_vpc-public ip addr | tee "$OUTDIR/ns-t2_vpc-public_ip_addr.txt" || true
sudo iptables -S | tee "$OUTDIR/iptables_all_rules.txt"
sudo iptables -t nat -S | tee "$OUTDIR/iptables_nat_rules.txt"
sudo iptables -S "vpc-t1_vpc" 2>/dev/null | tee "$OUTDIR/iptables_vpc-t1_vpc.txt" || true

echo "--- Step 10: connectivity tests (curl from t2->t1 and local namespace tests) ---"
T1_IP=""
if [[ -n "${T1_ADDR_CIDR:-}" ]]; then
  T1_IP=$(echo "$T1_ADDR_CIDR" | cut -d/ -f1)
else
  # fallback: try to read from namespace directly
  T1_IP=$(sudo ip netns exec ns-t1_vpc-public ip -4 -o addr show dev v-t1-vpc-public | awk '{print $4}' | cut -d/ -f1 | head -n1 || true)
fi

if [[ -n "$T1_IP" ]]; then
  echo "Curling http://$T1_IP:8080 from ns-t2_vpc-public" | tee -a "$OUTDIR/commands.log"
  sudo ip netns exec ns-t2_vpc-public curl -sS --max-time 5 "http://${T1_IP}:8080/" -o "$OUTDIR/curl_t2_to_t1_body.html" || echo "curl failed" | tee -a "$OUTDIR/connectivity.txt"
else
  echo "Could not determine t1_vpc public IP for connectivity test" | tee -a "$OUTDIR/connectivity.txt"
fi

echo "--- Step 11: stop apps and cleanup (unless --keep) ---"
if [[ $KEEP -eq 0 ]]; then
  logcmd sudo python3 "$REPO_ROOT/$PY" stop-app t1_vpc --ns ns-t1_vpc-public || true
  logcmd sudo python3 "$REPO_ROOT/$PY" stop-app t2_vpc --ns ns-t2_vpc-public || true
  logcmd sudo python3 "$REPO_ROOT/$PY" delete t1_vpc || true
  logcmd sudo python3 "$REPO_ROOT/$PY" delete t2_vpc || true
else
  echo "--keep specified; leaving resources intact for debugging" | tee -a "$OUTDIR/commands.log"
fi

echo "Acceptance test complete. Outputs are in: $OUTDIR"
echo "If you want me to open/parse those outputs and produce a PASS/FAIL matrix, upload the directory or paste its key files and I'll analyze them."

echo "--- Step 12: Basic PASS/FAIL analysis ---"
PASSFAIL="$OUTDIR/passfail.txt"
echo "Acceptance test analysis" > "$PASSFAIL"

# Check namespaces
echo -n "Namespaces: " >> "$PASSFAIL"
if sudo ip netns list | grep -q ns-t1_vpc-public && sudo ip netns list | grep -q ns-t2_vpc-public; then
  echo "OK" >> "$PASSFAIL"
else
  echo "MISSING" >> "$PASSFAIL"
fi

# Check HTTP servers started (look for saved PID lines in commands.log or processes)
echo -n "HTTP servers: " >> "$PASSFAIL"
if grep -q "HTTP server started" "$OUTDIR/commands.log" || (pgrep -f "python3 -m http.server" >/dev/null 2>&1); then
  echo "OK" >> "$PASSFAIL"
else
  echo "MISSING" >> "$PASSFAIL"
fi

# Check connectivity result
echo -n "Connectivity (t2 -> t1 HTTP): " >> "$PASSFAIL"
if [[ -s "$OUTDIR/curl_t2_to_t1_body.html" ]]; then
  echo "OK" >> "$PASSFAIL"
else
  echo "FAIL" >> "$PASSFAIL"
fi

echo "PASS/FAIL report written to: $PASSFAIL"
