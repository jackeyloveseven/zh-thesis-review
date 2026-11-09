#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit tests for audit_thesis.py (zh-thesis-review)."""

import json
import math
import tempfile
import unittest
from pathlib import Path

# Add scripts directory to sys.path
import sys
scripts_dir = Path(__file__).resolve().parent.parent / "scripts"
if str(scripts_dir) not in sys.path:
    sys.path.insert(0, str(scripts_dir))

import audit_thesis as audit


class TestAuditThesis(unittest.TestCase):

    def test_strip_comments(self):
        latex = (
            "Line 1 % comment\n"
            "Line 2 \\% not comment\n"
            "Line 3 \\\\% comment after double backslash\n"
            "Line 4"
        )
        cleaned = audit.strip_comments(latex)
        lines = cleaned.split("\n")
        self.assertEqual(len(lines), 4)
        self.assertEqual(lines[0].strip(), "Line 1")
        self.assertIn("\\%", lines[1])
        self.assertEqual(lines[2].strip(), "Line 3 \\\\")
        self.assertEqual(lines[3].strip(), "Line 4")

    def test_safe_eval_expr(self):
        # Basic arithmetic
        res = audit.safe_eval_expr("(1 + a) * (1 + b)", {"a": 0.483, "b": 15.877})
        self.assertAlmostEqual(res, 25.028591, places=5)

        # Functions: sqrt, abs
        res_sqrt = audit.safe_eval_expr("sqrt(x * y)", {"x": 0.64, "y": 0.81})
        self.assertAlmostEqual(res_sqrt, 0.72, places=5)

        # F1 score formula
        res_f1 = audit.safe_eval_expr("2 * p * r / (p + r)", {"p": 0.8, "r": 0.6})
        self.assertAlmostEqual(res_f1, 0.685714, places=5)

        # Unsafe node rejection
        with self.assertRaises(ValueError):
            audit.safe_eval_expr("__import__('os').system('echo hi')", {})

    def test_verify_composite_tables(self):
        # 1. Self-consistent table
        tabular_ok = r"""
\begin{tabular}{l c c c}
\toprule
方法 & CSD$\uparrow$ & CLIP-I$\uparrow$ & SCH$\uparrow$ \\
\midrule
基线A & 0.640 & 0.810 & 0.720 \\
基线B & 0.500 & 0.720 & 0.600 \\
\bottomrule
\end{tabular}
"""
        dummy_file = Path("dummy.tex")
        results, incons = audit.verify_composite_tables([dummy_file], {dummy_file: tabular_ok}, {dummy_file: "dummy.tex"})
        self.assertEqual(len(incons), 0)
        self.assertTrue(any("SCH 表" in r for r in results))

        # 2. Inconsistent table
        tabular_bad = r"""
\begin{tabular}{l c c c}
\toprule
方法 & CSD$\uparrow$ & CLIP-I$\uparrow$ & SCH$\uparrow$ \\
\midrule
基线A & 0.640 & 0.810 & 0.999 \\
\bottomrule
\end{tabular}
"""
        results_bad, incons_bad = audit.verify_composite_tables([dummy_file], {dummy_file: tabular_bad}, {dummy_file: "dummy.tex"})
        self.assertEqual(len(incons_bad), 1)
        self.assertIn("SCH=0.999", incons_bad[0])

    def test_custom_composite_metrics(self):
        tabular_f1 = r"""
\begin{tabular}{l c c c}
\toprule
Model & Precision & Recall & F1 \\
\midrule
BERT & 0.800 & 0.600 & 0.686 \\
\bottomrule
\end{tabular}
"""
        custom_rule = [{
            "name": "F1",
            "header_match": ["F1"],
            "components": ["Precision", "Recall"],
            "formula": "2 * Precision * Recall / (Precision + Recall)",
            "tolerance": 0.02
        }]
        dummy_file = Path("dummy.tex")
        results, incons = audit.verify_composite_tables(
            [dummy_file], {dummy_file: tabular_f1}, {dummy_file: "dummy.tex"}, composite_rules=custom_rule
        )
        self.assertEqual(len(incons), 0)
        self.assertTrue(any("F1 表" in r for r in results))

    def test_ghost_float_exclusions(self):
        text_with_compound = "在热力图中可以发现模式，在混淆矩阵表中列出分类统计，在反向计算图中梯度流顺畅。"
        exclude_prefixes = (
            "散列", "哈希", "符号", "对照", "统计", "记录", "邻接", "状态", "路由", "查找",
            "配置", "索引", "跳转", "真值", "特征", "计算", "网络", "因果", "关系", "拓扑",
            "热力", "散点", "分布", "折线", "雷达", "混淆", "流程", "时序", "示意", "架构",
            "结构", "数据流", "甘特", "框", "柱状", "箱线", "点云", "矩阵"
        )
        hits = []
        for m in audit.re.finditer(r"(?:表中|上表|下表|图中|上图|下图|见表|见图)", text_with_compound):
            pre = text_with_compound[max(0, m.start() - 6): m.start()]
            if any(pre.endswith(ex) for ex in exclude_prefixes):
                continue
            hits.append(m.group(0))
        self.assertEqual(hits, [])

        # Pure ghost reference without nearby \ref or environment
        text_ghost = "实验数据如表中所示，显示出了显著的增益。"
        hits_ghost = []
        for m in audit.re.finditer(r"(?:表中|上表|下表|图中|上图|下图|见表|见图)", text_ghost):
            pre = text_ghost[max(0, m.start() - 6): m.start()]
            if any(pre.endswith(ex) for ex in exclude_prefixes):
                continue
            hits_ghost.append(m.group(0))
        self.assertEqual(hits_ghost, ["表中"])

    def test_float_order_and_cref(self):
        # In-order figures referenced with \cref comma separation
        text_ordered = (
            "\\begin{figure}\\label{fig:arch}\\end{figure}\n"
            "\\begin{figure}\\label{fig:loss}\\end{figure}\n"
            "正文引用 \\cref{fig:arch,fig:loss}。"
        )
        defs = [lab for lab in audit.re.findall(r"\\label\{((?:fig|tab|alg):[^}]+)\}", text_ordered) if lab.startswith("fig:")]
        idx = {lab: i for i, lab in enumerate(defs)}
        first = {}
        for m in audit.re.finditer(r"\\(?:ref|cref|Cref|autoref|eqref|pageref)\{([^}]+)\}", text_ordered):
            for lab in [x.strip() for x in m.group(1).split(",")]:
                if lab.startswith("fig:"):
                    first.setdefault(lab, m.start())
        prev = -1
        bad_order = []
        for lab, pos in sorted(first.items(), key=lambda kv: kv[1]):
            if lab in idx and idx[lab] < prev:
                bad_order.append(lab)
            prev = max(prev, idx.get(lab, prev))
        self.assertEqual(bad_order, [])

        # Out-of-order figure references
        text_disorder = (
            "\\begin{figure}\\label{fig:first}\\end{figure}\n"
            "\\begin{figure}\\label{fig:second}\\end{figure}\n"
            "先引 \\ref{fig:second}，后引 \\ref{fig:first}。"
        )
        defs2 = [lab for lab in audit.re.findall(r"\\label\{((?:fig|tab|alg):[^}]+)\}", text_disorder) if lab.startswith("fig:")]
        idx2 = {lab: i for i, lab in enumerate(defs2)}
        first2 = {}
        for m in audit.re.finditer(r"\\(?:ref|cref|Cref|autoref|eqref|pageref)\{([^}]+)\}", text_disorder):
            for lab in [x.strip() for x in m.group(1).split(",")]:
                if lab.startswith("fig:"):
                    first2.setdefault(lab, m.start())
        prev2 = -1
        bad_order2 = []
        for lab, pos in sorted(first2.items(), key=lambda kv: kv[1]):
            if lab in idx2 and idx2[lab] < prev2:
                bad_order2.append(lab)
            prev2 = max(prev2, idx2.get(lab, prev2))
        self.assertEqual(bad_order2, ["fig:first"])

    def test_bare_math_with_latex_options(self):
        text = (
            "\\includegraphics[width=0.8\\textwidth]{figures/res.pdf}\n"
            "正文单字母变量 N = 2 漏加美元符号。"
        )
        spans = audit.non_prose_spans(text)
        clean_t = audit.re.sub(r"\[[^\]]*\]", lambda m: " " * len(m.group(0)), text)
        clean_t = audit.re.sub(r"\\[a-zA-Z]+", lambda m: " " * len(m.group(0)), clean_t)
        hits = []
        for m in audit.re.finditer(r"(?<![\\$a-zA-Z])([A-Za-z]{1,2})\s*=\s*(\d+(?:\.\d+)?)", clean_t):
            if audit.in_spans(spans, m.start()):
                continue
            hits.append(m.group(0))
        # width=0.8 should be ignored, while N = 2 should be caught
        self.assertEqual(hits, ["N = 2"])

    def test_recursive_tex_structure(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            (tmppath / "chapters").mkdir()

            master_content = (
                "\\documentclass{article}\n"
                "\\begin{document}\n"
                "\\input{chapters/ch1}\n"
                "\\end{document}\n"
            )
            (tmppath / "main.tex").write_text(master_content, encoding="utf-8")

            ch1_content = "第1章内容 \\input{chapters/sec1}"
            (tmppath / "chapters" / "ch1.tex").write_text(ch1_content, encoding="utf-8")

            sec1_content = "第1节内容"
            (tmppath / "chapters" / "sec1.tex").write_text(sec1_content, encoding="utf-8")

            orphan_content = "孤立文件未被引用"
            (tmppath / "chapters" / "orphan.tex").write_text(orphan_content, encoding="utf-8")

            master, ordered, unincluded = audit.get_tex_structure(tmppath)
            self.assertEqual(master.name, "main.tex")
            ordered_names = [p.name for p in ordered]
            self.assertEqual(ordered_names, ["main.tex", "ch1.tex", "sec1.tex"])
            unincluded_names = [p.name for p in unincluded]
            self.assertEqual(unincluded_names, ["orphan.tex"])

    def test_load_terms_and_merge(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            terms_file = tmppath / "terms.json"
            terms_data = {
                "own_methods": ["SuperModel"],
                "extra_acr_stop": ["XYZ", "ABC"],
                "term_pairs": [["算法A", "算法B"]],
                "self_deprecate": ["未进行深度测试"]
            }
            terms_file.write_text(json.dumps(terms_data), encoding="utf-8")
            loaded = audit.load_terms(str(terms_file))
            self.assertEqual(loaded["own_methods"], ["SuperModel"])
            self.assertEqual(loaded["extra_acr_stop"], {"XYZ", "ABC"})
            self.assertEqual(loaded["term_pairs"], [["算法A", "算法B"]])
            self.assertIn("未进行深度测试", loaded["self_deprecate"])

    def test_bib_citations_multiformat(self):
        bib_text = (
            "@article{vaswani2017attention,\n  author = {Vaswani},\n  title = {Attention}\n}\n"
            "@inproceedings{he2016deep,\n  author = {He},\n  title = {ResNet}\n}\n"
            "@book{knuth1984tex,\n  author = {Knuth},\n  title = {TeXbook}\n}\n"
        )
        keys = set(audit.re.findall(r"@(?!(?:comment|string|preamble)\b)\w+\s*\{\s*([^,\s]+)\s*,", bib_text, audit.re.I))
        self.assertEqual(keys, {"vaswani2017attention", "he2016deep", "knuth1984tex"})

        all_text = "如 \\cite{vaswani2017attention} 与 \\parencite{he2016deep} 所示。"
        cited = set()
        raw_cites = audit.re.findall(r"\\(?:cite|upcite|citep|citet|nocite|citeauthor|citeyear|autocite|parencite|textcite|footcite)\{([^}]+)\}", all_text)
        for k in raw_cites:
            for x in k.split(","):
                val = x.strip()
                if val:
                    cited.add(val)
        self.assertEqual(cited, {"vaswani2017attention", "he2016deep"})
        uncited = keys - cited
        self.assertEqual(uncited, {"knuth1984tex"})


if __name__ == "__main__":
    unittest.main()
