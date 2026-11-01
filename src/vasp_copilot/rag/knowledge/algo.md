# ALGO 与 IALGO 的输出观察
Source: https://vasp.at/wiki/index.php/ALGO
Keywords: ALGO, IALGO, 电子算法, 后处理设置, electronic algorithm
Reviewed: 2026-10-30

官方资料摘要：ALGO 可选择电子最小化算法或多体计算方法；None、Nothing、Eigenval 属于后处理选项。IALGO 是较低层的算法设置，使用时应结合具体方法和版本核对。

本项目使用限制：ALGO 和 IALGO 只记录各自在 OUTCAR 前缀中出现的值；仅见 IALGO=68 时不补出 ALGO 名称，也不将某个算法认定为异常根因。显式后处理设置只生成需核对适用性的条件说明，不能把未达消息提升为一般自洽失败或撤销消息。当前输入、输出采样及最后循环的运行关系仍需核实。
