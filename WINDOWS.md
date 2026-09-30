# CareArk Windows 版

适用于 Windows 10/11（64 位）。从 [Releases](https://github.com/crazyykhllc-bit/CareArk/releases) 下载最新版 Windows ZIP，**完整解压**后双击其中的 `CareArk.exe`。这个版本不需要安装 Docker、PostgreSQL、MinIO 或 Python。程序会在本机启动工作台并打开浏览器；首次使用请在网页中创建管理员账号。关闭 CareArk 启动窗口即停止本机服务。

数据库和原件不会装在 ZIP 或 EXE 中，也不会随着更新被覆盖。首次启动时，程序会在 `%LOCALAPPDATA%\CareArk` 建立一个**空档案**：`careark.db` 是 SQLite 数据库，`originals` 存放上传的原件，`.env` 存放视觉模型设置。可在启动窗口点击“数据目录”打开这个文件夹。

也可以打开普通 PowerShell 窗口，用一行命令自动下载、校验和解压，并创建桌面快捷方式，无需 Setup 或管理员权限：

```powershell
& ([scriptblock]::Create((Invoke-RestMethod 'https://raw.githubusercontent.com/crazyykhllc-bit/CareArk/main/scripts/install-windows.ps1')))
```

程序放在 `%LOCALAPPDATA%\Programs\CareArk\versions\<版本号>`，资料仍保存在上面的数据目录。命令不会自动启动程序，安装后双击桌面的 CareArk。关闭旧程序后再次执行命令可更新快捷方式到最新版；旧程序目录保留，资料和模型设置不会被安装脚本修改。只想下载 ZIP 的用户可以继续按第一段操作。

脚本支持 `-Version v0.1.2` 指定已有的稳定版本、`-InstallRoot` 指定程序目录和 `-NoShortcut` 跳过快捷方式。使用这些参数时，可先下载 [install-windows.ps1](https://github.com/crazyykhllc-bit/CareArk/blob/main/scripts/install-windows.ps1) 并在 PowerShell 执行。移除程序时可删除对应版本目录及桌面快捷方式；不要删除 `%LOCALAPPDATA%\CareArk`，除非明确要删除档案。

需要识别图片或扫描件时，点击“模型设置”，在 `.env` 的 `MODEL_API_KEY=` 后填写支持图片输入的模型密钥，保存后刷新工作台网页即可生效。默认示例使用 DeepSeek；也可以同时修改 `MODEL_BASE_URL` 和 `MODEL_NAME` 来使用其他兼容服务。在线视觉识别会把待识别内容发送给所配置的模型服务商；没有密钥仍可打开工作台，但不能识别新资料。

**备份和更新：**先关闭 CareArk，再复制整个 `%LOCALAPPDATA%\CareArk` 文件夹，包含数据库、原件和设置。更新程序时解压新版 ZIP 并运行新的 EXE；数据目录仍是同一个。不要把数据目录、`.env` 或含真实资料的备份上传到 GitHub。

如果程序无法启动，可在数据目录查看 `careark.log`。这个 Windows 包是本机单用户部署方式，不应直接开放到局域网或公网。
