
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
/**
 * Parallel coordinate system creator.
 */
import Parallel from './Parallel.js';
import { COMPONENT_TYPE_PARALLEL, COORD_SYS_TYPE_PARALLEL } from './ParallelModel.js';
import { SINGLE_REFERRING } from '../../util/model.js';
import { each } from 'zrender/lib/core/util.js';
import { associateSeriesWithAxis } from '../axisStatistics.js';
function createParallelCoordSys(ecModel, api) {
  var coordSysList = [];
  ecModel.eachComponent(COMPONENT_TYPE_PARALLEL, function (parallelModel, idx) {
    var coordSys = new Parallel(parallelModel, ecModel, api);
    coordSys.name = 'parallel_' + idx;
    coordSys.resize(parallelModel, api);
    parallelModel.coordinateSystem = coordSys;
    coordSys.model = parallelModel;
    coordSysList.push(coordSys);
  });
  // Inject the coordinateSystems into seriesModel
  ecModel.eachSeries(function (seriesModel) {
    if (seriesModel.get('coordinateSystem') === COORD_SYS_TYPE_PARALLEL) {
      var parallelModel = seriesModel.getReferringComponents(COMPONENT_TYPE_PARALLEL, SINGLE_REFERRING).models[0];
      var parallel_1 = seriesModel.coordinateSystem = parallelModel.coordinateSystem;
      if (parallel_1) {
        each(parallel_1.dimensions, function (dim) {
          associateSeriesWithAxis(parallel_1.getAxis(dim), seriesModel, COORD_SYS_TYPE_PARALLEL);
        });
      }
    }
  });
  return coordSysList;
}
var parallelCoordSysCreator = {
  create: createParallelCoordSys
};
export default parallelCoordSysCreator;