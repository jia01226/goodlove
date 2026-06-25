"""向量记忆：让助手从一堆记忆里"精准想起"最相关的几条，记再多也不糊、又省又准。

设计原则（为用户那台 4GB 小服务器量身）：
- **首选轻量路线**：直接调中转(apikey.fun，OpenAI 兼容)的 /embeddings 接口算向量，
  不下大模型、不占内存。可用 EMBED_* 环境变量配置。
- **可选本地模型**：EMBED_BACKEND=local 时用 sentence-transformers + bge-small-zh（重，按需开）。
- **永远不崩**：拿不到向量时自动降级成"关键词检索"，聊天功能绝不受影响。
- **混合检索**：语义相似度 + 词面重合度，小语料下更稳更准。

向量以 float32 字节存进 SQLite 的 embeddings 表（入库时已归一化，查询用点积=余弦）。
"""
import os, struct, math, time, json, re, datetime
import requests
import db as _db

# 检索加权：越近、越重要的记忆越容易被想起（借鉴 kimi-core 的时间衰减+重要度思路）
RECENCY_W = float(os.environ.get("VEC_RECENCY_W", "0.15"))      # 时间新鲜度加成强度
HALFLIFE_DAYS = float(os.environ.get("VEC_HALFLIFE_DAYS", "45"))  # 多少天热度减半
# 不同类型的"上心程度"加成（承诺/愿望最重要，别被淹没）
TYPE_BOOST = {"PROMISE": 0.25, "WISHLIST": 0.25, "EVENT": 0.12, "MOMENT": 0.10, "MEMORY": 0.0}

# ---- 配置（默认复用聊天用的那家中转）----
_API_BASE = os.environ.get("API_BASE", "https://openrouter.ai/api/v1").rstrip("/")
_API_KEY = os.environ.get("API_KEY") or os.environ.get("OPENROUTER_API_KEY", "")

EMBED_BACKEND = os.environ.get("EMBED_BACKEND", "gateway").strip().lower()  # gateway | local
EMBED_API_BASE = os.environ.get("EMBED_API_BASE", _API_BASE).rstrip("/")
EMBED_API_KEY = os.environ.get("EMBED_API_KEY", _API_KEY)
EMBED_MODEL = os.environ.get("EMBED_MODEL", "text-embedding-3-small").strip()
LOCAL_MODEL_NAME = os.environ.get("LOCAL_EMBED_MODEL", "BAAI/bge-small-zh-v1.5").strip()

# 检索权重：语义占多少，词面占多少
SEM_WEIGHT = float(os.environ.get("VEC_SEM_WEIGHT", "0.7"))

_backend_ready = None      # None=未检测, True/False=检测结果
_local_model = None        # 本地模型懒加载缓存


# ============ 向量编码 ============
def _embed_gateway(texts):
    """调中转的 OpenAI 兼容 /embeddings。失败抛异常。"""
    url = EMBED_API_BASE + "/embeddings"
    headers = {"Authorization": f"Bearer {EMBED_API_KEY}", "Content-Type": "application/json"}
    r = requests.post(url, headers=headers,
                      json={"model": EMBED_MODEL, "input": texts}, timeout=60)
    if r.status_code != 200:
        raise RuntimeError(f"embeddings {r.status_code}: {r.text[:200]}")
    data = r.json().get("data", [])
    if not data:
        raise RuntimeError("embeddings 返回空")
    # 按 index 排序，确保和输入一一对应
    data = sorted(data, key=lambda d: d.get("index", 0))
    return [d["embedding"] for d in data]


def _embed_local(texts):
    """本地 sentence-transformers（重，按需）。失败抛异常。"""
    global _local_model
    if _local_model is None:
        from sentence_transformers import SentenceTransformer
        _local_model = SentenceTransformer(LOCAL_MODEL_NAME)
    vecs = _local_model.encode(texts, normalize_embeddings=False)
    return [list(map(float, v)) for v in vecs]


def embed(texts):
    """把一批文本编码成向量（list[list[float]]）。按 EMBED_BACKEND 选后端。"""
    if not texts:
        return []
    if EMBED_BACKEND == "local":
        return _embed_local(texts)
    return _embed_gateway(texts)


def available():
    """语义向量后端是否可用（探测一次并缓存）。不可用则降级关键词检索。"""
    global _backend_ready
    if _backend_ready is not None:
        return _backend_ready
    try:
        v = embed(["助手测试一下向量"])
        _backend_ready = bool(v and v[0])
    except Exception as e:
        print("[vector] 语义后端不可用，降级关键词检索：", e)
        _backend_ready = False
    return _backend_ready


# ============ 向量打包/相似度（纯 Python，无 numpy 依赖）============
def _normalize(vec):
    n = math.sqrt(sum(x * x for x in vec)) or 1.0
    return [x / n for x in vec]


def _pack(vec):
    return struct.pack(f"{len(vec)}f", *vec)


def _unpack(blob, dim):
    return list(struct.unpack(f"{dim}f", blob))


def _dot(a, b):
    return sum(x * y for x, y in zip(a, b))


