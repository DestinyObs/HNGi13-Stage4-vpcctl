#!/usr/bin/env bash
set -euo pipefail

echo "STARTING FORCE CLEANUP (non-destructive to host interfaces)."

# 1) Stop processes inside namespaces and delete namespaces
for ns in $(ip netns list 2>/dev/null | awk '{print $1}' || true); do
  echo "==> namespace: $ns"
  pids=$(ip netns pids "$ns" 2>/dev/null || true)
  if [[ -n "$pids" ]]; then
    echo "  Killing PIDs in $ns: $pids"
    kill -TERM $pids 2>/dev/null || true
    sleep 0.2
  fi
  echo "  Flushing namespace iptables"
  ip netns exec "$ns" iptables -F 2>/dev/null || true
  ip netns exec "$ns" iptables -t nat -F 2>/dev/null || true
  echo "  Deleting namespace $ns"
  ip netns del "$ns" 2>/dev/null || true
done

# 2) Remove host-level FORWARD jump rules that reference vpc chains/bridges
echo "==> Removing host FORWARD jump rules referencing bridges or vpc chains"
# Delete forward rules referencing br-*
while read -r rule; do
  # convert '-A ...' to '-D ...'
  dcmd=$(echo "$rule" | sed 's/^-A /-D /')
  echo "  Deleting host FORWARD rule: $dcmd"
  iptables $dcmd 2>/dev/null || true
done < <(iptables -S | grep '^ -A FORWARD\|^-A FORWARD' || true)

# Also remove specific FORWARD rules that include br- names:
for br in $(ip -o link | awk -F': ' '{print $2}' | grep '^br-' 2>/dev/null || true); do
  echo "  Scanning FORWARD rules for bridge $br"
  # list matching FORWARD lines and delete them
  iptables -S | grep -E "^-A FORWARD .* -i $br |^-A FORWARD .* -o $br" | sed 's/^-A /-D /' | while read -r dcmd; do
    echo "    Deleting: $dcmd"
    iptables $dcmd 2>/dev/null || true
  done
done

# 3) Remove host-level vpc-* chains (flush jumps referencing them first)
echo "==> Deleting host chains named vpc* (flush and delete)"
# Find custom chains names that start with vpc
for chain in $(iptables -S | awk '/^-N /{print $2}' | grep '^vpc' 2>/dev/null || true); do
  echo "  Chain: $chain"
  # Delete any jumps elsewhere that reference this chain
  iptables -S | grep -F " -j $chain" | sed 's/^-A /-D /' | while read -r j; do
    echo "    Deleting jump rule: $j"
    iptables $j 2>/dev/null || true
  done
  echo "  Flushing $chain"
  iptables -F "$chain" 2>/dev/null || true
  echo "  Deleting $chain"
  iptables -X "$chain" 2>/dev/null || true
done

# 4) Remove nat rules added by vpcctl (look for comment tokens or vpcctl in nat table)
echo "==> Deleting NAT rules that mention vpcctl"
iptables -t nat -S | grep -i vpcctl || true | while read -r line; do
  # convert '-A' to '-D' and run deletion attempt
  dcmd=$(echo "$line" | sed 's/^-A /-D /')
  echo "  Deleting nat rule: $dcmd"
  iptables -t nat $dcmd 2>/dev/null || true
done

# 5) Bring down and delete bridges (br-*)
echo "==> Deleting bridges named br-*"
for br in $(ip -o link | awk -F': ' '{print $2}' | grep '^br-' 2>/dev/null || true); do
  echo "  Bridge: $br"
  ip link set "$br" down 2>/dev/null || true
  # try deleting as a bridge first, else try a generic ip link delete
  ip link del "$br" type bridge 2>/dev/null || ip link delete "$br" 2>/dev/null || true
done

# 6) Delete veth/pv interfaces that look like our patterns
echo "==> Deleting veth-like interfaces"
for ifn in $(ip -o link | awk -F': ' '{print $2}' | grep -E '^(veth-|v-|v-|pv-|pv-t|pv-t1|v-t1|v-)' 2>/dev/null || true); do
  echo "  Deleting interface $ifn"
  ip link delete "$ifn" 2>/dev/null || true
done

echo "Cleanup attempts complete. Re-run checks:"
ip netns list || true
ip -o link | awk -F': ' '{print $2}' | grep -E '^(br-|veth|v-|pv-|pv-t|vpc-)' || true
echo "Host iptables chains:"
iptables -S | sed -n '1,200p' || true
iptables -t nat -S | sed -n '1,200p' || true

echo "FORCE CLEANUP finished."
