
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
import { assert, createHashMap, each, retrieve2 } from 'zrender/lib/core/util.js';
import { makeCallOnlyOnce, makeInner } from '../util/model.js';
import { getCachePerECFullUpdate, getCachePerECPrepare } from '../util/cycleCache.js';
var callOnlyOnce = makeCallOnlyOnce();
// Ensure that it never appears in internal generated uid and pre-defined coordSysType.
export var AXIS_STAT_KEY_DELIMITER = '|&';
var ecModelCacheFullUpdateInner = makeInner();
// In this case, there are one or multiple valid data value but all the same.
export var LINEAR_POSITIVE_MIN_GAP_SINGLE_VALID_VALUE = -2;
export var LINEAR_POSITIVE_MIN_GAP_NO_VALID_VALUE = -1;
var ecModelCachePrepareInner = makeInner();
var validateInputAxis;
if (process.env.NODE_ENV !== 'production') {
  validateInputAxis = function (axis) {
    assert(axis && axis.model && axis.model.uid && axis.model.ecModel);
  };
}
function getAxisStatPerKeyPerAxis(axis, axisStatKey) {
  var axisModel = axis.model;
  var keyed = ecModelCacheFullUpdateInner(getCachePerECFullUpdate(axisModel.ecModel)).keyed;
  var perKey = keyed && keyed.get(axisStatKey);
  return perKey && perKey.get(axisModel.uid);
}
export function getAxisStat(axis, axisStatKey
// Return: Never return null/undefined.
) {
  if (process.env.NODE_ENV !== 'production') {
    assert(axisStatKey != null);
    validateInputAxis(axis);
  }
  return wrapStatResult(getAxisStatPerKeyPerAxis(axis, axisStatKey));
}
export function getAxisStatBySeries(axis, seriesList
// Return: Never be null/undefined; never contain null/undefined.
) {
  if (process.env.NODE_ENV !== 'production') {
    validateInputAxis(axis);
  }
  var result = [];
  eachKeyEachAxis(axis.model.ecModel, function (perKeyPerAxis) {
    for (var idx = 0; idx < seriesList.length; idx++) {
      if (seriesList[idx] && perKeyPerAxis.serByIdx[seriesList[idx].seriesIndex]) {
        result.push(wrapStatResult(perKeyPerAxis));
      }
    }
  });
  return result;
}
function eachKeyEachAxis(ecModel, cb) {
  var keyed = ecModelCacheFullUpdateInner(getCachePerECFullUpdate(ecModel)).keyed;
  keyed && keyed.each(function (perKey, axisStatKey) {
    perKey.each(function (perKeyPerAxis, axisModelUid) {
      cb(perKeyPerAxis, axisStatKey, axisModelUid);
    });
  });
}
function wrapStatResult(record) {
  return {
    liPosMinGap: record ? record.liPosMinGap : undefined
  };
}
export function eachSeriesOnAxis(axis, cb) {
  if (process.env.NODE_ENV !== 'production') {
    validateInputAxis(axis);
  }
  var ecModel = axis.model.ecModel;
  var seriesOnAxisMap = ecModelCacheFullUpdateInner(getCachePerECFullUpdate(ecModel)).axSer;
  seriesOnAxisMap && eachSeriesDealForAxisStat(ecModel, seriesOnAxisMap.get(axis.model.uid), cb);
}
/**
 * NOTE:
 *  - series declaration order is respected (some ec option precedence matters, e.g., bar series).
 *  - series filtered out are excluded.
 */
export function eachSeriesOnAxisOnKey(axis, axisStatKey, cb) {
  if (process.env.NODE_ENV !== 'production') {
    assert(axisStatKey != null);
    validateInputAxis(axis);
  }
  var perKeyPerAxis = getAxisStatPerKeyPerAxis(axis, axisStatKey);
  perKeyPerAxis && eachSeriesDealForAxisStat(axis.model.ecModel, perKeyPerAxis.sers, cb);
}
export function eachSeriesDealForAxisStat(ecModel, seriesList, cb) {
  if (!seriesList) {
    return;
  }
  for (var i = 0; i < seriesList.length; i++) {
    var seriesModel = seriesList[i];
    // Legend-filtered series need to be ignored since series are registered before `legendFilter`.
    if (!ecModel.isSeriesFiltered(seriesModel)) {
      cb(seriesModel);
    }
  }
}
/**
 * NOTE:
 *  - series filtered out are excluded.
 */
