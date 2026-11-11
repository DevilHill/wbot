# OC PostgreSQL、Redis 与腾讯云部署

这份配置面向 Linux 单台服务器、单 OC 实例。PostgreSQL 保存 OC 主数据、作业及日志、共享元素提交和合并记录；Redis 只保存 Robot 心跳与短期忙碌状态，不保存授权决定或唯一任务记录。Redis 故障时心跳回退到 PostgreSQL，调度仍以持久化作业为准。

## 当前部署安排

- 腾讯云：`wei@124.223.173.147:22`，Ubuntu 24.04。
- 域名：`rpa.marswei.fun`，DNS 已解析到上述服务器。
- 管理 API：服务器 `127.0.0.1:18892`；设备 API：`127.0.0.1:18893`。
- PostgreSQL：`127.0.0.1:25432`；Redis：`127.0.0.1:26379`，均不对公网开放。
- 已有 Nginx 网站继续使用 80/443；默认不启动 Compose 中的可选 Caddy。
- 首次部署使用独立空数据库。现有本地预览数据不自动迁移，不会自动执行本地等待任务。
- 镜像按 Git 提交 SHA 标记；当前发布版本记录在服务器 `~/wbot-oc/deployed.sha`。

## 运行与访问

使用 [compose.yml](../deploy/oc/compose.yml)。该配置使用 Linux host 网络让 OC 保持原来的 loopback 访问边界，不适用于未开启 host 网络支持的 Docker Desktop。数据库和 Redis 各自发布到服务器 loopback 端口；它们同时启用独立密码。

在部署目录创建 `.env`，参考 [配置示例](../deploy/oc/.env.example)。密码使用随机 URL-safe 字符，不要提交到 Git 或粘贴进命令行。可用 `python3` 的 `secrets.token_urlsafe(32)` 生成，配置文件权限设为 `600`。

```bash
docker compose --env-file .env -f deploy/oc/compose.yml up -d --build postgres redis oc
docker compose --env-file .env -f deploy/oc/compose.yml ps
```

默认 Dockerfile 会自行构建 React。若已在本机执行 `npm --prefix oc-web run build` 并验证产物，可使用 `docker build --build-arg WEB_SOURCE=web-prebuilt -f deploy/oc/Dockerfile -t wbot-oc:local .`，避免服务器再下载 Node 构建环境。构建产物应与本次源码一致；正式升级建议使用新镜像标签并通过 `.env` 的 `OC_IMAGE` 指定，保留上一标签用于回退。

在 Windows 上建立隧道，使用已经核验的服务器主机密钥和部署专用私钥：

```powershell
ssh -N -L 127.0.0.1:18892:127.0.0.1:18892 -o ExitOnForwardFailure=yes -o StrictHostKeyChecking=yes -o UserKnownHostsFile=build/oc-cloud-known-hosts -i build/tencent-oc-deploy.key wei@124.223.173.147
```

此隧道用于本机诊断。生产配置启用 Secure Cookie，正常登录请使用 HTTPS 域名；不要为 HTTP 隧道关闭生产 Cookie 安全属性。

## 域名入口

`rpa.marswei.fun` 的 A 记录已指向 `124.223.173.147`。现有 Nginx 已新增独立虚拟主机并安装该子域名证书，配置见 [nginx-rpa.conf](../deploy/oc/nginx-rpa.conf)，不覆盖其他域名配置。

公网管理入口采用 OC 自带账号登录页和角色授权；Nginx 只负责 HTTPS 和同源转发。设备接口保留 Robot 凭据认证，不使用管理账号密码。管理页面和静态资源可公开加载，业务 API 必须有有效登录会话；非本站 Origin 和跨站浏览器请求返回 403。

新服务器初始化管理员后，由具备 sudo 权限的管理员执行 `sudo bash /home/wei/wbot-oc/deploy/oc/install-nginx.sh`。从旧 Basic Auth 升级时执行 `sudo bash /home/wei/wbot-oc/deploy/oc/enable-account-login.sh`，脚本先确认 OC 已要求账号登录，再更换本站配置。失败会恢复本站 Nginx 配置，不覆盖其他域名。

