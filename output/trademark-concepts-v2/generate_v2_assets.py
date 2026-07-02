from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parent

FONT_STACK = (
    "PingFang SC, Hiragino Sans GB, Microsoft YaHei, Heiti SC, "
    "Arial Unicode MS, sans-serif"
)

PROMPT_ZH_FOUND = (
    "为「客来来」生成 3x3 商标方向九宫格。行业：私域客户增长 / 多渠道客服 / 商机跟进 SaaS / 客户线索转化；"
    "受众：中小商家、销售团队、私域运营、客服主管、门店老板；品牌价值：来客不断、及时跟进、智能获客、"
    "可信赖、轻量易用、把每个来客变成成交机会。九格分别探索文字商标、字母商标、图形商标、抽象商标、"
    "吉祥物商标、组合商标、徽章/印章、App 图标、包装标签。要求平面矢量感、轮廓强、负空间清楚、"
    "印刷安全、不要近似任何现有品牌。"
)

PROMPT_ZH_REFINED = (
    "为「客来来」重新生成 9 个更适合商标注册初筛的独立 Logo/商标候选。行业是私域客户增长、"
    "多渠道客服、客户线索跟进和成交转化 SaaS。目标用户是中小商家、销售团队、客服主管、私域运营、"
    "门店老板。品牌核心是来客不断、及时跟进、把每个来客变成成交机会、轻量可信。每个候选只保留一个"
    "强记忆符号或一个清晰字标，不做海报、不做 mockup、不依赖小字。必须满足：强轮廓、正负形清楚、"
    "黑白单色可用、24px 仍可识别、可转 SVG、印刷安全。可使用的符号暗示：来客入口、消息气泡、"
    "客户流入路径、增长阶梯、成交勾选、线索汇聚。避免直接近似微信、企业微信、钉钉、美团、有赞、"
    "销售易、纷享销客等平台的图标和配色结构。"
)

NEGATIVE_PROMPT = (
    "existing logo, famous brand mark, trademark infringement, copied symbol, app icon clone, "
    "WeChat-like bubble, DingTalk-like bird, Meituan-like shape, Youzan-like mark, stock logo template, "
    "tiny unreadable text, complex gradients, glossy mockup, photo background, watermark, legal emblem"
)


