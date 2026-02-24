# Security Policy

## Supported Versions

| Version | Supported          |
|---------|--------------------|
| 0.1.x   | Yes                |

## Reporting a Vulnerability

**Do not open a public GitHub issue for security vulnerabilities.**

Instead, please report vulnerabilities through one of these channels:

1. **GitHub Security Advisories**: Use the "Report a vulnerability" button on the [Security tab](https://github.com/masa-57/pic/security/advisories)
2. **Email**: Send details to masoud.ahanchian@gmail.com

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

PIC handles image data and provides an API with key-based authentication. When deploying:

- Always set a strong `PIC_API_KEY` in production
- Use HTTPS for all API communication
- Restrict database access to the API server and workers only
- Review S3/R2 bucket policies to prevent public access to images
- Rotate secrets regularly (see `docs/runbooks/secrets-rotation.md`)
