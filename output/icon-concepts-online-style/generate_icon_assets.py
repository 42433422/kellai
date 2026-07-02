from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parent

NAVY = "#102a56"
BLUE = "#2868f0"
SKY = "#0ea5e9"
CYAN = "#10b6d3"
GREEN = "#12b981"
MINT = "#ddfbf1"
AMBER = "#ffb020"
ORANGE = "#f97316"
PAPER = "#ffffff"


def write(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def svg(label: str, body: str) -> str:
    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512" role="img" aria-label="{label}">
  <rect width="512" height="512" fill="{PAPER}"/>
{body}
</svg>
'''


def rounded_gradient_bg(id_: str) -> str:
    return f'''  <defs>
    <linearGradient id="{id_}" x1="86" y1="72" x2="426" y2="444" gradientUnits="userSpaceOnUse">
      <stop offset="0" stop-color="{BLUE}"/>
      <stop offset="0.52" stop-color="{CYAN}"/>
      <stop offset="1" stop-color="{GREEN}"/>
    </linearGradient>
  </defs>
  <rect x="64" y="64" width="384" height="384" rx="96" fill="url(#{id_})"/>'''


def icon_01_arrival_ring() -> str:
    return svg(
        "客来来图标 01 来客环",
        f'''{rounded_gradient_bg("bgArrival")}
  <circle cx="256" cy="256" r="132" fill="#ffffff" opacity="0.92"/>
  <path d="M162 266c54-86 124-128 210-124" fill="none" stroke="{SKY}" stroke-width="34" stroke-linecap="round"/>
  <path d="M160 312c78 54 164 62 258 24" fill="none" stroke="{AMBER}" stroke-width="30" stroke-linecap="round"/>
  <path d="M250 138v166c0 22 16 38 38 38h88" fill="none" stroke="{NAVY}" stroke-width="34" stroke-linecap="round" stroke-linejoin="round"/>
  <circle cx="376" cy="144" r="20" fill="{GREEN}"/>''',
    )


def icon_02_leaf_flow() -> str:
    return svg(
        "客来来图标 02 来叶",
        f'''  <defs>
    <linearGradient id="leafBg" x1="88" y1="86" x2="420" y2="430" gradientUnits="userSpaceOnUse">
      <stop offset="0" stop-color="{BLUE}"/>
      <stop offset="0.5" stop-color="{CYAN}"/>
      <stop offset="1" stop-color="{GREEN}"/>
    </linearGradient>
  </defs>
  <rect x="64" y="64" width="384" height="384" rx="96" fill="#eefbff"/>
  <path d="M104 280c0-106 86-192 192-192h112v112c0 106-86 192-192 192H104z" fill="url(#leafBg)"/>
  <path d="M164 288c66-82 132-124 198-126" fill="none" stroke="#ffffff" stroke-width="34" stroke-linecap="round"/>
  <path d="M222 176v154" stroke="#ffffff" stroke-width="32" stroke-linecap="round"/>
  <path d="M282 214v116" stroke="#ffffff" stroke-width="32" stroke-linecap="round"/>
  <path d="M166 360c64 24 126 28 186 8" fill="none" stroke="{AMBER}" stroke-width="28" stroke-linecap="round"/>''',
    )


def icon_03_customer_gate() -> str:
    return svg(
        "客来来图标 03 来客门",
        f'''{rounded_gradient_bg("bgGate")}
  <path d="M156 350V220c0-62 50-112 112-112s112 50 112 112v130" fill="none" stroke="#ffffff" stroke-width="42" stroke-linecap="round"/>
  <path d="M218 350V226c0-28 22-50 50-50s50 22 50 50v124" fill="none" stroke="{MINT}" stroke-width="34" stroke-linecap="round"/>
  <path d="M146 356c72 46 154 62 246 48" fill="none" stroke="{AMBER}" stroke-width="30" stroke-linecap="round"/>
  <circle cx="164" cy="184" r="17" fill="{AMBER}"/>
  <circle cx="372" cy="184" r="17" fill="{GREEN}"/>''',
    )


def icon_04_k_loop() -> str:
    return svg(
        "客来来图标 04 K 回路",
        f'''  <defs>
    <linearGradient id="kBg" x1="86" y1="80" x2="422" y2="430" gradientUnits="userSpaceOnUse">
      <stop offset="0" stop-color="#f2fbff"/>
      <stop offset="1" stop-color="#e8fff5"/>
    </linearGradient>
    <linearGradient id="kStroke" x1="142" y1="128" x2="386" y2="386" gradientUnits="userSpaceOnUse">
      <stop offset="0" stop-color="{BLUE}"/>
      <stop offset="0.5" stop-color="{CYAN}"/>
      <stop offset="1" stop-color="{GREEN}"/>
    </linearGradient>
  </defs>
  <rect x="64" y="64" width="384" height="384" rx="96" fill="url(#kBg)"/>
  <path d="M164 370V142" fill="none" stroke="{NAVY}" stroke-width="48" stroke-linecap="round"/>
  <path d="M192 256l178-126" fill="none" stroke="url(#kStroke)" stroke-width="52" stroke-linecap="round"/>
  <path d="M192 256l182 134" fill="none" stroke="url(#kStroke)" stroke-width="52" stroke-linecap="round"/>
  <path d="M306 256h48c58 0 96 38 96 88s-38 88-96 88h-72" fill="none" stroke="{AMBER}" stroke-width="36" stroke-linecap="round"/>
  <circle cx="358" cy="344" r="14" fill="{NAVY}"/>
  <circle cx="408" cy="344" r="14" fill="{NAVY}"/>''',
    )


def icon_05_lai_tile() -> str:
    return svg(
        "客来来图标 05 来字块",
        f'''  <defs>
    <linearGradient id="laiTile" x1="80" y1="74" x2="426" y2="436" gradientUnits="userSpaceOnUse">
      <stop offset="0" stop-color="{BLUE}"/>
      <stop offset="0.48" stop-color="{SKY}"/>
      <stop offset="1" stop-color="{GREEN}"/>
    </linearGradient>
  </defs>
  <rect x="64" y="64" width="384" height="384" rx="96" fill="url(#laiTile)"/>
  <path d="M170 164h172" stroke="#ffffff" stroke-width="36" stroke-linecap="round"/>
  <path d="M256 164v214" stroke="#ffffff" stroke-width="38" stroke-linecap="round"/>
  <path d="M154 250h204" stroke="#ffffff" stroke-width="36" stroke-linecap="round"/>
  <path d="M246 254c-34 58-76 102-126 132" fill="none" stroke="#ffffff" stroke-width="38" stroke-linecap="round"/>
  <path d="M266 254c34 58 76 102 126 132" fill="none" stroke="#ffffff" stroke-width="38" stroke-linecap="round"/>
  <path d="M160 394c56 28 120 42 192 42" fill="none" stroke="{AMBER}" stroke-width="28" stroke-linecap="round"/>''',
    )


def icon_06_inbox_spark() -> str:
    return svg(
        "客来来图标 06 客源盒",
        f'''  <defs>
    <linearGradient id="boxBg" x1="88" y1="82" x2="426" y2="430" gradientUnits="userSpaceOnUse">
      <stop offset="0" stop-color="{BLUE}"/>
      <stop offset="0.55" stop-color="{CYAN}"/>
      <stop offset="1" stop-color="{GREEN}"/>
    </linearGradient>
  </defs>
  <rect x="64" y="64" width="384" height="384" rx="96" fill="#f2fbff"/>
  <path d="M128 300h86l30 52h24l30-52h86v74c0 34-28 62-62 62H190c-34 0-62-28-62-62z" fill="url(#boxBg)"/>
  <path d="M160 260c58-72 126-110 204-114" fill="none" stroke="{BLUE}" stroke-width="34" stroke-linecap="round"/>
  <path d="M176 292c58 30 122 38 192 22" fill="none" stroke="{AMBER}" stroke-width="30" stroke-linecap="round"/>
  <path d="M256 116l18 44 46 16-46 16-18 44-18-44-46-16 46-16z" fill="{GREEN}"/>''',
    )


def main() -> None:
    ROOT.mkdir(parents=True, exist_ok=True)
    icons = [
        ("01-arrival-ring", "来客环", icon_01_arrival_ring()),
        ("02-leaf-flow", "来叶流", icon_02_leaf_flow()),
        ("03-customer-gate", "来客门", icon_03_customer_gate()),
        ("04-k-loop", "K 回路", icon_04_k_loop()),
        ("05-lai-tile", "来字块", icon_05_lai_tile()),
        ("06-inbox-spark", "客源盒", icon_06_inbox_spark()),
    ]
    for slug, _, content in icons:
        write(ROOT / f"kellai-icon-style-{slug}.svg", content)
    write(
        ROOT / "design-notes.md",
        """# 客来来彩色图标候选

按上一版 Logo 的风格单独做 App/桌面图标：

- 彩色，不做黑白稿。
- 512 方形设计稿，保留圆角安全边距。
- 统一蓝、青、绿、琥珀色系。
- 每个图标只保留一个核心符号，避免把聊天、漏斗、勾选、增长柱全堆进去。

推荐：

1. 01 来客环：和 Logo 主推方向最一致。
2. 02 来叶流：更轻、更亲和。
3. 05 来字块：中文识别最强，适合 App 图标。
""",
    )
    print(f"wrote {len(icons)} icon assets to {ROOT}")


if __name__ == "__main__":
    main()
