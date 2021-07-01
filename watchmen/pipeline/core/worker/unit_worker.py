import logging

from distributed import as_completed

from watchmen.common.dask.client import client
from watchmen.config.config import settings
from watchmen.monitor.model.pipeline_monitor import UnitRunStatus
from watchmen.pipeline.core.context.action_context import ActionContext
from watchmen.pipeline.core.context.unit_context import UnitContext
from watchmen.pipeline.core.parameter.parse_parameter import parse_parameter_joint
from watchmen.pipeline.core.worker.action_worker import run_action

log = logging.getLogger("app." + __name__)


def should_run(unit_context: UnitContext) -> bool:
    unit = unit_context.unit
    if unit.on is None:
        return True
    current_data = unit_context.stageContext.pipelineContext.currentOfTriggerData
    variables = unit_context.stageContext.pipelineContext.variables
    return parse_parameter_joint(unit.on, current_data, variables)


def run_unit(unit_context: UnitContext):
    loop_variable_name = unit_context.unit.loopVariableName
    if loop_variable_name is not None and loop_variable_name != "":
        loop_variable = unit_context.stageContext.pipelineContext.variables[loop_variable_name]
        if isinstance(loop_variable, list):
            if settings.DASK_ON:
                run_loop_with_dask(loop_variable_name, unit_context)
            else:
                run_actions(loop_variable, loop_variable_name, unit_context)
        elif loop_variable is not None:  # the loop variable just have one element.
            run_actions(loop_variable_name, unit_context)
    else:
        if unit_context.unit.do is not None:
            if should_run(unit_context):
                unit_context.unitStatus = UnitRunStatus()
                for action in unit_context.unit.do:
                    action_context = ActionContext(unit_context, action)
                    run_action(action_context)
                    unit_context.unitStatus.actions.append(action_context.actionStatus)


def run_actions(loop_variable_name, unit_context):
    for value in unit_context.stageContext.pipelineContext.variables[loop_variable_name]:
        if unit_context.unit.do is not None:
            if should_run(unit_context):
                unit_context.unitStatus = UnitRunStatus()
                for action in unit_context.unit.do:
                    action_context = ActionContext(unit_context, action)
                    action_context.delegateVariableName = loop_variable_name
                    action_context.delegateValue = value
                    unit_context.unitStatus.actions.append(action_context.actionStatus)


def run_loop_with_dask(loop_variable_name, unit_context):
    futures = []
    for value in unit_context.stageContext.pipelineContext.variables[loop_variable_name]:
        if unit_context.unit.do is not None:
            if should_run(unit_context):
                unit_context.unitStatus = UnitRunStatus()
                for action in unit_context.unit.do:
                    action_context = ActionContext(unit_context, action)
                    action_context.delegateVariableName = loop_variable_name
                    action_context.delegateValue = value
                    futures.append(client.submit(run_action, action_context))
    for future in as_completed(futures):
        result = future.result()
        unit_context.unitStatus.actions.append(result.actionStatus)
