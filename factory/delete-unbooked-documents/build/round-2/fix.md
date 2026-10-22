# Round 2 fix

1. Same-origin guard: app/web/security.py (SameOriginMiddleware), registered in app/main.py create_app. Unsafe methods get 403 + plain-Dutch page when Sec-Fetch-Site not in {same-origin, none} or Origin host:port != Host. Header-less requests allowed. App-wide. CLAUDE.md untouched; suggest a one-line Decisions note later.
2. delete.html: booked state leads with "Maak de boeking eerst ongedaan (storno)" + info("storno") (GET and rejected POST); domain message reworded; list.html booked rows show "Bewaard (bewaarplicht)".

Tests added in tests/test_inbox_delete_web.py. Full suite: 1717 passed.
