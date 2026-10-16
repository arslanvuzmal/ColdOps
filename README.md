<div align="center">

# ⚡ TITAN-OS (ColdOps)
### *The Sovereign, Evidence-First Autonomous Sales Intelligence & Controlled Outreach Engine*

[![Production Status](https://img.shields.io/badge/Status-v0.2.0%20Hardened-0ea5e9?style=for-the-badge&logo=rocket&logoColor=white)](docs/audits/FINAL-PRODUCTION-VERIFICATION.md)
[![Safety Invariants](https://img.shields.io/badge/Safety%20Invariants-22%2F22%20Enforced-10b981?style=for-the-badge&logo=shieldcheck&logoColor=white)](docs/audits/FINAL-PRODUCTION-VERIFICATION.md)
[![Python Test Suite](https://img.shields.io/badge/Python%20Tests-477%20Passed-3b82f6?style=for-the-badge&logo=python&logoColor=white)](apps/api/tests)
[![TypeScript Tests](https://img.shields.io/badge/TS%20Tests-14%20Passed-3178c6?style=for-the-badge&logo=typescript&logoColor=white)](apps/browser-worker)
[![Next.js](https://img.shields.io/badge/Next.js-16%20App%20Router-black?style=for-the-badge&logo=nextdotjs&logoColor=white)](apps/web)
[![Temporal](https://img.shields.io/badge/Workflows-Temporal%20Durable-black?style=for-the-badge&logo=temporal&logoColor=white)](apps/api/titan/workflows)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16%20RLS%20Isolated-336791?style=for-the-badge&logo=postgresql&logoColor=white)](apps/api/titan/db)
[![License](https://img.shields.io/badge/License-Proprietary%20%2F%20MIT-8b5cf6?style=for-the-badge)](LICENSE)

<br/>

**[🌐 Live Command Center](https://titan-os-three.vercel.app)** • **[🏛️ Architecture Blueprint](#-system-architecture)** • **[🛡️ 22 Invariants](#-the-22-safety-invariants)** • **[🚀 Quickstart](#-rapid-local-setup)** • **[📑 Audit & Verification Report](docs/audits/FINAL-PRODUCTION-VERIFICATION.md)**

<br/>

> **"Titan-OS observes before it pitches, proves before it claims, and refuses to send when it cannot show its working."**  
> *A generative model can draft a message; only an isolated transactional outbox worker can deliver one, and only after every deterministic gate has passed.*

---

</div>

<br/>

## 🌟 Executive Overview

**Titan-OS (ColdOps)** is an enterprise autonomous sales intelligence and controlled outreach operating system engineered to eliminate hallucinated claims, unauthorized emails, deliverability burning, and silent multi-send loops. 

Traditional AI outreach platforms wire LLMs directly to email APIs. When a model hallucinates a customer fact or misfires an outreach trigger, companies suffer severe domain reputation degradation, CAN-SPAM violations, and legal liability. 

Titan-OS operates on a **zero-trust, evidence-first substrate**:
1. **No Evidence, No Claim**: Every single assertion in an outreach message must trace through an immutable claim map to an SHA-256 verified DOM snapshot captured by an isolated browser.
2. **Zero Direct Send Architecture**: Models **cannot** send mail. Email delivery credentials are mathematically isolated behind an atomic, transactional outbox worker. An AST static-analysis scanner runs in CI to guarantee that no module outside the outbox worker ever imports an email client.
3. **Four Independent Physical Gates**: Process kill switch, tenant workspace authorization, SPF/DKIM/DMARC preflight acknowledgement, and physical sender identity validation.
4. **Guessed Addresses Structurally Ineligible**: `pattern_guess` email sources are structurally rejected at the type and database level.

---

## 🏛️ System Architecture

Titan-OS enforces strict microservice isolation, preventing arbitrary code or browser escapes from compromising outreach credentials or tenant databases.

```mermaid
flowchart TD
    subgraph DiscoveryLayer["1. Discovery & Intelligence Surface"]
        Places[Google Places Adapter] --> LeadDedup[Lead Deduplication Engine]
        Webhooks[Inbound Webhooks] --> LeadDedup
        LeadDedup --> DB_Leads[(PostgreSQL 16 RLS)]
    end

    subgraph BrowserIsolation["2. Zero-Credential Browser Worker (Sandbox)"]
        ResearchReq[Crawl Target Domain] --> SSRF[Strict SSRF Guard: IPv6/IPv4/DNS-Pinning]
        SSRF --> Playwright[Playwright Headless Engine]
        Playwright --> DOMExtract[Immutable DOM Snapshot & Hashes]
        DOMExtract --> EvidenceStore[(Evidence & Findings DB)]
    end

    subgraph ModelGatewayLayer["3. Circuit-Broken Model Gateway"]
        EvidenceStore --> ClaimMapper[Deterministic Claim Mapper]
        ClaimMapper --> Gateway[Model Gateway: NVIDIA / OpenRouter / Cloudflare]
        Gateway --> DraftGen[Message Draft Synthesizer]
        DraftGen --> Validator[73-Rule Invariant Validator]
    end

    subgraph HumanGate["4. Human-in-the-Loop Operator CRM"]
        Validator --> AwaitingApproval{Operator Approval Queue}
        AwaitingApproval -- "Approve with Version Pin" --> OutboxQueue
        AwaitingApproval -- "Changes Requested / Reject" --> DraftGen
    end

    subgraph OutboxIsolation["5. Delivery Chokepoint & Transactional Outbox"]
        OutboxQueue[Atomic Outbox Lease] --> QuotaGate{Atomic Quotas & Suppression}
        QuotaGate -- "Blocked" --> DeadLetter[Suppression / Hold]
        QuotaGate -- "Passed" --> PreflightCheck{4-Gate Verification}
        PreflightCheck -- "SPF/DKIM/Mode Valid" --> ProviderDispatcher[Outbox Worker]
    end

    subgraph CarrierDelivery["6. Verified Carrier Adapters"]
        ProviderDispatcher --> Resend[Resend Adapter]
        ProviderDispatcher --> Smartlead[Smartlead Carrier Adapter 1-Step]
    end

    style BrowserIsolation fill:#0f172a,stroke:#38bdf8,stroke-width:2px,color:#fff
    style OutboxIsolation fill:#0f172a,stroke:#f43f5e,stroke-width:2px,color:#fff
    style HumanGate fill:#0f172a,stroke:#10b981,stroke-width:2px,color:#fff
    style ModelGatewayLayer fill:#0f172a,stroke:#818cf8,stroke-width:2px,color:#fff
```

### Component Isolation Boundaries
- **Browser Worker (`apps/browser-worker`)**: Operates in an isolated container holding **zero** database, email, or model credentials. A full browser escape yields no secrets and cannot send email or access tenant data.
- **Backend API (`apps/api/titan`)**: FastAPI + SQLAlchemy 2.0 with PostgreSQL Row-Level Security (RLS) enforcing complete workspace isolation across all models.
- **Operator CRM (`apps/web`)**: Next.js 16 App Router interface providing real-time evidence inspection, version-pinned approvals, and telemetry HUD.

---

## 🚦 Subsystem Implementation Status

Titan-OS strictly adheres to empirical status classification. **Live-verified** indicates authentic credentialed execution with real external services.

| Subsystem / Component | Technical Implementation | Verified State |
|:---|:---|:---:|
| **PostgreSQL 16 Schema & RLS** | 45 tables, 42 RLS-isolated, 14 immutability triggers | 🟢 Integration-Tested |
| **SSRF Firewall Guard** | Pinned-IP DNS resolution, IPv6 unwrapping, metadata blocking | 🟢 61 Unit + Hypothesis Tests |
| **Browser Evidence Worker** | Playwright Chromium crawler, selector-pinned findings | 🟢 Unit-Tested & TypeScript Clean |
| **Policy Engine & Operating Modes** | 4 Operating Modes (`audit`, `research`, `draft`, `live`) | 🟢 51 Tests Passed |
| **Intelligence, Scoring & Claims** | Findings verification, claim-to-DOM mapping, playbooks | 🟢 73 Tests Passed |
| **Transactional Outbox Engine** | Concurrent row leasing, atomic quotas, suppression lists | 🟢 8-Worker Chaos Tested |
| **Google Places Discovery** | Real credentialed query execution, place resolution | 🟢 **Live-Verified** |
| **Model Gateway** | Multi-provider fallback (NVIDIA NIM, OpenRouter, Cloudflare) | 🟢 **Live-Verified** |
| **Temporal Durable Workflows** | Approval deadlines, non-duplicating activity retry state | 🟢 Temporal Test Server |
| **REST Resource Surface (`/api/v1`)** | Argon2id JWT authentication, database-authoritative RBAC | 🟢 38 Integration Tests |
| **Operator CRM Desk (`/crm`)** | Evidence-first UI, split-view claims, real-time HUD | 🟢 Browser-Verified |
| **Resend Delivery Adapter** | Transactional email delivery with webhook signature checks | 🔵 Implemented · Mock Verified |
| **Smartlead Delivery Adapter** | Enforces single-sequence-step carrier campaign safety check | 🔵 Implemented · Unit Tested |
| **Follow-Up Scheduler** | Multi-touch sequence pacing with auto-halt on reply | 🟡 Phase 9 Implementation |
| **Inbound Reply Classifier** | Webhook sentiment classification & instant sequence cancellation | 🟡 Schema & Stop-On-Reply Ready |

---

## 🛡️ The 22 Safety Invariants

Titan-OS implements 22 non-negotiable architectural safety invariants. Static AST analyzers and continuous integration suites enforce these invariants against every pull request:

<details open>
<summary><b>Click to expand the 22 Invariant Safeguards</b></summary>
<br/>

| # | Invariant Rule | Enforcement Mechanism | Code Location |
|:---:|:---|:---|:---|
| **01** | **No Model Direct Send** | AST scan fails CI if any file other than outbox worker imports an email client | `tests/invariants/test_no_direct_send.py` |
| **02** | **No Evidence, No Claim** | Sentences asserting recipient facts must trace to a verified DOM artifact | `titan/intelligence/validator.py` |
| **03** | **SSRF Multi-Vector Shield** | DNS rebinding defeat, 0.0.0.0/8 block, metadata IP denylist, scheme allowlist | `titan/security/url_guard.py` |
| **04** | **Four-Gate Send Barrier** | Process kill switch + Workspace switch + SPF/DKIM ack + Physical address | `titan/policy/gates.py` |
| **05** | **Zero Guessed Addresses** | `pattern_guess` strictly forbidden from eligible-contact enum | `titan/intelligence/contacts.py` |
| **06** | **Atomic Quota Reservation** | Daily send limit decremented atomically via database transaction lock | `titan/delivery/outbox_worker.py` |
| **07** | **Instant Reply Suppression** | Any inbound communication immediately halts pending outbox deliveries | `titan/delivery/suppression.py` |
| **08** | **Single-Step Carrier Cap** | Smartlead adapter rejects any campaign having more than 1 sequence step | `titan/delivery/providers/smartlead.py` |
| **09** | **Row-Level Tenant Isolation** | PostgreSQL RLS guarantees complete isolation between workspace tenants | `titan/db/models/base.py` |
| **10** | **Version-Pinned Human Approvals**| Approvals bind to draft SHA/version; concurrent edits reject approval with 409 | `titan/api/v1/approvals.py` |
| **11** | **Exactly-Once Delivery** | Outbox message lease prevents duplicate deliveries during node crashes | `titan/delivery/lease.py` |
| **12** | **Credential-Free Browser Worker**| Headless crawler holds no db/email/API secrets whatsoever | `apps/browser-worker` |
| **13** | **Circuit-Broken LLM Gateway** | Budget caps, request timeouts, and token circuit-breakers prevent runaway costs| `titan/models/gateway.py` |
| **14** | **Structured Secret Redaction** | Logging layer redacts API tokens, emails, and sensitive headers | `titan/security/redaction.py` |
| **15** | **Domain Velocity Throttling** | Maximum 2 messages per recipient company domain per 24-hour window | `titan/policy/rate_limiter.py` |
| **16** | **Deterministic Workflow Engine**| Temporal workflows run with time-skipping validation and 7-day deadlines | `titan/workflows/` |
| **17** | **Mandatory Unsubscribe Link** | Outbox worker rejects any email payload missing unsubscribe headers/tokens | `titan/delivery/headers.py` |
| **18** | **Physical Sender Identification** | CAN-SPAM compliant postal address mandatory in message footer | `titan/cli.py preflight` |
| **19** | **Monotonic Webhook Processing** | Out-of-order delivery webhooks are re-sequenced or dropped safely | `titan/delivery/webhooks.py` |
| **20** | **Independent Clean Room Substrate** | Zero dependency on legacy unverified scraping libraries | `pyproject.toml` |
| **21** | **Default-Deny Production Send** | `TITAN_PRODUCTION_SENDING_ENABLED` defaults to `False` in all environments | `titan/config.py` |
| **22** | **Vacuous Mode Safety** | Research & Draft modes operate safely with no transmission capability | `titan/policy/modes.py` |

</details>

---

## ⚡ The Four Physical Delivery Gates

Outreach delivery is protected by four independent, non-bypassable barriers. If a single gate is closed, the message remains safely in the outbox:

```
+-----------------------------------------------------------------------------------------+
|                                    DELIVERY GATES                                       |
+---------------------------+---------------------------+---------------------------------+
| Gate                      | Parameter / Requirement   | Purpose                         |
+---------------------------+---------------------------+---------------------------------+
| 1. Global Process Gate    | TITAN_PRODUCTION_SENDING  | Hardware/operator kill switch   |
| 2. Tenant Workspace Gate  | sending_authorized = true | Workspace admin explicit opt-in |
| 3. Domain Auth Preflight  | SPF / DKIM / DMARC Ack    | Prevents burning fresh domains  |
| 4. Compliance Identity    | SENDER_MAILING_ADDRESS    | CAN-SPAM legal compliance       |
+---------------------------+---------------------------+---------------------------------+
```

Inspect gate status at any time via the operator CLI:
```bash
python -m titan.cli preflight
```

```text
PROCESS GATE CLOSED: 4 blocker(s).
  - TITAN_PRODUCTION_SENDING_ENABLED is false (global kill switch)
  - TITAN_EMAIL_PROVIDER is 'mock'; no real provider configured
  - TITAN_EMAIL_AUTH_PREFLIGHT_ACKNOWLEDGED is false (SPF/DKIM/DMARC not acknowledged)
  - TITAN_SENDER_MAILING_ADDRESS is not set
```

---

## 💻 Tech Stack & Monorepo Topology

```
ColdOps/
├── apps/
│   ├── api/                    # Core Python Engine (FastAPI, SQLAlchemy 2.0, Alembic, Temporal)
│   │   ├── titan/              # Modular Domain Logic (Security, Policy, Delivery, Intelligence)
│   │   └── tests/              # 477 Unit, Integration, Invariant & Chaos Tests
│   ├── browser-worker/         # Zero-Credential Headless Playwright Browser Service (Node/TS)
│   └── web/                    # Operator CRM & Telemetry Command Center (Next.js 16, React 19, Tailwind v4)
├── packages/
│   ├── contracts/              # Shared Protocol Models & JSON Schemas
│   ├── db/                     # Prisma ORM Database Client & Migrations
│   └── shared/                 # Common TypeScript Types & Utilities
├── docs/                       # Comprehensive System Audits, Security & Threat Model
└── deploy/                     # Docker Compose Orchestration & Production Scaffolding
```

---

## 🚀 Rapid Local Setup

### Prerequisites
- **Python 3.11+**
- **Node.js 20+** & **pnpm 9+**
- **Docker & Docker Compose**

### 1. Launch Infrastructure
```bash
git clone https://github.com/arslanvuzmal/ColdOps.git
cd ColdOps

# Spin up isolated PostgreSQL with pgvector
docker compose up -d postgres
```

### 2. Configure Backend Engine
```bash
cd apps/api

# Create virtual environment & install dependencies
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
pip install -e ".[dev]"

# Configure Environment
export TITAN_DATABASE_URL="postgresql+psycopg://titan:titan_dev_password@localhost:5432/titan"

# Run database migrations
alembic upgrade head

# Execute the complete test suite
python -m pytest tests -q
```

### 3. Launch Isolated Browser Worker
```bash
cd ../browser-worker
pnpm install
npx playwright install chromium
pnpm test
pnpm start
```

### 4. Start Next.js Operator CRM
```bash
cd ../web
pnpm install
pnpm dev
```
Open **[http://localhost:3000](http://localhost:3000)** to access the Operator CRM Command Center.

---

## 📚 Technical Documentation & Audits

| Document | Description |
|:---|:---|
| 📄 **[Final Production Verification](docs/audits/FINAL-PRODUCTION-VERIFICATION.md)** | Empirical record of test runs, live-verified endpoints, and known residual gaps |
| 🔍 **[Production Gap Analysis](docs/audits/PRODUCTION-GAP-ANALYSIS.md)** | Detailed forensic audit identifying 74 findings against legacy prototypes |
| 🛡️ **[Threat Model & Attack Surface](docs/security/THREAT-MODEL.md)** | Comprehensive STRIDE threat analysis and countermeasure map |
| 🔒 **[Security Controls Inventory](docs/security/SECURITY-CONTROLS.md)** | Defense-in-depth security catalog (SSRF firewall, rate limiters, token hashing) |
| 📋 **[Production Enablement Checklist](docs/PRODUCTION-ENABLEMENT-CHECKLIST.md)** | Mandatory steps required before unsealing production outreach |
| 🔬 **[Upstream Engineering Research](docs/research/UPSTREAM-ENGINEERING-RESEARCH.md)** | Evaluation of external cold email architectures and design decisions |

---

## 👤 Author & Architecture Lead

**Arslan Vuzmal Lone**  
*Lead Systems Architect & AI Engineer*  
🌐 **Website:** [arslanvuzmallone.vercel.app](https://arslanvuzmallone.vercel.app/) • [arslanvuzmallone.com](https://arslanvuzmallone.com)  
🐙 **GitHub:** [@arslanvuzmal](https://github.com/arslanvuzmal)  
✉️ **Email:** [arslanvuzmallone@gmail.com](mailto:arslanvuzmallone@gmail.com)

---

<div align="center">
<sub>Built with precision. Evidence-first. Zero hallucinations. Zero unauthorized sends.</sub><br/>
<sub>© 2026 Arslan Vuzmal Lone. All rights reserved.</sub>
</div>
