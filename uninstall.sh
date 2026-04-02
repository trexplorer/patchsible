#!/bin/bash
# ═══════════════════════════════════════════════════════════════
#  patchsible – Linux Patchmanagement — Deinstallationsscript
# ═══════════════════════════════════════════════════════════════

INSTALL_DIR="/opt/patchsible"
SERVICE_NAME="patchsible"
INV_FILE="/etc/ansible/hosts.patchsible.ini"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"

# ── Root-Check ────────────────────────────────────────────────────────────────
if [ "$EUID" -ne 0 ]; then
  echo "❌  Bitte als root ausführen:  sudo bash uninstall.sh"
  exit 1
fi

echo ""
echo "════════════════════════════════════════════════════════════════════════"
echo "   patchsible – Deinstallation"
echo "════════════════════════════════════════════════════════════════════════"
echo ""

# ── Sprachauswahl ─────────────────────────────────────────────────────────────
echo "   [1]  Deutsch"
echo "   [2]  English"
echo ""
read -r -p "   Sprache / Language [1/2, Enter = 1]: " _langchoice
_langchoice="${_langchoice:-1}"
if [[ "$_langchoice" == "2" ]]; then _LANG="en"; else _LANG="de"; fi
echo ""

msg() { if [[ "$_LANG" == "en" ]]; then echo "$2"; else echo "$1"; fi }

# ── Zusammenfassung was entfernt wird ────────────────────────────────────────
msg "Folgende Komponenten werden entfernt:" \
    "The following components will be removed:"
echo ""
msg "  • Systemd-Service:    $SERVICE_FILE" \
    "  • Systemd service:    $SERVICE_FILE"
msg "  • Installationsordner: $INSTALL_DIR" \
    "  • Installation folder: $INSTALL_DIR"
if [ -f "$INV_FILE" ]; then
  msg "  • Ansible-Inventory:  $INV_FILE" \
      "  • Ansible inventory:  $INV_FILE"
fi
echo ""
msg "Optional (wird separat gefragt):" \
    "Optional (asked separately):"
msg "  • Linux-Benutzer 'patchsible' (falls angelegt)" \
    "  • Linux user 'patchsible' (if it exists)"
msg "  • Linux-Gruppe 'patchsible'" \
    "  • Linux group 'patchsible'"
msg "  • Ansible (/etc/ansible bleibt erhalten, nur .ini wird entfernt)" \
    "  • Ansible (/etc/ansible is kept, only .ini is removed)"
echo ""

# ── Bestätigung ───────────────────────────────────────────────────────────────
msg "⚠  ACHTUNG: Die Datenbank (patchsible.db) und alle Logs gehen verloren!" \
    "⚠  WARNING: The database (patchsible.db) and all logs will be lost!"
echo ""
read -r -p "$(if [[ "$_LANG" == "en" ]]; then echo "   Continue with uninstall? [yes/no]: "; else echo "   Deinstallation fortfahren? [ja/nein]: "; fi)" _confirm

if [[ "$_LANG" == "en" ]]; then
  [[ "$_confirm" == "yes" ]] || { echo "   Aborted."; exit 0; }
else
  [[ "$_confirm" == "ja"  ]] || { echo "   Abgebrochen."; exit 0; }
fi
echo ""

# ── 1. Service stoppen und deaktivieren ───────────────────────────────────────
msg "⏹  Stoppe und deaktiviere Service …" \
    "⏹  Stopping and disabling service …"

if systemctl is-active --quiet "$SERVICE_NAME" 2>/dev/null; then
  systemctl stop "$SERVICE_NAME"
  msg "   ✓  Service gestoppt." "   ✓  Service stopped."
fi

if systemctl is-enabled --quiet "$SERVICE_NAME" 2>/dev/null; then
  systemctl disable "$SERVICE_NAME"
  msg "   ✓  Service deaktiviert." "   ✓  Service disabled."
fi

if [ -f "$SERVICE_FILE" ]; then
  rm -f "$SERVICE_FILE"
  systemctl daemon-reload
  msg "   ✓  Service-Datei entfernt." "   ✓  Service file removed."
fi

