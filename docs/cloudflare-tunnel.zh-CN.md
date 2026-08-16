# Docker 与 Cloudflare Tunnel 部署

本方案使用同一个域名提供前端、API 和 WebSocket：

```text
Browser -> Cloudflare Access -> Cloudflare Tunnel -> web:80
                                                    |-- React static files
                                                    `-- /api -> backend:8000
```

Cloudflare Tunnel 只建立由本机发起的出站连接，不需要公网 IP、端口转发或在路由器上开放端口。应用包含个人资料、邮件凭据和 API Key，因此必须同时配置 Cloudflare Access。

## 1. 本地准备

在项目根目录执行：

```bash
cp .env.example .env
```

暂时不要填写 Tunnel Token。先构建应用镜像：

```bash
docker compose build backend web
```

现有的以下目录会直接挂载到容器中，不会创建一套空数据：

- `backend/config`：API Key、邮件凭据、Profile、附件和私有模板
- `backend/data`：SQLite 数据库

默认绑定目录可以通过 `.env` 中的 `TAOCI_CONFIG_DIR` 和 `TAOCI_DATA_DIR` 调整。不要把真实配置复制进镜像。

如果当前还在用 tmux 启动开发服务，先保持它运行，等 Cloudflare Tunnel 和 Access 都配置完成后再进行第 5 步的正式切换。不要让 tmux 后端与 Docker 后端长期同时读取同一个 SQLite 数据库或轮询同一个邮箱。

## 2. 在 Cloudflare 创建 Tunnel

前提：域名已经添加到 Cloudflare，并正在使用 Cloudflare DNS。

1. 登录 Cloudflare Dashboard。
2. 进入 **Networking > Tunnels**。
3. 选择 **Create a tunnel**，连接器选择 **Cloudflared**。
4. Tunnel 名称填写 `taoci`，然后创建。
5. 在安装连接器页面选择 **Docker**。
6. 复制命令中 `--token` 后面的长字符串。这个 Token 等同于 Tunnel 凭据，不要发到聊天、截图或提交到 Git。
7. 打开项目根目录的 `.env`，填写：

```dotenv
CLOUDFLARE_TUNNEL_TOKEN=这里填写刚才复制的Token
TAOCI_ALLOWED_ORIGINS=http://localhost:8080
```

生产访问是同源请求，不需要把公网域名加入 CORS；保留 localhost 是为了本机调试。

## 3. 配置域名路由

回到刚创建的 Tunnel：

1. 打开 **Routes**。
2. 选择 **Add route > Published application**。
3. Subdomain 填写需要的子域名，例如 `taoci`。
4. Domain 选择自己的域名，例如 `example.com`。
5. Path 留空。
6. Service type 选择 `HTTP`。
7. Service URL 填写 `http://web:80`。
8. 保存。

最终地址为 `https://taoci.example.com`。这里必须填写 Compose 服务名 `web`，不要填写 `localhost`，因为 `cloudflared` 运行在独立容器中。

## 4. 配置 Cloudflare Access

不要在 Access 配好之前把应用长期暴露在公网。

1. 进入 **Zero Trust > Access controls > Applications**。
2. 选择 **Add an application > Self-hosted**。
3. Application name 填写 `Taoci`。
4. Application domain 填写完整域名，例如 `taoci.example.com`。
5. 新建一条 `Allow` Policy。
6. Include 规则选择 **Emails**，只填写允许访问的个人邮箱。
7. Session duration 建议设为 `24 hours`。
8. 保存应用和 Policy。

新建的 Zero Trust 组织通常已经配置 Cloudflare 自身作为默认身份提供商，适合只允许 Cloudflare 账户成员访问，并可直接使用账户上的 MFA。需要通过普通邮箱验证码登录时，进入 **Zero Trust > Integrations > Identity providers**，选择 **Add new identity provider > One-time PIN**。无论使用哪种登录方式，Access Policy 都必须用具体的 **Emails** 或 **Cloudflare account member** 限制身份；不要使用 `Include Everyone`，也不要只用 `Login Methods: One-time PIN` 作为 Include 条件。

完成后使用无痕窗口访问域名，应该先看到 Cloudflare 登录页，而不是应用页面。

## 5. 启动 Tunnel

先关闭旧的 tmux 开发服务：

```bash
tmux kill-session -t taoci-backend
tmux kill-session -t taoci-frontend
```

再启动生产容器：

```bash
docker compose --profile tunnel up -d --build
docker compose ps
docker compose logs --tail=100 cloudflared
```

Cloudflare Dashboard 中 Tunnel 状态应变为 `Healthy`。然后验证：

1. `http://localhost:8080` 仍可从本机访问。
2. 公网域名先要求 Cloudflare Access 登录。
3. 登录后导师列表和草稿可以加载。
4. 启动一次自动补全，确认右下角后台任务状态可以实时更新，以验证 WebSocket。
5. 上传一个小型测试 PDF，确认 Nginx 的上传限制和附件持久化正常。

## 日常运维

```bash
# 查看状态
docker compose ps

# 查看日志
docker compose logs --tail=200 backend web cloudflared

# 更新并重建应用
git pull
docker compose --profile tunnel up -d --build

# 停止服务
docker compose --profile tunnel down
```

不要使用 `down -v`，本方案当前使用 bind mount 保存数据，但养成不删除卷的习惯可以避免以后切换存储方式时误删数据。电脑睡眠、关机或 Docker Desktop 停止后，Tunnel 会离线；需要 24 小时可用时，应部署到常开的服务器、NAS 或 VPS。

## Cloudflare 官方参考

- [通过 Dashboard 创建 Tunnel](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/get-started/create-remote-tunnel/)
- [配置 Published application](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/routing-to-tunnel/)
- [添加 Self-hosted Access 应用](https://developers.cloudflare.com/cloudflare-one/access-controls/applications/http-apps/)
- [配置 Cloudflare 身份提供商](https://developers.cloudflare.com/cloudflare-one/integrations/identity-providers/cloudflare/)
- [配置 One-time PIN](https://developers.cloudflare.com/cloudflare-one/integrations/identity-providers/one-time-pin/)
- [Cloudflare WebSocket 支持](https://developers.cloudflare.com/network/websockets/)
