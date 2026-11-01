# ICHARG 与固定电荷计算语境
Source: https://vasp.at/wiki/index.php/ICHARG
Keywords: ICHARG, 固定电荷, fixed charge, 非自洽设置
Reviewed: 2026-10-30

官方资料摘要：ICHARG 控制初始电荷密度的构造。ICHARG 大于等于 10 时，电荷密度在电子最小化期间保持固定，相关设置需结合非自洽计算语境理解。

本项目使用限制：前缀观察到 ICHARG 数值不证明它与最后采样循环属于同一次运行，也不证明设置有效或计算成功。固定电荷提示只用于提醒先核对适用模式，不能据此撤销已观察到的未达 EDIFF 消息或直接宣布消息正常。缺失或歧义时不推断默认值，不自动修改 ICHARG。
