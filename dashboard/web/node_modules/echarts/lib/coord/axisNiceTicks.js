
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
import { assert, noop } from 'zrender/lib/core/util.js';
import { ensureValidSplitNumber, getIntervalPrecision, intervalScaleEnsureValidExtent, isIntervalScale, isLogScale, isTimeScale } from '../scale/helper.js';
import { mathCeil, mathFloor, mathMax, nice, quantity, round } from '../util/number.js';
import { updateIntervalOrLogScaleForNiceOrAligned } from './axisHelper.js';
import { calcNiceForTimeScale } from '../scale/Time.js';
import { adoptScaleExtentKindMapping, adoptScaleRawExtentInfoAndPrepare } from './scaleRawExtentInfo.js';
import { getScaleLinearSpanEffective } from '../scale/scaleMapper.js';
// ------ START: LinearIntervalScaleStub Nice ------
function calcNiceForIntervalOrLogScale(scale, opt) {
  // [CAVEAT]: If updating this impl, need to sync it to `axisAlignTicks.ts`.
  var isTargetLogScale = isLogScale(scale);
  var intervalStub = isTargetLogScale ? scale.intervalStub : scale;
  var fixMinMax = opt.fixMinMax || [];
  var oldOutermostExtent = isTargetLogScale ? scale.getExtent() : null;
  var oldIntervalExtent = intervalStub.getExtent();
  var newIntervalExtent = intervalScaleEnsureValidExtent(oldIntervalExtent, fixMinMax, opt.rawExtentResult);
  intervalStub.setExtent(newIntervalExtent[0], newIntervalExtent[1]);
  newIntervalExtent = intervalStub.getExtent();
  var config = isTargetLogScale ? logScaleCalcNiceTicks(intervalStub, opt) : intervalScaleCalcNiceTicks(intervalStub, opt);
  var autoIntervalPrecision = config.intervalPrecision;
  var autoInterval = config.interval;
  // When auto calculated interval is not preferable, users are allowed to explicity specify
  // `interval`, `min`, `max` to customize the axis. A typical case is, in angle axis with angle
  // 0 - 360, where the internally calculated interval is not 60-based.
  // NOTICE:
  //  - In `xxxAxis.type: 'log'`, ec option `xxxAxis.interval` requires a logarithm-applied
  //    value rather than a value in the raw scale.
  //  - Follow the historical behavior:
  //    - even `interval` is specified, the scale extent is still expanded based on the auto-calculated
  //      interval.
  //    - No validation to the specified `interval`.
  var userInterval = opt.userInterval;
  if (userInterval != null) {
    config.interval = userInterval;
    config.intervalPrecision = getIntervalPrecision(userInterval);
  }
  if (!fixMinMax[0]) {
    newIntervalExtent[0] = round(mathFloor(newIntervalExtent[0] / autoInterval) * autoInterval, autoIntervalPrecision);
  }
  if (!fixMinMax[1]) {
    newIntervalExtent[1] = round(mathCeil(newIntervalExtent[1] / autoInterval) * autoInterval, autoIntervalPrecision);
  }
  if (userInterval != null) {
    // Historical behavior.
    config.niceExtent = newIntervalExtent.slice();
  }
  updateIntervalOrLogScaleForNiceOrAligned(scale, fixMinMax, oldIntervalExtent, newIntervalExtent, oldOutermostExtent, config);
}
// ------ END: LinearIntervalScaleStub Nice ------
// ------ START: IntervalScale Nice ------
function intervalScaleCalcNiceTicks(scale, opt) {
  var splitNumber = ensureValidSplitNumber(opt.splitNumber, 5);
  // Use the span in the innermost linear space to calculate nice ticks.
  var span = getScaleLinearSpanEffective(scale);
  if (process.env.NODE_ENV !== 'production') {
    assert(isFinite(span) && span > 0); // It should have been ensured by `intervalScaleEnsureValidExtent`.
  }
  var minInterval = opt.minInterval;
  var maxInterval = opt.maxInterval;
  var interval = nice(span / splitNumber, true);
  if (minInterval != null && interval < minInterval) {
    interval = minInterval;
  }
  if (maxInterval != null && interval > maxInterval) {
    interval = maxInterval;
  }
  var intervalPrecision = getIntervalPrecision(interval);
  var extent = scale.getExtent();
  // By design, the `niceExtent` is inside the original extent
  var niceExtent = [round(mathCeil(extent[0] / interval) * interval, intervalPrecision), round(mathFloor(extent[1] / interval) * interval, intervalPrecision)];
  return {
    interval: interval,
    intervalPrecision: intervalPrecision,
    niceExtent: niceExtent
  };
}
;
// ------ END: IntervalScale Nice ------
// ------ START: LogScale Nice ------
function logScaleCalcNiceTicks(intervalStub, opt) {
  // [CAVEAT]: If updating this impl, need to sync it to `axisAlignTicks.ts`.
  var splitNumber = ensureValidSplitNumber(opt.splitNumber, 10);
  // Find nice ticks in the "logarithmic space". Notice that "logarithmic space" is a middle space
  // rather than the innermost linear space when axis breaks exist.
  var intervalExtent = intervalStub.getExtent();
  // But use the span in the innermost linear space to calculate nice ticks.
  var span = getScaleLinearSpanEffective(intervalStub);
  if (process.env.NODE_ENV !== 'production') {
    assert(isFinite(span) && span > 0); // It should be ensured by `intervalScaleEnsureValidExtent`.
  }
  // Interval should be integer
  var interval = mathMax(quantity(span), 1);
  var err = splitNumber / span * interval;
  // Filter ticks to get closer to the desired count.
  if (err <= 0.5) {
    // TODO: support other bases other than 10?
    interval *= 10;
  }
  var intervalPrecision = getIntervalPrecision(interval);
  // For LogScale, we use a `niceExtent` in the "logarithmic space" rather than
  // the original "pow space", because it is used in `intervalStub.getTicks()` thereafter.
  var niceExtent = [round(mathCeil(intervalExtent[0] / interval) * interval, intervalPrecision), round(mathFloor(intervalExtent[1] / interval) * interval, intervalPrecision)];
  return {
    intervalPrecision: intervalPrecision,
    interval: interval,
    niceExtent: niceExtent
  };
}
;
/**
 * NOTE: See the summary of the process of extent determination in the comment of `scaleMapper.setExtent`.
 *
 * Calculate a "nice" extent and "nice" ticks configs based on the current scale extent and ec options.
 * scale extent will be modified, and config may be set to the scale.
 *
 * @see SCALE_EXTENT_CONSTRUCTION for the full processing flow.
 */
