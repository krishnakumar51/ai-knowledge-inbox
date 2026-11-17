from datetime import datetime

from pydantic import BaseModel, field_serializer

from app.core.time import as_user_timezone


class APIModel(BaseModel):
    @field_serializer("*", when_used="json")
    def serialize_ist_datetimes(self, value):
        if isinstance(value, datetime):
            return as_user_timezone(value).isoformat()
        return value


class ErrorDetail(APIModel):
    code: str
    message: str


class ErrorResponse(APIModel):
    error: ErrorDetail
