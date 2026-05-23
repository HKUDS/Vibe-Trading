
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
import { calcBandWidth } from '../../coord/axisBand.js';
import { AXIS_STAT_KEY_DELIMITER } from '../../coord/axisStatistics.js';
import { registerMetricImplLiPosMinGap } from '../../coord/axisStatisticsMetricsImpl.js';
import { isOrdinalScale } from '../../scale/helper.js';
import { isNullableNumberFinite } from '../../util/number.js';
/**
 * Require `requireAxisStatistics`.
 *
 * Simply expand `Scale` extent by half bandWidth.
 * Do nothing if an `OrdinalScale` has `boundaryGap: true`.
 */
export function createBandWidthBasedAxisContainShapeHandler(axisStatKey) {
  // [AXIS_CONTAIN_SHAPE_COMMON_STRATEGY]:
  //  The calculation below is based on a proportion mapping
  //  from `[barsBoundVal[0], barsBoundVal[1]]` to `[minValNew, maxValNew]`:
  //                  |------|------------------------------|---|
  //     barsBoundVal[0]   minValOld                 maxValOld barsBoundVal[1]
  //                         |----|----------------------|--|
  //                  minValNew    minValOld     maxValOld maxValNew
  //     (Note: `|---|` above represents "pixels" rather than "data".)
  return function (axis, ecModel) {
    var bandWidthResult = calcBandWidth(axis, {
      fromStat: {
        key: axisStatKey
      }
    });
    if (isNullableNumberFinite(bandWidthResult.w2)) {
      return [-bandWidthResult.w2 / 2, bandWidthResult.w2 / 2];
    }
  };
}
/**
 * A pre-built `makeAxisStatKey`.
 * See `makeAxisStatKey2`. Use two functions rather than a optional parameter to impose checking.
 */
export function makeAxisStatKey(seriesType) {
  return seriesType + AXIS_STAT_KEY_DELIMITER;
}
export function makeAxisStatKey2(seriesType, coordSysType) {
  return seriesType + AXIS_STAT_KEY_DELIMITER + coordSysType;
}
/**
 * A pre-built `getMetrics`.
 */
export function createMetricsNonOrdinalLinearPositiveMinGap(axis) {
  registerMetricImplLiPosMinGap();
  return {
    // non-category scale do not use `liPosMinGap` to calculate `bandWidth`.
    liPosMinGap: !isOrdinalScale(axis.scale)
  };
}
;