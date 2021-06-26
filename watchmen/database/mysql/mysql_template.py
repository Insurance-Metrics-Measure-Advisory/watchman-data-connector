import datetime
import json
import logging
import operator
import time
from operator import eq

from sqlalchemy import update, Table, and_, or_, delete, Column, DECIMAL, String, CLOB, desc, asc, \
    text, func, DateTime, BigInteger, Date, Integer, JSON
from sqlalchemy.dialects.mysql import insert
from sqlalchemy.exc import NoSuchTableError
from sqlalchemy.future import select
from sqlalchemy.orm import Session

from watchmen.common.data_page import DataPage
from watchmen.database.mysql.mysql_engine import engine, dumps
from watchmen.database.mysql.mysql_table_definition import get_table_by_name, metadata, get_topic_table_by_name
from watchmen.database.mysql.mysql_utils import parse_obj, count_table, count_topic_data_table
from watchmen.database.storage.utils.table_utils import get_primary_key
from watchmen.common.snowflake.snowflake import get_surrogate_key
from watchmen.common.utils.data_utils import build_data_pages
from watchmen.common.utils.data_utils import convert_to_dict
from watchmen.monitor.model.pipeline_monitor import PipelineRunStatus

log = logging.getLogger("app." + __name__)

log.info("mysql template initialized")


def build_raw_sql_with_json_table(check_result, where, name):
    if check_result["table_name"] == "spaces" and check_result["column_name"] == "groupIds":
        json_table_stmt = "select s.*, jt.group_id " \
                          "from spaces s ,json_table(groupids,'$[*]' " \
                          "COLUMNS (group_id varchar2(60) PATH '$[*]') ) as jt"
        where_stmt = ""
        for id_ in where["groupIds"]["in"]:
            if where_stmt == "":
                where_stmt = "(" + id_
            else:
                where_stmt = where_stmt + ", " + id_
        where_stmt = where_stmt + ")"
        stmt = "select t.* from (" + json_table_stmt + \
               ") t where t.group_id in " + where_stmt
        return stmt

    if check_result["table_name"] == "user_groups" and check_result["column_name"] == "userIds":
        json_table_stmt = "select s.*, jt.user_id " \
                          "from user_groups s ,json_table(userids,'$[*]' " \
                          "COLUMNS (user_id varchar2(60) PATH '$[*]') ) as jt"
        where_stmt = ""
        for id_ in where["userIds"]["in"]:
            if where_stmt == "":
                where_stmt = "(" + id_
            else:
                where_stmt = where_stmt + ", " + id_
        where_stmt = where_stmt + ")"
        stmt = "select t.* from (" + json_table_stmt + \
               ") t where t.user_id in " + where_stmt
        return stmt

    if check_result["table_name"] == "user_groups" and check_result["column_name"] == "spaceIds":
        json_table_stmt = "select s.*, jt.space_id " \
                          "from user_groups s ,json_table(spaceids,'$[*]' " \
                          "COLUMNS (space_id varchar2(60) PATH '$[*]') ) as jt"
        where_stmt = ""
        for id_ in where["spaceIds"]["in"]:
            if where_stmt == "":
                where_stmt = "(" + id_
            else:
                where_stmt = where_stmt + ", " + id_
        where_stmt = where_stmt + ")"
        stmt = "select t.* from (" + json_table_stmt + \
               ") t where t.space_id in " + where_stmt
        return stmt

    if check_result["table_name"] == "users" and check_result["column_name"] == "groupIds":
        json_table_stmt = "select s.*, jt.group_id " \
                          "from users s ,json_table(groupids,'$[*]' " \
                          "COLUMNS (group_id varchar2(60) PATH '$[*]') ) as jt"
        where_stmt = ""
        for id_ in where["groupIds"]["in"]:
            if where_stmt == "":
                where_stmt = "(" + id_
            else:
                where_stmt = where_stmt + ", " + id_
        where_stmt = where_stmt + ")"
        stmt = "select t.* from (" + json_table_stmt + \
               ") t where t.group_id in " + where_stmt
        return stmt


