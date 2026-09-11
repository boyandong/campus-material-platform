"""生成校园资料目录帖图片和九份资料的私聊样图。

依赖 Pillow。默认在项目根目录运行：
    python scripts/generate_catalog_assets.py
"""

from pathlib import Path
import sys

from PIL import Image, ImageDraw, ImageFont


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


PROJECT_ROOT = Path(__file__).resolve().parent.parent
CATALOG_DIR = PROJECT_ROOT / "marketing" / "catalog"
PREVIEW_DIR = PROJECT_ROOT / "marketing" / "previews"
FONT_REGULAR = Path(r"C:\Windows\Fonts\msyh.ttc")
FONT_BOLD = Path(r"C:\Windows\Fonts\msyhbd.ttc")

WIDTH, HEIGHT = 1080, 1440
NAVY = "#14213D"
TEAL = "#0F766E"
TEAL_LIGHT = "#D9F3EE"
ORANGE = "#F59E0B"
ORANGE_LIGHT = "#FEF3C7"
INK = "#172033"
MUTED = "#667085"
PAPER = "#F7F5EF"
WHITE = "#FFFFFF"
LINE = "#D8DEE8"


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    path = FONT_BOLD if bold else FONT_REGULAR
    if not path.exists():
        raise FileNotFoundError(f"缺少中文字体：{path}")
    return ImageFont.truetype(str(path), size=size)


def wrap_text(draw: ImageDraw.ImageDraw, text: str, used_font, max_width: int) -> list[str]:
    lines: list[str] = []
    for paragraph in text.split("\n"):
        if not paragraph:
            lines.append("")
            continue
        current = ""
        for char in paragraph:
            candidate = current + char
            if current and draw.textlength(candidate, font=used_font) > max_width:
                lines.append(current)
                current = char
            else:
                current = candidate
        if current:
            lines.append(current)
    return lines


def paragraph(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int],
    text: str,
    used_font,
    fill: str,
    max_width: int,
    line_gap: int = 10,
) -> int:
    x, y = xy
    bbox = draw.textbbox((0, 0), "国Ag", font=used_font)
    line_height = bbox[3] - bbox[1]
    for line in wrap_text(draw, text, used_font, max_width):
        draw.text((x, y), line, font=used_font, fill=fill)
        y += line_height + line_gap
    return y


def rounded(draw, box, radius=28, fill=WHITE, outline=None, width=1):
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def base_page(kicker: str, title: str, subtitle: str, page_no: str):
    image = Image.new("RGB", (WIDTH, HEIGHT), PAPER)
    draw = ImageDraw.Draw(image)
    draw.ellipse((790, -170, 1210, 250), fill=TEAL_LIGHT)
    draw.ellipse((-120, 1160, 260, 1540), fill=ORANGE_LIGHT)
    draw.text((72, 64), kicker, font=font(26, True), fill=TEAL)
    y = paragraph(draw, (72, 116), title, font(62, True), NAVY, 900, 10)
    paragraph(draw, (74, y + 20), subtitle, font(28), MUTED, 880, 12)
    draw.text((925, 1360), page_no, font=font(22, True), fill=MUTED)
    return image, draw


def pill(draw, xy, text, bg, fg):
    x, y = xy
    used_font = font(24, True)
    w = int(draw.textlength(text, font=used_font)) + 46
    rounded(draw, (x, y, x + w, y + 52), radius=26, fill=bg)
    draw.text((x + 23, y + 9), text, font=used_font, fill=fg)
    return w


def product_card(draw, y, code, name, detail, price, accent=TEAL):
    rounded(draw, (72, y, 1008, y + 208), radius=30, fill=WHITE, outline=LINE, width=2)
    rounded(draw, (96, y + 28, 204, y + 80), radius=26, fill=accent)
    code_font = font(25, True)
    code_w = draw.textlength(code, font=code_font)
    draw.text((150 - code_w / 2, y + 38), code, font=code_font, fill=WHITE)
    draw.text((228, y + 26), name, font=font(34, True), fill=INK)
    paragraph(draw, (98, y + 102), detail, font(24), MUTED, 720, 8)
    draw.text((872, y + 112), price, font=font(36, True), fill=accent)


def save(image: Image.Image, folder: Path, filename: str):
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / filename
    image.save(path, format="PNG", optimize=True)
    return path


