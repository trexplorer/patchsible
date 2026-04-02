#!/usr/bin/env python3
"""
patchsible – Patchmanagement Dashboard
Web-basiertes Patch-Management via Ansible
Subtitle: Linux Patchmanagement
"""

import configparser
import grp
import os
import pwd
import re
import json
import socket
import sqlite3
import subprocess
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from functools import wraps

from flask import (
    Flask, render_template, jsonify, request,
    Response, stream_with_context,
    session, redirect, url_for
)
app = Flask(__name__)
VERSION = '0.1b'

# ─── Konfiguration aus config.ini ────────────────────────────────────────────
BASE_DIR    = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, 'config.ini')
DB_PATH     = os.path.join(BASE_DIR, 'patchsible.db')

cfg = configparser.ConfigParser()
cfg.read(CONFIG_PATH)

PORT           = cfg.getint   ('server',  'port',           fallback=5000)
HOST           = cfg.get      ('server',  'host',            fallback='0.0.0.0')
LANGUAGE       = cfg.get      ('server',  'language',        fallback='de').strip()
SSL_ON         = cfg.getboolean('ssl',    'enabled',         fallback=False)
SSL_CERT       = cfg.get      ('ssl',     'certfile',        fallback=os.path.join(BASE_DIR, 'ssl/cert.pem'))
SSL_KEY        = cfg.get      ('ssl',     'keyfile',         fallback=os.path.join(BASE_DIR, 'ssl/key.pem'))
AUTH_ON        = cfg.getboolean('auth',   'enabled',         fallback=True)
SECRET         = cfg.get      ('auth',    'secret_key',      fallback='bitte-in-config-ini-aendern')
ALLOWED_GROUP  = cfg.get      ('auth',    'allowed_group',   fallback='patchsible').strip()
ANSIBLE_USER      = cfg.get      ('ansible', 'user',            fallback='').strip()
ANSIBLE_INVENTORY = cfg.get      ('ansible', 'inventory',       fallback='/etc/ansible/hosts').strip()
CHECK_INTERVAL    = cfg.getint   ('check',   'interval_hours',  fallback=4)
ANSIBLE_TIMEOUT   = 120
INSTALL_TIMEOUT   = 600

app.secret_key = SECRET
# Session läuft 30 Minuten nach der letzten Anfrage ab (Idle-Timeout)
app.permanent_session_lifetime = timedelta(minutes=30)

# ─── PAM ──────────────────────────────────────────────────────────────────────
# Try python-pam (apt: python3-pam  /  pip: python-pam) first,
# then pamela (pip: pamela) as fallback — both wrap libpam via ctypes.
def _pam_authenticate(username: str, password: str) -> bool:
    return False  # overwritten below if a PAM library is found

PAM_AVAILABLE = False

try:
    import pam as _pam_mod
    _pam_obj = _pam_mod.pam()
    def _pam_authenticate(username: str, password: str) -> bool:  # noqa: F811
        return bool(_pam_obj.authenticate(username, password))
    PAM_AVAILABLE = True
except ImportError:
    pass

if not PAM_AVAILABLE:
    try:
        import pamela as _pamela
        def _pam_authenticate(username: str, password: str) -> bool:  # noqa: F811
            try:
                _pamela.authenticate(username, password)
                return True
            except Exception:
                return False
        PAM_AVAILABLE = True
    except ImportError:
        pass

# ─── Scheduler-State ──────────────────────────────────────────────────────────
_last_auto_check: datetime | None = None
_scheduled_jobs_scheduler = None

# ─── Auth ─────────────────────────────────────────────────────────────────────
def is_in_group(username: str, group_name: str) -> bool:
    """Prüft ob ein Linux-Benutzer Mitglied einer Gruppe ist."""
    try:
        g = grp.getgrnam(group_name)
    except KeyError:
        return False
    if username in g.gr_mem:
        return True
    try:
        return pwd.getpwnam(username).pw_gid == g.gr_gid
    except KeyError:
        return False


def check_credentials(username: str, password: str) -> tuple:
    """PAM-Auth + optionale Gruppenprüfung. Gibt (ok, fehlermeldung) zurück."""
    if not username or not password:
        return False, 'Benutzername und Passwort erforderlich'
    if not PAM_AVAILABLE:
        return False, 'PAM nicht verfügbar – bitte python-pam installieren'
    try:
        if not _pam_authenticate(username, password):
            return False, 'Benutzername oder Passwort falsch'
    except Exception as e:
        return False, f'PAM-Fehler: {e}'
    if ALLOWED_GROUP and not is_in_group(username, ALLOWED_GROUP):
        return False, (
            f'Zugriff verweigert – Benutzer muss Mitglied '
            f'der Gruppe „{ALLOWED_GROUP}" sein'
        )
    return True, ''


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if AUTH_ON and not session.get('logged_in'):
            if request.path.startswith('/api/'):
                return jsonify({'error': 'Nicht angemeldet', 'auth': False}), 401
            return redirect(url_for('login', next=request.path))
        return f(*args, **kwargs)
    return decorated


