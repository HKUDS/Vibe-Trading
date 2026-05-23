
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
import { each, defaults, hasOwn, assert } from 'zrender/lib/core/util.js';
import { mathAbs, mathMax, mathMin, parsePercent } from '../util/number.js';
import { isDimensionStacked } from '../data/helper/dataStackHelper.js';
import createRenderPlanner from '../chart/helper/createRenderPlanner.js';
import Axis2D from '../coord/cartesian/Axis2D.js';
import { createFloat32Array } from '../util/vendor.js';
import { makeCallOnlyOnce } from '../util/model.js';
import { isOrdinalScale } from '../scale/helper.js';
import { isCartesian2DInjectedAsDataCoordSys } from '../coord/cartesian/cartesianAxisHelper.js';
import { registerAxisContainShapeHandler } from '../coord/scaleRawExtentInfo.js';
import { eachAxisOnKey, eachSeriesOnAxisOnKey } from '../coord/axisStatistics.js';
import { calcBandWidth } from '../coord/axisBand.js';
import { getStartValue, requireAxisStatisticsForBaseBar } from './barCommon.js';
import { COORD_SYS_TYPE_CARTESIAN_2D } from '../coord/cartesian/GridModel.js';
import { createBandWidthBasedAxisContainShapeHandler, makeAxisStatKey2 } from '../chart/helper/axisSnippets.js';
var callOnlyOnce = makeCallOnlyOnce();
var STACK_PREFIX = '__ec_stack_';
function getSeriesStackId(seriesModel) {
  return seriesModel.get('stack') || STACK_PREFIX + seriesModel.seriesIndex;
}
/**
 * Return null/undefined if not 'category' axis.
 *
 * PENDING: The layout on non-'category' axis relies on `bandWidth`, which is calculated
 * based on the `linearPositiveMinGap` of series data. This strategy is somewhat heuristic
 * and will not be public to custom series until required in future. Additionally, more ec
 * options may be introduced for that, because it requires `requireAxisStatistics` to be
 * called on custom series that requires this feature.
 */
export function computeBarLayoutForCustomSeries(opt) {
  if (!isOrdinalScale(opt.axis.scale)) {
    return;
  }
  var bandWidthResult = calcBandWidth(opt.axis);
  var params = [];
  for (var i = 0; i < opt.count || 0; i++) {
    params.push(defaults({
      stackId: STACK_PREFIX + i
    }, opt));
  }
  var widthAndOffsets = calcBarWidthAndOffset({
    bandWidthResult: bandWidthResult,
    seriesInfo: params
  });
  var result = [];
  for (var i = 0; i < opt.count; i++) {
    var item = widthAndOffsets[STACK_PREFIX + i];
    item.offsetCenter = item.offset + item.width / 2;
    result.push(item);
  }
  return result;
}
/**
 * NOTICE: This layout is based on axis pixel extent and scale extent.
 *  It may be used on estimation, where axis pixel extent and scale extent
 *  are approximately set. But the result should not be cached since the
 *  axis pixel extent and scale extent may be changed finally.
 */
