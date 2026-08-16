# Docker 与 Cloudflare Tunnel 部署

本方案与 `gold` 项目使用同类结构：本地管理 Named Tunnel，Tunnel JSON 凭据通过 Docker Secret 挂载，`cloudflared` 与 Nginx 共享网络命名空间。

```text
Browser -> Cloudflare Access -> Cloudflare Tunnel -> 127.0.0.1:8080
                                                       |-- React
                                                       `-- /api -> backend:8000
```

Nginx 只监听容器网络命名空间内的 `127.0.0.1:8080`，Compose 不向宿主机发布端口。因此公网访问不能绕过 Cloudflare Access。Taoci 必须使用独立 Tunnel，不能复用其他项目的 Tunnel UUID 或凭据。

## 1. 准备应用

在项目根目录执行：

```bash
cp .env.example .env
docker compose build backend web
```

以下目录以可写 bind mount 持久化，真实数据不会进入镜像：

- `backend/config`：API Key、邮箱凭据、Profile、附件和私有模板
- `backend/data`：SQLite 数据库

可以在 `.env` 中通过 `TAOCI_CONFIG_DIR` 和 `TAOCI_DATA_DIR` 指向其他绝对路径。不要把真实配置、Tunnel JSON 凭据或 `.env` 提交到 Git。

如果当前仍由 tmux 运行开发服务，先保持它运行。完成 Tunnel 和 Access 配置后再切换，避免 Docker 后端与旧后端长期同时写同一个 SQLite 数据库或轮询同一个邮箱。

## 2. 创建独立 Named Tunnel

先按照 Cloudflare 官方说明安装 `cloudflared`。域名必须已经接入 Cloudflare DNS。

```bash
cloudflared tunnel login
cloudflared tunnel create taoci
cloudflared tunnel route dns taoci taoci.example.com
```

第二条命令会输出 Tunnel UUID，并在 `~/.cloudflared/` 创建对应的 `<UUID>.json`。这个 JSON 等同于 Tunnel 凭据，不要移动到项目目录，不要发送到聊天，也不要复用 `gold` 或其他服务的凭据。

复制部署模板：

```bash
cp deploy/cloudflare/config.yml.example deploy/cloudflare/config.yml
```

编辑 `deploy/cloudflare/config.yml`：

- 将 `REPLACE_WITH_TAOCI_TUNNEL_UUID` 替换为新建 Tunnel 的 UUID。
- 将 `taoci.example.com` 替换为实际域名，必须与 DNS 路由一致。
- 暂时保留 Access 占位符，完成下一步后再填写。

编辑根目录 `.env`：

```dotenv
CLOUDFLARED_CONFIG_FILE=./deploy/cloudflare/config.yml
CLOUDFLARED_CREDENTIALS_FILE=/home/你的WSL用户名/.cloudflared/这里填写UUID.json
TAOCI_ALLOWED_ORIGINS=http://localhost:5173
TAOCI_CONFIG_DIR=./backend/config
TAOCI_DATA_DIR=./backend/data
```

生产环境的浏览器请求与 API 同源，不需要把公网域名加入 CORS。`TAOCI_ALLOWED_ORIGINS` 只用于 Vite 本地开发。

## 3. 配置 Cloudflare Access

应用包含个人资料、邮件凭据和 API Key，必须在启动 Tunnel 前配置 Access。

1. 进入 **Zero Trust > Access controls > Applications**。
2. 选择 **Create new application > Self-hosted and private > Add public hostname**。
3. Application name 填写 `Taoci`。
4. Application domain 填写完整域名，例如 `taoci.example.com`。
5. 添加 `Allow` Policy，使用具体的 **Emails** 或 **Cloudflare account member** 限制身份。
6. 不要使用 `Include Everyone`；Session duration 可设为 `24 hours`。
7. 保存后复制该应用的 **Application Audience (AUD) Tag**。

需要邮箱验证码登录时，可在 **Zero Trust > Integrations > Identity providers** 中启用 **One-time PIN**。身份提供商只负责登录方式，真正的访问范围仍由上述 Allow Policy 决定。

回到 `deploy/cloudflare/config.yml`：

- `teamName` 填写 Zero Trust 团队域名中 `.cloudflareaccess.com` 前面的部分。
- `audTag` 填写刚才复制的 Application Audience Tag。

这里的 `access.required` 会让 connector 在转发到 Nginx 前再次验证 Access JWT。配置中的 `protocol: http2` 与 `gold` 保持一致，可避开 Docker Desktop/WSL 环境中偶发的 QUIC 连接问题。

## 4. 检查并启动

先检查 Compose 和 Tunnel 配置：

```bash
docker compose config
docker compose --profile tunnel config
docker run --rm \
  -v "$PWD/deploy/cloudflare/config.yml:/etc/cloudflared/config.yml:ro" \
  cloudflare/cloudflared:2026.7.1 \
  tunnel --config /etc/cloudflared/config.yml ingress validate
```

确认无误后关闭旧的 tmux 开发服务：

```bash
tmux kill-session -t taoci-backend
tmux kill-session -t taoci-frontend
```

启动生产容器：

```bash
docker compose --profile tunnel up -d --build
docker compose ps
docker compose logs --tail=100 cloudflared
```

Cloudflare Dashboard 中 Tunnel 状态应变为 `Healthy`。此时应用没有 `localhost:8080` 入口，只能通过受 Access 保护的域名访问。

本机健康检查可以在容器内执行：

```bash
docker compose exec web wget -qO- http://127.0.0.1:8080/healthz
docker compose exec web wget -qO- http://127.0.0.1:8080/api/stats
```

最后用无痕窗口访问公网域名，确认先出现 Cloudflare 登录页；登录后检查导师列表、草稿、附件上传和自动补全任务的实时状态。

## 日常运维

```bash
# 查看状态
docker compose ps

# 查看日志
docker compose logs --tail=200 backend web cloudflared

# 更新并重建
git pull
docker compose --profile tunnel up -d --build

# 停止服务
docker compose --profile tunnel down
```

不要使用 `down -v`。电脑睡眠、关机或 Docker Desktop 停止后，Tunnel 会离线；需要全天可用时，应迁移到常开的服务器、NAS 或 VPS。

## Cloudflare 官方参考

- [创建本地管理的 Tunnel](https://developers.cloudflare.com/tunnel/advanced/local-management/create-local-tunnel/)
- [Tunnel 配置文件](https://developers.cloudflare.com/tunnel/advanced/local-management/configuration-file/)
- [Origin 与 Access 验证参数](https://developers.cloudflare.com/tunnel/advanced/origin-parameters/)
- [添加 Self-hosted Access 应用](https://developers.cloudflare.com/cloudflare-one/access-controls/applications/http-apps/)
- [Access Policy](https://developers.cloudflare.com/cloudflare-one/access-controls/policies/)
- [配置 One-time PIN](https://developers.cloudflare.com/cloudflare-one/integrations/identity-providers/one-time-pin/)
- [Cloudflare WebSocket 支持](https://developers.cloudflare.com/network/websockets/)