def check_where_column_type(name, where):
    if name == "spaces":
        if "groupIds" in where:
            return {"table_name": "spaces", "column_name": "groupIds"}
    elif name == "user_groups":
        if "userIds" in where:
            return {"table_name": "user_groups", "column_name": "userIds"}
        if "spaceIds" in where:
            return {"table_name": "user_groups", "column_name": "spaceIds"}
    elif name == "users":
        if "groupIds" in where:
            return {"table_name": "users", "column_name": "groupIds"}
    else:
        return None


def build_mysql_where_expression(table, where):
    for key, value in where.items():
        if key == "and" or key == "or":
            if isinstance(value, list):
                filters = []
                for express in value:
                    result = build_mysql_where_expression(table, express)
                    filters.append(result)
            if key == "and":
                return and_(*filters)
            if key == "or":
                return or_(*filters)
        else:
            if isinstance(value, dict):
                for k, v in value.items():
                    if k == "=":
                        return table.c[key.lower()] == v
                    if k == "!=":
                        return operator.ne(table.c[key.lower()], v)
                    if k == "like":
                        if v != "" or v != '' or v is not None:
                            return table.c[key.lower()].like("%" + v + "%")
                    if k == "in":
                        if isinstance(table.c[key.lower()].type, JSON):
                            # not support clob to operate in here
                            raise ValueError("the json type field \"{0}\" of table \"{1}\" , should not support "
                                             "\"in\" of where expression".format(key.lower(), table.name))
                        else:
                            if isinstance(v, list):
                                if len(v) != 0:
                                    return table.c[key.lower()].in_(v)
                    if k == ">":
                        return table.c[key.lower()] > v
                    if k == ">=":
                        return table.c[key.lower()] >= v
                    if k == "<":
                        return table.c[key.lower()] < v
                    if k == "<=":
                        return table.c[key.lower()] <= v
                    if k == "between":
                        if (isinstance(v, tuple)) and len(v) == 2:
                            return table.c[key.lower()].between(check_value_type(v[0]), check_value_type(v[1]))
            else:
                return table.c[key.lower()] == value


def build_mysql_updates_expression_for_insert(table, updates):
    new_updates = {"id_": get_surrogate_key()}
    for key, value in updates.items():
        if key == "$inc":
            if isinstance(value, dict):
                for k, v in value.items():
                    new_updates[k.lower()] = v
        elif key == "$set":
            if isinstance(value, dict):
                for k, v in value.items():
                    new_updates[k.lower()] = v
        if isinstance(value, dict):
            for k, v in value.items():
                if k == "_sum":
                    new_updates[key.lower()] = v
                elif k == "_count":
                    new_updates[key.lower()] = v
        else:
            new_updates[key] = value
    return new_updates


def build_mysql_updates_expression_for_update(table, updates):
    new_updates = {}
    for key, value in updates.items():
        if key == "$inc":
            if isinstance(value, dict):
                for k, v in value.items():
                    key = k.lower()
                    new_updates[key] = operator.add(table.c[key], v)
        elif key == "$set":
            if isinstance(value, dict):
                for k, v in value.items():
                    new_updates[k.lower()] = v
        if isinstance(value, dict):
            for k, v in value.items():
                if k == "_sum":
                    new_updates[key.lower()] = text(f'{key.lower()} + {v}')
                elif k == "_count":
                    new_updates[key.lower()] = text(f'{key.lower()} + {v}')
        else:
            new_updates[key] = value
    return new_updates


def build_mysql_order(table, order_: list):
    result = []
    if order_ is None:
        return result
    else:
        for item in order_:
            if isinstance(item, tuple):
                if item[1] == "desc":
                    new_ = desc(table.c[item[0].lower()])
                    result.append(new_)
                if item[1] == "asc":
                    new_ = asc(table.c[item[0].lower()])
                    result.append(new_)
        return result


def insert_one(one, model, name):
    table = get_table_by_name(name)
    one_dict: dict = convert_to_dict(one)
    values = {}
    for key, value in one_dict.items():
        if isinstance(table.c[key.lower()].type, JSON):
            if value is not None:
                # values[key.lower()] = dumps(value)
                values[key.lower()] = value
            else:
                values[key.lower()] = None
        else:
            values[key.lower()] = value
    stmt = insert(table).values(values)
    with engine.connect() as conn:
        with conn.begin():
            conn.execute(stmt)
    return model.parse_obj(one)


