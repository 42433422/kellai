from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parent
FONT_STACK = (
    "PingFang SC, Hiragino Sans GB, Microsoft YaHei, Heiti SC, "
    "Arial Unicode MS, sans-serif"
)

NAVY = "#102a56"
BLUE = "#2868f0"
CYAN = "#10b6d3"
GREEN = "#12b981"
MINT = "#dffaf1"
AMBER = "#ffb020"
PAPER = "#ffffff"


def write(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def svg(width: int, height: int, label: str, body: str) -> str:
    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" role="img" aria-label="{label}">
  <rect width="{width}" height="{height}" fill="{PAPER}"/>
{body}
</svg>
'''


def wordmark(x: int, y: int, size: int, fill: str = NAVY) -> str:
    return f'<text x="{x}" y="{y}" fill="{fill}" font-family="{FONT_STACK}" font-size="{size}" font-weight="900" letter-spacing="2">客来来</text>'


def mark_arrival_ring() -> str:
    return f'''  <defs>
    <linearGradient id="arrivalRing" x1="34" y1="30" x2="238" y2="238" gradientUnits="userSpaceOnUse">
      <stop offset="0" stop-color="{BLUE}"/>
      <stop offset="0.55" stop-color="{CYAN}"/>
      <stop offset="1" stop-color="{GREEN}"/>
    </linearGradient>
  </defs>
  <circle cx="138" cy="138" r="104" fill="{MINT}"/>
  <path d="M78 150c38-62 86-92 146-90" fill="none" stroke="url(#arrivalRing)" stroke-width="28" stroke-linecap="round"/>
  <path d="M76 176c60 42 126 48 198 18" fill="none" stroke="{AMBER}" stroke-width="22" stroke-linecap="round"/>
  <path d="M133 62v116c0 14 10 24 24 24h62" fill="none" stroke="{NAVY}" stroke-width="24" stroke-linecap="round" stroke-linejoin="round"/>
  <circle cx="222" cy="64" r="15" fill="{GREEN}"/>'''


def mark_come_leaf() -> str:
    return f'''  <defs>
    <linearGradient id="comeLeaf" x1="38" y1="36" x2="238" y2="230" gradientUnits="userSpaceOnUse">
      <stop offset="0" stop-color="{BLUE}"/>
      <stop offset="0.45" stop-color="{CYAN}"/>
      <stop offset="1" stop-color="{GREEN}"/>
    </linearGradient>
  </defs>
  <path d="M42 154c0-70 56-126 126-126h76v78c0 70-56 126-126 126H42z" fill="url(#comeLeaf)"/>
  <path d="M82 170c44-54 88-82 132-84" fill="none" stroke="#ffffff" stroke-width="22" stroke-linecap="round"/>
  <path d="M122 88v104" stroke="#ffffff" stroke-width="22" stroke-linecap="round"/>
  <path d="M164 112v80" stroke="#ffffff" stroke-width="22" stroke-linecap="round"/>
  <path d="M100 208c42 16 82 18 120 6" fill="none" stroke="{AMBER}" stroke-width="18" stroke-linecap="round"/>'''


def mark_k_loop() -> str:
    return f'''  <defs>
    <linearGradient id="kLoop" x1="38" y1="42" x2="238" y2="232" gradientUnits="userSpaceOnUse">
      <stop offset="0" stop-color="{BLUE}"/>
      <stop offset="0.52" stop-color="{CYAN}"/>
      <stop offset="1" stop-color="{GREEN}"/>
    </linearGradient>
  </defs>
  <rect x="32" y="36" width="212" height="204" rx="56" fill="#f2fbff"/>
  <path d="M86 202V72" fill="none" stroke="{NAVY}" stroke-width="28" stroke-linecap="round"/>
  <path d="M104 142l108-78" fill="none" stroke="url(#kLoop)" stroke-width="30" stroke-linecap="round"/>
  <path d="M105 142l112 82" fill="none" stroke="url(#kLoop)" stroke-width="30" stroke-linecap="round"/>
  <path d="M172 142h24c42 0 72 28 72 64s-30 64-72 64h-46" fill="none" stroke="{AMBER}" stroke-width="24" stroke-linecap="round"/>
  <circle cx="202" cy="206" r="10" fill="{NAVY}"/>
  <circle cx="238" cy="206" r="10" fill="{NAVY}"/>'''


def logo(slug: str, name: str, mark: str) -> tuple[str, str]:
    horizontal = svg(
        880,
        260,
        f"客来来 Logo {name}",
        f'''  <g transform="translate(52 20) scale(0.82)">
{mark}
  </g>
  {wordmark(304, 145, 108)}
  <path d="M308 176h286" stroke="{GREEN}" stroke-width="9" stroke-linecap="round"/>
  <circle cx="628" cy="176" r="9" fill="{AMBER}"/>
  <circle cx="662" cy="176" r="9" fill="{CYAN}"/>''',
    )
    icon = svg(
        320,
        320,
        f"客来来图标 {name}",
        f'''  <g transform="translate(22 22)">
{mark}
  </g>''',
    )
    write(ROOT / f"kellai-online-{slug}-logo.svg", horizontal)
    write(ROOT / f"kellai-online-{slug}-icon.svg", icon)
    return (f"kellai-online-{slug}-logo.svg", f"kellai-online-{slug}-icon.svg")


def main() -> None:
    ROOT.mkdir(parents=True, exist_ok=True)
    concepts = [
        ("01-arrival-ring", "来客环", mark_arrival_ring(), "主推：一个客户流入的专属符号，克制、容易延展。"),
        ("02-come-leaf", "来叶", mark_come_leaf(), "更亲和，适合中小商家和私域增长。"),
        ("03-k-loop", "K 回路", mark_k_loop(), "更 SaaS / 科技感，适合桌面端和国际化。"),
    ]
    rows = []
    for slug, name, mark, note in concepts:
        logo_file, icon_file = logo(slug, name, mark)
        rows.append((name, note, logo_file, icon_file))

    write(
        ROOT / "design-notes.md",
        """# 客来来 Logo online-learned

上网看了相邻品牌后，本版按 Logo 重新收敛：

- 不做黑白稿。
- 不堆功能小图标。
- 每个方案只保留一个主符号，搭配中文品牌名。
- 图标和横版共用同一个核心符号，便于 App、桌面端、官网、物料统一。
- 避免直接近似微信/企微/钉钉/有赞/HubSpot/Intercom/Zendesk 的标志。

推荐优先级：

1. 01 来客环：最稳，适合继续精修为正式 Logo。
2. 02 来叶：更亲和、轻量，更适合中小商家。
3. 03 K 回路：更科技，但中文记忆点弱一些。
""",
    )

    cards = "\n".join(
        f'''    <section>
      <img class="logo" src="{logo_file}" alt="{name} Logo">
      <img class="icon" src="{icon_file}" alt="{name} Icon">
      <h2>{idx:02d} {name}</h2>
      <p>{note}</p>
    </section>'''
        for idx, (name, note, logo_file, icon_file) in enumerate(rows, 1)
    )
    write(
        ROOT / "index.html",
        f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>客来来 Logo 参考学习后重做</title>
  <style>
    :root {{ font-family: {FONT_STACK}; color: {NAVY}; background: #f6f8fb; }}
    body {{ margin: 0; padding: 44px; }}
    h1 {{ margin: 0 0 8px; font-size: 38px; line-height: 1.2; }}
    .lead {{ margin: 0 0 30px; color: #587392; font-size: 16px; }}
    .grid {{ display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 24px; }}
    section {{ background: white; border: 1px solid #dce6f1; border-radius: 8px; padding: 24px; }}
    .logo {{ width: 100%; height: 170px; object-fit: contain; display: block; }}
    .icon {{ width: 112px; height: 112px; object-fit: contain; display: block; margin-top: 18px; }}
    h2 {{ margin: 18px 0 8px; font-size: 22px; }}
    p {{ margin: 0; color: #587392; line-height: 1.6; }}
    @media (max-width: 980px) {{ body {{ padding: 22px; }} .grid {{ grid-template-columns: 1fr; }} }}
  </style>
</head>
<body>
  <h1>客来来 Logo 重做版</h1>
  <p class="lead">参考相邻 SaaS/CRM/客服品牌规律后收敛：一个主符号 + 中文字标，不做黑白稿。</p>
  <main class="grid">
{cards}
  </main>
</body>
</html>
""",
    )
    print(f"wrote online-learned logo assets to {ROOT}")


if __name__ == "__main__":
    main()
