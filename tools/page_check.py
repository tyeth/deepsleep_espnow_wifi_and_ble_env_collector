#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""
page_check.py - load the hub-served analyzer page in a real browser and say
whether it actually works, from a machine joined to the hub's AP.

    python3 tools/page_check.py                       # http://192.168.4.1
    python3 tools/page_check.py http://192.168.4.1 --shot /tmp/hub.png

Curl proves the headers; this proves the page: that the vendor bundle is
executed (not merely delivered), that the app reaches the REST API, and
that a reload costs 304s rather than the whole bundle again.

Needs Playwright's Python package and a system browser -- on a Pi there are
no Playwright ARM builds, so it drives /usr/bin/chromium directly.
"""

import argparse
import os
import sys

from playwright.sync_api import sync_playwright

BROWSERS = ("/usr/bin/chromium", "/usr/bin/chromium-browser",
            "/usr/bin/google-chrome")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("url", nargs="?", default="http://192.168.4.1/")
    ap.add_argument("--shot", default="/tmp/hub_page.png")
    ap.add_argument("--timeout", type=float, default=90)
    args = ap.parse_args()

    exe = next((b for b in BROWSERS if os.path.exists(b)), None)
    if exe is None:
        print("no system chromium found:", " ".join(BROWSERS))
        return 2

    console, failures, responses = [], [], []
    with sync_playwright() as p:
        browser = p.chromium.launch(
            executable_path=exe, headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"])
        page = browser.new_page(viewport={"width": 1000, "height": 900})
        page.on("console", lambda m: console.append("%s: %s" % (m.type, m.text)))
        page.on("requestfailed",
                lambda r: failures.append("%s %s" % (r.url, r.failure)))
        page.on("response",
                lambda r: responses.append((r.status, r.url)))

        print("loading", args.url)
        page.goto(args.url, wait_until="load",
                  timeout=int(args.timeout * 1000))
        page.wait_for_timeout(8000)          # let the deferred loaders run

        # Plotly is loaded on demand (ensurePlotly), not at startup: ask the
        # page to load it exactly the way drawing a chart would
        try:
            page.evaluate("""() => window.ensurePlotly && window.ensurePlotly()""")
        except Exception as exc:
            print("ensurePlotly call failed:", exc)
        page.wait_for_timeout(20000)
        plotly = page.evaluate("typeof window.Plotly")
        title = page.title()
        # the app fetches /api/latest itself; ask the page to do it again so a
        # failure shows up as a value rather than a silent empty dashboard
        api = page.evaluate("""async () => {
            try {
                const r = await fetch('/api/latest', {cache: 'no-store'});
                const j = await r.json();
                return {status: r.status, sources: Object.keys(j.sources || {}),
                        mesh: j.mesh || null};
            } catch (e) { return {error: String(e)}; }
        }""")
        page.screenshot(path=args.shot, full_page=False)

        first = [(s, u) for s, u in responses]
        responses.clear()
        # log what the browser asks for on the second visit: a stored
        # response shows up as a conditional request (If-None-Match)
        conditional = []
        page.on("request", lambda r: conditional.append(
            (r.url, r.headers.get("if-none-match", ""))))
        page.reload(wait_until="load", timeout=int(args.timeout * 1000))
        page.wait_for_timeout(5000)
        second = list(responses)
        browser.close()

    print("\ntitle: %r" % title)
    print("window.Plotly: %s" % plotly)
    print("/api/latest: %s" % api)

    print("\nfirst load (%d responses):" % len(first))
    for status, url in first:
        print("   %s %s" % (status, url[:96]))
    print("reload (%d responses):" % len(second))
    for status, url in second:
        print("   %s %s" % (status, url[:96]))
    revalidated = sum(1 for s, _ in second if s == 304)
    print("   -> %d served from cache as 304" % revalidated)
    asked = [(u, e) for u, e in conditional if e]
    print("   -> %d requests carried If-None-Match" % len(asked))
    for u, e in asked[:6]:
        print("      %s  %s" % (u[:70], e))

    if failures:
        print("\nfailed requests:")
        for f in failures:
            print("   ", f[:140])
    if console:
        print("\nconsole:")
        for c in console[:25]:
            print("   ", c[:140])

    ok = plotly == "object" and bool(api.get("sources"))
    print("\nscreenshot: %s" % args.shot)
    print("PAGE %s" % ("OK" if ok else "NOT WORKING"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
