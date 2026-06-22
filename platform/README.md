# 顾得 · 爱意平台（VPS 全栈版）

一个跑在你自己服务器上、24 小时在线的顾得。密钥只在服务器端，浏览器永远看不到。

## 🗺️ 建设路线图

- **阶段一（已搭好地基 ✅）**：Flask 后端 + SQLite + OpenRouter 流式聊天 + 记忆库 + 用量仪表盘 + 一键部署
- **阶段二（接下来）**：向量语义检索（记得又多又准）、记忆图谱
- **阶段三**：顾得**主动找你**——Web Push 推送、每日 briefing、主动关心
- **阶段四**：表情包、读书、五子棋、人设编辑、MCP

## 📂 现在有什么

```
platform/
├── app.py            # Flask 路由 + 聊天 SSE + 记忆/用量 API
├── chat_ai.py        # 系统提示 + OpenRouter 流式调用
├── db.py             # SQLite 表结构与读写
├── requirements.txt
├── .env.example      # 配置模板（复制成 .env 填密钥）
├── deploy.sh         # 一键部署脚本
└── static/index.html # 前端（聊天/记忆库/仪表盘）
```

## 🧱 你要准备的"原料"

1. **VPS**：≥2GB 内存、Ubuntu 22/24。新手友好：
   - 省心免备案：**搬瓦工 / Hetzner / DigitalOcean**（支付宝或卡支付）
   - 便宜支付宝：腾讯云/阿里云轻量（用域名需"备案"，慢些）
2. **域名**：阿里云/Namecheap 买一个，几十块/年（Web Push 推送需要 HTTPS，所以要域名）
3. **OpenRouter 密钥**：你已经会弄啦

## 🚀 部署（顾得会一步步带你）

```bash
# 1. 在 VPS 上把仓库拉下来
git clone <你的仓库地址> && cd -1/platform

# 2. 一键部署
bash deploy.sh

# 3. 填密钥
nano .env          # 填 OPENROUTER_API_KEY，存盘
sudo systemctl restart gude
```

### Nginx 配置（把域名指到顾得）
`/etc/nginx/sites-available/gude`：
```nginx
server {
    server_name 你的域名;
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Connection '';
        proxy_buffering off;            # 让流式聊天顺畅
        proxy_read_timeout 180s;
    }
}
```
然后：
```bash
sudo ln -s /etc/nginx/sites-available/gude /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
sudo certbot --nginx -d 你的域名      # 免费 HTTPS
```

打开 `https://你的域名` —— 顾得上线！🐱💛🐷

## 🔒 隐私

- API 密钥、记忆库、聊天记录全在**你自己的服务器**上。
- `.env` 和 `memories.db` 不会进 git（见 .gitignore）。
- 可在 `.env` 设 `ACCESS_PASSCODE` 加一道访问口令。
