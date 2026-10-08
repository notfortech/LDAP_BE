# LDAP_BE — Aptus backend

Backend for the Aptus Capability Intelligence Platform: a deterministic
capability assessment engine and the service that exposes it.

## Layout

```
engine/     Deterministic scoring engine — pure Python, no dependencies,
            versioned configuration, generated evidence basis
api/        FastAPI service (not yet built)
```

## Principles

These are load-bearing. Everything else is subordinate to them.

1. **Determinism over inference.** No language model participates in any
   score, ever. Scoring is a pure function of responses and versioned
   configuration — no clock, no randomness, no I/O. A golden-master
   suite enforces this on every build.
2. **Traceability.** Every result records the configuration version and
   a SHA-256 digest of the configuration that produced it, so any
   historical result can be reproduced exactly.
3. **No automated contact with framework sources.** Nothing in this
   system makes requests to training.gov.au, ACARA, the ABS or Jobs and
   Skills Australia. Reference data is human-entered and versioned.
4. **Tenant isolation as a trust gate.** Every record is organisation-
   scoped. No query path may return another tenant's rows.
5. **Honest positioning.** The platform measures capability and
   behavioural signal. It is not a validated psychometric instrument and
   is never described as one. See `engine/EVIDENCE.md`.

## Getting started

```bash
cd engine
pip install -e ".[dev]"
pytest
```

## Status

| Component | State |
|---|---|
| Deterministic engine | Built — 25 tests, determinism gate in CI |
| Evidence basis | Built — generated from configuration |
| API service | Not started |
| Organisations and membership | Not started |
| Authentication hardening | Not started |
| Database migrations | Not started |

The backlog driving the remaining work is the backend story set: an
eight-story MVP covering the organisation model, self-serve signup, the
auth boundary, tenant-isolation testing, rate limiting and migrations.
