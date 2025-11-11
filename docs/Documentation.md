# vpcctl — Complete Technical Documentation

## Table of Contents
1. [Purpose](#purpose)
2. [Architecture Overview](#architecture-overview)
3. [Prerequisites](#prerequisites)
4. [Installation](#installation)
5. [Command Reference](#command-reference)
6. [Advanced Features](#advanced-features)
7. [Metadata and State Management](#metadata-and-state-management)
8. [Testing and Validation](#testing-and-validation)
9. [Troubleshooting](#troubleshooting)
10. [Best Practices](#best-practices)

---

## Purpose

`vpcctl` is a single-host Virtual Private Cloud (VPC) simulator that uses Linux network namespaces, veth pairs, bridges, and iptables to emulate cloud VPC environments locally. It's designed for:

- **Learning**: Understand cloud networking concepts hands-on
- **Testing**: Validate network configurations before deploying to cloud
- **Development**: Test multi-tier applications locally
- **Demonstrations**: Show VPC concepts without cloud costs

### Key Features

- **Complete VPC Isolation**: Each VPC runs in its own network environment
- **Subnet Management**: Create public and private subnets with different access levels
- **VPC Peering**: Connect VPCs with granular CIDR-based access control
- **NAT Gateway**: Enable internet access for public subnets
- **Security Policies**: JSON-based ingress/egress firewall rules
- **Idempotent Operations**: Safe to re-run commands; existing resources are skipped
- **Deterministic Cleanup**: All resources tracked in metadata for clean removal
- **Dry-Run Mode**: Preview commands before execution

---

### Linux Primitives Used

1. **Network Namespaces** (`ip netns`): Isolated network environments for each subnet
2. **Linux Bridges** (`br-*`): Virtual switches connecting subnets within a VPC
3. **veth Pairs**: Virtual ethernet cables connecting namespaces to bridges
4. **iptables**: Firewall rules for NAT, security policies, and VPC peering
5. **Python HTTP Server**: Test applications for connectivity validation

---

## Prerequisites

### System Requirements

- **Operating System**: Linux (Ubuntu 20.04+, Debian 11+, or compatible)
- **Python**: 3.8 or higher
- **Privileges**: Root/sudo access required
- **Kernel Modules**: `bridge`, `veth`, `xt_comment` (usually pre-loaded)

### Required Packages

```bash
sudo apt update
sudo apt install -y python3 iproute2 iptables curl
```

**Package explanations:**
- `python3`: Runtime for vpcctl and test HTTP servers
- `iproute2`: Provides `ip` command for network management
- `iptables`: Firewall and NAT rule management
- `curl`: Testing connectivity

---

## Installation

### Method 1: Clone Repository (Recommended)

```bash
# Clone the repository
git clone https://github.com/DestinyObs/HNGi13-Stage4-vpcctl.git
cd HNGi13-Stage4-vpcctl

# Make executable and install
sudo chmod +x vpcctl.py
sudo ln -sf "$(pwd)/vpcctl.py" /usr/local/bin/vpcctl

# Verify installation
vpcctl --help
```

### Method 2: Direct Download

```bash
# Download the script
curl -O https://raw.githubusercontent.com/DestinyObs/HNGi13-Stage4-vpcctl/main/vpcctl.py

# Make executable and install
chmod +x vpcctl.py
sudo ln -sf "$(pwd)/vpcctl.py" /usr/local/bin/vpcctl
```

### Fix Line Endings (if needed on Windows)

If you get `/usr/bin/env: 'python3\r': No such file or directory`:

```bash
sed -i 's/\r$//' vpcctl.py
```

### Verify Installation

```bash
# Check vpcctl is accessible
which vpcctl

# Test parser (safe, makes no changes)
sudo vpcctl flag-check
```

---

## Command Reference

### Global Options

```bash
vpcctl [--dry-run] <command> [options]
```

**Global Flags:**
- `--dry-run`: Preview commands without executing (no sudo required)

### Core Commands

#### 1. `create` — Create a VPC

**Syntax:**
```bash
sudo vpcctl create <vpc-name> --cidr <ip-range>
```

**Example:**
```bash
sudo vpcctl create myvpc --cidr 10.10.0.0/16
```

**What it does:**
- Creates a Linux bridge `br-<vpc>`
- Assigns gateway IP (first IP in CIDR)
- Creates iptables chain `vpc-<vpc>`
- Saves metadata to `.vpcctl_data/vpc_<name>.json`

**Positional form (legacy):**
```bash
sudo vpcctl create myvpc 10.10.0.0/16
```

---

#### 2. `add-subnet` — Add Subnet to VPC

**Syntax:**
```bash
sudo vpcctl add-subnet <vpc> <subnet-name> --cidr <ip-range> [--gw <gateway-ip>]
```

**Example:**
```bash
sudo vpcctl add-subnet myvpc public --cidr 10.10.1.0/24
sudo vpcctl add-subnet myvpc private --cidr 10.10.2.0/24 --gw 10.10.2.254
```

**What it does:**
- Creates network namespace `ns-<vpc>-<subnet>`
- Creates veth pair connecting namespace to VPC bridge
- Assigns IP addresses
- Sets up routing inside namespace
- Auto-generates and applies default security policy
- Saves subnet metadata

**Default Policy Applied:**
- **Ingress**: Allow TCP 80, 443; Deny TCP 22
- **Egress**: Allow all (no restrictions)

---

#### 3. `enable-nat` — Enable Internet Access

**Syntax:**
```bash
sudo vpcctl enable-nat <vpc> --interface <host-interface> [--subnet <subnet-name>] [--all-subnets]
```

**Examples:**
```bash
# NAT for all public subnets (default behavior)
sudo vpcctl enable-nat myvpc --interface eth0

# NAT for specific subnet only
sudo vpcctl enable-nat myvpc --interface eth0 --subnet public

# NAT for ALL subnets (including private)
sudo vpcctl enable-nat myvpc --interface eth0 --all-subnets
```

**What it does:**
- Adds iptables MASQUERADE rule for specified subnets
- Enables IP forwarding (`net.ipv4.ip_forward=1`)
- Records NAT configuration in metadata

**Find your interface:**
```bash
ip route | grep default
# Look for "dev <interface-name>"
```

---

#### 4. `peer` — Connect Two VPCs

**Syntax:**
```bash
sudo vpcctl peer <vpc1> <vpc2> [--allow-cidrs <cidr1>,<cidr2>,...]
```

**Examples:**
```bash
# Peer with default (allow all VPC CIDRs)
sudo vpcctl peer vpc1 vpc2

# Peer with specific subnet restrictions
sudo vpcctl peer vpc1 vpc2 --allow-cidrs 10.10.1.0/24,10.20.1.0/24
```

**What it does:**
- Creates bidirectional iptables FORWARD rules
- Adds routes between VPC bridges
- Restricts traffic to specified CIDRs (if provided)
- Records peering in both VPC metadata files

**Idempotency:** Re-running with same parameters skips existing rules

---

#### 5. `apply-policy` — Apply Security Policy

**Syntax:**
```bash
sudo vpcctl apply-policy <vpc> <policy-file.json>
```

**Example:**
```bash
sudo vpcctl apply-policy myvpc policy_examples/example_ingress_egress_policy.json
```

**Policy File Format:**
```json
{
  "subnet": "10.10.1.0/24",
  "ingress": [
    {"port": 80, "protocol": "tcp", "action": "allow"},
    {"port": 443, "protocol": "tcp", "action": "allow"},
    {"port": 22, "protocol": "tcp", "action": "deny"}
  ],
  "egress": [
    {"port": 443, "protocol": "tcp", "action": "allow"},
    {"port": 25, "protocol": "tcp", "action": "deny"}
  ]
}
```

**What it does:**
- Finds matching subnet by CIDR
- Applies iptables rules inside the subnet's namespace
- Ingress rules → INPUT chain
- Egress rules → OUTPUT chain
- Merges with existing auto-generated policies

**Example policy file location:**
- `policy_examples/example_ingress_egress_policy.json`

---

#### 6. `deploy-app` — Deploy Test Application

**Syntax:**
```bash
sudo vpcctl deploy-app <vpc> <subnet> --port <port>
```

**Example:**
```bash
sudo vpcctl deploy-app myvpc public --port 8080
```

**What it does:**
- Starts Python HTTP server inside subnet namespace
- Runs with `nohup` in background
- Records PID in metadata
- Logs to `/tmp/vpcctl-<namespace>-http.log`

**Access the app:**
```bash
# Get subnet IP (usually .2)
sudo vpcctl inspect myvpc

# Test from another namespace
sudo ip netns exec ns-myvpc-private curl http://10.10.1.2:8080
```

---

#### 7. `test-connectivity` — Test Network Connectivity

**Syntax:**
```bash
sudo vpcctl test-connectivity <target-ip> <port> --from-ns <namespace>
```

**Example:**
```bash
sudo vpcctl test-connectivity 10.10.1.2 8080 --from-ns ns-myvpc-private
```

**What it does:**
- Runs `curl` from specified namespace to target
- Tests if firewall rules allow traffic
- Useful for validating policies and peering

---

#### 8. `list` — List All VPCs

**Syntax:**
```bash
sudo vpcctl list
```

**Output:**
```
VPCs:
- myvpc
- production
- testing
```

---

#### 9. `inspect` — Show VPC Details

**Syntax:**
```bash
sudo vpcctl inspect <vpc-name>
```

**Example:**
```bash
sudo vpcctl inspect myvpc
```

**Output:** Full JSON metadata including:
- CIDR range
- Bridge name
- All subnets with IPs
- Running applications
- Active peering connections
- NAT configuration
- Applied policies

---

#### 10. `stop-app` — Stop Application

**Syntax:**
```bash
sudo vpcctl stop-app <vpc> [--ns <namespace>] [--pid <process-id>]
```

**Examples:**
```bash
# Stop all apps in a VPC
sudo vpcctl stop-app myvpc

# Stop app in specific namespace
sudo vpcctl stop-app myvpc --ns ns-myvpc-public

# Stop specific PID
sudo vpcctl stop-app myvpc --pid 12345
```

---

#### 11. `delete` — Delete VPC

**Syntax:**
```bash
sudo vpcctl delete <vpc-name>
```

**Example:**
```bash
sudo vpcctl delete myvpc
```

**What it does:**
- Stops all running applications
- Deletes all subnet namespaces
- Removes veth pairs
- Deletes bridge
- Removes iptables rules (uses recorded commands)
- Deletes metadata file

---

#### 12. `cleanup-all` — Delete Everything

**Syntax:**
```bash
sudo vpcctl cleanup-all
```

**What it does:**
- Deletes ALL VPCs
- Useful for complete reset

---

#### 13. `verify` — Check for Orphans

**Syntax:**
```bash
sudo vpcctl verify
```

**What it does:**
- Lists all namespaces on system
- Compares with vpcctl metadata
- Reports orphaned resources

---

#### 14. `flag-check` — Parser Validation

**Syntax:**
```bash
sudo vpcctl flag-check
```

**What it does:**
- Validates argument parser
- Safe test (makes no system changes)
- Useful for CI/CD validation

---

## Advanced Features

### Automatic Policy Generation

When you create a subnet, `vpcctl` automatically generates and applies a default security policy:

**Default Policy:**
```json
{
  "subnet": "10.10.1.0/24",
  "ingress": [
    {"port": 80, "protocol": "tcp", "action": "allow"},
    {"port": 443, "protocol": "tcp", "action": "allow"},
    {"port": 22, "protocol": "tcp", "action": "deny"}
  ],
  "egress": []
}
```

**Policy files saved to:**
```
.vpcctl_data/policy_<vpc>_<subnet>_<cidr>.json
```

**View auto-generated policy:**
```bash
ls -l .vpcctl_data/policy_*
cat .vpcctl_data/policy_myvpc_public_10.10.1.0_24.json
```

### Idempotent Operations

`vpcctl` is designed to be idempotent — safe to re-run:

**iptables Rules:**
- Checks if rule exists before adding (using `-C` flag)
- Injects comment markers for reliable deletion
- Records exact commands in metadata

**Resources:**
- Bridges: Checks if bridge exists before creating
- Namespaces: Checks if namespace exists
- Peering: Skips duplicate peering connections

### Metadata-Driven Cleanup

All operations are recorded in JSON files under `.vpcctl_data/`:

```bash
.vpcctl_data/
├── vpc_myvpc.json          # VPC metadata
├── vpc_production.json
└── policy_myvpc_public_10.10.1.0_24.json
```

**Metadata includes:**
- Bridge and namespace names
- Exact iptables commands run
- Application PIDs
- Peering relationships
- NAT configuration

This ensures `delete` can cleanly remove everything.

---

## Metadata and State Management

### Metadata Files

Location: `.vpcctl_data/vpc_<name>.json`

**Structure:**
```json
{
  "name": "myvpc",
  "cidr": "10.10.0.0/16",
  "bridge": "br-myvpc",
  "chain": "vpc-myvpc",
  "subnets": [
    {
      "name": "public",
      "cidr": "10.10.1.0/24",
      "ns": "ns-myvpc-public",
      "gw": "10.10.1.1",
      "host_ip": "10.10.1.2",
      "veth": {"host": "v-myvpc-pub-b", "ns": "v-myvpc-pub-a"}
    }
  ],
  "host_iptables": [
    ["iptables", "-A", "FORWARD", "-m", "comment", "--comment", "vpcctl:myvpc", ...]
  ],
  "apps": [
    {
      "ns": "ns-myvpc-public",
      "port": 8080,
      "pid": 12345,
      "cmd": "python3 -m http.server 8080"
    }
  ],
  "peers": [
    {
      "peer_vpc": "othervpc",
      "allow_cidrs": ["10.10.1.0/24", "10.20.1.0/24"]
    }
  ],
  "nat": {
    "interface": "eth0",
    "subnets": ["public"]
  }
}
```

---

## Testing and Validation

### Acceptance Test Script

Location: `scripts/acceptance_test.sh`

Comprehensive test covering:
- VPC creation and isolation
- Subnet connectivity
- NAT gateway functionality
- VPC peering
- Security policies
- Cleanup verification

**Run dry-run (safe):**
```bash
sudo ./scripts/acceptance_test.sh
```

**Run full test:**
```bash
sudo ./scripts/acceptance_test.sh --apply --iface eth0
```

**Keep resources for debugging:**
```bash
sudo ./scripts/acceptance_test.sh --apply --iface eth0 --keep
```

**Test outputs saved to:**
```
docs/samples/actual-<timestamp>/
├── vpcctl_help.txt
├── flag_check.txt
├── namespaces_after_t1_create.txt
├── iptables_filter_all.txt
├── curl_private_to_public.html
└── SUMMARY.txt
```

### Manual Testing

**Test intra-VPC connectivity:**
```bash
# Create VPC and subnets
sudo vpcctl create test --cidr 10.30.0.0/16
sudo vpcctl add-subnet test public --cidr 10.30.1.0/24
sudo vpcctl add-subnet test private --cidr 10.30.2.0/24

# Deploy apps
sudo vpcctl deploy-app test public --port 8080
sudo vpcctl deploy-app test private --port 8081

# Test private → public
sudo ip netns exec ns-test-private curl http://10.30.1.2:8080
```

**Test VPC isolation:**
```bash
# Create second VPC
sudo vpcctl create test2 --cidr 10.40.0.0/16
sudo vpcctl add-subnet test2 web --cidr 10.40.1.0/24
sudo vpcctl deploy-app test2 web --port 8080

# Try to reach test2 from test (should fail)
sudo ip netns exec ns-test-public curl --max-time 5 http://10.40.1.2:8080
# Expected: timeout

# Enable peering
sudo vpcctl peer test test2

# Try again (should succeed)
sudo ip netns exec ns-test-public curl http://10.40.1.2:8080
```

---

## Troubleshooting

### Common Issues

#### 1. Line Ending Error

**Error:**
```
/usr/bin/env: 'python3\r': No such file or directory
```

**Fix:**
```bash
sed -i 's/\r$//' vpcctl.py
```

**Cause:** Windows CRLF line endings; Linux needs LF only

---

#### 2. Permission Denied

**Error:**
```
[Errno 1] Operation not permitted
```

**Fix:**
```bash
# Use sudo for all operations
sudo vpcctl create myvpc --cidr 10.10.0.0/16
```

---

#### 3. Bridge Already Exists

**Error:**
```
RTNETLINK answers: File exists
```

**Fix:**
```bash
# Delete existing VPC first
sudo vpcctl delete myvpc

# Or manually remove bridge
sudo ip link delete br-myvpc
```

---

#### 4. NAT Not Working

**Symptoms:** Subnet can't reach internet

**Debug:**
```bash
# Check IP forwarding
sysctl net.ipv4.ip_forward
# Should be 1

# Enable if needed
sudo sysctl -w net.ipv4.ip_forward=1

# Check NAT rules
sudo iptables -t nat -L -n -v | grep MASQUERADE

# Test from namespace
sudo ip netns exec ns-myvpc-public ping -c 2 8.8.8.8
```

---

#### 5. Orphaned Resources

**Check for orphans:**
```bash
sudo vpcctl verify
```

**Manual cleanup:**
```bash
# List all namespaces
sudo ip netns list

# Delete specific namespace
sudo ip netns delete ns-myvpc-public

# List bridges
ip link show type bridge

# Delete bridge
sudo ip link delete br-myvpc
```

---

#### 6. Interface Name Too Long

**Error:** Truncated interface names

**Cause:** Linux interface names limited to 15 characters

**Fix:** Use shorter VPC/subnet names
```bash
# Bad: Will be truncated
sudo vpcctl create my-very-long-vpc-name --cidr 10.10.0.0/16

# Good
sudo vpcctl create myvpc --cidr 10.10.0.0/16
```

---

## Best Practices

### 1. Use Dry-Run for Testing

```bash
# Preview commands before running
vpcctl --dry-run create prod --cidr 10.20.0.0/16
```

### 2. Consistent Naming

```bash
# Environment prefixes
sudo vpcctl create dev-app --cidr 10.10.0.0/16
sudo vpcctl create staging-app --cidr 10.20.0.0/16
sudo vpcctl create prod-app --cidr 10.30.0.0/16
```

### 3. Document CIDR Ranges

```bash
# Dev: 10.10.x.x
# Staging: 10.20.x.x  
# Production: 10.30.x.x
```

### 4. Test in Disposable VMs

- Run `vpcctl` in test VMs, not production hosts
- Use snapshots before testing
- `vpcctl` modifies host networking globally

### 5. Regular Cleanup

```bash
# After testing
sudo vpcctl delete test-vpc

# Complete cleanup
sudo vpcctl cleanup-all
sudo vpcctl verify
```

### 6. Version Control Policy Files

```bash
# Save custom policies
mkdir -p policies
sudo vpcctl apply-policy myvpc policies/production-web-policy.json
git add policies/
```

### 7. Monitor Metadata

```bash
# Check metadata regularly
ls -lh .vpcctl_data/
cat .vpcctl_data/vpc_myvpc.json | jq .
```

---

## Repository Structure

```
HNGi13-Stage4-vpcctl/
├── vpcctl.py                    # Main CLI tool
├── README.md                    # Quick start guide
├── .vpcctl_data/                # Runtime metadata (auto-created)
│   ├── vpc_myvpc.json
│   └── policy_*.json
├── docs/
│   ├── Documentation.md         # This file - complete reference
│   ├
│   └── samples/                 # Test evidence
│       └── actual-<timestamp>/  # Acceptance test outputs
├── policy_examples/
│   └── example_ingress_egress_policy.json
└── scripts/
    └── acceptance_test.sh       # Automated test suite
```

---

## Quick Reference

### Common Workflows

**Setup development environment:**
```bash
sudo vpcctl create dev --cidr 10.10.0.0/16
sudo vpcctl add-subnet dev web --cidr 10.10.1.0/24
sudo vpcctl add-subnet dev db --cidr 10.10.2.0/24
sudo vpcctl enable-nat dev --interface eth0 --subnet web
sudo vpcctl deploy-app dev web --port 80
sudo vpcctl deploy-app dev db --port 5432
```

**Multi-VPC setup with peering:**
```bash
sudo vpcctl create frontend --cidr 10.10.0.0/16
sudo vpcctl create backend --cidr 10.20.0.0/16
sudo vpcctl add-subnet frontend web --cidr 10.10.1.0/24
sudo vpcctl add-subnet backend api --cidr 10.20.1.0/24
sudo vpcctl peer frontend backend --allow-cidrs 10.10.1.0/24,10.20.1.0/24
```

**Apply security hardening:**
```bash
# Create restrictive policy
cat > secure-policy.json <<EOF
{
  "subnet": "10.10.1.0/24",
  "ingress": [
    {"port": 443, "protocol": "tcp", "action": "allow"},
    {"port": 22, "protocol": "tcp", "action": "deny"}
  ],
  "egress": [
    {"port": 443, "protocol": "tcp", "action": "allow"},
    {"port": 80, "protocol": "tcp", "action": "allow"}
  ]
}
EOF

sudo vpcctl apply-policy myvpc secure-policy.json
```

---

## Additional Resources

- **Beginner Guide**: See `docs/beginner.md` for step-by-step tutorials with analogies
- **Example Policies**: Check `policy_examples/` for security policy templates  
- **Test Evidence**: Browse `docs/samples/` for acceptance test outputs
- **Source Code**: Read `vpcctl.py` top-of-file docstring for architecture details

---

**Last Updated:** November 2025  
**Version:** 1.0  
**License:** MIT

**Last Updated:** November 2025  
**Version:** 1.0  
**License:** MIT