export function scaleCalcNice(axisLike) {
  var scale = axisLike.scale;
  var model = axisLike.model;
  var axis = model.axis;
  var ecModel = model.ecModel;
  if (process.env.NODE_ENV !== 'production') {
    assert(axis && ecModel);
  }
  scaleCalcNice2(scale, model, axis, ecModel, null);
}
/**
 * @see SCALE_EXTENT_CONSTRUCTION for the full processing flow.
 */
export function scaleCalcNice2(scale, model,
// Some call from external source, such as echarts-gl, may have no `axis` and `ecModel`,
// but has `externalDataExtent`.
axis, ecModel, externalDataExtent) {
  var rawExtentResult = adoptScaleRawExtentInfoAndPrepare(scale, model, ecModel, axis, externalDataExtent);
  var isIntervalOrTime = isIntervalScale(scale) || isTimeScale(scale);
  scaleCalcNiceDirectly(scale, {
    splitNumber: model.get('splitNumber'),
    fixMinMax: rawExtentResult.fixMM,
    userInterval: model.get('interval'),
    minInterval: isIntervalOrTime ? model.get('minInterval') : null,
    maxInterval: isIntervalOrTime ? model.get('maxInterval') : null,
    rawExtentResult: rawExtentResult
  });
  if (axis && ecModel) {
    adoptScaleExtentKindMapping(axis, scale, rawExtentResult, ecModel);
  }
  if (process.env.NODE_ENV !== 'production') {
    scale.freeze();
  }
}
export function scaleCalcNiceDirectly(scale, opt) {
  scaleCalcNiceMethods[scale.type](scale, opt);
}
var scaleCalcNiceMethods = {
  interval: calcNiceForIntervalOrLogScale,
  log: calcNiceForIntervalOrLogScale,
  time: calcNiceForTimeScale,
  ordinal: noop
};
// ------ END: scaleCalcNice Entry ------