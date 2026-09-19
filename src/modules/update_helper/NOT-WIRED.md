# NOT-WIRED · update_helper

## 结论
本工具**有意暂不接入**模板 `modules/update_helper/`，改用自带 `src/updater.py`（稳定位变体）。

## 依据
- 模板侧接口**已就绪**（1.4.5：`repo=` / `exe_name=` 就是为本工具加的，见
  `H:\Tools\_verify-scratch\UPDATER-SWAP-ls2t.md` 施工单 §3-A/§3-C）。
- **切换本身是独立工程**，施工单已列清：`main.py` 7 处调用点改写、删本仓启动兜底
  `process_pending_update`、`paths.UPDATE_PENDING` 失去消费者（三步②③），
  外加 **4 项切前必补验证**（§5）。
- ⇒ 属**已排期的缺口**，不是"不接"。本轮只完成"上改模板"这一半。

## 重验触发
- 施工单 §5 的 4 项验证补齐时；
- `src/updater.py` 与模板 `update_helper` 出现**新的语义分叉**时；
- `paths.UPDATE_PENDING` 的三步级联被排入波次时。
