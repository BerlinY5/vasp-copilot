# 阶段 2：证据标记，不是完整收敛诊断

核对日期：2026-10-23。适用于保留以下英文完整行的 OUTCAR；未全面验证不同版本、翻译输出或手工修改日志。除人工测试外，现已加入两份固定来源的 VASP 5.2.12 公开日志回归，详见 evaluation.md；未在本地运行 VASP。

| 规则 | 匹配内容 | 依据 | 局限 |
| --- | --- | --- | --- |
| outcar.timing_marker | General timing and accounting informations for this job: | [sisl 自身解析器源码](https://sisl.readthedocs.io/en/stable/_modules/sisl/io/vasp/outcar.html) 使用计时标记识别结束信息 | 本项目只确认完整标题行存在，未验证计时区块完整或进程退出码 |
| outcar.ionic_stop_marker | reached required accuracy - stopping structural energy minimisation | [ASE 自身解析器源码](https://wiki.fysik.dtu.dk/ase/_modules/ase/calculators/vasp/vasp.html) 用相关消息识别离子优化结束 | 不解析 IBRION、NSW、EDIFFG，不验证运行边界、所有电子步及实际力 |

[VASP EDIFFG 文档](https://vasp.at/wiki/index.php/EDIFFG) 定义离子优化停止条件，正值比较能量变化、负值比较力；不适用于分子动力学。[VASP EDIFF 文档](https://vasp.at/wiki/index.php/EDIFF) 定义电子自洽循环停止条件。两种概念不可互相替代。总体电子收敛仍不作裁决；新增的局部未达消息诊断见文末。

## 读取与证据语义

- 尾部观察最多读取末尾 65536 字节，不从头遍历大文件。read_start 为零起始字节位置，bytes_read 是尾部实际读取字节数，snapshot_size 是读取前文件大小。电子自洽设置另采样最多 128 KiB 加一探测字节的前缀，读取方式见文末新规则。
- 完整行去除两端空白后精确匹配；需换行结尾。窗口首行不完整的可能性无法排除时舍弃该行；未换行的末行也舍弃。由此可能漏检，结果保持 unknown。
- evidence.byte_offset 指原文件匹配行的起始字节（含缩进），不是行号；text 为去除空白的标记。每条规则只保存最后一次匹配。
- 标记可能属于较早运行，尤其在日志拼接、追加或正在运行时。因此 marker_found 仅指采样窗口存在标记。normal_termination、electronic_convergence、ionic_convergence、calculation_status 均保持 unknown。
- 缺文件、权限不足、同名目录等错误记录为结构化 error；未命中和读取失败都不会诊断失败或未收敛。
- 大小变化检查只能发现部分并发写入情况；最好对停止写入的输出快照进行诊断。

## 数据结构

schemas.py 使用 Pydantic v2 的 BaseModel 校验字段；Literal 限制状态词，Field 限制字节位置非负，extra='forbid' 捕获拼错或多余字段。model_validate 将字典校验成对象，model_dump 将对象转换为可输出 JSON 的字典。此步验证类型和状态词，不证明科学结论。

文件检查结果 error 仍保留阶段 1 的字符串格式以保持兼容；新增诊断的 ErrorInfo 提供 kind 和 message。以后统一工具协议时再考虑调整公开格式。

## 输入上下文规则（2026-10-23）

规则依据：[INCAR 格式](https://vasp.at/wiki/index.php/INCAR)、[IBRION 模式](https://vasp.at/wiki/index.php/IBRION)、[NSW 步数](https://vasp.at/wiki/index.php/NSW)。这是本项目对受限参数组合的分类，不是完整 VASP 输入验证器。

只有两个参数均显式出现且没有解析问题时才分类：

| 参数组合 | 分类 |
| --- | --- |
| IBRION=-1，NSW>=0 | static：离子不更新；NSW>0 可能重复计算同一结构，不代表推荐设置 |
| IBRION=1/2/3，NSW=0 | static：本项目按零离子更新步分类 |
| IBRION=1/2/3，NSW>0 | relaxation |
| IBRION=0，NSW>0 | molecular_dynamics |
| IBRION=0，NSW=0 | unknown：零步 MD，不推断为静态计算 |
| 其他、缺失、重复或无法解析 | unknown，附 issues |

特别注意 IBRION=3 虽称阻尼分子动力学算法，此处归于结构优化，不能与 IBRION=0 的 MD 混淆。

INCAR 读取上限为 65536+1 字节；多读一字节用于检测超限。超限不使用部分参数。支持 UTF-8（含 BOM）、ASCII、分号和显式注释，整数只接受可选符号加 1–9 位数字。续行、引号、嵌套标签及不符合赋值格式的行均保守返回 unknown；这些语法可能在 VASP 中合法。本工具的限制不等于 VASP 输入错误。相同参数即使值相同，重复也不猜优先级。

parameters 存储识别到的参数及一基行号、原始行；即使 issues 非空也可能保留部分证据，但不作分类。InputContext.error 区分文件系统与编码错误。其他普通赋值标签暂时忽略。

INCAR 可能在计算后被修改。VASP 官方提示应核对 OUTCAR 中实际解释后的参数；新增采样值核对见下文。input_context 仍不改变 OUTCAR 标记判定及任何收敛结论。最后迭代消息观察见后文，全部总体收敛状态仍为 unknown。

## 输入输出采样参数比较（2026-10-23）

依据：[VASP INCAR 文档](https://vasp.at/wiki/index.php/INCAR) 提示，VASP 会将输入解释写入 OUTCAR，用户应核实它与意图一致。本项目据此提供受限的参数值比较，不把任意采样行认定为已经验证的最终生效参数。

- 开头读取 131072+1 字节；额外一字节仅探测窗口是否受限，bytes_read 包含它；实际解析前 131072 字节，read_start=0。window_limited 不意味着读取失败。
- 只接受行首可有空格的、大写 IBRION 或 NSW 整数赋值。值后可跟空白分隔的说明文字，不支持一行多赋值、分号、NUL 或未换行末行。整数限制与 INCAR 解析一致。非参数行忽略。
- 重复参数即使值相同也不猜优先级；可能是原始输入回显与参数区重复，也可能是多段日志。issues 或 error 非空时两项比较都为 unknown。
- 两边解析无问题、某个参数各有唯一值时，用整数相等比较得到 matched / mismatched；缺少某个输出参数仅使该项 unknown，不发明默认值。
- 参数证据分别保留在 input_context.parameters（原始行、一基行号）与 output_context.parameters（OUTCAR 原文、零起始行首字节偏移）。context_comparison 保留被比较的两个数值。
- 尚未定位正式参数区块或保证单次运行归属。窗口外可能还有其他参数、后续运行或错误。matched 只表示可见采样值一致；mismatched 只表示可见值不同，原因可能是输入改动、输出来自其他运行或 VASP 参数处理，不能确定原因，更不意味着失败。
- 输入、输出及尾部诊断分次读取，并非原子快照；请尽量对停止写入的目录副本使用。仍保持全部科学收敛结论为 unknown。

测试使用人工小样例覆盖比较逻辑和读取边界，并用两份公开日志验证参数提取；不代表已在所有 VASP 版本上验证。

## 最后可识别迭代的消息观察（2026-10-23）

此迭代观察字段只关联日志消息，不直接输出 converged 或 unconverged；后续局部诊断见文末新增规则。

依据与适用范围：

- [Kitchin 研究组的原始示例](https://kitchingroup.cheme.cmu.edu/blog/category/vasp/2/) 展示 `Iteration i( j)` 格式及外层、内层步号提取。本项目仅借鉴格式，不使用达到 NELM/NSW 次数来推断未收敛。
- [ASE 项目原始问题报告 #1429](https://gitlab.com/ase/ase/-/issues/1429) 提供两种显式循环消息，并展示仅靠能量差重建 VASP 收敛判断的风险。这是有具体样例的缺陷报告，不是跨版本输出规范。
- [VASP 官方论坛关于 LEPSILON 的讨论](https://vasp.at/forum/viewtopic.php?p=18660) 指出响应计算中 EDIFF 消息可能与实际停止准则不一致。因此本步只报告消息，不将它当作所有计算模式下的电子收敛证明。

实现步骤：

1. 复用末尾 64 KiB 数据；起点非零时跳过第一行，避免使用被裁切的标题。
2. 识别带可选横线装饰的完整 `Iteration i( j)` 行，i、j 为 1–9 位正整数。每次匹配重建当前观察，丢弃前一标题的消息。
3. 只关联该标题之后的完整消息行：`aborting loop because EDIFF is reached` 或 `aborting loop EDIFF was not reached (unconverged)`；允许两端空白与横线装饰，不匹配引用文本中的子串。
4. 各类消息最多保留最后一个证据，两类同时出现时为 conflicting_markers。没有关联消息时 unknown，不由消息缺失推断失败。
5. 行首 `vasp.<数字>.` 视为可识别的新运行标题，清空旧状态；以 Iteration 开头但格式不支持的标题也清空状态。末行缺换行符则使状态 unknown，保留此前证据供查看。

字段含义：ionic_step、electronic_step 是最后识别到的编号；header 与 markers 包含原始行和原文件零起始字节偏移；issues 解释不完整或无法关联的情况。last_iteration 是读取窗口内的观察，不保证是真正最后一个物理步骤或完整运行。

局限：不支持所有日志变体；未识别的运行边界、特殊响应循环、手工拼接日志仍可能有歧义。头部参数采样与尾部观察没有建立同一次运行的绑定。未读到标题、格式不支持、尾部截断都可能返回 unknown。顶层 electronic_convergence、ionic_convergence、normal_termination、calculation_status 保持 unknown。

人工测试包含早期达到但随后新迭代、最后未达到、两类消息冲突、重复消息、新运行、损坏标题、截断末行、窗口边界及 CLI 序列化；另有两份公开 VASP 5.2.12 日志及其明确标注的截断、拼接派生测试。尚未在本地执行 VASP。

## 最后电子循环的局部异常诊断（2026-10-28）

规则 scf.last_loop_not_reached 首次加入可操作的局部诊断。它复用 last_iteration，不新增文件读取：需要完整迭代标题、其后唯一明确的 EDIFF 未达消息、无 issues，且原文字节位置顺序可靠，才返回 electronic_step_diagnosis.status=reported_not_reached、severity=warning。输出保留离子/电子步编号、标题和消息证据、潜在影响、人工排查步骤与局限。

| 输入观察 | 局部结果 | 含义 |
| --- | --- | --- |
| 唯一未达消息且关联可靠 | reported_not_reached / warning | 程序报告最后采样循环未达到 EDIFF，需要核查该步结果 |
| 唯一达到消息且关联可靠 | not_triggered | 本条未达消息规则未触发，不表示整次计算收敛 |
| 消息缺失、冲突、孤立、旧运行重置、标题不支持、末行截断等 | unknown | 不能据采样生成可靠局部异常判断 |
| OUTCAR 无法读取或旧记录缺此字段 | null | 未生成/未保存该规则结果，不追补历史 |

依据：[ASE 原始问题报告 #1429](https://gitlab.com/ase/ase/-/issues/1429) 展示显式停止消息及仅靠能量差重建判断的风险；[EDIFF 官方说明](https://vasp.at/wiki/index.php/EDIFF) 解释停止条件，并指出 EDIFF=0 时执行固定 NELM 次；[NELM 官方说明](https://vasp.at/wiki/index.php/NELM) 定义最大电子自洽次数并建议审查算法和混合设置。消息格式依据来自具体输出实例，未覆盖所有 VASP 版本与模式。

排查建议按来源/完整性、同次运行参数和模式、电子迭代轨迹的顺序展开，必要时再考虑算法、混合和迭代预算。2026-10-28 初版尚未提取 EDIFF/NELM/ICHARG/ALGO；新版设置观察见下一节。消息规则本身不捏造参数值，不宣布 NELM 耗尽或特定根因，不自动改输入或重启。局部警告不代表能量或力已经被本工具重新验证，程序终止和离子优化也必须分别检查。未识别运行边界、特殊响应模式、人为拼接和采样范围仍限制解释能力。

electronic_step_diagnosis 是 OutputDiagnosis 的可选字段，旧数据默认 null。新报告只展示已保存的结果；不会用当前规则解释旧记录。现有两份公开日志都是达到消息，只能验证不误报；首个在线正例为明确标注的人工消息变换，尚无真实未达日志覆盖。

## 电子自洽设置观察与条件性建议（2026-10-30）

electronic_settings 是 OUTCAR 诊断的新可选字段，旧记录默认 null，不追补历史。scf_settings.py 解析 EDIFF、NELM、ICHARG、ALGO、IALGO，每项记录 status、value、occurrences、原始行和行起始字节偏移；同一行可作为多个参数的证据。observed 表示唯一且语法支持的采样赋值，missing 表示当前前缀未保留该参数，ambiguous 表示格式、编码、截断或重复使取值不可靠。后两种状态 value=null，不猜默认值或优先级。无论是否看到 IALGO，都不反推 ALGO。

支持标准大写标签开头的参数行；NELM 的分号伴随 NELMIN/NELMDL 行可以解析，标签精确区分 EDIFFG、NELMIN、NELMDL 等其他名字。EDIFF 支持有限十进制和 E/e、D/d 指数，拒绝负值、非有限值、溢出、下溢为零和残缺数字。整数只接收 1–9 位明确字面量，NELM 必须正、ICHARG 非负。ALGO 接收明确单词或 Old Fast/Old VeryFast；不从说明文字或引用中猜值。SYSTEM 等非目标/伴随标签开头的整行忽略，即使后面有分号目标赋值；这不是完整 INCAR/OUTCAR 语法支持。损坏编码的显示证据可能含替代字符，相应参数不会视为 observed。

diagnose_outcar 在同一个文件句柄中读取有限前缀与尾部；小文件/重叠样本复用已经读入的字节，最大请求为前缀 131073 字节加尾部 65536 字节。前后文件大小、mtime 或读取长度变化时拒绝生成设置和循环结果。现有组合扫描的 IBRION/NSW output_context 仍为独立读取，不据此承诺原子快照。大小/mtime 检查也不能发现所有并发改动。

前缀至最后循环的 iteration_association 始终为 unknown。发现多个可识别 VASP 运行标题，或有运行标题晚于已保留参数证据时，保留原观察但停止基于参数的循环说明；未识别的边界与窗口间未读内容仍是局限。

| 可靠的前缀观察 | 条件性说明 | 不作出的推断 |
| --- | --- | --- |
| EDIFF=0 | 若属于该循环，需按固定电子步数语境核对 | 不撤销未达消息或宣称收敛 |
| ICHARG>=10 | 若属于该循环，先核对固定电荷/非自洽语境及设置有效性 | 不宣称当前循环已验证为非自洽 |
| 显式 ALGO=None/Nothing/Eigenval | 若属于该循环，按后处理语境核对 | 不补 ALGO、不给根因定论 |
| 有 NELM 和可靠最后电子编号 | 只给 below/equal/above 数值关系与双方证据 | 不宣称 NELM 已耗尽或迭代总数 |

依据：[EDIFF](https://vasp.at/wiki/index.php/EDIFF)、[NELM](https://vasp.at/wiki/index.php/NELM)、[ICHARG](https://vasp.at/wiki/index.php/ICHARG)、[ALGO](https://vasp.at/wiki/index.php/ALGO)、[IALGO](https://vasp.at/wiki/index.php/IALGO)。这些是定义和适用性解释，不证明本次参数生效、循环归属或异常根因。局部 reported_not_reached 的消息判断保持原样，settings_considerations 仅补充核查语境；整体三类状态仍为 unknown。

第 13 条在线记录进一步暴露解释边界：未达消息不能倒推出本次总自由能变化或能带能量变化已经高于或未低于 EDIFF，因为工具未执行这些数值比较；在“条件性解释”标题下也不能把它当成事实。应分别写通用停止条件与本次尚未验证的数值判据，并把 reported_not_reached 称为程序报告的局部警告，而非独立验证的真实物理故障。人工变换案例尤其只能验证日志解释流程。
