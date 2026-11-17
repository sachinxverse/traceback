# Security Policy

## Reporting a problem

If you find a security vulnerability in TRACEBACK, please email the
address configured in the repository owner's GitHub profile, or open a
GitHub issue marked `security` **without reproduction details** and the
owner will follow up privately. Do not disclose publicly until a fix is
deployed.

## Expectations

- Reports are acknowledged within 7 days.
- Please include: the affected page/endpoint, steps, and impact.
- We will not take action against researchers who act in good faith.

## Hardening overview

- Two-step verification (password + one-time code) on every portal.
- OTP codes stored HMAC-hashed, single-use, rate-limited, IP/UA-bound.
- JWTs in HttpOnly cookies with CSRF double-submit; instant revocation.
- Uploaded photos: EXIF stripped, size-limited, served only via
  authorised endpoints, never public.
- Production refuses weak/placeholder secrets and ephemeral storage.
