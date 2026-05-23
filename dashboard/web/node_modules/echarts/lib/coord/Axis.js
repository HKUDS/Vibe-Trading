
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
import { each, map } from 'zrender/lib/core/util.js';
import { linearMap } from '../util/number.js';
import { createAxisTicks, createAxisLabels, calculateCategoryInterval, AxisTickLabelComputingKind, createAxisLabelsComputingContext } from './axisTickLabelBuilder.js';
import { isOrdinalScale } from '../scale/helper.js';
import { calcBandWidth } from './axisBand.js';
import { getTickValueOutermost } from './axisHelper.js';
var NORMALIZED_EXTENT = [0, 1];
/**
 * Base class of Axis.
 *
 * Lifetime: recreate for each main process.
 * [NOTICE]: Some caches is stored on the axis instance (e.g., `axisTickLabelBuilder.ts`, `scaleRawExtentInfo.ts`),
 *  which is based on this lifetime.
 */
var Axis = /** @class */function () {
  function Axis(dim, scale, extent) {
    // NOTICE: Must ensure `true` is only available on 'category' axis.
    this.onBand = false;
    // Make sure that `extent[0] > extent[1]` only if `inverse: true`.
    // `inverse` can be inferred by `extent` unless `extent[0] === extent[1]`.
    this.inverse = false;
    this.dim = dim;
    this.scale = scale;
    this._extent = extent || [0, 0];
  }
  /**
   * If axis extent contain given coord
   */
  Axis.prototype.contain = function (coord) {
    var extent = this._extent;
    var min = Math.min(extent[0], extent[1]);
    var max = Math.max(extent[0], extent[1]);
    return coord >= min && coord <= max;
  };
  /**
   * If axis extent contain given data
   */
  Axis.prototype.containData = function (data) {
    return this.scale.contain(this.scale.parse(data));
  };
  /**
   * Get coord extent.
   */
  Axis.prototype.getExtent = function () {
    return this._extent.slice();
  };
  /**
   * Set coord extent
   */
  Axis.prototype.setExtent = function (start, end) {
    var extent = this._extent;
    extent[0] = start;
    extent[1] = end;
  };
  /**
   * Convert data to coord. Data is the rank if it has an ordinal scale
   */
  Axis.prototype.dataToCoord = function (data, clamp) {
    var scale = this.scale;
    data = scale.normalize(scale.parse(data));
    return linearMap(data, NORMALIZED_EXTENT, makeExtentWithBands(this), clamp);
  };
  /**
   * Convert coord to data. Data is the rank if it has an ordinal scale
   */
  Axis.prototype.coordToData = function (coord, clamp) {
    var t = linearMap(coord, makeExtentWithBands(this), NORMALIZED_EXTENT, clamp);
    return this.scale.scale(t);
  };
  /**
   * Convert pixel point to data in axis
   */
  Axis.prototype.pointToData = function (point, clamp) {
    // Should be implemented in derived class if necessary.
    return;
  };
  /**
   * Different from `zrUtil.map(axis.getTicks(), axis.dataToCoord, axis)`,
   * `axis.getTicksCoords` considers `onBand`, which is used by
   * `boundaryGap:true` of category axis and splitLine and splitArea.
   * @param opt.tickModel default: axis.model.getModel('axisTick')
   */
  Axis.prototype.getTicksCoords = function (opt) {
    opt = opt || {};
    var tickModel = opt.tickModel || this.getTickModel();
    var result = createAxisTicks(this, tickModel, {
      breakTicks: opt.breakTicks,
      pruneByBreak: opt.pruneByBreak
    });
    var preTicksCoords = map(result.ticks, function (tick) {
      return {
        coord: this.dataToCoord(getTickValueOutermost(this.scale, tick)),
        tick: tick
      };
    }, this);
    var alignWithLabel = tickModel.get('alignWithLabel');
    var onBandModified = fixOnBandTicksCoords(this, preTicksCoords, alignWithLabel);
    return map(preTicksCoords, function (item) {
      return {
        coord: item.coord,
        tickValue: item.tick.value,
        onBand: onBandModified
      };
    });
  };
  Axis.prototype.getMinorTicksCoords = function () {
    if (isOrdinalScale(this.scale)) {
      // Category axis doesn't support minor ticks
      return [];
    }
    var minorTickModel = this.model.getModel('minorTick');
    var splitNumber = minorTickModel.get('splitNumber');
    // Protection.
    if (!(splitNumber > 0 && splitNumber < 100)) {
      splitNumber = 5;
    }
    var minorTicks = this.scale.getMinorTicks(splitNumber);
    var minorTicksCoords = map(minorTicks, function (minorTicksGroup) {
      return map(minorTicksGroup, function (minorTick) {
        return {
          coord: this.dataToCoord(minorTick),
          tickValue: minorTick
        };
      }, this);
    }, this);
    return minorTicksCoords;
  };
  Axis.prototype.getViewLabels = function (ctx) {
    ctx = ctx || createAxisLabelsComputingContext(AxisTickLabelComputingKind.determine);
    return createAxisLabels(this, ctx).labels;
  };
  Axis.prototype.getLabelModel = function () {
    return this.model.getModel('axisLabel');
  };
  /**
   * Notice here we only get the default tick model. For splitLine
   * or splitArea, we should pass the splitLineModel or splitAreaModel
   * manually when calling `getTicksCoords`.
   * In GL, this method may be overridden to:
   * `axisModel.getModel('axisTick', grid3DModel.getModel('axisTick'));`
   */
  Axis.prototype.getTickModel = function () {
    return this.model.getModel('axisTick');
  };
  /**
   * @deprecated Use `calcBandWidth` instead.
   */
  Axis.prototype.getBandWidth = function () {
    return calcBandWidth(this, {
      min: 1
    }).w;
    // NOTICE: Do not add logic here. Implement everthing in `calcBandWidth`.
  };
  /**
   * Only be called in category axis.
   * Can be overridden, consider other axes like in 3D.
   * @return Auto interval for category axis tick and label
   */
  Axis.prototype.calculateCategoryInterval = function (ctx) {
    ctx = ctx || createAxisLabelsComputingContext(AxisTickLabelComputingKind.determine);
    return calculateCategoryInterval(this, ctx);
  };
  return Axis;
}();
function makeExtentWithBands(axis) {
  var extent = axis.getExtent();
  if (axis.onBand) {
    var size = extent[1] - extent[0];
    var margin = size / axis.scale.count() / 2;
    extent[0] += margin;
    extent[1] -= margin;
  }
  return extent;
}
/**
 * `axis.onBand: true` (i.e., `boundaryGap: true` in ec option) and `CategoryTickLabelSplitIntervalOption`
 *  affects `axisTick`/`axisLabel`/`splitLine`/`splitArea`.
 *
 * Currently, the visual result is best only when `axisTick/splitLine/splitArea.interval === 0`.
 * The typical case is:
 *      |---|---|---|     <= This is the input `preTicksCoords`
 *      0   1   2   3        (having been added half band width by `makeExtentWithBands`).
 *    |---|---|---|---|  <= This is the result.
 *      0   1   2   3
 *
 * When `interval > 0`, the visual result may be odd for `axisLabel` and `customValues`, but acceptable
 * for `axisTick` `splitLine` and `splitArea`:
 *      |---~---|---~---~---|---|    <= This is the input `preTicksCoords`; `interval: 2; min: 1; max: 7`.
 *      ₁   ₂   3   ₄   ₅   6   ₇       Subscript numbers (`₀`, `₁`, `₃`) indicate axis labels are hidden
 *                                      (by default settings) due to off-interval.
 *                                      A tilde (`~`) indicates a tick ignored due to off-interval.
 *    |---~---|---~---~---|---~---|  <= This is the result.
 *      ₁   ₂   3   ₄   ₅   6   ₇
 *
 * NOTE:
 *  - A inappropriate result may cause misleading (e.g., split 2 bars of a single data item when there
 *    are two bar series).
 *  - See also #11176 #11186 .
 * PENDING:
 *  - The show/hide of `axisLabel` may be optimized when `interval > 1 and be an even number`,
 *    but that may introduce complex and still not perfect in odd number, and may not necessary if
 *    `axisTick: {show: false}` and `axisLabel` can auto hidden when overlapping.
 */
function fixOnBandTicksCoords(axis, preTicksCoords, alignWithLabel) {
  var ticksLen = preTicksCoords.length;
  if (!axis.onBand || alignWithLabel || !ticksLen) {
    return false;
  }
  // Assume:
  //  - If `onBand: true`, `bandWidth` has been calculated by `ticksLen + 1` rather than `ticksLen`.
  //  - If `interval > 0`, some ticks may be ignored, but `ticksCoords` has always included boundary
  //    ticks of axis extent, and be `offInterval: true` if off-interval.
  //  - No need to consider breaks, since axis break is not supported in category axis.
  var bandWidth = calcBandWidth(axis).w;
  if (!bandWidth) {
    return false;
  }
  each(preTicksCoords, function (ticksItem) {
    ticksItem.coord -= bandWidth / 2;
  });
  var dataExtent = axis.scale.getExtent();
  var oldLast = preTicksCoords[ticksLen - 1];
  if (oldLast.tick.offInterval) {
    preTicksCoords.pop();
  }
  preTicksCoords.push({
    coord: oldLast.coord + bandWidth,
    tick: {
      value: dataExtent[1] + 1
    }
  });
  return true;
}
export default Axis;