def insert_all(data, model, name):
    table = get_table_by_name(name)
    stmt = insert(table)
    value_list = []
    for item in data:
        instance_dict: dict = convert_to_dict(item)
        values = {}
        for key in table.c.keys():
            values[key] = instance_dict.get(key)
        value_list.append(values)
    with engine.connect() as conn:
        with conn.begin():
            conn.execute(stmt, value_list)


def update_one(one, model, name) -> any:
    table = get_table_by_name(name)
    stmt = update(table)
    one_dict: dict = convert_to_dict(one)
    primary_key = get_primary_key(name)
    stmt = stmt.where(
        eq(table.c[primary_key.lower()], one_dict.get(primary_key)))
    values = {}
    for key, value in one_dict.items():
        if isinstance(table.c[key.lower()].type, JSON):
            if value is not None:
                values[key.lower()] = value
            else:
                values[key.lower()] = None
        else:
            values[key.lower()] = value
    stmt = stmt.values(values)
    with engine.connect() as conn:
        with conn.begin():
            result = conn.execute(stmt)
    return model.parse_obj(one)


def update_one_first(where, updates, model, name):
    table = get_table_by_name(name)
    stmt = update(table)
    stmt = stmt.where(build_mysql_where_expression(table, where))
    stmt = stmt.where(text("limit 1"))
    instance_dict: dict = convert_to_dict(updates)
    values = {}
    for key, value in instance_dict.items():
        if isinstance(table.c[key.lower()].type, JSON):
            if value is not None:
                values[key.lower()] = value
            else:
                values[key.lower()] = None
        else:
            values[key.lower()] = value
    stmt = stmt.values(values)
    with engine.connect() as conn:
        with conn.begin():
            conn.execute(stmt)
    return model.parse_obj(updates)


'''
The where condition must hit the unique index, for row lock
'''


def upsert_(where, updates, model, name):
    table = get_table_by_name(name)
    instance_dict: dict = convert_to_dict(updates)
    select_stmt = select(func.count(1).label("count")). \
        select_from(table). \
        with_for_update(nowait=True). \
        where(build_mysql_where_expression(where))
    insert_stmt = insert(table).values(instance_dict)
    update_stmt = update(table).values(instance_dict)
    with engine.connect() as conn:
        with conn.begin():
            row = conn.execute(select_stmt).fetchone()
            if row._mapping['count'] == 0:
                conn.execute(insert_stmt)
            if row._mapping['count'] == 1:
                conn.execute(update_stmt)
    return model.parse_obj(updates)


def update_(where, updates, model, name):
    table = get_table_by_name(name)
    stmt = update(table)
    stmt = stmt.where(build_mysql_where_expression(table, where))
    instance_dict: dict = convert_to_dict(updates)
    values = {}
    for key, value in instance_dict.items():
        if key != get_primary_key(name):
            values[key] = value
    stmt = stmt.values(values)
    session = Session(engine, future=True)
    try:
        session.execute(stmt)
        session.commit()
    except:
        session.rollback()
        raise
    finally:
        session.close()


def pull_update(where, updates, model, name):
    results = find_(where, model, name)
    updates_dict = convert_to_dict(updates)
    for key, value in updates_dict.items():
        for res in results:
            if isinstance(getattr(res, key), list):
                setattr(res, key, getattr(res, key).remove(value["in"][0]))
                update_one(res, model, name)
    # can't use update_, because the where have the json filed query
    # update_(where, results, model, name)


def delete_by_id(id_, name):
    table = get_table_by_name(name)
    key = get_primary_key(name)
    stmt = delete(table).where(eq(table.c[key.lower()], id_))
    with engine.connect() as conn:
        with conn.begin():
            conn.execute(stmt)


def delete_one(where: dict, name: str):
    table = get_table_by_name(name)
    stmt = delete(table).where(build_mysql_where_expression(table, where))
    with engine.connect() as conn:
        with conn.begin():
            conn.execute(stmt)


def delete_(where, model, name):
    table = get_table_by_name(name)
    if where is None:
        stmt = delete(table)
    else:
        stmt = delete(table).where(build_mysql_where_expression(table, where))
    with engine.connect() as conn:
        with conn.begin():
            conn.execute(stmt)


