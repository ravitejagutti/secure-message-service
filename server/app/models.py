from pydantic import BaseModel, Field


class MessageCreate(BaseModel):
    content: str = Field(min_length=1, max_length=10_000)


class Message(BaseModel):
    id: int
    content: str
    author: str
    created_at: str
    redactions: dict[str, int]
