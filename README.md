# 🛡️ aptsible – Apt PatchPanel

A lightweight, web-based patch management tool for Ubuntu and Debian servers — powered by **Ansible** as the backend interface.

Manage your entire server fleet from a clean web UI: check for available updates, select packages, and trigger installations — all in your browser, with live console output streaming in real time.

> **Language note:** The UI is in German. Contributions for translations are welcome!

---

## ✨ Features

- **Inventory from Ansible** — reads `/etc/ansible/hosts` automatically; no separate host configuration needed
- **Collapsible group view** — servers are organized by Ansible inventory groups (e.g. `[webservers]`, `[databases]`)
- **Per-host update check** — runs `apt list --upgradable` via Ansible ad-hoc commands over SSH
- **Selective package installation** — choose all or specific packages per host before installing
- **Live console output** — installation progress streams in real time via Server-Sent Events (SSE)
- **OS version display** — shows Ubuntu/Debian version for each host in the table
- **Automatic background checks** — configurable interval (default: every 24 h); cached status shown immediately on page load
- **Auto-refresh UI** — web interface refreshes host status every 60 seconds automatically
- **Update history** — all installation actions are logged to a local SQLite database with full output, including which user triggered the update
- **Login protection** — PAM authentication using Linux system users; optionally restrict access to a specific Linux group
- **HTTPS support** — self-signed certificate generated automatically by the installer, or bring your own
- **Easy configuration** — single `config.ini` file for port, SSL, auth group, Ansible user, inventory path, and check interval
- **Systemd service** — runs as a background service with auto-restart

---

## 📸 Screenshots

<details>
<summary>Main view — host table with collapsible groups</summary>

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ 🛡 aptsible  Apt PatchPanel   5 Server   ⟳ nächster Check: in 23h 14m      │
│                         [42s] [Alle prüfen]  [Historie]  👤 admin ⏻        │
├─────────────────────────────────────────────────────────────────────────────┤
│ ▾  webservers                                  2 ▲  1 ✓  3 Hosts           │
│ ──────────────────────────────────────────────────────────────────────────  │
│     Status  │ Server        │ Betriebssystem      │ Status     │ Geprüft    │
│  ✅         │ web01         │ Ubuntu 22.04.4 LTS  │ Aktuell    │ vor 2 Min. │[Prüfen] │
│  🔴         │ web02         │ Ubuntu 22.04.4 LTS  │ 3 Updates  │ vor 2 Min. │[Updates]│
│  ⚠️         │ web03         │ Debian 12 bookworm  │ Fehler     │ vor 2 Min. │[Prüfen] │
│                                                                             │
│ ▾  databases                                   1 ✓  2 Hosts               │
│  ✅         │ db01          │ Ubuntu 20.04.6 LTS  │ Aktuell    │ vor 1 Std. │[Prüfen] │
│  ⚪         │ db02          │ —                   │ Ungeprüft  │ —          │[Prüfen] │
└─────────────────────────────────────────────────────────────────────────────┘
```
</details>

---

## 🔧 Requirements

On the **management server** (where aptsible runs):

| Requirement | Version | Install |
|---|---|---|
| Python 3 | ≥ 3.9 | `sudo apt install python3 python3-pip` |
| Ansible | any | `sudo apt install ansible` |
| OpenSSL | any | `sudo apt install openssl` |

On the **managed hosts** (servers being patched):

- Ubuntu 18.04+ or Debian 10+ (anything with `apt`)
- SSH access configured in Ansible inventory
- SSH key-based authentication set up for the Ansible user

---

## 🚀 Quick Start

### 1. Clone the repository

```bash
git clone https://github.com/YOUR_USERNAME/aptsible.git
cd aptsible
```

### 2. Run the installer

```bash
sudo bash install.sh
```

The installer will interactively ask you about:
- **HTTPS** — generate a self-signed certificate or use HTTP
- **Port** — default is `5000`

It will then:
- Copy files to `/opt/aptsible/`
- Install Python dependencies via a virtual environment (`flask`, `apscheduler`, `python3-pam`)
- Generate a secure random session key
- Set up and start a `systemd` service (`aptsible`)

### 3. Open the web interface

```
http://YOUR-SERVER-IP:5000
```
(or `https://` if you enabled SSL)

