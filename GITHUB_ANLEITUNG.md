# patchsible auf GitHub veröffentlichen – Schritt-für-Schritt

---

## 1. Vorbereitung: Was gehört ins Repository?

Bevor du etwas hochlädst, lege eine `.gitignore`-Datei im Projektordner an. Diese sorgt dafür, dass keine sensiblen oder unnötigen Dateien ins Repository gelangen.

**Datei: `.gitignore`**
```
# Python
__pycache__/
*.pyc
*.pyo
venv/

# Datenbank (enthält Produktionsdaten!)
patchsible.db

# Konfiguration mit Geheimnissen (secret_key, Passwörter)
config.ini

# Logs
*.log

# Windows
Thumbs.db

# SSL-Zertifikate
*.pem
*.key
*.crt
```

> **Wichtig:** `config.ini` enthält den `secret_key` und ggf. Zugangsdaten. Diese Datei **niemals** committen. Stattdessen eine `config.ini.example` ohne echte Werte bereitstellen.

Erstelle `config.ini.example` als Vorlage (ohne echte Werte):
```bash
cp config.ini config.ini.example
# Dann in config.ini.example alle echten Werte durch Platzhalter ersetzen, z.B.:
# secret_key = DEIN_SECRET_KEY_HIER
```

---

## 2. Git lokal einrichten

Falls noch nicht vorhanden, Git installieren:
```bash
sudo apt install git   # Debian/Ubuntu
```

Einmalig deinen Namen und deine E-Mail konfigurieren:
```bash
git config --global user.name "Dein Name"
git config --global user.email "deine@email.de"
```

Im Projektordner Git initialisieren:
```bash
cd /opt/patchsible          # oder wo du entwickelst
git init
git add .gitignore
git add app.py install.sh patchsible.service requirements.txt config.ini.example
git add templates/
git add README.md logo.png
```

> Prüfe vorher mit `git status`, was hinzugefügt wird. Stelle sicher, dass `config.ini` und `patchsible.db` **nicht** in der Liste stehen.

Ersten Commit erstellen:
```bash
git commit -m "Initial release: patchsible v0.1b"
```

---

## 3. GitHub-Repository erstellen

