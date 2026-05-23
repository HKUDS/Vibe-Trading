
/*
* Licensed to the Apache Software Foundation (ASF) under one
* or more contributor license agreements.  See the NOTICE file
* distributed with this work for additional information
* regarding copyright ownership.  The ASF licenses this file
* to you under the Apache License, Version 2.0 (the
* "License"); you may not use this file except in compliance
* with the License.  You may obtain a copy of the License at
*
*   http://www.apache.org/licenses/LICENSE-2.0
*
* Unless required by applicable law or agreed to in writing,
* software distributed under the License is distributed on an
* "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
* KIND, either express or implied.  See the License for the
* specific language governing permissions and limitations
* under the License.
*/


/**
 * AUTO-GENERATED FILE. DO NOT MODIFY.
 */

/*
* Licensed to the Apache Software Foundation (ASF) under one
* or more contributor license agreements.  See the NOTICE file
* distributed with this work for additional information
* regarding copyright ownership.  The ASF licenses this file
* to you under the Apache License, Version 2.0 (the
* "License"); you may not use this file except in compliance
* with the License.  You may obtain a copy of the License at
*
*   http://www.apache.org/licenses/LICENSE-2.0
*
* Unless required by applicable law or agreed to in writing,
* software distributed under the License is distributed on an
* "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
* KIND, either express or implied.  See the License for the
* specific language governing permissions and limitations
* under the License.
*/
import { parseFinder } from '../../util/model.js';
import { defaults, each } from 'zrender/lib/core/util.js';
export var AXIS_BREAK_EXPAND_ACTION_TYPE = 'expandAxisBreak';
export var AXIS_BREAK_COLLAPSE_ACTION_TYPE = 'collapseAxisBreak';
export var AXIS_BREAK_TOGGLE_ACTION_TYPE = 'toggleAxisBreak';
var AXIS_BREAK_CHANGED_EVENT_TYPE = 'axisbreakchanged';
var expandAxisBreakActionInfo = {
  type: AXIS_BREAK_EXPAND_ACTION_TYPE,
  event: AXIS_BREAK_CHANGED_EVENT_TYPE,
  update: 'update',
  refineEvent: refineAxisBreakChangeEvent
};
var collapseAxisBreakActionInfo = {
  type: AXIS_BREAK_COLLAPSE_ACTION_TYPE,
  event: AXIS_BREAK_CHANGED_EVENT_TYPE,
  update: 'update',
  refineEvent: refineAxisBreakChangeEvent
};
var toggleAxisBreakActionInfo = {
  type: AXIS_BREAK_TOGGLE_ACTION_TYPE,
  event: AXIS_BREAK_CHANGED_EVENT_TYPE,
  update: 'update',
  refineEvent: refineAxisBreakChangeEvent
};
function refineAxisBreakChangeEvent(actionResultBatch, payload, ecModel, api) {
  var breaks = [];
  each(actionResultBatch, function (actionResult) {
    breaks = breaks.concat(actionResult.eventBreaks);
  });
  return {
    eventContent: {
      breaks: breaks
    }
  };
}
export function registerAction(registers) {
  registers.registerAction(expandAxisBreakActionInfo, actionHandler);
  registers.registerAction(collapseAxisBreakActionInfo, actionHandler);
  registers.registerAction(toggleAxisBreakActionInfo, actionHandler);
  function actionHandler(payload, ecModel) {
    var eventBreaks = [];
    var finderResult = parseFinder(ecModel, payload);
    function dealUpdate(modelProp, indexProp) {
      each(finderResult[modelProp], function (axisModel) {
        var result = axisModel.updateAxisBreaks(payload);
        each(result.breaks, function (item) {
          var _a;
          eventBreaks.push(defaults((_a = {}, _a[indexProp] = axisModel.componentIndex, _a), item));
        });
      });
    }
    dealUpdate('xAxisModels', 'xAxisIndex');
    dealUpdate('yAxisModels', 'yAxisIndex');
    dealUpdate('singleAxisModels', 'singleAxisIndex');
    return {
      eventBreaks: eventBreaks
    };
  }
}