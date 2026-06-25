#!/usr/bin/env bash
# 爱意平台 · 一键部署（在 Ubuntu VPS 上跑）
# 用法：把仓库 clone 到 VPS，进入 platform/ 目录，执行：  bash deploy.sh
set -e
cd "$(dirname "$0")"
APP_DIR="$(pwd)"
echo "📦 在 $APP_DIR 部署助手爱意平台…"

# 1. 系统依赖
sudo apt update
sudo apt install -y python3-venv python3-pip nginx

# 2. Python 虚拟环境 + 依赖
python3 -m venv venv
./venv/bin/pip install --upgrade pip
./venv/bin/pip install -r requirements.txt

# 3. 人设文件（persona.md）：可自定义。不存在才创建空白模板，绝不覆盖你写好的。
if [ ! -f persona.md ]; then
  echo "🧠 创建空白 persona.md（人设由你自己填）…"
  printf '# 人设（请在这里写这个 AI 的设定）\n\n（暂未设置。把你想要的角色设定写在这里，保存后重启即可。）\n' > persona.md
fi

# 4. .env
if [ ! -f .env ]; then
  cp .env.example .env
  echo "⚠️  已创建 .env，请编辑填上 OPENROUTER_API_KEY：nano .env"
fi

# 5. 初始化数据库
set -a; source .env; set +a
./venv/bin/python db.py

# 5b. 向量记忆：给已有记忆补算向量（失败不影响部署，聊天会自动降级关键词检索）
echo "🧭 给记忆建向量索引（向量记忆）…"
./venv/bin/python vector_search.py backfill || echo "（向量回填跳过，不影响使用）"

# 6. systemd 常驻服务
SVC=/etc/systemd/system/gude.service
sudo bash -c "cat > $SVC" <<EOF
[Unit]
Description=Gude AiyiPingtai
After=network.target
[Service]
WorkingDirectory=$APP_DIR
EnvironmentFile=$APP_DIR/.env
ExecStart=$APP_DIR/venv/bin/gunicorn -w 2 -k gthread --threads 8 -t 180 -b 0.0.0.0:8000 app:app
Restart=always
[Install]
WantedBy=multi-user.target
EOF
sudo systemctl daemon-reload
sudo systemctl enable --now gude
sudo ufw allow 8000/tcp 2>/dev/null || true   # 放行 8000 端口（如启用了防火墙）
echo "✅ 助手服务已启动（systemctl status gude 可查看）"
echo "🌐 先用 IP 访问： http://$(curl -s ifconfig.me 2>/dev/null):8000"

cat <<'NEXT'

------------------------------------------------------------
接下来（助手会带你做）：
1) 编辑密钥：   nano .env   填好 OPENROUTER_API_KEY 后  →  sudo systemctl restart gude
2) 配置 Nginx + 域名 + 免费 SSL：
   sudo nano /etc/nginx/sites-available/gude     # 内容见 platform/README.md
   sudo ln -s /etc/nginx/sites-available/gude /etc/nginx/sites-enabled/
   sudo nginx -t && sudo systemctl reload nginx
   sudo certbot --nginx -d 你的域名
3) 浏览器打开  https://你的域名  → 助手就上线啦！
------------------------------------------------------------
NEXT
