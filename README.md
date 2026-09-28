# 个人健康档案工作台

**本地部署，健康资料由自己管理。** 按推荐的 Docker Compose 方式运行时，网站、数据库和原件存储都在自己的电脑上，网页默认只允许本机访问。

把门诊病历、检验报告、检查报告、票据和药品资料整理到个人或受管家庭成员的独立档案中。上传时由支持图片输入的模型辅助识别；**模型结果须由人对照原件核对，确认后才进入正式档案和指标趋势。**

## 先看怎么用

工作台有三个最常用的入口：

- **上传资料**：选择这批资料属于哪个事件，上传原件，查看识别进度并核对结果。
- **健康档案**：按时间查看小事件和大事件，点开事件看所包含的资料。
- **原始资料**：逐份查找、查看和修订已归档的原件。数据概览、健康指标和医疗费用根据已确认资料更新。

一次完整操作是：**选择档案成员 → 选择事件归属 → 添加文件 → 等待模型识别 → 对照原件核对 → 确认整批归档 → 到健康档案查看**。

### 小事件、大事件怎么选

| 上传前的选择 | 适合什么情况 | 例子 |
| --- | --- | --- |
| **新建小事件** | 一次独立的门诊、检查或就诊；这次相关的多份单据可以放在一起 | 一次门诊的病历、检验单和处方 |
| **新建大事件** | 手术、住院或持续治疗等较长过程，之后还会陆续补充不同日期的资料 | 一次手术及术前检查、住院和术后随访 |
| **补充已有资料** | 已经建好了小事件或大事件，要把新拿到的资料放进去 | 第二次上传时继续补充同一次治疗 |

**大事件是整理一段诊疗过程的容器，不要求所有资料来自同一家医院。**每份单据仍保留自己识别出的医院、日期和原件。小事件也可在以后整理为大事件。如果只是保存资料而暂不建立事件，可在归属选项中选择“仅归档原始资料”。

在“上传资料”先选上述归属，再选文件。一次最多加入 **100 个文件**，系统会按当前每批最多 **20 个文件**自动拆成上传任务，沿用同一次选择的归属；不需要反复手动建立同名事件。文件列表中可选中多张图片，设为“同一份资料”；也可明确关联同一次就诊。没有手动分组的文件由模型尝试整理，同次就诊的不同单据仍分别保存。

点击“上传并按分组识别”后，在页面下方的“上传任务”看进度。任务进入“等待人工核对”后打开“核对本次资料”：左侧选择资料，中间对照原件，右侧修改这一份的标题、类型、日期、医院、检验项目等。顶部可以一次更改本批资料的事件归属。还没核对完可“保存草稿”；完成后勾选确认并点击“确认整批归档”。误传的资料可在核对时选择“不归档这份资料”。处理失败的任务会显示原因，可在上传任务中重试或调整。

**文件保存在哪里？**Windows 版把原件和 SQLite 数据库保存在 `%LOCALAPPDATA%\CareArk`；Docker 版把原件放在私有 MinIO 存储中，结构化内容保存在 PostgreSQL。待核对内容留在“上传资料”，不会直接进入正式档案；确认后可在“健康档案”按事件查看，在“原始资料”逐份查看，已确认的检验结果会进入“数据概览”的指标与趋势。视觉模型可能出错，尤其是数字、单位、日期和患者姓名，请以原件为准。

## 第一次启动和创建账户

