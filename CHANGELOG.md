# Changelog

All notable changes to local-speak2text are documented here.
The tagging convention matches the versions in this file.

## Unreleased

> 1.4.1 was never released: its single-instance root-cause fix is merged into this
> section and `VERSION` is rolled back to the last released version 1.4.0
> (STANDARDS G3 item 7: the version number changes only as part of a release).

- **重拷验收口径升级 + 本轮两处行尾漂移（lead 裁定 2026-09-19）：`.py` 的"已落地" =
  `sync_check` 报 `[ok]`（内容）**且**剥掉 `# TEMPLATE-*` 声明行后与正本**逐字节**相等。**
  后半条是**行尾敏感**的，而现有两件工具都看不见——本轮实测：
  * 对**宣告锚 `2afebbc`** 的 19 个派发件逐字节比对，**2 处不符，都是行尾，都是我的**：
    `src/icons.py`（内容早就一致、VER 2.0.0，但 63 LF vs 正本 63 CRLF）与
    `src/modules/appconfig/appconfig.py`（52 LF vs 正本 37 CRLF）。
  * 处置：`icons.py` **按字节从锚点重拷**（声明行 1:1 重写，并**断言 CRLF 数不变** 63→63）；
    `appconfig.py` 是 **`[param]` 设计豁免**——它的内容永远拿不到"与正本一致"的基线，
    所以只做 **CRLF 卫生，内容一个字没取模板**。全程 `git show` 取字节 + `write_bytes`，
    **无 `read_text`/`write_text`**（那正是四份"整文件 LF"的成因）。
  * 另外 3 件（`autostart.py` / `autostart/README.md` / `tray_kit.py`）复核为 strip-header 后
    逐字节相等且 CRLF 数一致 ⇒ 无需再动。提交 `4babff9` + `b8928de`。
  * 两个**判据缺口**（已上报，未擅自修）：
    ① **`C-18` 的详情文案对蓝本说谎**：那条"门禁须含 `sync_check` 步"的要求对
       `blueprints.txt` 名单内的工具**豁免**，而 `local-speak2text` 就在名单里 ⇒ 本仓门禁
       **从来没有** `sync_check` 步骤（已 grep 全仓 bat/cmd 确认），详情却仍打印
       "门禁含 sync_check 与测试"。⇒ lead 那条"重拷 → `sync_check` 绿 → 模板再动又红"的
       **自重置边不适用于本仓**（适用的是 dsh/ocx 这类非蓝本消费方）。
    ② **消费方的 `.py` 行尾没有任何机械判据**：`C-31` 是 TEMPLATE_CHECK
       （`--only C-31 --roots local-speak2text` 对本仓**一行都不输出**），而 `sync_check`
       的 `.py` 路径是 `sha256_text`（`splitlines()`）——**把行尾归一化掉**。
       上面两处漂移都是**手工逐字节比**才发现的。这和对 reme `clean` 的批评**同形**：
       **规则写在文档里，检查发生在别处，两者没连起来。**
       成品判据已备好（**未挂载**，避免在重建冻结前改动构建流程），判别力实测：
       LF 文件→红、全 CRLF→绿、**空扫描面→红（拒绝空真）**、本仓→绿（19 件）。
  * **锚点教训**：同一会话内读模板仓 HEAD 得到**三个不同值**（`2f0cfbf` / `d693c03` /
    `131f282`），且 `2afebbc..d693c03` **确实含 `modules/` 改动** ⇒ **"HEAD"不能当锚**，
    只有 **commit/blob id** 能；连 commit 也只是"当时的它"。本轮一切比对都锚在宣告的 `2afebbc`。
  * 行尾普查（供定范围）：本仓 `src/**`+`tests/**`+`tools/**` 共 **26 个 `.py`/`.md` 是 LF-only**。
    其中**派发件只有 2 个**（本轮已修），其余 24 个是**非派发件**（`tests/*`、`tools/*`、
    `CHANGELOG.md`、`src/updater.py`、`src/keyboard_hook.py`、`src/wasapi_probe.py`）——
    **未动**：裁定只覆盖派发件，扩面与否等 lead 决定，不擅自扩大改动面。
  * **⚠️ 我自己的三个假漂移（本轮最该记的一条）**：我先前把 `sync_check` / `conformance_check`
    的输出当事实报了三条——`[DIFF] paths/README.md 字节差`、`[lag] paths.py 1.1.3→1.1.4`、
    `C-27 FAIL（paths 声明必接 hold_exe_delete_guard、工具代码零引用）`。
    **按宣告锚 `2afebbc` 复算，三条全部不成立**（三条都是我自己刚实测的）：
    - `paths/README.md`：我的副本与锚点**逐字节相等**（46 行，sha `2233c6d363a1`）；
    - `paths.py`：锚点**就是 VER 1.1.3**，strip-header 后与我**差 0 行**；
    - `C-27` 的前提 `<!-- MUST-WIRE: hold_exe_delete_guard -->` 在**锚点的** README 里
      **出现 0 次**（模板工作树里 1 次、52 行）。
    机理是同一条：**那两件仪器读的是模板工作树，而工作树里有在飞改动**。那个在飞改动 =
    commit `082aaba`（`paths 1.1.4 + MUST-WIRE`，18:51:39）。**它是 `2afebbc` 的后继、同一条线上
    更晚的提交**（实测 `git merge-base --is-ancestor 2afebbc 082aaba` rc=0，且
    `merge-base 082aaba 2afebbc` 就是 `2afebbc` 本身）⇒ **本波（锚点）不含它**，
    "`MUST-WIRE: hold_exe_delete_guard`" 这一义务属于**下一波**。我先前"只备不挂"的做法对，
    但**理由给错了**（不是"等解冻"，是它根本不在这一波）。
    > ⚠️ 我在这里还犯了一次**方法错**：我先只跑了一个方向（`082aaba` 是不是 `2afebbc` 的祖先 → rc=1），
    > 就写下"两条线**分叉**"。补跑反方向才知 `2afebbc` 是 `082aaba` 的祖先 ⇒ 是**线性后继**，不是分叉。
    > ⇒ 纪律：**"分叉"是双向断言，必须两个方向都验**；单方向为假只证明"不是祖先"，
    > 不证明"无关"。这正是本仓反复出现的那类错误——**把"我没看到"当成"不存在"**。
    ⇒ **纪律（lead 2026-09-19 §0）**：**比对的正本一律取"被宣告的 commit"，不取工作树**；
    仪器缺 `--rev <commit>` 就先加；在它有之前，**任何人拿工作树比的结论都不算数**。
    ⇒ 教训比纪律更狠：我上一轮**刚亲手测出"HEAD 会漂"**，却没想到同一条机理也长在
    `sync_check` 的输出上——**同一个缺陷，我认得它，还是又犯了一次**。
  * 锚点口径下的真实状态（复算后）：**派发件 0 漂移**；`appconfig.py` 是唯一的 CONTENT-DIFF
    且**设计如此**（`[param]`）；仅剩的真实黄灯是 2 个 `missing-module`（`service_link`、
    `update_helper`；后者是本仓登记在案的 self-fork，见 #32）——这两个目录在锚点的 `ls-tree`
    里**确实存在**，是**真**的未采纳项，不是假漂移。
  * **两条针对"重拷会不会静默删东西"的自验（全仓实测）**：
    ① `grep -rn "TEMPLATE-LOCAL-OVERRIDE"`（全仓 `.py`/`.md`/`.bat`，排除 `release/`、`build/`）
    ⇒ **0 命中** ⇒ **本仓 0 处"已申报"override**，`icons.py` 那次**整份重拷是安全动作**
    （不是"应该没事"，是"没有可删的东西"）。
    > ⚠️ **我在这条上又犯了一次过强推论，已更正**：我当时把它读成了"本仓没有需要人工裁决的分叉"。
    > **而 `src/updater.py`（21 KB 的加固 fork）正是反例**——它是本仓最大的合法分叉，
    > 却**没有任何机器可读留痕**（既无 `TEMPLATE-FROM` 也无 `TEMPLATE-LOCAL-OVERRIDE`），
    > 所以"带 override 的文件不得整份覆盖"那条新纪律**按字面护不住它**。
    > **⇒ 纪律（lead 2026-09-19）：标记清单不是分叉清单。** "0 处 override" 只等于"0 处**申报**"，
    > **不等于"0 处分叉"**；任何"某仓无分叉"的结论必须另有独立证据（代码比对 / 文档记载）。
    > **修法已落**：给 `src/updater.py` 补上
    > `# TEMPLATE-LOCAL-OVERRIDE: 本仓加固 fork（#32 切到模板模块后整体删除）` ⇒ 新门从此护得住它。
    > **这与"grep 0 命中只证明这一层事实"是同一条**：grep 能证明"没有这行字"，
    > **证明不了"没有分叉"**。
    ② **`.py` 身份头全量审计**（对应 `sync_check` 的第 4 个盲区：它剔掉 `# TEMPLATE-` 行，
    因此"整行头缺失"它看不见）：扫描面 = 模板锚点下 `modules/**` 的 **19 个 `.py`** 映射到本仓
    ⇒ **副本 13 件、身份头合格 13 件、缺口 0**（另 6 件是本仓不消费的模块）。⇒ 该盲区**不咬本仓**。
    这一步是**独立扫的**，不是从 `verify_recopy.py` 那 4 件的 `ok` 推的（那 4 件只覆盖重拷清单）。

