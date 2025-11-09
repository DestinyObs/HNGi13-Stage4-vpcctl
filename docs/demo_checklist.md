Demo checklist — 5-minute submission script

Prep

- Ensure you're running on a Linux host with root (Ubuntu VM recommended).
- Ensure `ip`, `iptables`, `bridge` commands are installed (iproute2 and iptables).
- Run: sudo python3 vpcctl.py flag-check  # sanity-check parser

Steps

1. Create VPC A
   - sudo python3 vpcctl.py create t1_vpc 10.30.0.0/16
2. Add public and private subnets
   - sudo python3 vpcctl.py add-subnet t1_vpc public 10.30.1.0/24
   - sudo python3 vpcctl.py add-subnet t1_vpc private 10.30.2.0/24
3. Deploy simple HTTP app
   - sudo python3 vpcctl.py deploy-app t1_vpc public 8080
4. Enable NAT for public subnet (use your host interface e.g., eth0)
   - sudo python3 vpcctl.py enable-nat t1_vpc <your-host-iface>
5. Create VPC B and public subnet, deploy app
   - sudo python3 vpcctl.py create t2_vpc 10.40.0.0/16
   - sudo python3 vpcctl.py add-subnet t2_vpc public 10.40.1.0/24
   - sudo python3 vpcctl.py deploy-app t2_vpc public 8080
6. Peer the VPCs (allow only public CIDRs)
   - sudo python3 vpcctl.py peer t1_vpc t2_vpc --allow-cidrs 10.30.1.0/24,10.40.1.0/24
7. Test connectivity
   - Use ip netns exec or test script: ./policy_test.sh ns-t1_vpc-public 10.40.1.1 8080

Cleanup

- sudo python3 vpcctl.py delete t1_vpc
- sudo python3 vpcctl.py delete t2_vpc
- OR sudo python3 vpcctl.py cleanup-all

Notes

- The CLI is idempotent; rerunning peer or enable-nat will not append duplicate iptables rules.
- Policies: sample in policy_examples/example_ingress_egress_policy.json. Apply with:
  sudo python3 vpcctl.py apply-policy t1_vpc policy_examples/example_ingress_egress_policy.json

