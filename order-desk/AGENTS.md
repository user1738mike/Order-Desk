# Order Desk agent guidance

- Work in small verified increments, not as a full rewrite.
- Keep the locked Django/PostgreSQL stack and Compose workflow intact.
- Prefer existing repo conventions and app boundaries over introducing new patterns.
- Run the smallest focused Django test suite that validates the changed behavior.
- Preserve uncommitted user work; do not overwrite unrelated files.
- Document each phase in the repository state files before moving to the next one.
- Keep customer data synthetic and local-only while the application is still in development.
