from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Endpoints:
    semester: str = "/Xsxk/queryXkdqXnxq"
    courses: str = "/Xsxk/queryKxrw"
    enroll: str = "/Xsxk/addGouwuche"
    referer: str = "/Xsxk/query/1"

    @classmethod
    def from_dict(cls, data: dict) -> "Endpoints":
        fields = {f: str(data[f]) for f in cls.__dataclass_fields__ if f in data}
        return cls(**fields)
