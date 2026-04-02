#!/bin/bash
# ═══════════════════════════════════════════════════════════════
#  patchsible – Linux Patchmanagement — Installationsscript
#  Voraussetzungen: Ubuntu / Debian, Python 3, openssl
# ═══════════════════════════════════════════════════════════════
set -e

INSTALL_DIR="/opt/patchsible"
SERVICE_NAME="patchsible"

# Wird in den Abschnitten C und E befüllt
ANSIBLE_RUN_USER=""
SERVICE_USER="root"  # Systemd User= – wird auf patchsible gesetzt wenn Benutzer angelegt wird
_newpass=""          # Passwort des neu angelegten patchsible-Benutzers (für Abschluss-Anzeige)
_user_created=false  # Wurde ein neuer Benutzer angelegt?

echo ""
echo "════════════════════════════════════════════════"
echo "   patchsible – Linux Patchmanagement · Installation     "
echo "════════════════════════════════════════════════"
echo ""

# ── Language Selection ────────────────────────────────────────────────────────
echo "   [1]  Deutsch"
echo "   [2]  English"
echo ""
read -r -p "   Language / Sprache [1/2, Enter = 1]: " _langchoice
_langchoice="${_langchoice:-1}"
if [[ "$_langchoice" == "2" ]]; then
  _LANG="en"
else
  _LANG="de"
fi
echo ""

# ── i18n helper ───────────────────────────────────────────────────────────────
# Usage: msg "de string" "en string"  → prints the correct one
msg() {
  if [[ "$_LANG" == "en" ]]; then echo "$2"; else echo "$1"; fi
}
# Usage: prompt_yn "de question" "en question"  → sets $_ans
prompt_yn() {
  local q
  if [[ "$_LANG" == "en" ]]; then q="$2"; else q="$1"; fi
  read -r -p "$q" _ans
}

# ── Root-Check ──────────────────────────────────────────────────────────────
if [ "$EUID" -ne 0 ]; then
  msg "❌  Bitte als root ausführen:  sudo bash install.sh" \
      "❌  Please run as root:  sudo bash install.sh"
  exit 1
fi

# ══ A. Ansible prüfen / installieren ═══════════════════════════════════════
echo "── Ansible ────────────────────────────────────────────────────────────"
if command -v ansible &>/dev/null; then
  echo "✓  $(ansible --version 2>/dev/null | head -1)"
else
  msg "⚠  Ansible ist nicht installiert." "⚠  Ansible is not installed."
  echo ""
  prompt_yn "   Jetzt über apt installieren? [J/n]: " "   Install now via apt? [Y/n]: "
  if [[ "${_ans,,}" != "n" ]]; then
    msg "   Aktualisiere Paketlisten …" "   Updating package lists …"
    apt-get update -q
    msg "   Installiere ansible …" "   Installing ansible …"
    apt-get install -y ansible -q
    echo "   ✓ $(ansible --version 2>/dev/null | head -1)"
  else
    echo ""
    msg "   ⚠  Ohne Ansible ist kein Betrieb möglich." "   ⚠  Ansible is required for operation."
    msg "      Nachinstallieren:  sudo apt install ansible" "      Install manually:  sudo apt install ansible"
    msg "      Danach install.sh erneut ausführen." "      Then run install.sh again."
  fi
fi

# ══ B. Weitere Abhängigkeiten ══════════════════════════════════════════════
echo ""
msg "── Abhängigkeiten ─────────────────────────────────────────────────────" "── Dependencies ──────────────────────────────────────────────────────"
_missing=0
for tool in python3 openssl; do
  if command -v "$tool" &>/dev/null; then
    echo "✓  $tool"
  else
    msg "❌  '$tool' fehlt  →  sudo apt install $tool" "❌  '$tool' missing  →  sudo apt install $tool"
    _missing=1
  fi
done
if [ "$_missing" -eq 1 ]; then
  echo ""
  msg "Bitte fehlende Pakete installieren und install.sh erneut starten." "Please install missing packages and run install.sh again."
  exit 1
fi

# ══ C. Ansible-Benutzer ════════════════════════════════════════════════════
echo ""
msg "── Dienst- und Ansible-Benutzer ───────────────────────────────────────" "── Service and Ansible User ───────────────────────────────────────────"
echo ""

