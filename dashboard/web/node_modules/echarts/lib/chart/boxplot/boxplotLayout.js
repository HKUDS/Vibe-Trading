
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
import { isArray } from 'zrender/lib/core/util.js';
import { mathMax, mathMin, parsePercent } from '../../util/number.js';
import { SERIES_TYPE_BOXPLOT } from './BoxplotSeries.js';
import { countSeriesOnAxisOnKey, eachAxisOnKey, eachSeriesOnAxisOnKey, requireAxisStatistics } from '../../coord/axisStatistics.js';
import { createSimpleOverallStageHandler, makeCallOnlyOnce } from '../../util/model.js';
import { registerAxisContainShapeHandler } from '../../coord/scaleRawExtentInfo.js';
import { calcBandWidth } from '../../coord/axisBand.js';
import { createBandWidthBasedAxisContainShapeHandler, createMetricsNonOrdinalLinearPositiveMinGap, makeAxisStatKey } from '../helper/axisSnippets.js';
var callOnlyOnce = makeCallOnlyOnce();
export var boxplotLayoutStageHandler = createSimpleOverallStageHandler(SERIES_TYPE_BOXPLOT, boxplotLayout);
function boxplotLayout(ecModel) {
  var axisStatKey = makeAxisStatKey(SERIES_TYPE_BOXPLOT);
  eachAxisOnKey(ecModel, axisStatKey, function (axis) {
    var seriesCount = countSeriesOnAxisOnKey(axis, axisStatKey);
    if (!seriesCount) {
      return;
    }
    var baseResult = calculateBase(axis, seriesCount);
    eachSeriesOnAxisOnKey(axis, axisStatKey, function (seriesModel) {
      var seriesIndex = seriesModel.seriesIndex;
      layoutSingleSeries(seriesModel, baseResult.boxOffsetList[seriesIndex], baseResult.boxWidthList[seriesIndex]);
    });
  });
}
/**
 * Calculate offset and box width for each series.
 */
function calculateBase(baseAxis, seriesCount) {
  var boxWidthList = [];
  var boxOffsetList = [];
  var boundList = [];
  var bandWidth = calcBandWidth(baseAxis, {
    fromStat: {
      key: makeAxisStatKey(SERIES_TYPE_BOXPLOT)
    },
    min: 1
  }).w;
  eachSeriesOnAxisOnKey(baseAxis, makeAxisStatKey(SERIES_TYPE_BOXPLOT), function (seriesModel) {
    var boxWidthBound = seriesModel.get('boxWidth');
    if (!isArray(boxWidthBound)) {
      boxWidthBound = [boxWidthBound, boxWidthBound];
    }
    boundList[seriesModel.seriesIndex] = [parsePercent(boxWidthBound[0], bandWidth) || 0, parsePercent(boxWidthBound[1], bandWidth) || 0];
  });
  var availableWidth = bandWidth * 0.8 - 2;
  var boxGap = availableWidth / seriesCount * 0.3;
  var boxWidth = (availableWidth - boxGap * (seriesCount - 1)) / seriesCount;
  var base = boxWidth / 2 - availableWidth / 2;
  eachSeriesOnAxisOnKey(baseAxis, makeAxisStatKey(SERIES_TYPE_BOXPLOT), function (seriesModel) {
    var seriesIndex = seriesModel.seriesIndex;
    boxOffsetList[seriesIndex] = base;
    base += boxGap + boxWidth;
    boxWidthList[seriesIndex] = mathMin(mathMax(boxWidth, boundList[seriesIndex][0]), boundList[seriesIndex][1]);
  });
  return {
    boxOffsetList: boxOffsetList,
    boxWidthList: boxWidthList
  };
}
/**
 * Calculate points location for each series.
 */
function layoutSingleSeries(seriesModel, offset, boxWidth) {
  var coordSys = seriesModel.coordinateSystem;
  var data = seriesModel.getData();
  var halfWidth = boxWidth / 2;
  var cDimIdx = seriesModel.getWhiskerBoxesLayout() === 'horizontal' ? 0 : 1;
  var vDimIdx = 1 - cDimIdx;
  var coordDims = ['x', 'y'];
  var cDim = data.mapDimension(coordDims[cDimIdx]);
  var vDims = data.mapDimensionsAll(coordDims[vDimIdx]);
  if (cDim == null || vDims.length < 5) {
    return;
  }
  for (var dataIndex = 0; dataIndex < data.count(); dataIndex++) {
    var axisDimVal = data.get(cDim, dataIndex);
    var median = getPoint(axisDimVal, vDims[2], dataIndex);
    var end1 = getPoint(axisDimVal, vDims[0], dataIndex);
    var end2 = getPoint(axisDimVal, vDims[1], dataIndex);
    var end4 = getPoint(axisDimVal, vDims[3], dataIndex);
    var end5 = getPoint(axisDimVal, vDims[4], dataIndex);
    var ends = [];
    addBodyEnd(ends, end2, false);
    addBodyEnd(ends, end4, true);
    ends.push(end1, end2, end5, end4);
    layEndLine(ends, end1);
    layEndLine(ends, end5);
    layEndLine(ends, median);
    data.setItemLayout(dataIndex, {
      initBaseline: median[vDimIdx],
      ends: ends
    });
  }
  function getPoint(axisDimVal, dim, dataIndex) {
    var val = data.get(dim, dataIndex);
    var p = [];
    p[cDimIdx] = axisDimVal;
    p[vDimIdx] = val;
    var point;
    if (isNaN(axisDimVal) || isNaN(val)) {
      point = [NaN, NaN];
    } else {
      point = coordSys.dataToPoint(p);
      point[cDimIdx] += offset;
    }
    return point;
  }
  function addBodyEnd(ends, point, start) {
    var point1 = point.slice();
    var point2 = point.slice();
    point1[cDimIdx] += halfWidth;
    point2[cDimIdx] -= halfWidth;
    start ? ends.push(point1, point2) : ends.push(point2, point1);
  }
  function layEndLine(ends, endCenter) {
    var from = endCenter.slice();
    var to = endCenter.slice();
    from[cDimIdx] -= halfWidth;
    to[cDimIdx] += halfWidth;
    ends.push(from, to);
  }
}
export function registerBoxplotAxisHandlers(registers) {
  callOnlyOnce(registers, function () {
    var axisStatKey = makeAxisStatKey(SERIES_TYPE_BOXPLOT);
    requireAxisStatistics(registers, {
      key: axisStatKey,
      seriesType: SERIES_TYPE_BOXPLOT,
      getMetrics: createMetricsNonOrdinalLinearPositiveMinGap
    });
    registerAxisContainShapeHandler(axisStatKey, createBandWidthBasedAxisContainShapeHandler(axisStatKey));
  });
}