- **`AsrEngine`'s `model_dir` default was an import-time snapshot — the engine ignored a
  config change (#46).** `def __init__(self, model_dir=MODEL_DIR, ...)` evaluates the default
  **once, at class-definition time**; `load_config()` later rebinds the module global
  `MODEL_DIR`, but the default still held the old string, so `AsrEngine()` loaded the old
  model. The same signature already had the correct idiom one line below
  (`num_threads=None` + resolve in the body) — the fix makes `model_dir` match it:
  `model_dir=None` sentinel, resolved through one shared rule
  (`_engine_default_model_dir()`), which `describe_model_resolution()` now also uses so the
  printed `engine` value and the loaded directory can no longer be computed two different ways.
  * **Measured, not inferred** (`tests/test_engine_model_dir.py`, new): with the pin isolated,
  `load_config()` resolved the new dir into `MODEL_DIR` (**C1 green**) while `AsrEngine()`
  still reported and passed to `_build` the old
  `…\local-speak2text\asr-modules\sensevoice-small-int8` (**A and C2 red**). After the fix all
  three are green. Positive control B (explicit `model_dir=` still wins) guards against the
  degenerate "fix" that ignores the argument; a discriminating control asserts the import-time
  value really differs from the switched dir, without which A/C could pass on a broken build.
  Because the fix touches a *default*, a control that only checked "the new dir is used" would
  have been green before the fix too if the config happened to match — hence that third check.
  * Chose the sentinel over "pass explicitly at all call sites" because it (a) matches the idiom
  already in the same signature, (b) covers the four bare call sites
  (`main.py:1036/1092/1117`, `pipeline.py:772`) *and* any future one, and (c) is proven not to
  break explicit callers. The explicit-call-site route depends on every present and future
  author remembering — the failure mode this defect already is. Side benefit measured:
  `--smoke` validates `os.path.isdir(MODEL_DIR)` at `main.py:1090` and then constructs
  `AsrEngine()` at 1092 — those two can no longer disagree about which directory was checked.
  * Nothing else depended on the snapshot semantics: the only reader of the default parameter
  was `describe_model_resolution()` (`pipeline.py:119`), now switched to the shared rule. A
  build-time **regression probe** replaces it, printed by GATE 3: if the default ever becomes
  non-`None` again, the selftest says so (`WARN`, never `FAIL` — same disposition as the other
  GATE 3 lines, which must not fail on user-side stale state).
  * Same-family sweep (`def …=UPPERCASE_NAME`), scan surface **66 `.py` under the four tools'
  `src/`**, 13 hits: l-s2t 7, reme 4, dsh 1, ocx 1. In l-s2t all 7 reduce to five constants
  (`COLOR_IDLE`, `APP_NAME`, `SAMPLE_RATE`, `EXE_NAME`, `UPDATE_WAIT_LIMIT`) and each is
  defined exactly once, has no other assignment and no `global` rebinding, with an immutable
  value (`Constant`/`Tuple`) — i.e. **no second runtime-mutable instance in this repo**. The
  sweep has discriminating power: pointed at `HEAD` (pre-fix) it lists
  `pipeline.py:260 __init__(model_dir=MODEL_DIR)`; on the working tree that entry is gone and
  only the benign `open_mic_stream(sample_rate=SAMPLE_RATE)` remains.
  * **Registered gap, not fixed here** (same family, different mechanism — name import binding
    rather than a default parameter): `main.py:39` `from pipeline import MODEL_DIR` binds a
    frozen copy, so `main.MODEL_DIR` does **not** follow `pipeline.load_config()`. Measured:
    after rebinding the config, `pipeline.MODEL_DIR` = the new dir while `main.MODEL_DIR` = the
    old one. Affected read sites: `main.py:975` (the "model updated" notification prints the
    **old** directory), `main.py:957` (the picker's initial dir is stale on the second switch),
    `main.py:1090/1091/1094` (`--smoke` validates and prints the stale value). `main.py:40`
    imports `MODEL_NAME` and never uses it, which is a hint that this import list was never
    revisited. **已按 lead 路由修掉，见下一条。**

- **#47 修复：`main` 侧的模型目录改成"取用时现读"，不再持有导入期副本。**
  `from pipeline import MODEL_DIR` 绑的是**导入那一刻的静态副本**，而 `pipeline.load_config()`
  重绑的是 **pipeline 模块里的**那个名字——`main` 这边永远停在旧值。两处用户可见症状都实测到：
  * 托盘「选择模型目录」的**对话框初始目录**是旧的（第二次换目录时尤其明显）；
  * 换目录成功后的**通知打印旧目录**（`模型目录已更新: <旧路径>`）。
  修法（lead 采纳的最小形态）：**去掉 `MODEL_DIR` / `MODEL_NAME` 的 from-import**，
  在四个读点现取 `pipeline.MODEL_DIR`（选目录的 `initialdir`、通知文案、`--smoke` 的
  校验值 / 打印值各一处）。`MODEL_NAME` 同时是**死引用**（全仓无消费者，已核），一并去掉；
  并加了一行注释说明"这两个名字**有意**不 from-import"，避免后人加回去。
  * **先红后绿，同文件同环境**（`tests/test_main_model_dir.py`，新增）：
    旧实现下 `FAIL picker opens at the CURRENT model dir  initialdir=<导入期目录>` 与
    `FAIL 'model updated' notification names the NEW dir  notify='模型目录已更新: <导入期目录>'`
    → 改完 6/6 全绿。
  * **两条出口都钉**，因为只钉一条时"把某一处改成 `new_engine.model_dir`"这种**局部补丁**
    也能通过——而其余读点（尤其 `--smoke` 那三处）仍然是旧值。这与 #46 的 B 档是同一手法：
    **防退化解**。
  * 附带收益（与 #46 合并后才成立）：`--smoke` 里"校验目录存在"与"构造 `AsrEngine()`"
    **曾经可以指向不同目录**（一个读快照、一个读调用时值）；现在校验 / 引擎 / 打印三处**同源**，
    不可能再互相矛盾。
  * 门禁：新增 **GATE 2g**（在 F11/D12 pin 区间内），按同一套方法给出执行证据——
    原字节抽区间实跑，`[TEST] main-side model dir (use-time, not a frozen copy) ...` →
    `MAIN MODEL_DIR TEST OK`，`probe rc = 0`，收尾后 `build/test-data` 不存在。

- **`src/updater.py`（自家 fork）：轮询匹配用的是裸名 `find`——一条**取决于 PATH 顺序**的
  潜伏缺陷（**已按此定性修正，见下方"上下文更正"**）。** 渲染出的 `apply.bat` 里那一行是
  `find /i "{exe}" "%POLL%" >nul`。GNU find 会把 `/i` 与镜像名都当**路径**去 stat，于是
  **进程在跑与不在跑都返回 1** ⇒ `if errorlevel 1 goto gone` **第一拍就跳走**，`%tries%` 恒为 1、
  `:giveup` 不可达——等待循环从不等待，更新退化成**竞态**（旧进程若尚未退净，robocopy 撞锁 →
  `:install_failed` → 回铺快照）。**但这一串只在"GNU find 排在前面"时成立**，见下。
  * **实测（双向对照，不是单点读数）**：同一条命令，`explorer.exe`（必在跑）与
    `no_such_proc_xyz.exe`（必不存在）**errorlevel 都是 1**，stderr 都是
    `find: '/i': No such file or directory`。**返回值与进程是否存活无关**——这正是
    "调用方无法据它决定还要不要继续等"的机理。
  * ⚠️ **上下文更正（本轮最重要的自我纠错）**：上面那次双向对照是在**我自己的 bash 里**取的，
    而 **Git-Bash 会把 `Git\usr\bin` 前置到 PATH**——那不是 `apply.bat` 的真实运行环境。
    补测第二个上下文后结论**必须限定**：
    | 上下文 | `where find` 首命中 | 命中 | 未命中 | 有判别力？ |
    |---|---|---|---|---|
    | A：Git-Bash 派生 PATH（我先前测的） | `H:\Tools\Git\usr\bin\find.exe` | 1 | 1 | **否** |
    | B：**注册表合并 PATH**（explorer 启动的应用、以及它 spawn 的 `apply.bat` 实际继承的） | `C:\Windows\System32\find.exe` | **0** | 1 | **是** |
    上下文 B 的构造：`Machine PATH + ';' + User PATH`；实测该值里与 Git 相关的只有
    `H:\Tools\Git\cmd`（**不含 `usr\bin`**，`find.exe` 不在其中），msys64 的 `usr\bin` 也在
    System32 **之后** ⇒ 首命中是 **Windows 的 `find.exe`**，而 `find /i "串" 文件` 正是它的用法
    ⇒ **行为正确**。且 `launch_pending_cmd` 用 `Popen(["cmd.exe","/c",…])` **不传 `env=`**、
    继承应用环境 ⇒ 生产路径上跑的就是上下文 B。
    ⇒ **准确定性：这是"取决于 PATH 顺序"的潜伏缺陷，不是生产环境恒坏的缺陷。** 我先前
    "恒返回 1 / 等待循环从不等待"的表述**过强**，在此更正；lead 转述的"活缺陷"同样应改成
    "潜伏缺陷"。**修法依然正确且更有价值**——绝对路径让判别力**不再依赖 PATH 顺序**
    （本机 msys64 的 GNU find 就紧排在 System32 之后，任何 PATH 编辑都可能把它翻上来），
    并把这条命令钉成上下文无关。⇒ **修的是"正确性依赖环境偶然性"这件事本身**，不是"修一个
    正在流血的伤口"。
  * 修法：**只改那一行为绝对路径** `%SystemRoot%\System32\find.exe`（与 reme 的
    "EVERY command absolute" 同形；按用户规则以 reme 为标准，不需要再论证）。
    同时**逐命令实测了同族暴露面**（26 个候选）。**⚠️ 这一组也是在上下文 A 里测的**：
    被抢占的候选是 `find`→`Git\usr\bin\find.exe`、`sort`→`Git\usr\bin\sort.exe`、
    `timeout`→`Git\usr\bin\timeout.exe`、`curl`→`Git\mingw64\bin\curl.exe`、
    `tar`→`Git\usr\bin\tar.exe`，共**五个**；其余候选（`findstr`/`tasklist`/`robocopy`/
    `powershell`/`ping`/`more`/`where`/`xcopy`/`certutil`/`mshta`/`cscript`/`wscript`/`reg`/
    `sc`/`netsh`/`wmic`/`attrib`/`tree`/`fc`/`comp`/`compact`）首命中均 System32；
    `start` / `del` / `move` / `mkdir` / `rmdir` / `copy` / `type` 是 cmd **内建**，PATH 不参与
    （`where start` 虽命中 Git 的同名文件，但 cmd 优先用内建的）。
    **在上下文 B（生产）里重测：五个全部首命中 System32**（含 `find`）⇒ "被抢占"是
    **上下文 A 的产物**，这五个在真实运行环境里当前都安全。⇒ 五选一里只有 `find` 被调用
    （见下），而它连"当前会坏"都算不上，只是**可能**坏。
  * **五个"可被抢"的候选里，本仓实际调用几个？** 用"剥离 rem/:: 注释后按命令位置匹配"
    的扫描器扫四个语料（`build.bat` / `release.bat` / `run.bat` / 渲染模板 `_APPLY_BAT`）
    ⇒ **工作区 0 命中**。**判别控制**（防"0 命中其实是没扫到"）：对 **HEAD 里的
    `src/updater.py`**（`find` 尚未绝对路径化，因为该修复还在工作区未提交）跑同一扫描器
    ⇒ **命中 1**，正是 `find /i "{exe}" "%POLL%" >nul`（第 18 行，相对该模板）。
    ⇒ 结论：**这一类只有 `find` 一处被调，已修；`sort`/`timeout`/`curl`/`tar` 零调用**。
    一行修复即完整，不是"修了四分之一的局部补丁"。
  * **顺带一条"不做"**：`tasklist` / `robocopy` / `powershell` 本机首命中都在 System32，
    按"只修真缺陷"不动它们（绝对路径化的统一改造是**模板** #49 的事，且本 fork 将被
    `update_helper` 的稳定安装位模式整体取代——见 #32）。
  * **先红后绿**（`tests/test_poll_matcher.py`，新增）：喂两份 poll 文件（一份含镜像名、
    一份不含），断言**两条返回码必须不同**。修前**在上下文 A 里** `hit rc=1 miss rc=1`
    （红，无判别力）——**同一份裸名探测脚本在上下文 B 里是 0 / 1（绿）**，这个对照已写进
    该测试的 docstring，免得后来者把那次红当成"生产在流血"。修后 `hit rc=0 miss rc=1`
    且**两个上下文一致**（因为已是绝对路径）。这条判据**不依赖"此刻系统里恰好有哪些进程在跑"**，
    因此可复现；它锚的是"这条命令在做什么"（读 `%POLL%`、带 `/i`），不是命令的拼写。
  * **门禁自身的漏洞（本轮实测，已修）**：上一版 `test_poll_matcher.py` 继承**调用者
    shell** 的 PATH，于是它的判别力**取决于谁跑 build.bat**——从 Git-Bash 跑（`usr\bin`
    被前置）会红，从 cmd 跑（System32 在前）**即使把修复回退成裸名也照样绿**。实测：
    在**生产上下文**（注册表合并 PATH，`where find -> C:\Windows\System32\find.exe`）下
    把那一行临时改回裸名 ⇒ **旧的五条断言全绿**（`rc=0/1`，含"有判别力"那条），
    回归门禁对这次回退**零能力**；只有新加的抢占判据变红（`prod=0/1 shadowed=1/1`）。
    修法：测试**自己造抢占世界**——取一个"不是 System32 那个"的 `find.exe`（优先真 GNU find，
    由 `git` 反推 `usr\bin`；退路是 `cmd.exe` 的副本）放进临时目录并**前置**到子进程 PATH，
    然后要求"有抢占"与"无抢占"两个世界给出**同一个判决**。裸名做不到（实测 hit=1/miss=1，
    与 miss 同码 ⇒ 判别力归零），绝对路径做得到（两个世界都 0/1）。⇒ 判据从此**与跑测试的
    shell 无关**，这正是它该有的样子：**门禁的红/绿不能是调用环境的函数**。
  * **两个坏判据，都栽在"空读数算通过"**：① 抢占件第一版用 `find.bat`——批处理之间无 `call`
    调用会**接管控制权**不返回，于是 `echo RC=` 从不执行、读数是 **None**，而 `None != 0`
    为真 ⇒ 断言**假绿**（这是"0 命中其实是没扫到"的新变体：**没扫到**换成了**没跑起来**）。
    ② 同一段的 `rc_miss != 0` 同形。两处都补了 `is not None`。⇒ 纪律：**凡 `x != 0` /
    `x == 0` 形式的断言，先问一句"x 为 None 时它是什么"**。
  * **门禁**：新增 **GATE 2h**。整 bat 实跑（在副本里，见下）八条测试全绿。
  * **两个我自己的近失，留痕**：① 我第一版把**中文注释写进了那个 bat 模板**——
    `test_update_safety` 当场以 `UnicodeEncodeError: 'ascii' codec` 抓住：**那个模板会被
    写成 `.bat`，必须保持纯 ASCII**（C-22 的存在理由）。注释已改为英文。② 我的测试第一版
    按**命令拼写**（`find /i`）去定位那一行，修复（换成绝对路径）后**当场红成"找不到命令行"**
    ——正是"判据绑死实现形态"这个坑；已改为按行为定位。

- **两条"重建前置"的实测（先立仪器、后动手术）：产物可搬移性 + 重拷验收判据。**
  * **产物可搬移：成立。** 把现有 `release\local-speak2text-1.4.0\` 拷到 scratch，跑
    `--smoke`（按 build.bat 的原样 pin `_CONFIG`/`_DATA_DIR`）⇒ `rc=0`；再把它 **搬到另一个
    绝对路径、不同深度** 重跑 ⇒ `rc=0`，两次 `smoke.log` 都报同一个 model_dir。
    ⇒ "副本构建 → 再把产物就位"这条路对 l-s2t **前提成立**（PyInstaller 没有把构建期路径
    烘成不可搬移的东西）。
  * **补一条更直接的证据（同一结论，换一种测法）**：把产物目录下**全部 1103 个文件**逐个
    搜构建期源码绝对路径 `H:\Tools\my_diy_tools\local-speak2text` ⇒ **命中 1 个，且那是
    `smoke.log`（85 B 的日志，不是二进制）** ⇒ 构建期路径**没有被烘进任何二进制**。
    ⇒ 结论仍是"可搬移"，但**唯一未验的是"副本构建 + 放回真仓"后 `config.json` 里那个
    **相对** `model_dir` 的向上回退行为**——上面那次搬移测试是**显式把绝对 model_dir 钉回去
    才做的**（当时就写明"这是必须拆掉的混淆"）。⇒ 这一格应记成**可关闭的窄问题**，
    不是"无证据"。
  * **测试里有个必须拆掉的混淆**：打包出的 `config.json` 写的是**相对** `asr-modules/...`，
    靠"向上回退"在仓库内找模型；若照原样搬出仓库，冒烟会因**找不到模型**而失败——那会把
    "搬移失败"与"模型缺失"混成同一个红。所以我在副本的 config 里**显式写绝对 model_dir**，
    让"搬移"成为唯一变量。⇒ 顺带确认：**副本若没有 `asr-modules`，GATE 3 / 冻结冒烟必然失败**
    （副本构建需要把模型接进来，或用 `/J` 目录联接——只读）。
  * **新鲜度判据必须排除 `__pycache__`（lead 2026-09-19 立的口径的一条补丁，实测）**：
    口径是 `exe mtime > max(参与产物的目录下所有文件 mtime)`。实测本机：
    ```
    含 __pycache__/.pyc        最新 = src/modules/tray_kit/__pycache__/tray_kit.cpython-313.pyc  19:04:15
    排除 __pycache__ 与 .pyc    最新 = src/modules/appconfig/appconfig.py                        19:03:58
    ```
    ⇒ `src/` 下**最新的东西是一个 `.pyc`，比最新真实源文件还新 17 秒**，而它是**本仓门禁的
    GATE 1（`py_compile`）刚生成的**。⇒ **产物构建完成之后，任何人再跑一次 Python（门禁 /
    测试 / 导入）都会把这条判据打成"过期"**，即使源码一字未改。方向是安全的（假"过期"
    而非假"新鲜"），但它会**烧掉这个信号**——人们很快学会无视它。
    ⇒ 口径应写成 `… 排除 __pycache__/** 与 *.pyc`。与"比内容还是比钟"同族的第三问：
    **比的是"人写的"还是"机器生成的"**。
  * **`--smoke` 在往 APP_DIR 写状态（本轮顺带发现，未修，已上报）**：搜那条 1103 分之 1 的
    命中时看见的——`src/main.py:1100` 是 `log = os.path.join(base, "smoke.log")`，`base` =
    **exe 所在目录**。现场证据：`release\local-speak2text-1.4.0\smoke.log`（85 B，18:44），
    内容是 `OK model_dir=H:\Tools\my_diy_tools\local-speak2text\asr-modules\sensevoice-small-int8`。
    三个问题叠加：① **违反 F11/paths 的"禁止往 APP_DIR 写状态"**（APP_DIR 正是会被整目录替换
    的地方）；② 产物/安装目录因此**带一份含构建机绝对路径的文件**（打包发布即轻度路径泄露）；
    ③ `build.bat` 只在它自己那段 `del` 它（:345），**构建流程之外跑的 `--smoke` 会把它留下**
    （本机这次就是这样，正是 lead 让我做验收时跑的那一次）。
    ⇒ 修法：写进 `LOG_DIR`（数据区，随 `<APP>_DATA_DIR` 重定向）并同步 `build.bat:345/359/360`。
    **建议并进 `paths` C-2 那一波**（两条都动 `main()`），不单独动构建流程。
  * **重拷验收判据要改一处**：`副本 raw blob == 正本 raw blob` **设计上不可满足**——副本按
    家族规则必须带 `# TEMPLATE-FROM: <路径> | TEMPLATE-VER: x`，而正本写的是
    `# TEMPLATE-MODULE: <名> | TEMPLATE-VER: x`。实测：6 条派发路径 **6/6 mismatch**，连
    `sync_check` 报 `[ok]` 的 `log_kit.py` 也一样。而 `sync_check` 的归一化值又太松
    （`icons.py` 是 LF vs CRLF，重拷前后都 `[ok]`）。
    **正确判据 = 去掉声明行之后比字节**（EOL 仍参与）：
    ```
    log_kit.py / i18n.py / paths.py   ok（只有声明头不同，合法）
    icons.py        BLOB-DIFF  ← 真：LF vs CRLF，sync_check 看不见
    tray_kit.py     BLOB-DIFF  ← 真：模板 C2 未吸收
    autostart.py    BLOB-DIFF  ← 真：1.1.1 vs 1.1.2
    ```
    既可满足（3 条 ok）又有判别力（3 条真红）——两侧都验过，工具留在
    `_verify-scratch\blob_verify.py`。
  * **顺带解开一个看起来矛盾的数**：按**工作树**比，我的重拷清单是 **4 件**（含 C-2 的
    `paths.py` / `paths/README.md`）；按**已提交的 HEAD** 比是 **3 件**（C-2 还没 commit，
    所以 `paths.py` 那一格读作 ok）。两个数都对，**取决于比的是哪棵树**——这也说明"比之前
    必须先说清比的是工作树还是 commit"。

- **重建纪律（留痕，重建时照此执行）：删 `release\<name>-<VER>` **就是删线上安装位**。**
  本机只读实测：`HKCU\...\Run` 的 `LocalSpeak2Text` =
  `...\local-speak2text\release\local-speak2text-1.4.0\local-speak2text.exe`（存在，6,296,010 B，
  mtime `17:25:25`），而 `appconfig.VERSION = 1.4.0` ⇒ `build.bat` 的 `RELEASE_DIR` **正是该目录**；
  查进程为空（当时没在跑）。于是"开发期不改版本号"+"`build.bat` 见到同名目录就报错退出"
  ⇒ **重建必然要动这个目录**，而删除窗口里一旦注销/重启，Run key 就指向不存在的路径
  （用户报告的登录弹窗那一类）。**本仓原计划是"备份 → 删 → 构建"，已作废**，
  改为五步：① 记下 Run key 原值 → ② 确认没有进程从该目录运行 → ③ **改名保留**
  `release\_stale_<name>-<VER>-<ts>`（**不删**）→ ④ 构建 + 验新鲜度 → ⑤ 确认新产物好了**才**删
  改名后的旧目录；构建失败就**改回原名**（`rename` 一次即可，不必重写整目录）。
  * **新鲜度判据不能用 HEAD 的时钟**：`exe mtime > git log -1 --format=%ct -- src/` 在
    **dirty** 仓上恒真——实测当前产物 `17:25:25` > 提交 `16:04:49`，判据说"新鲜"，而
    `src/` 里有 6 个文件比它新（最新 `src/updater.py` `18:40:02`）。正确判据是
    **`exe mtime > max(src/ 下所有文件的 mtime)`**（用它对当前产物判 = 过期，正确）。
    通用规则：**判新鲜/判过期比"工作区当前内容"，不比 HEAD 的时钟**；只有 revision 快照
    才用 commit 时间，且必须标明是哪种。
  * 同样记一笔**被否决的做法**："在副本里构建再把产物搬进真仓"能把窗口压到毫秒级，但
    PyInstaller 可能把构建期绝对路径烘进 exe/`_internal`，**可搬移性未实测** ⇒ 在拿到
    证据之前不采用（"看起来更快"不能换一个未验证的假设）。

- **留痕：为什么 C-33 那次动作是「不跟先前指示」而不是「违反指示」。** 先前的指示是
  "届时不跟"，它的前提是"形态未定、无需跟"。前提消失了——C-33 已定为 FAIL 级、判据不再带
  "派发件"限定、且直接命中本仓的 fork——于是**指令随之失效**；并且 C-33 条文里已明文给出改法
  （`powershell -NoProfile -Command "Start-Sleep -Milliseconds N"` 取代 `ping -n 2 127.0.0.1`），
  照抄即可，没有自创形态。记为通用规则：**指令的前提过期 ⇒ 指令过期**；判断依据是理由，
  不是字面。附带收益：`ping` 节拍实测每拍约 9.0 s（名义 120 s 的预算实际约 18 分钟），
  换掉后 `test_update_safety` 从"每条渲染 bat 各付 9 s"降到 8.7 s 整轮，
  既更快也更少撞 25 s 超时——**这就是把它从风格问题变成工程收益的那条证据**。

- **两个新测试已挂进门禁，并证明它们真的被执行**（lead 裁定：不在门禁里的测试会烂掉）。
  `build.bat` 新增 **GATE 2e**（`tests\test_quit_failopen.py`）与 **GATE 2f**
  （`tests\test_engine_model_dir.py`），并在整个测试段外面加了 **F11/D12 harness pin**：
  `set "LOCAL_SPEAK2TEXT_DATA_DIR=%CD%\build\test-data"` 在 GATE 2b 之前、收尾 `rmdir`
  在 GATE 2f 之后。对现有测试是 **no-op**（每个文件都在文件内覆盖该 env），价值在于
  **新测试忘了钉也不再泄漏**——而这正是那 6 个缺陷能存在的土壤。
  * 执行证据（不是"我加了行"）：按**原字节**抽出 build.bat 的 pin 区间（行 125–200）
    写成探针 bat 实跑，`rc=0`，六条 `[TEST]` 按序打印，两条新测试各自报
    `QUIT FAIL-OPEN TEST OK` / `ENGINE MODEL_DIR TEST OK`；
    收尾行确实执行——跑完 `build/test-data` **不存在**。
  * `C-22` `[ok]`（3 个 bat/cmd 全 CRLF+ASCII 无 TAB，编辑后自证）；`C-25` `[ok]`
    （3 个 bat 的步骤调用都在磁盘上且不在死代码里）——后者正是家族为"门禁步骤静默不执行"
    （reme `build.bat:201` 被 TAB 写坏那次）立的判据。
  * 未能用 `build.bat` 本体跑到那一步：它在第 57 行就因 `release\1.4.0` 已存在而 `exit`
    ——要看到 GATE 2e/2f 的真身输出，必须走到**重建**那一步。

- **留痕：heredoc 会把我写的 `\\` 折成 `\`，于是"我转义过的字面量"在 Python 里重新被转义。**
  实例（2026-09-19，就在本条目上一步）：我用 `'build\\test-data"'` 在 build.bat 里找 pin 行，
  **两次都找不到**，而用不含反斜杠的锚点 `"test-data" in l` 立刻命中。打印出来才看清：
  ```
  我写的字面量 -> 到达 Python 后 repr = 'build\test-data"'   含反斜杠=False  含TAB=True
  ```
  即**这层传输把 `\\` 折叠成了 `\`**，Python 随后把 `\t` 当成 TAB——所以我实际去搜的是
  `…\build<TAB>est-data"`。**"没找到"在这里不是"不存在"，而是"我的搜索键被改写了"。**
  这与本轮 `/dev/null` 那次同源（lead 的定性：**检查与被检查共享同一层改写**），只是那次
  骗过的是"自证比对"，这次骗过的是"查找"。处置：**经此通道写字面量时不要依赖反斜杠转义**
  ——要么用 `chr(92)` 拼，要么选不含反斜杠的锚点（本次即如此）。

- **留痕：扫描记录必须带"时点"，否则"有界窗口"与"无界悬空"在单次读数上完全同形。**
  实例（2026-09-19）：一次对 `release/` 的扫描报"目录不存在 / 自启目标 `exists=False`"，
  看起来像一个**尚未闭合的中间态**；实测那次构建**早已完成**（产物 mtime `17:25:25`，
  两条断言均为 True）。两者在**单次读数**里给出的是同一个 `exists=False`——**读数的时刻
  早于 17:25:25**，而那份输出既没记时刻、也没读被扫对象的 mtime，因此它**无法区分
  "窗口开着"与"窗口已关"**。**拿一个不可判的读数当可判的证据**，是这条的根因。
  * 通用规则：**任何"扫到 X"的结论都必须附扫描时刻 + 被扫对象 mtime**；缺这两样，
    它不是证据而是猜测。与另外两条同族：C-30/纪律⑥（"0 hits"与"没东西可命中"必须
    可区分）、以及"锚点必须指向该文件最后一次变更"。
  * 本仓已经**操作化**的两处：`tests/_cleanup.py` 的 `scratch_dir()` 把每个 scratch root
    登记进 `SWEPT` + atexit 兜底（清理是**可验证**的，不是"没报错就算干净"）；
    自启测试在断言后**回读**注册表值并断言等于原值（"我改过"与"我改回来了"必须长得不一样）。
  * 同族判读纪律：**旧文件不构成本轮证据**。`build/crash.log` 的 mtime 是 09-17（两天前），
    落点在构建工作目录、只有一个栈一次事件 → **不立案**；只有它**再次出现**（新 mtime +
    同类栈）才构成有频率的证据。区分"这个文件有问题"与"这个文件在本轮变过"靠的仍是 mtime。

- **`:giveup` 的"名义预算"现在由同一次渲染用的 `limit` 现算——日志里的数不再自相矛盾。**
  旧写法 `build_apply_script(..., limit=limit)` 里，次数用**实参**，而预算传的是**模块常量**
  `UPDATE_WAIT_BUDGET_S`：`limit=2` 于是渲染出
  `... after %tries% polls x 1000ms (nominal budget 120s, lower bound)` —— **2 拍 × 1 秒
  写成 120 秒**。这不是"文案不精确"，是**拼出了一个不可能的组合**；而本文件的
  `_run_bat` 一直用 `limit=2` 保持等待短，也就是说**测试长期在渲染这行自相矛盾的文本，
  只是从没有人断言过它**（与 C-33"日志说谎"同族：口径是**日志里的数必须是被测过的数**）。
  * 修法：`budget_s=limit * UPDATE_WAIT_TICK_MS // 1000`，与 `limit`、`tick_ms` 同源；
    模块常量保留为**默认那一对**的取值并在注释里写明"不得直接传它渲染"。
  * 两侧实测（同一 `_APPLY_BAT`、同一个 `limit=2`）：
    旧形态 `budget=120s` → 修复后 `budget=2s`；判别力即在这 120≠2 上。
  * 钉法（`tests/test_update_safety.py` 新增 4 条断言）：`limit ∈ {120, 2, 7}` 逐个断言
    `budget == limit × tick ÷ 1000`，外加一条"默认渲染仍等于 `UPDATE_WAIT_BUDGET_S`"，
    保证修复没有顺手改掉默认行为。此前该测试**已经在跑 `limit=2` 的真替换脚本**，
    所以这 4 条是把"一直在渲染但从未被检查"的文本变成判据，不是新增覆盖。
  * 注：l-s2t 的 `src/updater.py` 是**自家 fork**（不随模板 `update_helper` 派发），
    所以模板侧的同一处修复**不会自动到达本仓**；本次是本仓自行的等价修复。
  * 三态在本仓各由哪一行体现（这是钉测试的靶，也是将来替换时的对照表）：
    | 状态 | 行 | 判据 |
    |---|---|---|
    | 富框抛 → 转原生框 | `src/main.py:932` | `except Exception as exc:` |
    | 富框抛 **且** 原生框抛 → 放行 | `src/main.py:939-942`（`choice = None`）→ `:943` | `if choice is None:` |
    | 用户明确取消 → 不退出 | `src/main.py:945` → `:947` | `elif not choice.get("go"): return` |
  * **"用户取消"与"链路不可用"在 l-s2t 里不会混淆**，这是三态能分开的前提：
    `tray_kit.confirm_quit_dialog` 的 docstring 第 161 行写"取消返回 None"，但实测
    取消只 `win.destroy()`，`result` 保持 `{"go": False, ...}`，第 220 行
    `return result or None` 因此**恒为 dict**。该 docstring 与实现不符，已上报模板侧。
  * 本仓读 `choice` 只读 `"go"` 一个键——`"stop_service"` 在 `src/main.py:938` 被写入后
    **全仓无人读**（`grep -n stop_service src/` 只命中 tray_kit 内部与这一处赋值）。
    这既证明 l-s2t 没有"服务"这个副作用面，也证明这一处结构整理**不改变行为**。
  * 钉法（`tests/test_quit_failopen.py`，4 档 + 只放行一次）：A 双链路抛仍退出且
    **恰好一个** exit 事件、B 用户取消不退出（正对照）、C 确认退出且恰好一个、
    D 富框抛 + 原生框答否不退出（证明 A 不是"只要富框抛就退出"）。
    `tests/test_quit_confirm.py` 从真 Tk 侧覆盖 Esc / 点「退出」；两者互不替代。

- **链路不可用时**不得沿用已保存的勾选去执行破坏性动作**（2026-09-19 lead 裁定，
  本仓照 dsh/ocx 形态改）。** 退出时是否**应用已下载的更新**（= 替换安装目录）由
  `quit_apply_update` 决定，它在 `main()` 的 finally 里被读（`src/main.py:1063`）。
  旧写法在"弹窗链路整个坏掉"时仍从配置读出用户**上次**的勾选——而那个勾选是他在
  **有确认框的语境**下保存的偏好；链路坏掉时**他这次根本没被问过**。于是"上次勾了
  退出时装更新"的用户，会由于一次坏掉的弹窗，在**没有任何确认**的情况下被装上更新。
  这正是整轮在打的形态：**辅助机制坏掉 ⇒ 触发破坏性动作**。
  * 修法：`choice is None` 分支直接 `self.quit_apply_update = False` 并 `return`，
    **不读配置**（dsh/ocx 末级硬编码 `False` 是标准形；"没问到"与"用户选了"必须分开）。
  * **一条我写强了、被测试当场纠正的断言**（留痕，因为它比断言本身有价值）：我先把
    "不读已存勾选"落成**毒药**——monkeypatch `load_config_dict` 成"一读就抛"，指望不可用
    分支仍得出 `False`。**它当场红了**，红得对：`_confirm_quit` 开头就
    `cfg = load_config_dict()` 一次，那是给对话框**播种勾选初值**（`checked`）用的，
    合法且必要——"完全不读配置"是**比设计更强**的性质，不是在钉设计。
    改成可观测且正确的形式：**读的次数**——播种恰好 **1** 次（若末级又去读就是 2），
    且那一次读**不决定结果**。两条断言现在都在。教训：**断言要钉设计保证的性质，
    不是钉"我能想到的最严的写法"**；写强了会误伤正确实现，而红得对正是它该有的反应。
  * 顺带：那次抛异常触发了 `tests/_cleanup.py` 的 atexit 兜底，打印
    `[LEAK-SWEPT] 测试未清理 1 个 scratch 根（多半中途抛异常）`——**兜底按设计工作**
    （不静默清理、把"这次没走到底"说出来），修好后正常路径无泄漏。
  * 先红后绿（同一文件、同一环境）：新增断言
    `A link unavailable -> does NOT apply the pending update` 在旧实现下 **FAIL
    （quit_apply_update=True）**，隔离配置里故意写 `{"quit_apply_update": true}`
    ——否则断言会因"读不到→默认"而失去判别力。改完 10/10 全绿。
  * 同时补**正对照** `C confirmed -> still honours the persisted checkbox`：用户**被问过**
    时仍然沿用他保存的勾选。少了这条，"一律不装更新"也能通过——那是从一个极端滑到
    另一个极端，等于把用户偏好整个作废。
  * 两条合起来才说明这个修正**有指向**：只改"没问到"的那一支，不动"问到了"的行为。

- **`modules/i18n` re-copied to 2.2.0** (template `6718118`, file-level declaration; the
  freeze was verified first: `git diff --stat 6718118 HEAD -- modules/i18n/
  modules/paths/README.md` is empty). `LANG` is now a **derived read** over the `_STATE`
  container instead of a module-level scalar, so the "menu stays Chinese while
  notifications switch to English" dead-copy is structurally impossible —
  `LANG in vars(package)` and `LANG in vars(submodule)` are both False. `modules/paths/README.md`
  came along in the same wave (it gained the `process_pending_update` deprecation notice).
  All four files are `[ok]` in `sync_check` and **C-23 turned green** — that check going
  from `LANG:27(标量)` to no finding is the mechanical proof this cascade worked.
- **Registered: `icons` is a build-time script, not an import package — an evaluated,
  accepted difference from the template's package form** (lead ruling; `sync_check`'s
  `[MISSING-FILE]` for `modules/icons/{__init__.py,README.md}` is a by-product of that
  form, not a gap). Evidence (tool `baefaa0` / template `188bbcc`):
  * `grep -rn "import icons\|from icons" src/` -> **zero hits**: nothing imports it.
  * `build.bat:175` runs it as a script (`"%PY%" src\icons.py`), and `build.bat:94`
    only lists it in `py_compile`. So it is a build-time generator, and
    `modules/icons/__init__.py` (`from .icons import *`) serves "import from inside the
    package" — a usage these tools do not have.
  * The code body is byte-identical: the **only** line that differs is line 2, the
    declaration header (`# TEMPLATE-FROM: ...` here vs `# TEMPLATE-MODULE: icons ...`
    in the template). Normalized hash (headers stripped) is equal on both sides:
    `4294a7a9ba8e86a8`.
  Converting `src/icons.py` into a package would change `build.bat`'s invocation path and
  the `py_compile` list — breaking the build for a pure form change. **Follow-up
  obligation** (user's rule): next round, tpl-keeper evaluates whether the template should
  drop the `icons` package facade, since no consumer imports it as a package.
- **`log_kit` re-copied to 1.0.3, plus `log_kit/README.md` and `tray_kit/README.md`
  (byte-exact)** — template `88ad3ea`. The freeze was verified *before* writing: the three
  paths are absent from `git status --porcelain` at that rev (worktree == HEAD), and their
  **byte hashes (sha256 over the raw bytes) matched the values recorded while the files were
  still uncommitted** (`da90958cf25c` / `d57d6ba24205` / `5893b97a2e5c`) — i.e. the commit
  captured exactly what had been inspected, nothing moved in between. (Wording correction,
  2026-09-19: an earlier revision of this entry called them "HEAD blob hashes". They are
  **not** git blob ids — those are `3d5d05886f03` / `8b623539a475` / `8bd3803da731` at the
  same rev. The recorded trio is the raw-byte sha256 set, and for the two `.md` files that
  coincides with `sync_check`'s `.md` normalization, since `.md` is compared byte-wise while
  `.py` is compared with `# TEMPLATE-*` lines stripped. Mixing the two families of hash is
  exactly how a "verified" claim can be true of the wrong object.) `sync_check` now reports
  `0 blueprint lag(s)` and `0 doc byte-diff(s)`; C-29 stays `[ok]` (this tool's
  `def log(*parts)` joins its arguments and forwards a single string, so it is correct
  against both 1.0.2's single-arg closure and 1.0.3's print form).
- **Fixed: the three declaration headers written during this cascade ended in a bare LF
  inside otherwise-CRLF files.** The `TEMPLATE-FROM` line is produced by the copy tooling
  with a `\n`, while every dispatched body is CRLF, so
  `src/modules/i18n/__init__.py`, `src/modules/i18n/i18n.py` and
  `src/modules/log_kit/log_kit.py` each ended up **mixed** (1 lone LF, 40/129/79 CRLF). It
  is precisely the class C-31 exists for, and it is invisible to every existing layer:
  `py_compile` is green, and `sync_check`'s `.py` comparison strips `# TEMPLATE-*` lines —
  i.e. it strips the very line that carries the defect. Caught only by reading the bytes
  back. All three header lines are now CRLF; verified: bare-LF count 0 on both sides for all
  five dispatched files, and each copy differs from template `88ad3ea` **only** in the
  declaration header line (identical after stripping it; the two `.md` copies are
  byte-identical outright). The remaining bare-LF files under `src/` are uniformly LF-only,
  not mixed (`icons.py`, `keyboard_hook.py`, `updater.py`, `wasapi_probe.py`, the exempt
  `appconfig.py`, and `autostart.py`, which is LF in the template too and therefore waits
  for the C-31 re-copyable wave).
- **The test scratch roots now survive a mid-test crash** (`tests/_cleanup.py`). Cleanup
  was a `check(..., rmtree_cleanup(_TMP))` line at the **end of each module** — so it ran
  only if the test reached the end. This repo already has the live example of the other
  path: a `TypeError` in the `check()` helper aborted two runs and left **4** scratch dirs
  behind (the whole point of the module is that this class must not be silent).
  `scratch_dir()` now registers every root it creates and an `atexit` backstop sweeps the
  leftovers — **printing `[LEAK-SWEPT] …` rather than cleaning quietly**, since a silent
  sweep is indistinguishable from "there was nothing to sweep" (same lesson as C-30's
  scan surface) and is morally the `rmtree(..., ignore_errors=True)` this module was
  written to kill. Proven, not asserted: a probe that writes a data root
  (`config.json` + `log/<app>.log`) and then raises prints the evidence line and leaves
  **0** residue; the `SWEPT` list is exposed so a test can assert no crash happened.
  Chosen over per-test `try/finally` because these tests are **module-level scripts** with
  no wrap point, and `atexit` covers a strict superset in-process (exceptions +
  `SystemExit` + normal exit); neither survives a hard kill, so nothing is given up.
- **The six remaining tests now pin their data root** (F11/D12, user's red line "the build must
  never affect the service"). `test_autostart_migrate`, `test_bench_core`, `test_bench_ui`,
  `test_help_ui`, `test_overlay_grow` and `test_quit_confirm` imported
  `main`/`modules`/`pipeline` **without** redirecting the data root, so import-time
  `seed_config()` and the benchmark/recognition `perf_log()` wrote into the **resident**
  `%LOCALAPPDATA%\local-speak2text\`. Measured, not inferred: a manual `test_bench_core` run
  moved the resident log's mtime to 17:16:54 (the full build that followed left it alone — GATE 3's
  pin held). All six now use the same shape as the four that were already correct:
  `scratch_dir()` plus `<APP>_DATA_DIR` / `_CONFIG` **before** the first src import,
  `assert rmtree_cleanup(_TMP)` at the end (a leak is **red**, not silent), and the hardcoded
  absolute `sys.path` is gone. Verified **without** launching Tk or touching the registry:
  * `py_compile` 6/6;
  * a mechanical check that the pin precedes the first `import main|modules|pipeline`
    (first src-import lines 17 / 20 / 16 / 16 / 16 / 26 — all after the pin);
  * a mechanism measurement: with the pin in place, `import pipeline` + `perf_log("f11-probe-line")`
    left the resident log's mtime **unchanged** (`1789809414.9633431` before and after) and wrote
    the line under the scratch root instead.
  The four GUI tests and the registry test are re-verified by the build gate, where they already run.
- **Fixed: the smoke diagnostic texts were outside the word table** (C-20). The two
  `RuntimeError` messages in `smoke()` were Chinese literals; they now go through
  `i18n.t("smoke_mutex_invalid")` / `i18n.t("smoke_model_dir_missing")` with both
  locales updated (80 -> 82 entries each).
- **Fixed: `log` was a single-argument wrapper while every template module calls it
  print-style** (C-29, template `log_kit` 1.0.3 contract). `tray_kit.MenuSignature`,
  `autostart.migrate_autostart` and the updater all do `log("update staged:", staged,
  "->", target)`, which raised `TypeError` **inside the template module's frame** —
  exactly where the tool-side `try` cannot swallow it. `main.log` is now
  `def log(*parts)`, joins with spaces and forwards one string, so it is correct
  against both 1.0.2 (single-arg closure) and 1.0.3 (print form). Pinned by two new
  assertions in `tests/test_startup_path.py` (a two-argument call must not raise, and
  the joined text must actually reach the log file).
- **`src/modules/appconfig/appconfig.py` now declares its origin**
  (`# TEMPLATE-FROM: ... | TEMPLATE-VER: 1.0.1`), clearing the last C-19 warning; the
  parameter file stays exempt from byte comparison by design.
- **The update-safety test no longer builds "target file is missing" scenarios** (lead
  ruling R1/R2/R4, after 15 modal WSH dialog boxes landed on the user's desktop).
  `start "" "<missing .vbs>"` pops a Windows Script Host modal exactly like `start` on a
  missing `.exe` — same modal, same permanent hang in a detached, console-less script.
  So the fake exe (`install/probe.vbs`) now **always exists**, "was it started" is judged
  by **side effects** (which marker file appears) and never by absence; the
  `:install_dead` path is now reached by breaking the *snapshot* (`_backup.pre` is a file,
  measured `robocopy` rc=16) instead of by emptying the target. Every bat run is timed and
  a timeout is a **red** assertion naming "疑似模态框", plus a best-effort kill of only the
  `wscript`/`cscript` processes whose command line references this run's scratch root (never
  by image name — that would kill the user's own scripts). `_stage(install_empty=...)` is gone.
- **GATE 3 pinned its data root, and now prints *why* it is green** (lead ruling 2026-09-19,
  F11/D12: the toolchain must not share any on-disk file with a resident instance — the
  user's rule is "what we dread most is the build affecting the service"). `build.bat` sets
  `LOCAL_SPEAK2TEXT_DATA_DIR=%CD%\build\selftest-data` around the selftest and removes it
  after; verified by mtime that the live `%LOCALAPPDATA%\local-speak2text\` was **not**
  touched, and the selftest log landed under `build/selftest-data/…/log/`.
  `pipeline.describe_model_resolution()` (read-only, mutates nothing) makes the reason for
  the green light visible, as a report + `[WARN]` — **never a FAIL**, because a stale config
  is user-side state, not a code defect. Three findings fell out of building it:
  * **The gate never consulted the config at all.** `selftest()` does not call
    `load_config()`, so `MODEL_DIR` is still the module default. Worse, that default is
    bound in `def __init__(self, model_dir=MODEL_DIR, …)` — evaluated at **function
    definition time**, i.e. an import-time snapshot — so `load_config()`'s later rebinding
    of `MODEL_DIR` does not reach `AsrEngine()` (five call sites construct it with no
    `model_dir`). In dev the two paths coincide, which is exactly why this stayed invisible.
    The report prints the engine's real directory **and** the resolved one separately and
    warns when they differ. **Not silently "fixed" here** — changing what the engine loads
    is a behaviour change that needs its own ruling.
  * **Pinning the data root also moves `CONFIG_PATH`** (it defaults to
    `USER_DATA_DIR/config.json`), and `pipeline.py:162` calls `seed_config()` at import —
    so the pinned run seeds a **factory** config whose `model_dir` is already the new
    `asr-modules/…`, hiding the user's stale path. Hence the report reads the **resident**
    config (`%LOCALAPPDATA%\<APP_ID>\config.json`) separately, read-only.
  * **The staleness is real and now visible**: the resident config's `model_dir` is
    `…\models\sensevoice-small-int8`, which no longer exists, so a running instance only
    finds its model through the upward fallback. That is the fact the `[WARN]` names.
- **GATE 3 could never go red — fixed with two assertions** (`pipeline.selftest()`), found
  while measuring timeout margins (template `conformance_check.py` 1.8.0 added C-30 for a
  different case; this was the same class — a gate that is always green is
  indistinguishable from no gate):
  * **The wait's return value was discarded.** `finish_ev.wait(timeout=60)` returns `False`
    on timeout and nobody looked, so "timed out" and "finished normally" were identical in
    the output. It now raises a distinct `自检超时…` — the two paths are told apart in the
    message, not just in the exit code.
  * **Nothing asserted on the recognized text** — the only assertion in the function was on
    the WAV format, so garbage output passed. It now requires non-empty text **and** at
    least 2 of the tokens `("欢迎", "达摩院", "语音")`. Those tokens were **measured**, not
    guessed: `sensevoice-small-int8`, `qwen3-asr-0.6B` and `fireredasr2-aed-int8` all produce
    `欢迎大家来体验达摩院推出的语音识别模型` for the shipped test wav, so the criterion
    tolerates the small drift between models while still failing on empty/hallucinated output.
    Whole-sentence equality was deliberately **not** used.
  * **Positive controls** (both branches really can fail): a 1-second silent WAV → `rc=1`
    with `自检失败：定稿文本为空…`; an unset `Event` → the old shape exits `0` while the new
    one raises. Verified `python src\pipeline.py` (exactly as `build.bat` GATE 3 runs it,
    no env pinning) returns `rc=0`, and a full `build.bat nopause norun` ends with `exit=0`.
- **Fixed: a failed marker deletion swallowed the upgrade-failure notice.** In
  `updater.pop_failed_update_note` the `marker.unlink()` sat inside the *same* `try` as
  `read_text()`, so an `OSError` from the delete (the marker briefly locked by
  Defender/the indexer — the same transient lock this repo already measured) took the
  `except` branch and returned `""`: the detail had been read successfully, yet the user
  never saw the "last update failed" notice, purely because *deleting the evidence*
  failed. Now the order is **build the note -> report -> delete last, in its own `try`**;
  if the delete fails the marker stays and the notice repeats next launch. Pinned by a
  regression that locks the marker with `FILE_SHARE_READ|WRITE` but **not**
  `FILE_SHARE_DELETE` (so it can be read but not deleted) and asserts the note is still
  returned and the evidence kept; the old code returns `""` under that same injection
  (positive control run separately).
- **Two "branches that exist but were never covered" are now exercised** (reviewer's method,
  2026-09-19: *branch present != branch covered* — their own write-back fallback never ran in
  35 live attempts because every delete raised `PermissionError`). End-to-end triggering would
  require the R1-forbidden shape (a missing target / a real hang), so these are **unit-level
  controls**: call the function directly with constructed inputs — no bat, no `start`.
  * The read-only self-proof is now `_readonly_selfproof(path)`; a control runs it on a
    **writable** file and asserts it returns `False` **and rewrites the target** (R1 invariant
    kept even when the protection is absent) — the branch that never executed in any live run.
  * `_check_no_hang`'s red path is exercised by swapping the module's `check` for a recorder and
    feeding `timed_out=True` (and an over-limit `elapsed`): both must register a **failure**,
    including the "疑似模态框" wording. Live runs can never reach it (a real hang would have to
    occur first).
- **Comment corrected in `test_update_safety.py`**: the read-only bit is a **partial** safeguard,
  not a structural guarantee — *"read-only makes the modal box impossible at the filesystem
  level" was an early misstatement (the lead has corrected it too; the reviewer had copied it
  into their harness docstring)*. The measured table now lives next to `os.chmod(...)`: blocked
  (`del`/`os.remove`/`rmtree` → `PermissionError`), **not** blocked (`rmdir /s /q <parent>` →
  rc=0; `robocopy /e /purge` → rc=3, content overwritten and the `R` bit cleared), and the
  positioning (an extra layer on top of R1 + the three `start` guards + the R4 timeout).
- **The fake exe in the update test is now read-only** (lead hardening order): `del <file>`,
  `os.unlink` and Python `shutil.rmtree` can no longer remove it, so no step can quietly
  lose the `start` target. A **self-proof assertion** runs inside the test window (deleting
  it must raise `PermissionError`) and immediately rewrites the file if the protection is
  not in effect — the test never proceeds with a missing `start` target. Cleanup clears the
  read-only bit first (`_cleanup.clear_readonly`, recursive), because the attribute is
  **copied by robocopy into the snapshot/backup dirs** and would otherwise make the next
  scenario's reset fail silently.
  **Measured boundaries — this is not a universal guarantee**: `rmdir /s /q <parent>` and
  `robocopy /e /purge` are **not** blocked by the read-only bit (measured: rmdir rc=0 and the
  directory is gone; robocopy rc=3, target overwritten, `R` bit cleared). What actually makes
  the modal box impossible stays R1 (stand-in always present) + the three `start` existence
  guards (pinned by C-26) + the R4 timeout; read-only is one extra layer on top.
- **Per-branch structural assertions on the rendered apply script** (lead ruling, replacing
  the `attrib +R` idea for this test — the read-only bit has no causal role here because the
  test waits for the marker before cleaning up, so there is no cleanup/`start` race to lose).
  Every branch is now pinned to its designed number of `start ""` sites and any deviation is
  red: `:gone` 1, `:install_failed` 1, `:stage_invalid` 0, `:install_dead` 0,
  `:start_missing` 0, `:giveup` 0. **Note the shape difference from the template**: two of
  the four branches the ruling named (`:install_dead`, `:start_missing`) contain **no `start`
  at all** — this tool refuses to launch anything on those paths, which is stronger than
  guarding a `start`. Those two branches are additionally asserted to say so explicitly
  (`RESTORE FAILED` / `NEW EXE MISSING`), so "no start" can never be confused with "the start
  was forgotten". Before this, only `:start_missing` had an assertion — the other branches
  could have been broken silently.
- Added the **C-26 structural half** to the same test: the rendered script has exactly two
  `start ""` sites and both must be guarded — one by the inline `if exist … start`, one by the
  immediately preceding `if not exist … goto start_missing`. The runtime scenarios only prove
  "no hang while the guard happens to be there"; this pins that the guard **is** there, and the
  two halves fail independently.
- Test scratch roots moved out of `%TEMP%` into `H:\Tools\_verify-scratch\` (R2), via
  `_cleanup.scratch_dir()`; `LS2T_SCRATCH_DIR` overrides it. Both locations are asserted
  empty after each run.
- `tests/_cleanup.py` also hardens stdout (`errors="replace"`): the apply script redirects
  `robocopy` output into the log, and robocopy prints **GBK**-encoded localized errors on a
  Chinese Windows. Reading that as UTF-8 yields `U+FFFD`, and printing it to a GBK console
  raised `UnicodeEncodeError` — the assertion failure turned into a crash *while printing*,
  so later cases and all cleanup were skipped.
- **Fixed: test temp dirs leaked into `%TEMP%`** (9 stale `l-s2t-*` dirs found, all
  containing `<TMP>/<app>/log/<app>.log`). Two causes: the `RotatingFileHandler` holds
  the log file open (Windows denies deleting an open file — Python's `open()` does not
  pass `FILE_SHARE_DELETE`) and a freshly written `config.json` is briefly locked by
  Defender/the indexer. `shutil.rmtree(..., ignore_errors=True)` turned both into
  "looks successful". New `tests/_cleanup.py` closes the logging handlers, retries, and
  **returns False unless the directory is really gone**; all four suites now assert it,
  so a future leak turns the gate red instead of silently accumulating.
- **Measured defect (not yet fixed, template-level): the apply script's "1 second" sleep
  is not 1 second.** The wait loop paces itself with `ping -n 2 127.0.0.1 >nul`, which
  assumes one iteration ~= 1 s, so `UPDATE_WAIT_LIMIT = 120` is documented as "aborted:
  ... still running after 120s". On this machine one iteration measures **8.5-9.0 s**
  (`ping` to loopback itself times out: 2 packets sent, 2 lost, 8.96 s wall), making the
  real ceiling ~18 minutes and the give-up message wrong by ~9x. The same idiom is in
  the template's `_APPLY_BAT` (and therefore in the other four tools), so the fix
  belongs in the template, not in a local override.
- **Mechanism code now converges on the family template** (`my-diy-tool-template`
  modules, byte-identical copies): `icons` 2.0.0, `log_kit` 1.0.2, `paths` 1.1.2,
  `autostart` 1.1.1, `tray_kit` 2.0.1, plus the `appconfig` parameter file.
  `src/modules/` is now the home of shared mechanism; `main.py` keeps only
  tool-specific logic.
- `VERSION` moved to `src/modules/appconfig/appconfig.py` (still the single
  source of truth; `build.bat` / `release.bat` / `release.yml` read it there).
- **Fixed (GUI-verified): Esc did not close the quit confirmation dialog.**
  The quit dialog is now `tray_kit.confirm_quit_dialog`, which binds
  `<Escape>` to cancel; `tests/test_quit_confirm.py` presses Esc to pin it.
  Unconfirmed quits are impossible: rich dialog -> native `askyesno` ->
  proceed, never skipping confirmation.
- Tray menu rebuilds go through `tray_kit.MenuSignature` with a menu-open
  probe, so a rebuild can no longer yank an open right-click menu away.
- **Fixed: switching language did not refresh the tray menu** (user-reported).
  `main.py` read the package-level `i18n.LANG`, which the old `from .i18n import *`
  had copied into the package namespace — the value stayed `zh`, the menu
  signature never changed, and the menu stayed Chinese while notifications
  switched to English. Now reads `i18n.current_lang()` (template i18n 2.1.1,
  which no longer copies mutable state); pinned by `tests/test_i18n_menu.py`
  and `build.bat` GATE 2c.
- **Update chain hardened to reme-verified semantics** (three same-family defects):
  * **sha256 is now fail-closed** — `download_update` aborts when the `.sha256`
    asset is missing or does not match; the old `except FileNotFoundError: skip
    verify` silently downgraded the only integrity check.
  * **The apply script no longer guesses.** It waits for the old process to
    actually exit (`tasklist` to a file + `find`, never a pipe — the script runs
    detached with no console, where `tasklist | find` blocks forever) with a wait
    limit; it snapshots the current install **before** copying and only rotates
    that snapshot to `_backup` after a copy that succeeded; it checks the
    `robocopy` exit code (>=8 = failure) and then **never starts the new exe** —
    it restores from the snapshot and starts the previous version, or starts
    nothing and keeps the snapshot if the restore also fails; failures write an
    `update.failed` marker that the next launch reads once and surfaces to the
    user (`pop_failed_update_note`).
  * **`process_pending_update` no longer destroys evidence** — it parses the
    `robocopy` return code and, on failure, keeps `update.pending.json`, the
    staged files and writes the marker; the `os.system` string interpolation is
    replaced by `subprocess.run([...])`. It now lives in `updater.py` (the
    template's copy in `modules/paths` is left byte-identical and unused, pending
    the template fix).
  * Fixed the staged-dir detection: our `release.yml` zips the package **flat**,
    so `UPDATE_DIR/<APP_ID>` never existed and `prepare_update_cmd` would have
    raised "staged exe missing" — the auto-update had never been run end to end.
  * **An empty stage is intercepted before anything is touched.** `robocopy` from a
    stage with no payload returns rc 0–7 ("nothing copied, no error"), so the old
    code would call it success after `/purge` had already wiped the install dir —
    and the following `start` on the now-missing exe pops a modal box in a
    detached, console-less script (hangs forever). Now: no staged exe → don't
    touch the install dir, write the marker, keep the staged files.
  * **"copy succeeded but no exe in target" is a failure too** (narrow remainder of
    the same path): it now goes to `:start_missing` — writes the marker and keeps
    WORK and BACKUP — instead of logging and falling through to `:cleanup`, which
    deleted the staged files and the pending marker and left a dead install.
  * **The apply script is launched without a console.** The exit path used
    `os.system('start "" /min ...')`, which goes through `cmd` and flashes a
    console window on the desktop. It now uses `launch_pending_cmd()` —
    `CREATE_NO_WINDOW | DETACHED_PROCESS`, the reme form — so the script
    outlives the parent without any visible window. If the launch fails the app
    logs it and notifies the user (the pending file stays, so the next start
    retries) instead of exiting silently.
    `tests/test_startup_path.py` now drives a **real exit flow** with a pending
    update staged and asserts the script was actually launched (marker file),
    on top of the flag assertions in `test_update_safety.py`.
  * New `tests/test_update_safety.py` (build.bat **GATE 2d**): the rendered
    `.bat` is really executed for both success and a failure injection
    (`robocopy` rc=16), asserting "failure starts the old version, never the new
    one, writes the marker and keeps the snapshot"; plus sha256 fail-closed and
    pending-evidence retention. The bat runs with `CREATE_NO_WINDOW` and a `.vbs`
    fake exe so it cannot pop a console window on the user's desktop.
- **Single-instance guard/probe converge on template `tray_kit` 2.2.0.** The
  inline `mutex_name_is_valid()` in `main.py` is deleted (no second definition);
  `--smoke` now calls `tray_kit.mutex_name_is_valid(APP_ID, mutex_name=MUTEX_NAME)`,
  which shares one naming criterion (`mutex_name_ok`) with the guard. The guard
  now fails **open** on an illegal name (logs it) instead of treating a
  `CreateMutexW` failure as "already running" — turning that programming error
  red is the build-time probe's job. `tests/test_single_instance.py` keeps the
  semantics with two assertions: guard passes + logs, probe says invalid.
- **New `--quit`**: asks a running instance to exit without the confirm
  dialog (request file lives under the redirectable data dir).
- Icon graphics are single-sourced from `appconfig.ICON_DRAW` (runtime tray
  and build-time `.ico` share one drawing function).
- `paths.py` carries **no override** any more: template 1.1.3 implements the
  `<APP>_CONFIG` env pin, and the env-var prefix is now the standard
  `APP_ID.upper().replace('-','_')` derivation. The two environment variables
  are therefore `LOCAL_SPEAK2TEXT_CONFIG` / `LOCAL_SPEAK2TEXT_DATA_DIR`
  (previously written without the underscore — a one-off name that is now
  retired, CONFORMANCE NAME-10).
- **Fixed: the exe could not start at all since 1.2.0.** The single-instance
  mutex was named `Local\<app>\SingleInstance`; a named kernel object may not
  contain a second backslash after the `Local\` namespace prefix, so
  `CreateMutexW` always failed with err=3 (`ERROR_PATH_NOT_FOUND`). The guard
  treated a null handle as "another instance is running", so every launch
  showed the "already running" box and exited. Renamed to the family-standard
  `Local\<app>-single-instance`.
- **Guard now fails open.** When the guard itself cannot run, the app continues
  instead of refusing to start (STANDARDS D3.2). Only a confirmed
  `ERROR_ALREADY_EXISTS` cancels the launch. Both directions are now asserted
  by `tests/test_single_instance.py`.
- Last-error is cleared before `CreateMutexW` so a stale 183 cannot be
  misread as "already exists"; the duplicate path is logged instead of being
  silent.
- **New `tests/test_startup_path.py`**: runs the real `main()` with UI/model
  stubs, asserting the startup sequence is actually reached — `--smoke`
  bypasses the guard, which is why this defect survived three months of green
  builds. Both suites are now gates in `build.bat` (GATE 2b).
- **Instance isolation**: `LOCAL_SPEAK2TEXT_DATA_DIR` redirects the whole
  data root (F11/D12, template `modules/paths`), so tests and build scripts
  no longer share config/log with a running tray instance.

## 1.4.0

- Model resources renamed: `models/` -> `asr-modules/` (auto-migrated once on
  first launch; keeps downloaded models intact).
- Default model is now SenseVoice-Small (int8) - lighter and faster RTF than
  the 0.6B default; Qwen3 remains selectable via "Choose model folder".
- Docs and locale strings updated to the new paths.

## 1.3.1

- Internal structure only: i18n moved into `modules/i18n.py` (family template
  layout, data-driven tables unchanged); imports updated. No behavior change.

## 1.3.0

- i18n v2: translation tables moved out of code into data files
  (`locales/zh.json` + `locales/en.json`, 74 entries each) - adding entries no
  longer touches code; mechanism aligned with the family template
  (my-diy-tool-template/modules/i18n). No user-visible behavior change.
- Build packages now bundle the locales folder.

## 1.2.0

- Single instance: a named mutex prevents a second tray instance from grabbing
  the keyboard hook and the audio device; a message box points to the running
  instance. Set `LST_ALLOW_MULTI=1` to bypass for tests.
- Rotating run log at `%LOCALAPPDATA%\local-speak2text\log\local-speak2text.log`
  (1 MB × 3 backups, reme-helper style) recording startup, model load, crashes
  and exit; new tray item "打开日志目录 / Open log folder".
- Tray menu restructured to the house standard (read-only info header on top,
  updates, business, open, preferences, quit last); "Guide..." is now the
  double-click default action.
- Fix: the updater referenced an undefined `APP_ID_PKG`, so downloading an
  update crashed with NameError before any file was written (regression from
  1.1.0's updater).

## 1.1.3

- Stable install location: in-place updates now install into
  `%LOCALAPPDATA%\local-speak2text\app\` and launch from there, so the
  autostart registry entry never goes stale across version updates.
- Autostart self-heal: on startup, if the registry entry points at an exe
  that no longer exists (old timestamped packages), it is rewritten to the
  current location.
- Quit confirmation: the tray "Quit" now asks before exiting (bilingual);
  cancel or closing the dialog keeps the app running.
- CI: release workflow now also fetches the test wav so the pipeline-selftest
  gate passes on clean runners (fixes the first v1.1.2 tag attempt).

## 1.1.2

- Bilingual README: `README.md` (English, canonical) + `README.zh-CN.md`
  (Chinese), each linking to the other at the top - same shape as reme-helper.

## 1.1.1

- Tray Help dialog: usage, how to add models (per-type file requirements),
  where config/logs live - all bilingual.
- "Copy model-setup instructions (for an AI assistant)": copies a ready-made
  prompt (per-type file checklist, sherpa-onnx releases link, CPU-suitability
  caveat) so an AI assistant can fetch and install a model end-to-end.
- "Benchmark models": real recognition speed test for every model under
  models\ - load time, short-clip and long-clip RTF, usability verdict,
  recommendation, and plain-language metric notes. The progress window can be
  closed; results pop up automatically when the run finishes.
- Shipped config defaults to SenseVoice and sets update_repo to the GitHub
  repo, enabling the update check out of the box.
- Model enumeration now validates required files per type (an incomplete
  folder is no longer mistaken for the default qwen3 type).
- CI: add requirements.txt (setup-python pip cache requires it).

## 1.1.0

- Multi-model auto-detection: Qwen3 / SenseVoice / FireRedASR / Paraformer
  model folders are identified by file layout; switch from the tray menu.
- SenseVoice-Small int8 benchmark: RTF 0.026 on the dev machine, ~7.5x faster
  than Qwen3-0.6B with identical output plus built-in punctuation.
- Overlay window grows upward with content (bottom-anchored, max 12 lines,
  internal scrolling keeps the latest text visible).
- Recognition queue: final results preempt partial previews; stale partials
  are dropped before decoding (no wasted duplicate decode on finish).
- Perf log: every recognition appends model/audio duration/RTF/text to
  %LOCALAPPDATA%\local-speak2text\log\local-speak2text.log.
- i18n: Chinese/English UI, tray menu toggle, persisted in config.
- Config and logs moved to %LOCALAPPDATA%\local-speak2text\ (one-time
  migration from the exe-side config.json).
- Update check + self-update via GitHub Releases (zip + sha256, applied on
  quit by a one-shot robocopy swap).
- Code-generated icons (microphone, blue=idle / orange=recording): tray icon
  plus a high-DPI taskbar .ico; the exe itself carries the icon.
- Build rewritten: version single-sourced from paths.py, gate tests
  (compile / i18n / pipeline selftest), deliverable checks, frozen smoke test.
- CI: tests.yml on every push/PR; release.yml builds and publishes the zip on
  v* tags; release.bat tags from a clean, pushed main branch only.

## 1.0.0

- First packaged release as qwen-dictate: hold Right-Ctrl to dictate,
  Ctrl+Space for continuous mode, local Qwen3-ASR-0.6B int8 via sherpa-onnx.