def find_by_id(id_, model, name):
    table = get_table_by_name(name)
    primary_key = get_primary_key(name)
    stmt = select(table).where(eq(table.c[primary_key.lower()], id_))
    with engine.connect() as conn:
        cursor = conn.execute(stmt).cursor
        columns = [col[0] for col in cursor.description]
        row = cursor.fetchone()
        result = {}
        for index, name in enumerate(columns):
            result[name] = row[index]
    if result is None:
        return
    else:
        return parse_obj(model, result, table)


def find_one(where, model, name):
    table = get_table_by_name(name)
    check_result = check_where_column_type(name, where)
    if check_result is not None:
        stmt = text(build_raw_sql_with_json_table(check_result, where, name))
    else:
        stmt = select(table)
        stmt = stmt.where(build_mysql_where_expression(table, where))
    with engine.connect() as conn:
        cursor = conn.execute(stmt).cursor
        columns = [col[0] for col in cursor.description]
        row = cursor.fetchone()
        result = {}
        if row is None:
            return None
        else:
            for index, name in enumerate(columns):
                result[name] = row[index]
            return parse_obj(model, result, table)


def find_(where: dict, model, name: str) -> list:
    table = get_table_by_name(name)
    check_result = check_where_column_type(name, where)
    if check_result is not None:
        stmt = text(build_raw_sql_with_json_table(check_result, where, name))
    else:
        stmt = select(table)
        where_expression = build_mysql_where_expression(table, where)
        if where_expression is not None:
            stmt = stmt.where(where_expression)
    results = []
    result = {}
    with engine.connect() as conn:
        cursor = conn.execute(stmt).cursor
        columns = [col[0] for col in cursor.description]
        records = cursor.fetchall()
        if records is None:
            return None
        else:
            for record in records:
                for index, name in enumerate(columns):
                    result[name] = record[index]
                results.append(result)
            return [parse_obj(model, row, table) for row in result]


def list_all(model, name):
    table = get_table_by_name(name)
    stmt = select(table)
    with engine.connect() as conn:
        cursor = conn.execute(stmt).cursor
        columns = [col[0] for col in cursor.description]
        res = cursor.fetchall()
    result = {}
    results = []
    for row in res:
        for index, name in enumerate(columns):
            result[name] = row[index]
        results.append(parse_obj(model,  result, table))
    return results


def list_(where, model, name) -> list:
    table = get_table_by_name(name)
    stmt = select(table).where(build_mysql_where_expression(table, where))
    with engine.connect() as conn:
        cursor = conn.execute(stmt).cursor
        columns = [col[0] for col in cursor.description]
        res = cursor.fetchall()
    results = []
    result = {}
    for row in res:
        for index, name in enumerate(columns):
            result[name] = row[index]
        results.append(parse_obj(model, result, table))
    return results


def page_all(sort, pageable, model, name) -> DataPage:
    count = count_table(name)
    table = get_table_by_name(name)
    stmt = select(table)
    orders = build_mysql_order(table, sort)
    for order in orders:
        stmt = stmt.order_by(order)
    offset = pageable.pageSize * (pageable.pageNumber - 1)
    stmt = stmt.offset(offset).limit(pageable.pageSize)
    results = []
    with engine.connect() as conn:
        cursor = conn.execute(stmt).cursor
        columns = [col[0] for col in cursor.description]
        res = cursor.fetchall()
    result = {}
    for row in res:
        for index, name in enumerate(columns):
            result[name] = row[index]
        results.append(parse_obj(model, result, table))
    return build_data_pages(pageable, results, count)


def page_(where, sort, pageable, model, name) -> DataPage:
    count = count_table(name)
    table = get_table_by_name(name)
    stmt = select(table).where(build_mysql_where_expression(table, where))
    orders = build_mysql_order(table, sort)
    for order in orders:
        stmt = stmt.order_by(order)
    offset = pageable.pageSize * (pageable.pageNumber - 1)
    stmt = stmt.offset(offset).limit(pageable.pageSize)
    results = []
    result = {}
    with engine.connect() as conn:
        cursor = conn.execute(stmt).cursor
        columns = [col[0] for col in cursor.description]
        res = cursor.fetchall()
    for row in res:
        for index, name in enumerate(columns):
            result[name] = row[index]
            results.append(parse_obj(model, result, table))
    return build_data_pages(pageable, results, count)


