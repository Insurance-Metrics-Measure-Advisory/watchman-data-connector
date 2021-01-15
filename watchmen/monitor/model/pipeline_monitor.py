import datetime
from typing import List

# from bson import timestamp
from datetime import datetime
from pydantic import BaseModel

from watchmen.common.mongo_model import MongoModel


class UnitStatus(BaseModel):
    name:str=None
    complete_time:datetime=None


class StageStatus(BaseModel):
    name:str=None
    complete_time:datetime=None
    units:List[UnitStatus]=[]


class PipelineRunStatus(MongoModel):
    status :str=None
    name :str=None
    uid:str=None
    complete_time :datetime=None
    stages:List[StageStatus]=[]
    error :str=None