# ─── Datenbank ────────────────────────────────────────────────────────────────
def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS history (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp    TEXT NOT NULL,
                host         TEXT NOT NULL,
                action       TEXT NOT NULL,
                packages     TEXT,
                status       TEXT NOT NULL,
                output       TEXT,
                triggered_by TEXT DEFAULT ''
            )
        ''')
        # Migration: triggered_by-Spalte für bestehende Datenbanken ergänzen
        try:
            conn.execute('ALTER TABLE history ADD COLUMN triggered_by TEXT DEFAULT ""')
        except sqlite3.OperationalError:
            pass  # Spalte existiert bereits
        # Gecachte Host-Statuses für Sofortanzeige beim Seitenaufruf
        conn.execute('''
            CREATE TABLE IF NOT EXISTS host_status (
                host            TEXT PRIMARY KEY,
                last_check      TEXT NOT NULL,
                status          TEXT NOT NULL,
                os_info         TEXT DEFAULT '',
                packages        TEXT DEFAULT '[]',
                update_count    INTEGER DEFAULT 0,
                ansible_host    TEXT DEFAULT '',
                reboot_required INTEGER DEFAULT 0,
                pkg_manager     TEXT DEFAULT ''
            )
        ''')
        # Migrationen für bestehende Datenbanken
        for col, definition in [
            ('ansible_host',    'TEXT DEFAULT ""'),
            ('reboot_required', 'INTEGER DEFAULT 0'),
            ('pkg_manager',     'TEXT DEFAULT ""'),
        ]:
            try:
                conn.execute(f'ALTER TABLE host_status ADD COLUMN {col} {definition}')
            except sqlite3.OperationalError:
                pass  # Spalte existiert bereits

        # Scheduled jobs table
        conn.execute('''
            CREATE TABLE IF NOT EXISTS scheduled_jobs (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                host         TEXT NOT NULL,
                action       TEXT NOT NULL,
                packages     TEXT,
                scheduled_at TEXT NOT NULL,
                created_at   TEXT NOT NULL,
                created_by   TEXT NOT NULL,
                status       TEXT NOT NULL DEFAULT 'pending',
                output       TEXT DEFAULT ''
            )
        ''')


def log_action(host, action, packages, status, output, triggered_by=''):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            'INSERT INTO history (timestamp, host, action, packages, status, output, triggered_by) '
            'VALUES (?,?,?,?,?,?,?)',
            (datetime.now().strftime('%Y-%m-%d %H:%M:%S'), host, action,
             json.dumps(packages) if packages else None, status, output,
             triggered_by or '')
        )


def get_history(date_from=None, date_to=None, host=None, user=None, status=None, limit=500):
    """Gibt History-Einträge zurück, gefiltert nach Datum, Host, Nutzer und Status.
    Standardmäßig nur die letzten 7 Tage."""
    if date_from is None:
        date_from = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d 00:00:00')
    conditions = ['timestamp >= ?']
    params: list = [date_from]
    if date_to:
        conditions.append('timestamp <= ?')
        params.append(date_to if len(date_to) > 10 else date_to + ' 23:59:59')
    if host:
        conditions.append('host = ?')
        params.append(host)
    if user:
        conditions.append('triggered_by = ?')
        params.append(user)
    if status:
        conditions.append('status = ?')
        params.append(status)
    where = ' AND '.join(conditions)
    params.append(limit)
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            f'SELECT * FROM history WHERE {where} ORDER BY id DESC LIMIT ?', params
        ).fetchall()
    return [dict(r) for r in rows]


def save_host_status(host: str, status: str, os_info: str, packages: list,
                     ansible_host: str = None, reboot_required: bool = None,
                     pkg_manager: str = None):
    """Speichert oder aktualisiert den gecachten Status eines Hosts.
    ansible_host, reboot_required, und pkg_manager sind optional – None bedeutet: bestehenden Wert behalten.
    """
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute('''
            INSERT INTO host_status (host, last_check, status, os_info, packages, update_count,
                                     ansible_host, reboot_required, pkg_manager)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(host) DO UPDATE SET
                last_check   = excluded.last_check,
                status       = excluded.status,
                os_info      = CASE WHEN excluded.os_info != '' THEN excluded.os_info
                                    ELSE host_status.os_info END,
                packages     = excluded.packages,
                update_count = excluded.update_count,
                ansible_host = CASE WHEN excluded.ansible_host != '' THEN excluded.ansible_host
                                    ELSE host_status.ansible_host END,
                reboot_required = CASE WHEN excluded.reboot_required >= 0 THEN excluded.reboot_required
                                       ELSE host_status.reboot_required END,
                pkg_manager  = CASE WHEN excluded.pkg_manager != '' THEN excluded.pkg_manager
                                    ELSE host_status.pkg_manager END
        ''', (
            host, now, status, os_info or '',
            json.dumps(packages), len(packages),
            ansible_host or '',
            int(reboot_required) if reboot_required is not None else -1,
            pkg_manager or '',
        ))


def get_all_statuses() -> dict:
    """Gibt gecachte Host-Statuses als Dict {host: info} zurück."""
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute('SELECT * FROM host_status').fetchall()
    result = {}
    for row in rows:
        d = dict(row)
        try:
            d['packages'] = json.loads(d['packages']) if d['packages'] else []
        except Exception:
            d['packages'] = []
        result[d['host']] = d
    return result


# ─── Ansible-Hilfsfunktionen ──────────────────────────────────────────────────
_IPV4_RE = re.compile(r'^\d{1,3}(\.\d{1,3}){3}$')

def _resolve_ip(addr: str) -> str:
    """Gibt die IPv4-Adresse zu einem Hostnamen zurück (DNS-Lookup).
    Ist addr bereits eine IP, wird sie unverändert zurückgegeben.
    Bei Fehler wird addr selbst zurückgegeben."""
    if _IPV4_RE.match(addr):
        return addr
    try:
        return socket.gethostbyname(addr)
    except Exception:
        return addr


def get_inventory():
    try:
        result = subprocess.run(
            ['ansible-inventory', '--list', '-i', ANSIBLE_INVENTORY],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode != 0:
            return {'groups': {}, 'all_hosts': [],
                    'error': result.stderr or 'ansible-inventory fehlgeschlagen'}
        inv = json.loads(result.stdout)
        groups, all_hosts = {}, set()
        if '_meta' in inv:
            all_hosts.update(inv['_meta'].get('hostvars', {}).keys())
        if 'all' in inv and isinstance(inv['all'], dict):
            all_hosts.update(inv['all'].get('hosts', []))
        # Erst alle Hosts sammeln, dann Gruppen filtern
        for key, val in inv.items():
            if key in ('_meta', 'all', 'ungrouped'):
                continue
            if isinstance(val, dict) and val.get('hosts'):
                all_hosts.update(val['hosts'])
        # Jetzt Gruppen bauen – Keys die selbst ein Hostname sind überspringen
        for key, val in inv.items():
            if key in ('_meta', 'all', 'ungrouped'):
                continue
            if key in all_hosts:
                continue  # Hostname als Key, keine echte Gruppe
            if isinstance(val, dict) and val.get('hosts'):
                groups[key] = val['hosts']

        # IP-Adressen: ansible_host aus hostvars, dann DNS-Auflösung.
        # Auflösung erfolgt parallel (max. 3 s pro Host), damit die Seite
        # auch bei vielen Hosts nicht ewig lädt.
        hostvars = inv.get('_meta', {}).get('hostvars', {})
        raw = {h: hostvars.get(h, {}).get('ansible_host', '') or h for h in all_hosts}
        host_ips: dict = {}
        if raw:
            with ThreadPoolExecutor(max_workers=min(len(raw), 20)) as pool:
                futures = {pool.submit(_resolve_ip, addr): h for h, addr in raw.items()}
                for fut, h in futures.items():
                    try:
                        host_ips[h] = fut.result(timeout=3)
                    except Exception:
                        host_ips[h] = raw[h]

        return {'groups': groups, 'all_hosts': sorted(list(all_hosts)), 'host_ips': host_ips,
                'inventory_path': ANSIBLE_INVENTORY}
    except FileNotFoundError:
        return {'groups': {}, 'all_hosts': [], 'host_ips': {},
                'inventory_path': ANSIBLE_INVENTORY, 'error': 'ansible-inventory nicht gefunden'}
    except Exception as e:
        return {'groups': {}, 'all_hosts': [], 'host_ips': {},
                'inventory_path': ANSIBLE_INVENTORY, 'error': str(e)}


def extract_stdout(raw: str) -> str:
    # JSON format: "hostname | FAILED! => {...}" or "hostname | UNREACHABLE! => {...}"
    for line in raw.split('\n'):
        if '| FAILED!' in line or '| UNREACHABLE!' in line:
            try:
                data = json.loads(line.split('=>', 1)[1].strip())
                # Prefer stdout over msg — msg is often just "non-zero return code"
                return data.get('stdout', '') or data.get('msg', '') or line
            except Exception:
                return line
    # Plain format: "hostname | CHANGED | rc=0 >> ..." or "hostname | FAILED | rc=100 >> ..."
    lines, result_lines, capturing = raw.split('\n'), [], False
    for line in lines:
        if re.match(r'^\S+\s*\|\s*(CHANGED|SUCCESS|FAILED)', line):
            capturing = True
            # Content may appear on the same line after ">>"
            # e.g. "hostname | FAILED | rc=100 >>##OS##CentOS Linux 7 (Core)"
            if '>>' in line:
                after = line.split('>>', 1)[1].strip()
                if after:
                    result_lines.append(after)
            continue
        if capturing:
            result_lines.append(line)
    return '\n'.join(result_lines)


def parse_upgradable(raw: str) -> list:
    """Parse apt list --upgradable output."""
    packages = []
    for line in raw.split('\n'):
        m = re.match(r'^([^/\s]+)/\S+\s+(\S+)\s+\S+\s+\[upgradable from:\s+([^\]]+)\]', line.strip())
        if m:
            packages.append({'name': m.group(1), 'new_version': m.group(2), 'current_version': m.group(3)})
    return packages


def parse_dnf_updates(raw: str) -> list:
    """Parse dnf/yum check-update output. Format: package.arch version repo"""
    # Known yum/dnf header/footer prefixes to skip
    _SKIP_PREFIXES = (
        'Last metadata', 'Loaded plugins', 'Loading mirror', 'Determining fastest',
        'Obsoleting', 'Security:', 'Update', 'Upgraded', 'Install', 'Remove',
        'Transaction', 'Running transaction', 'Verifying', 'Complete!',
        'Repodata', 'repodata', 'Delta', 'Delta RPMs', '* ', 'http', 'https',
        'mirrors.', 'base:', 'updates:', 'extras:', 'epel:', 'centos',
    )
    packages = []
    for line in raw.split('\n'):
        line = line.strip()
        if not line:
            continue
        if any(line.startswith(p) for p in _SKIP_PREFIXES):
            continue
        parts = line.split()
        if len(parts) >= 3:
            pkg_info = parts[0]  # e.g., 'kernel.x86_64'
            new_version = parts[1]
            # Version must contain a digit (filters out header lines like "Loaded plugins: fastestmirror")
            if not re.search(r'\d', new_version):
                continue
            # Package name must look like a real package (letters/digits/dots/dashes, optional .arch)
            if not re.match(r'^[a-zA-Z0-9][a-zA-Z0-9_.+\-]*$', pkg_info):
                continue
            # Extract package name (remove .arch suffix like .x86_64, .noarch, .i686)
            pkg_name = re.sub(r'\.(x86_64|i686|i386|noarch|aarch64|ppc64|ppc64le|s390x)$', '', pkg_info)
            packages.append({
                'name': pkg_name,
                'new_version': new_version,
                'current_version': ''  # yum/dnf check-update doesn't show current version
            })
    return packages


def sse(payload: dict) -> str:
    return f"data: {json.dumps(payload)}\n\n"


# ─── Kern-Check-Logik (geteilt von SSE-Endpoint und Scheduler) ───────────────
def _do_check(host: str) -> dict:
    """
    Führt Update-Prüfung für einen Host synchron durch.
    Gibt {'status', 'os_info', 'packages', 'error_msg', 'reboot_required', 'pkg_manager'} zurück.
    """
    shell_cmd = (
        # printf writes the marker without a trailing newline;
        # the subsequent command adds its own newline → "##OS##CentOS Linux 7 (Core)\n"
        # This avoids any shell quoting of the marker itself.
        r"printf '##OS##'; "
        r"grep -oP '(?<=PRETTY_NAME=\")[^\"]*' /etc/os-release 2>/dev/null"
        r" || head -1 /etc/redhat-release 2>/dev/null"
        r" || echo Unbekannt; "
        r"printf '##REBOOT##'; "
        r"if [ -f /var/run/reboot-required ]; then echo yes; "
        r"elif command -v needs-restarting >/dev/null 2>&1; then needs-restarting -r >/dev/null 2>&1 && echo no || echo yes; "
        r"else echo no; fi; "
        r"printf '##PKGMGR##'; "
        r"if command -v apt-get >/dev/null 2>&1; then "
        r"echo 'apt'; "
        r"apt-get update -qq 2>&1; "
        r"apt list --upgradable 2>/dev/null; "
        r"elif command -v dnf >/dev/null 2>&1; then "
        r"echo 'dnf'; "
        r"dnf check-update 2>/dev/null; "
        r"elif command -v yum >/dev/null 2>&1; then "
        r"echo 'yum'; "
        r"yum check-update 2>/dev/null; "
        r"else "
        r"echo unknown; "
        r"fi"
    )

    cmd = ['ansible', host, '-i', ANSIBLE_INVENTORY,
           '-m', 'shell', '-a', shell_cmd, '--become', '--timeout', '60']
    if ANSIBLE_USER:
        cmd += ['-u', ANSIBLE_USER]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=ANSIBLE_TIMEOUT)
        combined = result.stdout + result.stderr

        if 'UNREACHABLE' in combined:
            return {'status': 'error', 'os_info': '', 'packages': [],
                    'error_msg': 'Host nicht erreichbar (UNREACHABLE)', 'reboot_required': False,
                    'pkg_manager': ''}

        if 'FAILED' in combined:
            # Extract rc from JSON format ("rc": N) or plain Ansible format (| rc=N)
            rc_m = re.search(r'"rc":\s*(-?\d+)', combined) or re.search(r'\|\s*rc=(-?\d+)', combined)
            rc_val = int(rc_m.group(1)) if rc_m else None
            # rc=100 → yum/dnf "updates available" — not a real error, parse normally
            # rc=0   → success
            # anything else (including None = no rc found) → real error
            if rc_val not in (0, 100):
                return {'status': 'error', 'os_info': '', 'packages': [],
                        'error_msg': extract_stdout(combined) or combined[:300], 'reboot_required': False,
                        'pkg_manager': ''}

        stdout  = extract_stdout(combined)
        os_info = 'Unbekannt'
        reboot_required = False
        pkg_manager = 'unknown'
        pkgmgr_section_lines = []
        packages = []

        # Parse sections marked by ##OS##, ##REBOOT##, ##PKGMGR##
        in_pkgmgr_section = False
        for line in stdout.split('\n'):
            if line.startswith('##OS##'):
                os_info = line[6:].strip() or 'Unbekannt'
            elif line.startswith('##REBOOT##'):
                reboot_required = 'yes' in line[10:].strip().lower()
            elif line.startswith('##PKGMGR##'):
                in_pkgmgr_section = True
                # First line after ##PKGMGR## is the package manager name
                rest = line[10:].strip()
                if rest:
                    pkg_manager = rest
                    in_pkgmgr_section = True
            elif in_pkgmgr_section:
                pkgmgr_section_lines.append(line)

        # If pkg_manager line was on its own, get it from the first line of section
        if pkg_manager == 'unknown' and pkgmgr_section_lines:
            first_line = pkgmgr_section_lines[0].strip()
            if first_line in ('apt', 'dnf', 'yum'):
                pkg_manager = first_line
                pkgmgr_section_lines = pkgmgr_section_lines[1:]

        # Parse based on package manager type
        if pkg_manager == 'apt':
            packages = parse_upgradable('\n'.join(pkgmgr_section_lines))
        elif pkg_manager in ('dnf', 'yum'):
            packages = parse_dnf_updates('\n'.join(pkgmgr_section_lines))

        return {
            'status':          'updates' if packages else 'ok',
            'os_info':         os_info,
            'packages':        packages,
            'error_msg':       '',
            'reboot_required': reboot_required,
            'pkg_manager':     pkg_manager,
        }

    except subprocess.TimeoutExpired:
        return {'status': 'error', 'os_info': '', 'packages': [],
                'error_msg': f'Zeitüberschreitung ({ANSIBLE_TIMEOUT}s)', 'reboot_required': False,
                'pkg_manager': ''}
    except Exception as e:
        return {'status': 'error', 'os_info': '', 'packages': [],
                'error_msg': str(e), 'reboot_required': False,
                'pkg_manager': ''}


# ─── Automatische Prüfung ─────────────────────────────────────────────────────
def run_scheduled_check():
    """Wird vom Scheduler aufgerufen – prüft alle Hosts und cached Ergebnisse."""
    global _last_auto_check
    _last_auto_check = datetime.now()
    ts = _last_auto_check.strftime('%H:%M:%S')
    print(f"[Auto-Check] Start {ts}")

    inventory = get_inventory()
    hosts     = inventory.get('all_hosts', [])
    host_ips  = inventory.get('host_ips', {})
    if not hosts:
        print("[Auto-Check] Keine Hosts im Inventory.")
        return

    ok_count = err_count = 0
    for host in hosts:
        try:
            r = _do_check(host)
            save_host_status(
                host, r['status'], r['os_info'], r['packages'],
                ansible_host=host_ips.get(host, ''),
                reboot_required=r.get('reboot_required', False),
                pkg_manager=r.get('pkg_manager', ''),
            )
            n = len(r['packages'])
            print(f"[Auto-Check] {host}: {r['status']}"
                  + (f" ({n} Updates)" if n else "")
                  + (f" – {r['error_msg']}" if r['error_msg'] else ""))
            if r['status'] == 'error':
                err_count += 1
            else:
                ok_count += 1
        except Exception as exc:
            # Einzelner Host-Fehler darf die gesamte Prüfung nicht abbrechen
            print(f"[Auto-Check] {host}: Ausnahme – {exc}")
            err_count += 1

    print(f"[Auto-Check] Fertig – {ok_count} OK, {err_count} Fehler ({len(hosts)} Hosts)")


def _first_run_time() -> datetime:
    """
    Berechnet wann der erste Auto-Check nach dem Service-Start laufen soll.

    Logik: Erst starten wenn ALLE Hosts einen aktuellen Eintrag haben UND
    der älteste Eintrag jünger als CHECK_INTERVAL Stunden ist.
    In allen anderen Fällen (neue Hosts, leere DB, veraltete Daten) → sofort.
    30 Sekunden Puffer damit Flask vollständig hochgefahren ist.
    """
    STARTUP_DELAY = timedelta(seconds=30)
    try:
        with sqlite3.connect(DB_PATH) as conn:
            # Anzahl gecachter Hosts
            count = conn.execute('SELECT COUNT(*) FROM host_status').fetchone()[0]
            if count == 0:
                print("[Auto-Check] Keine gecachten Daten → starte sofort nach Boot")
                return datetime.now() + STARTUP_DELAY

            # Ältester gecachter Eintrag
            oldest_str = conn.execute('SELECT MIN(last_check) FROM host_status').fetchone()[0]
            if not oldest_str:
                return datetime.now() + STARTUP_DELAY

            oldest = datetime.strptime(oldest_str, '%Y-%m-%d %H:%M:%S')
            age_h  = (datetime.now() - oldest).total_seconds() / 3600

            if age_h >= CHECK_INTERVAL:
                # Daten sind älter als das Intervall → sofort prüfen
                print(f"[Auto-Check] Daten {age_h:.1f}h alt → starte sofort nach Boot")
                return datetime.now() + STARTUP_DELAY

            # Alle Daten frisch → nächsten Check zum regulären Zeitpunkt einplanen
            next_t = oldest + timedelta(hours=CHECK_INTERVAL)
            print(f"[Auto-Check] Daten aktuell → nächster Check: {next_t.strftime('%d.%m. %H:%M Uhr')}")
            return next_t

    except Exception as exc:
        print(f"[Auto-Check] Fehler bei _first_run_time: {exc} → starte sofort")
        return datetime.now() + STARTUP_DELAY


def run_scheduled_jobs_check():
    """Checked alle 60 Sekunden ob ausstehende scheduled_jobs ausgeführt werden müssen."""
    try:
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        with sqlite3.connect(DB_PATH) as conn:
            rows = conn.execute(
                'SELECT id, host, action, packages FROM scheduled_jobs WHERE status = ? AND scheduled_at <= ?',
                ('pending', now)
            ).fetchall()

        for job_id, host, action, packages_json in rows:
            packages = json.loads(packages_json) if packages_json else []
            try:
                if action == 'reboot':
                    _execute_scheduled_reboot(job_id, host)
                elif action == 'update':
                    _execute_scheduled_update(job_id, host, packages)
            except Exception as e:
                # Mark job as failed
                with sqlite3.connect(DB_PATH) as conn:
                    conn.execute(
                        'UPDATE scheduled_jobs SET status = ?, output = ? WHERE id = ?',
                        ('failed', str(e), job_id)
                    )
    except Exception as e:
        print(f"[Scheduled Jobs] Error in run_scheduled_jobs_check: {e}")


def _execute_scheduled_reboot(job_id: int, host: str):
    """Execute a scheduled reboot and update the job status."""
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute('UPDATE scheduled_jobs SET status = ? WHERE id = ?', ('running', job_id))

    reboot_cmd = [
        'ansible', host, '-i', ANSIBLE_INVENTORY,
        '-m', 'reboot',
        '-a', 'reboot_timeout=300 connect_timeout=30 post_reboot_delay=15',
        '--become', '--timeout', '360',
    ]
    if ANSIBLE_USER:
        reboot_cmd += ['-u', ANSIBLE_USER]

    try:
        result = subprocess.run(reboot_cmd, capture_output=True, text=True, timeout=INSTALL_TIMEOUT)
        output = result.stdout + result.stderr
        job_status = 'completed' if result.returncode == 0 else 'failed'
        log_status  = 'success'  if result.returncode == 0 else 'error'

        with sqlite3.connect(DB_PATH) as conn:
            conn.execute('UPDATE scheduled_jobs SET status = ?, output = ? WHERE id = ?',
                        (job_status, output, job_id))

        if job_status == 'completed':
            with sqlite3.connect(DB_PATH) as conn:
                conn.execute('UPDATE host_status SET reboot_required = 0 WHERE host = ?', (host,))

        log_action(host, 'reboot', [], log_status, output, 'scheduled')
    except Exception as e:
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute('UPDATE scheduled_jobs SET status = ?, output = ? WHERE id = ?',
                        ('failed', str(e), job_id))
        log_action(host, 'reboot', [], 'error', str(e), 'scheduled')


def _execute_scheduled_update(job_id: int, host: str, packages: list):
    """Execute a scheduled update and update the job status."""
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute('UPDATE scheduled_jobs SET status = ? WHERE id = ?', ('running', job_id))

    # Get package manager from host_status
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute('SELECT pkg_manager FROM host_status WHERE host = ?', (host,)).fetchone()
        pkg_manager = row[0] if row else ''

    # Determine module and args based on package manager
    if pkg_manager == 'apt':
        if packages:
            ansible_arg = f'name="{",".join(packages)}" state=latest update_cache=yes'
            action_type = 'install_selected'
        else:
            ansible_arg = 'upgrade=full update_cache=yes'
            action_type = 'upgrade_all'
        module = 'apt'
    elif pkg_manager in ('dnf', 'yum'):
        if packages:
            ansible_arg = f"name={','.join(packages)} state=latest"
            action_type = 'install_selected'
        else:
            ansible_arg = "name=* state=latest"
            action_type = 'upgrade_all'
        module = pkg_manager
    else:
        # Default to apt
        if packages:
            ansible_arg = f'name="{",".join(packages)}" state=latest update_cache=yes'
            action_type = 'install_selected'
        else:
            ansible_arg = 'upgrade=full update_cache=yes'
            action_type = 'upgrade_all'
        module = 'apt'

    install_cmd = [
        'ansible', host, '-i', ANSIBLE_INVENTORY,
        '-m', module, '-a', ansible_arg,
        '--become', '--timeout', '300', '-v',
    ]
    if ANSIBLE_USER:
        install_cmd += ['-u', ANSIBLE_USER]

    try:
        result = subprocess.run(install_cmd, capture_output=True, text=True, timeout=INSTALL_TIMEOUT)
        output = result.stdout + result.stderr
        job_status = 'completed' if result.returncode == 0 else 'failed'
        log_status  = 'success'  if result.returncode == 0 else 'error'

        with sqlite3.connect(DB_PATH) as conn:
            conn.execute('UPDATE scheduled_jobs SET status = ?, output = ? WHERE id = ?',
                        (job_status, output, job_id))

        if job_status == 'completed':
            save_host_status(host, 'ok', '', [])

        log_action(host, action_type, packages, log_status, output, 'scheduled')
    except Exception as e:
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute('UPDATE scheduled_jobs SET status = ?, output = ? WHERE id = ?',
                        ('failed', str(e), job_id))
        log_action(host, action_type if 'action_type' in locals() else 'error', packages, 'error', str(e), 'scheduled')


# ─── Session-Timeout ──────────────────────────────────────────────────────────
@app.before_request
def _touch_session():
    """Setzt den Session-Timer bei jeder Anfrage zurück (Idle-Timeout)."""
    if session.get('logged_in'):
        session.modified = True   # Verlängert das Session-Cookie um weitere 30 Min.


# ─── Routen: Auth ─────────────────────────────────────────────────────────────
@app.route('/login', methods=['GET', 'POST'])
def login():
    if not AUTH_ON:
        return redirect(url_for('index'))
    if session.get('logged_in'):
        return redirect(url_for('index'))

    error = None
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        ok, error = check_credentials(username, password)
        if ok:
            session.permanent   = True   # Aktiviert den Lifetime-Timer
            session['logged_in'] = True
            session['username']  = username
            next_url = request.args.get('next') or url_for('index')
            return redirect(next_url)

    return render_template('login.html', error=error,
                           pam_ok=PAM_AVAILABLE, allowed_group=ALLOWED_GROUP,
                           version=VERSION, lang=LANGUAGE)


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))


# ─── Routen: Haupt ────────────────────────────────────────────────────────────
@app.route('/')
@login_required
def index():
    return render_template('index.html', username=session.get('username', ''),
                           lang=LANGUAGE)


@app.route('/api/language', methods=['GET', 'POST'])
def api_language():
    """Liest oder ändert die globale Sprache (de/en). Kein Login nötig (für Login-Seite)."""
    global LANGUAGE
    if request.method == 'POST':
        new_lang = request.get_json(force=True).get('lang', 'de')
        if new_lang not in ('de', 'en'):
            new_lang = 'de'
        LANGUAGE = new_lang
        # In config.ini persistieren
        if not cfg.has_section('server'):
            cfg.add_section('server')
        cfg.set('server', 'language', new_lang)
        try:
            with open(CONFIG_PATH, 'w') as f:
                cfg.write(f)
        except Exception:
            pass
        return jsonify({'lang': LANGUAGE})
    return jsonify({'lang': LANGUAGE})


@app.route('/api/hosts')
@login_required
def api_hosts():
    return jsonify(get_inventory())


@app.route('/api/status')
@login_required
def api_status():
    """Gibt gecachte Host-Statuses aus der DB zurück (Sofortanzeige)."""
    return jsonify(get_all_statuses())


@app.route('/api/check_info')
@login_required
def api_check_info():
    """Gibt Info über den automatischen Check zurück."""
    info = {
        'interval_hours':  CHECK_INTERVAL,
        'last_auto_check': _last_auto_check.strftime('%Y-%m-%d %H:%M:%S') if _last_auto_check else None,
        'next_auto_check': None,
    }
    if CHECK_INTERVAL > 0 and _last_auto_check:
        info['next_auto_check'] = (
            _last_auto_check + timedelta(hours=CHECK_INTERVAL)
        ).strftime('%Y-%m-%d %H:%M:%S')
    return jsonify(info)


@app.route('/api/check/<path:host>')
@login_required
def api_check(host):
    """Manueller Check – Ergebnis als Server-Sent Events, wird auch gecacht."""
    def generate():
        if AUTH_ON and not session.get('logged_in'):
            yield sse({'type': 'error', 'msg': 'Sitzung abgelaufen', 'reload': True})
            yield sse({'type': 'done'})
            return

        try:
            yield sse({'type': 'status', 'msg': 'Aktualisiere Paketlisten…'})
            r = _do_check(host)

            # ansible_host aus dem Inventory holen
            inv = get_inventory()
            ansible_host_ip = inv.get('host_ips', {}).get(host, '')

            # Immer cachen (auch Fehler)
            save_host_status(
                host, r['status'], r['os_info'], r['packages'],
                ansible_host=ansible_host_ip,
                reboot_required=r.get('reboot_required', False),
                pkg_manager=r.get('pkg_manager', ''),
            )

            if r['status'] == 'error':
                yield sse({'type': 'error', 'msg': r['error_msg']})
            else:
                yield sse({
                    'type':            'result',
                    'host':            host,
                    'os_info':         r['os_info'],
                    'packages':        r['packages'],
                    'count':           len(r['packages']),
                    'ansible_host':    ansible_host_ip,
                    'reboot_required': r.get('reboot_required', False),
                    'pkg_manager':     r.get('pkg_manager', ''),
                })

        except Exception as e:
            yield sse({'type': 'error', 'msg': str(e)})

        yield sse({'type': 'done'})

    return Response(
        stream_with_context(generate()),
        content_type='text/event-stream',
        headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'},
    )


@app.route('/api/update', methods=['POST'])
@login_required
def api_update():
    data     = request.get_json(force=True)
    host     = data.get('host', '').strip()
    packages = data.get('packages', [])

    if not host:
        return jsonify({'error': 'Kein Host angegeben'}), 400

    # Username jetzt aus der Session lesen (im Request-Kontext, vor dem Streaming)
    triggered_by = session.get('username', '') if AUTH_ON else 'system'

    def generate():
        if AUTH_ON and not session.get('logged_in'):
            yield sse({'type': 'error', 'msg': 'Sitzung abgelaufen', 'reload': True})
            yield sse({'type': 'done'})
            return

        all_output = []
        try:
            # Get package manager from host_status
            with sqlite3.connect(DB_PATH) as conn:
                row = conn.execute('SELECT pkg_manager FROM host_status WHERE host = ?', (host,)).fetchone()
                pkg_manager = row[0] if row else ''

            # Determine module and args based on package manager
            if pkg_manager == 'apt':
                if packages:
                    ansible_arg = f'name="{",".join(packages)}" state=latest update_cache=yes'
                    label, action_type = f'{len(packages)} Paket(e)', 'install_selected'
                else:
                    ansible_arg = 'upgrade=full update_cache=yes'
                    label, action_type = 'alle verfügbaren Updates', 'upgrade_all'
                module = 'apt'
            elif pkg_manager in ('dnf', 'yum'):
                if packages:
                    ansible_arg = f"name={','.join(packages)} state=latest"
                    label, action_type = f'{len(packages)} Paket(e)', 'install_selected'
                else:
                    ansible_arg = "name=* state=latest"
                    label, action_type = 'alle verfügbaren Updates', 'upgrade_all'
                module = pkg_manager
            else:
                # Default to apt
                if packages:
                    ansible_arg = f'name="{",".join(packages)}" state=latest update_cache=yes'
                    label, action_type = f'{len(packages)} Paket(e)', 'install_selected'
                else:
                    ansible_arg = 'upgrade=full update_cache=yes'
                    label, action_type = 'alle verfügbaren Updates', 'upgrade_all'
                module = 'apt'

            yield sse({'type': 'status', 'msg': f'Installiere {label} auf {host}…'})

            install_cmd = [
                'ansible', host, '-i', ANSIBLE_INVENTORY,
                '-m', module, '-a', ansible_arg,
                '--become', '--timeout', '300', '-v',
            ]
            if ANSIBLE_USER:
                install_cmd += ['-u', ANSIBLE_USER]

            process = subprocess.Popen(
                install_cmd,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, bufsize=1,
            )

            for line in process.stdout:
                line = line.rstrip()
                if line:
                    all_output.append(line)
                    yield sse({'type': 'output', 'line': line})

            process.wait()
            status = 'success' if process.returncode == 0 else 'error'
            log_action(host, action_type, packages, status, '\n'.join(all_output), triggered_by)

            # Nach erfolgreicher Installation Status in DB aktualisieren
            if status == 'success':
                save_host_status(host, 'ok', '', [])

            yield sse({'type': 'done', 'status': status, 'returncode': process.returncode})

        except Exception as e:
            log_action(host, 'error', packages, 'error', str(e), triggered_by)
            yield sse({'type': 'error', 'msg': str(e)})
            yield sse({'type': 'done', 'status': 'error'})

    return Response(
        stream_with_context(generate()),
        content_type='text/event-stream',
        headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'},
    )


@app.route('/api/reboot', methods=['POST'])
@login_required
def api_reboot():
    """Startet einen kontrollierten Neustart via Ansible reboot-Modul (SSE)."""
    data = request.get_json(force=True)
    host = data.get('host', '').strip()

    if not host:
        return jsonify({'error': 'Kein Host angegeben'}), 400

    triggered_by = session.get('username', '') if AUTH_ON else 'system'

    def generate():
        if AUTH_ON and not session.get('logged_in'):
            yield sse({'type': 'error', 'msg': 'Sitzung abgelaufen', 'reload': True})
            yield sse({'type': 'done'})
            return

        all_output = []
        try:
            yield sse({'type': 'status', 'msg': f'Starte Neustart von {host}…'})

            reboot_cmd = [
                'ansible', host, '-i', ANSIBLE_INVENTORY,
                '-m', 'reboot',
                '-a', 'reboot_timeout=300 connect_timeout=30 post_reboot_delay=15',
                '--become', '--timeout', '360',
            ]
            if ANSIBLE_USER:
                reboot_cmd += ['-u', ANSIBLE_USER]

            process = subprocess.Popen(
                reboot_cmd,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, bufsize=1,
            )

            for line in process.stdout:
                line = line.rstrip()
                if line:
                    all_output.append(line)
                    yield sse({'type': 'output', 'line': line})

            process.wait()
            status = 'success' if process.returncode == 0 else 'error'
            log_action(host, 'reboot', [], status, '\n'.join(all_output), triggered_by)

            if status == 'success':
                # Neustart-ausstehend-Flag in der DB löschen
                with sqlite3.connect(DB_PATH) as conn:
                    conn.execute(
                        'UPDATE host_status SET reboot_required = 0 WHERE host = ?', (host,)
                    )

            yield sse({'type': 'done', 'status': status, 'returncode': process.returncode})

        except Exception as e:
            log_action(host, 'reboot', [], 'error', str(e), triggered_by)
            yield sse({'type': 'error', 'msg': str(e)})
            yield sse({'type': 'done', 'status': 'error'})

    return Response(
        stream_with_context(generate()),
        content_type='text/event-stream',
        headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'},
    )


@app.route('/api/schedule', methods=['GET', 'POST'])
@login_required
def api_schedule():
    """List scheduled jobs (GET) or create a new one (POST)."""
    if request.method == 'POST':
        data = request.get_json(force=True)
        host = data.get('host', '').strip()
        action = data.get('action', '').strip()
        packages = data.get('packages', [])
        scheduled_at = (data.get('scheduled_time') or data.get('scheduled_at', '')).strip()
        # Normalize: "2026-03-26T14:30" → "2026-03-26 14:30:00"
        scheduled_at = scheduled_at.replace('T', ' ')
        if len(scheduled_at) == 16:       # "YYYY-MM-DD HH:MM"
            scheduled_at += ':00'

        if not host or not action or not scheduled_at:
            return jsonify({'error': 'host, action, und scheduled_time erforderlich'}), 400

        if action not in ('reboot', 'update', 'update_all', 'update_selected'):
            return jsonify({'error': 'action muss "reboot", "update", "update_all" oder "update_selected" sein'}), 400

        # Normalize: update_all/update_selected → update (mit/ohne packages)
        if action in ('update_all', 'update_selected'):
            action = 'update'

        created_by = session.get('username', '') if AUTH_ON else 'system'
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        try:
            with sqlite3.connect(DB_PATH) as conn:
                cursor = conn.execute(
                    'INSERT INTO scheduled_jobs (host, action, packages, scheduled_at, created_at, created_by, status) '
                    'VALUES (?, ?, ?, ?, ?, ?, ?)',
                    (host, action, json.dumps(packages) if packages else None, scheduled_at, now, created_by, 'pending')
                )
                job_id = cursor.lastrowid
            return jsonify({'id': job_id, 'status': 'created'}), 201
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    else:  # GET
        # Filterparameter
        date_from = request.args.get('from')
        date_to   = request.args.get('to')
        host_f    = request.args.get('host') or None
        user_f    = request.args.get('user') or None
        status_f  = request.args.get('status') or None

        # Standard: letzte 7 Tage ODER Zukunft (pending), kein Filter gesetzt
        now_str   = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        seven_ago = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d 00:00:00')

        try:
            conditions = []
            params: list = []

            if date_from or date_to or host_f or user_f or status_f:
                # Expliziter Filter gesetzt
                if date_from:
                    conditions.append('scheduled_at >= ?')
                    params.append(date_from)
                if date_to:
                    conditions.append('scheduled_at <= ?')
                    params.append(date_to if len(date_to) > 10 else date_to + ' 23:59:59')
            else:
                # Standard: letzte 7 Tage + alles Zukünftige
                conditions.append('(scheduled_at >= ? OR status = "pending")')
                params.append(seven_ago)

            if host_f:
                conditions.append('host = ?')
                params.append(host_f)
            if user_f:
                conditions.append('created_by = ?')
                params.append(user_f)
            if status_f:
                conditions.append('status = ?')
                params.append(status_f)

            where = ('WHERE ' + ' AND '.join(conditions)) if conditions else ''
            sql = (
                f'SELECT * FROM scheduled_jobs {where} ORDER BY '
                'CASE WHEN status = "pending" THEN 0 ELSE 1 END, '
                'scheduled_at DESC'
            )
            with sqlite3.connect(DB_PATH) as conn:
                conn.row_factory = sqlite3.Row
                rows = conn.execute(sql, params).fetchall()

            result = []
            for row in rows:
                d = dict(row)
                d['scheduled_time'] = d.pop('scheduled_at', '')
                d['scheduled_by']   = d.pop('created_by', '')
                if d.get('packages'):
                    try:
                        d['packages'] = json.loads(d['packages'])
                    except Exception:
                        d['packages'] = []
                result.append(d)
            return jsonify(result)
        except Exception as e:
            return jsonify({'error': str(e)}), 500


@app.route('/api/schedule/<int:job_id>/cancel', methods=['POST'])
@login_required
def api_schedule_cancel(job_id):
    """Cancel a pending scheduled job."""
    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute(
                'UPDATE scheduled_jobs SET status = ? WHERE id = ? AND status = ?',
                ('cancelled', job_id, 'pending')
            )
        return jsonify({'status': 'cancelled'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/history')
@login_required
def api_history():
    date_from = request.args.get('from')
    date_to   = request.args.get('to')
    host      = request.args.get('host') or None
    user      = request.args.get('user') or None
    status    = request.args.get('status') or None
    return jsonify(get_history(date_from=date_from, date_to=date_to,
                               host=host, user=user, status=status))


@app.route('/api/history/<int:entry_id>/output')
@login_required
def api_history_output(entry_id):
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute('SELECT * FROM history WHERE id = ?', (entry_id,)).fetchone()
    if row is None:
        return jsonify({'error': 'Nicht gefunden'}), 404
    return jsonify(dict(row))


# ─── Start ────────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    init_db()

    # Scheduler starten (Auto-Check + Scheduled Jobs)
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        scheduler = BackgroundScheduler(daemon=True)

        # Automatischer Host-Check (deaktivierbar via interval_hours = 0)
        if CHECK_INTERVAL > 0:
            scheduler.add_job(
                run_scheduled_check,
                trigger='interval',
                hours=CHECK_INTERVAL,
                next_run_time=_first_run_time(),
            )
            print(f"✓ Auto-Check aktiv – alle {CHECK_INTERVAL} Stunden")
        else:
            print("  Auto-Check deaktiviert (interval_hours = 0 in config.ini)")

        # Scheduled Jobs Checker (immer aktiv – prüft alle 60s auf fällige Jobs)
        scheduler.add_job(
            run_scheduled_jobs_check,
            trigger='interval',
            seconds=60,
        )
        scheduler.start()
        print("✓ Scheduled Jobs Checker aktiv – alle 60 Sekunden")
    except ImportError:
        print("⚠ APScheduler nicht installiert – Auto-Check und Scheduled Jobs deaktiviert")
        print("  pip3 install apscheduler --break-system-packages")

    ssl_ctx = None
    if SSL_ON:
        if os.path.exists(SSL_CERT) and os.path.exists(SSL_KEY):
            ssl_ctx = (SSL_CERT, SSL_KEY)
            print(f"✓ HTTPS aktiv – {SSL_CERT}")
        else:
            print(f"⚠ SSL aktiviert aber Zertifikat fehlt: {SSL_CERT}")

    proto = 'https' if ssl_ctx else 'http'
    print(f"✓ patchsible läuft auf {proto}://{HOST}:{PORT}")
    print(f"  Auth: {'aktiv' if AUTH_ON else 'aus'}"
          + (f" · Gruppe: {ALLOWED_GROUP}" if ALLOWED_GROUP else ""))

    app.run(host=HOST, port=PORT, debug=False, ssl_context=ssl_ctx)
