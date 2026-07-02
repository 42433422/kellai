from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parent
FONT_STACK = (
    "PingFang SC, Hiragino Sans GB, Microsoft YaHei, Heiti SC, "
    "Arial Unicode MS, sans-serif"
)

INK = "#101828"
BLUE = "#2563eb"
GREEN = "#12b981"
TEAL = "#0891b2"
PAPER = "#ffffff"


def write(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def wrap(width: int, height: int, label: str, body: str) -> str:
    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" role="img" aria-label="{label}">
  <rect width="{width}" height="{height}" fill="{PAPER}"/>
{body}
</svg>
'''


def lai_glyph(fill: str = INK, accent: str | None = None) -> str:
    accent_part = ""
    if accent:
        accent_part = f'''
    <path d="M130 308c52 34 116 52 190 52s138-18 190-52" fill="none" stroke="{accent}" stroke-width="34" stroke-linecap="round"/>'''
    return f'''  <g>
    <rect x="146" y="94" width="220" height="50" rx="18" fill="{fill}"/>
    <rect x="230" y="94" width="52" height="332" rx="20" fill="{fill}"/>
    <rect x="122" y="206" width="268" height="50" rx="18" fill="{fill}"/>
    <path d="M220 256c-38 72-88 126-150 164" fill="none" stroke="{fill}" stroke-width="52" stroke-linecap="round" stroke-linejoin="round"/>
    <path d="M292 256c38 72 88 126 150 164" fill="none" stroke="{fill}" stroke-width="52" stroke-linecap="round" stroke-linejoin="round"/>{accent_part}
  </g>'''
    return f'''  <g>
    <rect x="146" y="94" width="220" height="50" rx="18" fill="{fill}"/>
    <rect x="230" y="94" width="52" height="332" rx="20" fill="{fill}"/>
    <rect x="122" y="206" width="268" height="50" rx="18" fill="{fill}"/>
    <path d="M220 256c-38 72-88 126-150 164" fill="none" stroke="{fill}" stroke-width="52" stroke-linecap="round" stroke-linejoin="round"/>
    <path d="M292 256c38 72 88 126 150 164" fill="none" stroke="{fill}" stroke-width="52" stroke-linecap="round" stroke-linejoin="round"/>
  </g>'''


def gate_mark(stroke: str = INK, accent: str | None = None) -> str:
    accent_part = ""
    if accent:
        accent_part = f'''
    <path d="M138 388c74 48 162 72 264 72s190-24 264-72" fill="none" stroke="{accent}" stroke-width="30" stroke-linecap="round"/>'''
    return f'''  <g fill="none" stroke-linecap="round" stroke-linejoin="round">
    <path d="M174 418V242c0-88 70-158 158-158s158 70 158 158v176" stroke="{stroke}" stroke-width="52"/>
    <path d="M264 418V252c0-38 30-68 68-68s68 30 68 68v166" stroke="{stroke}" stroke-width="52"/>
    <path d="M86 418h492" stroke="{stroke}" stroke-width="52"/>{accent_part}
  </g>'''
    return f'''  <g fill="none" stroke="{stroke}" stroke-width="52" stroke-linecap="round" stroke-linejoin="round">
    <path d="M174 418V242c0-88 70-158 158-158s158 70 158 158v176"/>
    <path d="M264 418V252c0-38 30-68 68-68s68 30 68 68v166"/>
    <path d="M86 418h492"/>
  </g>'''


def triple_arrival(fill: str = INK, accent: str | None = None) -> str:
    accent_part = ""
    if accent:
        accent_part = f'''
    <circle cx="256" cy="436" r="22" fill="{accent}"/>
    <circle cx="320" cy="436" r="22" fill="{accent}"/>
    <circle cx="384" cy="436" r="22" fill="{accent}"/>'''
    return f'''  <g>
    <path d="M320 78l168 102v194L320 476 152 374V180z" fill="none" stroke="{fill}" stroke-width="40" stroke-linejoin="round"/>
    <path d="M220 206h200" stroke="{fill}" stroke-width="46" stroke-linecap="round"/>
    <path d="M256 206v152" stroke="{fill}" stroke-width="46" stroke-linecap="round"/>
    <path d="M320 206v152" stroke="{fill}" stroke-width="46" stroke-linecap="round"/>
    <path d="M384 206v152" stroke="{fill}" stroke-width="46" stroke-linecap="round"/>
    <path d="M238 358c44 34 120 34 164 0" fill="none" stroke="{fill}" stroke-width="40" stroke-linecap="round"/>{accent_part}
  </g>'''


def wordmark(fill: str = INK, accent: str | None = None) -> str:
    accent_part = ""
    if accent:
        accent_part = f'''
    <path d="M24 164c58 26 136 26 196 0s138-26 196 0" fill="none" stroke="{accent}" stroke-width="14" stroke-linecap="round"/>
    <circle cx="444" cy="164" r="11" fill="{BLUE}"/>
    <circle cx="482" cy="164" r="11" fill="{GREEN}"/>'''
    return f'''  <g>
    <text x="0" y="128" fill="{fill}" font-family="{FONT_STACK}" font-size="118" font-weight="900" letter-spacing="2">客来来</text>{accent_part}
  </g>'''


def make_svg_assets() -> list[tuple[str, str, str, str]]:
    assets: list[tuple[str, str, str, str]] = []

    concepts = [
        (
            "01",
            "来字核心",
            lai_glyph(INK),
            lai_glyph(INK, GREEN),
            "把「来」做成独立核心符号，最像可注册主标。",
        ),
        (
            "02",
            "来客门",
            gate_mark(INK),
            gate_mark(INK, BLUE),
            "入口/到来感，但不使用聊天气泡和增长柱。",
        ),
        (
            "03",
            "三来印",
            triple_arrival(INK),
            triple_arrival(INK, GREEN),
            "三个来客汇入一个印记，适合做服务商标。",
        ),
        (
            "04",
            "中文字标",
            wordmark(INK),
            wordmark(INK, TEAL),
            "直接保护品牌名本身，后续可做定制字形。",
        ),
    ]

    for no, name, black_mark, color_mark, note in concepts:
        mark_name = f"kellai-v3-{no}-mark-black.svg"
        lockup_name = f"kellai-v3-{no}-lockup.svg"
        mark_svg = wrap(640, 640, f"客来来商标 v3 {no} {name} 黑白核心", f'''  <g transform="translate(64 64)">
{black_mark}
  </g>''')
        if no == "04":
            lock_body = f'''  <g transform="translate(120 112)">
{color_mark}
  </g>'''
        else:
            lock_body = f'''  <g transform="translate(74 50) scale(0.46)">
{color_mark}
  </g>
  <text x="360" y="158" fill="{INK}" font-family="{FONT_STACK}" font-size="100" font-weight="900" letter-spacing="2">客来来</text>
  <path d="M362 194h328" stroke="{GREEN}" stroke-width="12" stroke-linecap="round"/>'''
        lock_svg = wrap(960, 320, f"客来来商标 v3 {no} {name} 横版", lock_body)
        assets.append((mark_name, lockup_name, name, note))
        write(ROOT / mark_name, mark_svg)
        write(ROOT / lockup_name, lock_svg)

    return assets


def make_prompt_note() -> None:
    write(
        ROOT / "design-notes.md",
        """# 客来来商标 v3 设计说明

这版废弃 v2 的素材化方向，只保留更像商标的核心资产：

- 先做黑白核心形，再做彩色横版。
- 不堆叠聊天气泡、增长柱、渠道节点、漏斗等 SaaS 通用素材。
- 不使用英文小字和长口号作为识别主体。
- 优先考虑 24px 小尺寸、单色印刷、反白、商标注册初筛。
- 中文字标仍是草案字体，正式注册前应做字体授权或定制字形。

推荐优先级：

1. 01 来字核心：最简洁，最像主商标。
2. 02 来客门：适合 App/桌面图标，但还要再压缩细节。
3. 04 中文字标：适合注册文字/图文组合，但需要定制字体。
4. 03 三来印：偏服务认证感，可作为辅助标。
""",
    )


def make_index(assets: list[tuple[str, str, str, str]]) -> None:
    rows = "\n".join(
        f'''    <section class="concept">
      <div class="media mark"><img src="{mark}" alt="{name} 黑白核心"></div>
      <div class="media lockup"><img src="{lockup}" alt="{name} 横版"></div>
      <div class="copy">
        <h2>{idx} {name}</h2>
        <p>{note}</p>
      </div>
    </section>'''
        for idx, (mark, lockup, name, note) in enumerate(assets, 1)
    )
    write(
        ROOT / "index.html",
        f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>客来来商标候选 v3</title>
  <style>
    :root {{
      font-family: {FONT_STACK};
      color: #101828;
      background: #f6f8fb;
    }}
    body {{
      margin: 0;
      padding: 44px;
    }}
    h1 {{
      margin: 0 0 8px;
      font-size: 36px;
      line-height: 1.2;
    }}
    .lead {{
      margin: 0 0 30px;
      color: #667085;
      font-size: 16px;
      line-height: 1.7;
    }}
    .concept {{
      display: grid;
      grid-template-columns: 220px minmax(360px, 1fr) 260px;
      gap: 20px;
      align-items: center;
      margin: 0 0 22px;
      padding: 20px;
      background: #fff;
      border: 1px solid #d8e1ec;
      border-radius: 8px;
    }}
    .media {{
      background: #fff;
      border: 1px solid #e5ebf3;
      border-radius: 8px;
      display: grid;
      place-items: center;
      min-height: 168px;
    }}
    .mark img {{
      width: 168px;
      height: 168px;
      object-fit: contain;
    }}
    .lockup img {{
      width: 100%;
      height: 168px;
      object-fit: contain;
    }}
    h2 {{
      margin: 0 0 10px;
      font-size: 20px;
      line-height: 1.3;
    }}
    p {{
      margin: 0;
      color: #667085;
      line-height: 1.65;
    }}
    @media (max-width: 980px) {{
      body {{ padding: 22px; }}
      .concept {{ grid-template-columns: 1fr; }}
      .media {{ min-height: 190px; }}
    }}
  </style>
</head>
<body>
  <h1>客来来商标候选 v3</h1>
  <p class="lead">重做为真正商标方向：先看黑白核心形，再看横版组合。正式注册前仍需近似检索和字体授权/定制。</p>
{rows}
</body>
</html>
""",
    )


def main() -> None:
    ROOT.mkdir(parents=True, exist_ok=True)
    assets = make_svg_assets()
    make_prompt_note()
    make_index(assets)
    print(f"wrote v3 assets to {ROOT}")


if __name__ == "__main__":
    main()
