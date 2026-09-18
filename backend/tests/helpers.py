"""Тестийн хуваалцсан туслахууд.

`activate` нь хоёр шаттай баталгаажуулалтыг бүтнээр гүйцэтгэнэ — тест бүр
өөрийн хувилбарыг бичвэл урсгал өөрчлөгдөхөд зөрүү үүснэ.
"""
from __future__ import annotations


async def activate(client, *, note: str = "тест"):
    first = await client.post("/api/v1/system/activate", json={})
    if first.status_code != 409 or first.json().get("code") != "confirmation_required":
        return first
    token = first.json()["confirmation"]["token"]
    return await client.post(
        "/api/v1/system/activate", json={"confirmation_token": token, "note": note}
    )


async def wind_down(client, *, reason: str = "тест: унтраах бэлтгэл"):
    return await client.post("/api/v1/system/wind-down", json={"reason": reason})