'''
topic data interface
'''


def get_datatype_by_factor_type(type: str):
    if type == "text":
        return String(30)
    elif type == "sequence":
        return BigInteger
    elif type == "number":
        return DECIMAL(32)
    if type == 'datetime':
        return DateTime
    if type == 'date':
        return Date
    if type == "boolean":
        return String(5)
    elif type == "enum":
        return String(20)
    elif type == "object":
        return JSON
    elif type == "array":
        return JSON
    else:
        return String(20)


def check_topic_type_is_raw(topic_name):
    table = get_table_by_name("topics")
    select_stmt = select(table).where(
        build_mysql_where_expression(table, {"name": topic_name}))
    result = {}
    with engine.connect() as conn:
        cursor = conn.execute(select_stmt).cursor
        columns = [col[0] for col in cursor.description]
        row = cursor.fetchone()
        if row is None:
            raise
        else:
            for index, name in enumerate(columns):
                result[name] = row[index]
            if result['TYPE'] == "raw":
                return True
            else:
                return False


def create_topic_data_table(topic):
    topic_dict: dict = convert_to_dict(topic)
    topic_type = topic_dict.get("type")
    if topic_type == "raw":
        create_raw_topic_data_table(topic)
    else:
        topic_name = topic_dict.get('name')
        factors = topic_dict.get('factors')
        table = Table('topic_' + topic_name.lower(), metadata)
        key = Column(name="id_", type_=String(60), primary_key=True)
        table.append_column(key)
        for factor in factors:
            name_ = factor.get('name').lower()
            type_ = get_datatype_by_factor_type(factor.get('type'))
            col = Column(name=name_, type_=type_, nullable=True)
            table.append_column(col)
        table.create(engine)


def create_raw_topic_data_table(topic):
    topic_dict: dict = convert_to_dict(topic)
    topic_name = topic_dict.get('name')
    table = Table('topic_' + topic_name.lower(), metadata)
    key = Column(name="id_", type_=String(60), primary_key=True)
    table.append_column(key)
    col = Column(name="data_", type_=JSON, nullable=True)
    table.append_column(col)
    table.create(engine)


def create_topic_data_table_index(name: str, index_name: list, index_type: str):
    pass


def alter_topic_data_table(topic):
    topic_dict: dict = convert_to_dict(topic)
    if topic_dict.get("type") == "raw":
        pass
    else:
        topic_name = topic_dict.get('name')
        table_name = 'topic_' + topic_name
        '''
        table = Table(table_name, metadata, extend_existing=True,
                      autoload=True, autoload_with=engine)
        '''
        table = get_topic_table_by_name(table_name)
        factors = topic_dict.get('factors')
        existed_cols = []
        for col in table.columns:
            existed_cols.append(col.name)
        for factor in factors:
            factor_name = factor.get('name').lower()
            factor_type = get_datatype_by_factor_type(factor.get('type'))
            if factor_name in existed_cols:
                continue
            else:
                column = Column(factor_name, factor_type)
                column_name = column.compile(dialect=engine.dialect)
                column_type = column.type.compile(engine.dialect)
                stmt = 'ALTER TABLE %s ADD %s %s' % (
                    table_name, column_name, column_type)
                with engine.connect() as conn:
                    with conn.begin():
                        conn.execute(text(stmt))
        metadata.remove(table)


def drop_topic_data_table(topic_name):
    table_name = 'topic_' + topic_name
    try:
        table = get_topic_table_by_name(table_name)
        table.drop(engine)
    except NoSuchTableError:
        print("drop table \"{0}\" not existed".format(table_name))


def topic_data_delete_(where, topic_name):
    table_name = 'topic_' + topic_name
    table = get_topic_table_by_name(table_name)
    if where is None:
        stmt = delete(table)
    else:
        stmt = delete(table).where(build_mysql_where_expression(table, where))
    with engine.connect() as conn:
        with conn.begin():
            conn.execute(stmt)


