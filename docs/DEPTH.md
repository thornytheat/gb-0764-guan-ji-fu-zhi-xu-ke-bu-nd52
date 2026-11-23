# 深度登记 馆际复制许可簿

中型项目。文献传递岗复核历史刊号与许可条款，按页归卷并跟踪撤销。

## 功能模块

| 模块 | 使用者动作 | 入口 | 核心文件 | 测试 |
|---|---|---|---|---|
| M1 授权材料采信 | 查看回执和隔离原因 | `GET/POST /api/intake` | `app/intake/receive.py` `app/intake/spec.py` | `tests/test_intake.py` |
| M2 刊号与机构映射 | 查看旧刊号和机构对照 | `GET/POST /api/registry` | `app/registry/identify.py` `app/registry/rules.py` | `tests/test_registry.py` `tests/test_authority.py` |
| M3 许可版本裁决 | 查当日条款候选 | `GET/POST /api/licenses` | `app/licenses/decide.py` `app/licenses/terms.py` | `tests/test_licenses.py` |
| M4 拆页与额度占用 | 看并集、越界和退回额度 | `GET/POST /api/pages` | `app/pagination/ledger.py` `app/pagination/spans.py` | `tests/test_pages.py` |
| M5 签发请求对账 | 复算许可页与有效额度 | `GET/POST /api/balance` | `app/register/balance.py` | `tests/test_balance.py` |
| M6 批次留档复跑 | 取回原归档快照 | `POST /api/volumes` | `app/vault/record.py` `app/vault/database.py` | `tests/test_vault.py` |
| M7 许可证据签发 | 签发可复验凭证 | `POST /api/volumes/{id}/stamp` | `app/certificate/slip.py` | `tests/test_certificate.py` |
| M8 寄送回执对账 | 分批寄出、登记迟到回执、看补寄页 | `GET/POST /api/volumes/{id}/dispatch`、`POST /api/volumes/{id}/receipt` | `app/dispatch/journal.py` | `tests/test_dispatch.py` |

## 陷阱登记

| TRAP | 现象 | 朴素实现会怎样 | 本项目处理 | 处理位置 | 测试 |
|---|---|---|---|---|---|
| TRAP-02 | 带 BOM 原件 | 流水号列无法识别 | UTF-8 带 BOM 解码 | `app/intake/spec.py` | `tests/test_intake.py::test_bom_keeps_entry` |
| TRAP-04 | 合并表重复列名 | 多一笔申请 | 记录分段并跳过 | `app/intake/receive.py` | `tests/test_intake.py::test_repeated_header_counts_segment` |
| TRAP-05 | 追加余列 | 忽略或错位 | 隔离带原列 | `app/intake/receive.py` | `tests/test_intake.py::test_extra_column_quarantines` |
| TRAP-07 | 页段短横 | 空白申请混入扣减 | 输入校验隔离 | `app/intake/form.py` | `tests/test_intake.py::test_dash_is_missing` |
| TRAP-08 | 机构号有前导零 | 馆号被误合并 | 字符串映射 | `app/registry/identify.py` | `tests/test_registry.py::test_literal_org_codes_keep_zeroes` |
| TRAP-14 | 同流水号不同页 | 随写入次序变化 | 隔离双原件 | `app/intake/receive.py` | `tests/test_intake.py::test_conflicting_copy_id_quarantines_both` |
| TRAP-19 | 专属和公开同日适用 | 高修订公开版覆盖专属 | 先比较授权范围 | `app/licenses/terms.py` | `tests/test_licenses.py::test_special_beats_public_high_revision` |
| TRAP-23 | 请求在截止日 | 到期条款多算一天 | 左闭右开 | `app/licenses/terms.py` | `tests/test_licenses.py::test_closed_at_valid_until` |
| TRAP-25 | 两版时间重叠 | 按列表顺序选版 | 高修订优先，同级冲突待证 | `app/licenses/decide.py` | `tests/test_licenses.py::test_overlapping_versions_and_tie` |
| TRAP-28 | 迟到回执确认页早已收到 | 按整批补寄重发 | 回执逐页结清，只补未见回执的缺页 | `app/dispatch/journal.py` | `tests/test_dispatch.py::test_late_receipt_closes_pages_already_received` |
| TRAP-29 | 借方只报缺两页 | 未结清页全算可补寄 | 在途页计等回执，补寄与等回执互斥 | `app/dispatch/journal.py` | `tests/test_dispatch.py::test_reported_short_pages_only_are_resent` |
| TRAP-30 | 两人同时登记同一回执 | 同页算两份实收 | 写锁加主键，实收按页并集 | `app/dispatch/journal.py` | `tests/test_dispatch.py::test_concurrent_duplicate_receipt_settles_once` |
| TRAP-31 | 回执重试 | 重复结清 | 同号同内容返回原记录不重算 | `app/dispatch/journal.py` | `tests/test_dispatch.py::test_retrying_same_receipt_keeps_ledger_unchanged` |
| TRAP-32 | 回执页越出实签 | 越界页也结清或整张退回 | 越界页不入实收，留「待核查」 | `app/dispatch/journal.py` | `tests/test_dispatch.py::test_receipt_pages_beyond_signed_range_go_to_review` |

58 申请页 = 32 许可页 + 18 拒绝页 + 8 待证页。C01 已许可 6 页，R01 归还 6 页，因此有效占用 26 页。申请页计在订单内部去重，各不同订单独立计数。

签发凭证载 7 单共 26 实签页（C01 的 6 页因 R01 撤销不计）。寄送与回执在此 26 页上逐页对账：实签 = 实收 + 未结清，未结清 = 等回执 + 可补寄。
