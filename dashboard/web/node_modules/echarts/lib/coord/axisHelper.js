
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
import * as zrUtil from 'zrender/lib/core/util.js';
import OrdinalScale from '../scale/Ordinal.js';
import IntervalScale from '../scale/Interval.js';
import Scale from '../scale/Scale.js';
import TimeScale from '../scale/Time.js';
import LogScale from '../scale/Log.js';
import { AXIS_TYPES } from './axisCommonTypes.js';
import { getStackedDimension } from '../data/helper/dataStackHelper.js';
import { parseTimeAxisLabelFormatter } from '../util/time.js';
import { getScaleBreakHelper } from '../scale/break.js';
import { error } from '../util/log.js';
import { extentDiffers, isLogScale, isOrdinalScale } from '../scale/helper.js';
import { initExtentForUnion, isValidBoundsForExtent, makeInner } from '../util/model.js';
import { getScaleExtentForMappingUnsafe, SCALE_EXTENT_KIND_EFFECTIVE, SCALE_MAPPER_DEPTH_OUT_OF_BREAK } from '../scale/scaleMapper.js';
import ComponentModel from '../model/Component.js';
var axisInner = makeInner();
export function determineAxisType(model) {
  var type = model.get('type');
  if (
  // In ec option, `xxxAxis.type` may be undefined.
  type == null
  // PENDING: Theoretically, a customized `Scale` is probably impossible, since
  // the interface of `Scale` does not guarantee stability. But we still literally
  // support it for backward compat, though type incorrect.
  || !zrUtil.hasOwn(AXIS_TYPES, type) && !Scale.getClass(type)) {
    type = 'value';
  }
  return type;
}
export function createScaleByModel(model, type, coordSysSupportAxisBreaks) {
  var breakHelper = getScaleBreakHelper();
  var breakOption;
  if (breakHelper) {
    breakOption = retrieveAxisBreaksOption(model, type, coordSysSupportAxisBreaks);
  }
  switch (type) {
    case 'category':
      return new OrdinalScale({
        ordinalMeta: model.getOrdinalMeta ? model.getOrdinalMeta() : model.getCategories(),
        extent: initExtentForUnion()
      });
    case 'time':
      return new TimeScale({
        locale: model.ecModel.getLocaleModel(),
        useUTC: model.ecModel.get('useUTC'),
        breakOption: breakOption
      });
    case 'log':
      // See also #3749
      return new LogScale({
        logBase: model.get('logBase'),
        breakOption: breakOption
      });
    case 'value':
      return new IntervalScale({
        breakOption: breakOption
      });
    default:
      // case others.
      return new (Scale.getClass(type) || IntervalScale)({});
  }
}
/**
 * Check if the axis cross a specific value.
 */
export function getScaleValuePositionKind(scale, value, considerMappingExtent) {
  var dataExtent = considerMappingExtent ? getScaleExtentForMappingUnsafe(scale, null) : scale.getExtentUnsafe(SCALE_EXTENT_KIND_EFFECTIVE, null);
  var min = dataExtent[0];
  var max = dataExtent[1];
  return !isValidBoundsForExtent(min, max) ? SCALE_VALUE_POSITION_KIND_OUTSIDE : min === value || max === value ? SCALE_VALUE_POSITION_KIND_EDGE : min < value && max > value ? SCALE_VALUE_POSITION_KIND_INSIDE : SCALE_VALUE_POSITION_KIND_OUTSIDE;
}
export var SCALE_VALUE_POSITION_KIND_INSIDE = 1;
export var SCALE_VALUE_POSITION_KIND_EDGE = 2;
export var SCALE_VALUE_POSITION_KIND_OUTSIDE = 3;
export function discourageOnAxisZero(axis) {
  axisInner(axis).noOnMyZero = true;
}
/**
 * `true`: Prevent orthoganal axes from positioning at the zero point of this axis.
 */
export function isOnAxisZeroDiscouraged(axis) {
  return axisInner(axis).noOnMyZero;
}
/**
 * @param axis
 * @return Label formatter function.
 *         param: {number} tickValue,
 *         param: {number} idx, the index in all ticks.
 *                         If category axis, this param is not required.
 *         return: {string} label string.
 */
export function makeLabelFormatter(axis) {
  var labelFormatter = axis.getLabelModel().get('formatter');
  if (axis.type === 'time') {
    var parsed_1 = parseTimeAxisLabelFormatter(labelFormatter);
    return function (tick, idx) {
      return axis.scale.getFormattedLabel(tick, idx, parsed_1);
    };
  } else if (zrUtil.isString(labelFormatter)) {
    return function (tick) {
      // For category axis, get raw value; for numeric axis,
      // get formatted label like '1,333,444'.
      var label = axis.scale.getLabel(tick);
      var text = labelFormatter.replace('{value}', label != null ? label : '');
      return text;
    };
  } else if (zrUtil.isFunction(labelFormatter)) {
    if (axis.type === 'category') {
      return function (tick, idx) {
        // The original intention of `idx` is "the index of the tick in all ticks".
        // But the previous implementation of category axis do not consider the
        // `axisLabel.interval`, which cause that, for example, the `interval` is
        // `1`, then the ticks "name5", "name7", "name9" are displayed, where the
        // corresponding `idx` are `0`, `2`, `4`, but not `0`, `1`, `2`. So we keep
        // the definition here for back compatibility.
        return labelFormatter(getAxisRawValue(axis, tick), tick.value - axis.scale.getExtent()[0], null // Using `null` just for backward compat.
        );
      };
    }
    var scaleBreakHelper_1 = getScaleBreakHelper();
    return function (tick, idx) {
      // Using `null` just for backward compat. It's been found that in the `test/axis-customTicks.html`,
      // there is a formatter `function (value, index, revers = true) { ... }`. Although the third param
      // `revers` is incorrect and always `null`, changing it might introduce a breaking change.
      var extra = null;
      if (scaleBreakHelper_1) {
        extra = scaleBreakHelper_1.makeAxisLabelFormatterParamBreak(extra, tick["break"]);
      }
      return labelFormatter(getAxisRawValue(axis, tick), idx, extra);
    };
  } else {
    return function (tick) {
      return axis.scale.getLabel(tick);
    };
  }
}
export function getAxisRawValue(axis, tick) {
  // In category axis with data zoom, tick is not the original
  // index of axis.data. So tick should not be exposed to user
  // in category axis.
  var scale = axis.scale;
  return isOrdinalScale(scale) ? scale.getLabel(tick) : tick.value;
}
/**
 * @param model axisLabelModel or axisTickModel
 */
