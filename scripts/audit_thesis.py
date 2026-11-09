#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""中文学位论文机械检查（通用版）。只读，不改任何文件。

设计原则：结构性检查与通用硬伤内置，领域词表外置扩展。
提供词表时，词表规则与内置规则合并生效（不覆盖抹除内置规则）。
不提供词表时，脚本自动运行与学科无关的项：
  - L0: 盲审自贬递刀、主体归属缺失、浮动体乱序、幽灵表图、未引用浮动体/文献、
        复合指标逐行验算、尺度混用换算、math mode、首现缩写（自动区分外部文献引用与未定义缩写）
  - L1: 拼稿痕迹（补充材料/篇幅限制/两篇/合订）、第一人称出戏（“我们”）、
        机翻跳戏与出格口语、Markdown与占位残留、元写作、翻译腔数学、
        封面长标题双参数断行、未引用孤立模板文件
  - L2: 动词分布、否定密度、AI时空套话（报告坐标）、破折号密度（含---）、小节段末自卫
  - L3: 术语跨章分裂（词元vs标记、主干vs骨干等）、封面与答辩必填预留字段待填提示
  - 编译日志核验（可选，自动搜索或指定日志）

用法:
    python audit_thesis.py <tex_root> [--terms terms.json] [-o report.md] [--log build/x.log]
