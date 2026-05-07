#!/usr/bin/env python3
import browser_cookie3
import json
import sys

browsers = ['chrome', 'edge', 'firefox', 'brave']
found = False

for b in browsers:
    try:
        fn = getattr(browser_cookie3, b, None)
        if fn:
            cj = fn(domain_name='.zhipin.com')
            cookies = {c.name: c.value for c in cj if 'zhipin.com' in (c.domain or '')}
            if cookies:
                print(f'{b}: {len(cookies)} cookies found')
                print(json.dumps(list(cookies.keys())))
                found = True
    except Exception as e:
        print(f'{b}: {e}', file=sys.stderr)

if not found:
    print("No cookies found from any browser", file=sys.stderr)
    sys.exit(1)