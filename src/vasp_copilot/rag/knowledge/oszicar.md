# OSZICAR 电子行、摘要与步编号核对
Source: https://vasp.at/wiki/index.php/OSZICAR
Keywords: OSZICAR, 步编号, 步号, 电子行, 能量摘要, step alignment, electronic row, energy summary
Reviewed: 2026-10-26

官方资料摘要：OSZICAR 记录当前步及迭代信息。电子行的 N 表示电子步编号，E 为当前自由能，dE 为相邻电子步自由能变化，d eps 为能带能量变化。随后摘要中的 F 是总自由能，E0 是展宽趋于零时的能量；摘要 d E 的含义与计算模式有关，不应直接等同于电子行 dE。分子动力学摘要具有不同格式。

本项目使用限制：比较工具先核对最后保留的离子步编号，只有双方编号相同且 OSZICAR 电子行与后续摘要的顺序有效，才比较电子编号。这是 VASP-Copilot 的比较策略，不是官网给出的跨文件对齐算法。last_energy_summary=null 仅表示解析器没有保留可用摘要，不能一般化为完整文件中从未出现过摘要；没有摘要编号时，即使两边电子编号相同，也保留对齐 unknown。编号相同不证明同一次运行或收敛，缺失摘要不证明计算失败。文件观察须引用实际工具证据，资料不能替本次运行补出缺失编号。
