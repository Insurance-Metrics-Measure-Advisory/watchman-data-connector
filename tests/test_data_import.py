#
# from __future__ import absolute_import
# # from . import watchmen
# # load data raw_data_back
#
# # spilt data to topic base on raw_data_back
#
# # topic and feature map
# import pickle
# # from watchmen.model. import
# from watchmen.connector.local_connector import raw_data_load
# from watchmen.raw_data_back.model_schema_set import ModelSchemaSet
# from watchmen.service.import_data import import_raw_data
#
#
# def test():
#     pickle_data = pickle.dumps(raw_data_load('../../test/data/instance_data.json'))
#     model_schema_set = ModelSchemaSet.parse_raw(
#         pickle_data, content_type='application/pickle', allow_pickle=True
#     )
#
#     # print(type(model_schema_set))
#
#     import_raw_data(raw_data_load('../../test/data/policy.json'),model_schema_set,None)
#
#     # print(m)
