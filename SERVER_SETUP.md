# Running RAX Surgicals Outreach on an online server

On a server the software runs 24 hours a day: emails go out during the recipient's office hours even while you sleep, and you can open the dashboard on your phone.

## What you need

- **A small Linux VPS** (Ubuntu 24.04), for example from Hetzner, DigitalOcean, Vultr or Contabo. 1 GB of RAM is enough; it costs about 4 to 6 dollars a month.
- **A subdomain**, such as `outreach.raxsurgicals.com`. Add a DNS **A record** that points it to the server's IP address.

Note: cPanel shared hosting cannot run this software, because it does not let a program keep running. You need a VPS.

## Steps (on the server, over SSH)

```bash
# 1. Python and Caddy (Caddy sets up the HTTPS certificate by itself)
sudo apt update && sudo apt install -y python3 caddy unzip

# 2. The software files
sudo mkdir -p /opt/rax-surgicals-outreach && sudo chown $USER /opt/rax-surgicals-outreach
#   upload the zip from your PC (for example with WinSCP, or: scp RAX_Surgicals_Outreach_v1.0.zip user@SERVER:/opt/rax-surgicals-outreach/)
cd /opt/rax-surgicals-outreach && unzip RAX_Surgicals_Outreach_v1.0.zip && cp -r RAX_Surgicals_Outreach/. . && rm -r RAX_Surgicals_Outreach RAX_Surgicals_Outreach_v1.0.zip

# 3. Login password (8 or more characters)
python3 start.py --set-password

# 4. Keep it running, also after a restart
sudo tee /etc/systemd/system/rax-surgicals-outreach.service >/dev/null <<EOF
[Unit]
Description=RAX Surgicals Outreach
After=network-online.target

[Service]
User=$USER
WorkingDirectory=/opt/rax-surgicals-outreach
ExecStart=/usr/bin/python3 start.py --server --host 127.0.0.1 --port 8765
Restart=always

[Install]
WantedBy=multi-user.target
EOF
sudo systemctl enable --now rax-surgicals-outreach

# 5. HTTPS (write your own subdomain)
sudo tee /etc/caddy/Caddyfile >/dev/null <<EOF
outreach.raxsurgicals.com {
    reverse_proxy 127.0.0.1:8765 {
        header_up X-Forwarded-Proto https
    }
}
EOF
sudo systemctl reload caddy
```

Now open `https://outreach.raxsurgicals.com` in your browser and log in with the password. On a server the dashboard has no power button; `systemctl` stops and starts the software.

## Moving your PC data to the server

If you already worked on the PC:

1. On the PC, stop the software with the power button in the dashboard.
2. On the server: `sudo systemctl stop rax-surgicals-outreach`
3. Copy the PC's `data` folder to `/opt/rax-surgicals-outreach/data` on the server (for example with WinSCP).
4. On the server: `sudo systemctl start rax-surgicals-outreach`

Or, on the PC, use **Settings → Backup → Download a backup now**, and in the server's dashboard use **Restore from a backup file**.

Run the software in one place at a time, on the PC or on the server. Running both could send two emails to the same lead. (A second copy that uses the same `data` folder does not send by itself, but a PC and a server have separate folders and cannot see each other.) If the PC starts RAX Surgicals Outreach with Windows, turn that off in **Settings → Sending and safety**, or uninstall it from Windows **Settings → Apps**.

## Installing a new version

```bash
sudo systemctl stop rax-surgicals-outreach
cd /opt/rax-surgicals-outreach && unzip -o RAX_Surgicals_Outreach_v1.0.zip && cp -r RAX_Surgicals_Outreach/. . && rm -r RAX_Surgicals_Outreach RAX_Surgicals_Outreach_v1.0.zip
sudo systemctl start rax-surgicals-outreach
```

The zip has no `data` folder, so your data stays as it is. Data from an older version is upgraded automatically, and a copy of it is kept in `data/backups` first.

A server set up with version 2.1 or earlier (when the software was called RAX Outreach) uses the folder `/opt/rax-outreach` and the service `rax-outreach`. Keep those names: write them instead of `/opt/rax-surgicals-outreach` and `rax-surgicals-outreach` in the commands on this page.

## Useful commands

```bash
sudo systemctl status rax-surgicals-outreach    # is it running?
sudo journalctl -u rax-surgicals-outreach -n 50 # the last messages
sudo systemctl restart rax-surgicals-outreach   # after copying new files
ls /opt/rax-surgicals-outreach/data/backups      # the daily automatic backups
```

## Security

- The software only listens on `127.0.0.1`; the outside world reaches it only through Caddy over HTTPS.
- `--server` mode does not start without a password.
- After 8 wrong passwords, logging in is blocked for 15 minutes.
- Use an SSH key instead of a password for the server, and run `sudo apt upgrade` from time to time.
