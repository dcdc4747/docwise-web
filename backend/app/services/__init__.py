"""只读领域服务（routers 与 agent 的 packs 共用）。

规矩一条：**services → models/db；routers → services；packs → services**。
服务不碰 HTTP、不读请求、不抛 HTTPException（返回空/None 让上层决定怎么说）。
"""
