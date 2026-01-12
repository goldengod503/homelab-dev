# Canonical Documents & Definitions

This document enumerates the **authoritative (canonical) documents, directory trees, and system definitions** for this environment. Anything listed here is treated as the source of truth. Changes to canon must be explicit, intentional, and documented.

---

## 1. Canonical Directory Trees

### 1.1 Gaming PC / Development Machine

**Canonical file:** `GamingPC_DirectoryTree_011226a.txt`

**Status:** Canonical as of **2026-01-12**

**Scope:**
- Filesystem layout
- AI model storage
- Development workflows
- Experimentation boundaries

This directory tree defines:
- Where AI models, caches, and vector databases live
- How experiments, scratch work, and production-adjacent code are separated
- Which directories are considered durable vs ephemeral

Any future tooling, scripts, or documentation **must align with this tree** unless canon is explicitly updated.

---

## 2. Canonical Homelab Documents

### 2.1 Backup Pipeline Definition

**Canonical file:** `HOMELAB_BACKUP_PIPELINE_EXPLAINED_V4.md`

**Status:** Canonical

**Scope:**
- Backup behavior
- Encryption model
- Snapshot contents
- Restore guarantees

**Rules:**
- This document is the sole authority on how backups work
- Any modification to backup behavior requires:
  - Updating this file
  - Incrementing the version number by +1
- Scripts must conform to this document, not the other way around

This document functions as the **backup constitution**.

---

## 3. Canonical System Definitions

### 3.1 Raspberry Pi Homelab Architecture

- Exactly **one** Docker Compose project
- Root directory: `/opt/homelab`
- Managed via `COMPOSE_FILE`
- All containers are conceptually part of a single system

Fragmented or ad-hoc compose stacks are non-canonical.

---

### 3.2 Hardware Context Separation

The following environments are **strictly separate**:

- Raspberry Pi homelab
- Mini-PC
- Gaming PC / development machine

Assumptions, paths, performance characteristics, and instructions must not bleed between these systems.

---

## 4. Canon Governance Rules

- Canon only changes by **explicit declaration**
- Drift does not update canon
- If reality changes, canon must be updated to match — intentionally

When ambiguity exists, the existing canon prevails until replaced.

---

## 5. Non-Canonical (Informational Only)

The following are useful but not authoritative unless promoted:

- Experimental scripts
- Monitoring dashboards
- Benchmarks
- Hardware preferences
- Draft documentation

These may evolve freely without impacting canon.

---

## 6. Purpose

This document exists to:
- Prevent configuration drift
- Preserve system intent over time
- Enable safe iteration without rewriting history

Canon is how this system remembers what it is.

