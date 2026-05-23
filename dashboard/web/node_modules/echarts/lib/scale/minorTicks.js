
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
import { round } from '../util/number.js';
import { getScaleBreakHelper } from './break.js';
import { getIntervalPrecision } from './helper.js';
export function getMinorTicks(scale, splitNumber, breaks, scaleInterval) {
  var ticks = scale.getTicks({
    expandToNicedExtent: true
  });
  // NOTE: In log-scale, do not support minor ticks when breaks exist.
  //  because currently log-scale minor ticks is calculated based on raw values
  //  rather than log-transformed value, due to an odd effect when breaks exist.
  var minorTicks = [];
  var extent = scale.getExtent();
  for (var i = 1; i < ticks.length; i++) {
    var nextTick = ticks[i];
    var prevTick = ticks[i - 1];
    if (prevTick["break"] || nextTick["break"]) {
      // Do not build minor ticks to the adjacent ticks to breaks ticks,
      // since the interval might be irregular.
      continue;
    }
    var count = 0;
    var minorTicksGroup = [];
    var interval = nextTick.value - prevTick.value;
    var minorInterval = interval / splitNumber;
    var minorIntervalPrecision = getIntervalPrecision(minorInterval);
    while (count < splitNumber - 1) {
      var minorTick = round(prevTick.value + (count + 1) * minorInterval, minorIntervalPrecision);
      // For the first and last interval. The count may be less than splitNumber.
      if (minorTick > extent[0] && minorTick < extent[1]) {
        minorTicksGroup.push(minorTick);
      }
      count++;
    }
    var scaleBreakHelper = getScaleBreakHelper();
    scaleBreakHelper && scaleBreakHelper.pruneTicksByBreak('auto', minorTicksGroup, breaks, function (value) {
      return value;
    }, scaleInterval, extent);
    minorTicks.push(minorTicksGroup);
  }
  return minorTicks;
}