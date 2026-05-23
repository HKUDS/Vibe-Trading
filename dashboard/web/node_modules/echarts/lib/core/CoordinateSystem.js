
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
import { SINGLE_REFERRING } from '../util/model.js';
import { error } from '../util/log.js';
/**
 * FIXME:
 * `nonSeriesBoxCoordSysCreators` and `_nonSeriesBoxMasterList` are hardcoded implementations.
 * Regarding "coord sys layout based on another coord sys", currently we only experimentally support one level
 * dependency, such as, "grid(cartesian)s can be laid out based on matrix/calendar coord sys."
 * But a comprehensive implementation may need to support:
 *  - Recursive dependencies. e.g., a matrix coord sys lays out based on another matrix coord sys.
 *    That requires in the implementation `create` and `update` of coord sys are called by a dependency graph.
 *    (@see enableTopologicalTravel in `util/component.ts`)
 */
var nonSeriesBoxCoordSysCreators = {};
var normalCoordSysCreators = {};
var CoordinateSystemManager = /** @class */function () {
  function CoordinateSystemManager() {
    this._normalMasterList = [];
    this._nonSeriesBoxMasterList = [];
  }
  /**
   * Typically,
   *  - in `create`, a coord sys lays out based on a given rect;
   *  - in `update`, update the pixel and data extent of there axes (if any) based on processed `series.data`.
   * After that, a coord sys can serve (typically by `dataToPoint`/`dataToLayout`/`pointToData`).
   * If the coordinate system do not lay out based on `series.data`, `update` is not needed.
   */
  CoordinateSystemManager.prototype.create = function (ecModel, api) {
    this._nonSeriesBoxMasterList = dealCreate(nonSeriesBoxCoordSysCreators, true);
    this._normalMasterList = dealCreate(normalCoordSysCreators, false);
    function dealCreate(creatorMap, canBeNonSeriesBox) {
      var coordinateSystems = [];
      zrUtil.each(creatorMap, function (creator, type) {
        var list = creator.create(ecModel, api);
        coordinateSystems = coordinateSystems.concat(list || []);
        if (process.env.NODE_ENV !== 'production') {
          if (canBeNonSeriesBox) {
            // Disallow `update` is a brutal way to ensure `_nonSeriesBoxMasterList`s are ready to
            // serve after `create`. But if `update` has to be involved in `_nonSeriesBoxMasterList`
            // for some future case, more complicated mechanisms need to be introduced.
            zrUtil.each(list, function (master) {
              return zrUtil.assert(!master.update);
            });
          }
        }
      });
      return coordinateSystems;
    }
  };
  /**
   * @see CoordinateSystem['create']
   */
  CoordinateSystemManager.prototype.update = function (ecModel, api) {
    zrUtil.each(this._normalMasterList, function (coordSys) {
      coordSys.update && coordSys.update(ecModel, api);
    });
  };
  CoordinateSystemManager.prototype.getCoordinateSystems = function () {
    return this._normalMasterList.concat(this._nonSeriesBoxMasterList);
  };
  CoordinateSystemManager.register = function (type, creator) {
    if (type === 'matrix' || type === 'calendar') {
      // FIXME: hardcode, @see nonSeriesBoxCoordSysCreators
      nonSeriesBoxCoordSysCreators[type] = creator;
      return;
    }
    normalCoordSysCreators[type] = creator;
  };
  CoordinateSystemManager.get = function (type) {
    return normalCoordSysCreators[type] || nonSeriesBoxCoordSysCreators[type];
  };
  return CoordinateSystemManager;
}();
function canBeNonSeriesBoxCoordSys(coordSysType) {
  return !!nonSeriesBoxCoordSysCreators[coordSysType];
}
// By default fetch coord from `model.get('coord')`.
export var BOX_COORD_SYS_COORD_FROM_PROP_COORD = 1;
// Some model/series, such as pie, is allowed to also get coord from `model.get('center')`,
// if cannot get from `model.get('coord')`. But historically pie use `center` option, but
// geo use `layoutCenter` option to specify layout center; they are not able to be unified.
// Therefor it is not recommended.
export var BOX_COORD_SYS_COORD_FROM_PROP_COORD2 = 2;
/**
 * @see_also `createBoxLayoutReference`
 * @see_also `injectCoordSysByOption`
 */
export function registerLayOutOnCoordSysUsage(opt) {
  if (process.env.NODE_ENV !== 'production') {
    zrUtil.assert(!coordSysUseMap.get(opt.fullType));
  }
  coordSysUseMap.set(opt.fullType, {
    getCoord2: undefined
  }).getCoord2 = opt.getCoord2;
}
var coordSysUseMap = zrUtil.createHashMap();
/**
 * @return Be an object, but never be NullUndefined.
 */
