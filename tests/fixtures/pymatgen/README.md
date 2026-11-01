# 公开 OUTCAR 回归样例

来源：materialsproject/pymatgen，标签 v2025.6.14，固定提交 `682bfd855dd89264b0ff8d6bee4815f8834cc5ac`。获取日期：2026-10-23。

原始路径：

- `tests/files/io/vasp/fixtures/static_silicon/OUTCAR`
- `tests/files/io/vasp/fixtures/relaxation/OUTCAR`

精确下载链接、解压后 SHA-256 和大小见 manifest.json。仓库 MIT 许可全文保存在 LICENSE.pymatgen，其中包含原作者版权声明；该许可文件仅针对这些上游资源，不为整个项目另行指定许可证。

两个 OUTCAR 直接来自上游公开的计算测试目录，文件标题均为 VASP 5.2.12。仅作 gzip 压缩，解压后字节与原始下载完全相同，未筛选行、修改内容或混入人工片段。压缩合计 27531 字节；原始合计 167498 字节。不含 POTCAR 文件，也不包含本地私有计算数据。

test_real_outcar.py 使用 Python 标准库 gzip 解压到 pytest 临时目录，测试结束由 pytest 管理临时文件。运行测试不需要网络或安装 pymatgen，也不会修改压缩样例。

区分三类测试：

1. 完整公开日志：验证参数、最后迭代、结束标记及证据偏移。
2. 派生场景：在内存中明确截断或拼接公开日志，测试上下文重置。这些不是上游真实失败日志。
3. CLI 集成：OUTCAR 来自上游，INCAR 是测试临时构造的最小输入，不声称是上游配套 INCAR。

预期参数、步号及偏移依据直接查看原始行确定，不由被测解析器自动生成。完整性测试验证解压后大小和 SHA-256，以防换行转换或样例意外改变。

更新样例时应重新核对来源、许可、固定提交、哈希及人工预期，不能只更新快照让失败测试通过。

## OSZICAR 补充样例（2026-10-24）

static_silicon.OSZICAR 从此前已下载的同一固定提交 public-examples/static_silicon/OSZICAR 原样复制，1314 字节，无压缩或换行变换。来源路径为 tests/files/io/vasp/fixtures/static_silicon/OSZICAR，精确 URL、哈希和获取日期见 manifest.json 的 oszicar_samples 条目。沿用本目录 LICENSE.pymatgen。

人工核对的最后电子行位于零起始字节 1156，RMM 编号 13；能量摘要位于字节 1236，编号 1、F=E0=-10.645278 eV。tests/test_oszicar.py 核验原始字节、偏移和字段。其他解析边界使用测试中明确构造的记录，不冒充上游真实失败日志。单一样例不代表所有 VASP 版本与模式。
