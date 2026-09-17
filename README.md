# local-speak2text —— 本地离线语音转文字小工具

Windows 10 上的本地离线语音输入小工具：按住右 Ctrl 说话出字，松手把文字键入当前窗口；或左 Ctrl+空格 进入持续模式，一直说话一直出字。全程离线，语音不离开本机。

English: a tiny Windows tray tool that turns your voice into typed text locally and offline. Hold Right-Ctrl and speak; on release the text is pasted at your cursor. UI is Chinese/English (switch in the tray menu).

## 运行

```powershell
H:\Tools\Python\Python313\python.exe main.py
```

首次启动会加载模型（约 4 秒）。启动后：

| 按键 | 行为 |
|---|---|
| 按住右 Ctrl | 出现浮窗，说话实时出字；松手后把文字键入当前窗口并隐藏浮窗 |
| 左 Ctrl+空格 | 切换持续模式：一直说话一直出字，再次 Ctrl+空格 结束并键入 |
| Esc | 持续模式下取消本次内容（不键入） |

托盘菜单（右键托盘图标）：开机自启、自动增益、选择模型目录、**Language 语言**（中英切换）、**检查更新 / 立即更新**、退出。

## 配置与用户数据

配置和日志在 `%LOCALAPPDATA%\local-speak2text\`（`config.json` + `log\`），exe 目录保持干净、原地更新无需迁移。旧版 exe 旁的 config.json 会在首次运行时自动迁移。测试/便携模式可用环境变量 `LOCALSPEAK2TEXT_CONFIG` 指定配置文件位置。

## 目录结构

```
local-speak2text/
  main.py            主程序（热键 + 浮窗 + 键入 + 托盘 + 更新）
  pipeline.py        识别流水线（录音缓冲 + VAD 断句 + 实时识别 + 多模型分发）
  paths.py           路径与版本单一事实源（VERSION 在这里改）
  i18n.py            中英文案表（t() 取词）
  icons.py           图标代码生成（托盘 + 高 DPI 任务栏 ico）
  updater.py         GitHub Releases 升级检查与自动升级
  keyboard_hook.py   自写的 Windows 低级键盘钩子（热键按下/松开/吞掉）
  models/qwen3-asr-0.6B/  模型文件（约 980MB）
  models/sensevoice-small-int8/  SenseVoice-Small int8（228MB，更快，自带标点）
  tools/            按键注入测试脚本、基准脚本（开发用）
  test_overlay_grow.py    浮窗自动生长测试（无副作用，不键入文字）
  .github/workflows/      CI（tests.yml 全分支测试 / release.yml 打 tag 发布）