def topic_data_insert_one(one, topic_name):
    if check_topic_type_is_raw(topic_name):
        raw_topic_data_insert_one(one, topic_name)
    else:
        table_name = 'topic_' + topic_name
        table = get_topic_table_by_name(table_name)
        # one_dict: dict = convert_to_dict(one)
        one_dict: dict = capital_to_lower(convert_to_dict(one))
        one_dict = build_mysql_updates_expression_for_insert(table, one_dict)
        value = {}
        for key in table.c.keys():
            if key == "id_":
                value[key] = get_surrogate_key()
            else:
                value[key] = one_dict.get(key)
        stmt = insert(table)
        with engine.connect() as conn:
            with conn.begin():
                conn.execute(stmt, value)


def raw_topic_data_insert_one(one, topic_name):
    if topic_name == "raw_pipeline_monitor":
        raw_pipeline_monitor_insert_one(one, topic_name)
    else:
        table_name = 'topic_' + topic_name
        table = get_topic_table_by_name(table_name)
        one_dict: dict = convert_to_dict(one)
        value = {'id_': get_surrogate_key(), 'data_': one_dict}
        stmt = insert(table)
        with engine.connect() as conn:
            with conn.begin():
                conn.execute(stmt, value)


def topic_data_insert_(data, topic_name):
    if check_topic_type_is_raw(topic_name):
        raw_topic_data_insert_(data, topic_name)
    else:
        start_time = time.time()
        table_name = 'topic_' + topic_name
        table = get_topic_table_by_name(table_name)
        elapsed_time = time.time() - start_time

        values = []
        for instance in data:
            instance_dict: dict = convert_to_dict(instance)
            instance_dict['id_'] = get_surrogate_key()
            value = {}
            for key in table.c.keys():
                value[key] = instance_dict.get(key)
            values.append(value)
        stmt = insert(table)
        with engine.connect() as conn:
            with conn.begin():
                conn.execute(stmt, values)


def raw_topic_data_insert_(data, topic_name):
    table_name = 'topic_' + topic_name
    table = get_topic_table_by_name(table_name)

    values = []
    for instance in data:
        instance_dict: dict = convert_to_dict(instance)
        value = {'id_': get_surrogate_key(), 'data_': instance_dict}
        values.append(value)
    stmt = insert(table)
    with engine.connect() as conn:
        with conn.begin():
            conn.execute(stmt, values)


def topic_data_update_one(id_: str, one: any, topic_name: str):
    table_name = 'topic_' + topic_name
    table = get_topic_table_by_name(table_name)
    stmt = update(table).where(eq(table.c['id_'], id_))
    one_dict = convert_to_dict(one)
    one_dict_lower = build_mysql_updates_expression_for_update(table, capital_to_lower(one_dict))
    values = {}
    for key, value in one_dict_lower.items():
        if key != 'id_':
            if key.lower() in table.c.keys():
                values[key.lower()] = value
    stmt = stmt.values(values)
    with engine.begin() as conn:
        with conn.begin():
            conn.execute(stmt)


def topic_data_update_(query_dict, instance, topic_name):
    table_name = 'topic_' + topic_name
    table = get_topic_table_by_name(table_name)
    stmt = (update(table).
            where(build_mysql_where_expression(table, query_dict)))
    instance_dict: dict = convert_to_dict(instance)
    values = {}
    for key, value in instance_dict.items():
        if key != 'id_':
            if key.lower() in table.c.keys():
                values[key.lower()] = value
    stmt = stmt.values(values)
    with engine.begin() as conn:
        with conn.begin():
            conn.execute(stmt)


def topic_data_find_by_id(id_: str, topic_name: str) -> any:
    table_name = 'topic_' + topic_name
    table = get_topic_table_by_name(table_name)

    stmt = select(table).where(eq(table.c['id_'], id_))
    with engine.connect() as conn:

        cursor = conn.execute(stmt).cursor
        columns = [col[0] for col in cursor.description]
        row = cursor.fetchone()
    if row is None:
        return None
    else:
        result = {}
        for index, name in enumerate(columns):
            result[name] = row[index]
        return convert_dict_key(result, topic_name)