设备端填写 `https://rpa.marswei.fun`，在管理端批准新 Robot 的绑定申请。旧 `admin-access.txt` 是此前 Nginx Basic Auth 的凭据，不用于新版 OC 登录。

## 账号与角色

初始管理员账号为 `wei`，初始密码通过一次性标准输入设置，不写入仓库、镜像或 GitHub Secrets。首次登录必须改为至少 12 字符的新密码。以后管理员可在“账号与权限”中创建成员、设置角色、启用/禁用账号和重置密码。至少保留一名启用的管理员。

| 角色 | 权限 |
| --- | --- |
| 管理员 | 全部运营操作，以及账号、角色分配和设备审批 |
| 开发者 | 查看数据，上传包、部署流程、管理共享元素、提交与停止任务 |
| 操作员 | 查看数据、提交与停止任务 |
| 只读用户 | 查看运营数据、普通 Asset 配置、运行参数及日志 |

首版使用固定角色，不支持自定义角色、字段级或单 Robot 范围授权。账号与 Robot 身份分离，禁用某个管理账号不会撤销 Robot 凭据；需要停止开发设备访问时，应撤销对应 Robot 的绑定。

用户记录保存在 PostgreSQL（本机模式为 SQLite），密码使用独立随机盐与 PBKDF2-SHA256 600,000 次迭代。会话使用 HttpOnly、SameSite=Strict Cookie，生产环境附带 Secure；写操作另外验证会话 CSRF Token。会话最长 8 小时、空闲 30 分钟，服务重启会结束所有管理会话。角色调整、禁用或改密立即撤销该用户会话。错误登录按来源地址和账号限流，不将密码或 Cookie 写入应用日志。

为其他空环境初始化账号时先停止 OC，通过标准输入调用 `python -m app.oc.auth --state-dir /data --username ACCOUNT`，目标数据库通过 `WBOT_OC_DATABASE_URL` 配置。已有任何账号时拒绝重新初始化。未配置认证且没有账号的本机开发实例保留原 loopback 模式；生产 Compose 始终设置 `WBOT_OC_AUTH_REQUIRED=1`，数据库无账号时也不会开放业务接口。

## GitHub 自动部署

工作流：[deploy-oc.yml](../.github/workflows/deploy-oc.yml)。推送到 `main` 或在 `main` 手动运行工作流时，依次执行 Python/真实 PostgreSQL 与 Redis 集成测试、前端测试与 TypeScript 构建，再构建以提交 SHA 命名的 Docker 镜像，通过 SSH 上传和部署。分支推送不会发布到生产环境。

`production` 环境仅允许 `main` 分支，包含 `OC_SSH_KEY`、`OC_SSH_KNOWN_HOSTS`、`OC_SSH_HOST`、`OC_SSH_USER` 四项 Secrets。专用 CI 密钥禁用 SSH 转发和 PTY；连接强制核对预先验证的主机公钥。服务器用户需要 Docker 权限，该权限可管理主机容器，因此应只授权可信仓库维护者修改生产工作流。工作流不用自托管 Runner，也不在日志中输出私钥或数据库密码。

发布脚本使用 GitHub concurrency 和服务器 `flock` 避免并发切换。停止 OC 后，将数据库、文件卷和环境配置备份到 `~/wbot-oc/backups/`，再替换 OC 容器；PostgreSQL、Redis 和数据卷保持原位。新应用健康检查或认证检查失败会恢复旧镜像及部署配置，不自动回滚数据库，避免覆盖新数据。当前升级只新增账号表，后续破坏性数据库升级必须单独设计迁移与回退。

发布过程中管理端会短暂不可用，已在 Assistant 启动的任务继续运行。备份和旧镜像保留供回退，需根据磁盘容量定期审阅和清理；脚本不会自动删除历史备份。Nginx 配置变更仍需服务器管理员执行，不由日常 CI 越权修改系统文件。

