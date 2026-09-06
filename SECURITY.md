# Security Policy

## Supported Versions

Only the latest release version receives active security updates and vulnerability patches.

| Version | Supported          |
| ------- | ------------------ |
| 1.1.x   | :white_check_mark: |
| < 1.1.0 | :x:                |

---

## Reporting a Vulnerability

The project security team takes security and privacy vulnerabilities seriously. If you discover a potential vulnerability or security exposure, please disclose it responsibly.

### How to Report

- **Email**: Send vulnerability reports directly to the maintainers at `security@atelierberlin.test` or open a private security advisory through GitHub Security Advisories.
- **Details to Include**:
  - Description of the vulnerability and potential impact.
  - Clear steps to reproduce or a minimal proof of concept (PoC).
  - Affected components (Backend API, Desktop client, Mobile application, or Infrastructure configurations).

### Process & Expectations

1. **Acknowledgment**: Reports will be acknowledged within 48 hours.
2. **Investigation & Remediation**: A preliminary assessment and proposed mitigation will be communicated within 7 business days.
3. **Disclosure Policy**: Please refrain from publicly disclosing the issue until a patch has been released.

---

## Security Architecture Principles

- **Zero Hardcoded Secrets**: Secrets and credentials are never stored in source code. Configuration is managed via isolated environment secrets and variables.
- **Least Privilege**: All automated CI/CD workflows enforce minimal required permissions (`contents: read`).
- **Cryptographic Security**: Passwords are protected using Argon2id hashing. API authentication utilizes short-lived JWT access tokens and rotating refresh tokens.
- **Data Protection**: Client identification files and sensitive documents are stored with unguessable unique identifiers, validated by magic bytes, and restricted via strict Role-Based Access Control (RBAC).
