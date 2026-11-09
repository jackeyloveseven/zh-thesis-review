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
            "Line 1 % comment\r\n"
            "Line 2 \\% not comment\n"
            "Line 3 \\\\% comment after double backslash\r"
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

        # Functions: sqrt, abs, log, exp
        res_sqrt = audit.safe_eval_expr("sqrt(x * y)", {"x": 0.64, "y": 0.81})
        self.assertAlmostEqual(res_sqrt, 0.72, places=5)
        self.assertAlmostEqual(audit.safe_eval_expr("abs(-5.5)", {}), 5.5)

        # F1 score formula
        res_f1 = audit.safe_eval_expr("2 * p * r / (p + r)", {"p": 0.8, "r": 0.6})
        self.assertAlmostEqual(res_f1, 0.685714, places=5)

        # ZeroDivisionError check (division by zero should raise ZeroDivisionError)
        with self.assertRaises(ZeroDivisionError):
            audit.safe_eval_expr("1 / 0", {})

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

    def test_verify_composite_tables_negative_and_formatting(self):
        tabular_formatted = r"""
\begin{tabular}{l c c c}
\toprule
Model & \textbf{Precision} & \textbf{Recall} & \textbf{F1} \\
\midrule
BERT & \underline{0.800} & \cellcolor{gray!20}{0.600} & \textbf{0.686} \\
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
            [dummy_file], {dummy_file: tabular_formatted}, {dummy_file: "dummy.tex"}, composite_rules=custom_rule
        )
        self.assertEqual(len(incons), 0)
        self.assertTrue(any("F1 表" in r for r in results))

    def test_ghost_float_exclusions_and_detection(self):
        text_with_compound = "在热力图中可以发现模式，在混淆矩阵表中列出分类统计，在反向计算图中梯度流顺畅。"
        dummy_file = Path("dummy.tex")
        ghosts = audit.check_ghost_floats([dummy_file], {dummy_file: text_with_compound}, {dummy_file: "dummy.tex"})
        self.assertEqual(len(ghosts), 0)

        # Ghost float should NOT be suppressed by unrelated equation reference \ref{eq:1}
        text_ghost_with_eq = "根据公式 \\ref{eq:energy} 计算能量，见图中所示，曲线快速收敛。"
        ghosts_eq = audit.check_ghost_floats([dummy_file], {dummy_file: text_ghost_with_eq}, {dummy_file: "dummy.tex"})
        self.assertEqual(len(ghosts_eq), 1)
        self.assertEqual(ghosts_eq[0][2], "见图")

        # Legitimate figure reference nearby should suppress ghost alarm
        text_legit = "如图 \\ref{fig:arch} 所示，见图中所示架构。"
        ghosts_legit = audit.check_ghost_floats([dummy_file], {dummy_file: text_legit}, {dummy_file: "dummy.tex"})
        self.assertEqual(len(ghosts_legit), 0)

    def test_float_order_and_cref(self):
        # In-order figures referenced with \cref and \crefrange
        text_ordered = (
            "\\begin{figure}\\label{fig:arch}\\end{figure}\n"
            "\\begin{figure}\\label{fig:loss}\\end{figure}\n"
            "正文引用 \\cref{fig:arch,fig:loss}。"
        )
        dummy_file = Path("dummy.tex")
        bad = audit.check_float_order([dummy_file], {dummy_file: text_ordered}, {dummy_file: "dummy.tex"})
        self.assertEqual(len(bad), 0)

        # Out-of-order figure references
        text_disorder = (
            "\\begin{figure}\\label{fig:first}\\end{figure}\n"
            "\\begin{figure}\\label{fig:second}\\end{figure}\n"
            "先引 \\ref{fig:second}，后引 \\ref{fig:first}。"
        )
        bad_disorder = audit.check_float_order([dummy_file], {dummy_file: text_disorder}, {dummy_file: "dummy.tex"})
        self.assertEqual(len(bad_disorder), 1)
        self.assertEqual(bad_disorder[0][2], "fig:first")

    def test_uncited_floats_with_crefrange(self):
        text = (
            "\\begin{figure}\\label{fig:f1}\\end{figure}\n"
            "\\begin{figure}\\label{fig:f2}\\end{figure}\n"
            "正文采用宏包范围引用 \\crefrange{fig:f1}{fig:f2}。"
        )
        dummy_file = Path("dummy.tex")
        labels, refs, uncited = audit.check_uncited_floats([dummy_file], {dummy_file: text})
        self.assertEqual(uncited, set())
        self.assertEqual(refs, {"fig:f1", "fig:f2"})

    def test_bare_math_with_latex_options(self):
        text = (
            "\\includegraphics[width=0.8\\textwidth]{figures/res.pdf}\n"
            "正文单字母变量 N = 2 漏加美元符号。"
        )
        dummy_file = Path("dummy.tex")
        bare = audit.check_bare_math([dummy_file], {dummy_file: text}, {dummy_file: "dummy.tex"})
        self.assertEqual(len(bare), 1)
        self.assertEqual(bare[0][2], "N = 2")

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

    def test_tex_structure_fallback_without_master(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            (tmppath / "ch1.tex").write_text("章节内容一", encoding="utf-8")
            (tmppath / "ch2.tex").write_text("章节内容二", encoding="utf-8")

            master, ordered, unincluded = audit.get_tex_structure(tmppath)
            self.assertIsNone(master)
            self.assertEqual(len(ordered), 2)
            self.assertEqual(len(unincluded), 0)

    def test_load_terms_and_merge(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            terms_file = tmppath / "terms.json"
            terms_data = {
                "own_methods": ["SuperModel"],
                "extra_acr_stop": ["xyz", " abc "],
                "term_pairs": [["算法A", "算法B"]],
                "self_deprecate": ["未进行深度测试"]
            }
            terms_file.write_text(json.dumps(terms_data), encoding="utf-8")
            loaded = audit.load_terms(str(terms_file))
            self.assertEqual(loaded["own_methods"], ["SuperModel"])
            # extra_acr_stop normalized to uppercase and stripped
            self.assertEqual(loaded["extra_acr_stop"], {"XYZ", "ABC"})
            self.assertEqual(loaded["term_pairs"], [["算法A", "算法B"]])
            self.assertIn("未进行深度测试", loaded["self_deprecate"])

    def test_bib_citations_multiformat(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            bib_text = (
                "@article{vaswani2017attention,\n  author = {Vaswani},\n  title = {Attention}\n}\n"
                "@inproceedings{he2016deep,\n  author = {He},\n  title = {ResNet}\n}\n"
                "@book{knuth1984tex,\n  author = {Knuth},\n  title = {TeXbook}\n}\n"
            )
            (tmppath / "ref.bib").write_text(bib_text, encoding="utf-8")

            # Citation with optional argument \cite[p. 15]{...} and \parencite[see][p. 20]{...}
            all_text = "如 \\cite[p. 15]{vaswani2017attention} 与 \\parencite[see][p. 20]{he2016deep} 所示。"
            keys, cited, uncited = audit.check_bib_citations(tmppath, all_text)
            self.assertEqual(keys, {"vaswani2017attention", "he2016deep", "knuth1984tex"})
            self.assertEqual(cited, {"vaswani2017attention", "he2016deep"})
            self.assertEqual(uncited, {"knuth1984tex"})

    def test_self_deprecation_and_thanks_exclusion(self):
        text_body = "实验证明我们在高噪场景下严重不足，未能验证泛化能力。"
        text_thanks = "未能深入学习更多知识，感谢导师指导。"
        f_body = Path("chapter3.tex")
        f_thanks = Path("致谢.tex")

        hits = audit.check_self_deprecation(
            [f_body, f_thanks],
            {f_body: text_body, f_thanks: text_thanks},
            {f_body: "chapter3.tex", f_thanks: "致谢.tex"},
            audit.SELF_DEPRECATION_DEFAULT
        )
        # 致谢.tex should be excluded, while chapter3.tex should be flagged
        self.assertEqual(len(hits), 2)
        self.assertTrue(all(h[0] == "chapter3.tex" for h in hits))

    def test_first_person_check(self):
        text_ch = "本文方法展示了优越性，但我们提出了扩展方案。"
        text_ack = "感谢我们课题组同门的帮助。"
        f_ch = Path("chapter4.tex")
        f_ack = Path("acknowledgements.tex")

        hits = audit.check_first_person(
            [f_ch, f_ack],
            {f_ch: text_ch, f_ack: text_ack},
            {f_ch: "chapter4.tex", f_ack: "acknowledgements.tex"},
            audit.FIRST_PERSON_DEFAULT
        )
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0][0], "chapter4.tex")

    def test_subject_attribution_chapter_detection(self):
        text_attr = "本章介绍了该方法的实验设置。"
        # Arabic numeral, Chinese numeral, semantic stem
        f_arabic = Path("chapter3.tex")
        f_chinese = Path("第三章.tex")
        f_semantic = Path("chapters/method.tex")

        hits = audit.check_subject_attribution(
            [f_arabic, f_chinese, f_semantic],
            {f_arabic: text_attr, f_chinese: text_attr, f_semantic: text_attr},
            {f_arabic: "chapter3.tex", f_chinese: "第三章.tex", f_semantic: "chapters/method.tex"}
        )
        self.assertEqual(len(hits), 3)

    def test_frac_math_variations(self):
        text = "速度提升了 1/2.5 倍，相对比例为 3/2.5，乘法写为 ×2.5 倍。"
        f = Path("test.tex")
        hits = audit.check_frac_math([f], {f: text}, {f: "test.tex"})
        found = [h[2] for h in hits]
        self.assertTrue(any("1/2.5" in x for x in found))
        self.assertTrue(any("3/2.5" in x for x in found))
        self.assertTrue(any("×2.5 倍" in x for x in found))


if __name__ == "__main__":
    unittest.main()
