
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
import { __extends } from "tslib";
/**
 * Linear continuous scale
 * http://en.wikipedia.org/wiki/Level_of_measurement
 */
import Scale from './Scale.js';
import OrdinalMeta from '../data/OrdinalMeta.js';
import { isArray, map, isObject, isString } from 'zrender/lib/core/util.js';
import { mathMin, mathRound } from '../util/number.js';
import { decorateScaleMapper, enableScaleMapperFreeze, getScaleExtentForTickUnsafe, initBreakOrLinearMapper } from './scaleMapper.js';
import { ordinalScaleCreateTicks } from './helper.js';
var OrdinalScale = /** @class */function (_super) {
  __extends(OrdinalScale, _super);
  function OrdinalScale(setting) {
    var _this = _super.call(this) || this;
    _this.type = 'ordinal';
    _this.parse = OrdinalScale.parse;
    decorateScaleMapper(_this, OrdinalScale.decoratedMethods);
    var ordinalMeta = setting.ordinalMeta;
    // Caution: Should not use instanceof, consider ec-extensions using
    // import approach to get OrdinalMeta class.
    if (!ordinalMeta) {
      ordinalMeta = new OrdinalMeta({});
    }
    if (isArray(ordinalMeta)) {
      ordinalMeta = new OrdinalMeta({
        categories: map(ordinalMeta, function (item) {
          return isObject(item) ? item.value : item;
        })
      });
    }
    _this._ordinalMeta = ordinalMeta;
    // Create an interval LinearScaleMapper, and decorate it.
    var res = initBreakOrLinearMapper(null, null,
    // Do not support break in OrdinalScale yet.
    setting.extent || [0, ordinalMeta.categories.length - 1]);
    _this._mapper = res.mapper;
    enableScaleMapperFreeze(_this, res.mapper);
    return _this;
  }
  OrdinalScale.parse = function (val) {
    // Caution: Math.round(null) will return `0` rather than `NaN`
    if (val == null) {
      val = NaN;
    } else if (isString(val)) {
      val = this._ordinalMeta.getOrdinal(val);
      if (val == null) {
        val = NaN;
      }
    } else {
      // The val from user input might be float.
      val = mathRound(val);
    }
    return val;
  };
  /**
   * PENDING: currently this method is not used.
   * `makeCategoryTicks` is effectively used.
   */
  OrdinalScale.prototype.getTicks = function () {
    var ticks = [];
    ordinalScaleCreateTicks(this, 0, function (tick) {
      ticks.push(tick);
    });
    return ticks;
  };
  OrdinalScale.prototype.getMinorTicks = function (splitNumber) {
    // Not support.
    return;
  };
  /**
   * @see `Ordinal['_ordinalNumbersByTick']`
   */
  OrdinalScale.prototype.setSortInfo = function (info) {
    if (info == null) {
      this._ordinalNumbersByTick = this._ticksByOrdinalNumber = null;
      return;
    }
    var infoOrdinalNumbers = info.ordinalNumbers;
    var ordinalsByTick = this._ordinalNumbersByTick = [];
    var ticksByOrdinal = this._ticksByOrdinalNumber = [];
    // Unnecessary support negative tick in `realtimeSort`.
    var tickNum = 0;
    var allCategoryLen = this._ordinalMeta.categories.length;
    for (var len = mathMin(allCategoryLen, infoOrdinalNumbers.length); tickNum < len; ++tickNum) {
      var ordinalNumber = ordinalsByTick[tickNum] = infoOrdinalNumbers[tickNum];
      ticksByOrdinal[ordinalNumber] = tickNum;
    }
    // Handle that `series.data` only covers part of the `axis.category.data`.
    var unusedOrdinal = 0;
    for (; tickNum < allCategoryLen; ++tickNum) {
      while (ticksByOrdinal[unusedOrdinal] != null) {
        unusedOrdinal++;
      }
      ;
      ordinalsByTick[tickNum] = unusedOrdinal;
      ticksByOrdinal[unusedOrdinal] = tickNum;
    }
  };
  OrdinalScale.prototype._getTickNumber = function (ordinal) {
    var ticksByOrdinalNumber = this._ticksByOrdinalNumber;
    // also support ordinal out of range of `ordinalMeta.categories.length`,
    // where ordinal numbers are used as tick value directly.
    return ticksByOrdinalNumber && ordinal >= 0 && ordinal < ticksByOrdinalNumber.length ? ticksByOrdinalNumber[ordinal] : ordinal;
  };
  /**
   * @usage
   * ```js
   * const ordinalNumber = ordinalScale.getRawOrdinalNumber(tick.value);
   * // case0
   * const rawOrdinalValue = axisModel.getCategories()[ordinalNumber];
   * // case1
   * const rawOrdinalValue = this._ordinalMeta.categories[ordinalNumber];
   * // case2
   * const coord = axis.dataToCoord(ordinalNumber);
   * ```
   *
   * value may be out of range, e.g., when axis max is larger than `ordinalMeta.categories.length`,
   * where ordinal numbers are used as tick value directly.
   */
  OrdinalScale.prototype.getRawOrdinalNumber = function (tickValue) {
    var ordinalNumbersByTick = this._ordinalNumbersByTick;
    return ordinalNumbersByTick && tickValue >= 0 && tickValue < ordinalNumbersByTick.length ? ordinalNumbersByTick[tickValue] : tickValue;
  };
  /**
   * Get item on tick
   */
  OrdinalScale.prototype.getLabel = function (tick) {
    if (!this.isBlank()) {
      var ordinalNumber = this.getRawOrdinalNumber(tick.value);
      var category = this._ordinalMeta.categories[ordinalNumber];
      // Note that if no data, ordinalMeta.categories is an empty array.
      // Return empty if it's not exist.
      return category == null ? '' : category + '';
    }
  };
  /**
   * NOTICE: This is different from `.getOrdinalMeta().length` when extent
   * is specified by `xxxAxis.min/max` or by `dataZoom`.
   */
  OrdinalScale.prototype.count = function () {
    var extent = getScaleExtentForTickUnsafe(this._mapper);
    return extent[1] - extent[0] + 1;
  };
  OrdinalScale.prototype.getOrdinalMeta = function () {
    return this._ordinalMeta;
  };
  OrdinalScale.type = 'ordinal';
  OrdinalScale.decoratedMethods = {
    needTransform: function () {
      return this._mapper.needTransform();
    },
    contain: function (val) {
      return this._mapper.contain(this._getTickNumber(val)) && val >= 0 && val < this._ordinalMeta.categories.length;
    },
    normalize: function (val) {
      return this._mapper.normalize(this._getTickNumber(val));
    },
    scale: function (val) {
      return this.getRawOrdinalNumber(mathRound(this._mapper.scale(val)));
    },
    transformIn: function (val, opt) {
      return this._mapper.transformIn(this._getTickNumber(val), opt);
    },
    transformOut: function (val, opt) {
      return this.getRawOrdinalNumber(this._mapper.transformOut(val, opt));
    },
    getExtent: function () {
      return this._mapper.getExtent();
    },
    getExtentUnsafe: function (kind, depth) {
      return this._mapper.getExtentUnsafe(kind, depth);
    },
    /**
     * NOTICE: OrdinalScale extent should always originates from
     * `[0, ordinalMeta.categories.length - 1]`, regardless of min/max of `series.data`.
     * But settings like `xxxAxis.min/max` can still modify the extent.
     * It is handled by constructor of `ScaleRawExtentInfo`.
     */
    setExtent: function (start, end) {
      return this._mapper.setExtent(start, end);
    },
    setExtent2: function (kind, start, end) {
      return this._mapper.setExtent2(kind, start, end);
    }
  };
  return OrdinalScale;
}(Scale);
Scale.registerClass(OrdinalScale);
export default OrdinalScale;