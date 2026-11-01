# NELM 与电子自洽异常排查
Source: https://vasp.at/wiki/index.php/NELM
Keywords: NELM, 电子迭代上限, 自洽异常, 未达EDIFF, SCF failure
Reviewed: 2026-10-30

官方资料摘要：NELM 设置电子自洽循环允许的最大步数。官方建议遇到自洽困难时审视电子优化算法及电荷混合等设置，而非只增加迭代次数。

本项目使用限制：不能由最后步编号等于 NELM 宣布上限耗尽或未收敛；计数不确认停止原因。electronic_settings 记录 OUTCAR 前缀的 EDIFF、NELM、ICHARG、ALGO、IALGO；missing 表示未保留，ambiguous 表示不能选择值，都不补默认值。前缀与最后电子循环关联仍未验证，数值比较及模式解释只能作为条件性提示；发现运行重启时不将旧设置用于尾部循环。局部未达消息仍保留其程序报告含义，不由特殊设置撤销。项目不会自动改参数或重启计算。
