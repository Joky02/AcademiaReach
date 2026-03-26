"""FastAPI 应用入口"""

from __future__ import annotations

import asyncio
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.core.database import init_db
from backend.api.routes import router
from backend.services.reply_tracker import start_reply_polling

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="套磁 Agent 系统",
    description="全自动博士套磁系统 API",
    version="1.0.0",
)

# CORS — 允许前端开发服务器访问
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000", "*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


@app.on_event("startup")
async def startup():
    logger.info("正在初始化数据库...")
    await init_db()
    logger.info("数据库初始化完成")
    # 启动回复轮询后台任务
    asyncio.create_task(start_reply_polling())
    logger.info("回复跟踪轮询已启动")


@app.get("/")
async def root():
    return {"message": "套磁 Agent 系统 API", "docs": "/docs"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.main:app", host="0.0.0.0", port=8000, reload=True)
