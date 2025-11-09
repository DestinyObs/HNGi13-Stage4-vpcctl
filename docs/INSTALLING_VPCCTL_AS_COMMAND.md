Install `vpcctl` as a direct command
=====================================

This short note shows how to make the CLI runnable as `vpcctl` (no `python3` prefix).

Why do this?
- Makes the grader/user experience match `vpcctl ...` invocations.
- Keeps the tool editable in-place (you can symlink) or install system-wide.

Options
-------

1) Copy into `/usr/local/bin` (system-wide)

```bash
sudo cp vpcctl.py /usr/local/bin/vpcctl
sudo sed -i 's/\r$//' /usr/local/bin/vpcctl   # normalize CRLF -> LF if needed
sudo chmod +x /usr/local/bin/vpcctl
```

2) Create a symlink to the repository copy (keeps source single-copy)

```bash
sudo ln -s "$(pwd)/vpcctl.py" /usr/local/bin/vpcctl
sudo chmod +x vpcctl.py
```

Common issues
--------------

- If you get `/usr/bin/env: 'python3\r': No such file or directory`, the problem is CRLF line endings in the shebang. Run `dos2unix vpcctl.py` or `sed -i 's/\r$//' vpcctl.py` and reinstall.
- Privileged operations (namespaces, bridges, iptables) require root. Use `sudo vpcctl <command>` or run the acceptance script with `sudo`.

Verification
------------

After installation, verify:

```bash
vpcctl --help
sudo vpcctl create demo --cidr 10.11.0.0/16
```

If `vpcctl --help` shows usage and the create command runs with `sudo`, the command is installed correctly.

If you prefer to always run from the repository without installing, you can still use `python3 vpcctl.py <subcommand>`.
