import argparse
import json
import os
import time

import numpy as np
import pandas as pd
import requests
from dateutil.parser import parse as parse_dt
from tqdm import tqdm
from transformers import AutoModel, AutoTokenizer, pipeline


# ========================
# 配置（可按需修改）
# ========================

# Step 2: DeepSeek 摘要 + 每日×行业新闻数量
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEEPSEEK_MODEL = "deepseek-chat"

DATA_DIR = "Data"
NEWS_CSV = os.path.join(DATA_DIR, "FilteredNews_2011-2024.csv")
INDUSTRY_KEYWORDS_JSON = os.path.join(DATA_DIR, "industry_keywords_zh.json")

NEWS_TIME_COL = "Date"  # 时间列
NEWS_TEXT_COL = "News"  # 内容列
NEWS_SOURCE_COL = "Source"  # 来源列

START_DATE = None  # 例如 "2020-01-01"
END_DATE = None  # 例如 "2020-12-31"

MAX_ARTICLES_PER_GROUP = 20
MAX_CHARS_PER_ARTICLE = 500

NEWS_COUNT_OUT = os.path.join(DATA_DIR, "NewsCount_Day&Industry.csv")
SUMMARY_OUT = os.path.join(DATA_DIR, "IndustryNewsSummary_daily.csv")

# Step 3: embedding
EMBED_MODEL_NAME = "Qwen/Qwen3-Embedding-0.6B"
EMBED_OUT_PARQUET = os.path.join(DATA_DIR, "industry_news_embeddings.parquet")
EMBED_OUT_NPY = os.path.join(DATA_DIR, "industry_news_embeddings.npy")
EMBED_BATCH_SIZE = 16
EMBED_MAX_LENGTH = 1024

# Step 4: sentiment
SENTIMENT_MODEL_NAME = "yiyanghkust/finbert-tone-chinese"
SENTIMENT_OUT = os.path.join(DATA_DIR, "industry_daily_features.csv")


SOURCE_TIERS = {
    "新华社": {"tier": 1, "label": "高", "weight": 1.0},
    "人民日报": {"tier": 1, "label": "高", "weight": 1.0},
    "第一财经": {"tier": 2, "label": "中", "weight": 0.7},
    "新浪财经": {"tier": 3, "label": "低", "weight": 0.4},
    "网易财经": {"tier": 3, "label": "低", "weight": 0.4},
}

INDUSTRY_NAME_TO_ID = {
    "工业": 0,
    "信息技术": 1,
    "公用事业": 2,
    "可选消费": 3,
    "原材料": 4,
    "医药卫生": 5,
    "金融": 6,
    "能源": 7,
    "主要消费": 8,
    "通信服务": 9,
    "房地产": 10,
}


def get_source_info(src: str) -> dict:
    if src in SOURCE_TIERS:
        return SOURCE_TIERS[src]
    return {"tier": 2, "label": "中", "weight": 0.6}


def call_deepseek(prompt: str, temperature: float = 0.3, max_tokens: int = 512) -> str:
    if not DEEPSEEK_API_KEY or DEEPSEEK_API_KEY == "YOUR_DEEPSEEK_API_KEY_HERE":
        raise ValueError("请先配置 DEEPSEEK_API_KEY（建议使用环境变量）")

    url = f"{DEEPSEEK_BASE_URL}/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": DEEPSEEK_MODEL,
        "messages": [
            {"role": "system", "content": "你是一名金融研究员。"},
            {"role": "user", "content": prompt},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }

    resp = requests.post(url, headers=headers, json=payload, timeout=120)
    if resp.status_code != 200:
        print("DeepSeek API 返回错误：", resp.text)
    resp.raise_for_status()
    data = resp.json()
    return data["choices"][0]["message"]["content"].strip()


