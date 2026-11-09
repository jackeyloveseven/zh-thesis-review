# zh-thesis-review · 中文学位论文出审

一个给 Claude / Cursor 等 AI 助手用的 **skill（技能包）**，用于中文学位论文（硕士 / 博士）**送审与答辩前**的硬伤排查。

它不负责把论文写漂亮，只负责找出**会被盲审专家或答辩委员当场抓住**的问题：主体归属写错、主动给评审递刀、引用了不存在的表图、跨章悬空引用、指标没定义、不同协议的数字被强行并列、拼稿留下的人称跳戏与过程泄漏、以及一眼就能看出的 AI 口癖。

## 判断标准

只有一条：

> 一个不了解你工作的评委，读到这一句会不会停下来怀疑、翻页找表，或者问「这到底是谁做的」「学生自己都承认没做完，怎么能通过」。

## 分级

| 级别 | 含义 |
|---|---|
| **L0 致命** | 导致误判、无法评阅，或直接给盲审递刀 |
| **L1 硬伤** | 评委大概率会追问，答不上来就扣分 |
| **L2 观感** | 不影响结论，但显得不专业 |
| **L3 格式** | 规范与一致性问题 |

完整判定表见 [`references/checks.md`](references/checks.md)，常见误报与豁免情形见 [`references/false-positives.md`](references/false-positives.md)。

## 覆盖的检查面

- **主体归属**：方法章读起来像在综述别人的工作
- **盲审递刀**：贡献节、小结、结论里主动写「未开展用户研究」「缺少基线」「尚未验证」
- **幽灵表图**：正文引用了本节并不存在的浮动体
- **跨章悬空引用**：「表中」「上表」指向别的章节
- **指标未定义**：缩写首次出现没有全称、单位、尺度、方向
- **数字与事实库不一致**：正文与主表、与登记值不符
- **尺度混用**：百分制与小数制混写，或为「统一」而除常数
- **拼稿痕迹**：多篇英文小论文合成一本时的第一人称残留、机翻腔、环境泄漏
- **AI 口癖与自卫套话**：「值得注意的是」「综上所述」滥用，以及防御性对冲
- **符号表与格式**：符号未登记、术语前后不一致

## 用法

把 `SKILL.md`、`references/`、`scripts/` 放进你的 AI 工具的 skills 目录（例如 `~/.claude/skills/zh-thesis-review/`，或 DSH 的 `~/.dsh/skills/zh-thesis-review/`），然后对助手说：

- 「论文审一下，看看哪里会被评委抓」
- 「有没有 AI 味」
- 「检查有没有故意说自己不好的地方」
- 「送盲审前过一遍硬伤」

## 附带脚本

`scripts/audit_thesis.py` 做机械统计，覆盖人手容易漏的部分：

```bash
python scripts/audit_thesis.py <论文源码目录> [--terms terms.json] [--log build/main.log]
```

自动进行 L0--L3 四级机械检查（浮动体乱序、幽灵表图、首现未定义缩写、盲审自贬递刀、小论文合订与机翻残留、第一人称复数、AI 时空套话与破折号密度、术语跨章分裂、编译日志核验等），为人工逐章深度审读扫清硬伤。

## 配套文件与规范

- [`SKILL.md`](SKILL.md)：核心技能规范与「每章八问」审读指引。
- [`references/checks.md`](references/checks.md)：L0--L3 逐级判定标准与正则规则库。
- [`references/metric-registry.md`](references/metric-registry.md)：指标登记表规范（防“缩写对、全称错”、复合指标逐行验算）。
- [`references/false-positives.md`](references/false-positives.md)：已确认误报清单与反模式（防二次改错）。
- [`references/report-template.md`](references/report-template.md)：结构化终审报告骨架。
- [`references/terms.example.json`](references/terms.example.json)：项目专有词表模板（内部代号、裸用英文、自贬与口语词）。
- [`scripts/audit_thesis.py`](scripts/audit_thesis.py)：一键式机械静态检查脚本。

## 不适用

- 选题、实验设计、补实验（本 skill 只审已有内容）
- 从零起草与大段改写（那是写作，不是审查）
- 英文期刊论文（建议使用针对英文论文的审稿 pipeline）

## 许可

MIT，见 [LICENSE](LICENSE)。