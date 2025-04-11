from pydantic import BaseModel
from typing import Optional

class DirectLoginConfig(BaseModel):
    username: str
    password: str
    consumer_key: str
    base_uri: Optional[str]