
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
import { mathAbs, mathMax, mathMin, mathPI, parsePercent } from '../util/number.js';
import { isDimensionStacked } from '../data/helper/dataStackHelper.js';
import AngleAxis from '../coord/polar/AngleAxis.js';
import RadiusAxis from '../coord/polar/RadiusAxis.js';
import { calcBandWidth } from '../coord/axisBand.js';
import { createBandWidthBasedAxisContainShapeHandler, makeAxisStatKey2 } from '../chart/helper/axisSnippets.js';
import { createSimpleOverallStageHandler, makeCallOnlyOnce } from '../util/model.js';
import { registerAxisContainShapeHandler } from '../coord/scaleRawExtentInfo.js';
import { getStartValue, requireAxisStatisticsForBaseBar, SERIES_TYPE_BAR } from './barCommon.js';
import { eachAxisOnKey, eachSeriesOnAxisOnKey } from '../coord/axisStatistics.js';
import { COORD_SYS_TYPE_POLAR } from '../coord/polar/PolarModel.js';
import { assert, each } from 'zrender/lib/core/util.js';
var callOnlyOnce = makeCallOnlyOnce();
function getSeriesStackId(seriesModel) {
  return seriesModel.get('stack') || '__ec_stack_' + seriesModel.seriesIndex;
}
export var barLayoutPolarStageHandler = createSimpleOverallStageHandler(SERIES_TYPE_BAR, barLayoutPolar);
function barLayoutPolar(ecModel) {
  var axisStatKey = makeAxisStatKey2(SERIES_TYPE_BAR, COORD_SYS_TYPE_POLAR);
  eachAxisOnKey(ecModel, axisStatKey, function (axis) {
    if (process.env.NODE_ENV !== 'production') {
      assert(axis instanceof AngleAxis || axis instanceof RadiusAxis);
    }
    var barWidthAndOffset = calcRadialBar(axis, SERIES_TYPE_BAR);
    var lastStackCoords = {};
    eachSeriesOnAxisOnKey(axis, axisStatKey, function (seriesModel) {
      layoutPerAxisPerSeries(axis, seriesModel, barWidthAndOffset, lastStackCoords);
    });
  });
}
function layoutPerAxisPerSeries(baseAxis, seriesModel, barWidthAndOffset, lastStackCoords) {
  var data = seriesModel.getData();
  var stackId = getSeriesStackId(seriesModel);
  var columnLayoutInfo = barWidthAndOffset[stackId];
  var columnOffset = columnLayoutInfo.offset;
  var columnWidth = columnLayoutInfo.width;
  var polar = seriesModel.coordinateSystem;
  if (process.env.NODE_ENV !== 'production') {
    assert(polar.type === COORD_SYS_TYPE_POLAR);
  }
  var valueAxis = polar.getOtherAxis(baseAxis);
  var cx = polar.cx;
  var cy = polar.cy;
  var barMinHeight = seriesModel.get('barMinHeight') || 0;
  var barMinAngle = seriesModel.get('barMinAngle') || 0;
  lastStackCoords[stackId] = lastStackCoords[stackId] || [];
  var valueDim = data.mapDimension(valueAxis.dim);
  var baseDim = data.mapDimension(baseAxis.dim);
  var stacked = isDimensionStacked(data, valueDim /* , baseDim */);
  var clampLayout = baseAxis.dim !== 'radius' || !seriesModel.get('roundCap', true);
  var valueAxisStart = valueAxis.dataToCoord(getStartValue(valueAxis));
  for (var idx = 0, len = data.count(); idx < len; idx++) {
    var value = data.get(valueDim, idx);
    var baseValue = data.get(baseDim, idx);
    var sign = value >= 0 ? 'p' : 'n';
    var baseCoord = valueAxisStart;
    // Because of the barMinHeight, we can not use the value in
    // stackResultDimension directly.
    if (stacked) {
      // FIXME: follow the same logic in `barGrid.ts`:
      //  Use stackResultDimension, and lastStackCoords is not needed.
      if (!lastStackCoords[stackId][baseValue]) {
        lastStackCoords[stackId][baseValue] = {
          p: valueAxisStart,
          n: valueAxisStart // Negative stack
        };
      }
      // Should also consider #4243
      baseCoord = lastStackCoords[stackId][baseValue][sign];
    }
    var r0 = void 0;
    var r = void 0;
    var startAngle = void 0;
    var endAngle = void 0;
    // radial sector
    if (valueAxis.dim === 'radius') {
      var radiusSpan = valueAxis.dataToCoord(value) - valueAxisStart;
      var angle = baseAxis.dataToCoord(baseValue);
      if (mathAbs(radiusSpan) < barMinHeight) {
        radiusSpan = (radiusSpan < 0 ? -1 : 1) * barMinHeight;
      }
      r0 = baseCoord;
      r = baseCoord + radiusSpan;
      startAngle = angle - columnOffset;
      endAngle = startAngle - columnWidth;
      stacked && (lastStackCoords[stackId][baseValue][sign] = r);
    }
    // tangential sector
    else {
      var angleSpan = valueAxis.dataToCoord(value, clampLayout) - valueAxisStart;
      var radius = baseAxis.dataToCoord(baseValue);
      if (mathAbs(angleSpan) < barMinAngle) {
        angleSpan = (angleSpan < 0 ? -1 : 1) * barMinAngle;
      }
      r0 = radius + columnOffset;
      r = r0 + columnWidth;
      startAngle = baseCoord;
      endAngle = baseCoord + angleSpan;
      // if the previous stack is at the end of the ring,
      // add a round to differentiate it from origin
      // let extent = angleAxis.getExtent();
      // let stackCoord = angle;
      // if (stackCoord === extent[0] && value > 0) {
      //     stackCoord = extent[1];
      // }
      // else if (stackCoord === extent[1] && value < 0) {
      //     stackCoord = extent[0];
      // }
      stacked && (lastStackCoords[stackId][baseValue][sign] = endAngle);
    }
    data.setItemLayout(idx, {
      cx: cx,
      cy: cy,
      r0: r0,
      r: r,
      // Consider that positive angle is anti-clockwise,
      // while positive radian of sector is clockwise
      startAngle: -startAngle * mathPI / 180,
      endAngle: -endAngle * mathPI / 180,
      /**
       * Keep the same logic with bar in catesion: use end value to
       * control direction. Notice that if clockwise is true (by
       * default), the sector will always draw clockwisely, no matter
       * whether endAngle is greater or less than startAngle.
       */
      clockwise: startAngle >= endAngle
    });
  }
}
/**
 * Calculate bar width and offset for radial bar charts
 */