# Aufrufenden Nutzer ermitteln (wer hat sudo benutzt?)
if [ -n "$SUDO_USER" ] && [ "$SUDO_USER" != "root" ]; then
  _caller="$SUDO_USER"
else
  _caller="root"
fi

if [[ "$_LANG" == "en" ]]; then
  echo "   How should patchsible run?"
  echo ""
  echo "   [1]  As current user '${_caller}'"
  echo "        → Service runs as '${_caller}', uses existing SSH keys and sudo config."
  echo "        → Recommended if '${_caller}' already has Ansible access to target hosts."
  echo ""
  echo "   [2]  Create dedicated user 'patchsible' (recommended for production)"
  echo "        → New Linux user 'patchsible' is created with a random password."
  echo "        → The service runs as 'patchsible' (not root)."
  echo "        → /opt/patchsible is owned by 'patchsible'."
  echo "        → 'patchsible' is added to groups: sudo, shadow, patchsible."
  echo "        → SSH key is generated; you copy it to target hosts afterwards."
  echo "        → Web login: all users in group 'patchsible' can log in."
else
  echo "   Wie soll patchsible ausgeführt werden?"
  echo ""
  echo "   [1]  Als aktueller Benutzer '${_caller}'"
  echo "        → Dienst läuft als '${_caller}', nutzt vorhandene SSH-Keys und sudo-Konfiguration."
  echo "        → Empfohlen wenn '${_caller}' bereits Ansible-Zugriff auf die Zielhosts hat."
  echo ""
  echo "   [2]  Dedizierten Benutzer 'patchsible' anlegen (empfohlen für Produktion)"
  echo "        → Neuer Linux-Benutzer 'patchsible' wird mit Zufallspasswort erstellt."
  echo "        → Der Dienst läuft als 'patchsible' (nicht als root)."
  echo "        → /opt/patchsible gehört 'patchsible'."
  echo "        → 'patchsible' wird den Gruppen sudo, shadow und patchsible hinzugefügt."
  echo "        → SSH-Key wird generiert; anschließend auf Zielhosts verteilen."
  echo "        → Web-Login: alle Benutzer der Gruppe 'patchsible' können sich anmelden."
fi
echo ""
prompt_yn "   Wahl [1/2, Enter = 1]: " "   Choice [1/2, Enter = 1]: "
_uchoice="${_ans:-1}"

if [[ "$_uchoice" == "2" ]]; then
  ANSIBLE_RUN_USER="patchsible"
  SERVICE_USER="patchsible"

  if id "patchsible" &>/dev/null; then
    msg "   ✓  Benutzer 'patchsible' existiert bereits." "   ✓  User 'patchsible' already exists."
  else
    msg "   Lege Benutzer 'patchsible' an …" "   Creating user 'patchsible' …"
    useradd -m -s /bin/bash -c "patchsible Ansible-Dienstbenutzer" patchsible

    # Zufälliges sicheres Passwort
    _newpass=$(< /dev/urandom tr -dc 'A-Za-z0-9!@#%^*' 2>/dev/null | head -c 20 || true)
    echo "patchsible:${_newpass}" | chpasswd
    _user_created=true

    echo ""
    echo "   ┌──────────────────────────────────────────────────────┐"
    if [[ "$_LANG" == "en" ]]; then
      printf  "   │  Password for 'patchsible':   %-24s│\n" "${_newpass}"
      echo   "   │  ▶ Please note it down — shown again at the end.  │"
    else
      printf  "   │  Passwort für 'patchsible':  %-26s│\n" "${_newpass}"
      echo   "   │  ▶ Notieren — wird am Ende nochmals angezeigt.    │"
    fi
    echo   "   └──────────────────────────────────────────────────────┘"
    echo ""
  fi

  # sudo: für ansible --become (Privilege Escalation auf Zielsystemen)
  usermod -aG sudo patchsible
  msg "   ✓  'patchsible' → Gruppe sudo (für ansible --become)" \
      "   ✓  'patchsible' → group sudo (for ansible --become)"

  # shadow: für PAM-Authentifizierung im Web-Login
  usermod -aG shadow patchsible
  msg "   ✓  'patchsible' → Gruppe shadow (für Web-Login PAM)" \
      "   ✓  'patchsible' → group shadow (for web login PAM)"

