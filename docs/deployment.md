# Deployment

## API and database

`docker/Dockerfile.backend` is the authoritative backend image definition.
`docker/compose.yml` provides persistent database and upload volumes, a private
PostgreSQL network, and a loopback-bound API port. It runs the API as a non-root
user. Configure secrets in the ignored `docker/.env` file or your deployment's
secret manager; start with `docker/.env.example`.

Before deployment:

1. Choose strong, independent database and JWT credentials. Do not reuse example
   or test values. The Compose DSN interpolation expects a URL-safe database
   password.
2. Put an HTTPS reverse proxy in front of the API. Only expose its HTTPS port to
   clients; never publish PostgreSQL. For a containerized proxy, attach the proxy
   to the application network rather than exposing the database network.
3. Keep `DEBUG=false`, restrict browser CORS origins, and set a connection-pool
   budget appropriate for the database. Each API worker owns its own pool.
4. Back up the database and uploads before upgrading. Run `alembic upgrade head`
   with the same image and configuration as the API.
5. Start the API and verify `/health/ready`. Remove `ADMIN_PASSWORD` from deployment
   configuration after initial administrator provisioning and restart the API.
   Changing that bootstrap variable does not reset an existing account's password.

The realtime broadcaster is currently process-local. Use one API process/instance
unless a shared event transport is introduced. API reconnect and retry handling
must remain enabled. Client caches and the desktop pending-write queue still
exist; an API-only client migration requires separate application changes.

For managed PostgreSQL, configure the async driver with the provider's required
TLS settings and keep database access restricted to the application's private
network. Do not place a production hostname, DSN, or credential in tracked files.

## Fly.io template

`docker/fly.toml.example` is a provider template, not a live deployment config.
Copy it to the ignored `docker/fly.toml`, set your own app name and region, and
provision the upload volume in that region. Configure database URLs and JWT keys
through Fly secrets, not TOML. The database must not have a public listener.

Deploy from the repository root with:

```sh
fly deploy --config docker/fly.toml
```

The release command applies migrations. Verify the volume is mounted at
`/app/uploads` and that backups include it; a container filesystem alone is not
durable storage.

## Backups and restore

Use `scripts/backup.sh` with the Compose stack. It writes a PostgreSQL custom-format
archive to a private directory outside the repository by default. Set `BACKUP_DIR`
to override that destination, or `COMPOSE_ENV_FILE` to select another ignored
configuration file. Treat database archives as sensitive customer data and encrypt
and restrict them according to your retention policy.

`scripts/restore.sh <archive.dump> --confirm` restores into the configured stack
and replaces existing database objects. Stop the API first, take a fresh backup,
and verify the target configuration. Test recovery on a disposable deployment
before relying on it. Upload files require a separate volume backup and restore;
these scripts do not include them.

## Windows desktop

On Windows, from the repository root:

```powershell
.\packaging\windows\build_windows.ps1
```

The script creates an isolated packaging environment and uses the single spec at
`packaging/windows/ATELIER_BERLIN_LOCATION_CAR.spec`. Output is under
`packaging/windows/dist/`, which is ignored. Configure `API_BASE_URL` at runtime;
no deployment endpoint or credentials are embedded by this script. Windows code
signing is not configured; provide an approved signing process before distributing
installers to customers.

## Android releases

Debug builds use Android's standard debug signing. For release APKs and bundles,
provide these values through a private build environment:

| Setting | Purpose |
| --- | --- |
| `API_BASE_URL` | HTTPS API origin, or use `-PapiBaseUrl` |
| `KEYSTORE_PATH` | Path to a private release keystore outside the repository |
| `STORE_PASSWORD` | Keystore password |
| `KEY_ALIAS` | Release signing alias |
| `KEY_PASSWORD` | Private-key password |

From `mobile/`, run `./gradlew assembleRelease bundleRelease`. Release validation
rejects the placeholder API URL and missing signing configuration. There is no
fallback to a debug key. Preserve the existing application ID and signing identity
when upgrading installed apps, and deliberately increment the version code/name
before issuing a new Android release.

For GitHub Actions, set `API_BASE_URL` as a repository variable and the signing
values as repository/environment secrets. The Android release workflow expects
`KEYSTORE_BASE64` instead of `KEYSTORE_PATH`; it reconstructs and removes the
keystore only in the runner's temporary directory.

## Release artifacts

Version tags trigger the Android and Windows build workflows. They upload
short-lived CI artifacts for review; they do not publish a GitHub Release
automatically. Publish only reviewed, signed distributables and appropriate
checksums through GitHub Releases. Keep customer data, internal reports, test
logs, keystores, and old installers out of both the source tree and release assets.