def topic_data_find_one(where, topic_name) -> any:
    table_name = 'topic_' + topic_name
    table = get_topic_table_by_name(table_name)
    stmt = select(table).where(build_mysql_where_expression(table, where))
    with engine.connect() as conn:
        cursor = conn.execute(stmt).cursor
        columns = [col[0] for col in cursor.description]
        row = cursor.fetchone()
    if row is None:
        return None
    else:
        result = {}
        for index, name in enumerate(columns):
            result[name] = row[index]
        return convert_dict_key(result, topic_name)


def topic_data_find_(where, topic_name):
    table_name = 'topic_' + topic_name
    table = get_topic_table_by_name(table_name)
    stmt = select(table).where(build_mysql_where_expression(table, where))
    with engine.connect() as conn:
        cursor = conn.execute(stmt).cursor
        columns = [col[0] for col in cursor.description]
        res = cursor.fetchall()
    if res is None:
        return None
    else:
        result = {}
        results = []
        for row in res:
            for index, name in enumerate(columns):
                result[name] = row[index]
            results.append(result)
        return convert_list_elements_key(results, topic_name)


def topic_data_list_all(topic_name) -> list:
    pass


def topic_data_page_(where, sort, pageable, model, name) -> DataPage:
    if name == "topic_raw_pipeline_monitor":
        return raw_pipeline_monitor_page_(where, sort, pageable, model, name)
    else:
        count = count_topic_data_table(name)
        table = get_topic_table_by_name(name)
        stmt = select(table).where(build_mysql_where_expression(table, where))
        orders = build_mysql_order(table, sort)
        for order in orders:
            stmt = stmt.order_by(order)
        offset = pageable.pageSize * (pageable.pageNumber - 1)
        stmt = stmt.offset(offset).limit(pageable.pageSize)
        result = {}
        results = []
        with engine.connect() as conn:
            cursor = conn.execute(stmt).cursor
            columns = [col[0] for col in cursor.description]
            res = cursor.fetchall()
        for row in res:
            for index, name in enumerate(columns):
                result[name] = row[index]
            if model is not None:
                results.append(parse_obj(model, result, table))
            else:
                results.append(result)
        return build_data_pages(pageable, results, count)


def topic_find_one_and_update(where, updates, name):
    table_name = 'topic_' + name
    table = get_topic_table_by_name(table_name)
    data_dict: dict = convert_to_dict(updates)

    select_for_update_stmt = select(table). \
        with_for_update(nowait=False). \
        where(build_mysql_where_expression(table, where))

    # if "id_" not in updates:
    #     updates["id_"] = get_surrogate_key()
    insert_stmt = insert(table).values(
        build_mysql_updates_expression_for_insert(table, data_dict))

    update_stmt = update(table).where(
        build_mysql_where_expression(table, where)).values(
        build_mysql_updates_expression_for_update(table, data_dict))

    select_new_stmt = select(table). \
        where(build_mysql_where_expression(table, where))

    with engine.connect() as conn:
        with conn.begin():
            row = conn.execute(select_for_update_stmt).fetchone()
            if row is not None:
                conn.execute(update_stmt)
            else:
                conn.execute(insert_stmt)

    with engine.connect() as conn:
        with conn.begin():
            cursor = conn.execute(select_new_stmt).cursor
            columns = [col[0] for col in cursor.description]
            row = cursor.fetchone()
            result = {}
            for index, name in enumerate(columns):
                result[name] = row[index]
    return convert_dict_key(result, name)


def capital_to_lower(dict_info):
    new_dict = {}
    for i, j in dict_info.items():
        new_dict[i.lower()] = j
    return new_dict


def convert_dict_key(dict_info, topic_name):
    if dict_info is None:
        return None

    new_dict = {}
    stmt = "select t.factors from topics t where t.name=:topic_name"
    with engine.connect() as conn:
        cursor = conn.execute(stmt, {"topic_name": topic_name}).cursor
        columns = [col[0] for col in cursor.description]
        cursor.rowfactory = lambda *args: dict(zip(columns, args))
        row = cursor.fetchone()
        factors = json.loads(row['FACTORS'])
    for factor in factors:
        new_dict[factor['name']] = dict_info[factor['name'].upper()]
    new_dict['id_'] = dict_info['ID_']
    return new_dict


