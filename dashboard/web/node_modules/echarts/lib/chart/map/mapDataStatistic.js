
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
import { buildAllMapSeriesGroups, getMainMapSeries, SERIES_TYPE_MAP } from './MapSeries.js';
import { createSimpleOverallStageHandler } from '../../util/model.js';
// FIXME 公用？
function dataStatistics(datas, statisticType) {
  var dataNameMap = {};
  zrUtil.each(datas, function (data) {
    data.each(data.mapDimension('value'), function (value, idx) {
      // Add prefix to avoid conflict with Object.prototype.
      var mapKey = 'ec-' + data.getName(idx);
      dataNameMap[mapKey] = dataNameMap[mapKey] || [];
      if (!isNaN(value)) {
        dataNameMap[mapKey].push(value);
      }
    });
  });
  return datas[0].map(datas[0].mapDimension('value'), function (value, idx) {
    var mapKey = 'ec-' + datas[0].getName(idx);
    var sum = 0;
    var min = Infinity;
    var max = -Infinity;
    var len = dataNameMap[mapKey].length;
    for (var i = 0; i < len; i++) {
      min = Math.min(min, dataNameMap[mapKey][i]);
      max = Math.max(max, dataNameMap[mapKey][i]);
      sum += dataNameMap[mapKey][i];
    }
    var result;
    if (statisticType === 'min') {
      result = min;
    } else if (statisticType === 'max') {
      result = max;
    } else if (statisticType === 'average') {
      result = sum / len;
    } else {
      result = sum;
    }
    return len === 0 ? NaN : result;
  });
}
export var mapDataStatisticStageHandler = createSimpleOverallStageHandler(SERIES_TYPE_MAP, mapDataStatistic);
function mapDataStatistic(ecModel) {
  zrUtil.each(buildAllMapSeriesGroups(ecModel), function (seriesGroup) {
    var mainSeries = getMainMapSeries(seriesGroup);
    if (!mainSeries) {
      return;
    }
    var data = dataStatistics(zrUtil.map(seriesGroup.f, function (seriesModel) {
      return seriesModel.getData();
    }),
    // PENDING: It has long been using `seriesGroup[0]` here, but if the first map series
    // is filtered out by legend, `seriesGroup[0]` is the second series in ec option, therefore,
    // this definition is not reasonable enough for users.
    mainSeries.get('mapValueCalculation'));
    zrUtil.each(seriesGroup.f, function (series) {
      series.seriesGroup = seriesGroup;
      series.originalData = series.getData();
      series.setData(data.cloneShallow());
    });
  });
}