else
  ANSIBLE_RUN_USER="$_caller"
  SERVICE_USER="$_caller"
  msg "   → Dienst und Ansible laufen als Benutzer: ${ANSIBLE_RUN_USER}" \
      "   → Service and Ansible run as user: ${ANSIBLE_RUN_USER}"
fi

# ══ D. Gruppe 'patchsible' – Web-UI-Zugang ═════════════════════════════════
echo ""
msg "── Gruppe 'patchsible' (Web-UI-Login) ─────────────────────────────────" "── Group 'patchsible' (Web-UI Login) ────────────────────────────────────"

if getent group patchsible &>/dev/null; then
  msg "   ✓  Gruppe 'patchsible' existiert bereits." "   ✓  Group 'patchsible' already exists."
else
  groupadd patchsible
  msg "   ✓  Gruppe 'patchsible' angelegt." "   ✓  Group 'patchsible' created."
fi

# Ansible-Benutzer in die patchsible-Gruppe aufnehmen
usermod -aG patchsible "$ANSIBLE_RUN_USER"
msg "   ✓  '${ANSIBLE_RUN_USER}' → Gruppe 'patchsible' hinzugefügt" "   ✓  Added '${ANSIBLE_RUN_USER}' → group 'patchsible'"
msg "   ℹ  Weitere Web-UI-Nutzer hinzufügen:" "   ℹ  Add more Web-UI users:"
echo "      sudo usermod -aG patchsible <benutzername>"

# ══ 1. Verzeichnis & Dateien ═══════════════════════════════════════════════
echo ""
msg "📁  Erstelle ${INSTALL_DIR} …" "📁  Creating ${INSTALL_DIR} …"
mkdir -p "$INSTALL_DIR"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cp -r "$SCRIPT_DIR/." "$INSTALL_DIR/"
chmod +x "$INSTALL_DIR/install.sh"

# Verzeichnis-Eigentümer auf den Dienst-Benutzer setzen
if [ "$SERVICE_USER" != "root" ]; then
  chown -R "${SERVICE_USER}:${SERVICE_USER}" "$INSTALL_DIR"
  chmod 755 "$INSTALL_DIR"
  msg "   ✓  ${INSTALL_DIR} → Eigentümer: ${SERVICE_USER}" \
      "   ✓  ${INSTALL_DIR} → owner: ${SERVICE_USER}"
fi

# config.ini: Ansible-Benutzer eintragen
if [ "$ANSIBLE_RUN_USER" != "root" ]; then
  sed -i "s|^user = .*|user = ${ANSIBLE_RUN_USER}|" "$INSTALL_DIR/config.ini" 2>/dev/null || true
fi

# config.ini: Web-UI auf Gruppe 'patchsible' beschränken + Auth aktivieren
sed -i "s|^allowed_group = .*|allowed_group = patchsible|" "$INSTALL_DIR/config.ini" 2>/dev/null || true
# Auth-Sektion: enabled = true (nur in [auth]-Block ändern)
sed -i "/^\[auth\]/,/^\[/{s|^enabled = .*|enabled = true|}" "$INSTALL_DIR/config.ini" 2>/dev/null || true

# Set language in config.ini
sed -i "s|^language = .*|language = ${_LANG}|" "$INSTALL_DIR/config.ini" 2>/dev/null || true

msg "   ✓  config.ini: Ansible-Benutzer=${ANSIBLE_RUN_USER}, allowed_group=patchsible" "   ✓  config.ini: Ansible user=${ANSIBLE_RUN_USER}, allowed_group=patchsible"

# ══ 2. Python-Pakete in virtualenv ════════════════════════════════════════
echo ""
msg "📦  Erstelle Python-Umgebung (venv) und installiere Pakete …" "📦  Creating Python environment (venv) and installing packages …"
apt-get install -y python3-venv python3-pam -q
python3 -m venv --system-site-packages "$INSTALL_DIR/venv"
"$INSTALL_DIR/venv/bin/pip" install --quiet --upgrade pip
# python-pam wird NICHT per pip installiert – auf Ubuntu 24.04 schlägt der
# Build still fehl (kein passendes Wheel). Stattdessen:
#   1. python3-pam per apt (oben) + system-site-packages im venv
#   2. pamela per pip als universeller Fallback (reines Python, kein Build nötig)
"$INSTALL_DIR/venv/bin/pip" install --quiet flask apscheduler pamela