def make_catalog_pages():
    outputs = []

    image, draw = base_page(
        "校园资料目录 · 暑假验证版",
        "先看样图，\n再决定要不要买",
        "2025–2026资料为主｜版本与适用范围逐份标注",
        "1 / 6",
    )
    y = 450
    x = 72
    for text, bg, fg in [
        ("9份首批资料", TEAL_LIGHT, TEAL),
        ("3大类别", ORANGE_LIGHT, "#A15C00"),
        ("5–8元", "#E8EAFD", "#444BB0"),
    ]:
        x += pill(draw, (x, y), text, bg, fg) + 18
    rounded(draw, (72, 570, 1008, 1085), radius=40, fill=NAVY)
    draw.text((120, 628), "公共课复习", font=font(40, True), fill=WHITE)
    draw.text((120, 720), "计算机课程", font=font(40, True), fill=WHITE)
    draw.text((120, 812), "实验原理与仿真参考", font=font(40, True), fill=WHITE)
    draw.line((120, 914, 960, 914), fill="#50617E", width=2)
    draw.text((120, 962), "咨询时发送资料编号", font=font(31), fill="#DDE5F2")
    draw.text((120, 1013), "例如：B02", font=font(31, True), fill=ORANGE)
    paragraph(draw, (74, 1155), "资料来自校园同学授权提供。来源、版本与适用范围确认后上架。", font(25), MUTED, 870, 8)
    outputs.append(save(image, CATALOG_DIR, "01-cover.png"))

    image, draw = base_page("A类 · 公共课", "复习框架与考前整理", "适合快速梳理重点；购买前可先看样图", "2 / 6")
    product_card(draw, 390, "A01", "习概考前复习提纲", "知识框架｜重点概念｜2025–2026春", "¥5")
    product_card(draw, 628, "A02", "毛概期末复习整理", "个人版整理｜2025秋｜适用范围咨询确认", "¥5")
    product_card(draw, 866, "A03", "军事理论知识框架", "思维框架版｜2024–2025资料｜版本已标注", "¥5")
    rounded(draw, (72, 1118, 1008, 1288), radius=30, fill=ORANGE_LIGHT)
    draw.text((104, 1152), "A04  套餐", font=font(30, True), fill="#9A5900")
    draw.text((104, 1210), "任选两份 ¥8｜三份 ¥12", font=font(34, True), fill="#9A5900")
    outputs.append(save(image, CATALOG_DIR, "02-public-courses.png"))

    image, draw = base_page("B类 · 计算机课程", "把复习范围变得更清楚", "资料编号直接对应私聊样图，减少来回沟通", "3 / 6")
    product_card(draw, 390, "B01", "数据结构考前复习提纲", "复杂度｜线性表｜树图｜查找与排序", "¥5", "#4F46A5")
    product_card(draw, 628, "B02", "操作系统复习问答", "进程线程｜同步死锁｜内存与文件系统", "¥5", "#4F46A5")
    product_card(draw, 866, "B03", "计算机组成原理复习要点", "数据表示｜指令系统｜CPU｜存储与I/O", "¥5", "#4F46A5")
    paragraph(draw, (90, 1155), "老师、考试范围和版本可能不同，下单前请先核对适用性。", font(27), MUTED, 870, 10)
    outputs.append(save(image, CATALOG_DIR, "03-computer-science.png"))

    image, draw = base_page("C类 · 实验学习参考", "看原理、仿真与数据处理", "只作学习参考；实验与报告必须独立完成", "4 / 6")
    product_card(draw, 390, "C01", "数电实验原理与仿真参考包", "真值表｜表达式｜原理图｜仿真与连接参考", "¥8", "#B45309")
    product_card(draw, 628, "C02", "电路实验原理与仿真参考包", "RC频率特性｜RLC谐振｜Multisim｜数据处理", "¥8", "#B45309")
    product_card(draw, 866, "C03", "大学物理实验方法参考包", "霍尔效应｜受迫振动｜方法与误差分析", "¥8", "#B45309")
    rounded(draw, (72, 1125, 1008, 1295), radius=28, fill="#FFF4E5", outline="#F4C37D", width=2)
    paragraph(draw, (100, 1162), "不提供“直接提交”服务；请依据自己的实验过程和数据完成作业。", font(27, True), "#8A4B00", 840, 10)
    outputs.append(save(image, CATALOG_DIR, "04-lab-reference.png"))

    image, draw = base_page("购买流程", "四步拿到合适的资料", "先确认适用性，再付款，不合适就不买", "5 / 6")
    steps = [
        ("01", "发送编号", "例如 B02 或 A04"),
        ("02", "查看样图", "核对内容、年份与范围"),
        ("03", "确认付款", "单份5–8元，套餐另计"),
        ("04", "完成交付", "收到后及时检查文件"),
    ]
    y = 380
    for number, title, body in steps:
        rounded(draw, (72, y, 1008, y + 190), radius=28, fill=WHITE, outline=LINE, width=2)
        rounded(draw, (98, y + 42, 190, y + 134), radius=46, fill=TEAL)
        draw.text((116, y + 64), number, font=font(29, True), fill=WHITE)
        draw.text((226, y + 34), title, font=font(36, True), fill=INK)
        draw.text((226, y + 100), body, font=font(27), fill=MUTED)
        y += 214
    outputs.append(save(image, CATALOG_DIR, "05-purchase-flow.png"))

    image, draw = base_page("现在怎么问", "直接发送资料编号", "不用先解释一大段，我会先发对应样图", "6 / 6")
    rounded(draw, (72, 400, 1008, 800), radius=42, fill=NAVY)
    draw.text((124, 470), "示例", font=font(28, True), fill=ORANGE)
    draw.text((124, 548), "“你好，我想看 B02 的样图”", font=font(42, True), fill=WHITE)
    draw.text((124, 642), "“A01 + A02 套餐还有吗？”", font=font(36), fill="#DDE5F2")
    rounded(draw, (72, 860, 1008, 1090), radius=34, fill=TEAL_LIGHT)
    draw.text((112, 908), "同学推荐来的？", font=font(31, True), fill=TEAL)
    paragraph(draw, (112, 968), "请顺手告诉我推荐人编号，帮助我们统计真实口碑来源。", font(28), TEAL, 820, 10)
    paragraph(draw, (74, 1175), "样图只用于判断内容是否合适，请勿传播。资料版本与适用范围以私聊确认为准。", font(25), MUTED, 870, 9)
    outputs.append(save(image, CATALOG_DIR, "06-send-code.png"))
    return outputs


