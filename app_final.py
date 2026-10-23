"""Учебный сервис опросов. Все данные хранятся в памяти процесса."""

from itertools import count
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, StringConstraints, model_validator

import os

from dotenv import load_dotenv
load_dotenv(Path(__file__).with_name(".env"), override=False)

app = FastAPI(title="Опросы")
ROOT = Path(__file__).resolve().parent
polls: dict[int, dict] = {}
poll_ids = count(1)

Question = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
OptionText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]


class PollCreate(BaseModel):
    question: Question
    options: list[OptionText] = Field(min_length=2, max_length=8)

    @model_validator(mode="after")
    def unique_options(self):
        if len({text.casefold() for text in self.options}) != len(self.options):
            raise ValueError("Варианты ответа должны отличаться друг от друга")
        return self


class VoteCreate(BaseModel):
    option_id: int = Field(ge=1, strict=True)


class OptionView(BaseModel):
    id: int
    text: str


class PollView(BaseModel):
    id: int
    question: str
    options: list[OptionView]


class OptionResult(OptionView):
    votes: int
    percent: float


class PollResults(BaseModel):
    id: int
    question: str
    total_votes: int
    options: list[OptionResult]


def find_poll(poll_id: int) -> dict:
    poll = polls.get(poll_id)
    if poll is None:
        raise HTTPException(status_code=404, detail="Опрос не найден")
    return poll


def results_for(poll: dict) -> dict:
    total = sum(poll["votes"].values())
    options = []
    for option in poll["options"]:
        votes = poll["votes"][option["id"]]
        options.append({
            **option,
            "votes": votes,
            "percent": round(votes / total * 100, 1) if total else 0.0,
        })
    return {
        "id": poll["id"],
        "question": poll["question"],
        "total_votes": total,
        "options": options,
    }


@app.get("/", include_in_schema=False)
async def home():
    return FileResponse(ROOT / "index.html")


@app.post("/polls", response_model=PollView, status_code=201)
async def create_poll(data: PollCreate):
    poll_id = next(poll_ids)
    options = [{"id": i, "text": text} for i, text in enumerate(data.options, start=1)]
    poll = {
        "id": poll_id,
        "question": data.question,
        "options": options,
        "votes": {option["id"]: 0 for option in options},
    }
    polls[poll_id] = poll
    return poll


@app.get("/polls", response_model=list[PollView])
async def list_polls():
    return list(reversed(list(polls.values())))


@app.get("/polls/{poll_id}", response_model=PollView)
async def get_poll(poll_id: int):
    return find_poll(poll_id)


@app.post("/polls/{poll_id}/votes", response_model=PollResults)
async def vote(poll_id: int, data: VoteCreate):
    poll = find_poll(poll_id)
    if data.option_id not in poll["votes"]:
        raise HTTPException(status_code=422, detail="Такого варианта ответа нет в этом опросе")
    poll["votes"][data.option_id] += 1
    return results_for(poll)


@app.get("/polls/{poll_id}/results", response_model=PollResults)
async def get_results(poll_id: int):
    return results_for(find_poll(poll_id))


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/version")
async def version():
    return {"version": os.getenv("APP_VERSION", "0.1.0")}
