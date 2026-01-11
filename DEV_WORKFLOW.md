# Homelab Development Workflow

## Roles

- **Gaming PC (`/mnt/data/homelab-dev`)**
  - Sole authoring environment
  - All edits originate here
  - VS Code + Claude used for reasoning and refactoring
  - Commits and pushes happen only here

- **GitHub**
  - Canonical history
  - Contract between intent and execution

- **Raspberry Pi (`/opt/homelab`)**
  - Execution environment only
  - No direct editing
  - Pulls from GitHub and runs containers

---

## Authoring Rules

- All changes must be git-tracked
- No manual edits on the Pi
- Runtime state is never modified directly
- Claude may suggest edits but does not execute commands

---

## Deployment Procedure

On the Raspberry Pi only:

```bash
cd /opt/homelab
git pull
docker compose up -d
