# vpcctl — Single-Host VPC Simulator

A lightweight Python CLI tool that emulates Virtual Private Clouds (VPCs) on a single Linux host using network namespaces, veth pairs, bridges, and iptables. Designed for learning cloud networking concepts, local testing, and demonstration purposes.

## Features

- **Isolated VPCs** — Create multiple VPCs with separate network bridges and metadata
- **Subnet Management** — Add public/private subnets as network namespaces
- **VPC Peering** — Connect VPCs with controlled inter-VPC routing
- **NAT Gateway** — Enable internet access for public subnets via MASQUERADE
- **Security Policies** — Apply ingress/egress firewall rules (JSON-based)
- **App Deployment** — Launch test HTTP servers inside subnets
- **Idempotent Operations** — Safe to re-run commands; skips existing resources
- **Deterministic Cleanup** — Metadata-driven deletion of all created resources

## Prerequisites

**Host Requirements:**
- Linux (Ubuntu 20.04+ / Debian 11+ recommended)
- Root/sudo access
- Python 3.8+

**System Packages:**
```bash
sudo apt update
sudo apt install -y python3 iproute2 iptables curl
```

## Quick Start (For Graders & Reviewers)

**Run the complete test suite in one command:**

```bash
git clone https://github.com/DestinyObs/HNGi13-Stage4-vpcctl.git
cd HNGi13-Stage4-vpcctl
sudo make all
```

This will:
1. ✓ Install vpcctl CLI
2. ✓ Run comprehensive tests (VPC creation, routing, NAT, isolation, peering, policies)
3. ✓ Clean up all resources automatically
4. ✓ Verify no orphaned namespaces/bridges remain

**Expected runtime:** ~5 minutes  
**All tests must pass** for a valid submission.

---

## Installation

### Method 1: Using Makefile (Recommended)

```bash
# Clone the repo
git clone https://github.com/DestinyObs/HNGi13-Stage4-vpcctl.git
cd HNGi13-Stage4-vpcctl

# Install
sudo make install

# Run quick validation (2 mins)
sudo make test-quick

# Or run full test suite (5 mins)
sudo make test-full

# Cleanup when done
sudo make cleanup
```

**Available Makefile targets:**
- `make help` — Show all available commands
- `make install` — Install vpcctl CLI
- `make test-quick` — Quick validation test (~2 mins)
- `make test-full` — Comprehensive test suite (~5 mins)
- `make demo` — Interactive demo walkthrough
- `make cleanup` — Remove all VPCs
- `make verify` — Check for orphaned resources
- `make uninstall` — Complete removal
- `make all` — Install + test + cleanup (grader-friendly)

### Method 2: Manual Installation

```bash
# Clone the repo
git clone https://github.com/DestinyObs/HNGi13-Stage4-vpcctl.git
cd HNGi13-Stage4-vpcctl

# Install vpcctl command
sudo chmod +x vpcctl.py
sudo ln -sf "$(pwd)/vpcctl.py" /usr/local/bin/vpcctl

# Verify installation
sudo vpcctl flag-check
```

> **Note:** If you encounter `/usr/bin/env: 'python3\r': No such file or directory`, fix line endings:
> ```bash
> sed -i 's/\r$//' vpcctl.py
> ```

### Create Your First VPC

```bash
# 1. Create a VPC with CIDR 10.10.0.0/16
sudo vpcctl create myvpc --cidr 10.10.0.0/16

# 2. Add a public subnet
sudo vpcctl add-subnet myvpc public --cidr 10.10.1.0/24

# 3. Add a private subnet
sudo vpcctl add-subnet myvpc private --cidr 10.10.2.0/24

# 4. Enable NAT for internet access (public subnets only by default)
sudo vpcctl enable-nat myvpc --interface eth0

# 5. Deploy a test web server in the public subnet
sudo vpcctl deploy-app myvpc public --port 8080

# 6. Test connectivity from private to public subnet
sudo vpcctl test-connectivity 10.10.1.1 8080 --from-ns ns-myvpc-private
```

### View and Clean Up

```bash
# List all VPCs
sudo vpcctl list

# Inspect VPC details (JSON metadata)
sudo vpcctl inspect myvpc

# Delete a specific VPC
sudo vpcctl delete myvpc

# Clean up all VPCs
sudo vpcctl cleanup-all
```

## Core Commands

| Command | Description | Example |
|---------|-------------|---------|
| `create` | Create a new VPC | `sudo vpcctl create vpc1 --cidr 10.10.0.0/16` |
| `add-subnet` | Add a subnet to a VPC | `sudo vpcctl add-subnet vpc1 public --cidr 10.10.1.0/24` |
| `enable-nat` | Enable internet access via NAT | `sudo vpcctl enable-nat vpc1 --interface eth0` |
| `peer` | Connect two VPCs | `sudo vpcctl peer vpc1 vpc2` |
| `apply-policy` | Apply firewall rules (JSON) | `sudo vpcctl apply-policy vpc1 policy.json` |
| `deploy-app` | Start HTTP server in subnet | `sudo vpcctl deploy-app vpc1 public --port 8080` |
| `list` | List all VPCs | `sudo vpcctl list` |
| `inspect` | Show VPC metadata | `sudo vpcctl inspect vpc1` |
| `delete` | Delete a VPC | `sudo vpcctl delete vpc1` |
| `verify` | Check for orphaned resources | `sudo vpcctl verify` |

### Advanced Options

**Dry-run mode** (preview commands without executing):
```bash
vpcctl --dry-run create test --cidr 10.99.0.0/16
```

