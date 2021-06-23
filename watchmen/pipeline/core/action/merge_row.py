import logging
import time

from watchmen.common.constants import pipeline_constants
from watchmen.monitor.model.pipeline_monitor import MergeRowAction
from watchmen.pipeline.core.by.parse_on_parameter import parse_parameter_joint
from watchmen.pipeline.core.context.action_context import get_variables
from watchmen.pipeline.core.mapping.parse_mapping import parse_mappings
from watchmen.pipeline.core.monitor.model.pipeline_monitor import ActionStatus
from watchmen.pipeline.model.pipeline import UnitAction
from watchmen.pipeline.single.stage.unit.mongo.index import run_mapping_rules, build_query_conditions, \
    __build_mongo_query, index_conditions
from watchmen.pipeline.single.stage.unit.mongo.read_topic_data import query_topic_data
from watchmen.pipeline.single.stage.unit.mongo.write_topic_data import update_topic_data
from watchmen.pipeline.single.stage.unit.utils import PIPELINE_UID
from watchmen.topic.storage.topic_schema_storage import get_topic_by_id
from watchmen.topic.topic import Topic

log = logging.getLogger("app." + __name__)


def init(actionContext):
    def merge_topic():
        # begin time
        start = time.time()

        # create action status monitor
        status = ActionStatus()
        status.type = "MergeRow"
        status.uid = actionContext.unitContext.stageContext.pipelineContext.pipeline.pipelineId

        previous_data = actionContext.previousOfTriggerData
        current_data = actionContext.currentOfTriggerData
        action = actionContext.action
        if action.topicId is None:
            raise ValueError("action.topicId is empty {0}".format(action.name))

        pipeline_topic = actionContext.unitContext.stageContext.pipelineContext.pipelineTopic
        target_topic = get_topic_by_id(action.topicId)

        variables = get_variables(actionContext)

        # if there are aggregate functions, need lock the record to update
        mappings_results, having_aggregate_functions = parse_mappings(action.mapping,
                                                                      target_topic,
                                                                      previous_data,
                                                                      current_data,
                                                                      variables)
        status.mapping = mappings_results

        where_ = parse_parameter_joint(action.by, current_data, variables, pipeline_topic, target_topic)
        status.whereConditions = where_

        trigger_pipeline_data_list = []

        target_data = query_topic_data(where_, target_topic.name)
        if target_data is None:
            raise Exception("can't insert data in merge row action ")
        else:
            trigger_pipeline_data_list.append(
                update_topic_data(target_topic.name, mappings_results, target_data,
                                  actionContext.unitContext.stageContext.pipelineContext.pipeline.pipelineId,
                                  where_))
            status.updateCount = status.updateCount + 1

        elapsed_time = time.time() - start
        status.complete_time = elapsed_time
        return status, trigger_pipeline_data_list

    return merge_topic
