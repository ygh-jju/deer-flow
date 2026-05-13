# DeerFlow 使用操作指南

> 适合技术小白的详细操作手册

---

## 目录

1. [快速命令速查](#快速命令速查)
2. [DeerFlow 是什么](#deerflow-是什么)
3. [基本概念解释](#基本概念解释)
4. [如何访问 DeerFlow](#如何访问-deerflow)
5. [四种模式详解](#四种模式详解)
6. [日常使用步骤](#日常使用步骤)
7. [常见问题解决](#常见问题解决)
8. [数据库维护操作](#数据库维护操作)
9. [项目迁移指南](#项目迁移指南)
10. [Git 版本管理与上游同步](#git-版本管理与上游同步)
11. [附录：Docker 容器说明](#附录docker-容器说明)

---

## 快速命令速查

> 最常用的命令都在这里，复制粘贴即可使用

### 服务管理（最常用）

| 命令 | 作用 | 什么时候用 |
|------|------|-----------|
| `make docker-start` | 启动 DeerFlow 服务 | 每天第一次使用 |
| `make docker-stop` | 停止 DeerFlow 服务 | 用完关闭 |
| `make docker-stop && make docker-start` | 重启服务（配置变更后） | 修改 `.env` 或 `config.yaml` 后 |
| `make docker-stop && make docker-start` | 完全重建并启动 | 修改了代码/功能后 |
| `make docker-logs` | 查看运行日志 | 遇到问题 |
| `make docker-logs-gateway` | 只看网关日志 | API 报错时 |

**修改配置后的标准流程：**

```bash
# 1. 修改 .env 或 config.yaml 文件
# 2. 保存文件后，执行重启命令
make docker-stop && make docker-start

# 或使用分步命令
make docker-stop
make docker-start
```

**修改代码/功能后的标准流程：**

```bash
# 1. 修改了前端或后端代码
# 2. 需要完全重建容器镜像
make docker-stop && make docker-start

# docker-start 会自动执行 --build，重新构建所有容器
```

### 数据库维护（每周/需要时）

| 命令 | 作用 | 什么时候用 |
|------|------|-----------|
| `make db-stats` | 查看数据库大小和线程数 | 每周检查一次 |
| `make db-backup` | 备份所有数据 | 每周备份一次 |
| `make db-clean` | 删除不需要的旧对话 | 数据库 > 1GB 时 |
| `make db-prune` | 精简长对话，保留最近记录 | 对话太长时 |

### 查看容器状态

```bash
# 查看所有容器是否在运行
docker ps

# 查看某个容器的日志
docker logs deer-flow-gateway
docker logs deer-flow-langgraph
docker logs deer-flow-nginx
```

---

## DeerFlow 是什么

DeerFlow 是一个开源的 AI 超级智能体，可以帮您：

- 🔍 **搜索网络信息** - 自动搜索并总结网络内容
- 📊 **分析数据** - 处理 Excel、CSV 等数据文件
- 🎨 **生成作品** - 制作 PPT、网页、图片、播客
- 💻 **编写代码** - 自动生成和运行代码
- 📝 **撰写文档** - 写文章、报告、论文

简单来说，它是一个**超级智能助手**，能理解您的需求并自动完成复杂任务。

---

## 基本概念解释

### 1. Docker 容器（已经部署好的服务）

想象一下，Docker 容器就像是**四个不同功能的工作人员**，各自负责不同的工作：

```
┌─────────────────────────────────────────────────────────────┐
│                    DeerFlow 服务团队                          │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│   ┌─────────────┐                                           │
│   │  nginx      │  ← 前台接待（统一入口）                      │
│   │  :2026      │     负责接待所有访客，分配给对应的工作人员      │
│   └─────────────┘                                           │
│          │                                                  │
│          ▼                                                  │
│   ┌─────────────┐      ┌─────────────┐      ┌───────────┐  │
│   │  frontend   │◀────▶│  gateway    │◀────▶│ langgraph │  │
│   │  界面设计师  │      │  服务主管    │      │  AI 大脑   │  │
│   │  :3000      │      │  :8001      │      │  :2024    │  │
│   └─────────────┘      └─────────────┘      └───────────┘  │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

| 容器名称 | 角色 | 端口 | 工作内容 |
|---------|------|------|---------|
| deer-flow-nginx | 前台接待 | 2026 | 接待所有访客，指引到正确的地方 |
| deer-flow-frontend | 界面设计师 | 3000 | 负责漂亮的网页界面 |
| deer-flow-gateway | 服务主管 | 8001 | 处理您的请求，协调各项工作 |
| deer-flow-langgraph | AI 大脑 | 2024 | 真正的智能核心，理解并执行任务 |

**您只需要记住**：所有请求都先找 **nginx（2026端口）**，它会自动分配。

### 2. Session（对话线程）

Session 就是**一次完整的对话记录**。

- **新 Session**：开始一个新的对话，AI 不记得之前聊过什么
- **继续 Session**：接着上次的对话继续聊，AI 记得上下文

比喻：Session 就像是微信里的**不同聊天窗口**，每个窗口都是独立的对话。

### 3. 四种模式

DeerFlow 提供四种工作模式，就像汽车的档位：

| 模式 | 速度 | 智能程度 | 适合场景 |
|-----|------|---------|---------|
| **闪速** | ⚡ 最快 | ⭐ 基础 | 简单问答、快速查询 |
| **思考** | 🚀 中等 | ⭐⭐ 中等 | 需要分析的简单问题 |
| **Pro** | 🐌 较慢 | ⭐⭐⭐ 高级 | 复杂任务，需要规划 |
| **Ultra** | 🐢 最慢 | ⭐⭐⭐⭐ 最强 | 超复杂任务，多步骤协作 |

---

## 如何访问 DeerFlow

### 方法一：直接在服务器上访问（最简单）

如果您直接在服务器上操作，打开浏览器访问：

```
http://localhost:2026
```

### 方法二：从 Windows 电脑通过 SSH 访问（推荐）

#### 步骤 1：在 Windows 上建立 SSH 隧道

打开 PowerShell 或命令提示符，输入：

```powershell
# 格式：ssh -L 本地端口:localhost:远程端口 用户名@服务器IP
ssh -L 2026:localhost:2026 -L 3000:localhost:3000 用户名@服务器IP

# 示例（假设服务器 IP 是 192.168.1.100，用户名是 yugh）
ssh -L 2026:localhost:2026 -L 3000:localhost:3000 yugh@192.168.1.100
```

> 💡 提示：执行后会要求输入密码，输入后即可登录服务器。

#### 步骤 2：在 Windows 浏览器中访问

保持 SSH 连接不要关闭，然后在 Windows 浏览器中打开：

```
http://localhost:2026
```

### 方法三：使用 VS Code Remote-SSH（最方便）

#### 步骤 1：安装扩展

1. 在 VS Code 中安装 **Remote - SSH** 扩展

#### 步骤 2：连接服务器

1. 按 `Ctrl+Shift+P` 打开命令面板
2. 输入 `Remote-SSH: Connect to Host`
3. 输入服务器地址：`用户名@服务器IP`
4. 输入密码连接

#### 步骤 3：转发端口

1. 连接成功后，点击左下角的 **端口** 标签
2. 点击 **转发端口** 按钮
3. 输入 `2026`，回车
4. 输入 `3000`，回车

#### 步骤 4：访问

在 Windows 浏览器中打开：

```
http://localhost:2026
```

---

## 四种模式详解

### 模式对比

| 模式 | 特点 | 适用场景 | 不推荐场景 |
|-----|------|---------|-----------|
| **闪速** | 直接回答，不思考 | "今天天气怎么样"<br>"2+2等于几" | 复杂问题 |
| **思考** | 先思考再回答 | "分析这篇文章"<br>"比较 A 和 B" | 需要执行多步骤的任务 |
| **Pro** | 思考+规划+执行 | "帮我写一份报告"<br>"分析这个 Excel 文件" | 超级复杂的项目 |
| **Ultra** | Pro + 子代理协作 | "帮我做一个网站"<br>"深度调研某个主题" | 简单问题（杀鸡用牛刀） |

### 如何选择模式

```
问题简单程度
    ▲
    │
Ultra │  ★ 超级复杂项目
      │     （网站开发、深度调研）
      │
 Pro  │  ★★ 复杂任务
      │     （数据分析、报告撰写）
      │
思考  │  ★★★ 中等复杂度
      │     （文本分析、简单推理）
      │
闪速  │  ★★★★ 简单问题
      │     （问答、查询）
      └────────────────────────►
                              时间紧急程度
```

### 模式切换方法

1. 在输入框下方找到模式选择器
2. 点击当前模式（如「闪速 ▼」）
3. 从下拉菜单选择想要的模式

---

## 日常使用步骤

### 第一步：启动服务（如果已停止）

如果服务器重启了，需要重新启动 DeerFlow：

```bash
# 进入 DeerFlow 目录
cd /home/yugh/deer-flow

# 启动 Docker 服务
make docker-start
```

### 第二步：访问界面

按照上面的方法，通过浏览器访问：

```
http://localhost:2026
```

### 第三步：选择模式

根据任务复杂度选择合适的模式：
- 简单问题 → 闪速
- 需要分析 → 思考
- 复杂任务 → Pro
- 超级复杂 → Ultra

### 第四步：开始对话

1. 在输入框中输入您的问题或需求
2. 可以上传文件（图片、文档、数据文件等）
3. 点击发送或按 Enter

### 第五步：查看结果

DeerFlow 会：
- 显示思考过程
- 展示执行步骤
- 生成最终结果

---

## 常见问题解决

### Q1: 打不开网页

**可能原因**：
- Docker 服务没有启动
- 端口转发没有建立

**解决方法**：
```bash
# 检查容器状态
docker ps

# 如果容器没有运行，启动它们
cd /home/yugh/deer-flow
make docker-start
```

### Q2: Pro/Ultra 模式是灰色的

**原因**：模型配置中缺少 `supports_thinking` 属性

**解决方法**：
编辑 `/home/yugh/deer-flow/config.yaml`，在模型配置中添加：

```yaml
models:
  - name: kimi-k2.5
    # ... 其他配置 ...
    supports_thinking: true    # 添加这一行
```

然后重启服务：
```bash
docker restart deer-flow-gateway deer-flow-langgraph
```

### Q3: 对话很慢或无响应

**可能原因**：
- 选择了 Pro/Ultra 模式做简单任务
- 网络连接问题
- API Key 余额不足

**解决方法**：
1. 简单问题使用「闪速」或「思考」模式
2. 检查网络连接
3. 检查 API Key 余额

### Q4: 如何开始新的对话

**方法**：
1. 点击左侧边栏的 **+ 新建对话** 按钮
2. 或者在地址栏输入 `http://localhost:2026` 直接访问首页

### Q5: 如何查看历史对话

**方法**：
- 在左侧边栏查看历史对话列表
- 点击任意对话即可继续

---

## 数据库维护操作

DeerFlow 使用 PostgreSQL 数据库存储对话状态（checkpoints）。随着使用时间增长，数据库会逐渐变大。以下维护命令帮助您管理数据库。

### 查看数据库统计信息

```bash
cd /home/yugh/deer-flow
make db-stats
```

**输出示例**：
```
DeerFlow Database Statistics

            Summary
┌───────────────────┬─────────┐
│ Database Size     │ 7743 kB │
│ Total Threads     │ 15      │
│ Total Checkpoints │ 342     │
│ Total Blobs       │ 156     │
│ Total Blob Size   │ 12 MB   │
└───────────────────┴─────────┘
```

**说明**：
- **Threads**：对话线程数量
- **Checkpoints**：状态快照数量（每次对话交互都会产生）
- **Blobs**：存储的二进制数据块
- **Blob Size**：实际占用空间

### 清理旧对话数据

当数据库变大时，可以交互式地删除不需要的对话：

```bash
cd /home/yugh/deer-flow
make db-clean
```

**操作流程**：

1. 系统显示所有对话线程列表：
```
Available Threads

┌────┬──────────────────────────────────┬─────────────┬───────────┐
│ #  │ Thread ID                        │ Checkpoints │ Blob Size │
├────┼──────────────────────────────────┼─────────────┼───────────┤
│  1 │ 6014accd-c9b1-4cfd-acb5-c552... │          42 │ 1.2 MB    │
│  2 │ 7f9dc56c-e49c-4671-a3d2-c492... │          28 │ 856 kB    │
│  3 │ ad76c455-5bf9-4335-8517-fc03... │          15 │ 432 kB    │
└────┴──────────────────────────────────┴─────────────┴───────────┘

Total: 3 threads
```

2. 选择要删除的对话：
   - 输入 `1` - 删除第 1 个
   - 输入 `1,3,5` - 删除第 1、3、5 个
   - 输入 `1-5` - 删除第 1 到第 5 个
   - 输入 `all` - 删除全部
   - 输入 `prune` - 切换到精简模式（保留最近对话）
   - 直接回车 - 取消操作

3. 确认删除后，系统会：
   - 从数据库删除对应的 checkpoints
   - 删除本地的 threads 目录
   - 执行 VACUUM 回收磁盘空间

### 精简对话历史（保留最近对话）

如果某个对话历史太长，可以只删除旧的 checkpoints，保留最近的对话：

```bash
cd /home/yugh/deer-flow
make db-prune
```

**与 `db-clean` 的区别**：

| 命令 | 作用 | 适用场景 |
|-----|------|---------|
| `make db-clean` | 删除整个对话 | 不再需要的旧对话 |
| `make db-prune` | 只删除旧历史，保留最近对话 | 对话太长但仍想保留 |

**操作流程**：

1. 系统显示所有对话线程列表

2. 输入要处理的 thread 编号（如 `1`）

3. 输入要保留的 checkpoint 数量（如 `50`）

4. 确认后系统会：
   - 删除旧的 checkpoints，保留最近的 N 个
   - 删除不再被引用的 blobs
   - 执行 VACUUM 回收磁盘空间

**输出示例**：
```
Thread: 5ce924e2-fabb-4bf4-aef2-d4b38dd3b3f2
Total checkpoints: 200
How many recent checkpoints to keep? (200): 50

Will delete 150 old checkpoints, keeping 50 most recent.
Current blobs: 866, size: 1.50 GB

Proceed? [y/n] (n): y

Pruning complete!
  Deleted checkpoints: 150
  Deleted writes: 450
  Deleted blobs: 816
  Kept checkpoints: 50
```

### 截断对话消息（解决 API Token 超限问题）

当对话消息过多导致 Kimi API 报 `Range of input length should be [1, 260096]` 错误时，可以使用此命令截断消息历史，只保留最近的几条消息：

```bash
cd /home/yugh/deer-flow
make db-truncate
```

**适用场景**：
- API 报错输入长度超过限制（260,096 tokens）
- 对话历史过长，需要紧急修复
- 保留最近上下文，丢弃早期消息

**与 `db-prune` 的区别**：

| 命令 | 作用 | 适用场景 |
|-----|------|---------|
| `make db-prune` | 删除旧的 checkpoints | 减少数据库大小 |
| `make db-truncate` | 截断消息内容 | 解决 API Token 超限 |

**操作流程**：

1. 系统显示所有包含消息的线程列表

2. 选择要截断的 thread 编号（如 `1`）

3. 输入要保留的消息数量（建议 2-5 条）

4. 系统显示消息预览，确认后执行截断

**输出示例**：
```
Thread: dbf42fc9-c419-4694-af93-940f0f393a0d
Message blobs: 144
Total size: 47.79 MB
Current messages per blob: 55

Will truncate to last 3 messages (removing 52 oldest).

Kept messages preview:
  1. ToolMessage: (no output)...
  2. AIMessage: ...
  3. ToolMessage: Successfully presented files...

Proceed? [y/n] (n): y

Truncation complete!
  Updated blobs: 144
  Bytes saved: 36.87 MB
  Messages per blob: 3
```

**命令行参数方式（非交互式）**：
```bash
# 直接指定线程 ID 和保留消息数
cd /home/yugh/deer-flow/backend
uv run python ../scripts/db_maintenance.py truncate \
  --thread dbf42fc9-c419-4694-af93-940f0f393a0d \
  --keep 3
```

### 备份数据库

定期备份可以防止数据丢失：

```bash
cd /home/yugh/deer-flow
make db-backup
```

**备份位置**：`/home/yugh/deer-flow/backups/deerflow_YYYYMMDD_HHMMSS/`

**备份内容**：
- `checkpoints.sql` - PostgreSQL 数据库导出
- `memory.json` - 用户记忆数据
- `threads/` - 对话产生的文件（如生成的图片、文档等）
- `manifest.json` - 备份清单和恢复说明

**输出示例**：
```
Creating backup in backups/deerflow_20260406_143352

Dumping PostgreSQL database...
  Database dump: checkpoints.sql (5420 bytes)
  Memory backup: memory.json
  Threads backup: threads/
  Manifest: manifest.json

Backup complete!
  Location: backups/deerflow_20260406_143352
  Total size: 15.23 MB
```

**指定备份位置**：
```bash
# 直接运行脚本并指定输出目录
cd /home/yugh/deer-flow/backend
uv run python ../scripts/db_maintenance.py backup --output /path/to/backup
```

### 恢复数据库

如果需要从备份恢复：

```bash
# 1. 恢复数据库（备份目录在项目根目录下）
docker exec -i fishgenomedb-db-1 psql -U deerflow -d deerflow < backups/deerflow_20260406_161746/checkpoints.sql

# 2. 恢复记忆数据
cp backups/deerflow_20260406_161746/memory.json backend/.deer-flow/

# 3. 恢复对话文件
cp -r backups/deerflow_20260406_161746/threads/ backend/.deer-flow/

# 4. 重启服务使配置生效
make docker-stop && make docker-start
```

### 维护建议

| 操作 | 频率 | 说明 |
|------|------|------|
| `make db-stats` | 每周一次 | 了解数据库增长情况 |
| `make db-clean` | 数据库 > 1GB 时 | 清理不需要的旧对话 |
| `make db-prune` | 单个对话 > 500 checkpoints | 精简长对话，保留最近历史 |
| `make db-truncate` | API 报错 input length 超限 | 截断消息历史，解决 Token 超限 |
| `make db-backup` | 每周一次 | 定期备份防止数据丢失 |

---

## 项目迁移指南

如果需要将 DeerFlow 项目移动到其他目录，以下是完整的迁移步骤。

### 为什么需要重建 Python 虚拟环境

Python 虚拟环境（`.venv`）中的脚本包含**硬编码的绝对路径**：

```
# backend/.venv/bin/uvicorn 内容示例：
#!/home/yugh/deer-flow/backend/.venv/bin/python  ← 指向原路径
```

移动项目后，这些脚本会找不到正确的 Python 解释器，导致启动失败。

### 迁移步骤

**步骤 1：停止服务**
```bash
cd /home/yugh/deer-flow
make docker-stop
```

**步骤 2：移动项目目录**
```bash
# 移动到新位置（示例：移动到 /opt/deer-flow）
mv /home/yugh/deer-flow /opt/deer-flow
```

**步骤 3：重建 Python 虚拟环境**
```bash
cd /opt/deer-flow/backend
rm -rf .venv
uv sync
```

**步骤 4：重建前端依赖（可选）**
```bash
cd /opt/deer-flow/frontend
rm -rf node_modules
pnpm install
```

**步骤 5：启动服务**
```bash
cd /opt/deer-flow
make docker-start
```

### 迁移后的状态检查

| 项目 | 迁移后状态 | 需要操作 |
|------|------------|----------|
| Git 仓库 | ✅ 正常 | 无 |
| 代码本身 | ✅ 正常 | 无 |
| backend/.venv | ❌ 必须重建 | `rm -rf .venv && uv sync` |
| frontend/node_modules | ⚠️ 建议重建 | `pnpm install` |
| .deer-flow 数据目录 | ✅ 正常（相对路径） | 无 |
| Docker compose 配置 | ✅ 正常（相对路径） | 无 |
| config.yaml | ✅ 正常（相对路径 + $ENV_VAR） | 无 |

### 需要额外检查的配置

如果您在 `.env` 文件中配置了**外部数据挂载**，需要更新绝对路径：

```bash
# 检查是否有外部挂载路径
grep -r "/home/yugh" /opt/deer-flow/.env
```

如果有匹配，修改 `.env` 中对应的 `_SRC` 路径，然后重启容器：

```bash
cd /opt/deer-flow/docker && docker-compose -p deer-flow-dev -f docker-compose-dev.yaml up -d --force-recreate langgraph
```

---

## Git 版本管理与上游同步

本项目采用 **Fork + 双分支模式** 进行版本管理，确保本地定制修改能够与官方上游更新保持同步。

### 分支结构说明

```
本地分支：
  main        ← 纯净的官方代码，定期同步 upstream/main
  personal    ← 本地定制分支，承载所有个性化修改
  snapshot-*  ← 安全备份分支（迁移时创建，永久保留）

远程仓库：
  origin      ← https://github.com/ygh-jju/deer-flow.git (您的 Fork)
  upstream    ← https://github.com/bytedance/deer-flow.git (官方仓库)
```

**各分支用途：**

| 分支 | 来源 | 用途 | 更新频率 |
|-----|------|------|---------|
| `main` | upstream/main | 追踪官方最新版本，只同步不修改 | 每周/需要时 |
| `personal` | main + 定制 | 日常工作分支，承载本地修改 | 每次定制 |
| `snapshot-*` | 迁移前状态 | 安全备份，永不删除 | 只读 |

### 定期同步官方更新

**每周或需要新功能时执行：**

```bash
# 1. 切换到 main 分支，更新官方代码
git checkout main
git fetch upstream
git merge upstream/main

# 2. 切换到 personal 分支，同步更新
git checkout personal
git rebase main

# 3. 如有冲突，逐个解决后继续
#    - 冲突文件会显示差异，判断保留定制还是官方版本
#    - 使用 git add 标记解决，git rebase --continue 继续

# 4. 推送到您的 Fork
git push origin personal --force-with-lease
```

### 冲突处理策略

| 冲突类型 | 处理方式 |
|---------|---------|
| 定制文件（db_maintenance.py, USER_GUIDE.md） | 保留本地版本 |
| 配置相关代码（sandbox_config.py） | 视情况合并或保留本地 |
| 独立功能修复（dialog.tsx hydration） | 优先官方版本，必要时重新适配 |
| 官方新功能 | 全部接受 |

### 配置分离原则（减少冲突）

为了减少未来同步时的冲突，本地定制尽量采用以下形式：

**推荐形式（低冲突风险）：**
- 配置文件（config.yaml, .env）— ✅ 已实现
- 独立脚本（scripts/*.py）— ✅ 已实现
- 文档文件（USER_GUIDE.md）— ✅ 已实现
- 环境变量注入（sandbox environment）— ✅ 已实现

**避免直接修改（高冲突风险）：**
- 核心代码文件（backend/packages/）
- 前端组件（frontend/src/）

### 快速命令参考

```bash
# 查看当前分支状态
git branch -vv

# 检查是否落后于官方
git fetch upstream
git log main..upstream/main --oneline

# 查看定制 commits
git log personal --oneline -10

# 紧急回退到备份状态
git checkout snapshot-pre-migration-20260512
```

### 定期同步提醒

建议每周执行一次上游同步，保持获取官方新功能和修复：

| 日期 | 操作 | 备注 |
|-----|------|------|
| 每周一 | `git fetch upstream && git log main..upstream/main --oneline` | 检查是否有新更新 |
| 有更新时 | 执行同步流程（见上方） | rebase 后验证 Docker 服务正常 |

**设置提醒（可选）：**

```bash
# 添加 crontab 提醒（每周一上午 9 点）
echo "0 9 * * 1 echo 'DeerFlow: Check upstream updates (cd /data/workspace_op2/deer-flow && git fetch upstream)' | mail -s 'DeerFlow Sync Reminder' \$USER" | crontab -
```

### 灾难恢复：备份位置

如果发生严重问题，可以从以下备份恢复：

| 备份类型 | 位置 | 内容 | 用途 |
|---------|------|------|------|
| Git Snapshot 分支 | `snapshot-pre-migration-20260512` | 迁移前的完整 git 状态 | 快速回退到迁移前 |
| 物理目录备份 | `/home/yugh/workspace_op2/deer-flow-backup` | 完整项目目录（60GB） | 灾难恢复，含配置和数据 |
| 数据库备份 | `backups/deerflow_YYYYMMDD_HHMMSS/` | PostgreSQL + threads 数据 | 对话历史恢复 |

**从物理备份恢复：**

```bash
# 1. 停止当前服务
make docker-stop

# 2. 从备份恢复
cp -r /home/yugh/workspace_op2/deer-flow-backup /data/workspace_op2/deer-flow-restored
cd /data/workspace_op2/deer-flow-restored

# 3. 重建虚拟环境（如果需要）
cd backend && rm -rf .venv && uv sync

# 4. 启动服务
make docker-start
```

---

## 附录：Docker 容器说明

### 查看容器状态

```bash
# 查看所有运行中的容器
docker ps

# 查看所有容器（包括停止的）
docker ps -a
```

### 查看容器日志

```bash
# 查看 nginx 日志
docker logs deer-flow-nginx

# 查看前端日志
docker logs deer-flow-frontend

# 查看网关日志
docker logs deer-flow-gateway

# 查看 AI 大脑日志
docker logs deer-flow-langgraph
```

### 重启单个服务

```bash
# 重启 nginx
docker restart deer-flow-nginx

# 重启前端
docker restart deer-flow-frontend

# 重启网关
docker restart deer-flow-gateway

# 重启 AI 大脑
docker restart deer-flow-langgraph
```

### 停止/重启所有服务

```bash
cd /home/yugh/deer-flow
make docker-stop && make docker-start
```

### 完全删除并重建

**注意**：这会删除所有数据！

```bash
cd /home/yugh/deer-flow
make docker-stop
docker-compose -f docker/docker-compose-dev.yaml down -v
make docker-start
```

---

## 总结

记住这几句话：

1. **访问地址**：`http://localhost:2026`（nginx 统一入口）
2. **四种模式**：闪速 < 思考 < Pro < Ultra（从快到慢，从简单到复杂）
3. **SSH 隧道**：Windows 访问需要用 `ssh -L` 转发端口
4. **查看日志**：遇到问题先看 `docker logs`

祝您使用愉快！如有问题，请查看日志或重新启动服务。

---

## 进阶用法：生信分析 Docker 调用与数据挂载

DeerFlow 支持调用外部 Docker 镜像（如您自己封装的生信分析镜像）来处理数据。为了实现这一点，系统配置了 `LocalSandboxProvider` 模式，允许 Agent 访问宿主机的 Docker 引擎。

### 1. 配置数据挂载路径

当您的分析数据目录发生改变时，您不需要修改复杂的 YAML 文件，只需修改项目根目录下的 `.env` 文件。

**操作步骤：**

1. 打开 `/home/yugh/deer-flow/.env` 文件。
2. 找到文件末尾的 `Bioinformatics Data Mounts` 配置段：
   ```env
   # Bioinformatics Data Mounts (used by docker-compose-dev.yaml)
   DEER_FLOW_DATA_MOUNT_SRC=/home/yugh/workspace_op2/250820_culter_ssr
   DEER_FLOW_DATA_MOUNT_DEST=/mnt/data/250820_culter_ssr
   DEER_FLOW_RESULTS_MOUNT_SRC=/home/yugh/workspace_op2/250820_culter_ssr/results
   DEER_FLOW_RESULTS_MOUNT_DEST=/mnt/data/results
   ```
3. 修改对应的变量：
   - `_SRC`：代表宿主机（您的 Linux 服务器）上的真实物理路径。
   - `_DEST`：代表挂载到 Agent 运行环境（`langgraph` 容器）内的路径（通常保持 `/mnt/data/...` 即可）。
4. 保存 `.env` 文件后，在终端执行以下命令使配置生效：
   ```bash
   cd /home/yugh/deer-flow/docker && docker-compose -p deer-flow-dev -f docker-compose-dev.yaml up -d --force-recreate langgraph
   ```

### 2. 向 Agent 下达调用外部 Docker 的指令

由于 Agent 运行在容器中，且通过 `/var/run/docker.sock` 唤起宿主机的 Docker 引擎，因此在拼接 `docker run -v` 参数时，**挂载的源路径必须是宿主机的真实物理路径**（即 `.env` 中配置的 `_SRC` 路径）。

**指令示例：**

在 DeerFlow 的对话框中，您可以这样告诉 Agent：

> "请使用 docker 运行我本地的生信分析镜像 `my-bio-image:latest`。
> 将宿主机的 `/home/yugh/workspace_op2/250820_culter_ssr` 挂载为容器内的 `/data` (只读)，
> 将 `/home/yugh/workspace_op2/250820_culter_ssr/results` 挂载为容器内的 `/results` (读写)。
> 执行分析脚本 `python /app/analyze.py --input /data/xxx.fastq --output /results/out.csv`。"

**Agent 实际执行的命令类似：**
```bash
docker run --rm \
  -v /home/yugh/workspace_op2/250820_culter_ssr:/data:ro \
  -v /home/yugh/workspace_op2/250820_culter_ssr/results:/results:rw \
  my-bio-image:latest \
  python /app/analyze.py --input /data/xxx.fastq --output /results/out.csv
```

### 3. Sandbox 容器用户权限配置

默认情况下，DeerFlow 的 sandbox 容器以 root 用户运行。如果需要让 sandbox 容器以当前用户身份运行（解决挂载目录权限问题），可以在 `config.yaml` 的 `sandbox` 配置段添加 `environment` 字段。

**场景说明**：

当 sandbox 容器需要访问宿主机挂载的数据目录时，如果容器以 root 运行而宿主机目录属于特定用户，可能导致权限不匹配。通过配置 `USER_UID` 和 `USER_GID` 环境变量，可以让容器内的用户与宿主机用户匹配。

**配置步骤**：

1. 查询当前用户的 UID 和 GID：
   ```bash
   id yugh
   # 输出类似：uid=1002(yugh) gid=1002(yugh) ...
   ```

2. 编辑 `/home/yugh/deer-flow/config.yaml`，在 `sandbox` 配置段添加 `environment`：
   ```yaml
   sandbox:
     use: deerflow.community.aio_sandbox:AioSandboxProvider
     image: bioinfo-sandbox:latest
     idle_timeout: 0
     replicas: 3
     environment:
       USER_UID: "1002"      # 当前用户的 UID
       USER_GID: "1002"      # 当前用户的 GID
       USER: "gem"           # 容器内的用户名（通常使用 gem）
     mounts:
       - host_path: $DEER_FLOW_DATA_MOUNT_SRC
         container_path: $DEER_FLOW_DATA_MOUNT_DEST
         read_only: false
   ```

3. 保存配置后重启服务：
   ```bash
   cd /home/yugh/deer-flow
   make docker-stop && make docker-start
   ```

**验证效果**：

重启后，sandbox 容器内的进程将以 UID=1002 的 `gem` 用户运行，与宿主机用户权限匹配，可以正常读写挂载目录。

**注意事项**：

- `USER_UID` 和 `USER_GID` 必须使用**字符串格式**（加引号）
- Sandbox 镜像的 `entrypoint.sh` 会根据这些环境变量动态创建用户
- 每次创建新的 sandbox 容器都会应用此配置
- 如需修改，只需更新 `config.yaml` 并重启服务即可