**Windows 双击运行：**从 [Releases](https://github.com/crazyykhllc-bit/CareArk/releases) 下载 Windows ZIP，完整解压后运行 `CareArk.exe`。这个版本不需要安装 Docker、PostgreSQL、MinIO 或 Python；数据库和原件会建立在自己的 `%LOCALAPPDATA%\CareArk` 目录。详细步骤与备份方式见 [Windows 版说明](WINDOWS.md)。

**Windows 一行安装（免 Setup）：**打开普通 PowerShell 窗口，粘贴下面这一行。不需要管理员权限，也不需要安装 Docker 或 Python：

```powershell
& ([scriptblock]::Create((Invoke-RestMethod 'https://raw.githubusercontent.com/crazyykhllc-bit/CareArk/main/scripts/install-windows.ps1')))
```

命令会下载最新稳定版 Windows ZIP、核对 SHA256，解压到 `%LOCALAPPDATA%\Programs\CareArk\versions`，并创建桌面的 **CareArk** 快捷方式。安装完双击快捷方式打开；程序不会自动启动。以后关闭正在运行的 CareArk，再执行同一条命令即可获取最新版。旧版程序会保留，新版校验完成后才更新快捷方式；已有档案和模型设置继续使用。该方式与手动下载 ZIP 并行，都是同一个本机程序。脚本内容可在 [install-windows.ps1](scripts/install-windows.ps1) 查看。

**源码 / Docker 运行：**安装 Docker Desktop 和 Docker Compose 后，**不用单独安装或操作 PostgreSQL、MinIO**；Compose 会在本机启动这两个服务和网站。先确保 Docker Desktop 正在运行，然后在项目目录执行：

```powershell
Copy-Item .env.example .env
```

Docker 方式打开 `.env`，为 `POSTGRES_PASSWORD` 和 `S3_SECRET_KEY` 分别设置独立的强密码，并填写视觉模型 API Key。Windows 版则通过启动窗口的“模型设置”编辑自己的 `.env`，无需数据库和存储密码。密码建议使用密码管理器生成的字母数字随机串；不要把 `.env` 上传到 GitHub。没有模型密钥也能先打开网页，但无法识别新资料。Docker 配置完成后执行：

```powershell
docker compose up -d --build
```

浏览器打开 **http://localhost:8000**。全新数据库会显示“首次初始化 / 创建管理员账号”：输入自己的邮箱和**至少 8 个字符**的密码，点击“创建管理员”。这一步只做一次，建好后使用同一邮箱和密码登录。如果看到普通登录页，说明当前数据库已有账号；不要为重新看到初始化页而删除数据库。

进入系统后，右上角默认是“我”。要替不会使用电脑的家人管理资料，可在成员下拉框选“＋ 新增成员…”，自行填写成员名称，再切换到该成员档案上传。不同成员的资料和统计分开。会自己使用系统的人可以由管理员在“用户管理”创建邀请链接，让对方注册独立账号。请在仅自己能访问的本机完成首次初始化。

## 配置视觉模型：先看国内可用服务

`.env.example` 把 **DeepSeek** 放在第一套示例配置。根据 [DeepSeek 官方图像理解文档](https://api-docs.deepseek.com/zh-cn/guides/vision/)，`deepseek-flash` 支持图片输入和兼容 Chat Completions 的请求格式。填写自己申请的密钥即可：

```env
MODEL_BASE_URL=https://api.deepseek.com
MODEL_API_KEY=在这里填你的密钥
MODEL_NAME=deepseek-flash
MODEL_STRICT_JSON_SCHEMA=false
```

另一种国内选择是阿里云百炼的**千问视觉模型**，例如 `qwen3-vl-plus`。按[百炼官方兼容接口说明](https://help.aliyun.com/zh/model-studio/qwen-vl-compatible-with-openai)填写所属地域的 `MODEL_BASE_URL`、API Key 和模型名；北京地域现在推荐业务空间专属地址，需要把地址中的 `{WorkspaceId}` 换成自己的业务空间 ID。其他支持**图片输入、Chat Completions 和 JSON 输出**的兼容服务也可以接入，包括 OpenAI。只会处理文字的模型不能识别扫描件。

`MODEL_BASE_URL` 填基础地址，不要把 `/chat/completions` 再写进去。更换服务商时要同时更换密钥和模型名，并按它对 JSON Schema / JSON Object 的支持调整 `MODEL_STRICT_JSON_SCHEMA`。Windows 版保存设置后关闭并重新打开程序；Docker 版配置变更后运行：

```powershell
docker compose up -d --force-recreate web worker
```

先用**不含真实隐私的测试图片**试一次完整识别与核对，再上传医疗资料。主服务、第一备用和第二备用分别使用 `MODEL_*`、`MODEL_FALLBACK_*` 和 `MODEL_FALLBACK2_*` 变量；备用只在可切换的服务错误时接手。切换时医疗原件会发送给相应服务商，请只配置你信任的提供方，并检查其隐私条款。服务商的模型名和接口能力可能变化，以其官方文档为准。

## PostgreSQL 必须自己安装吗？

**Windows 版不需要 PostgreSQL**，会自动创建本机 SQLite 数据库和原件目录。Docker 版需要 PostgreSQL，但不需要用户手动安装；`docker compose up` 会自动启动 PostgreSQL、MinIO、网站和识别 Worker。两种版本的数据目录不同，不会自动互相迁移；不要只改数据库地址来搬迁真实健康资料。

Docker 也不是唯一运行方式。熟悉部署的用户可以自行安装 PostgreSQL 和 MinIO，配置环境变量，执行 `alembic upgrade head`，再分别运行 `uvicorn app.main:app` 与 `python -m app.worker`。这比 Docker 步骤多，首次使用建议先按上面的本机方式启动。

## 文件、备份与部署边界

支持 JPG、PNG、WebP、PDF、DOCX、XLSX 和 CSV；旧版 DOC/XLS 建议先转为 DOCX/XLSX。默认单文件上限为 25 MiB，PDF 最多处理 30 页。模型读取扫描件和照片，表格文件尽量直接读取单元格。

“原始资料”的完整导出会生成带 `health_archive_export.v5` 清单的 ZIP；受管成员分别导出。ZIP 包含健康隐私资料，应加密保管。**导出 ZIP 不等于完整备份**：Windows 版请先关闭程序，再备份整个 `%LOCALAPPDATA%\CareArk` 文件夹；Docker 版应同时备份 PostgreSQL 数据库和 MinIO 原件，并验证恢复。当前数据库迁移版本为 `0016`。

示例 Compose 只将网站和 MinIO 控制台绑定到本机 `127.0.0.1`，**不能原样用于公网部署**。公网环境还需 HTTPS、`SECURE_COOKIES=true`、独立强密码、秘密管理、访问控制、可靠备份，并在开放访问前完成管理员初始化。

## 许可证

项目代码采用 [MIT 许可证](LICENSE)。版权署名：赛博自由老爹。

## 开发测试

```powershell
python -m pip install -e ".[test]"
python -m pytest -q
docker compose config
```

自动测试使用假模型和测试存储，不消耗真实模型额度。运行 `docker compose config` 前需要按上文先创建并填写 `.env`。

## 从源码构建 Windows 版

在 Windows 10/11（64 位）和 Python 3.12 下执行：

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install ".[desktop]"
.\.venv\Scripts\python.exe scripts\build_windows.py
```

输出位于 `dist\CareArk-Windows-v<版本号>.zip`，`dist\SHA256SUMS.txt` 是校验值。打包脚本不会读取或加入本机的数据库、原件及 `.env`。
