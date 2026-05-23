
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
import { assert } from 'zrender/lib/core/util.js';
import { createMetricsNonOrdinalLinearPositiveMinGap } from '../chart/helper/axisSnippets.js';
import { requireAxisStatistics } from '../coord/axisStatistics.js';
import { isNullableNumberFinite } from '../util/number.js';
export var SERIES_TYPE_BAR = 'bar';
export var SERIES_TYPE_PICTORIAL_BAR = 'pictorialBar';
export function requireAxisStatisticsForBaseBar(registers, axisStatKey, seriesType, coordSysType) {
  requireAxisStatistics(registers, {
    key: axisStatKey,
    seriesType: seriesType,
    coordSysType: coordSysType,
    getMetrics: createMetricsNonOrdinalLinearPositiveMinGap
  });
}
// See cases in `test/bar-start.html` and `#7412`, `#8747`.
export function getStartValue(baseAxis) {
  var val = baseAxis.scale.rawExtentInfo.makeRenderInfo().startValue;
  if (process.env.NODE_ENV !== 'production') {
    assert(isNullableNumberFinite(val));
  }
  return val;
}