"""
import argparse
import json
import math
import re
import sys
from collections import Counter
from pathlib import Path

# 确保在 Windows 控制台输出 UTF-8
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

SKIP_DIRS = {"backups", "archive", "build", "out", ".git", "node_modules"}

# ---------------- 内置通用模式（学科无关） ----------------
# L0 通用：盲审递刀与过度自贬（给盲审送枪毙把柄：直陈核心缺失/缺陷/未验证）
SELF_DEPRECATION_DEFAULT = (
    r"(未能(充分|有效)?(证明|解决|验证|覆盖|达到)|"
    r"没有(开展|进行|实现|做)|"
    r"并未(开展|进行|实现|做|验证|证明|探索|考虑|深入)|"
    r"尚未(开展|进行|实现|做|验证|探索|解决|深入)|"
    r"(缺少|缺乏)(消融|用户|对比|基线|验证|理论|支撑|证明|数据)|"
    r"严重不足|效果(较差|不佳|欠佳)|性能(较差|不佳|欠佳)|表现(较差|不佳|欠佳|不尽如人意)|"
    r"劣势在于|遗憾的是|致命缺陷|先天不足|"
    r"(无法|难以)(保证|有效解决|应对|推广)|"
    r"在.{0,10}下失效|"
    r"坦白(而言|地说)|我们承认|"
    r"泛化(能力)?(较差|不足|有限)|鲁棒性(较差|不足|欠佳))"
)

# L0 通用：方法章主体归属缺失（方法章内把自己方法写成外部对象或他人复现）
SUBJECT_ATTR_DEFAULT = (
    r"(本章|本节)(研究|介绍|讨论|分析|使用|只使用|采用)(了)?[^。]{0,30}(方法|工作|框架)|"
    r"该(工作|方法|论文)(的)?(实验|结论|设置|数据)"
)

# L0 通用：跨协议尺度混用与随意换算（配合前序否定断言排除“不能/不可/不做换算”）
SCALE_CONVERT_DEFAULT = r"(?:除以|乘以|换算|折算|归一到|归一化到)"

# L1 通用：拼稿痕迹与小论文直接合订（暴露英文会议小论文合订、补充材料与篇幅限制残留，排除张量拼接）
COMPOSITE_DEFAULT = (
    r"两篇(论文|工作)?|合订|补充材料|补充实验|小论文|原始工作|原论文|"
    r"原文(?!本|献|档|稿)|"
    r"受?篇幅(限制|原因|所限)|正文与补充材料|"
    r"(?<!特征|词元|状态|向量|通道|张量|维度|一步|多头)拼接(?!并投影)"
)

# L1 通用：第一人称复数（暴露英文多作者小论文机翻拼合）
FIRST_PERSON_DEFAULT = (
    r"我们(的|提出|设计|发现|认为|构建|采用|使用|观察到|注意到|引入|将|证明|推导|对比|选取|选择|总结|团队|工作|实验|模型|方法|框架|在此|进一步)"
)

# L1 通用：机翻跳戏、指代不明与非学术口语（排除“其实际/其实验”等中性代词结构）
COLLOQUIAL_DEFAULT = (
    r"假装|口号|甩锅|硬凑|一锅端|顺便|毕竟|反正|"
    r"其实(?!际|验|施|质|体|况|效)|"
    r"文中(指出|给出|表明|提到|记为|所述)|"
    r"在另一(套|台|项)|另一套实现|先前的实现|原始实现|原表|"
    r"有趣的是|不幸的是|令人惊讶的是|众所周知|不难看出|不难发现|显而易见|"
    r"直观上|直观来看|直观地说|简单来说|简而言之|"
    r"正如(前文|文中所述|预期)|如我们所见"
)

# L1 通用：Markdown 粗体残留、代码块标记与 TODO 占位符
MARKDOWN_RESIDUE_RX = r"\*\*[^\*\n]+\*\*|```|(?<!\\)#{1,4}\s+|TODO|FIXME|TBD|待补充|待核实|XXX"

# L1 通用：元写作短语
META_DEFAULT = (
    r"值得(指出|说明|展开|注意|强调)|需要(分别)?(陈述|说明|讨论)|"
    r"读者(可能|容易)|不应被理解为|不能被改写成|不是对方法本身的否定|"
    r"(本节|本章|下面|后续)(将|会)(说明|给出|讨论|介绍)"
)

# L2 通用：否定密度与自卫
NEG_RX = r"不是[^。]{0,30}而是|而非|并不|并非"
SELF_DEF = r"(并不意味着|不等同于|不能简单|不可|不应|而非|而不是|仅限于|不代表)[^。]*。"
VERBS = ["说明", "表明", "显示", "证实", "反映", "揭示", "体现", "验证"]

# L2 通用：特征连词与空泛升华
CLICHE_RX = (
    r"综上所述|值得注意的是|不可否认的是|显而易见的是|不仅如此|总而言之|双刃剑|赋能|如同[^。]{0,10}一样|"
    r"具有重要的?(理论|实践|现实)意义|为后续研究提供(了)?(有益|重要)?(参考|借鉴)"
)

# L2 通用：AI 宏大时空套话与空泛修饰
AI_CLICHE_DEFAULT = (
    r"(近年来|随着).{0,15}(飞速发展|迅猛发展|蓬勃发展|广泛关注|日益增加)|"
    r"扮演着.{0,8}(角色|地位)|不可或缺|举足轻重|作为.{0,10}(基石|纽带|桥梁)|"
    r"毋庸置疑|不言而喻|全方位|多维度|深层次|系统性地|"
    r"显著提升了?|极大程度地|注入了新的活力|开辟了新的道路|奠定了坚实的基础|"
    r"如同一把双刃剑|如同双刃剑"
)

MATH_ENVS = (
    r"\$\$[\s\S]*?\$\$",
    r"(?<!\\)\$[^$\n]*?(?<!\\)\$",
    r"\\begin\{(?:equation|align|gather|multline|eqnarray|displaymath|split|aligned|gathered|flalign)\*?\}[\s\S]*?"
    r"\\end\{(?:equation|align|gather|multline|eqnarray|displaymath|split|aligned|gathered|flalign)\*?\}",
    r"\\\[[\s\S]*?\\\]",
    r"\\\([\s\S]*?\\\)",
)

CODE_ENVS = (
    r"\\begin\{(?:lstlisting|verbatim|minted)\*?\}[\s\S]*?"
    r"\\end\{(?:lstlisting|verbatim|minted)\*?\}",
)

ACR_STOP = {
    "ACM", "IEEE", "CVPR", "ICCV", "ECCV", "AAAI", "ICLR", "ICML", "NIPS", "SIGGRAPH",
    "COCO", "GPU", "CPU", "TPU", "API", "PDF", "DOI", "URL", "PNG", "JPG", "JPEG", "RGB", "RGBA",
    "TPAMI", "DPM", "FF", "MLP", "CNN", "RNN", "GAN", "VAE", "KL", "L2", "L1", "ViT", "LLM",
    "GB", "MB", "KB", "TB", "PB", "FPS", "HZ", "KHZ", "MHZ", "GHZ", "MS", "SEC", "MIN",
    "AI", "ML", "DL", "NLP", "CV", "RL", "SOTA", "CUDA", "ASCII", "UTF", "BERT", "GPT",
    # 领域通用指标、视觉基线与硬件宏包
    "FID", "LPIPS", "PSNR", "SSIM", "SD", "SDXL", "EDM", "IP", "DUT", "RTX", "NVIDIA",
}

DEFAULT_TERM_PAIRS = [
    ("词元", r"标记(?!语言)"),
    ("提示词", r"提示语(?!义)"),
    ("主干", "骨干"),
    ("隐空间", "潜空间"),
    ("风格迁移", "风格转换"),
    ("保真度", "真实度"),
    ("微调", "调优"),
]


def find_master_tex(root: Path) -> Path | None:
    """寻找主入口文件（包含 \\documentclass 与 \\begin{document}）。"""
    candidates = []
    for p in root.rglob("*.tex"):
        rel_parts = p.relative_to(root).parts[:-1]
        if any(part in SKIP_DIRS for part in rel_parts):
            continue
        try:
            content = p.read_text(encoding="utf-8", errors="ignore")
            if "\\documentclass" in content and "\\begin{document}" in content:
                candidates.append(p)
        except Exception:
            pass
    if candidates:
        for c in candidates:
            if any(k in c.stem.lower() for k in ["thesis", "main"]):
                return c
        return candidates[0]
    return None


def get_tex_structure(root: Path):
    """解析主文件物理包含顺序，区分正文包含文件与未引用的孤立文件。"""
    master = find_master_tex(root)
    ordered = []
    seen = set()

    if master:
        ordered.append(master)
        seen.add(master.resolve())
        m_txt = strip_comments(master.read_text(encoding="utf-8", errors="ignore"))
        for m in re.finditer(r"\\(?:include|input)\{([^}]+)\}", m_txt):
            target = m.group(1).strip()
            if not target.endswith(".tex"):
                target_tex = target + ".tex"
            else:
                target_tex = target
            for cand in ((master.parent / target_tex).resolve(), (root / target_tex).resolve()):
                if cand.exists() and cand not in seen:
                    ordered.append(cand)
                    seen.add(cand)
                    break

    unincluded = []
    for p in root.rglob("*.tex"):
        rel_parts = p.relative_to(root).parts[:-1]
        if any(part in SKIP_DIRS for part in rel_parts):
            continue
        if p.resolve() not in seen:
            unincluded.append(p)

    def sort_key(p: Path):
        stem = p.stem.lower()
        if "abstract" in stem or "denotation" in stem:
            return (0, stem)
        if "chapter" in stem:
            nums = re.findall(r"\d+", stem)
            n = int(nums[0]) if nums else 0
            return (1, n, stem)
        if "app" in stem:
            nums = re.findall(r"\d+", stem)
            n = int(nums[0]) if nums else 0
            return (2, n, stem)
        return (3, stem)

    unincluded.sort(key=sort_key)
    return master, ordered, unincluded


def iter_tex(root: Path):
    """按主文件物理包含顺序组织遍历。"""
    _, ordered, unincluded = get_tex_structure(root)
    for p in ordered + unincluded:
        yield p


def strip_comments(text: str) -> str:
    """去除 LaTeX 行内注释，正确处理 \\% 转义，保留换行以保证行号完全一致。"""
    lines = text.split("\n")
    cleaned = []
    for line in lines:
        m = re.search(r"(?<!\\)(?:\\\\)*(%)", line)
        if m:
            cleaned.append(line[:m.start(1)])
        else:
            cleaned.append(line)
    return "\n".join(cleaned)


def non_prose_spans(text: str):
    """提取公式环境与代码环境的区间，避免在公式/代码内检测缩写与变量。"""
    spans = []
    for rx in MATH_ENVS + CODE_ENVS:
        for m in re.finditer(rx, text, re.S):
            spans.append((m.start(), m.end()))
    return spans


def in_spans(spans, pos: int) -> bool:
    for a, b in spans:
        if a <= pos <= b:
            return True
    return False


def line_of(text: str, pos: int) -> int:
    return text.count("\n", 0, pos) + 1


def all_hits(rx: str, text: str):
    return [(m.start(), m.group(0)) for m in re.finditer(rx, text)]


def merge_rx(default: str, user_rx: str = None) -> str:
    """合并内置规则与用户规则，防止用户提供自定义词表时意外抹除默认硬伤检查。"""
    if not user_rx:
        return default
    if not default:
        return user_rx
    return f"(?:{default})|(?:{user_rx})"


def load_terms(path: str, root: Path = None):
    if not path:
        return {}
    p = Path(path)
    if not p.exists() and root and (root / path).exists():
        p = root / path
    if not p.exists():
        print(f"[警告] 指定的词表文件不存在: {path}，跳过词表增量规则。", file=sys.stderr)
        return {}
    try:
        t = json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[警告] 词表文件解析失败: {e}，跳过词表增量规则。", file=sys.stderr)
        return {}
    out = {}
    keys = ("codename", "bare_en", "composite", "meta",
            "self_deprecate", "first_person", "colloquial", "ai_cliche")
    for k in keys:
        vals = t.get(k) or []
        if vals:
            out[k] = "|".join("(?:%s)" % v for v in vals)
    if "term_pairs" in t and isinstance(t["term_pairs"], list):
        out["term_pairs"] = t["term_pairs"]
    return out


def verify_composite_tables(files, texts, rel):
    """机械核算表格中复合指标（ArtFID、SCH）公式自洽性。"""
    results = []
    inconsistencies = []
    for p in files:
        t = texts[p]
        for tm in re.finditer(r"\\begin\{tabular\}\s*\{([^}]+)\}([\s\S]*?)\\end\{tabular\}", t):
            body = tm.group(2)
            lines = [ln.strip() for ln in body.split(r"\\") if ln.strip()]
            if not lines:
                continue
            header = lines[0]
            # 1. 验算 ArtFID = (1 + LPIPS) * (1 + FID)
            if "ArtFID" in header and "FID" in header and "LPIPS" in header:
                cols = [c.strip() for c in header.split("&")]
                idx_art = next((i for i, c in enumerate(cols) if "ArtFID" in c), -1)
                idx_fid = next((i for i, c in enumerate(cols) if re.search(r"\bFID\b", c)), -1)
                idx_lp = next((i for i, c in enumerate(cols) if "LPIPS" in c and "gray" not in c), -1)
                if idx_art != -1 and idx_fid != -1 and idx_lp != -1:
                    row_ok, row_fail = 0, 0
                    for row_idx, row in enumerate(lines[1:], start=2):
                        if "&" not in row:
                            continue
                        cells = [re.sub(r"\\textbf\{([^}]+)\}", r"\1", c.strip()) for c in row.split("&")]
                        if len(cells) > max(idx_art, idx_fid, idx_lp):
                            m_art = re.search(r"\d+(?:\.\d+)?", cells[idx_art])
                            m_fid = re.search(r"\d+(?:\.\d+)?", cells[idx_fid])
                            m_lp = re.search(r"\d+(?:\.\d+)?", cells[idx_lp])
                            if m_art and m_fid and m_lp:
                                v_art = float(m_art.group(0))
                                v_fid = float(m_fid.group(0))
                                v_lp = float(m_lp.group(0))
                                calc = (1.0 + v_lp) * (1.0 + v_fid)
                                if abs(calc - v_art) > 0.15:
                                    inconsistencies.append(
                                        f"{rel[p]} 行「{cells[0]}」: ArtFID={v_art}，代入公式计算为 {calc:.3f}（差值 {abs(calc - v_art):.3f}）"
                                    )
                                    row_fail += 1
                                else:
                                    row_ok += 1
                    results.append(f"ArtFID 表 ({rel[p]}): {row_ok} 行自洽，{row_fail} 行不符")

            # 2. 验算 SCH = sqrt(CSD * CLIP-I)
            if "SCH" in header and "CSD" in header and "CLIP-I" in header:
                cols = [c.strip() for c in header.split("&")]
                idx_sch = next((i for i, c in enumerate(cols) if "SCH" in c), -1)
                idx_csd = next((i for i, c in enumerate(cols) if "CSD" in c), -1)
                idx_clip = next((i for i, c in enumerate(cols) if "CLIP-I" in c), -1)
                if idx_sch != -1 and idx_csd != -1 and idx_clip != -1:
                    row_ok, row_fail = 0, 0
                    for row_idx, row in enumerate(lines[1:], start=2):
                        if "&" not in row:
                            continue
                        cells = [re.sub(r"\\textbf\{([^}]+)\}", r"\1", c.strip()) for c in row.split("&")]
                        if len(cells) > max(idx_sch, idx_csd, idx_clip):
                            m_sch = re.search(r"\d+(?:\.\d+)?", cells[idx_sch])
                            m_csd = re.search(r"\d+(?:\.\d+)?", cells[idx_csd])
                            m_clip = re.search(r"\d+(?:\.\d+)?", cells[idx_clip])
                            if m_sch and m_csd and m_clip:
                                v_sch = float(m_sch.group(0))
                                v_csd = float(m_csd.group(0))
                                v_clip = float(m_clip.group(0))
                                calc = math.sqrt(v_csd * v_clip)
                                if abs(calc - v_sch) > 0.05:
                                    inconsistencies.append(
                                        f"{rel[p]} 行「{cells[0]}」: SCH={v_sch}，代入公式计算为 {calc:.3f}（差值 {abs(calc - v_sch):.3f}）"
                                    )
                                    row_fail += 1
                                else:
                                    row_ok += 1
                    results.append(f"SCH 表 ({rel[p]}): {row_ok} 行自洽，{row_fail} 行不符")

    return results, inconsistencies


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("root", help="LaTeX 根目录")
    ap.add_argument("--terms", default="", help="可选的项目词表 JSON 路径")
    ap.add_argument("-o", "--out", default="", help="输出 Markdown 报告路径")
    ap.add_argument("--log", default="", help="编译日志路径（检查 overfull/undefined）")
    args = ap.parse_args()

    root = Path(args.root)
    terms = load_terms(args.terms, root=root)
    master_file, ordered_files, unincluded_files = get_tex_structure(root)
    files = ordered_files + unincluded_files

    # texts 保存剥离注释后的纯代码，保留行号
    raw_texts = {p: p.read_text(encoding="utf-8", errors="ignore") for p in files}
    texts = {p: strip_comments(raw_texts[p]) for p in files}
    rel = {p: p.relative_to(root).as_posix() for p in files}

    out = []
    W = out.append
    W(f"# 机械检查报告\n\n源码：`{root}`\n\n发现 {len(files)} 个 .tex 文件（主干包含 {len(ordered_files)} 个，孤立 {len(unincluded_files)} 个）。")
    if not args.terms:
        W("\n> 未提供 `--terms`，项目特有代号与英文术语使用默认规则，建议配合项目 `terms.json` 拓展。")

    # ==================== L0 结构与致命项 ====================
    W("\n## 一、L0 结构与硬伤项\n")

    # 1. 盲审递刀与过度自贬
    self_dep_rx = merge_rx(SELF_DEPRECATION_DEFAULT, terms.get("self_deprecate"))
    bad_self_dep = []
    for p in files:
        if "thanks" in p.stem.lower():
            continue
        t = texts[p]
        for pos, s in all_hits(self_dep_rx, t):
            start = max(0, pos - 20)
            end = min(len(t), pos + len(s) + 35)
            snippet = t[start:end].replace("\n", " ").strip()
            bad_self_dep.append((rel[p], line_of(t, pos), s, snippet))
    W(f"- 盲审递刀与过度自贬：**{len(bad_self_dep)}** 处（直陈缺陷/缺少核心实验/尚未验证，需改为正面适用边界界定）")
    for r, ln, s, snip in bad_self_dep[:10]:
        W(f"  - {r}:{ln} 「{s}」→ `{snip}`")

    # 2. 方法章主体归属缺失（仅在第 3 章及以后的方法与核心分析章检查）
    bad_attr = []
    for p in files:
        nums = re.findall(r"\d+", p.stem)
        ch_num = int(nums[0]) if nums else 0
        if "chapter" in p.stem.lower() and ch_num >= 3:
            t = texts[p]
            for pos, s in all_hits(SUBJECT_ATTR_DEFAULT, t):
                start = max(0, pos - 15)
                end = min(len(t), pos + len(s) + 25)
                snip = t[start:end].replace("\n", " ").strip()
                bad_attr.append((rel[p], line_of(t, pos), s, snip))
    W(f"- 方法章主体归属缺失：**{len(bad_attr)}** 处（将自己工作写成外部复现或主体剥离）")
    for r, ln, s, snip in bad_attr[:8]:
        W(f"  - {r}:{ln} 「{s}」→ `{snip}`")

    # 3. 浮动体乱序（图、表、算法按前缀分别独立检查有序性）
    bad_float_order = []
    for p in files:
        t = texts[p]
        for kind in ("fig", "tab", "alg"):
            prefix = kind + ":"
            defs = [lab for lab in re.findall(r"\\label\{((?:fig|tab|alg):[^}]+)\}", t) if lab.startswith(prefix)]
            idx = {lab: i for i, lab in enumerate(defs)}
            first = {}
            for m in re.finditer(r"\\ref\{((?:fig|tab|alg):[^}]+)\}", t):
                lab = m.group(1)
                if lab.startswith(prefix):
                    first.setdefault(lab, m.start())
            prev = -1
            for lab, pos in sorted(first.items(), key=lambda kv: kv[1]):
                if lab in idx and idx[lab] < prev:
                    bad_float_order.append((rel[p], line_of(t, pos), lab))
                prev = max(prev, idx.get(lab, prev))
    W(f"- 浮动体引用乱序：**{len(bad_float_order)}** 处（插图/表格/算法各自分立有序）")
    for r, ln, lab in bad_float_order[:10]:
        W(f"  - {r}:{ln} `{lab}`")

    # 4. 指代未带 \ref 且周围无紧邻浮动体（排除特征图/计算图/散列表等学科专有数据结构）
    ghost = []
    ghost_rx = r"((?<!散列|哈希|符号)表中|上表|下表|(?<!特征|计算|网络|因果|关系|拓扑)图中|上图|下图|见表|见图)"
    for p in files:
        t = texts[p]
        for m in re.finditer(ghost_rx, t):
            win = t[max(0, m.start() - 400): min(len(t), m.start() + 400)]
            # 若窗口内包含 \ref 或紧邻各类表格/插图环境，视为正常就近指代
            if (r"\ref{" in win or
                r"\begin{table" in win or
                r"\begin{figure" in win or
                r"\begin{tabular" in win or
                r"\begin{sideway" in win or
                r"\begin{wrapfigure" in win or
                r"\begin{algorithm" in win):
                continue
            ghost.append((rel[p], line_of(t, m.start()), m.group(0)))
    W(f"- 「表中/图中」脱离浮动体悬空指代：**{len(ghost)}** 处（前后400字内无 `\\ref` 且无浮动体环境）")
    for r, ln, w in ghost[:10]:
        W(f"  - {r}:{ln} 「{w}」")

    # 5. 未引用浮动体与文献
    all_text = "\n".join(texts[p] for p in ordered_files)
    labels = set(re.findall(r"\\label\{((?:fig|tab|alg):[^}]+)\}", all_text))
    refs = set(re.findall(r"\\ref\{((?:fig|tab|alg):[^}]+)\}", all_text))
    uncited_floats = labels - refs
    W(f"- 未被引用的浮动体：**{len(uncited_floats)}** 个" + (f" → {sorted(uncited_floats)[:6]}" if uncited_floats else ""))

    # 修正 bib 过滤，使用 relative_to 避免父路径包含 build/archive 时误判
    bibs = [
        b for b in sorted(root.rglob("*.bib"))
        if not any(part in SKIP_DIRS for part in b.relative_to(root).parts[:-1])
    ]
    if bibs:
        keys = set()
        for b in bibs:
            raw_bib = strip_comments(b.read_text(encoding="utf-8", errors="ignore"))
            # 排除 @comment, @string, @preamble
            keys |= set(re.findall(r"@(?!(?:comment|string|preamble)\b)\w+\s*\{\s*([^,\s]+)\s*,", raw_bib, re.I))
        cited = set()
        # 兼容各类 cite 命令：\cite, \upcite, \citep, \citet, \nocite 等
        for k in re.findall(r"\\(?:up?cite|citep|citet|nocite|citeauthor|citeyear)\{([^}]+)\}", all_text):
            cited |= {x.strip() for x in k.split(",")}
        uncited_bibs = keys - cited
        W(f"- 参考文献：{len(keys)} 条，正文引用 {len(cited)} 条，未引用 **{len(uncited_bibs)}** 条"
          + (f" → {sorted(uncited_bibs)[:5]}" if uncited_bibs else ""))
    else:
        W(f"- 参考文献：未在 `{root}` 下找到 .bib 文件（跳过未引用文献检查）")

    # 6. 复合指标公式逐行验算（自洽性核算）
    tbl_summaries, tbl_incons = verify_composite_tables(ordered_files, texts, rel)
    W(f"- 复合指标公式逐行验算：**{len(tbl_incons)}** 处不自洽"
      + (f"（已核算 {len(tbl_summaries)} 张复合指标表，全部符合定义公式）" if not tbl_incons else ""))
    for inc in tbl_incons[:6]:
        W(f"  - ⚠ {inc}")

    # 7. 跨协议尺度混用与随意换算
    scale_hits = []
    for p in files:
        t = texts[p]
        for pos, s in all_hits(SCALE_CONVERT_DEFAULT, t):
            pre = t[max(0, pos - 15): pos]
            if re.search(r"(?:不|不可|不能|不得|严禁|无需|不应|禁止|无须)", pre):
                continue
            start = max(0, pos - 15)
            end = min(len(t), pos + len(s) + 25)
            snip = t[start:end].replace("\n", " ").strip()
            scale_hits.append((rel[p], line_of(t, pos), s, snip))
    W(f"- 跨协议尺度随意换算：**{len(scale_hits)}** 处（不同协议指标相除/换算/统一打分）")
    for r, ln, s, snip in scale_hits[:6]:
        W(f"  - {r}:{ln} 「{s}」→ `{snip}`")

    # 8. math mode 单字母变量未加 $
    bare_math = []
    for p in files:
        t = texts[p]
        spans = non_prose_spans(t)
        for m in re.finditer(r"(?<![\\$])\b([A-Za-z]{1,2})\s*=\s*(\d+(?:\.\d+)?)", t):
            if in_spans(spans, m.start()):
                continue
            bare_math.append((rel[p], line_of(t, m.start()), m.group(0)))
    W(f"- 数学变量漏加 `$`：**{len(bare_math)}** 处 {bare_math[:4]}")

    # 9. 缩写首现未定义（区分作者未定义缩写 vs 已正规引用的外部文献基线）
    body_files = [p for p in ordered_files if not any(x in p.stem.lower() for x in ["denotation", "pub", "thanks", "title", "cover"])]
    deno_file = next((p for p in files if "denotation" in p.stem.lower()), None)
    deno_text = deno_file.read_text(encoding="utf-8", errors="ignore") if deno_file else ""

    body_clean_chunks = []
    body_raw_chunks = []
    for p in body_files:
        t = texts[p]
        spans = non_prose_spans(t)
        chars = list(t)
        for a, b in spans:
            for i in range(a, min(b, len(chars))):
                chars[i] = " "
        masked = "".join(chars)
        # 屏蔽 LaTeX 命令与键名，防止宏包名或模版名泄露为正文缩写
        masked = re.sub(r"\\(?:documentclass|usepackage)(?:\[[^\]]*\])?\{[^}]*\}", " ", masked)
        masked = re.sub(r"\\(?:cite|upcite|label|ref|pageref|input|include|bibliography|bibliographystyle)\{[^}]*\}", " ", masked)
        masked = re.sub(r"\\(?:begin|end)\{[^}]*\}", " ", masked)
        body_clean_chunks.append(masked)
        body_raw_chunks.append(t)
    all_body_clean = "\n".join(body_clean_chunks)
    all_body_raw = "\n".join(body_raw_chunks)

    undef = []
    cited_ext = []
    seen_ab = set()
    for m in re.finditer(r"(?<![A-Za-z])[A-Z]{2,6}(?![A-Za-z])", all_body_clean):
        ab = m.group(0)
        if ab in ACR_STOP or ab in seen_ab:
            continue
        seen_ab.add(ab)
        # 若在符号表中已有收录（无论是正文环境还是 \mathrm 等数学环境），不报错
        if deno_text and re.search(r"(?:\\mathrm\{|\\operatorname\{|(?<![A-Za-z]))" + re.escape(ab) + r"(?:\}|(?![A-Za-z]))", deno_text):
            continue
        m_first = re.search(r"(?<![A-Za-z])" + re.escape(ab) + r"(?![A-Za-z])", all_body_clean)
        if not m_first:
            continue
        first = m_first.start()
        win = all_body_clean[max(0, first - 300): first + 200]
        # 兼容正文双向定义：全称（缩写）与 缩写（全称），以及表示、定义为、即等引导词
        rx_def = r"(?:（[^）]*{0}[^）]*）|{0}\s*（[^）]+）|\([^)]*{0}[^)]*\)|{0}\s*\([^)]+\)|全称|定义为|表示|衡量|即|简记|记为|简称)".format(re.escape(ab))
        if re.search(rx_def, win):
            continue

        # 检查原始上下文后方是否紧随文献引用（如 \upcite 或 等工作/等人）
        mf_raw = re.search(r"(?<![A-Za-z])" + re.escape(ab) + r"(?![A-Za-z])", all_body_raw)
        raw_after = all_body_raw[mf_raw.end(): min(len(all_body_raw), mf_raw.end() + 60)] if mf_raw else ""
        if re.search(r"\\up?cite|\b等(?:人|工作|方法)\b", raw_after):
            cited_ext.append(ab)
        else:
            undef.append(ab)

    uniq_undef = sorted(set(undef))
    uniq_cited = sorted(set(cited_ext))
    W(f"- 疑似首现未定义的缩写/指标：**{len(uniq_undef)}** 个" + (f" → `{uniq_undef[:10]}`" if uniq_undef else ""))
    if uniq_cited:
        W(f"- 外部文献/基线方法名称（正文紧邻学术引文，属正当引用）：**{len(uniq_cited)}** 个 → `{uniq_cited[:8]}`")
    if uniq_undef:
        W("  首现上下文（核对全称与原文是否一致，缩写对、全称错比缺定义更危险）：")
        for ab in uniq_undef[:8]:
            mf = re.search(r"(?<![A-Za-z])" + re.escape(ab) + r"(?![A-Za-z])", all_body_clean)
            if not mf:
                continue
            ctx = all_body_clean[max(0, mf.start() - 45): mf.start() + 70].replace("\n", " ")
            W(f"  - `{ab}` … {ctx} …")

    # ==================== L1 出戏与缝合项 ====================
    W("\n## 二、L1 出戏与机翻缝合项\n")

    # 1. 拼稿痕迹与小论文残留（补充材料、两篇、篇幅限制等）
    composite_rx = merge_rx(COMPOSITE_DEFAULT, terms.get("composite"))
    composite_hits = []
    for p in files:
        t = texts[p]
        for pos, s in all_hits(composite_rx, t):
            start = max(0, pos - 15)
            end = min(len(t), pos + len(s) + 25)
            snip = t[start:end].replace("\n", " ").strip()
            composite_hits.append((rel[p], line_of(t, pos), s, snip))
    W(f"- 拼稿痕迹与小论文残留：**{len(composite_hits)}** 处（多论文拼接/补充材料/篇幅限制/合订）")
    for r, ln, s, snip in composite_hits[:8]:
        W(f"  - {r}:{ln} 「{s}」→ `{snip}`")

    # 2. 第一人称出戏（“我们”）
    first_person_rx = merge_rx(FIRST_PERSON_DEFAULT, terms.get("first_person"))
    fp_hits = []
    for p in files:
        if "thanks" in p.stem.lower():
            continue
        t = texts[p]
        for pos, s in all_hits(first_person_rx, t):
            start = max(0, pos - 15)
            end = min(len(t), pos + len(s) + 25)
            snip = t[start:end].replace("\n", " ").strip()
            fp_hits.append((rel[p], line_of(t, pos), s, snip))
    W(f"- 第一人称复数出戏（“我们”）：**{len(fp_hits)}** 处（学位论文属独立成果，除致谢外应改为“本文/实测表明”）")
    for r, ln, s, snip in fp_hits[:8]:
        W(f"  - {r}:{ln} 「{s}」→ `{snip}`")

    # 3. 机翻跳戏与非学术口语
    colloquial_rx = merge_rx(COLLOQUIAL_DEFAULT, terms.get("colloquial"))
    colloquial_hits = []
    for p in files:
        t = texts[p]
        for pos, s in all_hits(colloquial_rx, t):
            start = max(0, pos - 15)
            end = min(len(t), pos + len(s) + 25)
            snip = t[start:end].replace("\n", " ").strip()
            colloquial_hits.append((rel[p], line_of(t, pos), s, snip))
    W(f"- 机翻跳戏与出格口语：**{len(colloquial_hits)}** 处（轻佻词汇/指代不明/跨环境泄漏）")
    for r, ln, s, snip in colloquial_hits[:8]:
        W(f"  - {r}:{ln} 「{s}」→ `{snip}`")

    # 4. Markdown 残留与占位符
    md_hits = []
    for p in files:
        t = texts[p]
        for pos, s in all_hits(MARKDOWN_RESIDUE_RX, t):
            md_hits.append((rel[p], line_of(t, pos), s.strip()))
    W(f"- Markdown 标记或 TODO 占位残留：**{len(md_hits)}** 处")
    for r, ln, s in md_hits[:6]:
        W(f"  - {r}:{ln} `{s}`")

    # 5. 元写作与辩护腔
    meta_rx = merge_rx(META_DEFAULT, terms.get("meta"))
    meta_hits = []
    for p in files:
        t = texts[p]
        for pos, s in all_hits(meta_rx, t):
            meta_hits.append((rel[p], line_of(t, pos), s))
    W(f"- 元写作与辩护腔：**{len(meta_hits)}** 处")
    for r, ln, s in meta_hits[:6]:
        W(f"  - {r}:{ln} 「{s}」")

    # 6. 翻译腔数学残留（如 1/2.5、分母带小数）
    frac_math_hits = []
    for p in files:
        t = texts[p]
        for pos, s in all_hits(r"1/\d+\.\d+|/\s*\d+\.\d+\s*倍", t):
            frac_math_hits.append((rel[p], line_of(t, pos), s))
    W(f"- 翻译腔数学残留（如分母带小数）：**{len(frac_math_hits)}** 处")
    for r, ln, s in frac_math_hits[:6]:
        W(f"  - {r}:{ln} 「{s}」")

    # 7. 封面长标题断行与单行页眉兼顾
    title_issues = []
    if master_file and master_file.exists():
        m_txt = raw_texts[master_file]
        m_title = re.search(r"\\title\s*(?:\[([^\]]*)\])?\s*\{([^}]*)\}", m_txt)
        if m_title:
            opt, body = m_title.group(1), m_title.group(2)
            if "\\\\" in body and not opt:
                title_issues.append("主文件 \\title 包含断行 \\\\ 但未提供可选参数单行短标题（易导致页眉/声明页被劈开断行）")
    W(f"- 封面长标题断行排版合规：**{len(title_issues)}** 处问题"
      + ("（已使用双参数解耦封面换行与单行页眉）" if not title_issues else ""))
    for ti in title_issues:
        W(f"  - ⚠ {ti}")

    # 8. 模板残留与未引用的孤立 .tex 文件
    W(f"- 未被主文件包含的孤立 .tex 文件：**{len(unincluded_files)}** 个"
      + (f" → `{[u.relative_to(root).as_posix() for u in unincluded_files]}`" if unincluded_files else ""))

    # 9. 项目词表专有字段（内部代号、裸用英文）
    for name, key in (("内部代号", "codename"), ("裸用英文术语", "bare_en")):
        rx = terms.get(key)
        if not rx:
            continue
        rows, skipped = [], 0
        for p in files:
            t = texts[p]
            for pos, s in all_hits(rx, t):
                ls = t.rfind("\n", 0, pos) + 1
                le = t.find("\n", pos)
                line = t[ls: le if le > 0 else len(t)]
                pre = t[max(0, pos - 14): pos]
                # 已带中文括注（…（英文）…）视为合规
                if "（" in pre or "(" in pre:
                    skipped += 1
                    continue
                # 数据集编号语境（编号 sty00 至 sty39 / $c_{00}$）视为合规
                if re.search(r"编号|至\s*[A-Za-z]*\d{2}|_\{\d+\}", line):
                    skipped += 1
                    continue
                rows.append((rel[p], line_of(t, pos), s))
        W(f"- {name}（词表）：**{len(rows)}** 处"
          + (f"（另有 {skipped} 处已带中文括注或属数据集编号，未计入）" if skipped else ""))
        for r, ln, s in rows[:6]:
            W(f"  - {r}:{ln} 「{s}」")

    # ==================== L2 文风与 AI 口癖 ====================
    W("\n## 三、L2 文风与 AI 口癖\n")

    cnt = {w: all_text.count(w) for w in VERBS}
    total_verbs = sum(cnt.values()) or 1
    W(f"- 动词分布：{cnt}")
    shuo_ratio = cnt["说明"] / total_verbs
    W(f"- 「说明」占比 **{shuo_ratio:.0%}**" + (" → 偏高（>50%）" if shuo_ratio > 0.5 else " → 正常（<50%）"))

    cjk_count = len(re.findall(r"[\u4e00-\u9fff]", all_text))
    neg_count = len(re.findall(NEG_RX, all_text))
    neg_density = neg_count / max(cjk_count, 1) * 1000
    W(f"- 否定转折：{neg_count} 次 / {cjk_count} 汉字（每千字 **{neg_density:.1f}** 次）"
      + (" → 偏密（>3.0/千字）" if neg_density > 3.0 else ""))

    # AI 破折号密度（包含全角破折号与 LaTeX 三连字 ---）
    dash_count = len(re.findall(r"——|(?<!-)(?:---)(?!-)", all_text))
    dash_density = dash_count / max(cjk_count, 1) * 1000
    W(f"- 破折号「——/---」：{dash_count} 次（每千字 **{dash_density:.2f}** 次）"
      + (" → 堆叠过密（>1.5/千字），具明显 AI 补充说明痕迹" if dash_density > 1.5 else ""))

    # 特征连词与空泛升华（逐文件定位）
    cliche_hits = []
    for p in files:
        t = texts[p]
        for pos, s in all_hits(CLICHE_RX, t):
            start = max(0, pos - 15)
            end = min(len(t), pos + len(s) + 25)
            snip = t[start:end].replace("\n", " ").strip()
            cliche_hits.append((rel[p], line_of(t, pos), s, snip))
    W(f"- 特征连词与空泛升华：**{len(cliche_hits)}** 处")
    for r, ln, s, snip in cliche_hits[:8]:
        W(f"  - {r}:{ln} 「{s}」→ `{snip}`")

    # AI 宏大时空套话（逐文件定位）
    ai_cliche_rx = merge_rx(AI_CLICHE_DEFAULT, terms.get("ai_cliche"))
    ai_cliches = []
    for p in files:
        t = texts[p]
        for pos, s in all_hits(ai_cliche_rx, t):
            start = max(0, pos - 15)
            end = min(len(t), pos + len(s) + 25)
            snip = t[start:end].replace("\n", " ").strip()
            ai_cliches.append((rel[p], line_of(t, pos), s, snip))
    W(f"- AI 时空套话与空泛修饰：**{len(ai_cliches)}** 处")
    for r, ln, s, snip in ai_cliches[:8]:
        W(f"  - {r}:{ln} 「{s}」→ `{snip}`")

    # 小节段末自卫（大小写不敏感匹配各类 BiSection / Section / Subsection）
    selfdef = 0
    for p in files:
        t = texts[p]
        marks = [m.end() for m in re.finditer(r"\\(?:Bi)?(?:sub)*section\{", t, re.I)]
        for i, s in enumerate(marks):
            seg = t[s: marks[i + 1] if i + 1 < len(marks) else len(t)].strip()
            if not seg:
                continue
            tails = [x for x in seg.split("。") if x.strip()]
            if tails and re.search(SELF_DEF, tails[-1]):
                selfdef += 1
    W(f"- 小节以否定/限定收尾：约 **{selfdef}** 处（需人工核对是否连续否定收束）")

    # ==================== L3 规范与术语一致性 ====================
    W("\n## 四、L3 规范与术语一致性\n")

    seen_pairs = set()
    term_pairs = []
    for pair in list(DEFAULT_TERM_PAIRS) + (terms.get("term_pairs") or []):
        key = (pair[0], pair[1])
        if key not in seen_pairs:
            seen_pairs.add(key)
            term_pairs.append(pair)

    chapter_files = [p for p in files if "chapter" in p.stem.lower()]
    term_conflicts = []
    for pair in term_pairs:
        name_a, name_b = pair[0], pair[1]
        cnt_a_total = 0
        cnt_b_total = 0
        dist = []
        for cf in chapter_files:
            t = texts[cf]
            # 排除构词后缀（「提示语」在「提示语义」中不算独立术语）
            ca = len(re.findall(name_a + r"(?!义|性|化|学)", t))
            cb = len(re.findall(name_b + r"(?!义|性|化|学)", t))
            cnt_a_total += ca
            cnt_b_total += cb
            if ca > 0 or cb > 0:
                dist.append(f"{cf.stem}({ca}:{cb})")
        if cnt_a_total > 0 and cnt_b_total > 0:
            clean_b = re.sub(r"\(\?[^)]*\)", "", name_b)
            term_conflicts.append((name_a, cnt_a_total, clean_b, cnt_b_total, ", ".join(dist)))

    W(f"- 核心术语跨章译名分裂：**{len(term_conflicts)}** 组（由多篇小论文合成时最易发生）")
    for na, ca, nb, cb, dist in term_conflicts:
        W(f"  - 「{na}」({ca}次) vs 「{nb}」({cb}次) → 章节分布: [{dist}]")

    # 封面与答辩必填预留字段待填提示
    empty_front = []
    if master_file and master_file.exists():
        m_txt = raw_texts[master_file]
        for cmd in ["defenddate", "englishadvisor", "shijian", "profone", "where"]:
            m = re.search(r"\\" + cmd + r"\{([^}]*)\}", m_txt)
            if m and not m.group(1).strip():
                empty_front.append(cmd)
    W(f"- 封面与答辩信息预留字段待填：**{len(empty_front)}** 项"
      + (f" → `\\{empty_front}`（需作者按学院答辩通知填齐）" if empty_front else "（已填齐）"))

    # ==================== 编译日志核验 ====================
    W("\n## 五、编译日志核验\n")
    log_file = None
    if args.log:
        p_log = Path(args.log)
        if p_log.exists():
            log_file = p_log
        elif (root / args.log).exists():
            log_file = root / args.log

    if not log_file:
        # 自动搜索常见编译日志路径（按最后修改时间取最新）
        search_dirs = [root, root / "build", root / "out" / "build", root.parent / "build", root.parent / "out" / "build"]
        for d in search_dirs:
            if d.is_dir():
                logs = sorted(d.glob("*.log"), key=lambda x: x.stat().st_mtime, reverse=True)
                for lg in logs:
                    if any(x in lg.name.lower() for x in ["main", "thesis"]):
                        log_file = lg
                        break
                if log_file:
                    break
                if logs:
                    log_file = logs[0]
                    break

    if log_file and log_file.exists():
        log = log_file.read_text(encoding="utf-8", errors="ignore")
        W(f"（核验日志：`{log_file.resolve()}`）\n")
        for label, rx in (
            ("Overfull hbox/vbox", r"Overfull "),
            ("未定义引用 (reference undefined)", r"reference.*undefined"),
            ("未定义引文 (Citation undefined)", r"Citation.*undefined"),
            ("字体替换警告 (Font shape undefined)", r"Font shape.*undefined"),
        ):
            hits_count = len(re.findall(rx, log))
            W(f"- {label}: **{hits_count}**")
    else:
        W("- 未提供 `--log` 且未在常用目录自动找到编译日志")

    W("\n---\n> 说明：机械项只覆盖结构、密度与特征词。主体归属、语义逻辑、跨章指代、指标定义，请对照 SKILL.md 的「每章八问」人工逐章通读核验。")

    md = "\n".join(out)
    if args.out:
        Path(args.out).write_text(md, encoding="utf-8")
        print(f"written: {args.out}")
    else:
        print(md)
    return 0


if __name__ == "__main__":
    sys.exit(main())