def convert_list_elements_key(list_info, topic_name):
    if list_info is None:
        return None
    new_dict = {}
    new_list = []
    stmt = "select t.factors from topics t where t.name=:topic_name"
    result = {}
    with engine.connect() as conn:
        cursor = conn.execute(stmt, {"topic_name": topic_name}).cursor
        columns = [col[0] for col in cursor.description]
        row = cursor.fetchone()
        for index, name in row:
            result[name] = row[index]
        factors = result['FACTORS']
    for item in list_info:
        for factor in factors:
            new_dict[factor['name']] = item[factor['name'].lower()]
            new_dict['id_'] = item['id_']
        new_list.append(new_dict)
    return new_list



def check_value_type(value):
    if isinstance(value, datetime.datetime):
        return func.to_date(value, "yyyy-mm-dd hh24:mi:ss")
    elif isinstance(value, datetime.date):
        return func.to_date(value, "yyyy-mm-dd")
    else:
        return value


'''
special for raw_pipeline_monitor, need refactor for raw topic schema structure, ToDo
'''


def create_raw_pipeline_monitor():
    table = Table('topic_raw_pipeline_monitor', metadata)
    table.append_column(Column(name='id_', type_=String(60), primary_key=True))
    table.append_column(Column(name='data_', type_=CLOB, nullable=True))
    table.append_column(Column(name='sys_inserttime', type_=Date, nullable=True))
    table.append_column(Column(name='sys_updatetime', type_=Date, nullable=True))
    schema = json.loads(PipelineRunStatus.schema_json(indent=1))
    for key, value in schema.get("properties").items():
        column_name = key.lower()
        column_type = value.get("type", None)
        if column_type is None:
            column_format = value.get("format", None)
            if column_format is None:
                table.append_column(Column(name=column_name, type_=CLOB, nullable=True))
            else:
                if column_format == "date-time":
                    table.append_column(Column(name=column_name, type_=Date, nullable=True))
        elif column_type == "boolean":
            table.append_column(Column(name=column_name, type_=String(5), nullable=True))
        elif column_type == "string":
            if column_name == "error":
                table.append_column(Column(name=column_name, type_=CLOB, nullable=True))
            elif column_name == "uid":
                table.append_column(Column(name=column_name.upper(), type_=String(50), quote=True, nullable=True))
            else:
                table.append_column(Column(name=column_name, type_=String(50), nullable=True))
        elif column_type == "integer":
            table.append_column(Column(name=column_name, type_=Integer, nullable=True))
        elif column_type == "array":
            table.append_column(Column(name=column_name, type_=CLOB, nullable=True))
        else:
            raise Exception(column_name + "not support type")
    table.create(engine)


def raw_pipeline_monitor_insert_one(one, topic_name):
    table_name = 'topic_' + topic_name
    table = get_topic_table_by_name(table_name)
    one_dict: dict = convert_to_dict(one)
    one_lower_dict = capital_to_lower(one_dict)
    value = {}
    for key in table.c.keys():
        if key == "id_":
            value[key] = get_surrogate_key()
        elif key == "data_":
            value[key] = dumps(one_dict)
        else:
            if isinstance(table.c[key].type, JSON):
                if one_lower_dict.get(key) is not None:
                    value[key] = one_lower_dict.get(key)
                else:
                    value[key] = None
            else:
                value[key] = one_lower_dict.get(key)
    stmt = insert(table)
    with engine.connect() as conn:
        conn.execute(stmt, value)


def raw_pipeline_monitor_page_(where, sort, pageable, model, name) -> DataPage:
    count = count_topic_data_table(name)
    table = get_topic_table_by_name(name)
    stmt = select(table).where(build_mysql_where_expression(table, where))
    orders = build_mysql_order(table, sort)
    for order in orders:
        stmt = stmt.order_by(order)
    offset = pageable.pageSize * (pageable.pageNumber - 1)
    stmt = stmt.offset(offset).limit(pageable.pageSize)
    results = []
    with engine.connect() as conn:
        cursor = conn.execute(stmt).cursor
        columns = [col[0] for col in cursor.description]
        res = cursor.fetchall()
    result = {}
    for row in res:
        for index,name in enumerate(columns):
            result[name] = row[index]
        if model is not None:
            results.append(parse_obj(model, result, table))
        else:
            results.append(result['DATA_'])
    return build_data_pages(pageable, results, count)


def clear_metadata():
    metadata.clear()