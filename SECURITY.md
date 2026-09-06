# Security policy

## Supported versions

Security fixes are developed on `main`. Older tags do not receive independent
security backports. Use the latest reviewed source and rebuild deployed clients
when a security fix is released. A successful test run is not a security
certification.

## Reporting a vulnerability

Do not disclose vulnerability details, credentials, customer records, or proof
of exploitation in public issues, pull requests, or release attachments.

1. If the repository's **Security → Report a vulnerability** option is available,
   use GitHub's [private vulnerability reporting form](https://github.com/kariaymane/ATELIER_BERLIN_LOCATION_CAR/security/advisories/new).
2. If private reporting is unavailable, open an issue containing only a request
   for a private security contact. Wait for a maintainer to provide a private
   channel before sending any technical details. Do not attach evidence publicly.
3. Privately provide the affected version, a concise impact description, and
   minimal reproduction steps using synthetic data. Include a proposed fix if
   available, and coordinate disclosure with the maintainers.

The private reporting form requires the repository owner to enable the feature;
its availability should not be assumed. No response-time guarantee is offered.

## Deployment expectations

- Keep PostgreSQL on a private network. Clients must authenticate through the API,
  not connect to the database directly.
- Use HTTPS, restricted CORS origins, least-privilege accounts, and independent
  deployment secrets. Never distribute signing keys with source or installers.
- Limit access to customer identity documents, runtime caches, uploads, and backups.
  Treat them as private even when filenames are not human-readable.
- Test only on disposable databases with synthetic accounts and customer records.
- Keep dependencies updated and apply database migrations before starting a new
  application version.

If a credential has been exposed, revoke or rotate it and invalidate affected
sessions. Deleting a file or adding an ignore rule does not remove the value from
Git history, clones, forks, logs, or previously published artifacts. Coordinate
history remediation privately with the repository owner and hosting provider.
