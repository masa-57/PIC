# Security Policy

## Supported Versions

Security fixes go into the latest release. Older versions are not patched; please upgrade.

| Version | Supported |
|---------|-----------|
| Latest release | Yes |
| Older releases | No |

## Reporting a Vulnerability

**Do not open a public GitHub issue for security vulnerabilities.**

Instead, please either report vulnerabilities using **GitHub Security Advisories**: use the "Report a vulnerability" button on the [Security tab](https://github.com/masa-57/pic/security/advisories) or send an email to: 118902016+masa-57@users.noreply.github.com

### What to Include

- Description of the vulnerability
- Steps to reproduce
- Potential impact
- Suggested fix (if any)

### Response Timeline

- **Acknowledgment**: Within 48 hours
- **Initial assessment**: Within 1 week
- **Fix for critical issues**: Within 30 days
- **Fix for non-critical issues**: Within 90 days

You will be credited in the fix unless you prefer to remain anonymous.

## Security Considerations

PIC handles image data and provides a JSON API and a web UI protected by one API key. When deploying:

- The Docker Compose stack is for a single machine: it disables auth (`PIC_AUTH_DISABLED=true`) and binds to `127.0.0.1`. Don't expose it as is.
- Set a long random `PIC_API_KEY` for anything reachable by others. API clients send it as `X-API-Key`; the web UI asks for it once and stores a `pic_session` cookie (an HMAC of the key, `HttpOnly`, `SameSite=Strict`, 30 days). Rotating the key ends every UI session.
- Serve PIC over HTTPS behind a reverse proxy, and make sure the proxy forwards the https scheme (for example with `--forwarded-allow-ips`), or the session cookie is set without the `Secure` flag.
- With the local storage backend, `/files` serves stored images **without authentication**. Use S3/R2/MinIO or GCS with private buckets for public deployments.
- PIC has no built-in rate limiting; add it at the reverse proxy.
- Restrict database access to the API and workers.
- Rotate secrets regularly (see `docs/runbooks/secrets-rotation.md`).