function makeColumnLayoutOnAxisReal(baseAxis, seriesType) {
  var seriesInfoListOnAxis = createLayoutInfoListOnAxis(baseAxis, seriesType);
  seriesInfoListOnAxis.columnMap = calcBarWidthAndOffset(seriesInfoListOnAxis);
  return seriesInfoListOnAxis;
}
function createLayoutInfoListOnAxis(baseAxis, seriesType) {
  var axisStatKey = makeAxisStatKey2(seriesType, COORD_SYS_TYPE_CARTESIAN_2D);
  var seriesInfoOnAxis = [];
  var bandWidthResult = calcBandWidth(baseAxis, {
    fromStat: {
      key: axisStatKey
    },
    min: 1
  });
  eachSeriesOnAxisOnKey(baseAxis, axisStatKey, function (seriesModel) {
    seriesInfoOnAxis.push({
      barWidth: parsePercent(seriesModel.get('barWidth'), bandWidthResult.w),
      barMaxWidth: parsePercent(seriesModel.get('barMaxWidth'), bandWidthResult.w),
      barMinWidth: parsePercent(
      // barMinWidth by default is 0.5 / 1 in cartesian. Because in value axis,
      // the auto-calculated bar width might be less than 0.5 / 1.
      seriesModel.get('barMinWidth') || (isInLargeMode(seriesModel) ? 0.5 : 1), bandWidthResult.w),
      barGap: seriesModel.get('barGap'),
      barCategoryGap: seriesModel.get('barCategoryGap'),
      defaultBarGap: seriesModel.get('defaultBarGap'),
      stackId: getSeriesStackId(seriesModel)
    });
  });
  return {
    bandWidthResult: bandWidthResult,
    seriesInfo: seriesInfoOnAxis
  };
}
/**
 * CAUTION: When multiple series are laid out on one axis, relevant ec options effect all series.
 * But for historical reason, these options are configured on each series option, which may
 * introduce confliction. The legacy implementation uses some options (e.g., `defaultBarGap`)
 * from the first declared series, and other options (e.g., `barGap`, `barCategoryGap`) from the last declared
 * series. Nevertheless, We remain this design to avoid breaking change.
 */
