from watchmen.pipeline.single.stage.unit.utils.units_func import get_value, get_factor
from watchmen.topic.factor.factor import Factor


def build_factor_list(factor):
    factor_name_list = factor.name.split(".")
    factor_list = []
    for name in factor_name_list:
        factor = Factor()
        factor.name = name
        factor_list.append(factor)
    return factor_list


def run_mapping_rules(mapping_list, target_topic, raw_data, pipeline_topic):
    mapping_results = []

    for mapping in mapping_list:
        result =[]
        source = mapping["from"]
        source_factor = get_factor(source["factorId"], pipeline_topic)

        source_value_list = get_source_factor_value(raw_data, result, source_factor)

        target = mapping["to"]
        target_factor = get_factor(target["factorId"], target_topic)
        ## TODO func convert
        mapping_results.append({target_factor.name:source_value_list})

    mapping_data_list = merge_mapping_data(mapping_results)

    print("mapping_data_list :",mapping_data_list)
    return mapping_data_list


def get_source_factor_value(raw_data, result, source_factor):
    if is_sub_field(source_factor):
        factor_list = build_factor_list(source_factor)
        source_value_list = get_factor_value(0, factor_list, raw_data, result)

    else:
        source_value_list = get_value(source_factor, raw_data)
    return source_value_list


def merge_mapping_data(mapping_results):
    max_value_size = get_max_value_size(mapping_results)
    mapping_data_list = []
    for i in range(max_value_size):
        mapping_data = {}
        for mapping_result in mapping_results:
            for key, value in mapping_result.items():
                if type(value) is list:
                    mapping_data[key] = value[i]
                else:
                    mapping_data[key] = value

        mapping_data_list.append(mapping_data)
    return mapping_data_list


def get_max_value_size(mapping_results):
    index = 0
    for mapping_result in mapping_results:
        for key ,value in mapping_result.items():
            if type(value) is list:
                # index = len(value)
                if len(value) > index:
                    index = len(value)
            else:
                index = 1
    return index


def is_sub_field(factor):
    return "." in factor.name


def get_factor_value(index, factor_list, raw_data, result):
    factor = factor_list[index]
    data = get_value(factor, raw_data)
    if type(data) is list:
        for raw in data:
             get_factor_value(index + 1, factor_list, raw, result)
            # result.append({"raw": raw, "value": value})
    elif type(data) is dict:
             get_factor_value(index + 1, factor_list, data, result)
        # result.append({"raw": data, "value": value})
    else:
        result.append(data)
    return result