```

调试日志：设置环境变量 `LST_DEBUG=1` 再启动，可在控制台看到热键和识别事件。

浮窗会随内容自动增高（底部锚定向上生长，最多 12 行，超出后在浮窗内部滚动并始终显示最新文字），不会超出屏幕。

## 配置（config.json）

| 配置项 | 默认值 | 说明 |
|---|---|---|
| auto_gain | true | 自动音量增益：识别前检测低音量音频并放大到正常水平（最大 20 倍，防削波）。设成 false 可关闭 |
| vad_floor | 0.005 | VAD 判断“有声”的绝对音量下限。越低越容易捕获轻声（也更容易把环境噪声当说话），0.010 是更保守的原值 |
| segment_padding | 0.15 | 断句边界前后各多保留的秒数，防止开头/结尾的轻声辅音被切掉（“吞音”） |
| num_threads | 8 | ONNX 解码线程数。实测过多线程数（4/6/8/10/16）：8 在本机（16 逻辑核）最快，16 反而最慢（线程争抢）；换机器后可用 `tools\bench_threads.py` 重新扫描 |
| language | auto | 界面语言：zh / en / auto（跟随 Windows）。托盘菜单可直接切换 |
| update_repo | 空 | 升级检查源，如 `YourName/local-speak2text`。填了才启用「检查更新」 |

修改后重启 `main.py` 生效。

## 打包与发布

```text
build.bat            构建（门禁测试 + 图标 + PyInstaller + 冻结冒烟），完成后启动
build.bat norun nopause   同上但不启动、不暂停（CI 用）
release.bat          打 v版本 tag 并推送，触发 CI 构建并发布 GitHub Release
```

版本号只写在 `paths.py` 的 `VERSION`；发布文件夹/zip 带版本号，exe 不带（开机自启注册表存的是 exe 完整路径）。图标由 `icons.py` 用代码生成，无需美术素材。

发布包结构：

```text
out\local-speak2text-pkg-<YYYYMMDD-HHmmssfff>\local-speak2text-1.0.exe
```

托盘中的“开机自启”和“自动增益”使用固定菜单名称，当前状态通过 `√` 勾选标记表示。模型仍保存在源码目录的 `models\qwen3-asr-0.6B`，发布包中的 `config.json` 会自动使用相对路径指向该模型目录。每次构建在 `out` 下新增一个 `local-speak2text-pkg-*` 目录，历史包保留在 `out` 中。

## 常见问题

- **浮窗提示"无法打开麦克风"**：麦克风正被其他程序占用（如 ToDesk 等远程软件的麦克风转发），关掉占用程序再试。
- **文字没进去**：文字通过"剪贴板 + Ctrl+V"键入。个别软件（游戏、受保护的窗口）会拦截粘贴，这类场景暂时无解，后续可加模拟按键模式。
- **识别不准**：模型对标准普通话准确率较高；人名、地名、中英混读仍可能出错（后续版本会加热词和纠错记忆）。
- **想改按键**：目前写死在 main.py 顶部（HOLD_KEY / TOGGLE_KEY）。

## 模型切换

托盘右键「选择模型目录...」即可切换模型，**目录类型自动识别**，无需改代码：

| 目录内文件 | 识别为 | 加载器 |
|---|---|---|
| conv_frontend.onnx + encoder*.onnx + tokenizer/ | qwen3_asr | from_qwen3_asr |
| model.int8.onnx + tokens.txt（含 use_itn 标点） | sense_voice | from_sense_voice |
| encoder.int8.onnx + decoder.int8.onnx + tokens.txt | fire_red_asr | from_fire_red_asr |
| model.int8.onnx / model.onnx + tokens.txt（无 itn） | paraformer | from_paraformer |

托盘提示会显示当前模型类型，如「就绪 [sense_voice]」。

## 性能说明

- 识别引擎为 Qwen3-ASR-0.6B int8（ONNX，CPU），实测本机 16.6 秒音频解码约 3.3 秒（RTF≈0.20）。
- 慢的根源是自回归 LLM 解码器（decoder int8 约 720MB，逐 token 生成）。想显著提速需换非自回归模型（见下）。
- 松手出字延迟已优化：结束时会自动丢弃过期的实时预览任务，最终结果优先解码，不重复计算。

### 更快/更准的替代模型（sherpa-onnx 官方预编译 int8 包，换 loader + 模型目录即可）

### 本机三模型实测（2026-09-17，16.6s 测试音频，同机对比）

| 模型 | 解码耗时 | RTF | 识别结果 |
|---|---|---|---|
| SenseVoice-Small int8 | **0.43s** | **0.026** | 与 Qwen3 一致 + 标点 |
| Qwen3-ASR-0.6B int8 | 3.23s | 0.194 | 基准 |
| FireRedASR2-AED int8 | 27.66s | 1.662 | 一致（无标点）但速度不可用 |

运行时性能日志：每次识别会在 `local-speak2text.log`（exe/源码同目录）记录一行 `模型类型 音频时长 解码耗时 RTF 字数 文本`，可直接对比实际使用中的速度与输出。

SenseVoice 快 **7.5 倍**（非自回归架构，不逐 token 生成），已随工程内置 `models\sensevoice-small-int8`，托盘切换即用。

| 目标 | 模型 | 说明 |
|---|---|---|
| 更快（不降准确率，带标点）✅ 已内置 | SenseVoice-Small int8 | 本机实测 RTF 0.026，自带标点+数字归一化 |
| ~~更准~~ ❌ 本机实测否决 | FireRedASR2-AED int8（约 1.2GB） | 官方 CER 3.05% 确实更准，但本机实测 RTF 1.66~1.87（比实时还慢），弱机上不可用；模型留在 models\fireredasr2-aed-int8 供体验，不用可删 |
| 留在 Qwen 生态升级 | Qwen3-ASR-1.7B int8 | 你机器上已实测打不动，不推荐 |

注：FireRedASR2 社区文档 RTF 0.33 来自服务器级 CPU；弱机实测差距巨大，换模型务必本机实测。

## 后续计划

- 打包成单文件 exe + 开机自启（注册表 Run，免管理员）
- 热词库 / 纠错记忆（纠正一次，下次自动替换）
- 可配置按键、浮窗位置、粘贴方式