function calcBarWidthAndOffset(seriesInfoOnAxis) {
  var bandWidth = seriesInfoOnAxis.bandWidthResult.w;
  var remainedWidth = bandWidth;
  var autoWidthCount = 0;
  var barCategoryGapOption;
  var barGapOption;
  var stackIdList = [];
  var stackMap = {};
  each(seriesInfoOnAxis.seriesInfo, function (seriesInfo, idx) {
    if (!idx) {
      barGapOption = seriesInfo.defaultBarGap || 0;
    }
    var stackId = seriesInfo.stackId;
    if (!hasOwn(stackMap, stackId)) {
      autoWidthCount++;
    }
    var stackItem = stackMap[stackId];
    if (!stackItem) {
      stackItem = stackMap[stackId] = {
        width: 0,
        maxWidth: 0
      };
      stackIdList.push(stackId);
    }
    var barWidth = seriesInfo.barWidth;
    if (barWidth && !stackItem.width) {
      // See #6312, do not restrict width.
      stackItem.width = barWidth;
      barWidth = mathMin(remainedWidth, barWidth);
      remainedWidth -= barWidth;
    }
    var barMaxWidth = seriesInfo.barMaxWidth;
    barMaxWidth && (stackItem.maxWidth = barMaxWidth);
    var barMinWidth = seriesInfo.barMinWidth;
    barMinWidth && (stackItem.minWidth = barMinWidth);
    var barGap = seriesInfo.barGap;
    barGap != null && (barGapOption = barGap);
    var barCategoryGap = seriesInfo.barCategoryGap;
    barCategoryGap != null && (barCategoryGapOption = barCategoryGap);
  });
  if (barCategoryGapOption == null) {
    // More columns in one group
    // the spaces between group is smaller. Or the column will be too thin.
    barCategoryGapOption = mathMax(35 - stackIdList.length * 4, 15) + '%';
  }
  var barCategoryGapNum = parsePercent(barCategoryGapOption, bandWidth);
  var barGapPercent = parsePercent(barGapOption, 1);
  var autoWidth = (remainedWidth - barCategoryGapNum) / (autoWidthCount + (autoWidthCount - 1) * barGapPercent);
  autoWidth = mathMax(autoWidth, 0);
  // Find if any auto calculated bar exceeded maxBarWidth
  each(stackIdList, function (stackId) {
    var column = stackMap[stackId];
    var maxWidth = column.maxWidth;
    var minWidth = column.minWidth;
    if (!column.width) {
      var finalWidth = autoWidth;
      if (maxWidth && maxWidth < finalWidth) {
        finalWidth = mathMin(maxWidth, remainedWidth);
      }
      // `minWidth` has higher priority. `minWidth` decide that whether the
      // bar is able to be visible. So `minWidth` should not be restricted
      // by `maxWidth` or `remainedWidth` (which is from `bandWidth`). In
      // the extreme cases for `value` axis, bars are allowed to overlap
      // with each other if `minWidth` specified.
      if (minWidth && minWidth > finalWidth) {
        finalWidth = minWidth;
      }
      if (finalWidth !== autoWidth) {
        column.width = finalWidth;
        remainedWidth -= finalWidth + barGapPercent * finalWidth;
        autoWidthCount--;
      }
    } else {
      // `barMinWidth/barMaxWidth` has higher priority than `barWidth`, as
      // CSS does. Because barWidth can be a percent value, where
      // `barMaxWidth` can be used to restrict the final width.
      var finalWidth = column.width;
      if (maxWidth) {
        finalWidth = mathMin(finalWidth, maxWidth);
      }
      // `minWidth` has higher priority, as described above
      if (minWidth) {
        finalWidth = mathMax(finalWidth, minWidth);
      }
      column.width = finalWidth;
      remainedWidth -= finalWidth + barGapPercent * finalWidth;
      autoWidthCount--;
    }
  });
  // Recalculate width again
  autoWidth = (remainedWidth - barCategoryGapNum) / (autoWidthCount + (autoWidthCount - 1) * barGapPercent);
  autoWidth = mathMax(autoWidth, 0);
  var widthSum = 0;
  var lastColumn;
  each(stackIdList, function (stackId) {
    var column = stackMap[stackId];
    if (!column.width) {
      column.width = autoWidth;
    }
    lastColumn = column;
    widthSum += column.width * (1 + barGapPercent);
  });
  if (lastColumn) {
    widthSum -= lastColumn.width * barGapPercent;
  }
  var result = {};
  var offset = -widthSum / 2;
  each(stackIdList, function (stackId) {
    var column = stackMap[stackId];
    result[stackId] = result[stackId] || {
      bandWidth: bandWidth,
      offset: offset,
      width: column.width
    };
    offset += column.width * (1 + barGapPercent);
  });
  return result;
}
export function createCrossSeriesLayoutHandler(seriesType) {
  return {
    seriesType: seriesType,
    overallReset: function (ecModel) {
      var axisStatKey = makeAxisStatKey2(seriesType, COORD_SYS_TYPE_CARTESIAN_2D);
      eachAxisOnKey(ecModel, axisStatKey, function (axis) {
        if (process.env.NODE_ENV !== 'production') {
          assert(axis instanceof Axis2D);
        }
        var columnLayout = makeColumnLayoutOnAxisReal(axis, seriesType);
        eachSeriesOnAxisOnKey(axis, axisStatKey, function (seriesModel) {
          var columnLayoutInfo = columnLayout.columnMap[getSeriesStackId(seriesModel)];
          seriesModel.getData().setLayout({
            bandWidth: columnLayoutInfo.bandWidth,
            offset: columnLayoutInfo.offset,
            size: columnLayoutInfo.width
          });
        });
      });
    }
  };
}
;
// TODO: Do not support stack in large mode yet.
export function createProgressiveLayout(seriesType) {
  return {
    seriesType: seriesType,
    plan: createRenderPlanner(),
    reset: function (seriesModel) {
      if (!isCartesian2DInjectedAsDataCoordSys(seriesModel)) {
        return;
      }
      var data = seriesModel.getData();
      var cartesian = seriesModel.coordinateSystem;
      var baseAxis = cartesian.getBaseAxis();
      var valueAxis = cartesian.getOtherAxis(baseAxis);
      var valueDimIdx = data.getDimensionIndex(data.mapDimension(valueAxis.dim));
      var baseDimIdx = data.getDimensionIndex(data.mapDimension(baseAxis.dim));
      var drawBackground = seriesModel.get('showBackground', true);
      var valueDim = data.mapDimension(valueAxis.dim);
      var stackResultDim = data.getCalculationInfo('stackResultDimension');
      var stacked = isDimensionStacked(data, valueDim) && !!data.getCalculationInfo('stackedOnSeries');
      var isValueAxisH = valueAxis.isHorizontal();
      var valueAxisStart = valueAxis.toGlobalCoord(valueAxis.dataToCoord(getStartValue(valueAxis)));
      var isLarge = isInLargeMode(seriesModel);
      var barMinHeight = seriesModel.get('barMinHeight') || 0;
      var stackedDimIdx = stackResultDim && data.getDimensionIndex(stackResultDim);
      // Layout info.
      var columnWidth = data.getLayout('size');
      var columnOffset = data.getLayout('offset');
      return {
        progress: function (params, data) {
          var count = params.count;
          var largePoints = isLarge && createFloat32Array(count * 3);
          var largeBackgroundPoints = isLarge && drawBackground && createFloat32Array(count * 3);
          var largeDataIndices = isLarge && createFloat32Array(count);
          var coordLayout = cartesian.master.getRect();
          var bgSize = isValueAxisH ? coordLayout.width : coordLayout.height;
          var dataIndex;
          var store = data.getStore();
          var idxOffset = 0;
          while ((dataIndex = params.next()) != null) {
            var value = store.get(stacked ? stackedDimIdx : valueDimIdx, dataIndex);
            var baseValue = store.get(baseDimIdx, dataIndex);
            var baseCoord = valueAxisStart;
            var stackStartValue = void 0;
            // Because of the barMinHeight, we can not use the value in
            // stackResultDimension directly.
            if (stacked) {
              stackStartValue = +value - store.get(valueDimIdx, dataIndex);
            }
            var x = void 0;
            var y = void 0;
            var width = void 0;
            var height = void 0;
            if (isValueAxisH) {
              var coord = cartesian.dataToPoint([value, baseValue]);
              if (stacked) {
                baseCoord = cartesian.dataToPoint([stackStartValue, baseValue])[0];
              }
              x = baseCoord;
              y = coord[1] + columnOffset;
              width = coord[0] - baseCoord;
              height = columnWidth;
              if (mathAbs(width) < barMinHeight) {
                width = (width < 0 ? -1 : 1) * barMinHeight;
              }
            } else {
              var coord = cartesian.dataToPoint([baseValue, value]);
              if (stacked) {
                baseCoord = cartesian.dataToPoint([baseValue, stackStartValue])[1];
              }
              x = coord[0] + columnOffset;
              y = baseCoord;
              width = columnWidth;
              height = coord[1] - baseCoord;
              if (mathAbs(height) < barMinHeight) {
                // Include zero to has a positive bar
                height = (height <= 0 ? -1 : 1) * barMinHeight;
              }
            }
            if (!isLarge) {
              data.setItemLayout(dataIndex, {
                x: x,
                y: y,
                width: width,
                height: height
              });
            } else {
              largePoints[idxOffset] = x;
              largePoints[idxOffset + 1] = y;
              largePoints[idxOffset + 2] = isValueAxisH ? width : height;
              if (largeBackgroundPoints) {
                largeBackgroundPoints[idxOffset] = isValueAxisH ? coordLayout.x : x;
                largeBackgroundPoints[idxOffset + 1] = isValueAxisH ? y : coordLayout.y;
                largeBackgroundPoints[idxOffset + 2] = bgSize;
              }
              largeDataIndices[dataIndex] = dataIndex;
            }
            idxOffset += 3;
          }
          if (isLarge) {
            data.setLayout({
              largePoints: largePoints,
              largeDataIndices: largeDataIndices,
              largeBackgroundPoints: largeBackgroundPoints,
              valueAxisHorizontal: isValueAxisH
            });
          }
        }
      };
    }
  };
}
function isInLargeMode(seriesModel) {
  return seriesModel.pipelineContext && seriesModel.pipelineContext.large;
}
function barGridCreateAxisContainShapeHandler(seriesType) {
  // See also #6728, #4862, `test/bar-overflow-time-plot.html` `test/bar-overflow-plot2.html`
  // NOTE:
  //  Series shapes may overflow `bandWidth` when ec option is set like:
  //    - `barWidth` > 100%.
  //    - `barWidth` is set as absolute pixel values and `dataZoom` is used, since `bandWidth` is
  //      calculated on data space rather than pixel space.
  //  We originally used `calcShapeOverflowSupplement` to cover this case, but it still can not
  //  resolve pixel `barWidth` case perfectly. A thorough solution may introduce considerable complex,
  //  but may not necessary, since users can avoid it by proper ec option settings.
  //  Therefore, we use simply `createBandWidthBasedAxisContainShapeHandler` to calculate "containShape"
  //  only based on `bandWidth`.
  return createBandWidthBasedAxisContainShapeHandler(makeAxisStatKey2(seriesType, COORD_SYS_TYPE_CARTESIAN_2D));
  // return function (axis, scale, ecModel) {
  //     if (!countSeriesOnAxisOnKey(axis, makeAxisStatKey2(seriesType, COORD_SYS_TYPE_CARTESIAN_2D))) {
  //         return; // Quick path - in most cases there is no bar on non-ordinal axis.
  //     }
  //     const columnLayout = makeColumnLayoutOnAxisReal(axis, seriesType);
  //     return calcShapeOverflowSupplement(columnLayout);
  // };
}
// /**
//  * @see [AXIS_CONTAIN_SHAPE_COMMON_STRATEGY] for more details.
//  */
// function calcShapeOverflowSupplement(
//     columnLayout: BarGridColumnLayoutOnAxis | NullUndefined
// ): number[] | NullUndefined {
//     if (columnLayout == null) {
//         return;
//     }
//     const bandWidthResult = columnLayout.bandWidthResult;
//     const invRatio = bandWidthResult.invRatio;
//     if (!isNullableNumberFinite(invRatio)) {
//         return; // No series data or no more than one distinct valid data values.
//     }
//     const barsBoundPx = initExtentForUnion();
//     const bandWidth = bandWidthResult.w;
//     // Union `-bandWidth / 2` and `bandWidth / 2` to provide extra space for visually preferred,
//     // Otherwise the bars on the edges may overlap with axis line.
//     // And it also includes `0`, which ensures `barsBoundPx[0] <= 0 <= barsBoundPx[1]`.
//     unionExtentFromNumber(barsBoundPx, -bandWidth / 2);
//     unionExtentFromNumber(barsBoundPx, bandWidth / 2);
//     // Shapes may overflow the `bandWidth`. For example, that might happen in `pictorialBar`.
//     // Therefore, we also involve shape size (mapped to data scale) in this expansion calculation.
//     each(columnLayout.columnMap, function (item) {
//         unionExtentFromNumber(barsBoundPx, item.offset);
//         unionExtentFromNumber(barsBoundPx, item.offset + item.width);
//     });
//     if (extentHasValue(barsBoundPx)) {
//         // Convert from pixel domain to data domain, since the `barsBoundPx` is calculated based on
//         // `minGap` and extent on data domain.
//         return [barsBoundPx[0] * invRatio, barsBoundPx[1] * invRatio];
//         // If AXIS_BAND_WIDTH_KIND_SINGULAR, extent expansion is not needed.
//     }
// }
export function registerBarGridAxisHandlers(registers) {
  callOnlyOnce(registers, function () {
    function register(seriesType) {
      var axisStatKey = makeAxisStatKey2(seriesType, COORD_SYS_TYPE_CARTESIAN_2D);
      requireAxisStatisticsForBaseBar(registers, axisStatKey, seriesType, COORD_SYS_TYPE_CARTESIAN_2D);
      registerAxisContainShapeHandler(axisStatKey, barGridCreateAxisContainShapeHandler(seriesType));
    }
    register('bar');
    register('pictorialBar');
  });
}