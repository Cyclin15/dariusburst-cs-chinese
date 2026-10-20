# DARIUSBURST Chronicle Saviours 简体中文汉化

Steam 版《DARIUSBURST Chronicle Saviours》的简体中文汉化补丁与全部构建工程。

官方自带的中文化只做了一半：主菜单、CS 模式剧情、Boss 警告画面等大量文本
是空缺的（官方数据里直接写着 `undefined`），而官方的中文字体是日文汉字集，
渲染简体中文还会缺字形。本项目补全了这些内容，并重建了整套字体。

## 汉化范围

- **主菜单**：AC模式 / CS模式 / DLC模式 / 排行榜 / 选项
- **CS 模式剧情字幕**：全部 320 条任务演出文本（含结局字幕）
- **Boss 战警告画面**（警告 / 海洋生物型巨大战舰 / …）
- **DLC 客机介绍、历代 Darius 系列介绍、各客机操作教程**
- 系统消息（网络提示、退出确认等）、商店、结算奖励等约 380 条
- 游戏名、机体名、版权行、DLC 包名按原样保留英文

## 安装

1. Steam 中将游戏语言设为 **简体中文**（汉化基于游戏的 `ch/` 语言目录工作）
2. 下载 [最新 Release](https://github.com/Cyclin15/dariusburst-cs-chinese/releases)
   中的汉化包，解压到游戏根目录覆盖即可
3. 卸载：用同 Release 里的"原版还原包"覆盖回去

要求 Windows 系统自带 SimHei（黑体）字体（用于渲染汉字）。

## 构建工程

本仓库包含完整的逆向与构建管线，可以在原版游戏文件上复现整个汉化：

| 文件 | 作用 |
|---|---|
| `dzip.py` | 游戏自研 DZIP 压缩格式的完整编解码器（从 exe 逆向） |
| `fontgen.py` | 字体重建：解析原版 BMF 字体，用 SimHei 渲染中文/简体字形，重排图集（TX2 纹理），生成 dxt+tx2 |
| `translations.py` | localizationtext 文本表的全部中文翻译 |
| `telop_zh.py` | CS 模式剧情字幕的全部中文翻译 |
| `build_localization.py` | 重建 localizationtext.dxt（含占位符校验、字体覆盖校验） |
| `build_telop.py` | 重建 orcanewmode_telopstrs.dxt（插入 telop_ch 列） |
| `fontcheck.py` | BMF 字体解析/覆盖检查工具 |
| `revert_all.py` | 一键还原全部被修改的游戏文件 |

游戏目录内运行（默认从 `*.bak` 原版文件构建）：

```bash
python build_localization.py    # 文本表
python build_telop.py           # 剧情字幕
# 字体：见 fontgen.py 的 gen_font()，按需指定字符集与图集尺寸
```

## 逆向笔记

- **DZIP**：`'DZIP' + u32(uncompressed_size) + 位流`。位流含 literal、长/短匹配、
  重复匹配、单字节匹配等算子，匹配偏移有 `0x500 / 0x7d00` 两档长度加成
  （`dzip.py` 里有完整格式说明）。
- **TX2 纹理**：DZIP 节点 = tag + 尺寸字段 + 40 字节纹理头（12 字节文件标识 +
  格式标记 `01 01 00 03` + 12×u16 尺寸表）+ RGBA 数据。图集尺寸必须使用真实
  存在于原版文件中的尺寸组合。
- **BMF 字体**：dxt 节点内是 AngelCode BMF v3 二进制格式；游戏按 chars 块的
  字形框渲染文本。
- **语言目录**：游戏按语言优先读取 `ch/`，缺失时回退 `jp/`；`ch/` 里的
  `font_rodin_ntlgpro24` 是全局中文字体兜底（字符回退链的终点）。
- **纹理预算**（重要教训）：字体图集总量在 ~370MB 时游戏会在关卡中途加载
  舞台纹理后出现整字体白块（纹理创建失败）；全部字体控制在 ≤2048×2048、
  总量 ~170MB 后稳定。

## 已知问题

- 选项菜单的语言选择项有个别汉字未渲染
- 部分界面为官方原样的英文（专有名词、版权行等，有意保留）

## 许可

构建代码以 MIT 许可发布（见 LICENSE）。翻译文本与再生的字体文件仅供学习
研究，请勿用于商业用途；游戏本体版权归 TAITO / Degica 所有。
