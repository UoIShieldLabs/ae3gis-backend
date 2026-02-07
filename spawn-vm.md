```bash
# QEMU + Python
# brew install qemu python@3.12

# Make a working dir
mkdir -p ~/gns3-qemu-*/{base,overlays,seeds,logs}


# Ubuntu 22.04 LTS (ARM64) cloud image
curl -LO https://cloud-images.ubuntu.com/jammy/current/jammy-server-cloudimg-arm64.img
mv jammy-server-cloudimg-arm64.img gold.qcow2
qemu-img resize gold.qcow2 40G


cd ~/gns3-qemu-*/base


# copy writable UEFI vars file
# cp /opt/homebrew/share/qemu/edk2-aarch64-vars.fd ./vars.fd


mkdir -p ~/gns3-qemu-*/base/seed-init
```

Create ~/gns3-qemu/base/seed-init/user-data:
```bash
vim ~/gns3-qemu-*/base/seed-init/user-data
```
Paste this in
```yaml
#cloud-config
package_update: true
packages:
  - python3
  - python3-pip
  - qemu-system
  - ufw
users:
  - default
  - name: gns3
    groups: [sudo, docker]
    shell: /bin/bash
    sudo: ['ALL=(ALL) NOPASSWD:ALL']
runcmd:
  # Install gns3-server (PyPI works fine on ARM64)
  - 'su - gns3 -c "python3 -m pip install --user gns3-server"'

  # Create config with placeholder creds (we’ll overwrite per VM later)
  - 'su - gns3 -c "mkdir -p /home/gns3/.config/GNS3 /home/gns3/projects"'
  - 'bash -lc "cat >/home/gns3/.config/GNS3/gns3_server.conf <<EOF
[Server]
host = 0.0.0.0
port = 3080
auth = True
user = PLACEHOLDER_USER
password = PLACEHOLDER_PASS
projects_path = /home/gns3/projects
EOF"'

  # systemd service
  - 'bash -lc "cat >/etc/systemd/system/gns3server.service <<EOF
[Unit]
Description=GNS3 Server
After=network-online.target
Wants=network-online.target
[Service]
User=gns3
Group=gns3
ExecStart=/home/gns3/.local/bin/gns3server --config /home/gns3/.config/GNS3/gns3_server.conf
Restart=always
RestartSec=2
[Install]
WantedBy=multi-user.target
EOF"'
  - 'systemctl daemon-reload'
  - 'systemctl enable --now gns3server'

  # Open firewall for 3080 (adjust or remove if you’ll firewall at the Mac)
  - 'ufw allow 3080/tcp || true'
  - 'yes | ufw enable || true'

```


Create ~/gns3-qemu/base/seed-init/meta-data:
```bash
vim ~/gns3-qemu/base/seed-init/meta-data
```
paste this in
```yaml
instance-id: gns3-gold-initial
local-hostname: gns3-gold
```

Make the cidata ISO (macOS native):
```bash
cd ~/gns3-qemu/base
hdiutil makehybrid -iso -joliet -default-volume-name cidata \
  -o seed-init.iso seed-init
```

---

To run the base VM
```bash
cd ~/gns3-qemu/base

sudo qemu-system-aarch64 \
  -accel hvf \
  -machine virt,highmem=on \
  -cpu host \
  -smp 6 -m 8192 \
  -bios /opt/homebrew/share/qemu/edk2-aarch64-code.fd \
  -drive if=pflash,format=raw,unit=1,file=./vars.fd \
  -drive if=virtio,file=gold.qcow2,format=qcow2 \
  -drive if=virtio,file=seed-init.iso,format=raw,readonly=on \
  -device virtio-gpu-pci \
  -device virtio-keyboard-pci \
  -device virtio-mouse-pci \
  -nic vmnet-bridged,ifname=en1,model=virtio-net-pci \
  -nographic
```

To create overlay disks:
```bash
cd ~/gns3-qemu-B/overlays

qemu-img create -f qcow2 -F qcow2 -b ../base/gold.qcow2 sA.qcow2
qemu-img create -f qcow2 -F qcow2 -b ../base/gold.qcow2 sB.qcow2
```

To run overlays:
```bash
sudo qemu-system-aarch64 \
  -accel hvf -machine virt,highmem=on -cpu host \
  -smp 4 -m 4096 \
  -bios /opt/homebrew/share/qemu/edk2-aarch64-code.fd \
  -drive if=pflash,format=raw,unit=1,file=../base/vars.fd \
  -drive if=virtio,file=sB.qcow2,format=qcow2 \
  -nic vmnet-bridged,ifname=en1,model=virtio-net-pci \
  -nographic -pidfile sB.pid -D sB.log
```

Tun overlays without caching:
```bash
sudo qemu-system-aarch64 \
  -accel hvf -machine virt,highmem=on -cpu host \
  -smp 4 -m 4096 \
  -bios /opt/homebrew/share/qemu/edk2-aarch64-code.fd \
  -drive if=pflash,format=raw,unit=1,file=../base/vars.fd \
  -drive if=virtio,file=sA.qcow2,format=qcow2,cache=none,discard=unmap \
  -nic vmnet-bridged,ifname=en1,model=virtio-net-pci \
  -nographic -pidfile sA.pid -D sA.log
  ```



