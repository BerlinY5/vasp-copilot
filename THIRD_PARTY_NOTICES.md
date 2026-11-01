# 第三方资料与样例

## pymatgen 测试样例

`tests/fixtures/pymatgen/` 中的两份压缩 OUTCAR 与一份 OSZICAR 来自
[materialsproject/pymatgen](https://github.com/materialsproject/pymatgen)，固定提交为
`682bfd855dd89264b0ff8d6bee4815f8834cc5ac`。

- 上游 MIT 许可及版权声明：[LICENSE.pymatgen](tests/fixtures/pymatgen/LICENSE.pymatgen)。
- 精确来源、大小和 SHA-256：[manifest.json](tests/fixtures/pymatgen/manifest.json)。
- 获取和变换说明：[样例说明](tests/fixtures/pymatgen/README.md)。

`examples/prepare_demo.py` 仅解压、核验并复制上述样例，不下载其他数据。
原始样例与测试中人工截断、替换或拼接的案例应区别看待。
本仓库不分发 VASP 程序或 POTCAR 文件。

## 知识笔记

`src/vasp_copilot/rag/knowledge/` 中的笔记保留各自参考来源与核对日期。
“官方资料摘要”为项目转述；“本项目使用限制”为项目规则，不应归因于外部来源。

## 项目源码许可

项目源码目前未指定统一许可证。上述上游 MIT 许可仅适用于对应第三方资源，
不自动扩展为整个 VASP-Copilot 项目的许可证。