# ── PAM-Verfügbarkeit im venv prüfen ──────────────────────────────────────
_pam_check='import importlib; [importlib.import_module(m) for m in ("pam","pamela") if importlib.util.find_spec(m)]'
if "$INSTALL_DIR/venv/bin/python3" -c "import pam" 2>/dev/null; then
  echo "   OK (PAM ✓ – python3-pam)"
elif "$INSTALL_DIR/venv/bin/python3" -c "import pamela" 2>/dev/null; then
  echo "   OK (PAM ✓ – pamela)"
else
  # Letzter Versuch: pam.py aus System-Python direkt ins venv kopieren
  _sys_pam=$(python3 -c "import pam, os; print(pam.__file__)" 2>/dev/null || true)
  _venv_site=$(ls -d "$INSTALL_DIR/venv/lib/python3."*/site-packages 2>/dev/null | head -1)
  if [ -n "$_sys_pam" ] && [ -n "$_venv_site" ]; then
    cp "$_sys_pam" "$_venv_site/"
    msg "   ℹ  pam.py aus System-Python in venv kopiert." "   ℹ  Copied pam.py from system Python into venv."
    echo "   OK (PAM ✓ – kopiert)"
  else
    echo ""
    msg "   ⚠  PAM-Modul konnte nicht eingebunden werden." "   ⚠  PAM module could not be loaded."
    msg "      Login funktioniert erst nach manuellem Fix:" "      Login requires manual fix first:"
    echo "      sudo apt install python3-pam"
    echo "      sudo systemctl restart $SERVICE_NAME"
    echo ""
  fi
fi

# ══ 3. Session-Schlüssel generieren ═══════════════════════════════════════
if grep -q "PLACEHOLDER" "$INSTALL_DIR/config.ini" 2>/dev/null; then
  echo ""
  msg "🔑  Generiere sicheren Session-Schlüssel …" "🔑  Generating secure session key …"
  _secret=$(python3 -c "import secrets; print(secrets.token_hex(32))")
  sed -i "s/secret_key = PLACEHOLDER/secret_key = ${_secret}/" "$INSTALL_DIR/config.ini"
  echo "   OK"
fi

# ══ F. Ansible Inventory ═══════════════════════════════════════════════════
echo ""
msg "── Ansible Inventory ──────────────────────────────────────────────────" "── Ansible Inventory ──────────────────────────────────────────────────"

_STD_HOSTS="/etc/ansible/hosts"
_APT_INV="/etc/ansible/hosts.patchsible.ini"
_USE_INVENTORY=""

