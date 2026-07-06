"""Third-party integrations (v0.8+).

Each integration exposes:

- an OAuth flow builder / token exchanger,
- a minimal REST wrapper that fetches *only* the fields declared safe by the
  Data Minimizer (see ``technical_implementation_guide.md`` § 6.3),
- and a webhook payload extractor + signature verifier when the vendor
  supports push-based delivery.
"""
