
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
import { createCrossSeriesLayoutHandler, createProgressiveLayout, registerBarGridAxisHandlers } from '../../layout/barGrid.js';
import dataSample from '../../processor/dataSample.js';
import BarSeries from './BarSeries.js';
import BarView from './BarView.js';
import { SERIES_TYPE_BAR } from '../../layout/barCommon.js';
export function install(registers) {
  registers.registerChartView(BarView);
  registers.registerSeriesModel(BarSeries);
  registers.registerLayout(registers.PRIORITY.VISUAL.LAYOUT, createCrossSeriesLayoutHandler(SERIES_TYPE_BAR));
  // Do layout after other overall layout, which can prepare some information.
  registers.registerLayout(registers.PRIORITY.VISUAL.PROGRESSIVE_LAYOUT, createProgressiveLayout(SERIES_TYPE_BAR));
  // Down sample after filter
  registers.registerProcessor(registers.PRIORITY.PROCESSOR.STATISTIC, dataSample(SERIES_TYPE_BAR));
  /**
   * @payload
   * @property {string} [componentType=series]
   * @property {number} [dx]
   * @property {number} [dy]
   * @property {number} [zoom]
   * @property {number} [originX]
   * @property {number} [originY]
   */
  registers.registerAction({
    type: 'changeAxisOrder',
    event: 'changeAxisOrder',
    update: 'update'
  }, function (payload, ecModel) {
    var componentType = payload.componentType || 'series';
    ecModel.eachComponent({
      mainType: componentType,
      query: payload
    }, function (componentModel) {
      if (payload.sortInfo) {
        componentModel.axis.setCategorySortInfo(payload.sortInfo);
      }
    });
  });
  registerBarGridAxisHandlers(registers);
}