export function getCoordForCoordSysUsageKindBox(model) {
  var coord = model.getShallow('coord', true);
  var from = BOX_COORD_SYS_COORD_FROM_PROP_COORD;
  if (coord == null) {
    var store = coordSysUseMap.get(model.type);
    if (store && store.getCoord2) {
      from = BOX_COORD_SYS_COORD_FROM_PROP_COORD2;
      coord = store.getCoord2(model);
    }
  }
  return {
    coord: coord,
    from: from
  };
}
/**
 * - `COORD_SYS_USAGE_KIND_DATA`: each data item is laid out based on a coord sys.
 * - `COORD_SYS_USAGE_KIND_BOX`: the overall bounding rect or anchor point is calculated based on a coord sys.
 *   e.g.,
 *      grid rect (cartesian rect) is calculate based on matrix/calendar coord sys;
 *      pie center is calculated based on calendar/cartesian;
 *
 * The default value (if not declared in option `coordinateSystemUsage`):
 *  For series, use `COORD_SYS_USAGE_KIND_DATA`, since this is the most common case and backward compatible.
 *  For non-series components, use `COORD_SYS_USAGE_KIND_BOX`, since `COORD_SYS_USAGE_KIND_DATA` is not applicable.
 */
export var COORD_SYS_USAGE_KIND_NONE = 0;
export var COORD_SYS_USAGE_KIND_DATA = 1;
export var COORD_SYS_USAGE_KIND_BOX = 2;
export function decideCoordSysUsageKind(
// Component or series
model, printError) {
  // For backward compat, still not use `true` in model.get.
  var coordSysType = model.getShallow('coordinateSystem');
  var coordSysUsageOption = model.getShallow('coordinateSystemUsage', true);
  var isDeclaredExplicitly = coordSysUsageOption != null;
  var kind = COORD_SYS_USAGE_KIND_NONE;
  if (coordSysType) {
    var isSeries = model.mainType === 'series';
    if (coordSysUsageOption == null) {
      coordSysUsageOption = isSeries ? 'data' : 'box';
    }
    if (coordSysUsageOption === 'data') {
      kind = COORD_SYS_USAGE_KIND_DATA;
      if (!isSeries) {
        if (process.env.NODE_ENV !== 'production') {
          if (isDeclaredExplicitly && printError) {
            error('coordinateSystemUsage "data" is not supported in non-series components.');
          }
        }
        kind = COORD_SYS_USAGE_KIND_NONE;
      }
    } else if (coordSysUsageOption === 'box') {
      kind = COORD_SYS_USAGE_KIND_BOX;
      if (!isSeries && !canBeNonSeriesBoxCoordSys(coordSysType)) {
        if (process.env.NODE_ENV !== 'production') {
          if (isDeclaredExplicitly && printError) {
            error("coordinateSystem \"" + coordSysType + "\" cannot be used" + (" as coordinateSystemUsage \"box\" for \"" + model.type + "\" yet."));
          }
        }
        kind = COORD_SYS_USAGE_KIND_NONE;
      }
    }
  }
  return {
    coordSysType: coordSysType,
    kind: kind
  };
}
/**
 * These cases are considered:
 *  (A) Most series can use only "COORD_SYS_USAGE_KIND_DATA", but "COORD_SYS_USAGE_KIND_BOX" is not applicable:
 *    - e.g., series.heatmap, series.line, series.bar, series.scatter, ...
 *  (B) Some series and most components can use only "COORD_SYS_USAGE_KIND_BOX", but "COORD_SYS_USAGE_KIND_DATA"
 *    is not applicable:
 *    - e.g., series.pie, series.funnel, ...
 *    - e.g., grid, polar, geo, title, ...
 *  (C) Several series can use both "COORD_SYS_USAGE_KIND_BOX" and "COORD_SYS_USAGE_KIND_DATA", even at the same time:
 *    - e.g., series.graph, series.map
 *      - If graph or map series use "COORD_SYS_USAGE_KIND_BOX", it creates a internal coord sys as
 *        "COORD_SYS_USAGE_KIND_DATA" to lay out its data.
 *      - Graph series can use matrix coord sys as either the "COORD_SYS_USAGE_KIND_DATA" (each item layout
 *        on one cell) or "COORD_SYS_USAGE_KIND_BOX" (the entire series are layout within one cell).
 *    - To achieve this effect,
 *      `series.coordinateSystemUsage: 'box'` needs to be specified explicitly.
 *
 * Check these echarts option settings:
 *  - If `series: {type: 'bar'}`:
 *      COORD_SYS_USAGE_KIND_DATA: "cartesian2d",
 *      COORD_SYS_USAGE_KIND_BOX: "none".
 *      (since `coordinateSystem: 'cartesian2d'` is the default option in bar.)
 *  - If `grid: {coordinateSystem: 'matrix'}`
 *      COORD_SYS_USAGE_KIND_DATA: "none",
 *      COORD_SYS_USAGE_KIND_BOX: "matrix".
 *  - If `series: {type: 'pie', coordinateSystem: 'matrix'}`:
 *      COORD_SYS_USAGE_KIND_DATA: "none",
 *      COORD_SYS_USAGE_KIND_BOX: "matrix".
 *      (since `coordinateSystemUsage: 'box'` is the default option in pie.)
 *  - If `series: {type: 'graph', coordinateSystem: 'matrix'}`:
 *      COORD_SYS_USAGE_KIND_DATA: "matrix",
 *      COORD_SYS_USAGE_KIND_BOX: "none"
 *  - If `series: {type: 'graph', coordinateSystem: 'matrix', coordinateSystemUsage: 'box'}`:
 *      COORD_SYS_USAGE_KIND_DATA: "an internal view",
 *      COORD_SYS_USAGE_KIND_BOX: "the internal view is laid out on a matrix"
 *  - If `series: {type: 'map'}`:
 *      COORD_SYS_USAGE_KIND_DATA: "a internal geo",
 *      COORD_SYS_USAGE_KIND_BOX: "none"
 *  - If `series: {type: 'map', coordinateSystem: 'geo', geoIndex: 0}`:
 *      COORD_SYS_USAGE_KIND_DATA: "a geo",
 *      COORD_SYS_USAGE_KIND_BOX: "none"
 *  - If `series: {type: 'map', coordinateSystem: 'matrix'}`:
 *      not_applicable
 *  - If `series: {type: 'map', coordinateSystem: 'matrix', coordinateSystemUsage: 'box'}`:
 *      COORD_SYS_USAGE_KIND_DATA: "an internal geo",
 *      COORD_SYS_USAGE_KIND_BOX: "the internal geo is laid out on a matrix"
 *
 * @usage
 * For case (A) & (B),
 *  call `injectCoordSysByOption({coordSysType: 'aaa', ...})` once for each series/components.
 * For case (C),
 *  call `injectCoordSysByOption({coordSysType: 'aaa', ...})` once for each series/components,
 *  and then call `injectCoordSysByOption({coordSysType: 'bbb', ..., isDefaultDataCoordSys: true})`
 *  once for each series/components.
 */
