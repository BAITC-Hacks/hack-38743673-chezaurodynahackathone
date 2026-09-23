"""Refresh the CSS fallback so index.html keeps its design when opened alone."""
from pathlib import Path


STATIC = Path(__file__).resolve().parents[1] / "smartmatch" / "static"
START = '<style id="embedded-styles">'
END = "</style>"


def main() -> None:
    path = STATIC / "index.html"
    html = path.read_text(encoding="utf-8")
    css = (STATIC / "styles.css").read_text(encoding="utf-8").strip()
    if "</style" in css.lower():
        raise ValueError("CSS contains an HTML closing style tag")
    block = f"{START}\n{css}\n{END}\n"
    if START in html:
        start = html.index(START)
        end = html.index(END, start) + len(END)
        html = html[:start] + block.rstrip("\n") + html[end:]
    else:
        anchor = '<link rel="stylesheet" href="./styles.css">'
        if anchor not in html:
            raise ValueError("Stylesheet link not found in index.html")
        html = html.replace(anchor, "\n" + block + anchor, 1)
    path.write_text(html, encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
