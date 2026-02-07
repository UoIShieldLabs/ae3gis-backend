Awesome — here’s a **fully-documented, hindsight-optimized build** for a second GNS3 VM you can run in parallel over **Wi-Fi bridged networking** (no per-node port forwarding). I’ll set everything up so consoles work out of the box, using the **official gns3-server repo** (not pip), with `gns3:gns3` credentials, Docker + uBridge + socat ready, UFW opened for API and console ports, and a smaller thin-provisioned disk (20 GB).

I’ll label each step so you can reuse it in your eventual bash spawner.

---

# A) Host (macOS) prep — new workspace

```bash
# A1) Tools (once)
brew install qemu python@3.12

# A2) New, separate workspace so this VM is independent from the first one
mkdir -p ~/gns3-qemu/{base,overlays,seeds,logs}
cd ~/gns3-qemu/base

# A3) UEFI firmware: Homebrew ships the code ROM; make your own writable NVRAM
#    (vars.fd is just a raw file; 64M is standard)
qemu-img create -f raw vars.fd 64M

# A4) Download Ubuntu ARM64 cloud image and make it your root base (thin-provisioned)
curl -LO https://cloud-images.ubuntu.com/jammy/current/jammy-server-cloudimg-arm64.img
mv jammy-server-cloudimg-arm64.img root.qcow2

#   Resize to a virtual 20G. This does NOT consume 20G immediately (qcow2 is thin).
qemu-img resize root.qcow2 20G
```

---

# B) Cloud-init seed — everything baked in on first boot

Create seed folder and two config files.

```bash
mkdir -p ~/gns3-qemu/base/seed-init
```

## B1) `user-data` (create user, install deps, Docker, uBridge, GNS3 from repo, systemd unit, firewall)

> Paste the block exactly.

```bash
cat > ~/gns3-qemu/base/seed-init/user-data <<'EOF'
#cloud-config
ssh_pwauth: true

users:
  - name: gns3
    groups: [sudo]
    shell: /bin/bash
    sudo: 'ALL=(ALL) NOPASSWD:ALL'
    lock_passwd: false

chpasswd:
  list: |
    gns3:gns3
  expire: false

package_update: true
packages:
  - python3
  - python3-pip
  - git
  - ufw
  - iproute2
  - net-tools
  - curl
  - ca-certificates
  - gnupg
  - lsb-release
  - socat
  - openssh-server

write_files:
  # GNS3 server config (bind all, auth on, fixed console ports, projects path)
  - path: /home/gns3/.config/GNS3/gns3_server.conf
    owner: gns3:gns3
    permissions: '0644'
    content: |
      [Server]
      host = 0.0.0.0
      port = 3080
      auth = True
      user = gns3
      password = gns3
      projects_path = /home/gns3/projects
      console_start_port = 5000
      console_end_port   = 5999

  # Systemd unit for gns3server (robust PATH and docker group)
  - path: /etc/systemd/system/gns3server.service
    owner: root:root
    permissions: '0644'
    content: |
      [Unit]
      Description=GNS3 Server
      After=network-online.target
      Wants=network-online.target

      [Service]
      User=gns3
      Group=gns3
      WorkingDirectory=/home/gns3
      ExecStart=/usr/bin/python3 -m gns3server --config /home/gns3/.config/GNS3/gns3_server.conf
      Environment=PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin
      SupplementaryGroups=docker
      Restart=always
      RestartSec=2

      [Install]
      WantedBy=multi-user.target

runcmd:
  # Folders for projects & config
  - 'su - gns3 -c "mkdir -p /home/gns3/projects /home/gns3/.config/GNS3"'

  # Install Docker Engine from official repo
  - 'install -m 0755 -d /etc/apt/keyrings'
  - 'curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg'
  - 'chmod a+r /etc/apt/keyrings/docker.gpg'
  - 'bash -lc "echo \"deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable\" > /etc/apt/sources.list.d/docker.list"'
  - 'apt-get update'
  - 'apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin'
  - 'usermod -aG docker gns3'
  - 'systemctl enable --now docker'

  # Install uBridge (APT if available; else build from source)
  - 'apt-get install -y ubridge || true'
  - 'bash -lc "if ! command -v ubridge >/dev/null 2>&1; then apt-get install -y build-essential libpcap-dev cmake git && git clone https://github.com/GNS3/ubridge.git /opt/ubridge && cd /opt/ubridge && make && make install; fi"'
  - 'bash -lc "setcap cap_net_admin,cap_net_raw+eip $(command -v ubridge) || true"'

  # Clone and install gns3-server from the official repo (NOT pip package)
  - 'git clone https://github.com/GNS3/gns3-server.git /opt/gns3-server || true'
  - 'chown -R gns3:gns3 /opt/gns3-server'
  - 'su - gns3 -c "python3 -m pip install --user -r /opt/gns3-server/requirements.txt"'
  - 'su - gns3 -c "cd /opt/gns3-server && python3 setup.py install --user"'

  # Firewall: API and console range
  - 'ufw allow 3080/tcp || true'
  - 'ufw allow 5000:5999/tcp || true'
  - 'yes | ufw enable || true'

  # Enable the gns3server service
  - 'systemctl daemon-reload'
  - 'systemctl enable --now gns3server'

final_message: "GNS3 root VM initial provisioning complete."
EOF
```

## B2) `meta-data` (unique instance-id so cloud-init runs)

```bash
cat > ~/gns3-qemu/base/seed-init/meta-data <<'EOF'
instance-id: gns3-root-v1
local-hostname: gns3-root
EOF
```

## B3) Build the seed ISO

