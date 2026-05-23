
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
import PictorialBarView from './PictorialBarView.js';
import PictorialBarSeriesModel from './PictorialBarSeries.js';
import { createProgressiveLayout, createCrossSeriesLayoutHandler, registerBarGridAxisHandlers } from '../../layout/barGrid.js';
import { SERIES_TYPE_PICTORIAL_BAR } from '../../layout/barCommon.js';
export function install(registers) {
  registers.registerChartView(PictorialBarView);
  registers.registerSeriesModel(PictorialBarSeriesModel);
  registers.registerLayout(registers.PRIORITY.VISUAL.LAYOUT, createCrossSeriesLayoutHandler(SERIES_TYPE_PICTORIAL_BAR));
  // Do layout after other overall layout, which can prepare some information.
  registers.registerLayout(registers.PRIORITY.VISUAL.PROGRESSIVE_LAYOUT, createProgressiveLayout(SERIES_TYPE_PICTORIAL_BAR));
  registerBarGridAxisHandlers(registers);
}