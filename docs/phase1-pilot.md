# 第一阶段试点部署

## 已实现的边界

- 可选 OIDC 登录；生产环境必须使用邮箱已验证的身份声明。
- 企业、成员、角色和一次性邀请代码保存在服务端数据库。
- 资料可按企业保存、版本化、提交和审核。
- 附件可保存到本地私有目录或 S3 兼容对象存储；生产环境需要文件扫描服务。
- 管理员可生成邀请、查看成员、审核资料和查看操作记录。
- 数据库默认使用 SQLite 方便本地试点，也可通过 `CITRUS_DATABASE_URL` 切换到 PostgreSQL。

## 当前产品决定

- 首发范围：邀请制试点，后续可扩展为公开注册。
- 登录方式：邮箱登录加企业邀请；生产环境使用 OIDC，邀请代码只允许对应邮箱接受。
- 部署地区：暂不锁定；数据库和附件通过配置切换，避免绑定单一云厂商。

正式开通前还需要业务负责人补充管理员邮箱、正式域名、部署地区、企业字段、公开字段、附件类型和隐私政策联系人。

## 本地试点

1. 在 `streamlit-deploy` 目录安装依赖：`python -m pip install -r requirements.txt`。
2. 复制 `.env.example` 为 `.env`，设置 `CITRUS_ENV=development`、`CITRUS_AUTH_REQUIRED=true`、`CITRUS_DEV_AUTH_ENABLED=true`。
3. 执行 `python scripts/init_platform.py 你的管理员邮箱`；初始化命令会在数据库中创建平台管理员和默认企业。
4. 启动 `streamlit run app/main.py`。
5. 用管理员邮箱进入本地试点；在设置页生成企业邀请代码。
6. 用另一个邮箱和邀请代码进入，填写供应端或生产端资料。
7. 管理员切换到设置页的“平台管理后台”，审核提交资料。

## 生产切换

- 配置 Streamlit OIDC 的 `[auth]` secrets；不要启用本地试点登录。默认配置直接使用 `[auth]`，只有在配置了命名 provider 时才设置 `CITRUS_AUTH_PROVIDER`。
- 将 `CITRUS_DATABASE_URL` 指向 PostgreSQL。
- 将 `CITRUS_BLOB_BACKEND=s3`，配置私有桶和服务端访问凭据。
- 配置 ClamAV 或等效的文件扫描服务，并设置 `CITRUS_ENV=production`。
- 先在预发布环境运行迁移、备份和恢复演练，再切换正式域名。
- 每日备份数据库和对象存储；每月执行一次恢复演练。

## 已知边界

第一阶段仍是邀请制资料与审核平台。公开供需市场、匹配算法、站内对接通知、交易和即时聊天属于下一阶段；当前页面不会把审核资料自动公开到真实市场。
