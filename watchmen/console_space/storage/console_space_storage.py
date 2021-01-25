from watchmen.common.snowflake.snowflake import get_surrogate_key
from watchmen.common.storage.engine.storage_engine import get_client
from watchmen.console_space.model.console_space import ConsoleSpace

db = get_client()
console_space_collection = db.get_collection('console_space')


def create_console_space(console_space: ConsoleSpace):
    console_space_collection.insert(console_space.dict())
    return console_space


def update_console_space(console_space: ConsoleSpace):
    console_space_collection.update_one({"connectId": console_space.connectId}, {"$set": console_space.dict()})
    return console_space


def save_console_space(console_space: ConsoleSpace):
    if console_space.connectId is None:
        console_space.connectId = get_surrogate_key()
        return create_console_space(console_space)
    else:
        return update_console_space(console_space)


def load_console_space_by_id(connect_id: str):
    result = console_space_collection.find_one({"connectId": connect_id})
    return ConsoleSpace.parse_obj(result)


def delete_console_space_storage(connect_id):
    console_space_collection.delete_one({"connectId": connect_id})


def load_console_space_list_by_user(user_id):
    result = console_space_collection.find({"userId": user_id})
    return list(result)


def load_console_space_by_subject_id(subject_id):
    result = console_space_collection.find_one({"subjectIds": subject_id})
    return ConsoleSpace.parse_obj(result)


def rename_console_space_by_id(connect_id, name):
    console_space_collection.update_one({"connectId": connect_id}, {"$set": {"name": name}})