1. Gehe zu [github.com](https://github.com) und melde dich an (oder erstelle einen Account).
2. Klicke oben rechts auf **„+"** → **„New repository"**.
3. Fülle aus:
   - **Repository name:** `patchsible`
   - **Description:** `Web-based Linux Patch Management via Ansible`
   - **Visibility:** Public (für Open Source) oder Private
   - **Kein** Häkchen bei „Add a README" – du hast schon einen
4. Klicke **„Create repository"**.

GitHub zeigt dir dann Befehle. Du brauchst nur diese:
```bash
git remote add origin https://github.com/DEIN-USERNAME/patchsible.git
git branch -M main
git push -u origin main
```

---

## 4. Versionierung mit Git Tags

Patchsible nutzt **Semantic Versioning**: `MAJOR.MINOR.PATCH`

| Teil    | Bedeutung                                      | Beispiel |
|---------|------------------------------------------------|----------|
| MAJOR   | Grundlegende, inkompatible Änderung            | 1.0.0 → 2.0.0 |
| MINOR   | Neue Funktion, rückwärtskompatibel             | 0.1.0 → 0.2.0 |
| PATCH   | Bugfix, keine neuen Features                   | 0.1.0 → 0.1.1 |

Beispiele für patchsible:
- `v0.1.0` – erste öffentliche Beta
- `v0.1.1` – Bugfix (z.B. Scheduler-Fix)
- `v0.2.0` – neue Funktion (z.B. Filter in History)
- `v1.0.0` – stabiles erstes Release

### Tag erstellen und pushen

Nach einem Release-Commit:
```bash
# Leichtgewichtiger Tag (nur Markierung)
git tag v0.1.0

# Annotierter Tag (empfohlen – enthält Datum, Name, Nachricht)
git tag -a v0.1.0 -m "Erste öffentliche Beta – Grundfunktionen stabil"

# Tag auf GitHub pushen
git push origin v0.1.0

# Alle Tags auf einmal pushen
git push origin --tags
```

---

## 5. GitHub Release erstellen (Download-Seite)

Ein „Release" ist die offizielle Download-Seite für eine Version – mit Changelog und ggf. ZIP-Download.

1. Gehe auf GitHub zu deinem Repository.
2. Rechts auf **„Releases"** klicken → **„Create a new release"**.
3. Wähle deinen Tag (z.B. `v0.1.0`) aus oder erstelle einen neuen.
4. Fülle aus:
   - **Release title:** `v0.1.0 – Erste Beta`
   - **Beschreibung (Changelog):** Was ist neu, was wurde gefixt
5. Optional: Eine fertige `.zip` oder `install.sh` als Asset hochladen.
6. Klicke **„Publish release"**.

---

## 6. Empfohlener Entwicklungs-Workflow

### Branches

```
main        ← immer stabil, nur fertige Releases
develop     ← laufende Entwicklung
feature/xyz ← einzelne neue Features
hotfix/xyz  ← dringende Bugfixes für main
```

Workflow in der Praxis:
```bash
# Neues Feature entwickeln
git checkout -b feature/mein-feature develop

# ... Entwicklung ...
git add .
git commit -m "feat: neue Funktion XYZ eingebaut"

# Feature fertig: in develop mergen
git checkout develop
git merge feature/mein-feature
git push origin develop

# Release vorbereiten
git checkout main
git merge develop
git tag -a v0.2.0 -m "v0.2.0 – Neue Funktion XYZ"
git push origin main --tags
```

---

## 7. Guter Commit-Stil

Verwende aussagekräftige Commit-Nachrichten. Die weit verbreitete **Conventional Commits**-Konvention:

```
feat: Filterleiste in History und Geplante Aufgaben
fix: Scheduler führt Jobs jetzt korrekt aus
fix: Datetime-Format-Fehler beim Planen behoben
chore: flask-socketio und paramiko entfernt
docs: README aktualisiert
```

Präfixe: `feat` (neu), `fix` (Bugfix), `chore` (Aufräumen), `docs` (Doku), `refactor` (Umbau ohne neue Funktion)

---

## 8. Täglicher Arbeitsablauf (Kurzreferenz)

```bash
# Status prüfen
git status
git diff

# Änderungen stagen
git add app.py templates/index.html

# Committen
git commit -m "fix: SSH-Feature und Migrations-Code entfernt"

# Auf GitHub pushen
git push

# Nach einem Release: Tag erstellen und pushen
git tag -a v0.1.1 -m "Bugfixes: SSH entfernt, Werkzeug-Fehler behoben"
git push origin --tags
```

---

## 9. README pflegen

Das `README.md` ist die Visitenkarte des Projekts auf GitHub. Es sollte enthalten:

- **Was ist patchsible?** (Kurzbeschreibung)
- **Features** (was kann es?)
- **Installation** (Verweis auf `install.sh`)
- **Anforderungen** (Debian/Ubuntu, Python 3.10+, Ansible)
- **Konfiguration** (Verweis auf `config.ini.example`)
- **Screenshots** (optional, aber sehr empfehlenswert)
- **Lizenz** (z.B. MIT, GPL)

---

## 10. Lizenz hinzufügen

Ohne Lizenz darf niemand den Code nutzen, auch wenn er öffentlich ist. Empfehlung für Open Source:

**MIT-Lizenz** (sehr permissiv, weit verbreitet):

Erstelle eine Datei `LICENSE` mit dem MIT-Text:
```
MIT License

Copyright (c) 2026 Lukas Lehmann

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software...
```
Den vollständigen Text gibt es auf github.com → beim Erstellen des Repos „Add a license" wählen → MIT.

---

## Schnellstart-Checkliste

- [ ] `.gitignore` erstellt (config.ini ausgenommen!)
- [ ] `config.ini.example` mit Platzhaltern erstellt
- [ ] `LICENSE` hinzugefügt
- [ ] `README.md` aktualisiert
- [ ] Erstes `git init` + `git add` + `git commit`
- [ ] Repository auf GitHub erstellt
- [ ] `git remote add origin ...` + `git push`
- [ ] Ersten Tag `v0.1.0` erstellt und gepusht
- [ ] GitHub Release angelegt

---

*Erstellt für patchsible – Linux Patchmanagement Dashboard*
