"""通过 python -m app 启动 FinPortfolio 后端。"""

import uvicorn


if __name__ == "__main__":
    uvicorn.run("app.main:app", host="127.0.0.1", port=8001)