export function countSeriesOnAxisOnKey(axis, axisStatKey) {
  if (process.env.NODE_ENV !== 'production') {
    assert(axisStatKey != null);
    validateInputAxis(axis);
  }
  var perKeyPerAxis = getAxisStatPerKeyPerAxis(axis, axisStatKey);
  if (!perKeyPerAxis || !perKeyPerAxis.sers.length) {
    return 0;
  }
  var count = 0;
  eachSeriesDealForAxisStat(axis.model.ecModel, perKeyPerAxis.sers, function () {
    count++;
  });
  return count;
}
/**
 * NOTICE: Available after `CoordinateSystem['create']` (not included).
 *
 * Query all axes that have at least one associated series (via `associateSeriesWithAxis`)
 * by the given key.
 */
export function eachAxisOnKey(ecModel, axisStatKey, cb) {
  if (process.env.NODE_ENV !== 'production') {
    assert(axisStatKey != null);
  }
  var keyed = ecModelCacheFullUpdateInner(getCachePerECFullUpdate(ecModel)).keyed;
  var perKey = keyed && keyed.get(axisStatKey);
  perKey && perKey.each(function (perKeyPerAxis) {
    if (process.env.NODE_ENV !== 'production') {
      assert(perKeyPerAxis.sers.length > 0); // This is to avoid irrelevant axes to enter `cb`.
    }
    cb(perKeyPerAxis.axis);
  });
}
/**
 * NOTICE: Available after `CoordinateSystem['create']` (not included).
 *
 * Query all `AxisStatKey`s that have at least one associated series (via `associateSeriesWithAxis`)
 * by the given axis.
 */
export function eachKeyOnAxis(axis, cb) {
  if (process.env.NODE_ENV !== 'production') {
    validateInputAxis(axis);
  }
  var model = axis.model;
  var keysByAxisModelUid = ecModelCacheFullUpdateInner(getCachePerECFullUpdate(model.ecModel)).keys;
  keysByAxisModelUid && each(keysByAxisModelUid.get(model.uid), function (axisStatKey) {
    if (process.env.NODE_ENV !== 'production') {
      var stat = getAxisStatPerKeyPerAxis(axis, axisStatKey);
      assert(stat && stat.sers.length > 0); // This is to avoid irrelevant `AxisStatKey` to enter `cb`.
    }
    cb(axisStatKey);
  });
}
/**
 * NOTICE: this processor may be omitted - it is registered only if required.
 */
function performAxisStatisticsOnOverallReset(ecModel) {
  var ecPrepareCache = ecModelCachePrepareInner(getCachePerECPrepare(ecModel));
  var ecPrepareCacheKeyed = ecPrepareCache.keyed || (ecPrepareCache.keyed = createHashMap());
  eachKeyEachAxis(ecModel, function (perKeyPerAxis, axisStatKey, axisModelUid) {
    var ecPrepareCachePerKey = ecPrepareCacheKeyed.get(axisStatKey) || ecPrepareCacheKeyed.set(axisStatKey, createHashMap());
    var ecPreparePerKeyPerAxis = ecPrepareCachePerKey.get(axisModelUid) || ecPrepareCachePerKey.set(axisModelUid, {});
    if (perKeyPerAxis.metrics.liPosMinGap) {
      // We should assert the impl exists -- fail-fast if missing `registerMetricImpl`.
      _metricImpl.liPosMinGap(ecModel, perKeyPerAxis, ecPreparePerKeyPerAxis);
    }
  });
}
// To reduce code size from unnecessary metrics.
export function registerMetricImpl(metricType, impl) {
  _metricImpl[metricType] = impl;
}
var _metricImpl = {};
/**
 * NOTICE:
 *  - It must be called in `CoordinateSystem['create']`, before series filtering.
 *  - It must be called in `seriesIndex` ascending order (series declaration order).
 *    i.e., iterated by `ecModel.eachSeries`.
 *  - Every <axis, series> pair can only call this method once.
 *
 * @see scaleRawExtentInfoCreate in `scaleRawExtentInfo.ts`
 */