def svg_wrap(width: int, height: int, label: str, body: str) -> str:
    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" role="img" aria-label="{label}">
  <rect width="{width}" height="{height}" fill="#ffffff"/>
{body}
</svg>
'''


def write_text(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def make_assets() -> list[tuple[str, str, str]]:
    navy = "#0f172a"
    blue = "#2563eb"
    teal = "#0891b2"
    green = "#10b981"
    amber = "#f59e0b"
    slate = "#64748b"
    pale = "#e0f2fe"
    pale_green = "#dcfce7"

    assets: list[tuple[str, str, str]] = []

    assets.append((
        "kellai-v2-01-wordmark-rhythm.svg",
        "01 字标节奏",
        svg_wrap(
            960,
            360,
            "客来来商标 v2 01 字标节奏",
            f'''  <g transform="translate(96 92)">
    <text x="0" y="116" fill="{navy}" font-family="{FONT_STACK}" font-size="128" font-weight="900">客来来</text>
    <path d="M12 158h124c32 0 62-12 84-34l30-30 42 44c28 30 66 46 107 46h318" fill="none" stroke="{blue}" stroke-width="18" stroke-linecap="round" stroke-linejoin="round"/>
    <path d="M290 138c32 32 82 32 114 0" fill="none" stroke="{green}" stroke-width="18" stroke-linecap="round"/>
    <circle cx="732" cy="184" r="18" fill="{amber}"/>
    <circle cx="784" cy="184" r="18" fill="{green}"/>
    <circle cx="836" cy="184" r="18" fill="{teal}"/>
  </g>''',
        ),
    ))

    assets.append((
        "kellai-v2-02-entry-flow-mark.svg",
        "02 来客入口",
        svg_wrap(
            640,
            640,
            "客来来商标 v2 02 来客入口",
            f'''  <defs>
    <linearGradient id="entryBg" x1="120" y1="92" x2="520" y2="548" gradientUnits="userSpaceOnUse">
      <stop offset="0" stop-color="{blue}"/>
      <stop offset="0.58" stop-color="{teal}"/>
      <stop offset="1" stop-color="{green}"/>
    </linearGradient>
  </defs>
  <rect x="88" y="84" width="464" height="472" rx="116" fill="url(#entryBg)"/>
  <path d="M222 442V256c0-76 46-126 116-126s116 50 116 126v186h-78V258c0-34-14-58-38-58s-38 24-38 58v184z" fill="#ffffff"/>
  <path d="M180 456c92 54 188 54 280 0" fill="none" stroke="{amber}" stroke-width="32" stroke-linecap="round"/>
  <path d="M326 294h138c28 0 50 22 50 50v10c0 28-22 50-50 50h-50l-54 44v-44h-34c-28 0-50-22-50-50v-10c0-28 22-50 50-50z" fill="#ffffff"/>
  <circle cx="366" cy="350" r="11" fill="{teal}"/>
  <circle cx="408" cy="350" r="11" fill="{teal}"/>
  <circle cx="450" cy="350" r="11" fill="{teal}"/>''',
        ),
    ))

    assets.append((
        "kellai-v2-03-lead-check-symbol.svg",
        "03 线索成交",
        svg_wrap(
            640,
            640,
            "客来来商标 v2 03 线索成交",
            f'''  <circle cx="320" cy="320" r="236" fill="{pale}"/>
  <path d="M162 350c76-112 170-164 284-154" fill="none" stroke="{blue}" stroke-width="42" stroke-linecap="round"/>
  <path d="M188 410h108c36 0 68-18 88-48l62-94" fill="none" stroke="{green}" stroke-width="42" stroke-linecap="round" stroke-linejoin="round"/>
  <path d="M390 338l58 58 118-132" fill="none" stroke="{navy}" stroke-width="44" stroke-linecap="round" stroke-linejoin="round"/>
  <rect x="132" y="388" width="44" height="88" rx="18" fill="{amber}"/>
  <rect x="204" y="344" width="44" height="132" rx="18" fill="{green}"/>
  <rect x="276" y="298" width="44" height="178" rx="18" fill="{teal}"/>''',
        ),
    ))

    assets.append((
        "kellai-v2-04-lai-chat-icon.svg",
        "04 来字气泡",
        svg_wrap(
            640,
            640,
            "客来来商标 v2 04 来字气泡",
            f'''  <defs>
    <linearGradient id="chatIconBg" x1="112" y1="100" x2="528" y2="540" gradientUnits="userSpaceOnUse">
      <stop offset="0" stop-color="{navy}"/>
      <stop offset="0.55" stop-color="{blue}"/>
      <stop offset="1" stop-color="{green}"/>
    </linearGradient>
  </defs>
  <rect x="84" y="84" width="472" height="472" rx="122" fill="url(#chatIconBg)"/>
  <path d="M180 190h280c42 0 76 34 76 76v66c0 42-34 76-76 76h-84l-96 80v-80H180c-42 0-76-34-76-76v-66c0-42 34-76 76-76z" fill="#ffffff"/>
  <text x="320" y="378" text-anchor="middle" fill="{navy}" font-family="{FONT_STACK}" font-size="192" font-weight="900">来</text>
  <circle cx="412" cy="286" r="14" fill="{green}"/>
  <circle cx="462" cy="286" r="14" fill="{green}"/>
  <circle cx="512" cy="286" r="14" fill="{green}"/>''',
        ),
    ))

    assets.append((
        "kellai-v2-05-kll-path-monogram.svg",
        "05 KLL 路径",
        svg_wrap(
            640,
            640,
            "客来来商标 v2 05 KLL 路径",
            f'''  <rect x="94" y="94" width="452" height="452" rx="96" fill="#f8fafc" stroke="#dbe4ef" stroke-width="10"/>
  <path d="M190 456V184" fill="none" stroke="{navy}" stroke-width="62" stroke-linecap="round"/>
  <path d="M210 326l216-142" fill="none" stroke="{blue}" stroke-width="62" stroke-linecap="round"/>
  <path d="M220 326l224 140" fill="none" stroke="{green}" stroke-width="62" stroke-linecap="round"/>
  <path d="M374 324h82c54 0 96 42 96 96s-42 96-96 96H342" fill="none" stroke="{amber}" stroke-width="42" stroke-linecap="round"/>
  <circle cx="424" cy="421" r="13" fill="{navy}"/>
  <circle cx="472" cy="421" r="13" fill="{navy}"/>''',
        ),
    ))

    assets.append((
        "kellai-v2-06-channel-hub.svg",
        "06 渠道汇聚",
        svg_wrap(
            640,
            640,
            "客来来商标 v2 06 渠道汇聚",
            f'''  <circle cx="320" cy="320" r="62" fill="{navy}"/>
  <circle cx="320" cy="320" r="170" fill="none" stroke="{pale}" stroke-width="38"/>
  <path d="M320 150v108M492 258l-92 46M478 424l-92-50M320 490V382M162 424l92-50M148 258l92 46" fill="none" stroke="{blue}" stroke-width="30" stroke-linecap="round"/>
  <circle cx="320" cy="118" r="58" fill="{green}"/>
  <circle cx="520" cy="236" r="58" fill="{teal}"/>
  <circle cx="504" cy="462" r="58" fill="{amber}"/>
  <circle cx="320" cy="522" r="58" fill="{green}"/>
  <circle cx="136" cy="462" r="58" fill="{teal}"/>
  <circle cx="120" cy="236" r="58" fill="{amber}"/>
  <path d="M284 312h72c20 0 36 16 36 36s-16 36-36 36h-18l-38 34v-34h-16c-20 0-36-16-36-36s16-36 36-36z" fill="#ffffff"/>''',
        ),
    ))

    assets.append((
        "kellai-v2-07-funnel-growth.svg",
        "07 获客漏斗",
        svg_wrap(
            640,
            640,
            "客来来商标 v2 07 获客漏斗",
            f'''  <path d="M104 146h432L380 324v128l-120 56V324z" fill="{navy}"/>
  <path d="M166 198h308L356 320v86l-72 34v-120z" fill="#ffffff"/>
  <path d="M144 510c82-40 168-40 258-2 34 14 68 14 102-4" fill="none" stroke="{green}" stroke-width="34" stroke-linecap="round"/>
  <circle cx="204" cy="126" r="28" fill="{blue}"/>
  <circle cx="320" cy="96" r="28" fill="{green}"/>
  <circle cx="436" cy="126" r="28" fill="{amber}"/>
  <path d="M232 244h176" stroke="{teal}" stroke-width="28" stroke-linecap="round"/>''',
        ),
    ))

    assets.append((
        "kellai-v2-08-trust-seal-clean.svg",
        "08 可信印章",
        svg_wrap(
            640,
            640,
            "客来来商标 v2 08 可信印章",
            f'''  <circle cx="320" cy="320" r="248" fill="#ffffff" stroke="{navy}" stroke-width="26"/>
  <circle cx="320" cy="320" r="184" fill="{pale_green}" stroke="{green}" stroke-width="18"/>
  <path d="M218 304h204c28 0 50 22 50 50v16c0 28-22 50-50 50h-56l-62 48v-48h-86c-28 0-50-22-50-50v-16c0-28 22-50 50-50z" fill="{navy}"/>
  <circle cx="268" cy="362" r="13" fill="#ffffff"/>
  <circle cx="320" cy="362" r="13" fill="#ffffff"/>
  <circle cx="372" cy="362" r="13" fill="#ffffff"/>
  <text x="320" y="254" text-anchor="middle" fill="{navy}" font-family="{FONT_STACK}" font-size="96" font-weight="900">客来来</text>
  <path d="M232 488c56 42 120 42 176 0" fill="none" stroke="{green}" stroke-width="24" stroke-linecap="round"/>''',
        ),
    ))

    assets.append((
        "kellai-v2-09-mono-core-mark.svg",
        "09 单色核心",
        svg_wrap(
            640,
            640,
            "客来来商标 v2 09 单色核心",
            f'''  <rect x="96" y="96" width="448" height="448" rx="108" fill="{navy}"/>
  <path d="M196 398V232c0-58 38-96 94-96h88c56 0 94 38 94 96v166h-68V236c0-22-12-36-32-36h-76c-20 0-32 14-32 36v162z" fill="#ffffff"/>
  <path d="M230 460c58 34 122 48 190 34" fill="none" stroke="#ffffff" stroke-width="34" stroke-linecap="round"/>
  <path d="M330 288h100c30 0 54 24 54 54s-24 54-54 54h-28l-48 42v-42h-24c-30 0-54-24-54-54s24-54 54-54z" fill="{navy}" stroke="#ffffff" stroke-width="26"/>
  <circle cx="360" cy="342" r="10" fill="#ffffff"/>
  <circle cx="398" cy="342" r="10" fill="#ffffff"/>
  <circle cx="436" cy="342" r="10" fill="#ffffff"/>''',
        ),
    ))

    return assets


def write_prompt_file() -> None:
    text = f"""# 客来来商标 v2 提示词

## 找到的员工原始提示词

{PROMPT_ZH_FOUND}

## 重新生成使用的注册候选提示词

{PROMPT_ZH_REFINED}

## 负面提示词

{NEGATIVE_PROMPT}

## 落图约束

- 每个方向单独成稿，不做海报或样机。
- 中文字标使用系统中文字体作为草稿，正式商标应再做字体授权或定制字形。
- 必须保留黑白版、反白版和 24px 小尺寸检查。
- 正式注册前做近似商标检索和法务复核。
"""
    write_text(ROOT / "prompts-used.md", text)


def write_index(assets: list[tuple[str, str, str]]) -> None:
    cards = "\n".join(
        f'''      <figure>
        <img src="{filename}" alt="{label}">
        <figcaption>{label}</figcaption>
      </figure>'''
        for filename, label, _ in assets
    )
    html = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>客来来商标候选稿 v2</title>
  <style>
    :root {{
      color-scheme: light;
      font-family: {FONT_STACK};
      color: #0f172a;
      background: #f8fafc;
    }}
    body {{
      margin: 0;
      padding: 48px;
    }}
    h1 {{
      margin: 0 0 10px;
      font-size: 36px;
      line-height: 1.2;
    }}
    .note {{
      margin: 0 0 32px;
      color: #64748b;
      font-size: 16px;
      line-height: 1.7;
      max-width: 980px;
    }}
    .grid {{
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 24px;
    }}
    figure {{
      margin: 0;
      background: #fff;
      border: 1px solid #dbe4ef;
      border-radius: 8px;
      padding: 22px;
    }}
    img {{
      width: 100%;
      aspect-ratio: 1 / 1;
      object-fit: contain;
      display: block;
      background: #fff;
    }}
    figcaption {{
      margin-top: 16px;
      font-weight: 800;
      color: #0f172a;
    }}
    @media (max-width: 980px) {{
      body {{ padding: 24px; }}
      .grid {{ grid-template-columns: 1fr; }}
    }}
  </style>
</head>
<body>
  <h1>客来来商标候选稿 v2</h1>
  <p class="note">根据商标生成员内置提示词重新改写为“注册候选”方向：强轮廓、少小字、可黑白化、可小尺寸识别。SVG 为可编辑草案，正式注册前仍需商标近似检索。</p>
  <main class="grid">
{cards}
  </main>
</body>
</html>
"""
    write_text(ROOT / "index.html", html)


def main() -> None:
    ROOT.mkdir(parents=True, exist_ok=True)
    assets = make_assets()
    for filename, _, svg in assets:
        write_text(ROOT / filename, svg)
    write_prompt_file()
    write_index(assets)
    print(f"wrote {len(assets)} svg assets to {ROOT}")


if __name__ == "__main__":
    main()
