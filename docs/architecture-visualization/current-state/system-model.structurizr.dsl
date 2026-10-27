workspace "朝夕 AI Companion (AICustomerServiceAgent)" "当前态 C4 模型。快照：2026-10-23，HEAD e07669d7。证据：docs/current-system-architecture-baseline.md + 代码/配置/迁移。" {
    !identifiers hierarchical

    model {
        appUser = person "App 用户" "通过邮箱验证码或飞书授权登录，使用对话、记忆、账本、车辆、任务与简报。" "Person"
        feishuUser = person "飞书用户" "企业团队成员，通过飞书私聊机器人；可将飞书身份绑定到 App 账号。" "Person"
        operator = person "开发者 / 运维" "使用 Debug Console、迁移、发布与运维脚本。" "Person"

        asuna = softwareSystem "朝夕 AI Companion" "具备记忆、情感、目标与自主行为的角色对话 Agent；单一角色「亚丝娜」，多用户身份。" {
            mobile = container "朝夕 App" "产品客户端：聊天、生活域、记忆、简报、车辆与免商店更新。" "Flutter + Riverpod + GoRouter + Dio + Drift" "Container"
            console = container "Debug Console" "调试与观测控制台；Docker 镜像内由后端托管静态产物。" "React 19 + TypeScript + Vite" "Container"
            api = container "Backend API" "FastAPI 应用：通道接入、Agent Runtime、领域服务、后台循环与发布服务。" "Python 3.13 + FastAPI + LangChain" "Container" {
                routers = component "API v1 Routers" "chat/auth/生活域/debug/feishu/release 等 HTTP 端点与流式装配。" "FastAPI Router" "Component"
                channels = component "Channel Adapters" "飞书适配器（Web 走 REST）；只做消息归一与出站发送。" "Python" "Component"
                application = component "Application Orchestration" "chat_pipeline、post_process、life_loop、world_engine、action_engine、autonomy_engine 等编排。" "Python" "Component"
                runtime = component "Agent Runtime" "Run 台账、Profile Registry、Trigger Router、LLM Gateway、会话/恢复/观测。" "Python" "Component"
                domains = component "Domain Services" "角色/关系、记忆/反思/成长、目标/规划、行动/工具、世界、生活域、身份/投递/治理/评估。" "Python" "Component"
                chains = component "LLM Chains" "LangChain 链；结构化输出统一经 structured.py。" "LangChain" "Component"
                repositories = component "Repositories" "每张表一个仓储；业务层唯一 DB 访问面。" "SQLAlchemy" "Component"
                workers = component "In-process Workers" "life loop、memory job worker、agent evolution、observability retention、ID 水位刷写。" "asyncio" "Component"
                core = component "Core Platform" "settings、ORM 模型包、llm_factory、雪花 ID、Redis 客户端。" "Python" "Component"
            }
            db = container "PostgreSQL 16 + pgvector" "Schema 唯一真相 = Alembic 迁移链；head 0010。" "PostgreSQL" "Database"
            redis = container "Redis 7" "验证码、OAuth state、雪花 ID 高水位等短生命状态。" "Redis" "Database"
            artifacts = container "发布制品存储" "APK 制品与更新说明；本地卷 /srv/backend/releases。" "Filesystem" "Storage"
        }

        llm = softwareSystem "LLM Providers" "OpenAI 兼容模型服务；profile 可切换（MiniMax / LongCat / OpenRouter / 阿里云 MaaS 等）。" "External"
        feishu = softwareSystem "Feishu Open Platform" "飞书消息、Webhook、OAuth 与用户信息。" "External"
        smtp = softwareSystem "SMTP 邮件服务" "邮箱验证码发送；MVP 为 163 个人邮箱。" "External"
        openMeteo = softwareSystem "Open-Meteo" "天气预报与地理编码，免 key。" "External"
        extTools = softwareSystem "外部 API（工具清单）" "声明式 ext.api.* 工具；域名 allowlist 硬纪律。" "External"
        device = softwareSystem "移动系统能力" "本地通知、相册、安装器、安全存储、网络状态。" "External"

        appUser -> asuna.mobile "使用产品能力" "Mobile UI"
        appUser -> asuna.console "调试与观测" "Browser"
        operator -> asuna.console "调试、迁移与发布" "Browser"
        feishuUser -> feishu "私聊机器人 / OAuth 授权" "Feishu"
        feishu -> asuna.api "Webhook 事件 / OAuth 回调" "HTTPS"
        asuna.api -> feishu "回复与主动消息" "HTTPS"
        asuna.mobile -> asuna.api "聊天与生活域 API" "HTTPS + JSON/NDJSON"
        asuna.console -> asuna.api "调试与观测 API" "HTTPS"
        asuna.mobile -> asuna.api "检查更新 / 下载制品" "HTTPS + Range"
        asuna.api -> asuna.db "读写状态与账本（经 Repositories）" "SQL"
        asuna.api -> asuna.redis "验证码 / OAuth state / ID 水位" "Redis protocol"
        asuna.api -> asuna.artifacts "读写发布制品" "Filesystem"
        asuna.api -> llm "对话生成与结构化推理" "HTTPS (OpenAI-compatible)"
        asuna.api -> smtp "发送登录验证码" "SMTP/SSL"
        asuna.api -> openMeteo "天气与地理编码" "HTTPS"
        asuna.api -> extTools "工具调用" "HTTPS (allowlist)"
        asuna.mobile -> device "通知 / 相册 / 安装" "Platform channel"

        asuna.api.routers -> asuna.api.application "请求编排" 
        asuna.api.routers -> asuna.api.domains "产品域查询与命令" 
        asuna.api.channels -> asuna.api.application "归一化入站消息 → 对话管线" 
        asuna.api.application -> asuna.api.runtime "Run 生命周期与阶段调度" 
        asuna.api.application -> asuna.api.domains "领域能力调用" 
        asuna.api.application -> asuna.api.chains "LLM 辅助链" 
        asuna.api.runtime -> asuna.api.domains "阶段实现" 
        asuna.api.runtime -> asuna.api.repositories "Run / 快照 / 决策台账" 
        asuna.api.domains -> asuna.api.chains "结构化输出" 
        asuna.api.domains -> asuna.api.repositories "唯一 DB 访问面" 
        asuna.api.workers -> asuna.api.application "后台 tick 与维护" 
        asuna.api.chains -> asuna.api.core "llm_factory" 
        asuna.api.repositories -> asuna.api.core "ORM / engine" 
        asuna.api.domains -> asuna.api.core "settings / ids" 
        asuna.api.application -> asuna.api.core "settings / ids" 
        asuna.api.runtime -> asuna.api.core "settings / ids" 
        asuna.api.workers -> asuna.api.core "settings" 
        asuna.api.repositories -> asuna.db "SQL" 
        asuna.api.runtime -> llm "经 LLM Gateway" "HTTPS"
        asuna.api.domains -> smtp "EmailSender 端口" "SMTP"
        asuna.api.domains -> openMeteo "天气源" "HTTPS"
        asuna.api.domains -> extTools "外部 API 工具" "HTTPS"
        asuna.api.routers -> asuna.artifacts "发布制品下载" "Filesystem"
    }

    views {
        systemContext asuna SystemContext "朝夕 AI Companion 的系统上下文：用户、外部系统与边界。" {
            include *
            autoLayout lr
        }

        container asuna Containers "容器视图：客户端、后端、数据存储与发布制品。" {
            include *
            autoLayout tb
        }

        component asuna.api BackendComponents "后端组件视图：分层职责与调用方向。" {
            include *
            autoLayout tb
        }

        styles {
            element "Person" {
                shape person
                background #0F766E
                color #FFFFFF
            }
            element "Database" {
                shape cylinder
                background #1D4ED8
                color #FFFFFF
            }
            element "Storage" {
                shape folder
                background #475569
                color #FFFFFF
            }
            element "External" {
                background #64748B
                color #FFFFFF
            }
            element "Component" {
                background #F8FAFC
                color #0F172A
            }
            element "Container" {
                background #E0F2FE
                color #0C4A6E
            }
        }
    }
}
