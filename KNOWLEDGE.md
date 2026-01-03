# Homelab Knowledge Base

This document explains *why* the homelab is configured the way it is.
It complements the auto-generated inventory snapshots.

Inventory source of truth:
- /opt/homelab/inventory/latest/

---

## Design Principles

- Containers are disposable; data is not
- Declarative config over imperative fixes
- Observability before optimization
- Security boundaries are intentional, not default

---

## Network Model (Why These Ports Exist)

See:
- inventory/latest/docker_networks.json
- inventory/latest/containers/*.json

Notes:
- Host networking is used only where discovery requires it
- Cross-VLAN access is explicitly allowed for specific services
- No “any-any” rules without a written reason

---

## Storage Model (Why Volumes Are Mapped This Way)

See:
- inventory/latest/docker_volumes.json
- docker-compose.yaml

Notes:
- Bind mounts used for data portability
- Volumes chosen for clarity over abstraction
- Backup scope aligns exactly with data mounts

---

## Service-Specific Notes

### Home Assistant
Why it exists:
- Central automation brain
- Requires host networking for discovery

Tradeoffs accepted:
- Broader network access in exchange for functionality

---

### Scrypted
Why it exists:
- Camera ingestion and HomeKit integration

Tradeoffs accepted:
- Non-trivial port exposure
- Higher complexity justified by performance

---

## Backup & Restore Philosophy

Backups:
- Off-device, encrypted, daily
- Inventory snapshot precedes backup

Restore:
- Rebuild host
- Restore /opt/homelab
- docker compose up -d

Inventory explains expected state.