会话设计参考 [OWASP Session Management](https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html)，部署环境与串行执行参考 [GitHub 部署控制](https://docs.github.com/en/actions/how-tos/deploy/configure-and-manage-deployments/control-deployments)。

## SQLite 数据迁移

迁移工具：`python -m app.oc.migrate --source SOURCE --state-dir TARGET`，目标连接通过 `WBOT_OC_DATABASE_URL` 配置，命名空间默认 `wbot_oc`。迁移前停止源与目标 OC，等待已派发任务结束并核实未知任务；两个目录必须独立，目标数据库必须为空。工具会取得目录锁，并拒绝源目录中仍存在 `service.json` 的在线迁移。

工具在 PostgreSQL 单个事务中导入主记录、日志、元素提交、分支、合并申请和幂等操作记录，保留顺序与标识。包和客户端更新文件逐个校验 SHA-256 并重新映射路径。文件复制失败或事务异常时不会删除源数据；目标目录可能保留已复制文件，再次迁移时只接受校验一致的文件。不能把失败后的 PostgreSQL 导入状态当作成功，需核对命令退出码和各表记录数。

Windows 本机目录连接迁到 Linux 后会标为维护且离线，历史记录仍保留。需要在 Assistant 中连接云端地址并审批新绑定，再调整流程和 Environment 成员。原有远程身份记录会保留，但客户端是否能复用取决于它保存的 OC 连接身份。

## 备份与恢复

备份必须同时包含 PostgreSQL、`oc-data` 文件卷和受限访问的 `.env`；Redis 是可重建缓存，无需作为权威备份。应在没有运行或等待任务的维护窗口停止 OC，再导出数据库及文件卷，保证一致性。

```bash
docker compose --env-file .env -f deploy/oc/compose.yml stop oc
docker compose --env-file .env -f deploy/oc/compose.yml exec -T postgres pg_dump -U wbot -d wbot -Fc > oc-postgres.dump
docker compose --env-file .env -f deploy/oc/compose.yml run --rm --no-deps --entrypoint python oc -c "import sys,tarfile; archive=tarfile.open(fileobj=sys.stdout.buffer,mode='w|gz'); archive.add('/data',arcname='data'); archive.close()" > oc-files.tar.gz
docker compose --env-file .env -f deploy/oc/compose.yml start oc
```

以上命令在 Bash 中分别导出数据库和文件卷，另需以受限权限备份 `.env`；不要只保存 SQL dump。备份命令失败时应先处理失败，再启动 OC。恢复应在独立空数据库和独立卷中进行并验证，再切换服务。不得在有新写入后直接恢复旧数据库；镜像回退也不等于数据回滚。

## 验证与边界

`requirements-oc.txt` 固定 PostgreSQL、连接池和 Redis 驱动；桌面 Assistant 不需要这些服务器依赖。未设置 `WBOT_OC_DATABASE_URL` 时保留 SQLite 开发模式；配置了 URL 后不会静默回退 SQLite。PostgreSQL 使用 JSONB 与任务状态/Robot 索引，共享元素写入使用事务及数据库锁，避免并发推进同一主分支。

可使用 [compose.test.yml](../deploy/oc/compose.test.yml) 启动隔离数据库，设置 `WBOT_TEST_DATABASE_URL` 和 `WBOT_TEST_REDIS_URL` 后运行 `python -m unittest tests.test_oc_postgres -v`。没有测试地址时这些集成用例明确跳过，不能视为 PostgreSQL 已验证。

目前仅支持一个 OC 服务实例，不能通过增加副本获得高可用；进程内业务锁和共享文件存储还不支持多实例调度。管理列表仍读取完整历史，尚未加入分页和日志保留策略。Redis 心跳每 15 秒进行持久化检查点，缓存失效时可能短暂显示旧在线状态，后续心跳会恢复。正式扩容前需进一步压测与容量规划。
