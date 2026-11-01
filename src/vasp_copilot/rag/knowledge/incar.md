# INCAR 设置与 OUTCAR 参数核对
Source: https://vasp.at/wiki/index.php/INCAR
Keywords: INCAR, IBRION, NSW, 参数核对, 参数不一致, 输入输出, input settings, parameter comparison
Reviewed: 2026-10-28

官方资料摘要：INCAR 是 VASP 的主要输入文件，其中的标签选择算法并设置参数。VASP 会将对 INCAR 数据的解释写入 OUTCAR，官方建议检查它是否符合预期设置。

本项目使用限制：input_context 只描述当前 INCAR 的显式 IBRION/NSW 与输入意图；output_context 只记录 OUTCAR 前缀采样中的参数。context_comparison 分别核对两项：mismatched 表示观察值不同，不确定差异原因；matched 也不证明文件属于同一次运行。不能把参数比较与 output_comparison 的步编号比较混为一项。即使一个比较不同、另一个相同，也不能据此宣布计算失败、运行身份或电子/离子收敛。建议先核对文件来源、作业记录与输入备份，任何可能原因都应标为待核实；本项目不自动修改文件。
