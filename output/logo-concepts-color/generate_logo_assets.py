from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parent
FONT_STACK = (
    "PingFang SC, Hiragino Sans GB, Microsoft YaHei, Heiti SC, "
    "Arial Unicode MS, sans-serif"
)

INK = "#15315f"
BLUE = "#2563eb"
SKY = "#0ea5e9"
CYAN = "#06b6d4"
GREEN = "#10b981"
LIME = "#84cc16"
AMBER = "#f59e0b"
ORANGE = "#f97316"
PAPER = "#ffffff"


def write(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def wrap(width: int, height: int, label: str, body: str) -> str:
    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" role="img" aria-label="{label}">
  <rect width="{width}" height="{height}" fill="{PAPER}"/>
{body}
</svg>
'''


def word(x: int = 330, y: int = 170, size: int = 92, fill: str = INK) -> str:
    return f'<text x="{x}" y="{y}" fill="{fill}" font-family="{FONT_STACK}" font-size="{size}" font-weight="900" letter-spacing="3">客来来</text>'


def logo_01_icon() -> str:
    return f'''  <defs>
    <linearGradient id="g1" x1="42" y1="36" x2="214" y2="220" gradientUnits="userSpaceOnUse">
      <stop offset="0" stop-color="{BLUE}"/>
      <stop offset="0.52" stop-color="{CYAN}"/>
      <stop offset="1" stop-color="{GREEN}"/>
    </linearGradient>
  </defs>
  <rect x="28" y="28" width="220" height="220" rx="58" fill="url(#g1)"/>
  <path d="M82 156c42-54 84-80 126-78" fill="none" stroke="#ffffff" stroke-width="22" stroke-linecap="round"/>
  <path d="M86 180c40 24 84 36 132 36" fill="none" stroke="{AMBER}" stroke-width="20" stroke-linecap="round"/>
  <rect x="104" y="106" width="22" height="80" rx="11" fill="#ffffff"/>
  <rect x="146" y="82" width="22" height="104" rx="11" fill="#ffffff"/>
  <rect x="188" y="118" width="22" height="68" rx="11" fill="#ffffff"/>
  <circle cx="110" cy="82" r="12" fill="#ffffff"/>
  <circle cx="152" cy="58" r="12" fill="#ffffff"/>
  <circle cx="194" cy="94" r="12" fill="#ffffff"/>'''


def logo_02_icon() -> str:
    return f'''  <defs>
    <linearGradient id="g2" x1="26" y1="30" x2="238" y2="230" gradientUnits="userSpaceOnUse">
      <stop offset="0" stop-color="{SKY}"/>
      <stop offset="0.54" stop-color="{GREEN}"/>
      <stop offset="1" stop-color="{LIME}"/>
    </linearGradient>
  </defs>
  <path d="M138 34c64 0 110 46 110 110s-46 110-110 110S28 208 28 144 74 34 138 34z" fill="url(#g2)"/>
  <path d="M78 154c36-42 74-64 116-66" fill="none" stroke="#ffffff" stroke-width="22" stroke-linecap="round"/>
  <path d="M98 176l38 34 62-78" fill="none" stroke="#ffffff" stroke-width="24" stroke-linecap="round" stroke-linejoin="round"/>
  <circle cx="86" cy="98" r="12" fill="{AMBER}"/>
  <circle cx="124" cy="78" r="12" fill="#ffffff"/>
  <circle cx="164" cy="80" r="12" fill="#ffffff"/>'''


def logo_03_icon() -> str:
    return f'''  <defs>
    <linearGradient id="g3" x1="48" y1="24" x2="230" y2="232" gradientUnits="userSpaceOnUse">
      <stop offset="0" stop-color="{BLUE}"/>
      <stop offset="1" stop-color="{GREEN}"/>
    </linearGradient>
  </defs>
  <rect x="28" y="38" width="220" height="202" rx="52" fill="#eef8ff"/>
  <path d="M70 174V98c0-34 27-61 61-61h16c34 0 61 27 61 61v76" fill="none" stroke="url(#g3)" stroke-width="26" stroke-linecap="round"/>
  <path d="M82 186c36 28 76 42 120 42" fill="none" stroke="{AMBER}" stroke-width="20" stroke-linecap="round"/>
  <path d="M117 142h114c18 0 33 15 33 33s-15 33-33 33h-42l-44 34v-34h-28c-18 0-33-15-33-33s15-33 33-33z" fill="{INK}"/>
  <circle cx="139" cy="176" r="7" fill="#ffffff"/>
  <circle cx="169" cy="176" r="7" fill="#ffffff"/>
  <circle cx="199" cy="176" r="7" fill="#ffffff"/>'''


def logo_04_icon() -> str:
    return f'''  <defs>
    <linearGradient id="g4" x1="34" y1="36" x2="236" y2="226" gradientUnits="userSpaceOnUse">
      <stop offset="0" stop-color="{ORANGE}"/>
      <stop offset="0.5" stop-color="{AMBER}"/>
      <stop offset="1" stop-color="{GREEN}"/>
    </linearGradient>
  </defs>
  <path d="M60 210V92c0-34 28-62 62-62h32c34 0 62 28 62 62v118" fill="none" stroke="url(#g4)" stroke-width="28" stroke-linecap="round"/>
  <path d="M96 210v-96c0-18 15-33 33-33h18c18 0 33 15 33 33v96" fill="none" stroke="{INK}" stroke-width="22" stroke-linecap="round"/>
  <path d="M62 218h154" stroke="{BLUE}" stroke-width="22" stroke-linecap="round"/>
  <circle cx="62" cy="82" r="15" fill="{BLUE}"/>
  <circle cx="216" cy="82" r="15" fill="{GREEN}"/>'''


def horizontal(filename: str, title: str, icon_body: str) -> str:
    return wrap(
        880,
        260,
        title,
        f'''  <g transform="translate(54 24) scale(0.8)">
{icon_body}
  </g>
  {word(x=310, y=156, size=104)}''',
    )


def square(filename: str, title: str, icon_body: str) -> str:
    return wrap(320, 320, title, f'''  <g transform="translate(22 22)">
{icon_body}
  </g>''')


def make_assets() -> list[tuple[str, str, str]]:
    concepts = [
        ("01-growth-flow", "增长流线", logo_01_icon(), "来客不断 · 跟进更快"),
        ("02-deal-arc", "成交弧线", logo_02_icon(), "把来客变成机会"),
        ("03-customer-gate", "来客入口", logo_03_icon(), "多渠道客户跟进"),
        ("04-welcome-door", "迎客门", logo_04_icon(), "轻量客户增长 CRM"),
    ]
    for slug, name, icon, tagline in concepts:
        write(ROOT / f"kellai-logo-{slug}.svg", horizontal(slug, f"客来来 Logo {name}", icon))
        write(ROOT / f"kellai-icon-{slug}.svg", square(slug, f"客来来图标 {name}", icon))
    write(ROOT / "design-notes.md", """# 客来来彩色 Logo 候选

这版按 Logo 重新做，不再按商标黑白稿处理：

- 全部是彩色 Logo，不提供黑白版本。
- 每个方向都有横版 Logo 和方形 App/桌面图标。
- 中文字标暂用系统字体落稿，正式使用建议再做定制字形或字体授权确认。
- 推荐优先看 01 和 03：更贴近客来来“客户增长 + 跟进”的产品定位。
""")
    return [(slug, name, tagline) for slug, name, _, tagline in concepts]


def make_index(concepts: list[tuple[str, str, str]]) -> None:
    cards = "\n".join(
        f'''    <section>
      <img class="logo" src="kellai-logo-{slug}.svg" alt="{name} 横版 Logo">
      <img class="icon" src="kellai-icon-{slug}.svg" alt="{name} 图标">
      <h2>{idx:02d} {name}</h2>
      <p>{tagline}</p>
    </section>'''
        for idx, (slug, name, tagline) in enumerate(concepts, 1)
    )
    write(ROOT / "index.html", f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>客来来彩色 Logo 候选</title>
  <style>
    :root {{
      font-family: {FONT_STACK};
      color: {INK};
      background: #f6f8fb;
    }}
    body {{
      margin: 0;
      padding: 44px;
    }}
    h1 {{
      margin: 0 0 28px;
      font-size: 38px;
      line-height: 1.2;
    }}
    .grid {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 24px;
    }}
    section {{
      background: white;
      border: 1px solid #dce6f1;
      border-radius: 8px;
      padding: 26px;
    }}
    .logo {{
      width: 100%;
      height: 180px;
      object-fit: contain;
      display: block;
    }}
    .icon {{
      width: 96px;
      height: 96px;
      object-fit: contain;
      display: block;
      margin-top: 14px;
    }}
    h2 {{
      margin: 16px 0 6px;
      font-size: 21px;
    }}
    p {{
      margin: 0;
      color: #52708f;
      font-size: 15px;
    }}
    @media (max-width: 900px) {{
      body {{ padding: 22px; }}
      .grid {{ grid-template-columns: 1fr; }}
    }}
  </style>
</head>
<body>
  <h1>客来来彩色 Logo 候选</h1>
  <main class="grid">
{cards}
  </main>
</body>
</html>
""")


def main() -> None:
    ROOT.mkdir(parents=True, exist_ok=True)
    concepts = make_assets()
    make_index(concepts)
    print(f"wrote color logo assets to {ROOT}")


if __name__ == "__main__":
    main()
