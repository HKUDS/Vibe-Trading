
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
import { graphEdgeVisualStageHandler } from './edgeVisual.js';
import { graphSimpleLayoutStageHandler } from './simpleLayout.js';
import { graphCircularLayoutStageHandler } from './circularLayout.js';
import { graphForceLayoutStageHandler } from './forceLayout.js';
import createView from './createView.js';
import View from '../../coord/View.js';
import GraphView from './GraphView.js';
import GraphSeriesModel, { SERIES_TYPE_GRAPH } from './GraphSeries.js';
import { registerRoamActionSimply } from '../../component/helper/roamHelper.js';
import { noop } from 'zrender/lib/core/util.js';
import { graphCategoryFilterStageHandler } from './categoryFilter.js';
import { graphCategoryVisualStageHandler } from './categoryVisual.js';
import { COMPONENT_MAIN_TYPE_SERIES } from '../../util/types.js';
export function install(registers) {
  registers.registerChartView(GraphView);
  registers.registerSeriesModel(GraphSeriesModel);
  registers.registerProcessor(graphCategoryFilterStageHandler);
  registers.registerVisual(graphCategoryVisualStageHandler);
  registers.registerVisual(graphEdgeVisualStageHandler);
  registers.registerLayout(graphSimpleLayoutStageHandler);
  registers.registerLayout(registers.PRIORITY.VISUAL.POST_CHART_LAYOUT, graphCircularLayoutStageHandler);
  registers.registerLayout(graphForceLayoutStageHandler);
  registers.registerCoordinateSystem('graphView', {
    dimensions: View.dimensions,
    create: createView
  });
  // Register legacy focus actions
  registers.registerAction({
    type: 'focusNodeAdjacency',
    event: 'focusNodeAdjacency',
    update: 'series:focusNodeAdjacency'
  }, noop);
  registers.registerAction({
    type: 'unfocusNodeAdjacency',
    event: 'unfocusNodeAdjacency',
    update: 'series:unfocusNodeAdjacency'
  }, noop);
  registerRoamActionSimply(registers, COMPONENT_MAIN_TYPE_SERIES, SERIES_TYPE_GRAPH);
}