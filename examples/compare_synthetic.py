"""Generate all seven illustrative fixtures and offline comparison reports."""
from __future__ import annotations

import argparse
import html
from pathlib import Path

from signum.comparison import compare_video
from signum.config import SamplerConfig
from signum.synthetic import generate_suite


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("output/showcase"))
    args = parser.parse_args()
    links = []
    for case, video in generate_suite(args.output / "media"):
        compare_video(video, args.output / case.name, SamplerConfig(budget=case.budget))
        links.append(
            f'<li><a href="{case.name}/index.html">{html.escape(case.name)}</a>'
            f' &mdash; {html.escape(case.description)}</li>'
        )
    page = (
        '<!doctype html><html lang="en"><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        '<title>Signum synthetic comparison gallery</title>'
        '<style>body{font:18px/1.6 system-ui;max-width:850px;margin:auto;padding:32px;'
        'color:#182a30;background:#f1f5f3}li{margin:16px 0}a{color:#175b46}</style>'
        '<h1>Inspect every synthetic case</h1>'
        '<p>Seven deterministic fixtures. Six observations per method in each case. '
        'No model calls or real-world accuracy claims. The gallery includes every '
        'case in the existing regression suite, not only favorable examples.</p>'
        f'<ul>{"".join(links)}</ul></html>'
    )
    index = args.output / "index.html"
    index.write_text(page, encoding="utf-8")
    print(index.resolve())


if __name__ == "__main__":
    main()
