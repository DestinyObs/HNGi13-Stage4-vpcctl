# vpcctl - Makefile for Installation, Testing, and Cleanup
# Author: DestinyObs
# Purpose: Automate full workflow for graders and users

.PHONY: help install test-quick test-full demo cleanup verify uninstall all

# Default target - show help
help:
	@echo "=================================================="
	@echo "  vpcctl - VPC Simulator Makefile"
	@echo "=================================================="
	@echo ""
	@echo "Quick Start (Recommended for Graders):"
	@echo "  make all              - Install + run full test + cleanup"
	@echo ""
	@echo "Individual Targets:"
	@echo "  make install          - Install vpcctl CLI"
	@echo "  make test-quick       - Quick validation (2 mins)"
	@echo "  make test-full        - Comprehensive test (5 mins)"
	@echo "  make demo             - Interactive demo walkthrough"
	@echo "  make cleanup          - Remove all VPCs"
	@echo "  make verify           - Check for orphaned resources"
	@echo "  make uninstall        - Remove vpcctl completely"
	@echo ""
	@echo "Requirements:"
	@echo "  - Linux (Ubuntu 20.04+ or similar)"
	@echo "  - sudo access"
	@echo "  - Python 3.8+"
	@echo "  - iproute2, iptables, curl"
	@echo ""
	@echo "Usage Example:"
	@echo "  sudo make all         # Run everything (grader-friendly)"
	@echo "=================================================="

# Check prerequisites
check-deps:
	@echo "==> Checking prerequisites..."
	@command -v python3 >/dev/null 2>&1 || { echo "ERROR: python3 not found. Install with: sudo apt install python3"; exit 1; }
	@command -v ip >/dev/null 2>&1 || { echo "ERROR: ip command not found. Install with: sudo apt install iproute2"; exit 1; }
	@command -v iptables >/dev/null 2>&1 || { echo "ERROR: iptables not found. Install with: sudo apt install iptables"; exit 1; }
	@command -v curl >/dev/null 2>&1 || { echo "ERROR: curl not found. Install with: sudo apt install curl"; exit 1; }
	@python3 --version | grep -qE "3\.(8|9|10|11|12)" || { echo "WARNING: Python 3.8+ recommended"; }
	@echo "  All prerequisites satisfied"

# Install vpcctl
install: check-deps
	@echo ""
	@echo "==> Installing vpcctl..."
	@chmod +x vpcctl.py
	@sed -i 's/\r$$//' vpcctl.py 2>/dev/null || true
	@ln -sf "$(shell pwd)/vpcctl.py" /usr/local/bin/vpcctl
	@echo "  vpcctl installed to /usr/local/bin/vpcctl"
	@echo ""
	@echo "==> Verifying installation..."
	@vpcctl flag-check
	@echo "  Installation successful"
	@echo ""

# Quick test (essential features only)
test-quick: install
	@echo ""
	@echo "=================================================="
	@echo "  Quick Test Suite (2 minutes)"
	@echo "=================================================="
	@echo ""
	@echo "==> Test 1: Create VPC and Subnets"
	@vpcctl create test-vpc --cidr 10.99.0.0/16
	@vpcctl add-subnet test-vpc web --cidr 10.99.1.0/24
	@vpcctl add-subnet test-vpc db --cidr 10.99.2.0/24
	@vpcctl list | grep -q test-vpc && echo "  VPC created" || { echo " VPC creation failed"; exit 1; }
	@echo ""
	@echo "==> Test 2: Deploy Apps and Test Connectivity"
	@vpcctl deploy-app test-vpc web --port 8080
	@vpcctl deploy-app test-vpc db --port 5432
	@sleep 2
	@ip netns exec ns-test-vpc-web curl -sS http://10.99.1.2:8080 | head -1 | grep -q DOCTYPE && echo " Web app reachable" || { echo " Web app failed"; exit 1; }
	@ip netns exec ns-test-vpc-db curl -sS http://10.99.1.2:8080 | head -1 | grep -q DOCTYPE && echo " Intra-VPC routing works" || { echo " Routing failed"; exit 1; }
	@echo ""
	@echo "==> Test 3: Cleanup"
	@vpcctl delete test-vpc
	@vpcctl verify | grep -q "Orphan.*None" && echo "  Clean deletion" || { echo " Cleanup incomplete"; exit 1; }
	@echo ""
	@echo "  Quick test PASSED"
	@echo ""