export function getOptionCategoryInterval(model) {
  var interval = model.get('interval');
  return interval == null ? 'auto' : interval;
}
/**
 * Set `categoryInterval` as 0 implicitly indicates that
 * show all labels regardless of overlap.
 * @param {Object} axis axisModel.axis
 */
export function shouldShowAllLabels(axis) {
  return axis.type === 'category' && getOptionCategoryInterval(axis.getLabelModel()) === 0;
}
export function getDataDimensionsOnAxis(data, axisDim) {
  // Remove duplicated dat dimensions caused by `getStackedDimension`.
  var dataDimMap = {};
  // Currently `mapDimensionsAll` will contain stack result dimension ('__\0ecstackresult').
  // PENDING: is it reasonable? Do we need to remove the original dim from "coord dim" since
  // there has been stacked result dim?
  zrUtil.each(data.mapDimensionsAll(axisDim), function (dataDim) {
    // For example, the extent of the original dimension
    // is [0.1, 0.5], the extent of the `stackResultDimension`
    // is [7, 9], the final extent should NOT include [0.1, 0.5],
    // because there is no graphic corresponding to [0.1, 0.5].
    // See the case in `test/area-stack.html` `main1`, where area line
    // stack needs `yAxis` not start from 0.
    dataDimMap[getStackedDimension(data, dataDim)] = true;
  });
  return zrUtil.keys(dataDimMap);
}
export function isNameLocationCenter(nameLocation) {
  return nameLocation === 'middle' || nameLocation === 'center';
}
export function shouldAxisShow(axisModel) {
  return axisModel.getShallow('show');
}
export function retrieveAxisBreaksOption(model, axisType, coordSysSupportAxisBreaks) {
  var option = model.get('breaks', true);
  if (option != null) {
    if (!getScaleBreakHelper()) {
      if (process.env.NODE_ENV !== 'production') {
        error('Must `import {AxisBreak} from "echarts/features.js"; use(AxisBreak);` first if using breaks option.');
      }
      return undefined;
    }
    if (!coordSysSupportAxisBreaks || !isAxisTypeSupportAxisBreak(axisType)) {
      if (process.env.NODE_ENV !== 'production') {
        // Users have provided `breaks` in ec option but not supported.
        var axisInfo = model instanceof ComponentModel ? " " + model.type + "[" + model.componentIndex + "]" : '';
        error("Axis" + axisInfo + " does not support break.");
      }
      return undefined;
    }
    return option;
  }
}
function isAxisTypeSupportAxisBreak(axisType) {
  return axisType !== 'category';
}
export function updateIntervalOrLogScaleForNiceOrAligned(scale, fixMinMax, oldIntervalExtent, newIntervalExtent, oldOutermostExtent, cfg) {
  var isTargetLogScale = isLogScale(scale);
  var intervalStub = isTargetLogScale ? scale.intervalStub : scale;
  intervalStub.setExtent(newIntervalExtent[0], newIntervalExtent[1]);
  if (isTargetLogScale) {
    // Sync intervalStub extent to the outermost extent (i.e., `powStub` for `LogScale`).
    var powStub = scale.powStub;
    var opt = {
      depth: SCALE_MAPPER_DEPTH_OUT_OF_BREAK
    };
    var minPow = scale.transformOut(newIntervalExtent[0], opt);
    var maxPow = scale.transformOut(newIntervalExtent[1], opt);
    // Log transform is probably not inversible by rounding error, which causes min/max tick may be
    // displayed as `5.999999999999999` unexpectedly when min/max are required to be fixed (specified
    // by users or by dataZoom). Therefore we set `powStub` with respect to `oldOutermostExtent` if
    // interval extent is not changed. But `intervalStub` should not be inversely changed by this
    // handling, otherwise its monotonicity between `niceExtent` and `extent` may be broken and cause
    // unexpected ticks generation.
    var extentChanged = extentDiffers(oldIntervalExtent, newIntervalExtent);
    // NOTE: extent may still be changed even when min/max are required to be fixed,
    // e.g., by `intervalScaleEnsureValidExtent`.
    if (fixMinMax[0] && !extentChanged[0]) {
      minPow = oldOutermostExtent[0];
    }
    if (fixMinMax[1] && !extentChanged[1]) {
      maxPow = oldOutermostExtent[1];
    }
    powStub.setExtent(minPow, maxPow);
  }
  intervalStub.setConfig(cfg);
}
export function getTickValueOutermost(scale, tick) {
  return isOrdinalScale(scale) ? scale.getRawOrdinalNumber(tick.value) : tick.value;
}
export function isAxisOnBand(scale, axisModel) {
  return isOrdinalScale(scale) && !!axisModel.get('boundaryGap');
}