def make_preview(code, title, subtitle, bullets, accent):
    image, draw = base_page(f"{code} · 私聊样图", title, subtitle, "样图")
    rounded(draw, (72, 390, 1008, 1110), radius=36, fill=WHITE, outline=LINE, width=2)
    y = 452
    for item in bullets:
        rounded(draw, (112, y + 5, 150, y + 43), radius=19, fill=accent)
        draw.text((174, y), item, font=font(31, True), fill=INK)
        y += 102
    rounded(draw, (72, 1160, 1008, 1305), radius=28, fill="#EEF2F7")
    paragraph(draw, (105, 1195), "本图展示资料覆盖范围，不代表考试命题；购买前请确认课程、老师和年份。", font(24), MUTED, 830, 8)
    return save(image, PREVIEW_DIR, f"{code}.png")


def make_previews():
    specs = [
        ("A01", "习概考前复习提纲", "知识框架式预览", ["中国式现代化", "坚持党的领导", "全面深化改革", "高质量发展", "人与自然和谐共生"], TEAL),
        ("A02", "毛概期末复习整理", "个人版内容范围预览", ["马克思主义中国化时代化", "毛泽东思想主要内容", "新民主主义革命理论", "社会主义革命与建设", "理论成果之间的关系"], TEAL),
        ("A03", "军事理论知识框架", "2024–2025版本", ["中国国防", "总体国家安全观", "国际战略形势", "军事思想", "现代战争与信息化装备"], TEAL),
        ("B01", "数据结构考前复习提纲", "章节范围预览", ["复杂度与抽象数据类型", "线性表", "栈与队列", "树与图", "查找与排序"], "#4F46A5"),
        ("B02", "操作系统复习问答", "问题式整理预览", ["操作系统结构", "进程与线程", "同步与死锁", "内存管理", "文件与I/O系统"], "#4F46A5"),
        ("B03", "计算机组成原理复习要点", "核心概念预览", ["数据表示与运算", "指令系统", "CPU与控制器", "存储系统", "输入输出系统"], "#4F46A5"),
        ("C01", "数电实验学习参考包", "原理与仿真范围", ["真值表与卡诺图", "逻辑表达式", "原理图", "仿真文件", "硬件连接参考"], "#B45309"),
        ("C02", "电路实验学习参考包", "原理与仿真范围", ["RC低通与高通", "频率特性", "RLC谐振", "Multisim仿真", "数据处理参考"], "#B45309"),
        ("C03", "大学物理实验方法参考包", "方法与分析范围", ["霍尔效应原理", "受迫振动与共振", "实验步骤参考", "数据处理方法", "误差分析思路"], "#B45309"),
    ]
    return [make_preview(*spec) for spec in specs]


def main():
    outputs = make_catalog_pages() + make_previews()
    print(f"已生成 {len(outputs)} 张图片：")
    for path in outputs:
        print(path.relative_to(PROJECT_ROOT))


if __name__ == "__main__":
    main()