function calcRadialBar(axis, seriesType) {
  var axisStatKey = makeAxisStatKey2(seriesType, COORD_SYS_TYPE_POLAR);
  var bandWidth = calcBandWidth(axis, {
    fromStat: {
      key: axisStatKey
    },
    min: 1
  }).w;
  var remainedWidth = bandWidth;
  var autoWidthCount = 0;
  var categoryGapOption = '20%';
  var gapOption = '30%';
  var stacks = {};
  eachSeriesOnAxisOnKey(axis, axisStatKey, function (seriesModel) {
    var stackId = getSeriesStackId(seriesModel);
    if (!stacks[stackId]) {
      autoWidthCount++;
    }
    stacks[stackId] = stacks[stackId] || {
      width: 0,
      maxWidth: 0
    };
    var barWidth = parsePercent(seriesModel.get('barWidth'), bandWidth);
    var barMaxWidth = parsePercent(seriesModel.get('barMaxWidth'), bandWidth);
    var barGapOption = seriesModel.get('barGap');
    var barCategoryGapOption = seriesModel.get('barCategoryGap');
    if (barWidth && !stacks[stackId].width) {
      barWidth = mathMin(remainedWidth, barWidth);
      stacks[stackId].width = barWidth;
      remainedWidth -= barWidth;
    }
    barMaxWidth && (stacks[stackId].maxWidth = barMaxWidth);
    // For historical design, use the last series declared that.
    barGapOption != null && (gapOption = barGapOption);
    barCategoryGapOption != null && (categoryGapOption = barCategoryGapOption);
  });
  var result = {};
  var categoryGap = parsePercent(categoryGapOption, bandWidth);
  var barGapPercent = parsePercent(gapOption, 1);
  var autoWidth = (remainedWidth - categoryGap) / (autoWidthCount + (autoWidthCount - 1) * barGapPercent);
  autoWidth = mathMax(autoWidth, 0);
  // Find if any auto calculated bar exceeded maxBarWidth
  each(stacks, function (column, stack) {
    var maxWidth = column.maxWidth;
    if (maxWidth && maxWidth < autoWidth) {
      maxWidth = mathMin(maxWidth, remainedWidth);
      if (column.width) {
        maxWidth = mathMin(maxWidth, column.width);
      }
      remainedWidth -= maxWidth;
      column.width = maxWidth;
      autoWidthCount--;
    }
  });
  // Recalculate width again
  autoWidth = (remainedWidth - categoryGap) / (autoWidthCount + (autoWidthCount - 1) * barGapPercent);
  autoWidth = mathMax(autoWidth, 0);
  var widthSum = 0;
  var lastColumn;
  each(stacks, function (column, idx) {
    if (!column.width) {
      column.width = autoWidth;
    }
    lastColumn = column;
    widthSum += column.width * (1 + barGapPercent);
  });
  if (lastColumn) {
    widthSum -= lastColumn.width * barGapPercent;
  }
  var offset = -widthSum / 2;
  each(stacks, function (column, stackId) {
    result[stackId] = result[stackId] || {
      offset: offset,
      width: column.width
    };
    offset += column.width * (1 + barGapPercent);
  });
  return result;
}
export function registerBarPolarAxisHandlers(registers, seriesType // Currently only 'bar' is supported.
) {
  callOnlyOnce(registers, function () {
    var axisStatKey = makeAxisStatKey2(seriesType, COORD_SYS_TYPE_POLAR);
    requireAxisStatisticsForBaseBar(registers, axisStatKey, seriesType, COORD_SYS_TYPE_POLAR);
    registerAxisContainShapeHandler(axisStatKey, createBandWidthBasedAxisContainShapeHandler(axisStatKey));
  });
}