# ── 2. Installationsverzeichnis entfernen ─────────────────────────────────────
echo ""
msg "🗑  Entferne $INSTALL_DIR …" \
    "🗑  Removing $INSTALL_DIR …"

if [ -d "$INSTALL_DIR" ]; then
  rm -rf "$INSTALL_DIR"
  msg "   ✓  $INSTALL_DIR entfernt." "   ✓  $INSTALL_DIR removed."
else
  msg "   ℹ  $INSTALL_DIR nicht gefunden – bereits entfernt?" \
      "   ℹ  $INSTALL_DIR not found – already removed?"
fi

# ── 3. Ansible-Inventory ──────────────────────────────────────────────────────
echo ""
if [ -f "$INV_FILE" ]; then
  msg "📋  Entferne patchsible-Inventory ($INV_FILE) …" \
      "📋  Removing patchsible inventory ($INV_FILE) …"
  rm -f "$INV_FILE"
  msg "   ✓  Inventory entfernt." "   ✓  Inventory removed."
  # /etc/ansible leer? Dann ggf. entfernen
  if [ -d "/etc/ansible" ] && [ -z "$(ls -A /etc/ansible 2>/dev/null)" ]; then
    rmdir /etc/ansible 2>/dev/null || true
    msg "   ✓  /etc/ansible (leer) entfernt." "   ✓  /etc/ansible (empty) removed."
  fi
fi

# ── 4. Linux-Benutzer 'patchsible' ───────────────────────────────────────────
echo ""
if id "patchsible" &>/dev/null; then
  msg "👤  Linux-Benutzer 'patchsible' gefunden." \
      "👤  Linux user 'patchsible' found."
  read -r -p "$(if [[ "$_LANG" == "en" ]]; then echo "   Delete user 'patchsible' and home directory? [yes/no]: "; else echo "   Benutzer 'patchsible' und Home-Verzeichnis löschen? [ja/nein]: "; fi)" _deluser

  if [[ "$_LANG" == "en" && "$_deluser" == "yes" ]] || \
     [[ "$_LANG" == "de" && "$_deluser" == "ja"  ]]; then
    userdel -r patchsible 2>/dev/null || userdel patchsible 2>/dev/null || true
    msg "   ✓  Benutzer 'patchsible' gelöscht." "   ✓  User 'patchsible' deleted."
  else
    msg "   → Benutzer 'patchsible' bleibt erhalten." \
        "   → User 'patchsible' kept."
  fi
else
  msg "   ℹ  Benutzer 'patchsible' nicht vorhanden." \
      "   ℹ  User 'patchsible' does not exist."
fi

# ── 5. Linux-Gruppe 'patchsible' ─────────────────────────────────────────────
echo ""
if getent group patchsible &>/dev/null; then
  msg "👥  Linux-Gruppe 'patchsible' gefunden." \
      "👥  Linux group 'patchsible' found."
  read -r -p "$(if [[ "$_LANG" == "en" ]]; then echo "   Delete group 'patchsible'? [yes/no]: "; else echo "   Gruppe 'patchsible' löschen? [ja/nein]: "; fi)" _delgroup

  if [[ "$_LANG" == "en" && "$_delgroup" == "yes" ]] || \
     [[ "$_LANG" == "de" && "$_delgroup" == "ja"  ]]; then
    groupdel patchsible 2>/dev/null || true
    msg "   ✓  Gruppe 'patchsible' gelöscht." "   ✓  Group 'patchsible' deleted."
  else
    msg "   → Gruppe 'patchsible' bleibt erhalten." \
        "   → Group 'patchsible' kept."
  fi
else
  msg "   ℹ  Gruppe 'patchsible' nicht vorhanden." \
      "   ℹ  Group 'patchsible' does not exist."
fi

# ── 6. Abschluss ──────────────────────────────────────────────────────────────
echo ""
echo "════════════════════════════════════════════════════════════════════════"
msg "  ✅  patchsible wurde vollständig deinstalliert." \
    "  ✅  patchsible has been completely uninstalled."
echo ""
msg "  ℹ  Nicht automatisch entfernt (falls manuell installiert):" \
    "  ℹ  Not automatically removed (if manually installed):"
echo "     apt remove ansible python3-pam python3-venv"
echo "════════════════════════════════════════════════════════════════════════"
echo ""
