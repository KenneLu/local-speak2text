# local-speak2text

[English](README.md) | **简体中文**

Windows 上的本地离线语音转文字听写工具：按住热键说话，松手文字就落在光标处。多引擎 ASR（Qwen3 / SenseVoice / FireRedASR / Paraformer）自动识别，全程本机运行。

一个小巧的 Windows 托盘工具：按住**右 Ctrl** 说话——浮窗里实时出字，松手后文字自动键入你正在用的窗口。**Ctrl+空格** 切换持续模式。语音不离开本机。

## 安装

1. 从 [Releases](../../releases) 下载 `local-speak2text-<版本>-windows-x64.zip`，解压到任意目录。
2. 下载一个 ASR 模型（见[模型](#模型)），放到 `asr-modules\` 文件夹——或者用你自己的模型。默认加载 SenseVoice-Small（int8）。
3. 运行 `local-speak2text.exe`，它在托盘常驻。

## 热键

| 按键 | 行为 |
|---|---|
| 按住右 Ctrl | 浮窗出现，说话实时出字；松手后文字键入当前窗口 |
| Ctrl+空格 | 切换持续模式：一直说话一直出字；再按一次结束并键入 |
| Esc | 取消本次内容（不键入） |

托盘菜单（右键图标）：开机自启、自动增益、**选择模型目录**、**Language 语言**（中英切换）、**帮助**、**复制添加模型方式（交给 AI 执行）**、**检测模型性能**、检查更新/立即更新、退出。

## 模型

把模型文件夹放进 `asr-modules\` 下——按目录内文件布局自动识别类型，无需改配置：

| 目录内文件 | 识别为 |
|---|---|
| `conv_frontend.onnx` + `encoder*.onnx` + `tokenizer/` | Qwen3-ASR |
| `model.int8.onnx` + `tokens.txt` | SenseVoice / Paraformer |
| `encoder.int8.onnx` + `decoder.int8.onnx` + `tokens.txt` | FireRedASR |

现成的 int8 包：[sherpa-onnx releases](https://github.com/k2-fsa/sherpa-onnx/releases/tag/asr-models)。或者点托盘里的**复制添加模型方式（交给 AI 执行）**，把提示词交给 AI 助手代办——里面含各类型文件核对清单和下载地址。

托盘里的**检测模型性能**会对 `models\` 下每个模型做真实识别测速，输出各模型 RTF、通俗结论和推荐。

开发机实测（16.6 秒音频，纯 CPU）：

| 模型 | 解码耗时 | RTF | 结论 |
|---|---|---|---|
| SenseVoice-Small int8 | **0.43s** | **0.026** | 默认之选，自带标点 |
| Qwen3-ASR-0.6B int8 | 3.23s | 0.194 | 基准 |
| FireRedASR2-AED int8 | 27.66s | 1.662 | CPU 上太慢（更准，但本机不可用） |

RTF（实时率）= 处理耗时 ÷ 音频时长。低于 1.0 表示跟得上说话速度，越小越快。

## 配置与数据

工具写入的一切都在 `%LOCALAPPDATA%\local-speak2text\`，不在解压目录里：

```text
config.json    设置（模型目录、语言、热键调优）
log\           应用日志，每次识别追加一行性能记录（模型、音频秒数、解码耗时、RTF、文本）
crash.log      万一崩溃，未捕获异常落在这里
```

常用配置：`language`（`zh` / `en` / `auto`）、`update_repo`（`用户名/仓库名`，填了才启用更新检查）、`num_threads`（ONNX 线程数——实测 16 线程 CPU 上 8 最快）、`model_dir`。测试/便携模式可用环境变量 `LOCAL_SPEAK2TEXT_CONFIG` 指定配置文件；`LOCAL_SPEAK2TEXT_DATA_DIR` 重定向整个数据根（测试/CI 必须用它，绝不能与常驻托盘实例共享任何落盘文件）。

## 更新

托盘菜单里的**检查更新**。新版本下载时带 SHA-256 校验，退出托盘时原地替换应用；你的配置在 `%LOCALAPPDATA%`，更新全程不动。

## 常见问题

- **提示"无法打开麦克风"**：麦克风被其他程序占用（远程桌面工具常这样）。关掉占用程序再试。
- **文字没进去**：键入走"剪贴板 + Ctrl+V"；个别应用（游戏、管理员权限窗口）会拦截粘贴。
- **闪退 / 托盘没出现**：看 `%LOCALAPPDATA%\local-speak2text\crash.log` 和 `log\`。

## 开发

```bat
build.bat            :: 门禁（编译、i18n、流水线自测）+ 图标 + 打包 + 冻结冒烟，完成后启动
build.bat norun nopause  :: 无人值守，CI 用
release.bat          :: 打 v版本 tag 并推送；CI 构建并发布 zip
```

版本号在 `src/modules/appconfig/appconfig.py`（`VERSION`）——应用、发布目录、git tag 的单一事实源；推 `v*` tag 即触发发版。共用机制件在 `src/modules/`（模板拷贝：`appconfig`、`paths`、`log_kit`、`i18n`、`autostart`、`tray_kit`），工具自身逻辑留在 `src/main.py` / `pipeline.py`。`local-speak2text.exe --quit` 可让运行中的实例退出（不弹确认框）。图标由代码生成（`icons.py`），无需美术素材。界面中英双语（`i18n.py`）。变更记录见 [CHANGELOG.md](CHANGELOG.md)。

## 许可

[MIT](LICENSE) © 2026 KenneLu