def load_industry_keywords(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        kw = json.load(f)

    cleaned: dict[str, list[str]] = {}
    for industry_name, keywords in kw.items():
        if isinstance(keywords, str):
            cleaned[industry_name] = [keywords]
        else:
            cleaned[industry_name] = list(dict.fromkeys(keywords))
    return cleaned


def detect_industries_for_text(text: str, kw_dict: dict) -> list[str]:
    if not isinstance(text, str) or not text:
        return []

    hits: list[str] = []
    for industry_name, keywords in kw_dict.items():
        for kw in keywords:
            if kw and kw in text:
                hits.append(industry_name)
                break
    return hits


def load_and_prepare_news_df() -> pd.DataFrame:
    print("读取新闻数据中...")
    news_df = pd.read_csv(NEWS_CSV)
    print("新闻表列名：", list(news_df.columns))

    df = news_df.rename(
        columns={
            NEWS_TIME_COL: "Date",
            NEWS_TEXT_COL: "News",
            NEWS_SOURCE_COL: "Source",
        }
    )

    df["Date"] = df["Date"].apply(lambda x: parse_dt(str(x)))
    df["date"] = df["Date"].dt.date

    if START_DATE is not None:
        start = parse_dt(START_DATE).date()
        df = df[df["date"] >= start]

    if END_DATE is not None:
        end = parse_dt(END_DATE).date()
        df = df[df["date"] <= end]

    df["News"] = df["News"].astype(str).str.strip()
    df["Source"] = df["Source"].astype(str).str.strip()

    print(f"过滤后新闻条数: {len(df)}")
    return df


def add_industry_columns(df: pd.DataFrame) -> pd.DataFrame:
    print("读取行业关键词...")
    industry_keywords = load_industry_keywords(INDUSTRY_KEYWORDS_JSON)
    print("行业数量：", len(industry_keywords), " -> ", list(industry_keywords.keys()))

    print("为每条新闻匹配行业（中文名）...")
    df = df.copy()
    df["industry_names"] = df["News"].apply(lambda txt: detect_industries_for_text(txt, industry_keywords))

    df = df[df["industry_names"].map(len) > 0].copy()
    print(f"命中任一行业的新闻条数: {len(df)}")

    df = df.explode("industry_names").rename(columns={"industry_names": "industry_name"})
    df["industry_id"] = df["industry_name"].map(INDUSTRY_NAME_TO_ID)

    unknown = df[df["industry_id"].isna()]["industry_name"].unique()
    if len(unknown) > 0:
        print("警告：以下行业中文名没有在 INDUSTRY_NAME_TO_ID 中找到映射，请检查：", unknown)

    df = df.dropna(subset=["industry_id"]).copy()
    df["industry_id"] = df["industry_id"].astype(int).astype(str)

    print(f"拆分后总行数（新闻×行业）：{len(df)}")
    return df


def save_news_count_day_industry(df_expanded: pd.DataFrame, out_path: str = NEWS_COUNT_OUT) -> pd.DataFrame:
    news_count_df = (
        df_expanded.groupby(["date", "industry_id"], as_index=False)
        .size()
        .rename(columns={"size": "news_count"})
    )
    news_count_df.to_csv(out_path, index=False, encoding="utf-8-sig")
    print(f"已保存每日×行业新闻数量到: {out_path}")
    return news_count_df


def generate_daily_industry_summaries(df_expanded: pd.DataFrame, out_path: str = SUMMARY_OUT) -> pd.DataFrame:
    groups = df_expanded.groupby(["date", "industry_id"])
    print(f"需要生成摘要的 (date, industry_id) 组合数量：{len(groups)}")

    results: list[dict] = []
    for (date, industry_id), group in tqdm(groups, desc="生成行业日度摘要"):
        group_sorted = group.sort_values("Date")
        group_sampled = group_sorted.head(MAX_ARTICLES_PER_GROUP).copy()

        news_items_text = []
        for _, row in group_sampled.iterrows():
            src = row["Source"]
            cred_label = get_source_info(src)["label"]

            news_text = row["News"]
            if len(news_text) > MAX_CHARS_PER_ARTICLE:
                news_text = news_text[:MAX_CHARS_PER_ARTICLE] + "……"

            ts_str = row["Date"].strftime("%Y-%m-%d %H:%M")
            news_items_text.append(f"【来源：{src}｜可信度：{cred_label}】（时间：{ts_str}）{news_text}")

        news_block = "\n\n".join(f"{idx + 1}. {txt}" for idx, txt in enumerate(news_items_text))
        prompt = (
            f"请你针对 **行业编号 {industry_id}**，在日期 **{date}** 的新闻，"
            f"输出一个不超过 200 字的中文简短摘要，用于后续资产定价模型。\n\n"
            f"请你：\n"
            f"1. 概括当日该行业面临的主要政策、宏观与公司层面的事件；\n"
            f"2. 明确指出这些信息对该行业股价整体的潜在影响方向（利好/利空/中性），并简单解释原因；\n"
            f"3. 若不同来源之间存在明显矛盾或不确定性，请说明不确定性来源；\n"
            f"4. 在综合判断时，要对新华社、人民日报给予最高权重，其次是第一财经，"
            f"新浪财经和网易财经权重最低；如存在冲突，以高可信度来源为主。\n\n"
            f"下面是该行业在 {date} 的新闻列表：\n\n"
            f"{news_block}\n\n"
            f"请直接给出一段连续的摘要文字，不要罗列新闻条目。"
        )

        try:
            summary = call_deepseek(prompt)
        except Exception as e:
            print(f"\n[错误] 日期 {date}, 行业 {industry_id} 调用 DeepSeek 失败：{e}")
            summary = f"[调用失败] {e}"

        results.append(
            {
                "date": date,
                "industry_id": industry_id,
                "num_articles_used": len(group_sampled),
                "summary": summary,
            }
        )
        time.sleep(0.3)

    out_df = pd.DataFrame(results)
    out_df.to_csv(out_path, index=False, encoding="utf-8-sig")
    print(f"已保存行业日度新闻摘要到: {out_path}")
    return out_df


def run_step2(generate_summary: bool = True) -> None:
    df = load_and_prepare_news_df()
    df_expanded = add_industry_columns(df)
    save_news_count_day_industry(df_expanded, NEWS_COUNT_OUT)
    if generate_summary:
        generate_daily_industry_summaries(df_expanded, SUMMARY_OUT)


def mean_pooling(last_hidden_state, attention_mask):
    mask = attention_mask.unsqueeze(-1).expand(last_hidden_state.size()).float()
    masked_embeddings = last_hidden_state * mask
    sum_embeddings = masked_embeddings.sum(dim=1)
    sum_mask = mask.sum(dim=1).clamp(min=1e-9)
    return sum_embeddings / sum_mask


def generate_embeddings_from_summary_csv(
    input_csv: str = SUMMARY_OUT,
    out_parquet: str = EMBED_OUT_PARQUET,
    out_npy: str = EMBED_OUT_NPY,
    model_name: str = EMBED_MODEL_NAME,
    batch_size: int = EMBED_BATCH_SIZE,
    max_length: int = EMBED_MAX_LENGTH,
) -> None:
    import torch
    import torch.nn.functional as F

    df = pd.read_csv(input_csv)
    required_cols = {"date", "industry_id", "summary"}
    missing = required_cols - set(df.columns)
    if missing:
        raise ValueError(f"{input_csv} 缺少列: {sorted(missing)}；请先运行 Step2 生成摘要文件。")

    df = df[["date", "industry_id", "summary"]].copy()
    df["summary"] = df["summary"].fillna("").astype(str).str.strip()
    df = df[df["summary"] != ""].reset_index(drop=True)
    print(f"样本数: {len(df)}")

    device = "cuda:7" if torch.cuda.is_available() else "cpu"
    tokenizer = AutoTokenizer.from_pretrained(model_name, trust_remote_code=True)
    model = AutoModel.from_pretrained(
        model_name,
        trust_remote_code=True,
        torch_dtype=torch.float16 if str(device).startswith("cuda") else torch.float32,
    ).to(device)
    model.eval()

    all_embeddings = []
    for start in tqdm(range(0, len(df), batch_size), desc="Encoding"):
        batch_texts = df["summary"].iloc[start : start + batch_size].tolist()
        inputs = tokenizer(
            batch_texts,
            padding=True,
            truncation=True,
            max_length=max_length,
            return_tensors="pt",
        )
        inputs = {k: v.to(device) for k, v in inputs.items()}

        with torch.no_grad():
            outputs = model(**inputs)
            if hasattr(outputs, "last_hidden_state"):
                embeddings = mean_pooling(outputs.last_hidden_state, inputs["attention_mask"])
            elif hasattr(outputs, "embeddings"):
                embeddings = outputs.embeddings
            else:
                raise ValueError("模型输出中未找到 last_hidden_state 或 embeddings，请检查模型接口。")

            embeddings = F.normalize(embeddings, p=2, dim=1)

        all_embeddings.append(embeddings.detach().cpu().numpy())

    all_embeddings = np.vstack(all_embeddings)
    print("embedding shape:", all_embeddings.shape)

    np.save(out_npy, all_embeddings)
    save_df = df.copy()
    save_df["embedding"] = [vec.tolist() for vec in all_embeddings]
    save_df.to_parquet(out_parquet, index=False)

    print(f"已保存到: {out_npy}")
    print(f"已保存到: {out_parquet}")


def run_step3() -> None:
    generate_embeddings_from_summary_csv()


def add_news_count_to_embeddings(
    embeddings_parquet: str = EMBED_OUT_PARQUET,
    news_count_csv: str = NEWS_COUNT_OUT,
) -> pd.DataFrame:
    emb = pd.read_parquet(embeddings_parquet)
    cnt = pd.read_csv(news_count_csv)

    emb = emb.copy()
    emb["date"] = pd.to_datetime(emb["date"])
    emb["industry_id"] = emb["industry_id"].astype(str)

    cnt = cnt.copy()
    cnt["date"] = pd.to_datetime(cnt["date"])
    cnt["industry_id"] = cnt["industry_id"].astype(str)

    merged = emb.merge(cnt, on=["date", "industry_id"], how="left")
    merged["news_count"] = merged["news_count"].fillna(0).astype(int)
    return merged


def compute_sentiment_features(
    embeddings_parquet: str = EMBED_OUT_PARQUET,
    news_count_csv: str = NEWS_COUNT_OUT,
    out_csv: str = SENTIMENT_OUT,
    model_name: str = SENTIMENT_MODEL_NAME,
) -> pd.DataFrame:
    df = add_news_count_to_embeddings(embeddings_parquet, news_count_csv)

    classifier = pipeline("text-classification", model=model_name)
    label_map = {"positive": 1, "neutral": 0, "negative": -1}

    df["summary"] = df["summary"].fillna("").astype(str)
    results = classifier(df["summary"].tolist())

    df["label"] = [x["label"].lower() for x in results]
    df["prob"] = [x["score"] for x in results]
    df["sentiment"] = df["label"].map(label_map).fillna(0).astype(int)
    df["sentiment_score"] = df["sentiment"] * df["prob"]

    daily_features = df[
        [
            "date",
            "industry_id",
            "summary",
            "news_count",
            "label",
            "prob",
            "sentiment",
            "sentiment_score",
            "embedding",
        ]
    ].copy()
    daily_features.to_csv("Data/NewsFullData.csv",index = False, encoding="utf-8-sig")
    # daily_features.to_csv(out_csv, index=False, encoding="utf-8-sig")
    print(f"已保存日度特征到: {out_csv}")
    return daily_features


def run_step4() -> None:
    compute_sentiment_features()


def main():
    parser = argparse.ArgumentParser(description="新闻处理流水线：摘要/计数 -> embedding -> 情绪特征")
    parser.add_argument("--step2", action="store_true", help="运行 Step2：DeepSeek 摘要 + 每日×行业新闻数量")
    parser.add_argument("--step3", action="store_true", help="运行 Step3：Qwen embedding（基于 Step2 摘要文件）")
    parser.add_argument("--step4", action="store_true", help="运行 Step4：FinBERT 情绪（基于 Step3 parquet + Step2 计数）")
    parser.add_argument("--no-summary", action="store_true", help="Step2 只生成 NewsCount，不调用 DeepSeek 摘要")
    args = parser.parse_args()

    # 默认只跑 Step2（避免一运行就下载大模型/跑很久）
    run2 = args.step2 or (not args.step3 and not args.step4)
    run3 = args.step3
    run4 = args.step4

    if run2:
        run_step2(generate_summary=not args.no_summary)
    if run3:
        run_step3()
    if run4:
        run_step4()


if __name__ == "__main__":
    main()
    import sys
    sys.exit(0)

# # END_OF_SCRIPT

# import argparse
# import json
# import os
# import time

# import numpy as np
# import pandas as pd
# import requests
# from dateutil.parser import parse as parse_dt
# from tqdm import tqdm
# from transformers import AutoModel, AutoTokenizer, pipeline


# # ========================
# # 配置（可按需修改）
# # ========================

# # Step 2: DeepSeek 摘要 + 每日×行业新闻数量
# DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
# DEEPSEEK_BASE_URL = "https://api.deepseek.com"
# DEEPSEEK_MODEL = "deepseek-chat"

# DATA_DIR = "Data"
# NEWS_CSV = os.path.join(DATA_DIR, "FilteredNews_2011-2024.csv")
# INDUSTRY_KEYWORDS_JSON = os.path.join(DATA_DIR, "industry_keywords_zh.json")

# NEWS_TIME_COL = "Date"  # 时间列
# NEWS_TEXT_COL = "News"  # 内容列
# NEWS_SOURCE_COL = "Source"  # 来源列

# START_DATE = None  # 例如 "2020-01-01"
# END_DATE = None  # 例如 "2020-12-31"

# MAX_ARTICLES_PER_GROUP = 20
# MAX_CHARS_PER_ARTICLE = 500

# NEWS_COUNT_OUT = os.path.join(DATA_DIR, "NewsCount_Day&Industry.csv")
# SUMMARY_OUT = os.path.join(DATA_DIR, "IndustryNewsSummary_daily.csv")

# # Step 3: embedding
# EMBED_MODEL_NAME = "Qwen/Qwen3-Embedding-0.6B"
# EMBED_OUT_PARQUET = os.path.join(DATA_DIR, "industry_news_embeddings.parquet")
# EMBED_OUT_NPY = os.path.join(DATA_DIR, "industry_news_embeddings.npy")
# EMBED_BATCH_SIZE = 16
# EMBED_MAX_LENGTH = 1024

# # Step 4: sentiment
# SENTIMENT_MODEL_NAME = "yiyanghkust/finbert-tone-chinese"
# SENTIMENT_OUT = os.path.join(DATA_DIR, "industry_daily_features.csv")


# # ========================
# # Step 2: DeepSeek 摘要 + 计数
# # ========================

# SOURCE_TIERS = {
#     "新华社": {"tier": 1, "label": "高", "weight": 1.0},
#     "人民日报": {"tier": 1, "label": "高", "weight": 1.0},
#     "第一财经": {"tier": 2, "label": "中", "weight": 0.7},
#     "新浪财经": {"tier": 3, "label": "低", "weight": 0.4},
#     "网易财经": {"tier": 3, "label": "低", "weight": 0.4},
# }

# INDUSTRY_NAME_TO_ID = {
#     "工业": 0,
#     "信息技术": 1,
#     "公用事业": 2,
#     "可选消费": 3,
#     "原材料": 4,
#     "医药卫生": 5,
#     "金融": 6,
#     "能源": 7,
#     "主要消费": 8,
#     "通信服务": 9,
#     "房地产": 10,
# }


# def get_source_info(src: str) -> dict:
#     if src in SOURCE_TIERS:
#         return SOURCE_TIERS[src]
#     return {"tier": 2, "label": "中", "weight": 0.6}


# def call_deepseek(prompt: str, temperature: float = 0.3, max_tokens: int = 512) -> str:
#     if not DEEPSEEK_API_KEY or DEEPSEEK_API_KEY == "YOUR_DEEPSEEK_API_KEY_HERE":
#         raise ValueError("请先配置 DEEPSEEK_API_KEY（建议使用环境变量）")

#     url = f"{DEEPSEEK_BASE_URL}/v1/chat/completions"
#     headers = {
#         "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
#         "Content-Type": "application/json",
#     }
#     payload = {
#         "model": DEEPSEEK_MODEL,
#         "messages": [
#             {"role": "system", "content": "你是一名金融研究员。"},
#             {"role": "user", "content": prompt},
#         ],
#         "temperature": temperature,
#         "max_tokens": max_tokens,
#     }

#     resp = requests.post(url, headers=headers, json=payload, timeout=120)
#     if resp.status_code != 200:
#         print("DeepSeek API 返回错误：", resp.text)
#     resp.raise_for_status()
#     data = resp.json()
#     return data["choices"][0]["message"]["content"].strip()


# def load_industry_keywords(path: str) -> dict:
#     with open(path, "r", encoding="utf-8") as f:
#         kw = json.load(f)

#     cleaned: dict[str, list[str]] = {}
#     for industry_name, keywords in kw.items():
#         if isinstance(keywords, str):
#             cleaned[industry_name] = [keywords]
#         else:
#             cleaned[industry_name] = list(dict.fromkeys(keywords))
#     return cleaned


# def detect_industries_for_text(text: str, kw_dict: dict) -> list[str]:
#     if not isinstance(text, str) or not text:
#         return []

#     hits: list[str] = []
#     for industry_name, keywords in kw_dict.items():
#         for kw in keywords:
#             if kw and kw in text:
#                 hits.append(industry_name)
#                 break
#     return hits


# def load_and_prepare_news_df() -> pd.DataFrame:
#     print("读取新闻数据中...")
#     news_df = pd.read_csv(NEWS_CSV)
#     print("新闻表列名：", list(news_df.columns))

#     df = news_df.rename(
#         columns={
#             NEWS_TIME_COL: "Date",
#             NEWS_TEXT_COL: "News",
#             NEWS_SOURCE_COL: "Source",
#         }
#     )

#     df["Date"] = df["Date"].apply(lambda x: parse_dt(str(x)))
#     df["date"] = df["Date"].dt.date

#     if START_DATE is not None:
#         start = parse_dt(START_DATE).date()
#         df = df[df["date"] >= start]

#     if END_DATE is not None:
#         end = parse_dt(END_DATE).date()
#         df = df[df["date"] <= end]

#     df["News"] = df["News"].astype(str).str.strip()
#     df["Source"] = df["Source"].astype(str).str.strip()

#     print(f"过滤后新闻条数: {len(df)}")
#     return df


# def add_industry_columns(df: pd.DataFrame) -> pd.DataFrame:
#     print("读取行业关键词...")
#     industry_keywords = load_industry_keywords(INDUSTRY_KEYWORDS_JSON)
#     print("行业数量：", len(industry_keywords), " -> ", list(industry_keywords.keys()))

#     print("为每条新闻匹配行业（中文名）...")
#     df = df.copy()
#     df["industry_names"] = df["News"].apply(lambda txt: detect_industries_for_text(txt, industry_keywords))

#     df = df[df["industry_names"].map(len) > 0].copy()
#     print(f"命中任一行业的新闻条数: {len(df)}")

#     df = df.explode("industry_names").rename(columns={"industry_names": "industry_name"})
#     df["industry_id"] = df["industry_name"].map(INDUSTRY_NAME_TO_ID)

#     unknown = df[df["industry_id"].isna()]["industry_name"].unique()
#     if len(unknown) > 0:
#         print("警告：以下行业中文名没有在 INDUSTRY_NAME_TO_ID 中找到映射，请检查：", unknown)

#     df = df.dropna(subset=["industry_id"]).copy()
#     df["industry_id"] = df["industry_id"].astype(int).astype(str)

#     print(f"拆分后总行数（新闻×行业）：{len(df)}")
#     return df


# def save_news_count_day_industry(df_expanded: pd.DataFrame, out_path: str = NEWS_COUNT_OUT) -> pd.DataFrame:
#     news_count_df = (
#         df_expanded.groupby(["date", "industry_id"], as_index=False)
#         .size()
#         .rename(columns={"size": "news_count"})
#     )
#     news_count_df.to_csv(out_path, index=False, encoding="utf-8-sig")
#     print(f"已保存每日×行业新闻数量到: {out_path}")
#     return news_count_df


# def generate_daily_industry_summaries(df_expanded: pd.DataFrame, out_path: str = SUMMARY_OUT) -> pd.DataFrame:
#     groups = df_expanded.groupby(["date", "industry_id"])
#     print(f"需要生成摘要的 (date, industry_id) 组合数量：{len(groups)}")

#     results: list[dict] = []
#     for (date, industry_id), group in tqdm(groups, desc="生成行业日度摘要"):
#         group_sorted = group.sort_values("Date")
#         group_sampled = group_sorted.head(MAX_ARTICLES_PER_GROUP).copy()

#         news_items_text = []
#         for _, row in group_sampled.iterrows():
#             src = row["Source"]
#             cred_label = get_source_info(src)["label"]

#             news_text = row["News"]
#             if len(news_text) > MAX_CHARS_PER_ARTICLE:
#                 news_text = news_text[:MAX_CHARS_PER_ARTICLE] + "……"

#             ts_str = row["Date"].strftime("%Y-%m-%d %H:%M")
#             news_items_text.append(f"【来源：{src}｜可信度：{cred_label}】（时间：{ts_str}）{news_text}")

#         news_block = "\n\n".join(f"{idx + 1}. {txt}" for idx, txt in enumerate(news_items_text))
#         prompt = (
#             f"请你针对 **行业编号 {industry_id}**，在日期 **{date}** 的新闻，"
#             f"输出一个不超过 200 字的中文简短摘要，用于后续资产定价模型。\n\n"
#             f"请你：\n"
#             f"1. 概括当日该行业面临的主要政策、宏观与公司层面的事件；\n"
#             f"2. 明确指出这些信息对该行业股价整体的潜在影响方向（利好/利空/中性），并简单解释原因；\n"
#             f"3. 若不同来源之间存在明显矛盾或不确定性，请说明不确定性来源；\n"
#             f"4. 在综合判断时，要对新华社、人民日报给予最高权重，其次是第一财经，"
#             f"新浪财经和网易财经权重最低；如存在冲突，以高可信度来源为主。\n\n"
#             f"下面是该行业在 {date} 的新闻列表：\n\n"
#             f"{news_block}\n\n"
#             f"请直接给出一段连续的摘要文字，不要罗列新闻条目。"
#         )

#         try:
#             summary = call_deepseek(prompt)
#         except Exception as e:
#             print(f"\n[错误] 日期 {date}, 行业 {industry_id} 调用 DeepSeek 失败：{e}")
#             summary = f"[调用失败] {e}"

#         results.append(
#             {
#                 "date": date,
#                 "industry_id": industry_id,
#                 "num_articles_used": len(group_sampled),
#                 "summary": summary,
#             }
#         )
#         time.sleep(0.3)

#     out_df = pd.DataFrame(results)
#     out_df.to_csv(out_path, index=False, encoding="utf-8-sig")
#     print(f"已保存行业日度新闻摘要到: {out_path}")
#     return out_df


# def run_step2(generate_summary: bool = True) -> None:
#     df = load_and_prepare_news_df()
#     df_expanded = add_industry_columns(df)
#     save_news_count_day_industry(df_expanded, NEWS_COUNT_OUT)
#     if generate_summary:
#         generate_daily_industry_summaries(df_expanded, SUMMARY_OUT)


# # ========================
# # Step 3: Qwen embedding
# # ========================


# def mean_pooling(last_hidden_state, attention_mask):
#     mask = attention_mask.unsqueeze(-1).expand(last_hidden_state.size()).float()
#     masked_embeddings = last_hidden_state * mask
#     sum_embeddings = masked_embeddings.sum(dim=1)
#     sum_mask = mask.sum(dim=1).clamp(min=1e-9)
#     return sum_embeddings / sum_mask


# def generate_embeddings_from_summary_csv(
#     input_csv: str = SUMMARY_OUT,
#     out_parquet: str = EMBED_OUT_PARQUET,
#     out_npy: str = EMBED_OUT_NPY,
#     model_name: str = EMBED_MODEL_NAME,
#     batch_size: int = EMBED_BATCH_SIZE,
#     max_length: int = EMBED_MAX_LENGTH,
# ) -> None:
#     import torch
#     import torch.nn.functional as F

#     df = pd.read_csv(input_csv)
#     required_cols = {"date", "industry_id", "summary"}
#     missing = required_cols - set(df.columns)
#     if missing:
#         raise ValueError(f"{input_csv} 缺少列: {sorted(missing)}；请先运行 Step2 生成摘要文件。")

#     df = df[["date", "industry_id", "summary"]].copy()
#     df["summary"] = df["summary"].fillna("").astype(str).str.strip()
#     df = df[df["summary"] != ""].reset_index(drop=True)
#     print(f"样本数: {len(df)}")

#     device = "cuda" if torch.cuda.is_available() else "cpu"
#     tokenizer = AutoTokenizer.from_pretrained(model_name, trust_remote_code=True)
#     model = AutoModel.from_pretrained(
#         model_name,
#         trust_remote_code=True,
#         torch_dtype=torch.float16 if device == "cuda" else torch.float32,
#     ).to(device)
#     model.eval()

#     all_embeddings = []
#     for start in tqdm(range(0, len(df), batch_size), desc="Encoding"):
#         batch_texts = df["summary"].iloc[start : start + batch_size].tolist()
#         inputs = tokenizer(
#             batch_texts,
#             padding=True,
#             truncation=True,
#             max_length=max_length,
#             return_tensors="pt",
#         )
#         inputs = {k: v.to(device) for k, v in inputs.items()}

#         with torch.no_grad():
#             outputs = model(**inputs)
#             if hasattr(outputs, "last_hidden_state"):
#                 embeddings = mean_pooling(outputs.last_hidden_state, inputs["attention_mask"])
#             elif hasattr(outputs, "embeddings"):
#                 embeddings = outputs.embeddings
#             else:
#                 raise ValueError("模型输出中未找到 last_hidden_state 或 embeddings，请检查模型接口。")

#             embeddings = F.normalize(embeddings, p=2, dim=1)

#         all_embeddings.append(embeddings.detach().cpu().numpy())

#     all_embeddings = np.vstack(all_embeddings)
#     print("embedding shape:", all_embeddings.shape)

#     np.save(out_npy, all_embeddings)
#     save_df = df.copy()
#     save_df["embedding"] = [vec.tolist() for vec in all_embeddings]
#     save_df.to_parquet(out_parquet, index=False)

#     print(f"已保存到: {out_npy}")
#     print(f"已保存到: {out_parquet}")


# def run_step3() -> None:
#     generate_embeddings_from_summary_csv()


# # ========================
# # Step 4: FinBERT 情绪
# # ========================


# def add_news_count_to_embeddings(
#     embeddings_parquet: str = EMBED_OUT_PARQUET,
#     news_count_csv: str = NEWS_COUNT_OUT,
# ) -> pd.DataFrame:
#     emb = pd.read_parquet(embeddings_parquet)
#     cnt = pd.read_csv(news_count_csv)

#     emb = emb.copy()
#     emb["date"] = pd.to_datetime(emb["date"])
#     emb["industry_id"] = emb["industry_id"].astype(str)

#     cnt = cnt.copy()
#     cnt["date"] = pd.to_datetime(cnt["date"])
#     cnt["industry_id"] = cnt["industry_id"].astype(str)

#     merged = emb.merge(cnt, on=["date", "industry_id"], how="left")
#     merged["news_count"] = merged["news_count"].fillna(0).astype(int)
#     return merged


# def compute_sentiment_features(
#     embeddings_parquet: str = EMBED_OUT_PARQUET,
#     news_count_csv: str = NEWS_COUNT_OUT,
#     out_csv: str = SENTIMENT_OUT,
#     model_name: str = SENTIMENT_MODEL_NAME,
# ) -> pd.DataFrame:
#     df = add_news_count_to_embeddings(embeddings_parquet, news_count_csv)

#     classifier = pipeline("text-classification", model=model_name)
#     label_map = {"positive": 1, "neutral": 0, "negative": -1}

#     df["summary"] = df["summary"].fillna("").astype(str)
#     results = classifier(df["summary"].tolist())

#     df["label"] = [x["label"].lower() for x in results]
#     df["prob"] = [x["score"] for x in results]
#     df["sentiment"] = df["label"].map(label_map).fillna(0).astype(int)
#     df["sentiment_score"] = df["sentiment"] * df["prob"]

#     daily_features = df[
#         [
#             "date",
#             "industry_id",
#             "summary",
#             "news_count",
#             "label",
#             "prob",
#             "sentiment",
#             "sentiment_score",
#             "embedding",
#         ]
#     ].copy()

#     daily_features.to_csv(out_csv, index=False, encoding="utf-8-sig")
#     print(f"已保存日度特征到: {out_csv}")
#     return daily_features


# def run_step4() -> None:
#     compute_sentiment_features()


# def main():
#     parser = argparse.ArgumentParser(description="新闻处理流水线：摘要/计数 -> embedding -> 情绪特征")
#     parser.add_argument("--step2", action="store_true", help="运行 Step2：DeepSeek 摘要 + 每日×行业新闻数量")
#     parser.add_argument("--step3", action="store_true", help="运行 Step3：Qwen embedding（基于 Step2 摘要文件）")
#     parser.add_argument("--step4", action="store_true", help="运行 Step4：FinBERT 情绪（基于 Step3 parquet + Step2 计数）")
#     parser.add_argument("--no-summary", action="store_true", help="Step2 只生成 NewsCount，不调用 DeepSeek 摘要")
#     args = parser.parse_args()

#     # 默认只跑 Step2（避免一运行就下载大模型/跑很久）
#     run2 = args.step2 or (not args.step3 and not args.step4)
#     run3 = args.step3
#     run4 = args.step4

#     if run2:
#         run_step2(generate_summary=not args.no_summary)
#     if run3:
#         run_step3()
#     if run4:
#         run_step4()


# if __name__ == "__main__":
#     main()

# """

# import argparse
# import json
# import os
# import time

# import numpy as np
# import pandas as pd
# import requests
# from dateutil.parser import parse as parse_dt
# from tqdm import tqdm
# from transformers import AutoModel, AutoTokenizer, pipeline


# # ========================
# # 配置（可按需修改）
# # ========================

# # Step 2: DeepSeek 摘要 + 每日×行业新闻数量
# DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
# DEEPSEEK_BASE_URL = "https://api.deepseek.com"
# DEEPSEEK_MODEL = "deepseek-chat"

# DATA_DIR = "Data"
# NEWS_CSV = os.path.join(DATA_DIR, "FilteredNews_2011-2024.csv")
# INDUSTRY_KEYWORDS_JSON = os.path.join(DATA_DIR, "industry_keywords_zh.json")

# NEWS_TIME_COL = "Date"  # 时间列
# NEWS_TEXT_COL = "News"  # 内容列
# NEWS_SOURCE_COL = "Source"  # 来源列

# START_DATE = None  # 例如 "2020-01-01"
# END_DATE = None  # 例如 "2020-12-31"

# MAX_ARTICLES_PER_GROUP = 20
# MAX_CHARS_PER_ARTICLE = 500

# NEWS_COUNT_OUT = os.path.join(DATA_DIR, "NewsCount_Day&Industry.csv")
# SUMMARY_OUT = os.path.join(DATA_DIR, "IndustryNewsSummary_daily.csv")

# # Step 3: embedding
# EMBED_MODEL_NAME = "Qwen/Qwen3-Embedding-0.6B"
# EMBED_OUT_PARQUET = os.path.join(DATA_DIR, "industry_news_embeddings.parquet")
# EMBED_OUT_NPY = os.path.join(DATA_DIR, "industry_news_embeddings.npy")
# EMBED_BATCH_SIZE = 16
# EMBED_MAX_LENGTH = 1024

# # Step 4: sentiment
# SENTIMENT_MODEL_NAME = "yiyanghkust/finbert-tone-chinese"
# SENTIMENT_OUT = os.path.join(DATA_DIR, "industry_daily_features.csv")


# # ========================
# # Step 2: DeepSeek 摘要 + 计数
# # ========================

# SOURCE_TIERS = {
#     "新华社": {"tier": 1, "label": "高", "weight": 1.0},
#     "人民日报": {"tier": 1, "label": "高", "weight": 1.0},
#     "第一财经": {"tier": 2, "label": "中", "weight": 0.7},
#     "新浪财经": {"tier": 3, "label": "低", "weight": 0.4},
#     "网易财经": {"tier": 3, "label": "低", "weight": 0.4},
# }

# INDUSTRY_NAME_TO_ID = {
#     "工业": 0,
#     "信息技术": 1,
#     "公用事业": 2,
#     "可选消费": 3,
#     "原材料": 4,
#     "医药卫生": 5,
#     "金融": 6,
#     "能源": 7,
#     "主要消费": 8,
#     "通信服务": 9,
#     "房地产": 10,
# }


# def get_source_info(src: str) -> dict:
#     if src in SOURCE_TIERS:
#         return SOURCE_TIERS[src]
#     return {"tier": 2, "label": "中", "weight": 0.6}


# def call_deepseek(prompt: str, temperature: float = 0.3, max_tokens: int = 512) -> str:
#     if not DEEPSEEK_API_KEY or DEEPSEEK_API_KEY == "YOUR_DEEPSEEK_API_KEY_HERE":
#         raise ValueError("请先配置 DEEPSEEK_API_KEY（建议使用环境变量）")

#     url = f"{DEEPSEEK_BASE_URL}/v1/chat/completions"
#     headers = {
#         "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
#         "Content-Type": "application/json",
#     }
#     payload = {
#         "model": DEEPSEEK_MODEL,
#         "messages": [
#             {"role": "system", "content": "你是一名金融研究员。"},
#             {"role": "user", "content": prompt},
#         ],
#         "temperature": temperature,
#         "max_tokens": max_tokens,
#     }

#     resp = requests.post(url, headers=headers, json=payload, timeout=120)
#     if resp.status_code != 200:
#         print("DeepSeek API 返回错误：", resp.text)
#     resp.raise_for_status()
#     data = resp.json()
#     return data["choices"][0]["message"]["content"].strip()


# def load_industry_keywords(path: str) -> dict:
#     with open(path, "r", encoding="utf-8") as f:
#         kw = json.load(f)

#     cleaned: dict[str, list[str]] = {}
#     for industry_name, keywords in kw.items():
#         if isinstance(keywords, str):
#             cleaned[industry_name] = [keywords]
#         else:
#             cleaned[industry_name] = list(dict.fromkeys(keywords))
#     return cleaned


# def detect_industries_for_text(text: str, kw_dict: dict) -> list[str]:
#     if not isinstance(text, str) or not text:
#         return []

#     hits: list[str] = []
#     for industry_name, keywords in kw_dict.items():
#         for kw in keywords:
#             if kw and kw in text:
#                 hits.append(industry_name)
#                 break
#     return hits


# def load_and_prepare_news_df() -> pd.DataFrame:
#     print("读取新闻数据中...")
#     news_df = pd.read_csv(NEWS_CSV)
#     print("新闻表列名：", list(news_df.columns))

#     df = news_df.rename(
#         columns={
#             NEWS_TIME_COL: "Date",
#             NEWS_TEXT_COL: "News",
#             NEWS_SOURCE_COL: "Source",
#         }
#     )

#     df["Date"] = df["Date"].apply(lambda x: parse_dt(str(x)))
#     df["date"] = df["Date"].dt.date

#     if START_DATE is not None:
#         start = parse_dt(START_DATE).date()
#         df = df[df["date"] >= start]

#     if END_DATE is not None:
#         end = parse_dt(END_DATE).date()
#         df = df[df["date"] <= end]

#     df["News"] = df["News"].astype(str).str.strip()
#     df["Source"] = df["Source"].astype(str).str.strip()

#     print(f"过滤后新闻条数: {len(df)}")
#     return df


# def add_industry_columns(df: pd.DataFrame) -> pd.DataFrame:
#     print("读取行业关键词...")
#     industry_keywords = load_industry_keywords(INDUSTRY_KEYWORDS_JSON)
#     print("行业数量：", len(industry_keywords), " -> ", list(industry_keywords.keys()))

#     print("为每条新闻匹配行业（中文名）...")
#     df = df.copy()
#     df["industry_names"] = df["News"].apply(lambda txt: detect_industries_for_text(txt, industry_keywords))

#     df = df[df["industry_names"].map(len) > 0].copy()
#     print(f"命中任一行业的新闻条数: {len(df)}")

#     df = df.explode("industry_names").rename(columns={"industry_names": "industry_name"})
#     df["industry_id"] = df["industry_name"].map(INDUSTRY_NAME_TO_ID)

#     unknown = df[df["industry_id"].isna()]["industry_name"].unique()
#     if len(unknown) > 0:
#         print("警告：以下行业中文名没有在 INDUSTRY_NAME_TO_ID 中找到映射，请检查：", unknown)

#     df = df.dropna(subset=["industry_id"]).copy()
#     df["industry_id"] = df["industry_id"].astype(int).astype(str)

#     print(f"拆分后总行数（新闻×行业）：{len(df)}")
#     return df


# def save_news_count_day_industry(df_expanded: pd.DataFrame, out_path: str = NEWS_COUNT_OUT) -> pd.DataFrame:
#     news_count_df = (
#         df_expanded.groupby(["date", "industry_id"], as_index=False)
#         .size()
#         .rename(columns={"size": "news_count"})
#     )
#     news_count_df.to_csv(out_path, index=False, encoding="utf-8-sig")
#     print(f"已保存每日×行业新闻数量到: {out_path}")
#     return news_count_df


# def generate_daily_industry_summaries(df_expanded: pd.DataFrame, out_path: str = SUMMARY_OUT) -> pd.DataFrame:
#     groups = df_expanded.groupby(["date", "industry_id"])
#     print(f"需要生成摘要的 (date, industry_id) 组合数量：{len(groups)}")

#     results: list[dict] = []
#     for (date, industry_id), group in tqdm(groups, desc="生成行业日度摘要"):
#         group_sorted = group.sort_values("Date")
#         group_sampled = group_sorted.head(MAX_ARTICLES_PER_GROUP).copy()

#         news_items_text = []
#         for _, row in group_sampled.iterrows():
#             src = row["Source"]
#             cred_label = get_source_info(src)["label"]

#             news_text = row["News"]
#             if len(news_text) > MAX_CHARS_PER_ARTICLE:
#                 news_text = news_text[:MAX_CHARS_PER_ARTICLE] + "……"

#             ts_str = row["Date"].strftime("%Y-%m-%d %H:%M")
#             news_items_text.append(f"【来源：{src}｜可信度：{cred_label}】（时间：{ts_str}）{news_text}")

#         news_block = "\n\n".join(f"{idx + 1}. {txt}" for idx, txt in enumerate(news_items_text))
#         prompt = (
#             f"请你针对 **行业编号 {industry_id}**，在日期 **{date}** 的新闻，"
#             f"输出一个不超过 200 字的中文简短摘要，用于后续资产定价模型。\n\n"
#             f"请你：\n"
#             f"1. 概括当日该行业面临的主要政策、宏观与公司层面的事件；\n"
#             f"2. 明确指出这些信息对该行业股价整体的潜在影响方向（利好/利空/中性），并简单解释原因；\n"
#             f"3. 若不同来源之间存在明显矛盾或不确定性，请说明不确定性来源；\n"
#             f"4. 在综合判断时，要对新华社、人民日报给予最高权重，其次是第一财经，"
#             f"新浪财经和网易财经权重最低；如存在冲突，以高可信度来源为主。\n\n"
#             f"下面是该行业在 {date} 的新闻列表：\n\n"
#             f"{news_block}\n\n"
#             f"请直接给出一段连续的摘要文字，不要罗列新闻条目。"
#         )

#         try:
#             summary = call_deepseek(prompt)
#         except Exception as e:
#             print(f"\n[错误] 日期 {date}, 行业 {industry_id} 调用 DeepSeek 失败：{e}")
#             summary = f"[调用失败] {e}"

#         results.append(
#             {
#                 "date": date,
#                 "industry_id": industry_id,
#                 "num_articles_used": len(group_sampled),
#                 "summary": summary,
#             }
#         )
#         time.sleep(0.3)

#     out_df = pd.DataFrame(results)
#     out_df.to_csv(out_path, index=False, encoding="utf-8-sig")
#     print(f"已保存行业日度新闻摘要到: {out_path}")
#     return out_df


# def run_step2(generate_summary: bool = True) -> None:
#     df = load_and_prepare_news_df()
#     df_expanded = add_industry_columns(df)
#     save_news_count_day_industry(df_expanded, NEWS_COUNT_OUT)
#     if generate_summary:
#         generate_daily_industry_summaries(df_expanded, SUMMARY_OUT)


# # ========================
# # Step 3: Qwen embedding
# # ========================

# def mean_pooling(last_hidden_state, attention_mask):
#     mask = attention_mask.unsqueeze(-1).expand(last_hidden_state.size()).float()
#     masked_embeddings = last_hidden_state * mask
#     sum_embeddings = masked_embeddings.sum(dim=1)
#     sum_mask = mask.sum(dim=1).clamp(min=1e-9)
#     return sum_embeddings / sum_mask


# def generate_embeddings_from_summary_csv(
#     input_csv: str = SUMMARY_OUT,
#     out_parquet: str = EMBED_OUT_PARQUET,
#     out_npy: str = EMBED_OUT_NPY,
#     model_name: str = EMBED_MODEL_NAME,
#     batch_size: int = EMBED_BATCH_SIZE,
#     max_length: int = EMBED_MAX_LENGTH,
# ) -> None:
#     import torch
#     import torch.nn.functional as F

#     df = pd.read_csv(input_csv)
#     required_cols = {"date", "industry_id", "summary"}
#     missing = required_cols - set(df.columns)
#     if missing:
#         raise ValueError(f"{input_csv} 缺少列: {sorted(missing)}；请先运行 Step2 生成摘要文件。")

#     df = df[["date", "industry_id", "summary"]].copy()
#     df["summary"] = df["summary"].fillna("").astype(str).str.strip()
#     df = df[df["summary"] != ""].reset_index(drop=True)
#     print(f"样本数: {len(df)}")

#     device = "cuda" if torch.cuda.is_available() else "cpu"
#     tokenizer = AutoTokenizer.from_pretrained(model_name, trust_remote_code=True)
#     model = AutoModel.from_pretrained(
#         model_name,
#         trust_remote_code=True,
#         torch_dtype=torch.float16 if device == "cuda" else torch.float32,
#     ).to(device)
#     model.eval()

#     all_embeddings = []
#     for start in tqdm(range(0, len(df), batch_size), desc="Encoding"):
#         batch_texts = df["summary"].iloc[start : start + batch_size].tolist()
#         inputs = tokenizer(
#             batch_texts,
#             padding=True,
#             truncation=True,
#             max_length=max_length,
#             return_tensors="pt",
#         )
#         inputs = {k: v.to(device) for k, v in inputs.items()}

#         with torch.no_grad():
#             outputs = model(**inputs)
#             if hasattr(outputs, "last_hidden_state"):
#                 embeddings = mean_pooling(outputs.last_hidden_state, inputs["attention_mask"])
#             elif hasattr(outputs, "embeddings"):
#                 embeddings = outputs.embeddings
#             else:
#                 raise ValueError("模型输出中未找到 last_hidden_state 或 embeddings，请检查模型接口。")

#             embeddings = F.normalize(embeddings, p=2, dim=1)

#         all_embeddings.append(embeddings.detach().cpu().numpy())

#     all_embeddings = np.vstack(all_embeddings)
#     print("embedding shape:", all_embeddings.shape)

#     np.save(out_npy, all_embeddings)
#     save_df = df.copy()
#     save_df["embedding"] = [vec.tolist() for vec in all_embeddings]
#     save_df.to_parquet(out_parquet, index=False)

#     print(f"已保存到: {out_npy}")
#     print(f"已保存到: {out_parquet}")


# def run_step3() -> None:
#     generate_embeddings_from_summary_csv()


# # ========================
# # Step 4: FinBERT 情绪
# # ========================

# def add_news_count_to_embeddings(
#     embeddings_parquet: str = EMBED_OUT_PARQUET,
#     news_count_csv: str = NEWS_COUNT_OUT,
# ) -> pd.DataFrame:
#     emb = pd.read_parquet(embeddings_parquet)
#     cnt = pd.read_csv(news_count_csv)

#     emb = emb.copy()
#     emb["date"] = pd.to_datetime(emb["date"])
#     emb["industry_id"] = emb["industry_id"].astype(str)

#     cnt = cnt.copy()
#     cnt["date"] = pd.to_datetime(cnt["date"])
#     cnt["industry_id"] = cnt["industry_id"].astype(str)

#     merged = emb.merge(cnt, on=["date", "industry_id"], how="left")
#     merged["news_count"] = merged["news_count"].fillna(0).astype(int)
#     return merged


# def compute_sentiment_features(
#     embeddings_parquet: str = EMBED_OUT_PARQUET,
#     news_count_csv: str = NEWS_COUNT_OUT,
#     out_csv: str = SENTIMENT_OUT,
#     model_name: str = SENTIMENT_MODEL_NAME,
# ) -> pd.DataFrame:
#     df = add_news_count_to_embeddings(embeddings_parquet, news_count_csv)

#     classifier = pipeline("text-classification", model=model_name)
#     label_map = {"positive": 1, "neutral": 0, "negative": -1}

#     df["summary"] = df["summary"].fillna("").astype(str)
#     results = classifier(df["summary"].tolist())

#     df["label"] = [x["label"].lower() for x in results]
#     df["prob"] = [x["score"] for x in results]
#     df["sentiment"] = df["label"].map(label_map).fillna(0).astype(int)
#     df["sentiment_score"] = df["sentiment"] * df["prob"]

#     daily_features = df[
#         [
#             "date",
#             "industry_id",
#             "summary",
#             "news_count",
#             "label",
#             "prob",
#             "sentiment",
#             "sentiment_score",
#             "embedding",
#         ]
#     ].copy()

#     daily_features.to_csv(out_csv, index=False, encoding="utf-8-sig")
#     print(f"已保存日度特征到: {out_csv}")
#     return daily_features


# def run_step4() -> None:
#     compute_sentiment_features()


# def main():
#     parser = argparse.ArgumentParser(description="新闻处理流水线：摘要/计数 -> embedding -> 情绪特征")
#     parser.add_argument("--step2", action="store_true", help="运行 Step2：DeepSeek 摘要 + 每日×行业新闻数量")
#     parser.add_argument("--step3", action="store_true", help="运行 Step3：Qwen embedding（基于 Step2 摘要文件）")
#     parser.add_argument("--step4", action="store_true", help="运行 Step4：FinBERT 情绪（基于 Step3 parquet + Step2 计数）")
#     parser.add_argument("--no-summary", action="store_true", help="Step2 只生成 NewsCount，不调用 DeepSeek 摘要")
#     args = parser.parse_args()

#     # 默认只跑 Step2（避免一运行就下载大模型/跑很久）
#     run2 = args.step2 or (not args.step3 and not args.step4)
#     run3 = args.step3
#     run4 = args.step4

#     if run2:
#         run_step2(generate_summary=not args.no_summary)
#     if run3:
#         run_step3()
#     if run4:
#         run_step4()


# if __name__ == "__main__":
#     main()

# """
# import time
# from datetime import datetime
# from dateutil.parser import parse as parse_dt
# import numpy as np
# import pandas as pd
# import matplotlib.pyplot as plt
# from transformers import pipeline
# import requests
# from tqdm import tqdm
# # --------------步骤二，通过deepseekAPI来获取新闻摘要以及每天每个股票行业板块涉及到的新闻数量-------------------------
# # ========================
# # 1. 基本配置
# # ========================

# DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
# DEEPSEEK_BASE_URL = "https://api.deepseek.com"
# DEEPSEEK_MODEL = "deepseek-chat"

# DATA_DIR = "Data"
# NEWS_CSV = os.path.join(DATA_DIR, "FilteredNews_2011-2024.csv")
# INDUSTRY_KEYWORDS_JSON = os.path.join(DATA_DIR, "industry_keywords_zh.json")

# # 你的 csv 列名（改成你自己的）
# NEWS_TIME_COL = "Date"   # 时间列
# NEWS_News_COL = "News"     # 内容列
# NEWS_Source_COL = "Source"       # 来源列

# START_DATE = None  # 例如 "2020-01-01"
# END_DATE = None    # 例如 "2020-12-31"

# MAX_ARTICLES_PER_GROUP = 20
# MAX_CHARS_PER_ARTICLE = 500

# # ========================
# # 2. 来源可信度梯度
# # ========================

# Source_TIERS = {
#     "新华社": {"tier": 1, "label": "高", "weight": 1.0},
#     "人民日报": {"tier": 1, "label": "高", "weight": 1.0},
#     "第一财经": {"tier": 2, "label": "中", "weight": 0.7},
#     "新浪财经": {"tier": 3, "label": "低", "weight": 0.4},
#     "网易财经": {"tier": 3, "label": "低", "weight": 0.4},
# }

# def get_Source_info(src: str):
#     if src in Source_TIERS:
#         return Source_TIERS[src]
#     return {"tier": 2, "label": "中", "weight": 0.6}


# # ========================
# # 3. DeepSeek API
# # ========================

# def call_deepseek(prompt: str, temperature: float = 0.3, max_tokens: int = 512) -> str:
#     if not DEEPSEEK_API_KEY or DEEPSEEK_API_KEY == "YOUR_DEEPSEEK_API_KEY_HERE":
#         raise ValueError("请先配置 DEEPSEEK_API_KEY")

#     url = f"{DEEPSEEK_BASE_URL}/v1/chat/completions"   # 必须加 /v1 !!!

#     headers = {
#         "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
#         "Content-Type": "application/json",
#     }

#     payload = {
#         "model": DEEPSEEK_MODEL,
#         "messages": [
#             {"role": "system", "content": "你是一名金融研究员……"},
#             {"role": "user", "content": prompt},
#         ],
#         "temperature": temperature,
#         "max_tokens": max_tokens,
#     }

#     resp = requests.post(url, headers=headers, json=payload, timeout=120)

#     # 如果返回 400，为你打印错误内容
#     if resp.status_code != 200:
#         print("DeepSeek API 返回错误：", resp.text)

#     resp.raise_for_status()
#     data = resp.json()
#     return data["choices"][0]["message"]["content"].strip()


# # ========================
# # 4. 行业关键词 & 映射
# # ========================

# # 行业中文名 -> 编号（0-10）
# INDUSTRY_NAME_TO_ID = {
#     "工业": 0,
#     "信息技术": 1,
#     "公用事业": 2,
#     "可选消费": 3,
#     "原材料": 4,
#     "医药卫生": 5,
#     "金融": 6,
#     "能源": 7,
#     "主要消费": 8,
#     "通信服务": 9,
#     "房地产": 10,
# }

# def load_industry_keywords(path: str):
#     """
#     读取类似这样的 json：
#     {
#         "工业": ["制造业", "装备制造", ...],
#         "信息技术": ["信息技术", "软件", ...],
#         ...
#     }
#     返回 {行业中文名: [关键词列表]}
#     """
#     with open(path, "r", encoding="utf-8") as f:
#         kw = json.load(f)

#     cleaned = {}
#     for industry_name, keywords in kw.items():
#         if isinstance(keywords, str):
#             cleaned[industry_name] = [keywords]
#         else:
#             cleaned[industry_name] = list(dict.fromkeys(keywords))  # 去重
#     return cleaned


# def detect_industries_for_text(text: str, kw_dict: dict) -> list:
#     """
#     根据关键词匹配出命中的“行业中文名”列表，
#     后面再用 INDUSTRY_NAME_TO_ID 映射成 0-10 的编号。
#     """
#     if not isinstance(text, str) or not text:
#         return []

#     hits = []
#     for industry_name, keywords in kw_dict.items():
#         for kw in keywords:
#             if kw and kw in text:
#                 hits.append(industry_name)
#                 break
#     return hits


# # ========================
# # 5. 主流程
# # ========================

# def main():
#     print("读取新闻数据中...")
#     news_df = pd.read_csv(NEWS_CSV)
#     print("新闻表列名：", list(news_df.columns))

#     df = news_df.rename(
#         columns={
#             NEWS_TIME_COL: "Date",
#             NEWS_News_COL: "News",
#             NEWS_Source_COL: "Source",
#         }
#     )

#     df["Date"] = df["Date"].apply(lambda x: parse_dt(str(x)))
#     df["date"] = df["Date"].dt.date

#     if START_DATE is not None:
#         start = parse_dt(START_DATE).date()
#         df = df[df["date"] >= start]

#     if END_DATE is not None:
#         end = parse_dt(END_DATE).date()
#         df = df[df["date"] <= end]

#     df["News"] = df["News"].astype(str).str.strip()
#     df["Source"] = df["Source"].astype(str).str.strip()

#     print(f"过滤后新闻条数: {len(df)}")

#     # 5.2 读取行业关键词（key 是行业中文名）
#     print("读取行业关键词...")
#     industry_keywords = load_industry_keywords(INDUSTRY_KEYWORDS_JSON)
#     print("行业数量：", len(industry_keywords), " -> ", list(industry_keywords.keys()))

#     # 5.3 每条新闻匹配“行业中文名”列表
#     print("为每条新闻匹配行业（中文名）...")
#     df["industry_names"] = df["News"].apply(
#         lambda txt: detect_industries_for_text(txt, industry_keywords)
#     )

#     df = df[df["industry_names"].map(len) > 0].copy()
#     print(f"命中任一行业的新闻条数: {len(df)}")

#     # 一条新闻命中多行业时拆成多行
#     df = df.explode("industry_names").rename(columns={"industry_names": "industry_name"})

#     # 映射成行业编号
#     df["industry_id"] = df["industry_name"].map(INDUSTRY_NAME_TO_ID)

#     # 如果有没映射上的，打印出来方便你检查
#     unknown = df[df["industry_id"].isna()]["industry_name"].unique()
#     if len(unknown) > 0:
#         print("警告：以下行业中文名没有在 INDUSTRY_NAME_TO_ID 中找到映射，请检查：", unknown)

#     df = df.dropna(subset=["industry_id"]).copy()
#     df["industry_id"] = df["industry_id"].astype(int).astype(str)  # 统一为字符串方便 groupby

#     print(f"拆分后总行数（新闻×行业）：{len(df)}")

#     # 5.4 统计每日×行业的新闻数量，并保存
#     news_count_df = (
#         df.groupby(["date", "industry_id"], as_index=False)
#         .size()
#         .rename(columns={"size": "news_count"})
#     )
#     news_count_path = os.path.join(DATA_DIR, "NewsCount_Day&Industry.csv")
#     news_count_df.to_csv(news_count_path, index=False, encoding="utf-8-sig")
#     print(f"已保存每日×行业新闻数量到: {news_count_path}")

#     # 5.4 按 (date, industry_id) 分组生成摘要
#     groups = df.groupby(["date", "industry_id"])
#     print(f"需要生成摘要的 (date, industry_id) 组合数量：{len(groups)}")

#     results = []

#     for (date, industry_id), group in tqdm(groups, desc="生成行业日度摘要"):
#         group_sorted = group.sort_values("Date")
#         group_sampled = group_sorted.head(MAX_ARTICLES_PER_GROUP).copy()

#         news_items_text = []
#         for _, row in group_sampled.iterrows():
#             src = row["Source"]
#             src_info = get_Source_info(src)
#             cred_label = src_info["label"]

#             News = row["News"]
#             if len(News) > MAX_CHARS_PER_ARTICLE:
#                 News = News[:MAX_CHARS_PER_ARTICLE] + "……"

#             ts_str = row["Date"].strftime("%Y-%m-%d %H:%M")

#             news_items_text.append(
#                 f"【来源：{src}｜可信度：{cred_label}】（时间：{ts_str}）{News}"
#             )

#         news_block = "\n\n".join(
#             f"{idx+1}. {txt}" for idx, txt in enumerate(news_items_text)
#         )

#         prompt = (
#             f"请你针对 **行业编号 {industry_id}**，在日期 **{date}** 的新闻，"
#             f"输出一个不超过 200 字的中文简短摘要，用于后续资产定价模型。\n\n"
#             f"请你：\n"
#             f"1. 概括当日该行业面临的主要政策、宏观与公司层面的事件；\n"
#             f"2. 明确指出这些信息对该行业股价整体的潜在影响方向（利好/利空/中性），并简单解释原因；\n"
#             f"3. 若不同来源之间存在明显矛盾或不确定性，请说明不确定性来源；\n"
#             f"4. 在综合判断时，要对新华社、人民日报给予最高权重，其次是第一财经，"
#             f"新浪财经和网易财经权重最低；如存在冲突，以高可信度来源为主。\n\n"
#             f"下面是该行业在 {date} 的新闻列表：\n\n"
#             f"{news_block}\n\n"
#             f"请直接给出一段连续的摘要文字，不要罗列新闻条目。"
#         )

#         try:
#             summary = call_deepseek(prompt)
#         except Exception as e:
#             print(f"\n[错误] 日期 {date}, 行业 {industry_id} 调用 DeepSeek 失败：{e}")
#             summary = f"[调用失败] {e}"

#         results.append(
#             {
#                 "date": date,
#                 "industry_id": industry_id,
#                 "num_articles_used": len(group_sampled),
#                 "summary": summary,
#             }
#         )

#         time.sleep(0.3)

#     out_df = pd.DataFrame(results)
#     out_path = os.path.join(DATA_DIR, "IndustryNewsSummary_daily.csv")
#     out_df.to_csv(out_path, index=False, encoding="utf-8-sig")
#     print(f"\n已保存行业日度新闻摘要到: {out_path}")


# # --------------步骤三，通过huggingface中的Qwen/Qwen3-Embedding-0.6B来获取各个新闻的embeding----------------------
# import os
# import numpy as np
# import pandas as pd
# import torch
# import torch.nn.functional as F
# from tqdm import tqdm
# from transformers import AutoTokenizer, AutoModel

# # =========================
# # 1. 配置
# # =========================
# INPUT_CSV = "Data/IndustryNewsSummary.csv"   # 你的输入文件
# OUTPUT_PARQUET = "industry_news_embeddings.parquet"
# OUTPUT_NPY = "industry_news_embeddings.npy"

# MODEL_NAME = "Qwen/Qwen3-Embedding-0.6B"
# TEXT_COL = "Summary"
# DATE_COL = "Date"
# IND_COL = "Industry_id"

# BATCH_SIZE = 16
# MAX_LENGTH = 1024   # 如显存不足可改成 512
# DEVICE = "cuda" if torch.cuda.is_available() else "cpu"

# # =========================
# # 2. 读取数据
# # =========================
# df = pd.read_csv(INPUT_CSV)

# # 基本清洗
# df = df[[DATE_COL, IND_COL, TEXT_COL]].copy()
# df[TEXT_COL] = df[TEXT_COL].fillna("").astype(str).str.strip()
# df = df[df[TEXT_COL] != ""].reset_index(drop=True)

# print(f"样本数: {len(df)}")

# # =========================
# # 3. 加载模型
# # =========================
# tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME, trust_remote_code=True)
# model = AutoModel.from_pretrained(
#     MODEL_NAME,
#     trust_remote_code=True,
#     torch_dtype=torch.float16 if DEVICE == "cuda" else torch.float32
# ).to(DEVICE)
# model.eval()

# # =========================
# # 4. 池化函数：mean pooling
# # =========================
# def mean_pooling(last_hidden_state, attention_mask):
#     """
#     last_hidden_state: [B, L, H]
#     attention_mask:    [B, L]
#     """
#     mask = attention_mask.unsqueeze(-1).expand(last_hidden_state.size()).float()
#     masked_embeddings = last_hidden_state * mask
#     sum_embeddings = masked_embeddings.sum(dim=1)
#     sum_mask = mask.sum(dim=1).clamp(min=1e-9)
#     return sum_embeddings / sum_mask

# # =========================
# # 5. 批量编码
# # =========================
# all_embeddings = []

# for start in tqdm(range(0, len(df), BATCH_SIZE), desc="Encoding"):
#     batch_texts = df[TEXT_COL].iloc[start:start+BATCH_SIZE].tolist()

#     inputs = tokenizer(
#         batch_texts,
#         padding=True,
#         truncation=True,
#         max_length=MAX_LENGTH,
#         return_tensors="pt"
#     )

#     inputs = {k: v.to(DEVICE) for k, v in inputs.items()}

#     with torch.no_grad():
#         outputs = model(**inputs)

#         # 某些 embedding 模型返回 last_hidden_state
#         if hasattr(outputs, "last_hidden_state"):
#             embeddings = mean_pooling(outputs.last_hidden_state, inputs["attention_mask"])
#         # 某些模型直接返回 sentence embeddings
#         elif hasattr(outputs, "embeddings"):
#             embeddings = outputs.embeddings
#         else:
#             raise ValueError("模型输出中未找到 last_hidden_state 或 embeddings，请检查模型接口。")

#         # L2 归一化，便于后续余弦相似度/检索
#         embeddings = F.normalize(embeddings, p=2, dim=1)

#     all_embeddings.append(embeddings.detach().cpu().numpy())

# all_embeddings = np.vstack(all_embeddings)
# print("embedding shape:", all_embeddings.shape)

# # =========================
# # 6. 保存结果
# # =========================

# # 保存为 .npy
# np.save(OUTPUT_NPY, all_embeddings)

# # 保存为 parquet（每行保留原始键 + embedding）
# save_df = df.copy()
# save_df["embedding"] = [vec.tolist() for vec in all_embeddings]
# save_df.to_parquet(OUTPUT_PARQUET, index=False)

# print(f"已保存到: {OUTPUT_NPY}")
# print(f"已保存到: {OUTPUT_PARQUET}")


# # --------------步骤四，通过FinBert来获取新闻的情感倾向----------------------
# news_embedings = pd.read_parquet('industry_news_embeddings.parquet')
# news_count = pd.read_csv("Data/NewsCount_Day&Industry.csv")
# news_embedings["Date"] = pd.to_datetime(news_embedings["Date"])
# news_count["date"] = pd.to_datetime(news_count["date"])

# news_embedings = news_embedings.merge(
#     news_count[["date", "industry_id", "news_count"]],
#     left_on=["Date", "Industry_id"],
#     right_on=["date", "industry_id"],
#     how="left"
# ).drop(columns=["date", "industry_id"])

# news_embedings["news_count"] = news_embedings["news_count"].fillna(0)

# # 1. 加载中文金融情绪模型
# classifier = pipeline(
#     "text-classification",
#     model="yiyanghkust/finbert-tone-chinese"
# )

# # 2. 标签映射
# label_map = {
#     "positive": 1,
#     "neutral": 0,
#     "negative": -1
# }

# # 3. 复制一份数据，避免直接改原表
# df = news_embedings.copy()

# # 4. 确保 Summary 是字符串，防止空值或非字符串报错
# df["Summary"] = df["Summary"].fillna("").astype(str)

# # 5. 批量做情绪分类
# results = classifier(df["Summary"].tolist())

# # 6. 提取标签和概率
# df["label"] = [x["label"].lower() for x in results]
# df["prob"] = [x["score"] for x in results]

# # 7. 映射成数值情绪
# df["sentiment"] = df["label"].map(label_map)

# # 8. 构造连续情绪分数
# df["sentiment_score"] = df["sentiment"] * df["prob"]

# # 9. 如果 Date 不是时间格式，先转一下
# df["Date"] = pd.to_datetime(df["Date"])

# # 10. 如果你这张表已经是一行 = 一个行业-日期摘要
# # 那其实可以直接保留，不一定非要再 groupby
# daily_features = df[[
#     "Date", "Industry_id", "Summary", "news_count", "label", "prob", "sentiment", "sentiment_score"
# ]].copy()

# print(daily_features.head())

# if __name__ == "__main__":
#     main()