export function injectCoordSysByOption(opt) {
  var targetModel = opt.targetModel,
    coordSysType = opt.coordSysType,
    coordSysProvider = opt.coordSysProvider,
    isDefaultDataCoordSys = opt.isDefaultDataCoordSys,
    allowNotFound = opt.allowNotFound;
  if (process.env.NODE_ENV !== 'production') {
    zrUtil.assert(!!coordSysType);
  }
  var _a = decideCoordSysUsageKind(targetModel, true),
    kind = _a.kind,
    declaredType = _a.coordSysType;
  if (isDefaultDataCoordSys && kind !== COORD_SYS_USAGE_KIND_DATA) {
    // If both `COORD_SYS_USAGE_KIND_DATA` and `COORD_SYS_USAGE_KIND_BOX` declared in one model.
    // There is the only case in series-graph, and no other cases yet.
    kind = COORD_SYS_USAGE_KIND_DATA;
    declaredType = coordSysType;
  }
  if (kind === COORD_SYS_USAGE_KIND_NONE || declaredType !== coordSysType) {
    return COORD_SYS_USAGE_KIND_NONE;
  }
  var coordSys = coordSysProvider(coordSysType, targetModel);
  if (!coordSys) {
    if (process.env.NODE_ENV !== 'production') {
      if (!allowNotFound) {
        error(coordSysType + " cannot be found for" + (" " + targetModel.type + " (index: " + targetModel.componentIndex + ")."));
      }
    }
    return COORD_SYS_USAGE_KIND_NONE;
  }
  if (kind === COORD_SYS_USAGE_KIND_DATA) {
    if (process.env.NODE_ENV !== 'production') {
      zrUtil.assert(targetModel.mainType === 'series');
    }
    targetModel.coordinateSystem = coordSys;
  } else {
    // kind === COORD_SYS_USAGE_KIND_BOX
    targetModel.boxCoordinateSystem = coordSys;
  }
  return kind;
}
export var simpleCoordSysInjectionProvider = function (coordSysType, injectTargetModel) {
  var coordSysModel = injectTargetModel.getReferringComponents(coordSysType, SINGLE_REFERRING).models[0];
  return coordSysModel && coordSysModel.coordinateSystem;
};
export default CoordinateSystemManager;