export function associateSeriesWithAxis(axis, seriesModel, coordSysType) {
  if (!axis) {
    return;
  }
  var ecModel = seriesModel.ecModel;
  var ecFullUpdateCache = ecModelCacheFullUpdateInner(getCachePerECFullUpdate(ecModel));
  var axisModelUid = axis.model.uid;
  if (process.env.NODE_ENV !== 'production') {
    validateInputAxis(axis);
    // - An axis can be associated with multiple `axisStatKey`s. For example, if `axisStatKey`s are
    //   "candlestick" and "bar", they can be associated with the same "xAxis".
    // - Within an individual axis, it is a typically incorrect usage if a <axis, series> pair is
    //   associated with multiple `perKeyPerAxis`, which may cause repeated calculation and
    //   performance degradation, had hard to be found without the checking below. For example, If
    //   `axisStatKey` are "grid-bar" (see `barGrid.ts`) and "polar-bar" (see `barPolar.ts`), and
    //   a <xAxis-series> pair is wrongly associated with both "polar-bar" and "grid-bar", the
    //   relevant statistics will be computed twice.
    var axSerPairCheck = ecFullUpdateCache.axSerPairCheck || (ecFullUpdateCache.axSerPairCheck = createHashMap());
    var pairKey = "" + axisModelUid + AXIS_STAT_KEY_DELIMITER + seriesModel.uid;
    assert(!axSerPairCheck.get(pairKey));
    axSerPairCheck.set(pairKey, 1);
  }
  var seriesOnAxisMap = ecFullUpdateCache.axSer || (ecFullUpdateCache.axSer = createHashMap());
  var seriesListPerAxis = seriesOnAxisMap.get(axisModelUid) || seriesOnAxisMap.set(axisModelUid, []);
  if (process.env.NODE_ENV !== 'production') {
    var lastSeries = seriesListPerAxis[seriesListPerAxis.length - 1];
    if (lastSeries) {
      // Series order should respect to the input order, since it matters in some cases
      // (e.g., see `barGrid.ts` and `barPolar.ts` - ec option declaration order matters).
      assert(lastSeries.seriesIndex < seriesModel.seriesIndex);
    }
  }
  seriesListPerAxis.push(seriesModel);
  var seriesType = seriesModel.subType;
  var isBaseAxis = seriesModel.getBaseAxis() === axis;
  var client = clientsForLookup.get(makeClientLookupKey(seriesType, isBaseAxis, coordSysType)) || clientsForLookup.get(makeClientLookupKey(seriesType, isBaseAxis, null));
  if (!client) {
    return;
  }
  var keyed = ecFullUpdateCache.keyed || (ecFullUpdateCache.keyed = createHashMap());
  var keys = ecFullUpdateCache.keys || (ecFullUpdateCache.keys = createHashMap());
  var axisStatKey = client.key;
  var perKey = keyed.get(axisStatKey) || keyed.set(axisStatKey, createHashMap());
  var perKeyPerAxis = perKey.get(axisModelUid);
  if (!perKeyPerAxis) {
    perKeyPerAxis = perKey.set(axisModelUid, {
      axis: axis,
      sers: [],
      serByIdx: []
    });
    // They should only be executed for each <key, axis> pair once:
    perKeyPerAxis.metrics = client.getMetrics(axis);
    (keys.get(axisModelUid) || keys.set(axisModelUid, [])).push(axisStatKey);
  }
  // series order should respect to the input order.
  perKeyPerAxis.sers.push(seriesModel);
  perKeyPerAxis.serByIdx[seriesModel.seriesIndex] = seriesModel;
}
/**
 * NOTE: Currently, the scenario is simple enough to look up clients by hash map.
 * Otherwise, a caller-provided `filter` may be an alternative if more complex requirements arise.
 */
function makeClientLookupKey(seriesType, isBaseAxis, coordSysType) {
  return seriesType + AXIS_STAT_KEY_DELIMITER + retrieve2(isBaseAxis, true) + AXIS_STAT_KEY_DELIMITER + (coordSysType || '');
}
/**
 * NOTICE: Can only be called in "install" stage.
 *
 * See `axisSnippets.ts` for some commonly used clients.
 */
export function requireAxisStatistics(registers, client) {
  var clientKey = makeClientLookupKey(client.seriesType, client.baseAxis, client.coordSysType);
  if (process.env.NODE_ENV !== 'production') {
    assert(client.seriesType && client.key && !clientsForCheckingStatKey.get(client.key) && !clientsForLookup.get(clientKey)); // More checking is performed in `axSerPairCheck`.
    clientsForCheckingStatKey.set(client.key, 1);
  }
  clientsForLookup.set(clientKey, client);
  callOnlyOnce(registers, function () {
    registers.registerProcessor(registers.PRIORITY.PROCESSOR.AXIS_STATISTICS, {
      // NOTE: Theoretically, `appendData` requires `dirtyOnOverallProgress: true` here to re-calculate them.
      // But this OVERALL_STAGE_TASK is applied to all series (no `getTargetSeries` specified),
      // `dirtyOnOverallProgress: true` can cause irrelevant series (e.g., series on geo)
      // to be re-rendered when `appendData` is called, which cause `appendData` meaningless,
      // thereby not setting `dirtyOnOverallProgress: true`.
      overallReset: performAxisStatisticsOnOverallReset
    });
  });
}
var clientsForCheckingStatKey;
if (process.env.NODE_ENV !== 'production') {
  clientsForCheckingStatKey = createHashMap();
}
var clientsForLookup = createHashMap();