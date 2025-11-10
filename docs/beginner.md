# The Complete Beginner's Guide to vpcctl: Building Virtual Networks on Linux

**A hands-on, beginner-friendly guide to understanding Virtual Private Clouds and building isolated networks on a single Linux machine**

---

## Table of Contents

1. [Introduction: What Problem Are We Solving?](#introduction-what-problem-are-we-solving)
2. [Real-World Scenario: The Coffee Shop Network](#real-world-scenario-the-coffee-shop-network)
3. [Understanding the Basics](#understanding-the-basics)
   - [What is a VPC?](#what-is-a-vpc)
   - [What is a Subnet?](#what-is-a-subnet)
   - [What is NAT?](#what-is-nat)
   - [What is Peering?](#what-is-peering)
4. [How vpcctl Works Under the Hood](#how-vpcctl-works-under-the-hood)
5. [Prerequisites and Installation](#prerequisites-and-installation)
6. [Your First VPC: Step-by-Step Tutorial](#your-first-vpc-step-by-step-tutorial)
7. [Understanding Every vpcctl Function](#understanding-every-vpcctl-function)
8. [Advanced Scenarios](#advanced-scenarios)
9. [Troubleshooting Common Issues](#troubleshooting-common-issues)
10. [Complete Code Reference](#complete-code-reference)

---

## Introduction: What Problem Are We Solving?

Imagine you're a developer working on a web application. Your app has:
- A **web server** that customers access
- A **database** that stores customer data
- An **admin panel** for internal staff

You want to:
1. **Isolate** your database so random people on the internet can't access it
2. **Allow** your web server to talk to the database
3. **Control** which ports and services are accessible from outside
4. **Test** everything locally before deploying to the cloud

This is exactly what cloud providers like AWS, Azure, and Google Cloud do with their VPC (Virtual Private Cloud) services. But what if you want to:
- Learn how these systems work without spending money?
- Test network configurations on your laptop?
- Understand the underlying Linux networking magic?

**That's where vpcctl comes in.** It's a tool that simulates cloud-style VPCs on a single Linux computer using native Linux features.

---

## Real-World Scenario: The Coffee Shop Network

Let's use a simple analogy to understand VPCs and subnets.

### The Coffee Shop

Imagine you own a coffee shop with different areas:

1. **The Customer Area (Public Subnet)**
   - Customers can walk in freely
   - They can order coffee and use WiFi
   - They can access the internet

2. **The Kitchen (Private Subnet)**
   - Only staff can enter
   - This is where coffee is made
   - No direct internet access needed
   - But staff need to send orders from the customer area to the kitchen

3. **The Office (Another Private Subnet)**
   - Where you do accounting and management
   - Only the owner can access
   - Needs internet to process payments
   - Completely separate from the kitchen

In networking terms:
- The entire coffee shop is your **VPC** (Virtual Private Cloud)
- Each area (customer area, kitchen, office) is a **subnet**
- The staff walking between areas is **routing**
- The front door that controls who enters is your **firewall/security group**
- The WiFi router that lets customers access the internet is **NAT** (Network Address Translation)

### Translating to vpcctl

When you create a VPC with vpcctl, you're building a virtual "coffee shop":

```bash
# Create the coffee shop (VPC)
sudo vpcctl create coffeeshop --cidr 10.1.0.0/16

# Create the customer area (public subnet)
sudo vpcctl add-subnet coffeeshop customer-area --cidr 10.1.1.0/24

# Create the kitchen (private subnet)
sudo vpcctl add-subnet coffeeshop kitchen --cidr 10.1.2.0/24

# Create the office (private subnet)
sudo vpcctl add-subnet coffeeshop office --cidr 10.1.3.0/24
```

Now you have isolated areas that you can control independently!

---

## Understanding the Basics

### What is a VPC?

**VPC stands for Virtual Private Cloud.**

Think of it as your own private piece of the internet. In the real world (AWS, Azure), it's a logically isolated section of the cloud where you can launch resources. On your Linux machine with vpcctl, it's a simulated network environment.

**Key characteristics:**
- Has its own IP address range (CIDR block)
- Everything inside can talk to each other by default
- Isolated from other VPCs
- You control all the networking rules

**Example:**
```bash
sudo vpcctl create myapp --cidr 10.10.0.0/16
```

This creates a VPC named "myapp" with IP addresses ranging from 10.10.0.1 to 10.10.255.254.

### What is a Subnet?

**A subnet is a subdivision of your VPC.**

If a VPC is a building, subnets are the individual rooms. Each subnet has:
- A smaller IP range (part of the VPC's range)
- A specific purpose (public-facing, private, database, etc.)
- Its own security rules

**Types of subnets:**

1. **Public Subnet**
   - Can access the internet
   - Can be accessed from the internet (with proper rules)
   - Example: Web servers, load balancers

2. **Private Subnet**
   - Cannot be directly accessed from the internet
   - Can access internet through NAT (if configured)
   - Example: Databases, internal services

**Example:**
```bash
# Public subnet for web servers
sudo vpcctl add-subnet myapp web --cidr 10.10.1.0/24

# Private subnet for databases
sudo vpcctl add-subnet myapp database --cidr 10.10.2.0/24
```

### What is NAT?

**NAT stands for Network Address Translation.**

**The Problem:** Your private subnet (like the database) might need to download security updates from the internet, but you don't want the internet to directly access your database.

**The Solution:** NAT acts like a receptionist:
- Your database makes a request to download something
- The NAT gateway forwards that request using its own public IP
- The response comes back to NAT
- NAT forwards it to your database
- From the internet's perspective, everything came from NAT

**Think of it like a hotel:**
- You're in room 205 (private IP: 10.10.2.5)
- You call reception and ask them to order pizza
- Reception calls the pizza place using the hotel's number (public IP)
- Pizza arrives at reception, they call you to pick it up
- The pizza place never knew your room number

**Example:**
```bash
# Enable internet access for your VPC through NAT
sudo vpcctl enable-nat myapp --interface eth0
```

### What is Peering?

**Peering connects two separate VPCs so they can talk to each other.**

**Real-world scenario:** You have two applications:
- VPC 1: Your main web application
- VPC 2: Your analytics service

You want the web app to send data to analytics, but you want to keep them in separate VPCs for security and organization.

**Peering creates a private bridge between them.**

**Example:**
```bash
# Create two VPCs
sudo vpcctl create webapp --cidr 10.10.0.0/16
sudo vpcctl create analytics --cidr 10.20.0.0/16

# Connect them via peering
sudo vpcctl peer webapp analytics --allow-cidrs 10.10.1.0/24,10.20.1.0/24
```

Now specific subnets in webapp and analytics can communicate!

---

## How vpcctl Works Under the Hood

vpcctl uses Linux networking primitives. Here's what's really happening:

### 1. Network Namespaces
**What they are:** Isolated network environments on Linux. Each namespace has its own network interfaces, routing tables, and firewall rules.

**Why we use them:** Each subnet you create is actually a network namespace. This provides true isolation—processes in one namespace can't see or access another namespace's network.

**Real command:**
```bash
# vpcctl runs this for you:
sudo ip netns add ns-myapp-web
```

### 2. Virtual Ethernet (veth) Pairs
**What they are:** Like a virtual network cable. Data sent into one end comes out the other.

**Why we use them:** To connect a namespace (subnet) to the VPC bridge.

**Think of it as:** A network cable plugged into your computer's network card.

**Real command:**
```bash
# vpcctl creates a veth pair:
sudo ip link add v-myapp-web-a type veth peer name v-myapp-web-b
```

### 3. Linux Bridge
**What it is:** A virtual network switch inside your computer.

**Why we use it:** Each VPC is a bridge. All subnets (namespaces) in that VPC connect to this bridge, allowing them to communicate.

**Think of it as:** A network switch in an office that connects all computers.

**Real command:**
```bash
# vpcctl creates a bridge for each VPC:
sudo ip link add br-myapp type bridge
```

### 4. iptables
**What it is:** Linux's firewall system.

**Why we use it:** To control traffic flow, implement NAT, enforce security policies, and manage peering rules.

**Real command:**
```bash
# NAT rule example:
sudo iptables -t nat -A POSTROUTING -s 10.10.0.0/16 -o eth0 -j MASQUERADE
```

### The Complete Picture

When you run:
```bash
sudo vpcctl create myapp --cidr 10.10.0.0/16
sudo vpcctl add-subnet myapp web --cidr 10.10.1.0/24
```

Here's what happens:

1. **VPC Creation:**
   - Creates a Linux bridge named `br-myapp`
   - Assigns IP `10.10.0.1` to the bridge
   - Creates an iptables chain `vpc-myapp` for filtering traffic
   - Saves metadata to `.vpcctl_data/vpc_myapp.json`

2. **Subnet Creation:**
   - Creates a network namespace `ns-myapp-web`
   - Creates a veth pair: one end in the namespace, one on the bridge
   - Assigns IP `10.10.1.2` inside the namespace
   - Sets up routing inside the namespace
   - Generates and applies default security policies
   - Updates the metadata JSON

**Visual representation:**
```
Host Machine
├─ Bridge: br-myapp (10.10.0.1)
│  │
│  ├─ veth ←→ Namespace: ns-myapp-web (10.10.1.2)
│  │          └─ Your web application runs here
│  │
│  └─ veth ←→ Namespace: ns-myapp-db (10.10.2.2)
│             └─ Your database runs here
│
└─ Physical Interface: eth0 (internet connection)
   └─ iptables NAT rules forward traffic
```

---

## Prerequisites and Installation

### System Requirements

**Operating System:**
- Linux (Ubuntu 20.04+ or Debian 10+ recommended)
- You can use a virtual machine if you're on Windows or Mac

**Required Tools:**
- Python 3.6 or higher
- iproute2 (provides `ip` command)
- iptables
- curl (for testing)

**Privileges:**
- Root access (sudo) is required

### Installation Steps

#### Step 1: Install Required Packages

On Ubuntu/Debian:
```bash
sudo apt update
sudo apt install -y python3 iproute2 iptables curl tcpdump bridge-utils
```

On CentOS/RHEL:
```bash
sudo yum install -y python3 iproute iptables curl tcpdump bridge-utils
```

#### Step 2: Download vpcctl

**Option A: Clone from GitHub**
```bash
git clone https://github.com/DestinyObs/HNGi13-Stage4-vpcctl/
cd vpcctl
```

**Option B: Download the Single File**
```bash
curl -O https://github.com/DestinyObs/HNGi13-Stage4-vpcctl/blob/main/vpcctl.py
chmod +x vpcctl.py
```

#### Step 3: Install vpcctl as a Command (Optional but Recommended)

This lets you type `vpcctl` instead of `python3 vpcctl.py`:

```bash
# Make it executable
chmod +x vpcctl.py

# Create a symlink in your PATH
sudo ln -s "$(pwd)/vpcctl.py" /usr/local/bin/vpcctl

# Verify installation
vpcctl --help
```

#### Step 4: Verify Everything Works

Run the parser check (this is safe and makes no system changes):
```bash
sudo vpcctl flag-check
```

You should see: "Parser check OK"

---

## Your First VPC: Step-by-Step Tutorial

Let's build a realistic setup: a simple web application with a database.

### Scenario

You're building a blog platform with:
- A web server (public, accessible from internet)
- A database server (private, not accessible from internet)
- The web server needs to access the database
- The database needs to download updates from the internet (via NAT)

### Step 1: Create the VPC

```bash
sudo vpcctl create blog --cidr 10.20.0.0/16
```

**What this does:**
- Creates a VPC named "blog"
- Assigns IP range 10.20.0.0/16 (65,534 possible addresses)
- Creates a bridge `br-blog`

**Expected output:**
```
>>> ip link add br-blog type bridge
>>> ip addr add 10.20.0.1/16 dev br-blog
>>> ip link set br-blog up
Created VPC: blog (10.20.0.0/16, bridge: br-blog)
```

### Step 2: Add a Public Subnet for the Web Server

```bash
sudo vpcctl add-subnet blog webserver --cidr 10.20.1.0/24
```

**What this does:**
- Creates a subnet named "webserver" in the blog VPC
- Assigns IP range 10.20.1.0/24 (254 addresses)
- Creates namespace `ns-blog-webserver`
- Sets up connectivity

**Expected output:**
```
>>> ip netns add ns-blog-webserver
>>> ip link add v-blog-webser-a type veth peer name v-blog-webser-b
>>> ip link set v-blog-webser-a netns ns-blog-webserver
>>> ip link set v-blog-webser-b master br-blog
...
Added subnet webserver (10.20.1.0/24) to VPC blog
```

### Step 3: Add a Private Subnet for the Database

```bash
sudo vpcctl add-subnet blog database --cidr 10.20.2.0/24
```

**What this does:**
- Creates another subnet for the database
- Separate namespace `ns-blog-database`
- IP range 10.20.2.0/24

### Step 4: Deploy Test Applications

Let's deploy a simple HTTP server in each subnet to test connectivity:

```bash
# Deploy web server on port 8080
sudo vpcctl deploy-app blog webserver --port 8080

# Deploy database mock on port 5432
sudo vpcctl deploy-app blog database --port 5432
```

**What this does:**
- Starts a Python HTTP server inside each namespace
- Web server: accessible on 10.20.1.2:8080
- Database: accessible on 10.20.2.2:5432

**Expected output:**
```
Deployed app in subnet webserver (ns-blog-webserver) on port 8080, PID=12345
```

### Step 5: Test Intra-VPC Connectivity

Let's verify that the web server can reach the database (they're in the same VPC):

```bash
sudo ip netns exec ns-blog-webserver curl -s http://10.20.2.2:5432
```

**Expected result:** You should see HTML output from the Python server running in the database namespace.

**What this command does:**
- `ip netns exec ns-blog-webserver`: Run the following command inside the webserver namespace
- `curl http://10.20.2.2:5432`: Make an HTTP request to the database

✅ **Success!** Your web server can talk to your database.

### Step 6: Enable Internet Access (NAT)

Right now, neither subnet can access the internet. Let's add NAT:

```bash
# Find your host's network interface (usually eth0, enp0s3, or wlan0)
ip route | grep default

# Enable NAT (replace eth0 with your interface)
sudo vpcctl enable-nat blog --interface eth0
```

**What this does:**
- Adds iptables MASQUERADE rule
- Enables IP forwarding on the host
- Allows namespaces to access the internet using the host's IP

### Step 7: Test Internet Access

From the web server namespace:
```bash
sudo ip netns exec ns-blog-webserver curl -s http://example.com | head -n 5
```

**Expected result:** HTML from example.com

✅ **Success!** Your subnets can now access the internet.

### Step 8: Apply Security Policies

Let's restrict access to the database—block SSH (port 22) but allow HTTP (port 80):

First, create a policy file `database_policy.json`:
```json
{
  "subnet": "10.20.2.0/24",
  "ingress": [
    {"port": 5432, "protocol": "tcp", "action": "allow"},
    {"port": 22, "protocol": "tcp", "action": "deny"}
  ],
  "egress": [
    {"port": 80, "protocol": "tcp", "action": "allow"},
    {"port": 443, "protocol": "tcp", "action": "allow"}
  ]
}
```

Apply the policy:
```bash
sudo vpcctl apply-policy blog database_policy.json
```

**What this does:**
- Adds iptables rules inside the database namespace
- Blocks incoming SSH connections
- Allows incoming connections on port 5432 (PostgreSQL)
- Allows outgoing HTTP/HTTPS

### Step 9: List Your VPCs

```bash
sudo vpcctl list
```

**Output:**
```
VPCs:
- blog
```

### Step 10: Inspect VPC Details

```bash
sudo vpcctl inspect blog
```

**Output:** Full JSON metadata showing subnets, IP addresses, running apps, and applied policies.

### Step 11: Cleanup

When you're done experimenting:
```bash
sudo vpcctl delete blog
```

**What this does:**
- Stops all running applications
- Deletes namespaces
- Removes the bridge
- Cleans up iptables rules
- Deletes metadata

**Expected output:**
```
Deleted VPC: blog
```

---

## Understanding Every vpcctl Function

Let's walk through each command in detail.

### 1. `create` - Create a New VPC

**Purpose:** Initialize a new VPC with an IP address range.

**Syntax:**
```bash
sudo vpcctl create <vpc-name> --cidr <ip-range>
```

**Parameters:**
- `<vpc-name>`: Any alphanumeric name (e.g., "myapp", "production", "test_vpc")
- `--cidr`: IP address range in CIDR notation (e.g., 10.0.0.0/16)

**What happens internally:**
1. Creates a Linux bridge named `br-<vpc-name>`
2. Assigns the first IP in the range to the bridge (gateway IP)
3. Brings the bridge up
4. Creates an iptables chain for the VPC
5. Saves metadata to `.vpcctl_data/vpc_<name>.json`

**Examples:**
```bash
# Development VPC
sudo vpcctl create dev --cidr 10.10.0.0/16

# Production VPC
sudo vpcctl create prod --cidr 10.20.0.0/16

# Testing VPC
sudo vpcctl create test --cidr 192.168.100.0/24
```

**Common CIDR ranges:**
- `/16`: 65,534 hosts (10.0.0.0/16 → 10.0.0.1 to 10.0.255.254)
- `/24`: 254 hosts (10.0.1.0/24 → 10.0.1.1 to 10.0.1.254)
- `/20`: 4,094 hosts

**Dry-run mode (preview without changes):**
```bash
vpcctl --dry-run create dev --cidr 10.10.0.0/16
```

---

### 2. `add-subnet` - Create a Subnet

**Purpose:** Add a subnet (network namespace) to an existing VPC.

**Syntax:**
```bash
sudo vpcctl add-subnet <vpc-name> <subnet-name> --cidr <ip-range>
```

**Parameters:**
- `<vpc-name>`: Name of the VPC
- `<subnet-name>`: Name for this subnet (e.g., "public", "private", "web", "db")
- `--cidr`: IP range for this subnet (must be within VPC's range)
- `--gw` (optional): Gateway IP (defaults to first IP in subnet range)

**What happens internally:**
1. Creates a network namespace `ns-<vpc>-<subnet>`
2. Creates a veth pair (virtual network cable)
3. Attaches one end to the namespace, one to the VPC bridge
4. Assigns IP addresses
5. Sets up routing tables inside the namespace
6. Generates default security policy
7. Applies the policy

**Examples:**
```bash
# Public subnet for web servers
sudo vpcctl add-subnet myapp web --cidr 10.10.1.0/24

# Private subnet for databases
sudo vpcctl add-subnet myapp database --cidr 10.10.2.0/24

# Private subnet for backend services
sudo vpcctl add-subnet myapp backend --cidr 10.10.3.0/24

# Custom gateway IP
sudo vpcctl add-subnet myapp dmz --cidr 10.10.4.0/24 --gw 10.10.4.254
```

**Subnet naming best practices:**
- `public`: Internet-facing resources
- `private`: Internal resources
- `database` or `db`: Database servers
- `backend`: Application backend services
- `frontend`: Frontend services

**Default policy applied:**
- **Ingress:** Allow TCP ports 80, 443; Deny TCP port 22
- **Egress:** No restrictions (allows all outbound)

---

### 3. `deploy-app` - Deploy a Test Application

**Purpose:** Start a simple Python HTTP server inside a subnet for testing.

**Syntax:**
```bash
sudo vpcctl deploy-app <vpc-name> <subnet-name> --port <port>
```

**Parameters:**
- `<vpc-name>`: Name of the VPC
- `<subnet-name>`: Name of the subnet
- `--port`: Port number for the HTTP server

**What happens internally:**
1. Runs `python3 -m http.server <port>` inside the namespace
2. Uses `nohup` to run in background
3. Records PID (process ID) in metadata
4. Saves the command for later cleanup

**Examples:**
```bash
# Web server on standard HTTP port
sudo vpcctl deploy-app myapp web --port 8080

# Database mock on PostgreSQL port
sudo vpcctl deploy-app myapp database --port 5432

# API server
sudo vpcctl deploy-app myapp api --port 3000
```

**Testing the deployed app:**
```bash
# From another subnet in the same VPC
sudo ip netns exec ns-myapp-web curl http://10.10.2.2:5432

# From the host
curl http://10.10.1.2:8080
```

**Note:** This is for testing only. In real scenarios, you'd deploy actual applications (Node.js, Python Flask, PostgreSQL, etc.) inside the namespaces.

---

### 4. `stop-app` - Stop a Running Application

**Purpose:** Stop an application that was started with `deploy-app`.

**Syntax:**
```bash
sudo vpcctl stop-app <vpc-name> <subnet-name>
```

**What happens internally:**
1. Looks up the PID from metadata
2. Kills the process
3. Removes app entry from metadata

**Examples:**
```bash
sudo vpcctl stop-app myapp web
```

---

### 5. `enable-nat` - Enable Internet Access

**Purpose:** Allow subnets to access the internet using the host's IP address (NAT).

**Syntax:**
```bash
sudo vpcctl enable-nat <vpc-name> --interface <host-interface>
```

**Parameters:**
- `<vpc-name>`: Name of the VPC
- `--interface`: Host network interface (eth0, enp0s3, wlan0, etc.)

**Optional flags:**
- `--subnet-filter`: Only enable NAT for specific subnets (comma-separated)

**What happens internally:**
1. Enables IP forwarding: `sysctl net.ipv4.ip_forward=1`
2. Adds MASQUERADE rule: `iptables -t nat -A POSTROUTING -s <vpc-cidr> -o <interface> -j MASQUERADE`
3. Adds FORWARD rules to allow traffic
4. Records rules in metadata for cleanup

**Examples:**
```bash
# Enable NAT for entire VPC
sudo vpcctl enable-nat myapp --interface eth0

# Enable NAT only for specific subnets
sudo vpcctl enable-nat myapp --interface eth0 --subnet-filter public,web
```

**Find your host interface:**
```bash
ip route | grep default
# Output: default via 192.168.1.1 dev eth0
#                                      ^^^^ this is your interface
```

**Common interfaces:**
- `eth0`: Ethernet
- `enp0s3`: VirtualBox VM
- `wlan0`: WiFi
- `wlp2s0`: WiFi (newer naming)

---

### 6. `peer` - Connect Two VPCs

**Purpose:** Create a connection between two VPCs so specific subnets can communicate.

**Syntax:**
```bash
sudo vpcctl peer <vpc1-name> <vpc2-name> --allow-cidrs <cidr1>,<cidr2>,...
```

**Parameters:**
- `<vpc1-name>`, `<vpc2-name>`: Names of the VPCs to connect
- `--allow-cidrs`: Comma-separated list of CIDR blocks allowed to communicate

**What happens internally:**
1. Creates a veth pair between the two VPC bridges
2. Adds iptables rules to allow traffic for specified CIDRs
3. Adds DROP rule for all other traffic (security)
4. Records peering info in both VPCs' metadata

**Examples:**
```bash
# Create two VPCs
sudo vpcctl create app1 --cidr 10.10.0.0/16
sudo vpcctl create app2 --cidr 10.20.0.0/16

# Add subnets
sudo vpcctl add-subnet app1 web --cidr 10.10.1.0/24
sudo vpcctl add-subnet app2 api --cidr 10.20.1.0/24

# Peer them (allow only web and api subnets to talk)
sudo vpcctl peer app1 app2 --allow-cidrs 10.10.1.0/24,10.20.1.0/24
```

**Use cases:**
- Main app needs to talk to analytics service
- Frontend VPC needs to reach backend VPC
- Staging environment needs to access shared services

**Security:** Only the CIDRs you specify can communicate. Everything else is blocked.

---

### 7. `apply-policy` - Apply Firewall Rules

**Purpose:** Apply custom ingress and egress firewall rules to a subnet.

**Syntax:**
```bash
sudo vpcctl apply-policy <vpc-name> <policy-file.json>
```

**Parameters:**
- `<vpc-name>`: Name of the VPC
- `<policy-file.json>`: Path to JSON policy file

**Policy file format:**
```json
{
  "subnet": "10.10.1.0/24",
  "ingress": [
    {"port": 80, "protocol": "tcp", "action": "allow"},
    {"port": 443, "protocol": "tcp", "action": "allow"},
    {"port": 22, "protocol": "tcp", "action": "deny"}
  ],
  "egress": [
    {"port": 25, "protocol": "tcp", "action": "deny"},
    {"port": 80, "protocol": "tcp", "action": "allow"}
  ]
}
```

**What happens internally:**
1. Reads the JSON policy
2. Translates rules to iptables commands
3. Executes commands inside the namespace using `ip netns exec`
4. Records policy in metadata

**Examples:**

**Example 1: Web Server (allow HTTP/HTTPS, block SSH)**
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

```bash
sudo vpcctl apply-policy myapp web_policy.json
```

**Example 2: Database (allow only PostgreSQL, block everything else)**
```json
{
  "subnet": "10.10.2.0/24",
  "ingress": [
    {"port": 5432, "protocol": "tcp", "action": "allow"}
  ],
  "egress": [
    {"port": 80, "protocol": "tcp", "action": "allow"},
    {"port": 443, "protocol": "tcp", "action": "allow"}
  ]
}
```

**Actions:**
- `allow`: Permit traffic
- `deny`: Block traffic

**Protocols:**
- `tcp`: TCP traffic
- `udp`: UDP traffic
- `icmp`: Ping and ICMP

---

### 8. `list` - List All VPCs

**Purpose:** Show all VPCs you've created.

**Syntax:**
```bash
sudo vpcctl list
```

**Output example:**
```
VPCs:
- myapp
- production
- test_vpc
```

---

### 9. `inspect` - View VPC Details

**Purpose:** Show detailed information about a specific VPC.

**Syntax:**
```bash
sudo vpcctl inspect <vpc-name>
```

**Output:** JSON metadata including:
- VPC name and CIDR
- Bridge name
- All subnets with their IPs and namespaces
- Running applications (PIDs)
- Peering connections
- NAT configuration
- Applied iptables rules

**Example:**
```bash
sudo vpcctl inspect myapp
```

**Output:**
```json
{
  "name": "myapp",
  "cidr": "10.10.0.0/16",
  "bridge": "br-myapp",
  "subnets": [
    {
      "name": "web",
      "cidr": "10.10.1.0/24",
      "ns": "ns-myapp-web",
      "gw": "10.10.1.1",
      "host_ip": "10.10.1.2"
    }
  ],
  "apps": [
    {
      "ns": "ns-myapp-web",
      "port": 8080,
      "pid": 12345
    }
  ]
}
```

---

### 10. `delete` - Delete a VPC

**Purpose:** Completely remove a VPC and all its subnets.

**Syntax:**
```bash
sudo vpcctl delete <vpc-name>
```

**What happens internally:**
1. Stops all running applications
2. Removes all iptables rules (using recorded commands from metadata)
3. Deletes all network namespaces
4. Removes veth pairs
5. Deletes the bridge
6. Removes peering connections
7. Deletes metadata file

**Example:**
```bash
sudo vpcctl delete myapp
```

**Warning:** This is destructive and cannot be undone!

---

### 11. `cleanup-all` - Emergency Cleanup

**Purpose:** Delete ALL VPCs at once.

**Syntax:**
```bash
sudo vpcctl cleanup-all
```

**Use cases:**
- Starting fresh
- Something went wrong and you want to reset
- Clearing test environments

**Warning:** Deletes everything created by vpcctl!

---

### 12. `verify` - Run System Checks

**Purpose:** Verify your system has all required tools and permissions.

**Syntax:**
```bash
sudo vpcctl verify
```

**Checks performed:**
- Root/sudo access
- `ip` command availability
- `iptables` command availability
- `bridge` command availability
- Existing VPCs and their states

---

### 13. `test-connectivity` - Test Network Connectivity

**Purpose:** Test if one subnet can reach another.

**Syntax:**
```bash
sudo vpcctl test-connectivity <vpc-name> <source-subnet> <target-ip> --port <port>
```

**Example:**
```bash
# Test if web subnet can reach database
sudo vpcctl test-connectivity myapp web 10.10.2.2 --port 5432
```

---

### 14. `flag-check` - Validate CLI Parser

**Purpose:** Test that the command-line parser works correctly (safe, no system changes).

**Syntax:**
```bash
sudo vpcctl flag-check
```

**Output:** "Parser check OK" or error messages

---

### 15. `--dry-run` - Preview Mode (Global Flag)

**Purpose:** See what commands would be executed without actually running them.

**Syntax:**
```bash
vpcctl --dry-run <any-command>
```

**Examples:**
```bash
# Preview VPC creation
vpcctl --dry-run create test --cidr 10.99.0.0/16

# Preview subnet addition
vpcctl --dry-run add-subnet test web --cidr 10.99.1.0/24
```

**Use cases:**
- Learning what vpcctl does
- Debugging issues
- Verifying commands before execution

---

## Advanced Scenarios

### Scenario 1: Multi-Tier Web Application

Build a realistic 3-tier architecture:

```bash
# Create VPC
sudo vpcctl create webapp --cidr 10.30.0.0/16

# Tier 1: Load balancer (public)
sudo vpcctl add-subnet webapp loadbalancer --cidr 10.30.1.0/24

# Tier 2: Application servers (private)
sudo vpcctl add-subnet webapp appservers --cidr 10.30.2.0/24

# Tier 3: Database (private)
sudo vpcctl add-subnet webapp database --cidr 10.30.3.0/24

# Deploy apps
sudo vpcctl deploy-app webapp loadbalancer --port 80
sudo vpcctl deploy-app webapp appservers --port 8080
sudo vpcctl deploy-app webapp database --port 5432

# Enable NAT for updates
sudo vpcctl enable-nat webapp --interface eth0

# Apply strict database policy
cat > db_policy.json << 'EOF'
{
  "subnet": "10.30.3.0/24",
  "ingress": [
    {"port": 5432, "protocol": "tcp", "action": "allow"}
  ],
  "egress": [
    {"port": 80, "protocol": "tcp", "action": "allow"},
    {"port": 443, "protocol": "tcp", "action": "allow"}
  ]
}
EOF

sudo vpcctl apply-policy webapp db_policy.json

# Test connectivity
# Load balancer → App server
sudo ip netns exec ns-webapp-loadbalancer curl http://10.30.2.2:8080

# App server → Database
sudo ip netns exec ns-webapp-appservers curl http://10.30.3.2:5432
```

---

### Scenario 2: Microservices with Service Mesh

Simulate a microservices architecture:

```bash
# Create VPC for microservices
sudo vpcctl create microservices --cidr 10.40.0.0/16

# API Gateway (public)
sudo vpcctl add-subnet microservices api-gateway --cidr 10.40.1.0/24

# User Service (private)
sudo vpcctl add-subnet microservices user-service --cidr 10.40.2.0/24

# Order Service (private)
sudo vpcctl add-subnet microservices order-service --cidr 10.40.3.0/24

# Payment Service (private)
sudo vpcctl add-subnet microservices payment-service --cidr 10.40.4.0/24

# Shared Database
sudo vpcctl add-subnet microservices shared-db --cidr 10.40.10.0/24

# Deploy services
sudo vpcctl deploy-app microservices api-gateway --port 8080
sudo vpcctl deploy-app microservices user-service --port 8081
sudo vpcctl deploy-app microservices order-service --port 8082
sudo vpcctl deploy-app microservices payment-service --port 8083
sudo vpcctl deploy-app microservices shared-db --port 5432

# Enable internet access
sudo vpcctl enable-nat microservices --interface eth0

# Test inter-service communication
sudo ip netns exec ns-microservices-api-gateway curl http://10.40.2.2:8081
sudo ip netns exec ns-microservices-order-service curl http://10.40.10.2:5432
```

---

### Scenario 3: Development and Production Isolation with Peering

```bash
# Create Development VPC
sudo vpcctl create dev --cidr 10.50.0.0/16
sudo vpcctl add-subnet dev web --cidr 10.50.1.0/24
sudo vpcctl add-subnet dev db --cidr 10.50.2.0/24

# Create Production VPC
sudo vpcctl create prod --cidr 10.60.0.0/16
sudo vpcctl add-subnet prod web --cidr 10.60.1.0/24
sudo vpcctl add-subnet prod db --cidr 10.60.2.0/24

# Create Shared Services VPC (logging, monitoring)
sudo vpcctl create shared --cidr 10.70.0.0/16
sudo vpcctl add-subnet shared logging --cidr 10.70.1.0/24
sudo vpcctl add-subnet shared monitoring --cidr 10.70.2.0/24

# Peer dev and shared (so dev can send logs)
sudo vpcctl peer dev shared --allow-cidrs 10.50.1.0/24,10.70.1.0/24

# Peer prod and shared (so prod can send logs)
sudo vpcctl peer prod shared --allow-cidrs 10.60.1.0/24,10.70.1.0/24

# Note: dev and prod are NOT peered (isolated from each other)

# Deploy apps
sudo vpcctl deploy-app dev web --port 8080
sudo vpcctl deploy-app prod web --port 8080
sudo vpcctl deploy-app shared logging --port 9200

# Test: dev can reach shared logging
sudo ip netns exec ns-dev-web curl http://10.70.1.2:9200

# Test: prod can reach shared logging
sudo ip netns exec ns-prod-web curl http://10.70.1.2:9200

# Verify: dev CANNOT reach prod (should fail)
sudo ip netns exec ns-dev-web curl --max-time 5 http://10.60.1.2:8080 || echo "Correctly blocked!"
```

---

### Scenario 4: Simulating Cloud Provider Regions

```bash
# Region 1: us-east
sudo vpcctl create us-east --cidr 10.1.0.0/16
sudo vpcctl add-subnet us-east public --cidr 10.1.1.0/24
sudo vpcctl add-subnet us-east private --cidr 10.1.2.0/24

# Region 2: eu-west
sudo vpcctl create eu-west --cidr 10.2.0.0/16
sudo vpcctl add-subnet eu-west public --cidr 10.2.1.0/24
sudo vpcctl add-subnet eu-west private --cidr 10.2.2.0/24

# Cross-region peering (like AWS Transit Gateway)
sudo vpcctl peer us-east eu-west --allow-cidrs 10.1.1.0/24,10.2.1.0/24

# Deploy apps
sudo vpcctl deploy-app us-east public --port 8080
sudo vpcctl deploy-app eu-west public --port 8080

# Test cross-region communication
sudo ip netns exec ns-us-east-public curl http://10.2.1.2:8080
```

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

**Symptom:**
```bash
sudo ip netns exec ns-myapp-web curl http://google.com
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
sudo ip netns exec ns-myapp-web curl http://google.com
```

---

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

**Recommended reading:**
- `man ip-netns`
- `man iptables`
- `man ip-link`

### Practice Exercises

**Exercise 1: Build a DMZ**
Create a 3-subnet VPC with:
- Public DMZ (web servers)
- Private application tier
- Private database tier

**Exercise 2: Simulate AWS VPC**
Replicate an AWS VPC setup with:
- Public and private subnets across 2 availability zones
- NAT gateway
- Security groups via policies

**Exercise 3: Microservices Mesh**
Build 5+ microservices that communicate via private networking.

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

## Appendix: Mapping to Cloud Providers

### vpcctl → AWS

| vpcctl | AWS Equivalent |
|--------|----------------|
| VPC | VPC |
| Subnet | Subnet |
| enable-nat | NAT Gateway |
| peer | VPC Peering |
| apply-policy | Security Groups |
| Bridge | (Internal AWS implementation) |
| Namespace | (Internal AWS implementation) |

### vpcctl → Azure

| vpcctl | Azure Equivalent |
|--------|------------------|
| VPC | Virtual Network (VNet) |
| Subnet | Subnet |
| enable-nat | NAT Gateway |
| peer | VNet Peering |
| apply-policy | Network Security Groups (NSG) |

### vpcctl → Google Cloud

| vpcctl | GCP Equivalent |
|--------|----------------|
| VPC | VPC Network |
| Subnet | Subnet |
| enable-nat | Cloud NAT |
| peer | VPC Peering |
| apply-policy | Firewall Rules |

---

**Author's Note:** This guide was written to be completely standalone and beginner-friendly. If you're reading this and something is unclear, that's a bug in the documentation, not in your understanding. Re-read the section, try the examples, and experiment!

**Happy networking!**