Install Docker:
```bash
# Add Docker's official GPG key:
sudo apt-get update
sudo apt-get install ca-certificates curl
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc

# Add the repository to Apt sources:
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu \
  $(. /etc/os-release && echo "${UBUNTU_CODENAME:-$VERSION_CODENAME}") stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt-get update

sudo apt-get install docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

sudo systemctl start docker

sudo systemctl status docker
```


Allow multiple ports in the firewall:
```bash
sudo sed -n '1,120p' /home/gns3/.config/GNS3/gns3_server.conf

sudo tee -a /home/gns3/.config/GNS3/gns3_server.conf >/dev/null <<'EOF'
# Restrict console port range so we can allow it in the firewall
console_start_port = 5000
console_end_port   = 6999
EOF

sudo systemctl restart gns3server

sudo apt update
sudo apt install -y socat

sudo ufw allow 5000:6999/tcp
sudo ufw status

```


Make machine ID unique for DHCP to assign different IPs:
```bash
# run this in the gold before powering it off for cloning
sudo truncate -s 0 /etc/machine-id
sudo rm -f /var/lib/dbus/machine-id
sudo ln -s /etc/machine-id /var/lib/dbus/machine-id
sudo poweroff
```


```
# Config
sudo -u gns3 mkdir -p /home/gns3/.config/GNS3 /home/gns3/projects
sudo tee /home/gns3/.config/GNS3/gns3_server.conf >/dev/null <<'EOF'
[Server]
host = 0.0.0.0
port = 3080
auth = True
user = gns3
password = gns3
projects_path = /home/gns3/projects
EOF
sudo chown -R gns3:gns3 /home/gns3/.config/GNS3 /home/gns3/projects

# Service uses the venv's python
sudo tee /etc/systemd/system/gns3server.service >/dev/null <<'EOF'
[Unit]
Description=GNS3 Server
After=network-online.target
Wants=network-online.target

[Service]
User=gns3
Group=gns3
WorkingDirectory=/home/gns3
ExecStart=/home/gns3/venv/bin/python -m gns3server --config /home/gns3/.config/GNS3/gns3_server.conf
Restart=always
RestartSec=2
Environment=PATH=/home/gns3/venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now gns3server.service
systemctl status gns3server --no-pager

```


Create and run Overlays

```bash
cd ~/gns3-qemu/overlays
qemu-img create -f qcow2 -F qcow2 -b ../base/root.qcow2 rootB.qcow2

hdiutil makehybrid -iso -joliet -default-volume-name cidata -o ~/gns3-qemu/seeds/seed-B.iso ~/gns3-qemu/seeds/seed-init-B

sudo qemu-system-aarch64 \
  -accel hvf -machine virt,highmem=on -cpu host \
  -smp 4 -m 4096 \
  -bios /opt/homebrew/share/qemu/edk2-aarch64-code.fd \
  -drive if=pflash,format=raw,unit=1,file=../base/vars.fd \
  -drive if=virtio,file=rootB.qcow2,format=qcow2,cache=none,discard=unmap \
  -drive if=virtio,file=../seeds/seed-B.iso,format=raw,readonly=on \
  -nic vmnet-bridged,ifname=en1,model=virtio-net-pci \
  -nographic
```

 sudo qemu-system-aarch64 \
  -accel hvf -machine virt,highmem=on -cpu host \
  -smp 4 -m 12288 \
  -bios /opt/homebrew/share/qemu/edk2-aarch64-code.fd \
  -drive if=pflash,format=raw,unit=1,file=../base/vars.fd \
  -drive if=virtio,file=root.qcow2,format=qcow2,cache=none,discard=unmap \
  -drive if=virtio,file=seed-init-3.iso,format=raw,readonly=on \
  -nic vmnet-bridged,ifname=en1,model=virtio-net-pci \
  -nographic



---

# Newly pasted

```bash
cd /Users/tberhanu@uidaho.edu/gns3-qemu && sudo qemu-system-aarch64     -accel hvf -machine virt,highmem=on -cpu host     -smp 4 -m 12288     -bios /opt/homebrew/share/qemu/edk2-aarch64-code.fd     -drive if=pflash,format=raw,unit=1,file=/Users/tberhanu@uidaho.edu/gns3-qemu/base/vars.fd     -drive if=virtio,file=/Users/tberhanu@uidaho.edu/gns3-qemu/overlays/overlay-4.qcow2,format=qcow2,cache=none,discard=unmap     -drive if=virtio,file=/Users/tberhanu@uidaho.edu/gns3-qemu/seeds/seed-4.iso,format=raw,readonly=on     -nic vmnet-bridged,ifname=en1,model=virtio-net-pci,mac=52:54:00:12:34:36     -uuid FB2D2ED0-04C9-4959-844E-498E23A41E59     -name overlay-4     -nographic
```