```bash
cd ~/gns3-qemu/base
hdiutil makehybrid -iso -joliet -default-volume-name cidata \
  -o seed-init.iso seed-init
```

---

# C) First boot (GUI once), bridged over Wi-Fi (en1)

> This is your proven working pattern. We’ll do GUI once so you can see cloud-init and verify everything.

```bash
cd ~/gns3-qemu/base

sudo qemu-system-aarch64 \
  -accel hvf \
  -machine virt,highmem=on \
  -cpu host \
  -smp 6 -m 8192 \
  -bios /opt/homebrew/share/qemu/edk2-aarch64-code.fd \
  -drive if=pflash,format=raw,unit=1,file=./vars.fd \
  -drive if=virtio,file=root.qcow2,format=qcow2 \
  -drive if=virtio,file=seed-init.iso,format=raw,readonly=on \
  -device virtio-gpu-pci \
  -device virtio-keyboard-pci \
  -device virtio-mouse-pci \
  -nic vmnet-bridged,ifname=en1,model=virtio-net-pci \
  -display cocoa
```

Inside the guest (after first boot completes):

```bash
# Login:
#   username: gns3
#   password: gns3

# Networking (bridged)
hostname -I           # expect a real LAN IP (from your hotspot/Wi-Fi)

# GNS3 server status
systemctl status gns3server --no-pager

# API reachable locally (auth required)
curl -u gns3:gns3 http://127.0.0.1:3080/v2/version

# Docker works without sudo
docker run --rm hello-world

# uBridge capabilities
which ubridge && getcap "$(command -v ubridge)"

# (Optional) console range is pinned
grep -E 'console_|port =' /home/gns3/.config/GNS3/gns3_server.conf
```

If all good, shut down cleanly to freeze the **root**:

```bash
sudo poweroff
```

---

# D) Run **two** VMs at once (overlays), bridged, no port forwards

Create two overlays:

```bash
cd ~/gns3-qemu/overlays

# D1) Create overlay disks (thin CoW on top of root)
qemu-img create -f qcow2 -F qcow2 -b ../base/root.qcow2 sA.qcow2
qemu-img create -f qcow2 -F qcow2 -b ../base/root.qcow2 sB.qcow2
```

Start **VM A** (headless, bridged Wi-Fi):

```bash
sudo qemu-system-aarch64 \
  -accel hvf -machine virt,highmem=on -cpu host \
  -smp 4 -m 4096 \
  -bios /opt/homebrew/share/qemu/edk2-aarch64-code.fd \
  -drive if=pflash,format=raw,unit=1,file=../base/vars.fd \
  -drive if=virtio,file=sA.qcow2,format=qcow2 \
  -nic vmnet-bridged,ifname=en1,model=virtio-net-pci \
  -nographic -daemonize -pidfile sA.pid -D sA.log
```

Start **VM B** (headless, bridged Wi-Fi):

```bash
sudo qemu-system-aarch64 \
  -accel hvf -machine virt,highmem=on -cpu host \
  -smp 4 -m 4096 \
  -bios /opt/homebrew/share/qemu/edk2-aarch64-code.fd \
  -drive if=pflash,format=raw,unit=1,file=../base/vars.fd \
  -drive if=virtio,file=sB.qcow2,format=qcow2 \
  -nic vmnet-bridged,ifname=en1,model=virtio-net-pci \
  -nographic -daemonize -pidfile sB.pid -D sB.log
```

Get each VM’s IP **from inside** the guest (console/SSH), or quickly attach once with GUI if needed.
(If you want painless SSH, it’s already installed. From your Mac: `ssh gns3@<VM_IP>` → password `gns3`.)

From each client computer, connect GNS3 GUI to each VM:

* **Host:** `<VM_A_IP>` and `<VM_B_IP>`
* **Port:** `3080`
* **Auth:** `gns3 / gns3`
* Add a Docker node and open its console — it should **immediately** connect to `<VM_IP>:<5xxx>` because:

  * socat is installed,
  * uBridge caps are set,
  * UFW already allows `5000–5999/tcp`.

Stop & clean up (when done testing):

```bash
cd ~/gns3-qemu/overlays
sudo kill "$(cat sA.pid)" "$(cat sB.pid)"
rm -f sA.pid sB.pid
# (keep sA.qcow2 / sB.qcow2 if you want to persist their changes; remove to reset)
```

---

## Notes & rationale

* **Wi-Fi bridging:** You already proved it works on your hotspot (`en1`). On campus Wi-Fi it can fail (policy blocks multiple MACs). Your flow avoids per-node port forwards entirely.
* **20 GB disk:** qcow2 is **thin**; 20 GB won’t be allocated up front. This lets more students run simultaneously. If labs pull many Docker images, you can bump to 30–40 GB later with `qemu-img resize` and a guest fs grow.
* **Official gns3-server repo:** cloud-init clones and installs from `/opt/gns3-server`, **not** pip. The systemd unit uses `python3 -m gns3server`.
* **Credentials:** `gns3:gns3` per your request.
* **Firewall:** `3080/tcp` + `5000–5999/tcp` opened once during provisioning.
* **Consoles:** pinning a port range plus installing `socat` + uBridge and setting caps ensures telnet consoles work immediately.
* **Docker:** from Docker’s official repository; `gns3` is in the `docker` group and the service has `SupplementaryGroups=docker`, so no permission dead-ends.

---

If everything here looks good, you’re ready to run these commands.
When you give me the 👍, I can also drop a **tiny bash spawner** that creates an overlay, launches bridged, pulls the VM’s IP (via SSH or a small helper), and prints the “connect to `<IP>:3080`” info—so you can spawn on the fly.