# ============ 词面检索（关键词/降级用，纯 Python 不依赖 jieba）============
_token_re = re.compile(r"[a-zA-Z0-9]+")

def _tokens(text):
    """中文取连续二字片段(char-bigram) + 英文/数字整词。无需 jieba，对中文够用。"""
    text = (text or "").lower()
    toks = set(_token_re.findall(text))
    cn = re.sub(r"[^一-鿿]", "", text)
    toks.update(cn[i:i + 2] for i in range(len(cn) - 1))
    toks.update(c for c in cn)  # 单字兜底
    return toks


def _lexical_score(q_tokens, text):
    t = _tokens(text)
    if not t or not q_tokens:
        return 0.0
    inter = len(q_tokens & t)
    return inter / (len(q_tokens) ** 0.5 * len(t) ** 0.5 + 1e-9)


# ============ 入库 / 回填 ============
def index_post(post_id, content):
    """给一条 post 算向量并入库（已存在则更新）。失败安静跳过，绝不影响主流程。"""
    if not available():
        return False
    try:
        vec = _normalize(embed([content])[0])
        _db.upsert_embedding("post", post_id, EMBED_MODEL, len(vec), _pack(vec), content)
        return True
    except Exception as e:
        print("[vector] index_post 失败：", e)
        return False


def backfill(batch=32, kinds=("post",)):
    """给还没有向量的记忆批量补算。返回新建条数。"""
    if not available():
        print("[vector] 语义后端不可用，无法回填（聊天仍正常，走关键词检索）")
        return 0
    total = 0
    if "post" in kinds:
        rows = _db.posts_without_embedding(EMBED_MODEL)
        for i in range(0, len(rows), batch):
            chunk = rows[i:i + batch]
            try:
                vecs = embed([r["content"] for r in chunk])
            except Exception as e:
                print("[vector] 回填一批失败，跳过：", e)
                continue
            for r, v in zip(chunk, vecs):
                nv = _normalize(v)
                _db.upsert_embedding("post", r["id"], EMBED_MODEL, len(nv), _pack(nv), r["content"])
                total += 1
            time.sleep(0.2)  # 对中转温柔点
    print(f"[vector] 回填完成，新增 {total} 条向量")
    return total


# ============ 检索 ============
def _post_meta():
    """{post_id: (type, created_at)}，给检索做时间/重要度加权用。"""
    meta = {}
    for p in _db.all_posts():
        meta[p["id"]] = (p.get("type", ""), p.get("created_at", ""))
    return meta

def _weight(meta, ref_id):
    """按"时间新鲜度 + 类型重要度"给基础分一个放大倍数（≥1）。"""
    typ, created = meta.get(ref_id, ("", ""))
    boost = TYPE_BOOST.get(typ, 0.0)
    rec = 0.0
    try:
        dt = datetime.datetime.strptime(str(created)[:19], "%Y-%m-%d %H:%M:%S")
        now = datetime.datetime.utcnow() + datetime.timedelta(hours=8)
        age = max(0.0, (now - dt).total_seconds() / 86400.0)
        rec = math.exp(-age / HALFLIFE_DAYS)   # 0~1，越新越接近1
    except Exception:
        pass
    return 1.0 + RECENCY_W * rec + boost

def search(query, k=8, kind="post"):
    """返回最相关的 k 条：[{ref_id, text, score}]。语义可用走混合，否则纯词面；
    再按"时间新鲜度+类型重要度"加权，让越近越重要的记忆更容易被想起。"""
    query = (query or "").strip()
    if not query:
        return []
    q_tokens = _tokens(query)
    rows = _db.embeddings_by_kind(kind, EMBED_MODEL)
    meta = _post_meta()

    use_sem = available() and rows
    q_vec = None
    if use_sem:
        try:
            q_vec = _normalize(embed([query])[0])
        except Exception as e:
            print("[vector] 查询编码失败，降级词面：", e)
            use_sem = False

    scored = []
    if use_sem:
        for r in rows:
            sem = _dot(q_vec, _unpack(r["vec"], r["dim"]))
            lex = _lexical_score(q_tokens, r["text"])
            base = SEM_WEIGHT * sem + (1 - SEM_WEIGHT) * lex
            scored.append({"ref_id": r["ref_id"], "text": r["text"],
                           "score": base * _weight(meta, r["ref_id"])})
    else:
        # 降级：对全部 posts 做词面检索（即使没建过向量也能用）
        for p in _db.all_posts():
            lex = _lexical_score(q_tokens, p["content"])
            if lex > 0:
                scored.append({"ref_id": p["id"], "text": p["content"],
                               "score": lex * _weight(meta, p["id"])})

    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[:k]


if __name__ == "__main__":
    # 便于在服务器上手动跑：回填 + 试搜
    import sys
    _db.init_db()
    print("后端：", EMBED_BACKEND, "| 模型：", EMBED_MODEL, "| 可用：", available())
    if len(sys.argv) > 1 and sys.argv[1] == "backfill":
        backfill()
    elif len(sys.argv) > 2 and sys.argv[1] == "search":
        for r in search(sys.argv[2]):
            print(round(r["score"], 4), r["text"][:60])