if [ -f "$_STD_HOSTS" ]; then
  msg "   ✓  Standard-Inventory gefunden: ${_STD_HOSTS}" "   ✓  Standard inventory found: ${_STD_HOSTS}"
  echo ""
  msg "   [1]  ${_STD_HOSTS} direkt verwenden" "   [1]  Use ${_STD_HOSTS} directly"
  msg "   [2]  Eigenes Inventory anlegen: ${_APT_INV}" "   [2]  Create own inventory: ${_APT_INV}"
  msg "        (Gruppen können aus der Standard-hosts importiert werden)" "        (Groups can be imported from standard hosts)"
  echo ""
  prompt_yn "   Wahl [1/2, Enter = 1]: " "   Choice [1/2, Enter = 1]: "
  _invchoice="${_ans:-1}"

  if [[ "$_invchoice" == "2" ]]; then
    # ── Eigenes Inventory anlegen ─────────────────────────────────────
    mkdir -p /etc/ansible

    # Versuche Gruppen aus der bestehenden hosts-Datei zu lesen
    _do_import=false
    if command -v ansible-inventory &>/dev/null; then
      echo ""
      prompt_yn "   Hosts aus ${_STD_HOSTS} importieren? [J/n]: " "   Import hosts from ${_STD_HOSTS}? [Y/n]: "
      if [[ "${_ans,,}" != "n" ]]; then
        _do_import=true
      fi
    fi

    if [ "$_do_import" = true ]; then
      # Gruppen aus der hosts-Datei lesen
      # Methode 1: ansible-inventory --list (JSON)
      # Methode 2: Fallback – direktes INI-Parsing
      _group_data=""

      # --- Methode 1: ansible-inventory ---
      if command -v ansible-inventory &>/dev/null; then
        _group_data=$(ansible-inventory --list -i "$_STD_HOSTS" 2>/dev/null | python3 -c "
import sys, json
try:
    inv = json.load(sys.stdin)
    all_hosts = set(inv.get('_meta', {}).get('hostvars', {}).keys())
    for special in ('all', 'ungrouped'):
        if special in inv and isinstance(inv[special], dict):
            all_hosts.update(inv[special].get('hosts', []))
    for k, v in inv.items():
        if k in ('_meta', 'all', 'ungrouped'):
            continue
        if isinstance(v, dict) and v.get('hosts'):
            all_hosts.update(v['hosts'])
    for k in sorted(inv):
        if k in ('_meta', 'all', 'ungrouped'):
            continue
        if k in all_hosts:
            continue
        v = inv[k]
        if isinstance(v, dict) and v.get('hosts'):
            print(f'{k}|{len(v[\"hosts\"])}|{\",\".join(v[\"hosts\"])}')
except Exception:
    sys.exit(1)
" 2>/dev/null || true)
      fi

      # --- Methode 2: Fallback – direktes INI-Parsing ---
      if [ -z "$_group_data" ] && [ -f "$_STD_HOSTS" ]; then
        _group_data=$(python3 -c "
import sys
groups = {}
current = None
for line in open(sys.argv[1]):
    line = line.strip()
    if not line or line.startswith('#') or line.startswith(';'):
        continue
    if line.startswith('['):
        name = line.strip('[]').strip()
        if ':' in name:
            current = None
            continue
        if name.lower() in ('all', 'ungrouped'):
            current = None
            continue
        current = name
        if current not in groups:
            groups[current] = []
        continue
    if current is not None:
        host = line.split()[0]
        host = host.split('#')[0].strip()
        if host:
            groups[current].append(host)
for g in sorted(groups):
    if groups[g]:
        print(f'{g}|{len(groups[g])}|{\",\".join(groups[g])}')
" "$_STD_HOSTS" 2>/dev/null || true)
      fi

      if [ -n "$_group_data" ]; then
        # Gruppen anzeigen
        echo ""
        msg "   Gefundene Gruppen:" "   Found groups:"
        _gnames=()
        _ghosts=()
        _gi=0
        while IFS='|' read -r _gname _gcount _gmembers; do
          _gi=$((_gi + 1))
          # Hosts sind kommagetrennt – für Anzeige ersten Host zeigen
          _disp=$(echo "$_gmembers" | cut -d',' -f1)
          [ "$_gcount" -gt 1 ] 2>/dev/null && _disp="${_disp}, ..."
          echo "   [${_gi}]  ${_gname}  (${_gcount} Hosts: ${_disp})"
          _gnames+=("$_gname")
          _ghosts+=("$_gmembers")
        done <<< "$_group_data"

        echo ""
        prompt_yn "   Alle Gruppen importieren? [J/n]: " "   Import all groups? [Y/n]: "
        if [[ "${_ans,,}" != "n" ]]; then
          _selected=("${_gnames[@]}")
        else
          echo ""
          msg "   Nummern der gewünschten Gruppen eingeben (kommagetrennt, z.B. 1,3):" "   Enter numbers of desired groups (comma-separated, e.g. 1,3):"
          read -r _sel
          _selected=()
          IFS=',' read -ra _nums <<< "$_sel"
          for _n in "${_nums[@]}"; do
            _n=$(echo "$_n" | tr -d ' ')
            if [[ "$_n" =~ ^[0-9]+$ ]] && [ "$_n" -ge 1 ] && [ "$_n" -le "${#_gnames[@]}" ]; then
              _selected+=("${_gnames[$((_n - 1))]}")
            fi
          done
        fi

        # Inventory-Datei zusammenbauen
        {
          echo "# patchsible Inventory"
          echo "# Erstellt am $(date '+%Y-%m-%d %H:%M')"
          echo "#"
          echo "# Importiert aus: ${_STD_HOSTS}"
          echo ""
          for _sg in "${_selected[@]}"; do
            # Gruppe und ihre Hosts finden
            for _j in "${!_gnames[@]}"; do
              if [ "${_gnames[$_j]}" = "$_sg" ]; then
                echo "[${_sg}]"
                echo "${_ghosts[$_j]}" | tr ',' '\n'
                echo ""
                break
              fi
            done
          done
          echo "[all:vars]"
          echo "ansible_user = ${ANSIBLE_RUN_USER}"
        } > "$_APT_INV"

        msg "   ✓  ${#_selected[@]} Gruppe(n) importiert → ${_APT_INV}" "   ✓  ${#_selected[@]} group(s) imported → ${_APT_INV}"
      else
        msg "   ⚠  Keine Gruppen im Inventory gefunden." "   ⚠  No groups found in inventory."
        _do_import=false
      fi
    fi

    # Falls kein Import: leeres Inventory mit Beispiel anlegen
    if [ "$_do_import" = false ]; then
      cat > "$_APT_INV" << 'INVEOF'
# patchsible Inventory
# Hosts und Gruppen hier eintragen
#
# Beispiel:
# [webserver]
# server1.example.com
# server2.example.com
#
# [database]
# db1.example.com

INVEOF
      echo "[all:vars]" >> "$_APT_INV"
      echo "ansible_user = ${ANSIBLE_RUN_USER}" >> "$_APT_INV"
      msg "   ✓  Leeres Inventory angelegt: ${_APT_INV}" "   ✓  Empty inventory created: ${_APT_INV}"
    fi

    # Inventory in config.ini eintragen
    sed -i "s|^inventory = .*|inventory = ${_APT_INV}|" "$INSTALL_DIR/config.ini" 2>/dev/null || true
    _USE_INVENTORY="$_APT_INV"
    msg "   ✓  config.ini: inventory = ${_APT_INV}" "   ✓  config.ini: inventory = ${_APT_INV}"

  else
    # ── Standard-hosts verwenden ──────────────────────────────────────
    _USE_INVENTORY="$_STD_HOSTS"
    msg "   → Verwende ${_STD_HOSTS}" "   → Using ${_STD_HOSTS}"

    if [ "$ANSIBLE_RUN_USER" != "root" ]; then
      echo ""
      echo "   ┌──────────────────────────────────────────────────────────────┐"
      if [[ "$_LANG" == "en" ]]; then
        echo "   │  ℹ  Tip: The Ansible user '${ANSIBLE_RUN_USER}' is set in"
        echo "   │  config.ini as 'user' (used via -u flag)."
        echo "   │"
        echo "   │  Alternatively, add to ${_STD_HOSTS}:"
        echo "   │"
      else
        echo "   │  ℹ  Tipp: Der Ansible-Benutzer '${ANSIBLE_RUN_USER}' ist in"
        echo "   │  config.ini als 'user' hinterlegt (wird per -u Flag genutzt)."
        echo "   │"
        echo "   │  Alternativ in ${_STD_HOSTS} eintragen:"
        echo "   │"
      fi
      echo "   │    [all:vars]"
      echo "   │    ansible_user = ${ANSIBLE_RUN_USER}"
      echo "   └──────────────────────────────────────────────────────────────┘"
    fi
  fi

else
  # ── Kein Standard-Inventory vorhanden ─────────────────────────────────
  msg "   ⚠  Kein Inventory unter ${_STD_HOSTS} gefunden." "   ⚠  No inventory found at ${_STD_HOSTS}."
  msg "   Lege ${_APT_INV} an …" "   Creating ${_APT_INV} …"

  mkdir -p /etc/ansible
  cat > "$_APT_INV" << 'INVEOF'
# patchsible Inventory
# Hosts und Gruppen hier eintragen
#
# Beispiel:
# [webserver]
# server1.example.com
# server2.example.com

INVEOF
  echo "[all:vars]" >> "$_APT_INV"
  echo "ansible_user = ${ANSIBLE_RUN_USER}" >> "$_APT_INV"

  sed -i "s|^inventory = .*|inventory = ${_APT_INV}|" "$INSTALL_DIR/config.ini" 2>/dev/null || true
  _USE_INVENTORY="$_APT_INV"
  msg "   ✓  Leeres Inventory angelegt: ${_APT_INV}" "   ✓  Empty inventory created: ${_APT_INV}"
  msg "   ✓  config.ini: inventory = ${_APT_INV}" "   ✓  config.ini: inventory = ${_APT_INV}"
fi

# ══ 4. SSL-Zertifikat ═════════════════════════════════════════════════════
echo ""
prompt_yn "🔒  HTTPS aktivieren? (selbst-signiertes Zertifikat) [j/N]: " "🔒  Enable HTTPS? (self-signed certificate) [y/N]: "
SSL_CHOICE="${_ans,,}"

if [[ "$SSL_CHOICE" == "j" || "$SSL_CHOICE" == "y" ]]; then
  msg "   Erstelle selbst-signiertes TLS-Zertifikat (10 Jahre) …" "   Creating self-signed TLS certificate (10 years) …"
  mkdir -p "$INSTALL_DIR/ssl"

  LOCAL_IP=$(hostname -I | awk '{print $1}')
  HOSTNAME=$(hostname -f 2>/dev/null || hostname)

  openssl req -x509 -newkey rsa:2048 \
    -keyout "$INSTALL_DIR/ssl/key.pem" \
    -out    "$INSTALL_DIR/ssl/cert.pem" \
    -days 3650 -nodes \
    -subj "/CN=${HOSTNAME}/O=patchsible" \
    -addext "subjectAltName=IP:${LOCAL_IP},IP:127.0.0.1,DNS:${HOSTNAME},DNS:localhost" \
    2>/dev/null
  chmod 600 "$INSTALL_DIR/ssl/key.pem"

  sed -i "s/^enabled = false/enabled = true/" "$INSTALL_DIR/config.ini"

  msg "   ✓  Zertifikat: $INSTALL_DIR/ssl/cert.pem" "   ✓  Certificate: $INSTALL_DIR/ssl/cert.pem"
  msg "   ✓  HTTPS in config.ini aktiviert" "   ✓  HTTPS enabled in config.ini"
  echo ""
  msg "   ℹ  Browser-Warnung 'Verbindung nicht sicher' ist bei self-signed normal." "   ℹ  Browser warning 'Connection not secure' is normal for self-signed certs."
  msg "      Einmalig im Browser akzeptieren oder eigenes Zertifikat eintragen." "      Accept once in browser or add your own certificate."
  SSL_ENABLED=true
else
  msg "   → HTTP (HTTPS später in config.ini aktivierbar)" "   → HTTP (HTTPS can be enabled later in config.ini)"
  SSL_ENABLED=false
fi

# ══ 5. Port ═══════════════════════════════════════════════════════════════
echo ""
CURRENT_PORT=$(grep "^port" "$INSTALL_DIR/config.ini" | awk -F' = ' '{print $2}' | tr -d ' ')
if [[ "$_LANG" == "en" ]]; then
  read -r -p "🌐  Port [Default: ${CURRENT_PORT}]: " PORT_INPUT
else
  read -r -p "🌐  Port [Standard: ${CURRENT_PORT}]: " PORT_INPUT
fi
if [[ "$PORT_INPUT" =~ ^[0-9]+$ ]] && [ "$PORT_INPUT" -ge 1 ] && [ "$PORT_INPUT" -le 65535 ]; then
  sed -i "s/^port = .*/port = $PORT_INPUT/" "$INSTALL_DIR/config.ini"
  msg "   → Port gesetzt: $PORT_INPUT" "   → Port set: $PORT_INPUT"
else
  msg "   → Port bleibt: ${CURRENT_PORT}" "   → Port remains: ${CURRENT_PORT}"
fi

# ══ 6. Datenbank initialisieren ═══════════════════════════════════════════
echo ""
msg "🗄️  Initialisiere Datenbank …" "🗄️  Initializing database …"
cd "$INSTALL_DIR"
"$INSTALL_DIR/venv/bin/python3" -c "
import sys; sys.path.insert(0, '.')
from app import init_db; init_db()
print('   OK')
"

# ══ 7. Systemd-Service ════════════════════════════════════════════════════
echo ""
msg "⚙️  Richte Systemd-Service ein …" "⚙️  Setting up systemd service …"

cat > /etc/systemd/system/${SERVICE_NAME}.service << EOF
[Unit]
Description=patchsible – Linux Patchmanagement
After=network.target

[Service]
Type=simple
User=${SERVICE_USER}
WorkingDirectory=${INSTALL_DIR}
ExecStart=${INSTALL_DIR}/venv/bin/python3 ${INSTALL_DIR}/app.py
Restart=on-failure
RestartSec=5
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable "$SERVICE_NAME"
systemctl restart "$SERVICE_NAME"

# ══ 8. Ergebnis ═══════════════════════════════════════════════════════════
sleep 2
LOCAL_IP=$(hostname -I | awk '{print $1}')
FINAL_PORT=$(grep "^port" "$INSTALL_DIR/config.ini" | awk -F' = ' '{print $2}' | tr -d ' ')
PROTO=$( [[ "$SSL_ENABLED" == "true" ]] && echo "https" || echo "http" )

echo ""
if systemctl is-active --quiet "$SERVICE_NAME"; then
  echo "════════════════════════════════════════════════════════════════════════"
  msg "  ✅  Installation erfolgreich!" "  ✅  Installation successful!"
  echo ""
  echo "  🌐  patchsible – Linux Patchmanagement"
  echo "      ${PROTO}://${LOCAL_IP}:${FINAL_PORT}"
  echo ""
  if [[ "$_LANG" == "en" ]]; then
    echo "  🔑  Login:  Linux user of group 'patchsible' + password"
    echo "              Add more users:  sudo usermod -aG patchsible <name>"
  else
    echo "  🔑  Login:  Linux-Benutzer der Gruppe 'patchsible' + Passwort"
    echo "              Weitere Nutzer:  sudo usermod -aG patchsible <name>"
  fi
  # Passwort des neu angelegten Benutzers nochmals anzeigen
  if [ "$_user_created" = true ] && [ -n "$_newpass" ]; then
    echo ""
    echo "  ┌──────────────────────────────────────────────────────────┐"
    if [[ "$_LANG" == "en" ]]; then
      printf  "  │  🔐  Password for 'patchsible':  %-24s│\n" "${_newpass}"
      echo   "  │      Please store it securely — it cannot be recovered. │"
    else
      printf  "  │  🔐  Passwort für 'patchsible':  %-24s│\n" "${_newpass}"
      echo   "  │      Sicher aufbewahren — kann nicht wiederhergestellt werden. │"
    fi
    echo   "  └──────────────────────────────────────────────────────────┘"
  fi
  echo ""
  msg "  🤖  Ansible-Benutzer:  ${ANSIBLE_RUN_USER}" "  🤖  Ansible user:  ${ANSIBLE_RUN_USER}"
  if [ -f "$INSTALL_DIR/ansible.cfg" ]; then
  msg "      ansible.cfg:       ${INSTALL_DIR}/ansible.cfg" "      ansible.cfg:       ${INSTALL_DIR}/ansible.cfg"
  fi
  if [ -n "$_USE_INVENTORY" ]; then
  msg "      Inventory:         ${_USE_INVENTORY}" "      Inventory:         ${_USE_INVENTORY}"
  fi
  echo ""
  msg "  📝  Konfiguration:  ${INSTALL_DIR}/config.ini" "  📝  Configuration:  ${INSTALL_DIR}/config.ini"
  msg "      (Port, SSL, Auth, Inventory – Änderung: systemctl restart patchsible)" "      (Port, SSL, Auth, Inventory – Change: systemctl restart patchsible)"
  echo ""
  msg "  🔧  Service-Befehle:" "  🔧  Service commands:"
  echo "      systemctl status  $SERVICE_NAME"
  echo "      systemctl restart $SERVICE_NAME"
  echo "      journalctl -u $SERVICE_NAME -f"
  echo "════════════════════════════════════════════════════════════════════════"

else
  msg "⚠️  Service konnte nicht gestartet werden." "⚠️  Service could not be started."
  msg "   Fehlerlog:  journalctl -u $SERVICE_NAME -n 30" "   Error log:  journalctl -u $SERVICE_NAME -n 30"
fi
