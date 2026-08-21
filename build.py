"""Inline the web app into self-contained pages.

Produces two builds of identical markup and code, differing only in how the
fonts arrive:

    dist/zero-plus.html          artifact shape: no doctype/html/head/body,
                                 because the Artifact host supplies that
                                 skeleton. Links to Google Fonts, which is fine
                                 for a page that is viewed online.

    dist/zero-plus-offline.html  a complete document with the fonts embedded as
                                 data URIs. One file, no network, no server --
                                 this is the one to copy onto other machines.

Run it after editing anything under web/. Fonts come from web/fonts.css, which
fetch_fonts.py generates; build.py itself never needs a network.
"""

import io
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
WEB = os.path.join(HERE, "web")
DIST = os.path.join(HERE, "dist")

FONT_LINK = ('<link rel="stylesheet" href="https://fonts.googleapis.com/css2?'
             'family=Chivo:wght@700;900&family=IBM+Plex+Mono:wght@400;500&'
             'family=IBM+Plex+Sans:wght@400;500;600&display=swap">')


def read(name):
    with io.open(os.path.join(WEB, name), encoding="utf-8") as handle:
        return handle.read()


def write(path, text):
    with io.open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
    return os.path.getsize(path)


def body_of(html):
    """The markup between <body> and </body>, minus the script tags."""
    match = re.search(r"<body>(.*)</body>", html, re.S)
    if not match:
        raise SystemExit("index.html has no <body>")
    body = re.sub(r'\s*<script src="[^"]+"></script>', "", match.group(1))
    return body.strip()


def compose(fonts_head, css, body, solver, app):
    return "\n".join([
        "<title>Zero Plus</title>",
        fonts_head,
        "<style>",
        css,
        "</style>",
        "",
        body,
        "",
        "<script>",
        solver,
        "</script>",
        "<script>",
        app,
        "</script>",
        ""
    ])


def main():
    if not os.path.isdir(DIST):
        os.mkdir(DIST)

    html = read("index.html")
    css = read("style.css").strip()
    solver = read("solver.js").strip()
    app = read("app.js").strip()
    body = body_of(html)

    for label, source in (("style.css", css), ("solver.js", solver), ("app.js", app)):
        if "</script>" in source or "</style>" in source:
            raise SystemExit("%s contains a closing tag that would break inlining"
                             % label)

    online = compose(FONT_LINK, css, body, solver, app)
    size = write(os.path.join(DIST, "zero-plus.html"), online)
    print("dist/zero-plus.html          %6.0f KB   for publishing as an Artifact"
          % (size / 1024.0))

    fonts_path = os.path.join(WEB, "fonts.css")
    if os.path.exists(fonts_path):
        embedded = "<style>\n%s</style>" % read("fonts.css")
        note = "fonts embedded, works with no network"
    else:
        embedded = FONT_LINK
        note = ("fonts NOT embedded -- run fetch_fonts.py first if this copy "
                "needs to work offline")

    offline = "\n".join([
        "<!doctype html>",
        '<html lang="en">',
        "<head>",
        '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        "</head>",
        "<body>",
        compose(embedded, css, body, solver, app),
        "</body>",
        "</html>",
        ""
    ])
    path = os.path.join(DIST, "zero-plus-offline.html")
    size = write(path, offline)
    print("dist/zero-plus-offline.html  %6.0f KB   %s" % (size / 1024.0, note))

    leftover = re.findall(r"https?://(?!www\.w3\.org)[^\"')\s]+", offline)
    if leftover:
        print("\nwarning: the offline build still reaches out to:")
        for url in sorted(set(leftover))[:5]:
            print("  " + url[:90])
    else:
        print("\nverified: the offline build makes no external requests")


if __name__ == "__main__":
    main()