**Login** with any Linux system user account. To restrict access to a specific group, see [Configuration](#configuration).

---

## ⚙️ Configuration

Edit `/opt/aptsible/config.ini`, then restart the service:

```bash
sudo systemctl restart aptsible
```

```ini
[server]
port = 5000           # Port to listen on
host = 0.0.0.0        # 0.0.0.0 = all interfaces, 127.0.0.1 = local only

[ssl]
enabled = false       # Set to true to enable HTTPS
certfile = /opt/aptsible/ssl/cert.pem
keyfile  = /opt/aptsible/ssl/key.pem

[auth]
enabled = true        # Login required (PAM / Linux users)
allowed_group =       # Restrict to this Linux group (empty = all users)
                      # Create group: sudo groupadd aptsible
                      # Add user:     sudo usermod -aG aptsible username
secret_key = ...      # Auto-generated by installer – do not change

[ansible]
inventory = /etc/ansible/hosts   # Path to Ansible inventory file or directory
                                  # Example: inventory = /home/user/ansible/hosts
user =                            # SSH user for Ansible (empty = system default)
                                  # Example: user = deploy

[check]
interval_hours = 24   # Auto-check interval in hours (0 = disabled)
```

### Restricting login to a specific group

```bash
# Create a group
sudo groupadd aptsible

# Add users
sudo usermod -aG aptsible alice
sudo usermod -aG aptsible bob

# Set in config.ini
allowed_group = aptsible
```

---

## 🔄 Updating

```bash
cd aptsible              # your cloned repo directory
git pull                 # fetch latest changes

# Copy only the application files – NOT config.ini (keep your settings!)
sudo cp app.py /opt/aptsible/
sudo cp -r templates/ /opt/aptsible/

sudo systemctl restart aptsible
```

> ⚠️ **Never overwrite `/opt/aptsible/config.ini`** — it contains your generated `secret_key` and local settings.

---

## 📁 File Structure

```
aptsible/
├── app.py                  # Flask backend – API + SSE + scheduler
├── config.ini              # Configuration template (PLACEHOLDER secret_key)
├── install.sh              # Interactive installer script
├── requirements.txt        # Python dependencies
├── aptsible.service        # Systemd unit file (reference only)
└── templates/
    ├── index.html          # Main web UI (Bootstrap 5, accordion table)
    └── login.html          # Login page
```

After installation, the live config lives in `/opt/aptsible/config.ini`.

---

## 🗄️ Data & Database

aptsible stores state in a local SQLite database at `/opt/aptsible/aptsible.db`:

- **`host_status`** — cached update check results (status, package list, OS info, timestamp)
- **`history`** — log of all installation runs with full Ansible output and the Linux user who triggered the update

The database is created automatically on first run.

---

## 🔐 Security Notes

- The application runs as `root` (required for Ansible and PAM)
- **Only expose to a trusted network** — there is no rate limiting on the login form
- For internet-facing deployments, consider putting it behind a reverse proxy (nginx/Caddy) with an additional auth layer
- The auto-generated `secret_key` in `config.ini` secures browser sessions — keep this file private

---

## 🏗️ Tech Stack

| Component | Technology |
|---|---|
| Web framework | [Flask](https://flask.palletsprojects.com/) (Python) |
| Live output | Server-Sent Events (SSE) |
| Automation backend | [Ansible](https://www.ansible.com/) ad-hoc commands |
| Authentication | Linux PAM (`python3-pam` via apt) |
| Background scheduler | [APScheduler](https://apscheduler.readthedocs.io/) |
| Database | SQLite (via Python `sqlite3`) |
| Frontend | [Bootstrap 5](https://getbootstrap.com/) + Bootstrap Icons |
| Service management | systemd |

---

## 🤝 Contributing

Pull requests and issues are welcome! Some ideas for future improvements:

- [ ] English UI / i18n support
- [ ] Reboot tracking / reboot-required indicator
- [ ] Email/Slack notifications when updates are found
- [ ] Support for other package managers (yum/dnf for RHEL/Rocky)
- [ ] Role-based access (read-only vs. admin)
- [ ] Dark mode

---

## 📄 License

MIT License — free to use, modify, and distribute.

---

*Built with ❤️ and Ansible. Contributions welcome.*
