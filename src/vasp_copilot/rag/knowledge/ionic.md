# EDIFFG 与离子结构优化
Source: https://vasp.at/wiki/index.php/EDIFFG
Keywords: EDIFFG, 离子收敛, 结构优化, 力收敛, ionic convergence, relaxation
Reviewed: 2026-10-23

官方资料摘要：EDIFFG 控制离子结构优化的停止条件。正值使用相邻离子步的总能量变化；负值使用所有原子受力的模是否小于该值的绝对值。设为零时，优化在 NSW 指定的步数后停止。该参数不适用于分子动力学模拟。

本项目使用限制：达到步数限制不能直接当作优化收敛。现有工具没有完整解析 EDIFFG 和最终受力，也没有绑定输入文件与输出日志的运行归属，因此这里只提供参数解释，不增加新的收敛判定。固定离子计算、电子自洽和结构优化应分别解释；证据不足时保留 unknown。
