# CareArk Windows 版

适用于 Windows 10/11（64 位）。从 [Releases](https://github.com/crazyykhllc-bit/CareArk/releases) 下载最新版 Windows ZIP，**完整解压**后双击其中的 `CareArk.exe`。这个版本不需要安装 Docker、PostgreSQL、MinIO 或 Python。程序会在本机启动工作台并打开浏览器；首次使用请在网页中创建管理员账号。关闭 CareArk 启动窗口即停止本机服务。

数据库和原件不会装在 ZIP 或 EXE 中，也不会随着更新被覆盖。首次启动时，程序会在 `%LOCALAPPDATA%\CareArk` 建立一个**空档案**：`careark.db` 是 SQLite 数据库，`originals` 存放上传的原件，`.env` 存放视觉模型设置。可在启动窗口点击“数据目录”打开这个文件夹。

需要识别图片或扫描件时，点击“模型设置”，在 `.env` 的 `MODEL_API_KEY=` 后填写支持图片输入的模型密钥，保存并重启 CareArk。默认示例使用 DeepSeek；也可以同时修改 `MODEL_BASE_URL` 和 `MODEL_NAME` 来使用其他兼容服务。在线视觉识别会把待识别内容发送给所配置的模型服务商；没有密钥仍可打开工作台，但不能识别新资料。

**备份和更新：**先关闭 CareArk，再复制整个 `%LOCALAPPDATA%\CareArk` 文件夹，包含数据库、原件和设置。更新程序时解压新版 ZIP 并运行新的 EXE；数据目录仍是同一个。不要把数据目录、`.env` 或含真实资料的备份上传到 GitHub。

如果程序无法启动，可在数据目录查看 `careark.log`。这个 Windows 包是本机单用户部署方式，不应直接开放到局域网或公网。