**NAT targeting**:
```bash
# NAT only a specific subnet
sudo vpcctl enable-nat myvpc --interface eth0 --subnet private

# NAT all subnets
sudo vpcctl enable-nat myvpc --interface eth0 --all-subnets
```

**VPC Peering with CIDR restrictions**:
```bash
sudo vpcctl peer vpc1 vpc2 --allow-cidrs 10.10.1.0/24,10.20.1.0/24
```

## Project Structure

```
HNGi13-Stage4-vpcctl/
├── vpcctl.py                    # Main CLI tool (see Usage above)
├── README.md                    # This file
├── .vpcctl_data/                # Runtime metadata (auto-generated JSON files)
├── docs/
│   ├── Documentation.md         # Full command reference, flags, troubleshooting
│   ├── beginner.md              # Comprehensive guide for new users
│   └── samples/                 # Test outputs for validation and grading
│       └── actual-<timestamp>/  # Evidence bundles from acceptance tests
├── policy_examples/
│   └── example_ingress_egress_policy.json  # Sample security policy
└── scripts/
    └── acceptance_test.sh       # Automated test suite
```

### Key Files and Directories

- **[vpcctl.py](vpcctl.py)** — Main Python CLI implementation with all VPC operations
- **[docs/Documentation.md](docs/Documentation.md)** — Complete command reference, behavioral details, and troubleshooting guide
- **[docs/samples/](docs/samples/)** — Contains timestamped evidence directories from acceptance test runs (iptables dumps, namespace listings, curl outputs, policy files) for grading and verification purposes
- **[policy_examples/](policy_examples/)** — Example JSON policy files showing ingress/egress rule format
- **[scripts/acceptance_test.sh](scripts/acceptance_test.sh)** — Comprehensive automated test script that validates all requirements
- **[.vpcctl_data/](.vpcctl_data/)** — Runtime metadata directory (auto-created) storing JSON files for each VPC's state

## Documentation

For detailed information, see:
- **[Full Documentation](docs/Documentation.md)** — Complete command reference, flags, idempotency behavior, troubleshooting
- **[Test Evidence](docs/samples/)** — Sample outputs from acceptance tests for validation

## Security Policies

`vpcctl` auto-generates default policies when creating subnets:
-  Allow TCP 80, 443 (HTTP/HTTPS)
-  Deny TCP 22 (SSH)

Custom policies (JSON format):
```json
{
  "subnet": "10.10.1.0/24",
  "ingress": [
    {"port": 80, "protocol": "tcp", "action": "allow"},
    {"port": 22, "protocol": "tcp", "action": "deny"}
  ],
  "egress": [
    {"port": 443, "protocol": "tcp", "action": "allow"}
  ]
}
```

Apply with:
```bash
sudo vpcctl apply-policy myvpc policy_examples/example_ingress_egress_policy.json
```

See [policy_examples/example_ingress_egress_policy.json](policy_examples/example_ingress_egress_policy.json) for the complete policy format.

## Testing

Run the comprehensive acceptance test suite:

```bash
# Dry-run (shows commands without executing)
sudo ./scripts/acceptance_test.sh

# Full test (creates VPCs, tests NAT, peering, policies)
sudo ./scripts/acceptance_test.sh --apply --iface eth0

# Keep VPCs after test for inspection
sudo ./scripts/acceptance_test.sh --apply --iface eth0 --keep
```

Test outputs are saved to `docs/samples/actual-<timestamp>/` for verification.

## Common Workflows

### Scenario 1: Public + Private Subnet with NAT
```bash
sudo vpcctl create prod --cidr 10.20.0.0/16
sudo vpcctl add-subnet prod public --cidr 10.20.1.0/24
sudo vpcctl add-subnet prod private --cidr 10.20.2.0/24
sudo vpcctl enable-nat prod --interface eth0
sudo vpcctl deploy-app prod public --port 80
```

### Scenario 2: VPC Peering
```bash
sudo vpcctl create vpc-a --cidr 10.10.0.0/16
sudo vpcctl create vpc-b --cidr 10.20.0.0/16
sudo vpcctl add-subnet vpc-a web --cidr 10.10.1.0/24
sudo vpcctl add-subnet vpc-b db --cidr 10.20.1.0/24
sudo vpcctl peer vpc-a vpc-b
```

### Scenario 3: Custom Security Policy
```bash
sudo vpcctl create secure --cidr 10.30.0.0/16
sudo vpcctl add-subnet secure dmz --cidr 10.30.1.0/24
sudo vpcctl apply-policy secure policy_examples/example_ingress_egress_policy.json
```

## Troubleshooting

**Error: `/usr/bin/env: 'python3\r': No such file or directory`**
```bash
sed -i 's/\r$//' vpcctl.py
```

**Error: `must be run as root`**
```bash
# Use sudo for all operations
sudo vpcctl create myvpc --cidr 10.10.0.0/16
```

**Orphaned namespaces after crashes:**
```bash
sudo vpcctl verify           # List orphans
sudo vpcctl cleanup-all      # Clean everything
```

**NAT not working:**
```bash
# Ensure ip_forward is enabled
sudo sysctl -w net.ipv4.ip_forward=1

# Check iptables NAT rules
sudo iptables -t nat -L -n -v
```

For more troubleshooting, see [docs/Documentation.md](docs/Documentation.md).

## License

This project is open source and available under the MIT License.

## Acknowledgments

Built for HNG Internship Stage 4 DevOps task. Demonstrates cloud networking concepts using Linux primitives.

---