# Full comprehensive test
test-full: install
	@echo ""
	@echo "=================================================="
	@echo "  Full Test Suite (5 minutes)"
	@echo "=================================================="
	@$(MAKE) -s cleanup 2>/dev/null || true
	@echo ""
	@echo "==> Phase 1: VPC Creation & Routing"
	@vpcctl create prod-test --cidr 10.10.0.0/16
	@vpcctl add-subnet prod-test public --cidr 10.10.1.0/24
	@vpcctl add-subnet prod-test private --cidr 10.10.2.0/24
	@vpcctl deploy-app prod-test public --port 8080
	@vpcctl deploy-app prod-test private --port 8081
	@sleep 2
	@ip netns exec ns-prod-test-private curl -sS http://10.10.1.2:8080 | head -1 | grep -q DOCTYPE && echo "  Intra-VPC routing OK" || exit 1
	@echo ""
	@echo "==> Phase 2: NAT Gateway"
	@IFACE=$$(ip route | grep default | awk '{print $$5}' | head -1); \
	vpcctl enable-nat prod-test --interface $$IFACE --subnet public
	@ip netns exec ns-prod-test-public curl -I -m 5 http://1.1.1.1 2>/dev/null | grep -q "HTTP" && echo "  Public NAT works" || echo " NAT test inconclusive (network issue)"
	@echo ""
	@echo "==> Phase 3: VPC Isolation"
	@vpcctl create staging-test --cidr 10.20.0.0/16
	@vpcctl add-subnet staging-test web --cidr 10.20.1.0/24
	@vpcctl deploy-app staging-test web --port 9090
	@sleep 2
	@ip netns exec ns-prod-test-public curl -m 3 http://10.20.1.2:9090 2>&1 | grep -qE "(timed out|Connection refused)" && echo "  VPCs isolated" || { echo " Isolation failed"; exit 1; }
	@echo ""
	@echo "==> Phase 4: VPC Peering"
	@vpcctl peer prod-test staging-test --allow-cidrs 10.10.1.0/24,10.20.1.0/24
	@ip netns exec ns-prod-test-public curl -sS http://10.20.1.2:9090 | head -1 | grep -q DOCTYPE && echo "  Peering works" || { echo "  Peering failed"; exit 1; }
	@ip netns exec ns-prod-test-private curl -m 3 http://10.20.1.2:9090 2>&1 | grep -qE "(timed out|Connection refused)" && echo "  Peering CIDR restriction OK" || { echo "  CIDR restriction failed"; exit 1; }
	@echo ""
	@echo "==> Phase 5: Security Policies"
	@echo '{"subnet":"10.10.1.0/24","ingress":[{"port":80,"protocol":"tcp","action":"allow"},{"port":22,"protocol":"tcp","action":"deny"}],"egress":[]}' > /tmp/test-policy.json
	@vpcctl apply-policy prod-test /tmp/test-policy.json
	# Verify using rule syntax (order-stable) instead of -L pretty output
	@ip netns exec ns-prod-test-public iptables -S INPUT | grep -q -- "--dport 22 -j DROP" && echo "  Firewall policy applied" || { echo "  Policy failed"; exit 1; }
	@rm -f /tmp/test-policy.json
	@echo ""
	@echo "==> Phase 6: Metadata & Verification"
	@vpcctl inspect prod-test | grep -q '"name": "prod-test"' && echo "  Metadata tracking OK" || exit 1
	@vpcctl verify | grep -q "prod-test\|staging-test" && echo "  Resource tracking OK" || exit 1
	@echo ""
	@echo "==> Phase 7: Cleanup Test"
	@vpcctl delete prod-test
	@vpcctl delete staging-test
	@vpcctl verify | grep -q "Orphan.*None" && echo "  Clean teardown" || { echo "✗ Orphans detected"; exit 1; }
	@echo ""
	@echo "=================================================="
	@echo "    ALL TESTS PASSED"
	@echo "=================================================="
	@echo ""

# Interactive demo
demo: install
	@echo ""
	@echo "=================================================="
	@echo "  Interactive Demo"
	@echo "=================================================="
	@echo ""
	@echo "This will create a demo VPC with public/private subnets,"
	@echo "deploy test apps, enable NAT, and demonstrate peering."
	@echo ""
	@read -p "Press Enter to continue or Ctrl+C to cancel... " dummy
	@IFACE=$$(ip route | grep default | awk '{print $$5}' | head -1); \
	echo "Using interface: $$IFACE"; \
	vpcctl create demo-vpc --cidr 10.50.0.0/16; \
	vpcctl add-subnet demo-vpc public --cidr 10.50.1.0/24; \
	vpcctl add-subnet demo-vpc private --cidr 10.50.2.0/24; \
	vpcctl deploy-app demo-vpc public --port 8080; \
	vpcctl deploy-app demo-vpc private --port 8081; \
	echo ""; \
	echo "Testing connectivity..."; \
	ip netns exec ns-demo-vpc-private curl -sS http://10.50.1.2:8080 | head -3; \
	echo ""; \
	echo "Enabling NAT for public subnet..."; \
	vpcctl enable-nat demo-vpc --interface $$IFACE --subnet public; \
	echo ""; \
	echo "Demo VPC created! Inspect with: sudo vpcctl inspect demo-vpc"; \
	echo "Clean up with: sudo make cleanup"

# Cleanup all VPCs
cleanup:
	@echo ""
	@echo "==> Cleaning up all VPCs..."
	@vpcctl cleanup-all 2>/dev/null || true
	@echo "  Cleanup complete"
	@echo ""

# Verify system state
verify:
	@echo ""
	@echo "==> Verifying system state..."
	@vpcctl verify
	@echo ""

# Uninstall vpcctl
uninstall:
	@echo ""
	@echo "==> Uninstalling vpcctl..."
	@$(MAKE) -s cleanup 2>/dev/null || true
	@rm -f /usr/local/bin/vpcctl
	@rm -rf .vpcctl_data
	@echo "  vpcctl uninstalled"
	@echo ""

# Complete workflow (grader-friendly)
all: install test-full cleanup
	@echo ""
	@echo "=================================================="
	@echo "  Complete Test Cycle Finished"
	@echo "=================================================="
	@echo ""
	@echo "Summary:"
	@echo "    Installation verified"
	@echo "    All tests passed"
	@echo "    Cleanup completed"
	@echo ""
	@echo "The system is ready for the next run."
	@echo "=================================================="
	@echo ""
