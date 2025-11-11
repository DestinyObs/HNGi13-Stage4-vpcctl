# The Complete Beginner's Guide to vpcctl: Building Virtual Networks on Linux

**A hands-on, beginner-friendly guide to understanding Virtual Private Clouds and building isolated networks on a single Linux machine**

---

## Table of Contents

1. [Introduction: What Problem Are We Solving?](#introduction-what-problem-are-we-solving)
2. [Understanding the Basics](#understanding-the-basics)
   - [What is a VPC?](#what-is-a-vpc)
   - [What is a Subnet?](#what-is-a-subnet)
   - [What is NAT?](#what-is-nat)
   - [What is Peering?](#what-is-peering)
3. [Real-World Scenario: The Coffee Shop Network](#real-world-scenario-the-coffee-shop-network)
4. [How vpcctl Works Under the Hood](#how-vpcctl-works-under-the-hood)
5. [Prerequisites and Installation](#prerequisites-and-installation)
6. [Quick Start: Your First VPC](#quick-start-your-first-vpc)
7. [Deep Dive: Understanding Each Command](#deep-dive-understanding-each-command)
8. [Architecture Overview](#architecture-overview)
9. [Command Reference](#command-reference)
10. [Advanced Scenarios](#advanced-scenarios)
11. [Troubleshooting Common Issues](#troubleshooting-common-issues)
12. [Complete Code Reference](#complete-code-reference)
13. [Best Practices](#best-practices)
14. [Learning Resources](#learning-resources)
15. [Credits](#credits)

---

## Introduction: What Problem Are We Solving?

Imagine you're a developer working on a web application with:

- A web server that customers access
- A database that stores customer data
- An admin panel for internal staff

You want to:

1. Isolate your database so random people on the internet can't access it
2. Allow your web server to talk to the database
3. Control which ports and services are accessible from outside
4. Test everything locally before deploying to the cloud

Cloud providers (AWS, Azure, Google Cloud) solve this with VPCs (Virtual Private Clouds). vpcctl lets you simulate VPCs locally on Linux using native networking features.

---

## Understanding the Basics

### What is a VPC?

VPC stands for Virtual Private Cloud. It's a logically isolated network where you control IP ranges, routing, internet access, and security rules. Think of it like an office building where you control entrances, floors, and WiFi.

### What is a Subnet?

A subnet is a smaller network inside your VPC with its own IP range and purpose (e.g., public web, private database). Common types:

- Public subnet: can reach the internet and may accept inbound traffic
- Private subnet: no direct internet access; used for internal services

### What is NAT?

NAT (Network Address Translation) lets private subnets access the internet without exposing them. Like a hotel reception calling restaurants on behalf of guests—responses come back via reception.

### What is Peering?

Peering connects two VPCs so they can talk privately. Useful for connecting apps across isolated networks while allowing only specific subnets to communicate.

---

## Real-World Scenario: The Coffee Shop Network

Picture a coffee shop:

- Customer Area = Public subnet (internet access, open to customers)
- Kitchen = Private subnet (staff-only, no direct internet from outside)
- Office = Another private subnet (admin-only)

Translating to vpcctl, creating a VPC is like building that coffee shop; adding subnets creates the areas; NAT is the WiFi router; firewall rules control who gets in.

---

## How vpcctl Works Under the Hood

vpcctl uses Linux primitives:

1. Network namespaces: isolated network environments per subnet
2. veth pairs: virtual cables connecting namespaces to the VPC
3. Linux bridges: the VPC switch interconnecting subnets
4. iptables: firewall rules, NAT, and peering enforcement

---

## Prerequisites and Installation

### System Requirements

- Linux (Ubuntu 20.04+/Debian 10+ recommended). Use WSL/VM on Windows if needed.
- Root access (sudo) required
- Tools: Python 3.6+, iproute2 (ip), iptables, curl, tcpdump, bridge-utils

### Install Steps

1) Install required packages

```bash
sudo apt update
sudo apt install -y python3 iproute2 iptables curl tcpdump bridge-utils
# CentOS/RHEL: sudo yum install -y python3 iproute iptables curl tcpdump bridge-utils
```

2) Get vpcctl

```bash
git clone https://github.com/DestinyObs/HNGi13-Stage4-vpcctl
cd HNGi13-Stage4-vpcctl
```

3) Make it available as a command

```bash
chmod +x vpcctl.py
sudo ln -s "$(pwd)/vpcctl.py" /usr/local/bin/vpcctl
vpcctl --help
sudo vpcctl flag-check  # safe: validates parser only
```

---

## Quick Start: Your First VPC

We'll use these consistent names and CIDRs everywhere:

- myvpc: 10.10.0.0/16
  - public: 10.10.1.0/24
  - private: 10.10.2.0/24
- othervpc: 10.20.0.0/16
  - public: 10.20.1.0/24

### Step 0: One-Time Checks

```bash
sudo vpcctl --help | head -n 5
sudo vpcctl flag-check
```

### Step 1: Create the VPC

```bash
sudo vpcctl create myvpc --cidr 10.10.0.0/16
```

### Step 2: Add Subnets

```bash
sudo vpcctl add-subnet myvpc public  --cidr 10.10.1.0/24
sudo vpcctl add-subnet myvpc private --cidr 10.10.2.0/24
```

### Step 3: Deploy Test Apps

```bash
sudo vpcctl deploy-app myvpc public  --port 8080
sudo vpcctl deploy-app myvpc private --port 8081
```

### Step 4: Enable NAT (Internet Access for public)

```bash
IFACE=$(ip route get 1.1.1.1 | awk '{print $5; exit}')
echo "Using host interface: $IFACE"
sudo vpcctl enable-nat myvpc --interface "$IFACE"
```

### Step 5: Test Connectivity

```bash
# Private -> Public (intra-VPC)
sudo ip netns exec ns-myvpc-private curl -s http://10.10.1.2:8080 | head -n 1

# Public -> Internet (NAT)
sudo ip netns exec ns-myvpc-public curl -I http://1.1.1.1 | head -5 

# Host -> Private (should fail)
curl -s --connect-timeout 2 http://10.10.2.2:8081 || echo "private not reachable from host (expected)"
```

### Step 6: Show VPC Isolation

```bash
sudo vpcctl create othervpc --cidr 10.20.0.0/16
sudo vpcctl add-subnet othervpc public --cidr 10.20.1.0/24
sudo vpcctl deploy-app othervpc public --port 8080
sudo ip netns exec ns-myvpc-public curl -s --connect-timeout 2 http://10.20.1.2:8080 || echo "blocked by default (expected)"
```

### Step 7: Peer VPCs (Allow Only Public↔Public)

```bash
sudo vpcctl peer myvpc othervpc --allow-cidrs 10.10.1.0/24,10.20.1.0/24
sudo ip netns exec ns-myvpc-public curl -s http://10.20.1.2:8080 | head -n 1
```

### Step 8: Apply Security Policy

```bash
sudo vpcctl apply-policy myvpc policy_examples/example_ingress_egress_policy.json
```

### Step 9: Inspect and List

```bash
sudo vpcctl list
sudo vpcctl inspect myvpc | head -n 30
```

### Step 10: Cleanup

```bash
sudo vpcctl delete othervpc
sudo vpcctl delete myvpc
sudo vpcctl list
```

---

## Deep Dive: Understanding Each Command

Below are the key commands and what happens under the hood.

### create

Command

```bash
sudo vpcctl create myvpc --cidr 10.10.0.0/16
```

What happens

- Creates a Linux bridge br-myvpc and assigns 10.10.0.1/16
- Enables routing and prepares an iptables chain vpc-myvpc
- Records metadata to .vpcctl_data/vpc_myvpc.json

Under the hood

- Creates a Linux bridge device (br-myvpc) and brings it up
- Assigns the VPC gateway IP to the bridge interface and enables IPv4 forwarding (sysctl)
- Creates/uses a dedicated host iptables chain (vpc-myvpc) to keep VPC rules isolated and easy to clean up

Example commands

```bash
# Create bridge for the VPC and assign gateway IP
sudo ip link add name br-myvpc type bridge
sudo ip addr add 10.10.0.1/16 dev br-myvpc
sudo ip link set br-myvpc up

# Enable kernel forwarding
sudo sysctl -w net.ipv4.ip_forward=1

# Create isolated chain for VPC rules and hook into FORWARD
sudo iptables -N vpc-myvpc 2>/dev/null || true
sudo iptables -C FORWARD -j vpc-myvpc 2>/dev/null || sudo iptables -A FORWARD -j vpc-myvpc
```

### add-subnet

Command

```bash
sudo vpcctl add-subnet myvpc public --cidr 10.10.1.0/24
```

What happens

- Creates namespace ns-myvpc-public
- Creates a veth pair; one end attaches to br-myvpc, the other goes into the namespace
- Assigns 10.10.1.1/24 to the bridge and 10.10.1.2/24 inside the namespace; sets default route via 10.10.1.1

Under the hood

- Adds a network namespace (ns-myvpc-public) and a veth pair (host end on br-myvpc, peer moved into the namespace)
- Configures IP addresses on both ends and sets the subnet's default route to the VPC bridge gateway
- Ensures interfaces are up and connected via the bridge for L2 switching between subnets in the same VPC

Example commands (public subnet 10.10.1.0/24)

```bash
# Create namespace and veth pair
sudo ip netns add ns-myvpc-public
sudo ip link add v-myvpc-public type veth peer name v-myvpc-public-ns

# Attach host end to the VPC bridge
sudo ip link set v-myvpc-public master br-myvpc
sudo ip link set v-myvpc-public up

# Move peer into the namespace and configure IPs
sudo ip link set v-myvpc-public-ns netns ns-myvpc-public
sudo ip addr add 10.10.1.1/24 dev br-myvpc
sudo ip netns exec ns-myvpc-public ip addr add 10.10.1.2/24 dev v-myvpc-public-ns
sudo ip netns exec ns-myvpc-public ip link set lo up
sudo ip netns exec ns-myvpc-public ip link set v-myvpc-public-ns up
sudo ip netns exec ns-myvpc-public ip route add default via 10.10.1.1
```

### deploy-app

Command

```bash
sudo vpcctl deploy-app myvpc public --port 8080
```

What happens

- Runs python3 -m http.server PORT in the target namespace
- Captures PID and stores it in metadata for reliable stop/cleanup

Under the hood

- Executes the HTTP server with ip netns exec so the process is fully inside the subnet namespace
- Starts the server in the background and records its PID/command so it can be stopped and cleaned up deterministically

Example commands (serve 8080 from ns-myvpc-public)

```bash
sudo ip netns exec ns-myvpc-public nohup python3 -m http.server 8080 \
  > /tmp/ns-myvpc-public-8080.log 2>&1 &
echo $!  # PID recorded to metadata
```

### stop-app

Command

```bash
sudo vpcctl stop-app myvpc public
```

What happens

- Looks up the PID from metadata and terminates the app in the namespace
- Updates metadata

Under the hood

- Reads the stored PID/command and sends a graceful SIGTERM; falls back to stronger signals if needed
- Removes the application entry from the VPC metadata to keep state consistent

Example commands

```bash
sudo kill -TERM <PID>
# If needed after timeout: sudo kill -KILL <PID>
```

### enable-nat

Command

```bash
sudo vpcctl enable-nat myvpc --interface eth0
```

What happens

- Enables IPv4 forwarding
- Adds NAT (MASQUERADE) and FORWARD rules to let selected subnets reach the internet via the host interface

Under the hood

- Turns on kernel routing (net.ipv4.ip_forward=1)
- Installs an iptables NAT POSTROUTING MASQUERADE rule on the chosen egress interface, scoped to the VPC/subnets
- Adds FORWARD rules to permit established/related return traffic, keeping the ruleset minimal and safe

Example commands (egress via $IFACE)

```bash
IFACE=$(ip route | awk '/default/ {print $5; exit}')
sudo sysctl -w net.ipv4.ip_forward=1

# NAT for the VPC CIDR
sudo iptables -t nat -C POSTROUTING -s 10.10.0.0/16 -o "$IFACE" -j MASQUERADE \
  2>/dev/null || sudo iptables -t nat -A POSTROUTING -s 10.10.0.0/16 -o "$IFACE" -j MASQUERADE

# Forwarding rules: allow outbound and established return
sudo iptables -C FORWARD -i br-myvpc -o "$IFACE" -j ACCEPT \
  2>/dev/null || sudo iptables -A FORWARD -i br-myvpc -o "$IFACE" -j ACCEPT
sudo iptables -C FORWARD -i "$IFACE" -o br-myvpc -m state --state RELATED,ESTABLISHED -j ACCEPT \
  2>/dev/null || sudo iptables -A FORWARD -i "$IFACE" -o br-myvpc -m state --state RELATED,ESTABLISHED -j ACCEPT
```

### peer

Command

```bash
sudo vpcctl peer myvpc othervpc --allow-cidrs 10.10.1.0/24,10.20.1.0/24
```

What happens

- Creates a veth pair connecting br-myvpc and br-othervpc
- Adds iptables rules to allow only the specified CIDR pairs; everything else remains blocked

Under the hood

- Connects the two VPC bridges with a veth pair to provide L2 reachability between VPCs
- Adds explicit host-level iptables rules to allow only the permitted CIDR ranges; a final DROP ensures least-privilege

Example commands (peer myvpc ↔ othervpc, allow public↔public only)

```bash
# Wire the bridges with a veth pair
sudo ip link add pv-myvpc-otherv-a type veth peer name pv-myvpc-otherv-b
sudo ip link set pv-myvpc-otherv-a master br-myvpc
sudo ip link set pv-myvpc-otherv-b master br-othervpc
sudo ip link set pv-myvpc-otherv-a up
sudo ip link set pv-myvpc-otherv-b up

# Allow only specific CIDR pairs
sudo iptables -C vpc-myvpc   -s 10.10.1.0/24 -d 10.20.1.0/24 -j ACCEPT 2>/dev/null \
  || sudo iptables -A vpc-myvpc   -s 10.10.1.0/24 -d 10.20.1.0/24 -j ACCEPT
sudo iptables -C vpc-othervpc -s 10.20.1.0/24 -d 10.10.1.0/24 -j ACCEPT 2>/dev/null \
  || sudo iptables -A vpc-othervpc -s 10.20.1.0/24 -d 10.10.1.0/24 -j ACCEPT
# (Default-deny handled by chain policy or fallback rules)
```

### apply-policy

Command

```bash
sudo vpcctl apply-policy myvpc policy_examples/example_ingress_egress_policy.json
```

What happens

- Parses JSON and applies ingress/egress rules with iptables inside the target subnet namespace
- Uses rule comments to stay idempotent on re-apply

Under the hood

- Enters the subnet namespace and writes INPUT/OUTPUT rules with iptables
- Uses consistent comments/tags so re-applying the same policy updates rules without duplication

Example commands (inside ns-myvpc-public)

```bash
# Allow HTTP/HTTPS, deny SSH
sudo ip netns exec ns-myvpc-public iptables -C INPUT -p tcp --dport 80  -j ACCEPT 2>/dev/null \
  || sudo ip netns exec ns-myvpc-public iptables -A INPUT -p tcp --dport 80  -j ACCEPT -m comment --comment vpcctl:allow-80
sudo ip netns exec ns-myvpc-public iptables -C INPUT -p tcp --dport 443 -j ACCEPT 2>/dev/null \
  || sudo ip netns exec ns-myvpc-public iptables -A INPUT -p tcp --dport 443 -j ACCEPT -m comment --comment vpcctl:allow-443
sudo ip netns exec ns-myvpc-public iptables -C INPUT -p tcp --dport 22  -j DROP   2>/dev/null \
  || sudo ip netns exec ns-myvpc-public iptables -A INPUT -p tcp --dport 22  -j DROP   -m comment --comment vpcctl:deny-22
```

### list / inspect / delete

- list: shows all VPCs (based on metadata files)
- inspect: pretty-prints full metadata (subnets, apps, NAT, peers, policies)
- delete: stops apps, removes namespaces, veths, bridge, and rules; then deletes metadata

Under the hood

- list: enumerates JSON files in .vpcctl_data to discover VPCs
- inspect: reads and pretty-prints the VPC's metadata to reflect actual state
- delete: reverses creation steps in a safe order (stop apps → tear down rules → remove namespaces/veths → delete bridge → purge metadata)

Example commands

```bash
# list
ls -1 .vpcctl_data | sed -n 's/^vpc_\(.*\)\.json$/\1/p'

# inspect
jq . .vpcctl_data/vpc_myvpc.json

# delete (excerpt)
sudo ip netns del ns-myvpc-public || true
sudo ip netns del ns-myvpc-private || true
sudo ip link del br-myvpc || true
sudo iptables -F vpc-myvpc 2>/dev/null || true
sudo iptables -X vpc-myvpc 2>/dev/null || true
rm -f .vpcctl_data/vpc_myvpc.json
```

---

## Architecture Overview

Single VPC

![Single VPC Architecture](https://res.cloudinary.com/dvgk3fko3/image/upload/v1762848698/minimain_ulzxld.png)

VPC Peering (VPC ↔ VPC)

![VPC Peering Architecture](https://res.cloudinary.com/dvgk3fko3/image/upload/v1762848698/peer_hw5cge.png)

---

## Command Reference

| Command | Description | Example |
|---------|-------------|---------|
| create | Create a new VPC | `sudo vpcctl create myvpc --cidr 10.10.0.0/16` |
| add-subnet | Add a subnet to a VPC | `sudo vpcctl add-subnet myvpc public --cidr 10.10.1.0/24` |
| deploy-app | Start HTTP server in subnet | `sudo vpcctl deploy-app myvpc public --port 8080` |
| stop-app | Stop running application | `sudo vpcctl stop-app myvpc public` |
| enable-nat | Enable internet access via NAT | `sudo vpcctl enable-nat myvpc --interface eth0` |
| peer | Connect two VPCs | `sudo vpcctl peer myvpc othervpc --allow-cidrs 10.10.1.0/24,10.20.1.0/24` |
| apply-policy | Apply firewall rules (JSON) | `sudo vpcctl apply-policy myvpc policy.json` |
| list | List all VPCs | `sudo vpcctl list` |
| inspect | Show VPC metadata | `sudo vpcctl inspect myvpc` |
| delete | Delete a VPC | `sudo vpcctl delete myvpc` |
| cleanup-all | Delete all VPCs | `sudo vpcctl cleanup-all` |
| verify | Check for orphaned resources | `sudo vpcctl verify` |

---

## Troubleshooting Common Issues

### Issue 1: "Permission denied" or "Operation not permitted"

**Symptom:**
```
Error: Operation not permitted
```

**Cause:** Not running with root privileges.

**Solution:**
```bash
# Always use sudo
sudo vpcctl create myapp --cidr 10.10.0.0/16
```

---

### Issue 2: "Cannot find command: ip"

**Symptom:**
```
Error: Cannot find required command: ip
```

**Cause:** Missing iproute2 package.

**Solution:**
```bash
# Ubuntu/Debian
sudo apt install -y iproute2

# CentOS/RHEL
sudo yum install -y iproute
```

---

### Issue 3: "Bridge already exists"

**Symptom:**
```
Error: RTNETLINK answers: File exists
```

**Cause:** You already created a VPC with this name.

**Solutions:**

**Option A: Use a different name**
```bash
sudo vpcctl create myapp2 --cidr 10.10.0.0/16
```

**Option B: Delete the existing VPC first**
```bash
sudo vpcctl delete myapp
sudo vpcctl create myapp --cidr 10.10.0.0/16
```

---

### Issue 4: Namespace Cannot Access Internet

### Issue 4: Namespace Cannot Access Internet

**Symptom:**
```bash
sudo ip netns exec ns-myapp-web curl -I http://1.1.1.1 | head -5
# Hangs or fails
```

**Possible causes and solutions:**

**Cause 1: NAT not enabled**
```bash
sudo vpcctl enable-nat myapp --interface eth0
```

**Cause 2: Wrong host interface**
```bash
# Find correct interface
ip route | grep default

# Use the interface shown
sudo vpcctl enable-nat myapp --interface <correct-interface>
```

**Cause 3: Firewall blocking**
```bash
# Check iptables
sudo iptables -t nat -L -n -v

# Check for MASQUERADE rule
sudo iptables -t nat -L POSTROUTING -n -v | grep MASQUERADE
```

**Cause 4: DNS not configured in namespace**
```bash
# Copy resolv.conf into namespace
sudo mkdir -p /etc/netns/ns-myapp-web
sudo cp /etc/resolv.conf /etc/netns/ns-myapp-web/

# Test again
sudo ip netns exec ns-myapp-web curl -I http://1.1.1.1 | head -5
```

---

### Issue 5: Subnets Cannot Communicate
### Issue 5: Subnets Cannot Communicate

**Symptom:**
```bash
# From subnet A trying to reach subnet B
sudo ip netns exec ns-myapp-web curl http://10.10.2.2:5432
# Connection refused or timeout
```

**Debugging steps:**

**Step 1: Verify both subnets are in the same VPC**
```bash
sudo vpcctl inspect myapp
# Check that both subnets appear in the output
```

**Step 2: Check if application is running in target subnet**
```bash
sudo vpcctl inspect myapp | grep apps
# Or
sudo ip netns exec ns-myapp-database netstat -tlnp
```

**Step 3: Verify routing**
```bash
# Check routing table in source namespace
sudo ip netns exec ns-myapp-web ip route
```

**Step 4: Check firewall rules**
```bash
# Check iptables in target namespace
sudo ip netns exec ns-myapp-database iptables -L -n -v
```

**Step 5: Test basic connectivity (ping)**
```bash
sudo ip netns exec ns-myapp-web ping -c 3 10.10.2.2
```

---

### Issue 6: "Cannot delete VPC: bridge is busy"

**Symptom:**
```
Error: RTNETLINK answers: Device or resource busy
```

**Cause:** Something is still using the bridge (running app, existing veth).

**Solution:**
```bash
# Force stop all apps first
sudo vpcctl cleanup-all

# Or manually kill processes
sudo pkill -f "ip netns exec ns-myapp"

# Then try deleting again
sudo vpcctl delete myapp
```

---

### Issue 7: Peered VPCs Cannot Communicate

**Symptom:**
```bash
sudo vpcctl peer vpc1 vpc2 --allow-cidrs 10.10.1.0/24,10.20.1.0/24
# But curl between VPCs times out
```

**Debugging steps:**

**Step 1: Verify peering exists**
```bash
sudo vpcctl inspect vpc1 | grep peers
sudo vpcctl inspect vpc2 | grep peers
```

**Step 2: Check allowed CIDRs**
```bash
# Make sure the source and destination subnets are in the allowed list
sudo vpcctl inspect vpc1
```

**Step 3: Check iptables rules**
```bash
sudo iptables -L vpc-vpc1 -n -v
# Look for ACCEPT rules with peer CIDRs
```

**Step 4: Test with specific IPs**
```bash
# From vpc1 subnet to vpc2 subnet
sudo ip netns exec ns-vpc1-web curl http://10.20.1.2:8080
```

---

### Issue 8: High CPU Usage from Python HTTP Server

**Symptom:** System becomes slow after deploying multiple apps.

**Cause:** Python's simple HTTP server is not designed for high performance.

**Solution:**

**Option A: Limit number of test apps**
```bash
# Only deploy what you need
sudo vpcctl stop-app myapp web
```

**Option B: Use lighter alternatives**
Instead of using `deploy-app`, manually run a lighter server:
```bash
# Use busybox httpd (if available)
sudo ip netns exec ns-myapp-web busybox httpd -f -p 8080
```

---

### Issue 9: "Address already in use"

**Symptom:**
```
Error: bind: address already in use
```

**Cause:** Port is already taken by another application.

**Solution:**

**Option 1: Use a different port**
```bash
sudo vpcctl deploy-app myapp web --port 8081
```

**Option 2: Stop the conflicting app**
```bash
# Find what's using the port
sudo lsof -i :8080

# Stop it
sudo kill <PID>

# Or use vpcctl
sudo vpcctl stop-app myapp web
```

---

### Issue 10: Metadata File Corruption

**Symptom:**
```
Error: JSON decode error
```

**Cause:** Metadata file `.vpcctl_data/vpc_<name>.json` got corrupted.

**Solution:**

**Option 1: Delete and recreate**
```bash
# Remove corrupted metadata
rm .vpcctl_data/vpc_myapp.json

# Recreate VPC
sudo vpcctl create myapp --cidr 10.10.0.0/16
```

**Option 2: Manual cleanup**
```bash
# Remove namespace
sudo ip netns del ns-myapp-web

# Remove bridge
sudo ip link del br-myapp

# Remove metadata
rm .vpcctl_data/vpc_myapp.json
```

---

### Debugging Tips

**Enable verbose output:**
```bash
# Add debugging to see all iptables operations
sudo vpcctl create myapp --cidr 10.10.0.0/16 2>&1 | tee debug.log
```

**Check system logs:**
```bash
# View kernel network messages
dmesg | tail -50

# System logs
journalctl -xe
```

**Verify bridge state:**
```bash
# List all bridges
ip link show type bridge

# Show bridge details
bridge link show
```

**Verify namespace state:**
```bash
# List all namespaces
sudo ip netns list

# Show interfaces in a namespace
sudo ip netns exec ns-myapp-web ip addr
```

**Verify iptables rules:**
```bash
# NAT table
sudo iptables -t nat -L -n -v

# Filter table
sudo iptables -L -n -v

# Check specific chain
sudo iptables -L vpc-myapp -n -v
```

---

## Complete Code Reference

### Metadata File Structure

Every VPC has a JSON metadata file stored in `.vpcctl_data/vpc_<name>.json`:

```json
{
  "name": "myapp",
  "cidr": "10.10.0.0/16",
  "bridge": "br-myapp",
  "chain": "vpc-myapp",
  "subnets": [
    {
      "name": "web",
      "cidr": "10.10.1.0/24",
      "ns": "ns-myapp-web",
      "gw": "10.10.1.1",
      "host_ip": "10.10.1.2",
      "veth": "v-myapp-web"
    }
  ],
  "host_iptables": [
    ["iptables", "-A", "vpc-myapp", "-s", "10.10.0.0/16", "-d", "10.10.0.0/16", "-j", "ACCEPT"]
  ],
  "apps": [
    {
      "ns": "ns-myapp-web",
      "port": 8080,
      "pid": 12345,
      "cmd": ["ip", "netns", "exec", "ns-myapp-web", "python3", "-m", "http.server", "8080"]
    }
  ],
  "peers": [
    {
      "peer_vpc": "otherapp",
      "veth_a": "pv-myapp-other-va",
      "veth_b": "pv-myapp-other-vb",
      "allowed": ["10.10.1.0/24", "10.20.1.0/24"]
    }
  ],
  "nat": {
    "interface": "eth0"
  }
}
```

---

### Policy File Structure

Policy files define ingress and egress firewall rules:

```json
{
  "subnet": "10.10.1.0/24",
  "ingress": [
    {"port": 80, "protocol": "tcp", "action": "allow"},
    {"port": 443, "protocol": "tcp", "action": "allow"},
    {"port": 22, "protocol": "tcp", "action": "deny"},
    {"port": 3389, "protocol": "tcp", "action": "deny"}
  ],
  "egress": [
    {"port": 25, "protocol": "tcp", "action": "deny"},
    {"port": 80, "protocol": "tcp", "action": "allow"},
    {"port": 443, "protocol": "tcp", "action": "allow"}
  ]
}
```

**Fields:**
- `subnet`: CIDR of the subnet this policy applies to
- `ingress`: Rules for incoming traffic
- `egress`: Rules for outgoing traffic
- `port`: Port number
- `protocol`: `tcp`, `udp`, or `icmp`
- `action`: `allow` or `deny`

---

### Common IP Address Ranges (CIDR)

**Private IP ranges (safe to use):**
- `10.0.0.0/8`: 10.0.0.0 to 10.255.255.255 (16 million IPs)
- `172.16.0.0/12`: 172.16.0.0 to 172.31.255.255 (1 million IPs)
- `192.168.0.0/16`: 192.168.0.0 to 192.168.255.255 (65,534 IPs)

**CIDR notation explained:**
- `/8`: 16,777,216 addresses
- `/16`: 65,536 addresses
- `/24`: 256 addresses
- `/28`: 16 addresses
- `/32`: 1 address

**Examples:**
- `10.0.0.0/16` = 10.0.0.1 to 10.0.255.254
- `192.168.1.0/24` = 192.168.1.1 to 192.168.1.254
- `172.16.0.0/20` = 172.16.0.1 to 172.16.15.254

---

### Quick Command Cheat Sheet

```bash
# Create VPC
sudo vpcctl create <name> --cidr <ip-range>

# Add subnet
sudo vpcctl add-subnet <vpc> <subnet-name> --cidr <ip-range>

# Deploy test app
sudo vpcctl deploy-app <vpc> <subnet> --port <port>

# Enable internet
sudo vpcctl enable-nat <vpc> --interface <iface>

# Peer VPCs
sudo vpcctl peer <vpc1> <vpc2> --allow-cidrs <cidr1>,<cidr2>

# Apply policy
sudo vpcctl apply-policy <vpc> <policy-file.json>

# List VPCs
sudo vpcctl list

# Inspect VPC
sudo vpcctl inspect <vpc>

# Delete VPC
sudo vpcctl delete <vpc>

# Test connectivity
sudo ip netns exec ns-<vpc>-<subnet> curl http://<ip>:<port>

# Run command in namespace
sudo ip netns exec ns-<vpc>-<subnet> <command>

# Check namespace IPs
sudo ip netns exec ns-<vpc>-<subnet> ip addr

# Check namespace routing
sudo ip netns exec ns-<vpc>-<subnet> ip route

# Check namespace firewall
sudo ip netns exec ns-<vpc>-<subnet> iptables -L -n -v
```

---

## Best Practices

### 1. Plan Your IP Address Space

**Bad:**
```bash
# Random, overlapping ranges
sudo vpcctl create app1 --cidr 10.0.0.0/24
sudo vpcctl create app2 --cidr 10.0.0.0/24  # CONFLICT!
```

**Good:**
```bash
# Organized, non-overlapping ranges
sudo vpcctl create dev --cidr 10.10.0.0/16
sudo vpcctl create staging --cidr 10.20.0.0/16
sudo vpcctl create prod --cidr 10.30.0.0/16
```

### 2. Use Descriptive Names

**Bad:**
```bash
sudo vpcctl create vpc1 --cidr 10.0.0.0/16
sudo vpcctl add-subnet vpc1 sub1 --cidr 10.0.1.0/24
```

**Good:**
```bash
sudo vpcctl create ecommerce-app --cidr 10.0.0.0/16
sudo vpcctl add-subnet ecommerce-app web-tier --cidr 10.0.1.0/24
sudo vpcctl add-subnet ecommerce-app database --cidr 10.0.2.0/24
```

### 3. Document Your Network

Create a simple diagram:

```
VPC: ecommerce-app (10.0.0.0/16)
├── web-tier (10.0.1.0/24) - Public, NAT enabled
│   └── nginx on 10.0.1.2:80
├── app-tier (10.0.2.0/24) - Private
│   └── node.js on 10.0.2.2:3000
└── database (10.0.3.0/24) - Private
    └── postgres on 10.0.3.2:5432
```

### 4. Test Before Applying Policies

```bash
# First, get everything working without restrictions
sudo vpcctl create test --cidr 10.99.0.0/16
sudo vpcctl add-subnet test web --cidr 10.99.1.0/24
sudo vpcctl deploy-app test web --port 8080

# Test connectivity
sudo ip netns exec ns-test-web curl localhost:8080

# THEN apply policies
sudo vpcctl apply-policy test restrictive_policy.json
```

### 5. Clean Up After Testing

```bash
# Always cleanup when done
sudo vpcctl delete test-vpc

# Or nuke everything
sudo vpcctl cleanup-all
```

### 6. Use Dry-Run First

```bash
# Preview before executing
vpcctl --dry-run create prod --cidr 10.30.0.0/16
# Review the commands
# Then run for real:
sudo vpcctl create prod --cidr 10.30.0.0/16
```

---

## Learning Resources

### Understanding Linux Networking

**Concepts to research:**
- Network namespaces
- Virtual Ethernet (veth) pairs
- Linux bridges
- iptables and netfilter
- IP routing and forwarding
- NAT and MASQUERADE

---

## Conclusion

You now have a complete understanding of:
- What VPCs and subnets are
- Why we need network isolation
- How vpcctl works under the hood
- Every command and function in vpcctl
- How to build realistic network architectures
- How to troubleshoot common issues

**Next steps:**
1. Follow the "Your First VPC" tutorial
2. Build one of the advanced scenarios
3. Create your own custom network topology
4. Read the vpcctl source code to go deeper

**Remember:** vpcctl is a learning tool. It helps you understand cloud networking concepts without needing an AWS/Azure account. Once you master it, you'll find cloud provider VPCs much easier to work with!

---

**Author's Note:** This guide was written to be beginner-friendly. If you're reading this and something is unclear, that's a bug in the documentation, not in your understanding. Re-read the section, try the examples, and experiment!

---

## Credits

Author: DestinyObs  
Tagline: iBuild | iDeploy | iSecure | iSustain  
GitHub: https://github.com/DestinyObs/HNGi13-Stage4-vpcctl

---

**Happy networking!**